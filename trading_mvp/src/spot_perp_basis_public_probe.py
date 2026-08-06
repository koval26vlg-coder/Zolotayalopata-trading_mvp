from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from funding import GateFundingClient, MexcFundingClient


PLAN_DECISION = "SPOT_PERP_BASIS_PUBLIC_PROBE_PLAN_READY_AWAITING_CONFIRMATION"
ACCEPTED_DECISION = "SPOT_PERP_BASIS_PUBLIC_PROBE_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET"
REJECTED_DECISION = "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE"
PRICE_EPSILON = 1e-12
MAX_USABLE_SPREAD_BPS = 100.0
MAX_ABS_FUNDING_RATE = 0.01


@dataclass(frozen=True)
class BookMetrics:
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    mid: float
    spread_bps: float
    top_depth_notional: float

    def as_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_finite_number(value: Any) -> bool:
    parsed = _as_float(value)
    return parsed is not None and math.isfinite(parsed)


def _in_range(value: Any, low: float, high: float) -> bool:
    parsed = _as_float(value)
    return parsed is not None and math.isfinite(parsed) and low <= parsed <= high


def _positive(value: Any) -> bool:
    parsed = _as_float(value)
    return parsed is not None and math.isfinite(parsed) and parsed > 0


def _get_json(session: requests.Session, url: str, params: dict[str, Any] | None, timeout_sec: int) -> Any:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=timeout_sec)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError(f"GET failed: {url}")


def _pair_values(row: Any) -> tuple[float, float] | None:
    if isinstance(row, dict):
        price = _as_float(row.get("p") or row.get("price"))
        qty = _as_float(row.get("q") or row.get("amount") or row.get("size") or row.get("s"))
    elif isinstance(row, (list, tuple)) and len(row) >= 2:
        price = _as_float(row[0])
        qty = _as_float(row[1])
    else:
        return None
    if price is None or qty is None:
        return None
    return price, qty


def extract_book_metrics(payload: Any) -> BookMetrics:
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict):
        raise ValueError("order book payload must be an object")
    bids = data.get("bids") or data.get("Bids") or []
    asks = data.get("asks") or data.get("Asks") or []
    if not bids or not asks:
        raise ValueError("order book has no top bid/ask")
    bid_pair = _pair_values(bids[0])
    ask_pair = _pair_values(asks[0])
    if bid_pair is None or ask_pair is None:
        raise ValueError("order book top bid/ask cannot be parsed")
    bid, bid_qty = bid_pair
    ask, ask_qty = ask_pair
    if not all(math.isfinite(value) for value in (bid, ask, bid_qty, ask_qty)):
        raise ValueError("order book top values must be finite")
    if bid <= 0 or ask <= 0 or bid_qty < 0 or ask_qty < 0:
        raise ValueError("invalid order book top prices")
    if ask + PRICE_EPSILON < bid:
        raise ValueError("invalid crossed order book top prices")
    if ask < bid:
        ask = bid
    mid = (bid + ask) / 2.0
    spread_bps = ((ask - bid) / mid) * 1e4 if mid else 0.0
    return BookMetrics(
        bid=bid,
        ask=ask,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        mid=mid,
        spread_bps=spread_bps,
        top_depth_notional=(bid * bid_qty) + (ask * ask_qty),
    )


def load_preflight(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_pairs_from_preflight(preflight: dict[str, Any], max_bases: int) -> list[dict[str, Any]]:
    daily = preflight.get("daily_history") or {}
    bases = list(daily.get("candidate_non_binance_bases") or [])
    symbols_by_base = daily.get("candidate_symbols_by_base") or {}
    out: list[dict[str, Any]] = []
    for base in bases:
        base_key = str(base).upper()
        symbols = symbols_by_base.get(base_key) or {}
        mexc = str(symbols.get("mexc") or f"{base_key}_USDT").upper()
        gate = str(symbols.get("gateio") or f"{base_key}_USDT").upper()
        out.append(
            {
                "base": base_key,
                "quote": "USDT",
                "mexc": {"spot_symbol": mexc.replace("_", ""), "perp_symbol": mexc},
                "gateio": {"spot_symbol": gate, "perp_symbol": gate},
            }
        )
        if len(out) >= max_bases:
            break
    return out


def build_plan_report(
    *,
    preflight_path: Path,
    output_path: Path | None,
    max_bases: int,
    min_success_bases: int,
) -> dict[str, Any]:
    preflight = load_preflight(preflight_path)
    candidates = candidate_pairs_from_preflight(preflight, max_bases=max_bases)
    return {
        "mode": "spot_perp_basis_public_probe_plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": PLAN_DECISION,
        "selected_branch": "spot_perp_basis_mean_reversion_no_funding",
        "research_only": True,
        "would_start": False,
        "confirmed_public_probe": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "strategy_accepted": False,
        "preflight_path": str(preflight_path),
        "output_path": str(output_path) if output_path else None,
        "params": {
            "max_bases": max_bases,
            "min_success_bases": min_success_bases,
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
        "probe_scope": {
            "exchanges": ["mexc", "gateio"],
            "venues": ["spot", "perp"],
            "fields": [
                "spot_mid",
                "spot_spread_bps",
                "spot_depth_top",
                "perp_mid_or_mark",
                "perp_spread_bps",
                "perp_depth_top",
                "funding_rate",
                "next_funding_ts",
            ],
            "network_calls_now": False,
        },
        "next_valid_moves": [
            "Run this same wrapper with -ConfirmedPublicProbe -UpdateGate -Json only after explicit user confirmation.",
            "If the probe accepts enough paired bases, build a visible spot/perp snapshot collect approval packet.",
            "Do not run collect/replay/grid/live/API-key/paper-forward from this report.",
        ],
        "blocked_moves": [
            "actual_collect_without_explicit_confirmation",
            "backtest_or_replay",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
        ],
    }


def _probe_mexc(session: requests.Session, candidate: dict[str, Any], depth_limit: int, timeout_sec: int) -> dict[str, Any]:
    spot_symbol = candidate["mexc"]["spot_symbol"]
    perp_symbol = candidate["mexc"]["perp_symbol"]
    spot_book = extract_book_metrics(
        _get_json(
            session,
            "https://api.mexc.com/api/v3/depth",
            {"symbol": spot_symbol, "limit": depth_limit},
            timeout_sec,
        )
    )
    funding_snapshot = MexcFundingClient(timeout_sec=timeout_sec).fetch_snapshot(perp_symbol)
    perp_book = extract_book_metrics(
        _get_json(
            session,
            f"https://contract.mexc.com/api/v1/contract/depth/{perp_symbol}",
            {"limit": depth_limit},
            timeout_sec,
        )
    )
    perp_mid = funding_snapshot.mark_price or (
        ((funding_snapshot.perp_bid or 0.0) + (funding_snapshot.perp_ask or 0.0)) / 2.0
        if funding_snapshot.perp_bid and funding_snapshot.perp_ask
        else perp_book.mid
    )
    return {
        "exchange": "mexc",
        "base": candidate["base"],
        "spot_symbol": spot_symbol,
        "perp_symbol": perp_symbol,
        "spot": spot_book.as_dict(),
        "perp": {
            "book": perp_book.as_dict(),
            "mid_or_mark": perp_mid,
            "mark_price": funding_snapshot.mark_price,
            "index_price": funding_snapshot.index_price,
            "funding_rate": funding_snapshot.funding_rate,
            "next_funding_ts": funding_snapshot.next_funding_ts,
            "funding_interval_sec": funding_snapshot.funding_interval_sec,
        },
        "ok": True,
        "error": None,
    }


def _probe_gateio(session: requests.Session, candidate: dict[str, Any], depth_limit: int, timeout_sec: int) -> dict[str, Any]:
    spot_symbol = candidate["gateio"]["spot_symbol"]
    perp_symbol = candidate["gateio"]["perp_symbol"]
    spot_book = extract_book_metrics(
        _get_json(
            session,
            "https://api.gateio.ws/api/v4/spot/order_book",
            {"currency_pair": spot_symbol, "limit": depth_limit},
            timeout_sec,
        )
    )
    funding_snapshot = GateFundingClient(timeout_sec=timeout_sec).fetch_snapshot(perp_symbol)
    perp_book = extract_book_metrics(
        _get_json(
            session,
            "https://api.gateio.ws/api/v4/futures/usdt/order_book",
            {"contract": perp_symbol, "limit": depth_limit},
            timeout_sec,
        )
    )
    perp_mid = funding_snapshot.mark_price or (
        ((funding_snapshot.perp_bid or 0.0) + (funding_snapshot.perp_ask or 0.0)) / 2.0
        if funding_snapshot.perp_bid and funding_snapshot.perp_ask
        else perp_book.mid
    )
    return {
        "exchange": "gateio",
        "base": candidate["base"],
        "spot_symbol": spot_symbol,
        "perp_symbol": perp_symbol,
        "spot": spot_book.as_dict(),
        "perp": {
            "book": perp_book.as_dict(),
            "mid_or_mark": perp_mid,
            "mark_price": funding_snapshot.mark_price,
            "index_price": funding_snapshot.index_price,
            "funding_rate": funding_snapshot.funding_rate,
            "next_funding_ts": funding_snapshot.next_funding_ts,
            "funding_interval_sec": funding_snapshot.funding_interval_sec,
        },
        "ok": True,
        "error": None,
    }


def paired_base_ok(row: dict[str, Any]) -> bool:
    venues = row.get("venues") or {}
    if not all((venues.get(exchange) or {}).get("ok") for exchange in ("mexc", "gateio")):
        return False
    for exchange in ("mexc", "gateio"):
        venue = venues[exchange]
        spot = venue.get("spot") or {}
        perp = venue.get("perp") or {}
        book = perp.get("book") or {}
        required = [
            spot.get("mid"),
            spot.get("spread_bps"),
            spot.get("top_depth_notional"),
            perp.get("mid_or_mark"),
            book.get("spread_bps"),
            book.get("top_depth_notional"),
            perp.get("funding_rate"),
            perp.get("next_funding_ts"),
        ]
        if any(value is None for value in required):
            return False
        checks = [
            _positive(spot.get("mid")),
            _in_range(spot.get("spread_bps"), 0.0, MAX_USABLE_SPREAD_BPS),
            _positive(spot.get("top_depth_notional")),
            _positive(perp.get("mid_or_mark")),
            _in_range(book.get("spread_bps"), 0.0, MAX_USABLE_SPREAD_BPS),
            _positive(book.get("top_depth_notional")),
            _in_range(perp.get("funding_rate"), -MAX_ABS_FUNDING_RATE, MAX_ABS_FUNDING_RATE),
            _positive(perp.get("next_funding_ts")),
        ]
        if not all(checks):
            return False
    return True


def summarize_probe_rows(rows: list[dict[str, Any]], min_success_bases: int) -> dict[str, Any]:
    paired_ok = [row for row in rows if row.get("paired_ok")]
    decision = ACCEPTED_DECISION if len(paired_ok) >= min_success_bases else REJECTED_DECISION
    return {
        "decision": decision,
        "probed_bases": len(rows),
        "paired_ok_bases": len(paired_ok),
        "min_success_bases": min_success_bases,
        "acceptance_passed": decision == ACCEPTED_DECISION,
        "failed_bases": [row.get("base") for row in rows if not row.get("paired_ok")],
    }


def run_public_probe(
    *,
    preflight_path: Path,
    output_path: Path | None,
    max_bases: int,
    min_success_bases: int,
    depth_limit: int,
    timeout_sec: int,
) -> dict[str, Any]:
    preflight = load_preflight(preflight_path)
    candidates = candidate_pairs_from_preflight(preflight, max_bases=max_bases)
    session = requests.Session()
    session.trust_env = False
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        venues: dict[str, Any] = {}
        for exchange, probe in (("mexc", _probe_mexc), ("gateio", _probe_gateio)):
            try:
                venues[exchange] = probe(session, candidate, depth_limit, timeout_sec)
            except Exception as exc:  # noqa: BLE001 - probe report must preserve per-symbol failures.
                venues[exchange] = {
                    "exchange": exchange,
                    "base": candidate["base"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        row = {"base": candidate["base"], "quote": "USDT", "venues": venues}
        row["paired_ok"] = paired_base_ok(row)
        rows.append(row)

    summary = summarize_probe_rows(rows, min_success_bases=min_success_bases)
    return {
        "mode": "spot_perp_basis_public_probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": summary["decision"],
        "selected_branch": "spot_perp_basis_mean_reversion_no_funding",
        "research_only": True,
        "would_start": True,
        "confirmed_public_probe": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "strategy_accepted": False,
        "preflight_path": str(preflight_path),
        "output_path": str(output_path) if output_path else None,
        "params": {
            "max_bases": max_bases,
            "min_success_bases": min_success_bases,
            "depth_limit": depth_limit,
            "timeout_sec": timeout_sec,
        },
        "summary": summary,
        "rows": rows,
        "next_valid_moves": (
            [
                "Build a visible spot/perp snapshot collect approval packet.",
                "Keep replay/grid/live/API-key/paper-forward blocked until an actual collected dataset passes data-quality gates.",
            ]
            if summary["decision"] == ACCEPTED_DECISION
            else [
                "Reject or rescope spot_perp_basis_mean_reversion_no_funding.",
                "Do not start collect/replay/grid/live/API-key/paper-forward.",
            ]
        ),
        "blocked_moves": [
            "actual_collect_without_explicit_confirmation",
            "backtest_or_replay",
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
        ],
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="spot/perp basis short public REST probe")
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bases", type=int, default=10)
    parser.add_argument("--min-success-bases", type=int, default=5)
    parser.add_argument("--depth-limit", type=int, default=5)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()

    output_path = Path(args.out)
    if args.probe:
        report = run_public_probe(
            preflight_path=Path(args.preflight),
            output_path=output_path,
            max_bases=args.max_bases,
            min_success_bases=args.min_success_bases,
            depth_limit=args.depth_limit,
            timeout_sec=args.timeout_sec,
        )
    else:
        report = build_plan_report(
            preflight_path=Path(args.preflight),
            output_path=output_path,
            max_bases=args.max_bases,
            min_success_bases=args.min_success_bases,
        )
    write_report(report, output_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
