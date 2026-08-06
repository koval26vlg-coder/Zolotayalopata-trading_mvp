from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from costs import CostProfile, base_api_cost_profile, route_legs

DAY_SEC = 86400
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_ALIGNED_DAYS = 30
DEFAULT_TURNOVER_PER_YEAR = 12.0


def _utc_day(ts: float) -> int:
    return int(ts // DAY_SEC)


def load_funding_daily(run_dir: Path, exchange: str, symbol: str) -> dict[int, float]:
    path = run_dir / exchange / "funding" / f"{symbol}.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    daily: dict[int, float] = {}
    for row in payload.get("rows") or []:
        day = _utc_day(float(row["ts"]))
        daily[day] = daily.get(day, 0.0) + float(row["funding_rate"])
    return daily


def load_close_daily(run_dir: Path, exchange: str, symbol: str) -> dict[int, float]:
    path = run_dir / exchange / "klines" / f"{symbol}.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    closes: dict[int, float] = {}
    for row in payload.get("rows") or []:
        close = row.get("close")
        if close and close > 0:
            closes[_utc_day(float(row["ts"]))] = float(close)
    return closes


def spread_stats(
    daily_a: dict[int, float],
    daily_b: dict[int, float],
    from_day: int,
    to_day: int,
) -> dict[str, Any] | None:
    """Спред daily funding: leg_a - leg_b (положительный -> short A / long B)."""
    days = sorted(
        day for day in set(daily_a) & set(daily_b) if from_day <= day <= to_day
    )
    if not days:
        return None
    spreads = [daily_a[day] - daily_b[day] for day in days]
    mean = statistics.mean(spreads)
    dominant_sign = 1 if mean >= 0 else -1
    consistency = sum(1 for s in spreads if s * dominant_sign > 0) / len(spreads)
    return {
        "aligned_days": len(days),
        "mean_daily_spread_bps": round(mean * 1e4, 3),
        "annualized_spread_pct": round(mean * 365 * 100, 2),
        "abs_annualized_spread_pct": round(abs(mean) * 365 * 100, 2),
        "sign_consistency": round(consistency, 3),
        "direction": "short_a_long_b" if mean >= 0 else "short_b_long_a",
    }


def basis_stats(
    closes_a: dict[int, float],
    closes_b: dict[int, float],
    from_day: int,
    to_day: int,
) -> dict[str, Any] | None:
    days = sorted(
        day for day in set(closes_a) & set(closes_b) if from_day <= day <= to_day
    )
    if len(days) < 2:
        return None
    ratios = [closes_a[day] / closes_b[day] - 1.0 for day in days]
    mean = statistics.mean(ratios)
    std = statistics.stdev(ratios) if len(ratios) > 1 else 0.0
    return {
        "days": len(days),
        "mean_basis_bps": round(mean * 1e4, 2),
        "std_basis_bps": round(std * 1e4, 2),
        "max_abs_basis_bps": round(max(abs(r) for r in ratios) * 1e4, 2),
    }


def leg_annualized_pct(daily: dict[int, float], from_day: int, to_day: int) -> float | None:
    days = [day for day in daily if from_day <= day <= to_day]
    if len(days) < 2:
        return None
    values = [daily[day] for day in days]
    return round(statistics.mean(values) * 365 * 100, 2)


def mexc_spot_symbols(fee_evidence_dir: Path) -> set[str]:
    path = fee_evidence_dir / "mexc_spot_exchangeinfo.json"
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(item.get("symbol") or "").upper()
        for item in payload.get("symbols") or []
        if str(item.get("status") or "") in ("1", "ENABLED", "TRADING")
    }


@dataclass(frozen=True)
class PairReport:
    symbol: str
    base: str
    spread: dict[str, Any]
    basis: dict[str, Any] | None
    leg_annualized_pct: dict[str, float | None]
    min_volume_24h_quote: float
    mexc_spot_available: bool
    non_binance_baseline: bool
    cycle_cost: dict[str, Any]
    funding_haircut: float
    turnover_per_year: float

    def as_dict(self) -> dict[str, Any]:
        gross_pct = self.spread["abs_annualized_spread_pct"] * self.funding_haircut
        annual_cost_pct = self.cycle_cost["total_bps"] * self.turnover_per_year / 100.0
        net_pct = gross_pct - annual_cost_pct
        return {
            "symbol": self.symbol,
            "base": self.base,
            "spread_gate_minus_mexc": self.spread,
            "basis_mexc_vs_gate": self.basis,
            "leg_annualized_pct": self.leg_annualized_pct,
            "min_volume_24h_quote": self.min_volume_24h_quote,
            "mexc_spot_available": self.mexc_spot_available,
            "non_binance_baseline": self.non_binance_baseline,
            "economics": {
                "gross_abs_annualized_pct": self.spread["abs_annualized_spread_pct"],
                "funding_haircut": self.funding_haircut,
                "gross_abs_annualized_after_haircut_pct": round(gross_pct, 2),
                "cycle_cost": self.cycle_cost,
                "turnover_per_year": self.turnover_per_year,
                "annualized_costs_pct": round(annual_cost_pct, 2),
                "net_abs_annualized_after_costs_pct": round(net_pct, 2),
            },
            # Compatibility key. The value now uses the full conservative cost profile.
            "net_abs_annualized_after_costs_pct": round(net_pct, 2),
        }


def analyze_pairs(
    run_dir: str | Path,
    fee_evidence_dir: str | Path,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_aligned_days: int = DEFAULT_MIN_ALIGNED_DAYS,
    now_ts: float | None = None,
    cost_profile: CostProfile | None = None,
    turnover_per_year: float = DEFAULT_TURNOVER_PER_YEAR,
    non_binance_only: bool = True,
) -> dict[str, Any]:
    root = Path(run_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    universe = manifest.get("universe", [])
    by_exchange: dict[str, dict[str, dict[str, Any]]] = {}
    for item in universe:
        by_exchange.setdefault(item["exchange"], {})[item["symbol"]] = item
    mexc_symbols = by_exchange.get("mexc", {})
    gate_symbols = by_exchange.get("gateio", {})
    shared_all = sorted(set(mexc_symbols) & set(gate_symbols))
    shared = [
        symbol
        for symbol in shared_all
        if not non_binance_only
        or (
            mexc_symbols[symbol].get("non_binance_baseline") is True
            and gate_symbols[symbol].get("non_binance_baseline") is True
        )
    ]

    now = now_ts if now_ts is not None else time.time()
    to_day = _utc_day(now)
    from_day = to_day - window_days
    spot_set = mexc_spot_symbols(Path(fee_evidence_dir))
    profile = cost_profile or base_api_cost_profile()
    cycle_cost = profile.cycle_cost(route_legs("cross_venue_perp_perp", profile=profile))

    pairs: list[PairReport] = []
    for symbol in shared:
        mexc_funding = load_funding_daily(root, "mexc", symbol)
        gate_funding = load_funding_daily(root, "gateio", symbol)
        spread = spread_stats(gate_funding, mexc_funding, from_day, to_day)
        if spread is None or spread["aligned_days"] < min_aligned_days:
            continue
        basis = basis_stats(
            load_close_daily(root, "mexc", symbol),
            load_close_daily(root, "gateio", symbol),
            from_day,
            to_day,
        )
        base = str(mexc_symbols[symbol].get("base") or "").upper()
        volumes = [
            float(mexc_symbols[symbol].get("volume_24h_quote") or 0.0),
            float(gate_symbols[symbol].get("volume_24h_quote") or 0.0),
        ]
        pairs.append(
            PairReport(
                symbol=symbol,
                base=base,
                spread=spread,
                basis=basis,
                leg_annualized_pct={
                    "mexc": leg_annualized_pct(mexc_funding, from_day, to_day),
                    "gateio": leg_annualized_pct(gate_funding, from_day, to_day),
                },
                min_volume_24h_quote=min(volumes),
                mexc_spot_available=f"{base}USDT" in spot_set,
                non_binance_baseline=(
                    mexc_symbols[symbol].get("non_binance_baseline") is True
                    and gate_symbols[symbol].get("non_binance_baseline") is True
                ),
                cycle_cost=cycle_cost,
                funding_haircut=profile.funding_haircut,
                turnover_per_year=turnover_per_year,
            )
        )

    pair_rows = [pair.as_dict() for pair in pairs]
    pair_rows.sort(key=lambda p: p["net_abs_annualized_after_costs_pct"], reverse=True)
    return {
        "schema": "funding_pairs_v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(root),
        "params": {
            "window_days": window_days,
            "min_aligned_days": min_aligned_days,
            "turnover_per_year": turnover_per_year,
            "non_binance_only": non_binance_only,
            "route": "cross_venue_perp_perp",
            "cycle_cost_bps": cycle_cost["total_bps"],
            "spread_definition": "daily_funding_gate_minus_mexc",
        },
        "cost_profile": profile.as_dict(),
        "shared_symbols_before_non_binance_filter": len(shared_all),
        "shared_symbols_total": len(shared),
        "pairs_analyzed": len(pairs),
        "pairs": pair_rows,
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="H2 cross-exchange funding pair analysis (research-only)")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--fee-evidence-dir", required=True)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--turnover-per-year", type=float, default=DEFAULT_TURNOVER_PER_YEAR)
    parser.add_argument(
        "--include-binance-reference",
        action="store_true",
        help="Diagnostic only: include symbols present on Binance spot.",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    report = analyze_pairs(
        args.run_dir,
        args.fee_evidence_dir,
        window_days=args.window_days,
        turnover_per_year=args.turnover_per_year,
        non_binance_only=not args.include_binance_reference,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = (
        Path(args.out)
        if args.out
        else Path(args.run_dir).parents[1] / "analysis" / f"funding_pairs_{stamp}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"shared symbols: {report['shared_symbols_total']}, analyzed pairs: {report['pairs_analyzed']}")
    print("top-15 by |annualized spread|:")
    for pair in report["pairs"][:15]:
        spread = pair["spread_gate_minus_mexc"]
        basis = pair["basis_mexc_vs_gate"] or {}
        legs = pair["leg_annualized_pct"]
        print(
            f"  {pair['symbol']:20} spread={spread['annualized_spread_pct']:8.2f}%/y "
            f"cons={spread['sign_consistency']:.2f} days={spread['aligned_days']} "
            f"legs(mexc/gate)={legs.get('mexc')}/{legs.get('gateio')}% "
            f"basis_std={basis.get('std_basis_bps')}bps spot={pair['mexc_spot_available']} "
            f"minVol24h=${pair['min_volume_24h_quote']:,.0f}"
        )
    print(f"DONE report={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
