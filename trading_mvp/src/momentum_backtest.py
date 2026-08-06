from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DAY_SEC = 86400
DEFAULT_LOOKBACKS = (30, 60, 90)
DEFAULT_HOLD_DAYS = 7
DEFAULT_MIN_PER_SIDE = 5
DEFAULT_MIN_QVOL_30D = 300_000.0
DEFAULT_TRAIN_FRACTION = 0.7

# Round-trip bps on whole portfolio capital.
# For a dollar-neutral long/short rebalance, each side uses half capital:
# 10 bps per side per leg -> 20 bps round-trip per leg -> 20 bps on total capital.
# The project currently assumes base/VIP0/no-volume fees, so train selection must
# use the conservative base case, not lower maker-tier sensitivity rows.
FEE_SCENARIOS: dict[str, float] = {
    "base_vip0_taker_taker_20bps": 20.0,
    "base_vip0_stress_plus_50pct_fee_30bps": 30.0,
    "A_mexc_maker_maker": 0.0,
    "B_mexc_maker_taker": 2.0,
    "D_gate_maker_taker": 6.5,
    "stress_legacy_taker_39bps": 39.0,
}
SELECTION_SCENARIO = "base_vip0_taker_taker_20bps"
DEFAULT_SLIPPAGE_BPS = 10.0


def _utc_day(ts: float) -> int:
    return int(ts // DAY_SEC)


@dataclass
class MarketSeries:
    exchange: str
    symbol: str
    base: str
    non_binance_baseline: bool
    volume_24h_quote: float
    closes: dict[int, float] = field(default_factory=dict)
    quote_volumes: dict[int, float] = field(default_factory=dict)
    funding: list[tuple[float, float]] = field(default_factory=list)

    def funding_sum(self, from_day: int, to_day: int) -> float:
        from_ts = from_day * DAY_SEC
        to_ts = to_day * DAY_SEC
        return sum(rate for ts, rate in self.funding if from_ts < ts <= to_ts)

    def rolling_qvol(self, day: int, window: int = 30) -> float:
        values = [self.quote_volumes.get(d, 0.0) for d in range(day - window, day)]
        present = [v for v in values if v > 0]
        if not present:
            return 0.0
        return sum(present) / len(present)


def load_markets(run_dir: str | Path) -> list[MarketSeries]:
    root = Path(run_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    markets: list[MarketSeries] = []
    for item in manifest.get("universe", []):
        exchange = item["exchange"]
        symbol = item["symbol"]
        klines_path = root / exchange / "klines" / f"{symbol}.json"
        if not klines_path.exists():
            continue
        payload = json.loads(klines_path.read_text(encoding="utf-8"))
        rows = payload.get("rows") or []
        if not rows:
            continue
        market = MarketSeries(
            exchange=exchange,
            symbol=symbol,
            base=str(item.get("base") or "").upper(),
            non_binance_baseline=bool(item.get("non_binance_baseline")),
            volume_24h_quote=float(item.get("volume_24h_quote") or 0.0),
        )
        for row in rows:
            day = _utc_day(row["ts"])
            close = row.get("close")
            if close is None or close <= 0:
                continue
            market.closes[day] = float(close)
            qvol = row.get("volume_quote")
            if qvol is not None:
                market.quote_volumes[day] = float(qvol)
        funding_path = root / exchange / "funding" / f"{symbol}.json"
        if funding_path.exists():
            fpayload = json.loads(funding_path.read_text(encoding="utf-8"))
            market.funding = [
                (float(row["ts"]), float(row["funding_rate"]))
                for row in fpayload.get("rows") or []
            ]
        markets.append(market)
    return markets


def dedupe_by_base(markets: list[MarketSeries]) -> list[MarketSeries]:
    best: dict[str, MarketSeries] = {}
    for market in markets:
        current = best.get(market.base)
        if current is None or market.volume_24h_quote > current.volume_24h_quote:
            best[market.base] = market
    return list(best.values())


def filter_universe(markets: list[MarketSeries], baseline_only: bool) -> list[MarketSeries]:
    if baseline_only:
        markets = [m for m in markets if m.non_binance_baseline]
    return dedupe_by_base(markets)


@dataclass(frozen=True)
class RebalanceResult:
    day: int
    n_long: int
    n_short: int
    gross_return: float
    funding_return: float
    base_contributions: dict[str, float] = field(default_factory=dict)

    @property
    def portfolio_return(self) -> float:
        return self.gross_return + self.funding_return

    @property
    def position_count(self) -> int:
        return self.n_long + self.n_short


def lookback_return(market: MarketSeries, day: int, lookback: int) -> float | None:
    now = market.closes.get(day)
    past = market.closes.get(day - lookback)
    if now is None or past is None or past <= 0:
        return None
    return now / past - 1.0


def holding_return(market: MarketSeries, day: int, hold_days: int) -> float | None:
    now = market.closes.get(day)
    future = market.closes.get(day + hold_days)
    if now is None or future is None or now <= 0:
        return None
    return future / now - 1.0


def run_rebalance(
    markets: list[MarketSeries],
    day: int,
    lookback: int,
    hold_days: int,
    min_per_side: int,
    min_qvol: float,
) -> RebalanceResult | None:
    scored: list[tuple[float, MarketSeries]] = []
    for market in markets:
        if market.rolling_qvol(day) < min_qvol:
            continue
        score = lookback_return(market, day, lookback)
        hold = holding_return(market, day, hold_days)
        if score is None or hold is None:
            continue
        scored.append((score, market))
    if len(scored) < min_per_side * 4:
        return None
    scored.sort(key=lambda pair: pair[0])
    bucket = max(min_per_side, len(scored) // 10)
    shorts = scored[:bucket]
    longs = scored[-bucket:]

    def leg(items: list[tuple[float, MarketSeries]], sign: int) -> tuple[float, float, dict[str, float]]:
        price = 0.0
        funding = 0.0
        contributions: dict[str, float] = {}
        weight = 0.5 / len(items)
        for _, market in items:
            hold = holding_return(market, day, hold_days) or 0.0
            fund = market.funding_sum(day, day + hold_days)
            price_component = sign * hold
            funding_component = -sign * fund  # long платит положительный funding, short получает
            price += price_component
            funding += funding_component
            contributions[market.base] = contributions.get(market.base, 0.0) + weight * (
                price_component + funding_component
            )
        return price / len(items), funding / len(items), contributions

    long_price, long_funding, long_contrib = leg(longs, +1)
    short_price, short_funding, short_contrib = leg(shorts, -1)
    contributions = dict(long_contrib)
    for base, value in short_contrib.items():
        contributions[base] = contributions.get(base, 0.0) + value
    return RebalanceResult(
        day=day,
        n_long=len(longs),
        n_short=len(shorts),
        gross_return=0.5 * (long_price + short_price),
        funding_return=0.5 * (long_funding + short_funding),
        base_contributions=contributions,
    )


def run_series(
    markets: list[MarketSeries],
    days: list[int],
    lookback: int,
    hold_days: int,
    min_per_side: int,
    min_qvol: float,
) -> list[RebalanceResult]:
    results: list[RebalanceResult] = []
    for day in days:
        result = run_rebalance(markets, day, lookback, hold_days, min_per_side, min_qvol)
        if result is not None:
            results.append(result)
    return results


def series_metrics(
    results: list[RebalanceResult],
    cost_bps: float,
    *,
    funding_multiplier: float = 1.0,
    extra_adverse_bps: float = 0.0,
) -> dict[str, Any]:
    if not results:
        return {"n_rebalances": 0}
    cost = (cost_bps + extra_adverse_bps) / 1e4
    nets = [r.gross_return + funding_multiplier * r.funding_return - cost for r in results]
    mean = sum(nets) / len(nets)
    var = sum((x - mean) ** 2 for x in nets) / max(1, len(nets) - 1)
    std = math.sqrt(var)
    t_stat = mean / std * math.sqrt(len(nets)) if std > 0 else 0.0
    gains = sum(x for x in nets if x > 0)
    losses = -sum(x for x in nets if x < 0)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    base_contributions: dict[str, float] = {}
    for result in results:
        position_count = max(1, result.position_count)
        per_base_cost = cost / position_count
        for base, contribution in result.base_contributions.items():
            # Funding stress is applied at aggregate level; concentration remains
            # directionally useful and conservative for identifying single-name dependence.
            base_contributions[base] = base_contributions.get(base, 0.0) + contribution - per_base_cost
    positive_total = sum(value for value in base_contributions.values() if value > 0)
    top_base = None
    top_base_share = 0.0
    if positive_total > 0 and base_contributions:
        top_base, top_value = max(base_contributions.items(), key=lambda item: item[1])
        top_base_share = max(0.0, top_value) / positive_total

    return {
        "n_rebalances": len(nets),
        "mean_weekly_net_bps": round(mean * 1e4, 3),
        "std_weekly_bps": round(std * 1e4, 3),
        "t_stat": round(t_stat, 3),
        "cum_return_pct": round(cum * 100, 3),
        "profit_factor": round(gains / losses, 3) if losses > 0 else None,
        "hit_rate": round(sum(1 for x in nets if x > 0) / len(nets), 3),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "avg_funding_contribution_bps": round(
            sum(r.funding_return for r in results) / len(results) * 1e4, 3
        ),
        "top_base": top_base,
        "top_base_positive_share": round(top_base_share, 3),
        "top_base_net_contribution_pct": round((base_contributions.get(top_base, 0.0) if top_base else 0.0) * 100, 3),
    }


def select_lookback(
    markets: list[MarketSeries],
    train_days: list[int],
    lookbacks: tuple[int, ...],
    hold_days: int,
    min_per_side: int,
    min_qvol: float,
    selection_cost: float,
) -> tuple[int | None, dict[str, Any]]:
    train_report: dict[str, Any] = {}
    best_lookback: int | None = None
    best_mean: float | None = None
    for lookback in lookbacks:
        results = run_series(markets, train_days, lookback, hold_days, min_per_side, min_qvol)
        metrics = series_metrics(results, selection_cost)
        train_report[str(lookback)] = metrics
        mean = metrics.get("mean_weekly_net_bps")
        if metrics.get("n_rebalances", 0) > 0 and (best_mean is None or mean > best_mean):
            best_mean = mean
            best_lookback = lookback
    return best_lookback, train_report


def rolling_walk_forward(
    markets: list[MarketSeries],
    rebalance_days: list[int],
    lookbacks: tuple[int, ...],
    hold_days: int,
    min_per_side: int,
    min_qvol: float,
    selection_cost: float,
    train_window: int = 26,
    test_window: int = 8,
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    start = train_window
    while start < len(rebalance_days):
        train_days = rebalance_days[start - train_window : start]
        test_days = rebalance_days[start : min(len(rebalance_days), start + test_window)]
        if not test_days:
            break
        selected, train_report = select_lookback(
            markets, train_days, lookbacks, hold_days, min_per_side, min_qvol, selection_cost
        )
        if selected is None:
            folds.append(
                {
                    "fold_index": len(folds),
                    "selected_lookback": None,
                    "train_rebalances": len(train_days),
                    "test_rebalances": len(test_days),
                    "metrics": {"n_rebalances": 0},
                    "train_by_lookback": train_report,
                }
            )
            start += test_window
            continue
        results = run_series(markets, test_days, selected, hold_days, min_per_side, min_qvol)
        folds.append(
            {
                "fold_index": len(folds),
                "selected_lookback": selected,
                "train_rebalances": len(train_days),
                "test_rebalances": len(test_days),
                "metrics": series_metrics(results, selection_cost),
                "train_by_lookback": train_report,
            }
        )
        start += test_window
    valid = [fold for fold in folds if fold["metrics"].get("n_rebalances", 0) > 0]
    positive = [fold for fold in valid if fold["metrics"].get("mean_weekly_net_bps", 0.0) > 0]
    means = [fold["metrics"].get("mean_weekly_net_bps", 0.0) for fold in valid]
    means_sorted = sorted(means)
    median = 0.0
    if means_sorted:
        mid = len(means_sorted) // 2
        median = means_sorted[mid] if len(means_sorted) % 2 else (means_sorted[mid - 1] + means_sorted[mid]) / 2
    return {
        "train_window_rebalances": train_window,
        "test_window_rebalances": test_window,
        "folds": folds,
        "valid_folds": len(valid),
        "positive_folds": len(positive),
        "positive_fold_ratio": round(len(positive) / len(valid), 3) if valid else 0.0,
        "median_mean_weekly_net_bps": round(median, 3),
    }


def run_config(
    markets: list[MarketSeries],
    *,
    label: str,
    lookbacks: tuple[int, ...] = DEFAULT_LOOKBACKS,
    hold_days: int = DEFAULT_HOLD_DAYS,
    min_per_side: int = DEFAULT_MIN_PER_SIDE,
    min_qvol: float = DEFAULT_MIN_QVOL_30D,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> dict[str, Any]:
    all_days = sorted({day for market in markets for day in market.closes})
    if not all_days:
        return {"label": label, "error": "no data"}
    start = all_days[0] + max(lookbacks)
    end = all_days[-1] - hold_days
    rebalance_days = list(range(start, end + 1, hold_days))
    split_index = int(len(rebalance_days) * train_fraction)
    train_days = rebalance_days[:split_index]
    test_days = rebalance_days[split_index:]

    selection_cost = FEE_SCENARIOS[SELECTION_SCENARIO] + slippage_bps
    best_lookback, train_report = select_lookback(
        markets, train_days, lookbacks, hold_days, min_per_side, min_qvol, selection_cost
    )

    oos_report: dict[str, Any] = {}
    if best_lookback is not None:
        oos_results = run_series(markets, test_days, best_lookback, hold_days, min_per_side, min_qvol)
        for scenario, fee_bps in FEE_SCENARIOS.items():
            oos_report[scenario] = series_metrics(oos_results, fee_bps + slippage_bps)
        oos_report["base_vip0_2x_slippage"] = series_metrics(
            oos_results, FEE_SCENARIOS["base_vip0_taker_taker_20bps"] + 2 * slippage_bps
        )
        oos_report["base_vip0_zero_funding"] = series_metrics(
            oos_results,
            FEE_SCENARIOS["base_vip0_taker_taker_20bps"] + slippage_bps,
            funding_multiplier=0.0,
        )
        oos_report["base_vip0_adverse_funding_50pct"] = series_metrics(
            oos_results,
            FEE_SCENARIOS["base_vip0_taker_taker_20bps"] + slippage_bps,
            funding_multiplier=0.5,
        )
        oos_report["base_vip0_partial_fill_stale_exit_25bps"] = series_metrics(
            oos_results,
            FEE_SCENARIOS["base_vip0_taker_taker_20bps"] + slippage_bps,
            extra_adverse_bps=25.0,
        )
        half = len(oos_results) // 2
        oos_report["walk_forward_halves"] = {
            "first_half": series_metrics(oos_results[:half], selection_cost),
            "second_half": series_metrics(oos_results[half:], selection_cost),
        }

    return {
        "label": label,
        "markets_in_universe": len(markets),
        "rebalance_days_total": len(rebalance_days),
        "train_rebalances": len(train_days),
        "test_rebalances": len(test_days),
        "params": {
            "lookbacks": list(lookbacks),
            "hold_days": hold_days,
            "min_per_side": min_per_side,
            "min_qvol_30d": min_qvol,
            "train_fraction": train_fraction,
            "slippage_bps": slippage_bps,
            "selection_scenario": SELECTION_SCENARIO,
        },
        "train_by_lookback": train_report,
        "selected_lookback": best_lookback,
        "oos_by_scenario": oos_report,
        "rolling_walk_forward": rolling_walk_forward(
            markets,
            rebalance_days,
            lookbacks,
            hold_days,
            min_per_side,
            min_qvol,
            selection_cost,
        ),
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="H1 cross-sectional momentum daily backtest (research-only)")
    parser.add_argument("--run-dir", required=True, help="Папка daily_collect с manifest.json")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--min-qvol", type=float, default=DEFAULT_MIN_QVOL_30D)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir.parents[1] / "backtests"
    markets = load_markets(run_dir)
    print(f"loaded markets: {len(markets)}", flush=True)

    report: dict[str, Any] = {
        "schema": "momentum_daily_backtest_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(run_dir),
        "setup_id": "cross_sectional_momentum_daily",
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "paper_forward_allowed": False,
        "economics_policy": {
            "selection_scenario": SELECTION_SCENARIO,
            "base_fee_model": "base/VIP0/no-volume",
            "optimize_for": "OOS net expectancy after fees, slippage and funding drag",
            "winrate_policy": "supporting metric only; reject high hit-rate variants with negative net expectancy",
        },
        "caveats": [
            "survivorship_bias: universe = текущие top-volume контракты; погибшие/делистнутые монеты отсутствуют",
            "funding window aligned to UTC day boundaries (approximation)",
            "gate funding history depth ~179d: funding contribution до этого = 0",
            "research-only long/short perp simulation; live leverage/margin/API keys remain blocked",
        ],
        "configs": {},
    }
    for label, baseline_only in (("extended", False), ("non_binance_baseline", True)):
        universe = filter_universe(markets, baseline_only)
        result = run_config(
            universe,
            label=label,
            min_qvol=args.min_qvol,
            slippage_bps=args.slippage_bps,
        )
        report["configs"][label] = result
        print(
            f"[{label}] markets={result.get('markets_in_universe')} "
            f"selected_lookback={result.get('selected_lookback')}",
            flush=True,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"momentum_daily_{stamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DONE report={out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
