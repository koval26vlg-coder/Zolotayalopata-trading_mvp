"""The replay must run under the costs fixed before the data, not the cheaper defaults.

The 2026-07-08 drift-reversal plan - written before any history was collected - set a
69 bps round trip and said "do not accept lower-cost sensitivity as proof". The replay
module written on 2026-07-10 defaults to 30 bps, and its stress case of 50 bps is still
cheaper than the contract's normal case. The single most useful thing this plan does is
make that substitution impossible to perform quietly, so it is what these tests pin.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import listing_event_replay_plan as plan_module  # noqa: E402
from listing_event_replay import ReplayConfig  # noqa: E402


def _issued() -> dict:
    return json.loads(plan_module.PLAN_PATH.read_text(encoding="utf-8"))


class CostContractTests(unittest.TestCase):
    def test_the_issued_plan_applies_the_contract_cost_not_the_module_default(self):
        plan = _issued()
        costs = plan["cost_contract"]
        self.assertEqual(costs["applied_round_trip_cost_bps"], 69.0)
        self.assertEqual(costs["module_default_round_trip_cost_bps"], 30.0)
        self.assertGreater(
            costs["applied_round_trip_cost_bps"],
            costs["module_default_round_trip_cost_bps"],
        )

    def test_the_frozen_cost_reproduces_what_the_module_would_compute(self):
        """cost_bps = 2*(fee + slippage) inside the module; the plan must match it."""
        frozen = _issued()["frozen_parameters"]
        recomputed = 2.0 * (frozen["fee_bps_per_side"] + frozen["slippage_bps_per_side"])
        self.assertEqual(recomputed, 69.0)
        self.assertEqual(plan_module.frozen_cost_bps(), 69.0)

    def test_the_module_defaults_are_indeed_the_cheaper_set(self):
        # If this ever stops being true the plan's whole premise needs revisiting.
        defaults = ReplayConfig()
        default_round_trip = 2.0 * (
            defaults.fee_bps_per_side + defaults.slippage_bps_per_side
        )
        self.assertEqual(default_round_trip, 30.0)
        self.assertLess(default_round_trip, 69.0)

    def test_even_the_module_stress_case_is_cheaper_than_the_contract_normal_case(self):
        d = ReplayConfig()
        stress = 2.0 * (
            d.fee_bps_per_side * d.stress_fee_multiplier
            + d.slippage_bps_per_side * d.stress_slippage_multiplier
        )
        self.assertEqual(stress, 50.0)
        self.assertLess(stress, 69.0)

    def test_a_plan_that_applied_the_module_default_is_refused(self):
        plan = _issued()
        plan["cost_contract"]["applied_round_trip_cost_bps"] = 30.0
        plan["plan_hash"] = plan_module._canonical_hash_without(plan, "plan_hash")
        with self.assertRaisesRegex(Exception, "applied cost must equal the contract"):
            plan_module.validate_plan(plan)


class ProvenanceTests(unittest.TestCase):
    def test_every_frozen_parameter_declares_where_it_came_from(self):
        plan = _issued()
        self.assertEqual(
            set(plan["frozen_parameters"]), set(plan["parameter_provenance"])
        )

    def test_only_parameters_with_a_pre_data_anchor_are_contract_anchored(self):
        provenance = _issued()["parameter_provenance"]
        self.assertEqual(
            {k for k, v in provenance.items() if v == "contract_anchored"},
            {"trigger_bps", "fee_bps_per_side", "slippage_bps_per_side"},
        )
        # Everything fixed on 2026-07-10, after the 2026-07-09 collection, is honest
        # about it rather than being called pre-registered.
        self.assertEqual(provenance["hold_hours"], "chosen_after_data")
        self.assertEqual(provenance["entry_delay_hours"], "chosen_after_data")
        self.assertEqual(provenance["min_profit_factor"], "chosen_after_data")

    def test_the_trigger_clears_the_pre_registered_hurdle(self):
        frozen = _issued()["frozen_parameters"]
        self.assertGreaterEqual(
            frozen["trigger_bps"], plan_module.CONTRACT_MIN_GROSS_MOVE_HURDLE_BPS
        )

    def test_a_trigger_below_the_hurdle_is_refused(self):
        plan = _issued()
        plan["frozen_parameters"]["trigger_bps"] = 100.0
        plan["plan_hash"] = plan_module._canonical_hash_without(plan, "plan_hash")
        with self.assertRaisesRegex(Exception, "minimum gross move hurdle"):
            plan_module.validate_plan(plan)

    def test_an_invented_provenance_label_is_refused(self):
        plan = _issued()
        plan["parameter_provenance"]["hold_hours"] = "preregistered"
        plan["plan_hash"] = plan_module._canonical_hash_without(plan, "plan_hash")
        with self.assertRaisesRegex(Exception, "provenance must be"):
            plan_module.validate_plan(plan)


class AuthorityTests(unittest.TestCase):
    def test_a_descriptive_replay_authorizes_nothing(self):
        acceptance = _issued()["acceptance_policy"]
        for key in (
            "replay_authorizes",
            "paper_forward_authorized",
            "live_trading_authorized",
        ):
            with self.subTest(key=key):
                self.assertIs(acceptance[key], False)

    def test_grid_search_over_the_frozen_parameters_is_forbidden(self):
        plan = _issued()
        self.assertIs(plan["grid_search_allowed"], False)
        self.assertIn(
            "re-running with cheaper costs and reporting the better result",
            plan["forbidden"],
        )

    def test_the_issued_plan_validates(self):
        plan_module.validate_plan(_issued())

    def test_it_binds_the_normalizer_that_asked_for_it(self):
        binding = _issued()["source_bindings"]["normalizer"]
        self.assertEqual(
            binding["decision"],
            "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY",
        )
        self.assertEqual(
            binding["required_next_step"],
            "implement_read_only_listing_event_replay_planonly_no_grid_no_live",
        )


if __name__ == "__main__":
    unittest.main()
