from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from costs import (  # noqa: E402
    MAX_RUNTIME_SEC,
    VenueFeeSchedule,
    base_api_cost_profile,
    route_legs,
    validate_runtime_sec,
)


class CostProfileTests(unittest.TestCase):
    def test_base_api_fees_are_conservative(self) -> None:
        profile = base_api_cost_profile()
        self.assertEqual(profile.fee_bps("mexc", "perp", "maker"), 6.0)
        self.assertEqual(profile.fee_bps("mexc", "perp", "taker"), 8.0)
        self.assertEqual(profile.fee_bps("mexc", "spot", "maker"), 10.0)
        self.assertEqual(profile.fee_bps("gateio", "perp", "maker"), 10.0)

    def test_unverified_negative_rebate_is_not_counted(self) -> None:
        schedule = VenueFeeSchedule(
            exchange="gateio",
            spot_maker_bps=-2.5,
            spot_taker_bps=7.5,
            perp_maker_bps=-2.5,
            perp_taker_bps=7.5,
            source="fixture",
            account_verified=False,
            conservative_floor_bps=10.0,
        )
        self.assertEqual(schedule.fee_bps("perp", "maker"), 10.0)
        self.assertEqual(schedule.fee_bps("perp", "taker"), 10.0)

    def test_cycle_cost_covers_both_legs_entry_and_exit(self) -> None:
        profile = base_api_cost_profile()
        legs = route_legs(
            "cross_venue_perp_perp",
            mexc_spread_bps=4.0,
            gate_spread_bps=6.0,
            mexc_impact_bps=2.0,
            gate_impact_bps=2.0,
            profile=profile,
        )
        cost = profile.cycle_cost(legs)
        self.assertAlmostEqual(cost["fees_bps"], 35.0)
        self.assertAlmostEqual(cost["spread_bps"], 7.5)
        self.assertAlmostEqual(cost["impact_bps"], 6.0)
        self.assertAlmostEqual(cost["slippage_bps"], 4.0)
        self.assertAlmostEqual(cost["rebalance_buffer_bps"], 10.0)
        self.assertAlmostEqual(cost["total_bps"], 62.5)

    def test_stress_uses_taker_and_larger_buffers(self) -> None:
        profile = base_api_cost_profile()
        legs = route_legs("same_venue_mexc_spot_perp", profile=profile)
        normal = profile.cycle_cost(legs)
        stress = profile.cycle_cost(legs, stress=True)
        self.assertEqual(stress["maker_fill_probability"], 0.0)
        self.assertGreater(stress["total_bps"], normal["total_bps"])

    def test_gate_spot_perp_route_accounts_for_four_taker_operations(self) -> None:
        profile = base_api_cost_profile()
        legs = route_legs(
            "same_venue_gateio_spot_perp",
            spot_spread_bps=0.0,
            gate_spread_bps=0.0,
            spot_impact_bps=0.0,
            gate_impact_bps=0.0,
            profile=profile,
        )
        cost = profile.cycle_cost(legs, stress=True)

        self.assertEqual([(leg.exchange, leg.market_type) for leg in legs], [("gateio", "spot"), ("gateio", "perp")])
        self.assertEqual(cost["fees_bps"], 40.0)

    def test_runtime_is_hard_capped(self) -> None:
        self.assertEqual(validate_runtime_sec(1200), 1200)
        with self.assertRaises(ValueError):
            validate_runtime_sec(MAX_RUNTIME_SEC + 1)
        with self.assertRaises(ValueError):
            validate_runtime_sec(0)


if __name__ == "__main__":
    unittest.main()
