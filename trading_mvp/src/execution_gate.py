from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from costs import CostProfile, base_api_cost_profile, route_legs

BANDS_BPS = (25, 50, 100)
DEPTH_SHARE_CAP = 0.20      # не более 20% глубины полосы ±50bps
DAILY_VOLUME_CAP = 0.005    # не более 0.5% суточного оборота
STRESS_FUNDING_HAIRCUT = 0.5
DEFAULT_CANDIDATES = "BEAT_USDT,SKYAI_USDT,BAS_USDT,M_USDT,EVAA_USDT,B_USDT,US_USDT,RAVE_USDT,BROCCOLIF3B_USDT"
AUTO_MIN_LEG_PCT = 20.0
AUTO_MIN_CONS = 0.75
AUTO_MIN_SPREAD_PCT = 15.0


def select_candidates(
    pairs: list[dict[str, Any]],
    max_e: int = 8,
    max_g: int = 6,
    min_leg_pct: float = AUTO_MIN_LEG_PCT,
    min_cons: float = AUTO_MIN_CONS,
    min_spread_pct: float = AUTO_MIN_SPREAD_PCT,
) -> list[str]:
    """Динамический watchlist из свежего pairs-отчёта: E-ноги + стабильные G-спреды."""
    e_scored: list[tuple[float, str]] = []
    g_scored: list[tuple[float, str]] = []
    for pair in pairs:
        symbol = str(pair.get("symbol") or "")
        if not symbol:
            continue
        leg = (pair.get("leg_annualized_pct") or {}).get("mexc")
        if pair.get("mexc_spot_available") and leg is not None and leg >= min_leg_pct:
            e_scored.append((float(leg), symbol))
        spread = pair.get("spread_gate_minus_mexc") or {}
        abs_spread = spread.get("abs_annualized_spread_pct")
        cons = spread.get("sign_consistency")
        if (
            abs_spread is not None
            and cons is not None
            and float(abs_spread) >= min_spread_pct
            and float(cons) >= min_cons
        ):
            g_scored.append((float(abs_spread), symbol))
    e_scored.sort(reverse=True)
    g_scored.sort(reverse=True)
    selected: list[str] = []
    for _, symbol in e_scored[:max_e] + g_scored[:max_g]:
        if symbol not in selected:
            selected.append(symbol)
    return selected


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> Any:
    response = session.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def normalize_mexc_spot(payload: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = [(float(p), float(q)) for p, q in payload.get("bids") or []]
    asks = [(float(p), float(q)) for p, q in payload.get("asks") or []]
    return bids, asks


def normalize_mexc_perp(payload: dict[str, Any], contract_size: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    data = payload.get("data") or payload
    bids = [(float(row[0]), float(row[1]) * contract_size) for row in data.get("bids") or []]
    asks = [(float(row[0]), float(row[1]) * contract_size) for row in data.get("asks") or []]
    return bids, asks


def normalize_gate_perp(payload: dict[str, Any], multiplier: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = [(float(row["p"]), float(row["s"]) * multiplier) for row in payload.get("bids") or []]
    asks = [(float(row["p"]), float(row["s"]) * multiplier) for row in payload.get("asks") or []]
    return bids, asks


def book_stats(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> dict[str, Any] | None:
    if not bids or not asks:
        return None
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return None
    mid = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / mid * 1e4
    depth: dict[str, dict[str, float]] = {}
    for band in BANDS_BPS:
        low = mid * (1 - band / 1e4)
        high = mid * (1 + band / 1e4)
        bid_quote = sum(p * q for p, q in bids if p >= low)
        ask_quote = sum(p * q for p, q in asks if p <= high)
        depth[f"band_{band}bps"] = {
            "bid_quote_usd": round(bid_quote, 2),
            "ask_quote_usd": round(ask_quote, 2),
        }
    return {"mid": mid, "spread_bps": round(spread_bps, 3), "depth": depth}


def position_capacity_usd(stats: dict[str, Any] | None, volume_24h_quote: float) -> float:
    if stats is None:
        return 0.0
    band = stats["depth"].get("band_50bps") or {}
    depth_side = min(band.get("bid_quote_usd", 0.0), band.get("ask_quote_usd", 0.0))
    return round(min(DEPTH_SHARE_CAP * depth_side, DAILY_VOLUME_CAP * volume_24h_quote), 2)


def market_impact_bps(
    levels: list[tuple[float, float]],
    *,
    side: str,
    notional_quote: float,
) -> float | None:
    """VWAP impact relative to best price, excluding the bid/ask spread."""
    if not levels or notional_quote <= 0.0 or side not in {"buy", "sell"}:
        return None
    ordered = sorted(levels, key=lambda row: row[0], reverse=side == "sell")
    best = ordered[0][0]
    remaining = float(notional_quote)
    filled_base = 0.0
    filled_quote = 0.0
    for price, quantity in ordered:
        if price <= 0.0 or quantity <= 0.0:
            continue
        take_base = min(quantity, remaining / price)
        take_quote = take_base * price
        filled_base += take_base
        filled_quote += take_quote
        remaining -= take_quote
        if remaining <= 1e-9:
            break
    if remaining > max(1e-6, notional_quote * 1e-9) or filled_base <= 0.0:
        return None
    vwap = filled_quote / filled_base
    impact = (vwap / best - 1.0) if side == "buy" else (1.0 - vwap / best)
    return round(max(impact, 0.0) * 1e4, 6)


def capacity_within_impact_bps(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    *,
    max_impact_bps: float = 10.0,
    depth_share_cap: float = DEPTH_SHARE_CAP,
) -> float:
    if not bids or not asks or max_impact_bps < 0.0:
        return 0.0
    best_bid = max(price for price, _ in bids)
    best_ask = min(price for price, _ in asks)
    bid_floor = best_bid * (1.0 - max_impact_bps / 1e4)
    ask_ceiling = best_ask * (1.0 + max_impact_bps / 1e4)
    bid_quote = sum(price * quantity for price, quantity in bids if price >= bid_floor)
    ask_quote = sum(price * quantity for price, quantity in asks if price <= ask_ceiling)
    return round(max(min(bid_quote, ask_quote) * depth_share_cap, 0.0), 2)


def carry_economics(
    leg_annual_pct: float,
    capacity_usd: float,
    perp_spread_bps: float,
    hedge_spread_bps: float,
    turnover_per_year: float = 12.0,
    *,
    route: str = "cross_venue_perp_perp",
    cost_profile: CostProfile | None = None,
    perp_impact_bps: float | None = None,
    hedge_impact_bps: float | None = None,
    stress: bool = False,
) -> dict[str, Any]:
    """Annual carry economics using the shared four-order cost model."""
    profile = cost_profile or base_api_cost_profile()
    if route == "cross_venue_perp_perp":
        legs = route_legs(
            route,
            mexc_spread_bps=perp_spread_bps,
            gate_spread_bps=hedge_spread_bps,
            mexc_impact_bps=perp_impact_bps,
            gate_impact_bps=hedge_impact_bps,
            profile=profile,
        )
    elif route == "same_venue_mexc_spot_perp":
        legs = route_legs(
            route,
            mexc_spread_bps=perp_spread_bps,
            spot_spread_bps=hedge_spread_bps,
            mexc_impact_bps=perp_impact_bps,
            spot_impact_bps=hedge_impact_bps,
            profile=profile,
        )
    else:
        raise ValueError(f"Unknown carry route: {route}")
    cycle_cost = profile.cycle_cost(legs, stress=stress)
    effective_profile = profile.stress_profile() if stress else profile
    gross_pct = abs(leg_annual_pct) * effective_profile.funding_haircut
    costs_pct = cycle_cost["total_bps"] * turnover_per_year / 100.0
    net_pct = gross_pct - costs_pct
    return {
        "gross_after_persistence_haircut_pct": round(gross_pct, 2),
        "spread_costs_annual_pct": round(
            cycle_cost["spread_bps"] * turnover_per_year / 100.0,
            2,
        ),
        "all_in_costs_annual_pct": round(costs_pct, 2),
        "cycle_cost": cycle_cost,
        "route": route,
        "net_annual_pct": round(net_pct, 2),
        "net_annual_usd_at_capacity": round(net_pct / 100 * capacity_usd, 2),
    }


def load_contract_sizes(fee_evidence_dir: Path) -> tuple[dict[str, float], dict[str, float]]:
    mexc_payload = json.loads((fee_evidence_dir / "mexc_contract_detail.json").read_text(encoding="utf-8"))
    mexc = {
        str(item.get("symbol")): float(item.get("contractSize") or 1.0)
        for item in mexc_payload.get("data") or []
    }
    gate_payload = json.loads((fee_evidence_dir / "gate_usdt_contracts.json").read_text(encoding="utf-8"))
    gate = {
        str(item.get("name")): float(item.get("quanto_multiplier") or 1.0)
        for item in gate_payload
    }
    return mexc, gate


def analyze_candidate(
    session: requests.Session,
    symbol: str,
    pair_info: dict[str, Any],
    mexc_sizes: dict[str, float],
    gate_sizes: dict[str, float],
    sleep_sec: float = 0.25,
    cost_profile: CostProfile | None = None,
) -> dict[str, Any]:
    base = symbol.replace("_USDT", "")
    profile = cost_profile or base_api_cost_profile()
    result: dict[str, Any] = {"symbol": symbol, "books": {}, "errors": []}

    try:
        payload = _get_json(session, "https://api.mexc.com/api/v3/depth", {"symbol": f"{base}USDT", "limit": 100})
        result["books"]["mexc_spot"] = book_stats(*normalize_mexc_spot(payload))
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"mexc_spot {type(exc).__name__}: {exc}")
    time.sleep(sleep_sec)

    try:
        payload = _get_json(session, f"https://contract.mexc.com/api/v1/contract/depth/{symbol}", {"limit": 100})
        result["books"]["mexc_perp"] = book_stats(*normalize_mexc_perp(payload, mexc_sizes.get(symbol, 1.0)))
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"mexc_perp {type(exc).__name__}: {exc}")
    time.sleep(sleep_sec)

    try:
        payload = _get_json(
            session,
            "https://api.gateio.ws/api/v4/futures/usdt/order_book",
            {"contract": symbol, "limit": 100},
        )
        result["books"]["gate_perp"] = book_stats(*normalize_gate_perp(payload, gate_sizes.get(symbol, 1.0)))
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"gate_perp {type(exc).__name__}: {exc}")
    time.sleep(sleep_sec)

    volume = float(pair_info.get("min_volume_24h_quote") or 0.0)
    legs = pair_info.get("leg_annualized_pct") or {}
    mexc_leg = legs.get("mexc") or 0.0

    spot = result["books"].get("mexc_spot")
    perp = result["books"].get("mexc_perp")
    if spot and perp and mexc_leg:
        capacity = min(position_capacity_usd(spot, volume), position_capacity_usd(perp, volume))
        result["e_construction_short_mexc_perp_long_mexc_spot"] = {
            "leg_annual_pct": mexc_leg,
            "capacity_usd": capacity,
            **carry_economics(
                mexc_leg,
                capacity,
                perp["spread_bps"],
                spot["spread_bps"],
                route="same_venue_mexc_spot_perp",
                cost_profile=profile,
            ),
        }

    gate = result["books"].get("gate_perp")
    spread_info = pair_info.get("spread_gate_minus_mexc") or {}
    if perp and gate and spread_info:
        capacity = min(position_capacity_usd(perp, volume), position_capacity_usd(gate, volume))
        result["g_construction_perp_perp"] = {
            "spread_annual_pct": spread_info.get("annualized_spread_pct"),
            "sign_consistency": spread_info.get("sign_consistency"),
            "capacity_usd": capacity,
            **carry_economics(
                float(spread_info.get("annualized_spread_pct") or 0.0),
                capacity,
                perp["spread_bps"],
                gate["spread_bps"],
                route="cross_venue_perp_perp",
                cost_profile=profile,
            ),
        }
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="Execution gate v1: depth/spread/capacity snapshot (research-only)")
    parser.add_argument("--pairs-json", required=True, help="Отчет funding_pairs_*.json")
    parser.add_argument("--fee-evidence-dir", required=True)
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES)
    parser.add_argument(
        "--auto-candidates",
        action="store_true",
        help="Отобрать watchlist из pairs-отчёта (E-ноги >=20%% со спотом + G-спреды >=15%% cons>=0.75)",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    pairs_payload = json.loads(Path(args.pairs_json).read_text(encoding="utf-8"))
    pairs_list = pairs_payload.get("pairs") or []
    pairs = {p["symbol"]: p for p in pairs_list}
    mexc_sizes, gate_sizes = load_contract_sizes(Path(args.fee_evidence_dir))
    session = _session()

    cost_profile = base_api_cost_profile()
    report: dict[str, Any] = {
        "schema": "execution_gate_v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pairs_source": args.pairs_json,
        "params": {
            "bands_bps": list(BANDS_BPS),
            "depth_share_cap": DEPTH_SHARE_CAP,
            "daily_volume_cap": DAILY_VOLUME_CAP,
            "stress_funding_haircut": STRESS_FUNDING_HAIRCUT,
            "turnover_per_year": 12.0,
        },
        "cost_profile": cost_profile.as_dict(),
        "caveat": "Однократный снапшот стакана: не среднее по времени. Экономика включает 4 комиссии, maker-fill/taker fallback, spread, impact, slippage и rebalance buffer.",
        "candidates": [],
    }
    if args.auto_candidates:
        candidate_symbols = select_candidates(pairs_list)
        report["params"]["auto_candidates"] = True
        print(f"auto-selected candidates: {len(candidate_symbols)}", flush=True)
    else:
        candidate_symbols = [s.strip() for s in args.candidates.split(",") if s.strip()]
    for symbol in candidate_symbols:
        info = pairs.get(symbol)
        if info is None:
            report["candidates"].append({"symbol": symbol, "errors": ["not in pairs report"]})
            continue
        item = analyze_candidate(
            session,
            symbol,
            info,
            mexc_sizes,
            gate_sizes,
            cost_profile=cost_profile,
        )
        report["candidates"].append(item)
        e_part = item.get("e_construction_short_mexc_perp_long_mexc_spot") or {}
        g_part = item.get("g_construction_perp_perp") or {}
        print(
            f"{symbol:18} E: cap=${e_part.get('capacity_usd', 0):,.0f} net={e_part.get('net_annual_pct', '-')}%/y "
            f"(${e_part.get('net_annual_usd_at_capacity', 0):,.0f})  "
            f"G: cap=${g_part.get('capacity_usd', 0):,.0f} net={g_part.get('net_annual_pct', '-')}%/y "
            f"errors={len(item.get('errors') or [])}",
            flush=True,
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else Path(args.pairs_json).parent / f"execution_gate_v1_{stamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DONE report={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
