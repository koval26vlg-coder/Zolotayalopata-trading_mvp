from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from momentum_backtest import (  # noqa: E402
    DAY_SEC,
    FEE_SCENARIOS,
    MarketSeries,
    RebalanceResult,
    SELECTION_SCENARIO,
    dedupe_by_base,
    filter_universe,
    holding_return,
    lookback_return,
    run_rebalance,
    series_metrics,
)


def make_market(
    base: str,
    daily_returns: dict[int, float],
    start_price: float = 100.0,
    exchange: str = "mexc",
    volume: float = 1_000_000.0,
    baseline: bool = False,
    funding: list[tuple[float, float]] | None = None,
    qvol: float = 1_000_000.0,
) -> MarketSeries:
    market = MarketSeries(
        exchange=exchange,
        symbol=f"{base}_USDT",
        base=base,
        non_binance_baseline=baseline,
        volume_24h_quote=volume,
    )
    price = start_price
    days = sorted(daily_returns)
    for day in range(days[0], days[-1] + 1):
        price *= 1.0 + daily_returns.get(day, 0.0)
        market.closes[day] = price
        market.quote_volumes[day] = qvol
    market.funding = funding or []
    return market


class ReturnTests(unittest.TestCase):
    def test_lookback_and_holding_return(self) -> None:
        market = make_market("AAA", {day: 0.01 for day in range(0, 40)})
        look = lookback_return(market, 39, 30)
        self.assertIsNotNone(look)
        self.assertAlmostEqual(look, 1.01**30 - 1, places=9)
        hold = holding_return(market, 30, 7)
        self.assertAlmostEqual(hold, 1.01**7 - 1, places=9)

    def test_missing_days_return_none(self) -> None:
        market = make_market("AAA", {0: 0.0, 1: 0.01})
        self.assertIsNone(lookback_return(market, 1, 30))
        self.assertIsNone(holding_return(market, 1, 7))


class FundingSumTests(unittest.TestCase):
    def test_funding_sum_window_boundaries(self) -> None:
        market = make_market(
            "AAA",
            {day: 0.0 for day in range(0, 20)},
            funding=[
                (10 * DAY_SEC + 1, 0.001),
                (17 * DAY_SEC, 0.002),
                (17 * DAY_SEC + 1, 0.004),
            ],
        )
        self.assertAlmostEqual(market.funding_sum(10, 17), 0.003)


class UniverseTests(unittest.TestCase):
    def test_dedupe_prefers_higher_volume(self) -> None:
        low = make_market("AAA", {0: 0.0}, exchange="gateio", volume=10.0)
        high = make_market("AAA", {0: 0.0}, exchange="mexc", volume=100.0)
        result = dedupe_by_base([low, high])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].exchange, "mexc")

    def test_filter_universe_baseline(self) -> None:
        base_market = make_market("AAA", {0: 0.0}, baseline=True)
        other = make_market("BBB", {0: 0.0}, baseline=False)
        result = filter_universe([base_market, other], baseline_only=True)
        self.assertEqual([m.base for m in result], ["AAA"])


class RebalanceTests(unittest.TestCase):
    def _universe(self) -> list[MarketSeries]:
        markets: list[MarketSeries] = []
        # 20 winners (+1%/день до ребаланса, +1%/день после), 20 losers (-1% / -1%)
        for index in range(20):
            markets.append(make_market(f"W{index}", {day: 0.01 for day in range(0, 45)}))
        for index in range(20):
            markets.append(make_market(f"L{index}", {day: -0.01 for day in range(0, 45)}))
        return markets

    def test_momentum_continuation_positive(self) -> None:
        result = run_rebalance(self._universe(), day=37, lookback=30, hold_days=7, min_per_side=5, min_qvol=0.0)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreater(result.gross_return, 0.0)
        self.assertEqual(result.n_long, result.n_short)

    def test_too_few_markets_returns_none(self) -> None:
        markets = self._universe()[:10]
        result = run_rebalance(markets, day=37, lookback=30, hold_days=7, min_per_side=5, min_qvol=0.0)
        self.assertIsNone(result)

    def test_liquidity_filter_excludes(self) -> None:
        markets = self._universe()
        for market in markets:
            for day in market.quote_volumes:
                market.quote_volumes[day] = 10.0
        result = run_rebalance(markets, day=37, lookback=30, hold_days=7, min_per_side=5, min_qvol=1000.0)
        self.assertIsNone(result)

    def test_funding_sign_long_pays_short_receives(self) -> None:
        markets = self._universe()
        funding = [(day * DAY_SEC + 1, 0.001) for day in range(37, 44)]
        for market in markets:
            market.funding = list(funding)
        result = run_rebalance(markets, day=37, lookback=30, hold_days=7, min_per_side=5, min_qvol=0.0)
        assert result is not None
        # long: -sum(f), short: +sum(f) -> в сумме 0 при одинаковом funding
        self.assertAlmostEqual(result.funding_return, 0.0, places=12)


class MetricsTests(unittest.TestCase):
    def test_selection_scenario_uses_base_fee_not_discount_tier(self) -> None:
        self.assertEqual(SELECTION_SCENARIO, "base_vip0_taker_taker_20bps")
        self.assertGreaterEqual(FEE_SCENARIOS[SELECTION_SCENARIO], 20.0)

    def test_series_metrics_costs_reduce_mean(self) -> None:
        results = [
            RebalanceResult(day=0, n_long=5, n_short=5, gross_return=0.002, funding_return=0.0),
            RebalanceResult(day=7, n_long=5, n_short=5, gross_return=0.004, funding_return=0.0),
        ]
        free = series_metrics(results, cost_bps=0.0)
        paid = series_metrics(results, cost_bps=10.0)
        self.assertAlmostEqual(free["mean_weekly_net_bps"], 30.0, places=6)
        self.assertAlmostEqual(paid["mean_weekly_net_bps"], 20.0, places=6)
        self.assertEqual(free["n_rebalances"], 2)
        self.assertEqual(free["hit_rate"], 1.0)

    def test_series_metrics_empty(self) -> None:
        self.assertEqual(series_metrics([], 0.0), {"n_rebalances": 0})


if __name__ == "__main__":
    unittest.main()
