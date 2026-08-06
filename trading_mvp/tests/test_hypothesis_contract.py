from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from costs import base_api_cost_profile  # noqa: E402
from hypothesis_contract import (  # noqa: E402
    build_pit_membership_drift_contract,
    cost_profile_hash,
    hypothesis_contract_hash,
    validate_hypothesis_contract,
)


class HypothesisContractTests(unittest.TestCase):
    def test_builds_deterministic_hash_bound_contract_without_data_access(self) -> None:
        first = build_pit_membership_drift_contract()
        second = build_pit_membership_drift_contract()

        self.assertEqual(first, second)
        self.assertEqual(first["contract_hash"], hypothesis_contract_hash(first))
        self.assertEqual(validate_hypothesis_contract(first)["verdict"], "VALID")
        self.assertFalse(first["data_access_audit"]["forward_market_rows_read"])
        self.assertFalse(first["data_access_audit"]["returns_read"])
        self.assertFalse(first["data_access_audit"]["pnl_computed"])
        self.assertFalse(first["grid_search"])
        self.assertFalse(first["retune"])

    def test_seals_current_base_api_cost_profile_and_canonical_protocol(self) -> None:
        contract = build_pit_membership_drift_contract()

        self.assertEqual(contract["economics"]["cost_profile"], base_api_cost_profile().as_dict())
        self.assertEqual(contract["economics"]["cost_profile_sha256"], cost_profile_hash())
        self.assertEqual(contract["sample_plan"]["train_eligibility_days"], 20)
        self.assertEqual(contract["sample_plan"]["oos_closed_days"], 100)
        self.assertEqual(contract["sample_plan"]["required_quality_dates"], 120)
        self.assertEqual(contract["validation_protocol"]["minimum_oos_portfolio_events_total"], 20)
        self.assertEqual(contract["validation_protocol"]["minimum_oos_portfolio_events_per_venue"], 10)
        self.assertEqual(contract["validation_protocol"]["minimum_combined_profit_factor"], 1.2)
        self.assertEqual(contract["validation_protocol"]["minimum_capacity_quote_per_leg"], 500.0)
        capacity_model = contract["position"].get("capacity_model")
        self.assertIsNotNone(capacity_model)
        assert capacity_model is not None
        self.assertEqual(capacity_model["source"], "entry_and_exit_top_of_book_quantity")
        self.assertTrue(capacity_model["required_on_entry_and_exit"])
        self.assertEqual(capacity_model["missing_or_insufficient_quantity"], "reject_event")
        self.assertFalse(capacity_model["volume_24h_proxy_allowed"])
        self.assertEqual(contract["validation_protocol"]["walk_forward"]["folds"], 5)
        self.assertTrue(contract["validation_protocol"]["walk_forward"]["non_overlapping"])
        self.assertEqual(contract["robustness"]["entry_delay_cycles"], 2)
        self.assertEqual(contract["stress"]["entry_delay_cycles"], 2)
        self.assertEqual(contract["observation_model"]["unit"], "quality_certified_local_date")
        self.assertTrue(contract["observation_model"]["require_consecutive_calendar_dates"])
        self.assertEqual(contract["economics"]["spread_accounting"], "embedded_in_executable_bbo")
        self.assertEqual(contract["economics"]["normal_cycle_cost"]["spread_bps"], 0.0)
        self.assertGreater(
            contract["economics"]["normal_max_all_in_cycle_cost_bps"],
            contract["economics"]["normal_cycle_cost"]["total_bps"],
        )

    def test_rejects_tampering_without_rehash(self) -> None:
        contract = build_pit_membership_drift_contract()
        contract["signal"]["minimum_gross_dislocation_bps"] = 25.0

        with self.assertRaisesRegex(ValueError, "contract hash mismatch"):
            validate_hypothesis_contract(contract)

    def test_rejects_relaxed_gate_even_when_rehashed(self) -> None:
        contract = copy.deepcopy(build_pit_membership_drift_contract())
        contract["validation_protocol"]["minimum_combined_profit_factor"] = 1.1
        contract["contract_hash"] = hypothesis_contract_hash(contract)

        with self.assertRaisesRegex(ValueError, "minimum_combined_profit_factor"):
            validate_hypothesis_contract(contract)

    def test_rejects_forward_data_access_even_when_rehashed(self) -> None:
        contract = copy.deepcopy(build_pit_membership_drift_contract())
        contract["data_access_audit"]["forward_market_rows_read"] = True
        contract["contract_hash"] = hypothesis_contract_hash(contract)

        with self.assertRaisesRegex(ValueError, "forward_market_rows_read"):
            validate_hypothesis_contract(contract)

    def test_rejects_hypothesis_slot_outside_track_budget(self) -> None:
        contract = copy.deepcopy(build_pit_membership_drift_contract())
        contract["multiplicity"]["hypothesis_slot"] = 4
        contract["contract_hash"] = hypothesis_contract_hash(contract)

        with self.assertRaisesRegex(ValueError, "hypothesis_slot"):
            validate_hypothesis_contract(contract)

    def test_rejects_volume_proxy_capacity_even_when_rehashed(self) -> None:
        contract = copy.deepcopy(build_pit_membership_drift_contract())
        capacity_model = contract["position"].setdefault("capacity_model", {})
        capacity_model["volume_24h_proxy_allowed"] = True
        contract["contract_hash"] = hypothesis_contract_hash(contract)

        with self.assertRaisesRegex(ValueError, "volume_24h_proxy_allowed"):
            validate_hypothesis_contract(contract)


if __name__ == "__main__":
    unittest.main()
