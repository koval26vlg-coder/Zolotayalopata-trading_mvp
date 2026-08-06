from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_gate import (  # noqa: E402
    book_stats,
    carry_economics,
    capacity_within_impact_bps,
    market_impact_bps,
    normalize_gate_perp,
    normalize_mexc_perp,
    normalize_mexc_spot,
    position_capacity_usd,
    select_candidates,
)


class NormalizeTests(unittest.TestCase):
    def test_mexc_spot(self) -> None:
        bids, asks = normalize_mexc_spot({"bids": [["1.0", "10"]], "asks": [["1.1", "5"]]})
        self.assertEqual(bids, [(1.0, 10.0)])
        self.assertEqual(asks, [(1.1, 5.0)])

    def test_mexc_perp_contract_size(self) -> None:
        bids, asks = normalize_mexc_perp({"data": {"bids": [[2.0, 100, 3]], "asks": [[2.1, 50, 1]]}}, contract_size=10.0)
        self.assertEqual(bids, [(2.0, 1000.0)])
        self.assertEqual(asks, [(2.1, 500.0)])

    def test_gate_perp_multiplier(self) -> None:
        bids, asks = normalize_gate_perp({"bids": [{"p": "3.0", "s": 20}], "asks": [{"p": "3.1", "s": 10}]}, multiplier=5.0)
        self.assertEqual(bids, [(3.0, 100.0)])
        self.assertEqual(asks, [(3.1, 50.0)])


class BookStatsTests(unittest.TestCase):
    def test_spread_and_band_depth(self) -> None:
        bids = [(99.9, 10.0), (99.0, 100.0), (90.0, 1000.0)]
        asks = [(100.1, 10.0), (101.0, 100.0), (110.0, 1000.0)]
        stats = book_stats(bids, asks)
        assert stats is not None
        self.assertAlmostEqual(stats["mid"], 100.0)
        self.assertAlmostEqual(stats["spread_bps"], 20.0, places=6)
        band25 = stats["depth"]["band_25bps"]
        self.assertAlmostEqual(band25["bid_quote_usd"], 999.0)
        self.assertAlmostEqual(band25["ask_quote_usd"], 1001.0)
        band100 = stats["depth"]["band_100bps"]
        self.assertAlmostEqual(band100["bid_quote_usd"], 999.0 + 9900.0)
        self.assertAlmostEqual(band100["ask_quote_usd"], 1001.0 + 10100.0)

    def test_empty_book(self) -> None:
        self.assertIsNone(book_stats([], [(1.0, 1.0)]))


class CapacityTests(unittest.TestCase):
    def test_capacity_min_of_depth_and_volume(self) -> None:
        stats = {
            "mid": 100.0,
            "spread_bps": 10.0,
            "depth": {"band_50bps": {"bid_quote_usd": 10_000.0, "ask_quote_usd": 20_000.0}},
        }
        # 20% от min(bid, ask)=10000 -> 2000; 0.5% от 1M -> 5000 => 2000
        self.assertEqual(position_capacity_usd(stats, 1_000_000.0), 2000.0)
        # объемный лимит биндит: 0.5% от 100k -> 500
        self.assertEqual(position_capacity_usd(stats, 100_000.0), 500.0)

    def test_capacity_none_stats(self) -> None:
        self.assertEqual(position_capacity_usd(None, 1_000_000.0), 0.0)

    def test_market_impact_and_impact_capacity(self) -> None:
        bids = [(100.0, 3.0), (99.95, 4.0), (99.0, 100.0)]
        asks = [(100.1, 3.0), (100.15, 4.0), (101.0, 100.0)]
        self.assertAlmostEqual(market_impact_bps(asks, side="buy", notional_quote=500.0) or 0.0, 2.0, delta=0.6)
        self.assertAlmostEqual(market_impact_bps(bids, side="sell", notional_quote=500.0) or 0.0, 2.0, delta=0.6)
        self.assertAlmostEqual(capacity_within_impact_bps(bids, asks), 139.96, places=2)

    def test_market_impact_requires_full_depth(self) -> None:
        self.assertIsNone(market_impact_bps([(100.0, 1.0)], side="buy", notional_quote=500.0))


class SelectCandidatesTests(unittest.TestCase):
    def _pair(
        self,
        symbol: str,
        mexc_leg: float | None,
        spot: bool,
        abs_spread: float,
        cons: float,
    ) -> dict:
        return {
            "symbol": symbol,
            "mexc_spot_available": spot,
            "leg_annualized_pct": {"mexc": mexc_leg},
            "spread_gate_minus_mexc": {
                "abs_annualized_spread_pct": abs_spread,
                "sign_consistency": cons,
            },
        }

    def test_selects_e_and_g_dedup(self) -> None:
        pairs = [
            self._pair("AAA_USDT", 50.0, True, 5.0, 0.5),    # только E
            self._pair("BBB_USDT", 60.0, True, 30.0, 0.9),   # E и G -> без дубля
            self._pair("CCC_USDT", None, True, 40.0, 0.8),   # только G
            self._pair("DDD_USDT", 90.0, False, 5.0, 0.5),   # нет спота -> мимо E
            self._pair("EEE_USDT", 10.0, True, 90.0, 0.5),   # слабая нога, шаткий спред
        ]
        selected = select_candidates(pairs)
        self.assertEqual(selected, ["BBB_USDT", "AAA_USDT", "CCC_USDT"])

    def test_caps_respected(self) -> None:
        pairs = [self._pair(f"S{i}_USDT", 100.0 - i, True, 0.0, 0.0) for i in range(12)]
        selected = select_candidates(pairs, max_e=3)
        self.assertEqual(len(selected), 3)
        self.assertEqual(selected[0], "S0_USDT")

    def test_empty_pairs(self) -> None:
        self.assertEqual(select_candidates([]), [])


class EconomicsTests(unittest.TestCase):
    def test_carry_economics_haircut_and_costs(self) -> None:
        eco = carry_economics(leg_annual_pct=60.0, capacity_usd=10_000.0, perp_spread_bps=10.0, hedge_spread_bps=10.0)
        self.assertAlmostEqual(eco["gross_after_persistence_haircut_pct"], 60.0)
        self.assertAlmostEqual(eco["spread_costs_annual_pct"], 1.8)
        self.assertAlmostEqual(eco["all_in_costs_annual_pct"], 8.4)
        self.assertAlmostEqual(eco["cycle_cost"]["total_bps"], 70.0)
        self.assertAlmostEqual(eco["net_annual_pct"], 51.6)
        self.assertAlmostEqual(eco["net_annual_usd_at_capacity"], 5160.0)


if __name__ == "__main__":
    unittest.main()
