from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_campaign_contract as campaign  # noqa: E402
from dense_ws_signal_evaluator_contract import (  # noqa: E402
    DRAFT_SCHEMA,
    DraftIntegrityError,
    build_review_draft,
    canonical_draft_hash,
    validate_review_draft,
)


def _campaign_sources() -> tuple[dict, dict]:
    execution = {
        "sample_clock": "UTC epoch boundaries where timestamp modulo 5 seconds is zero",
        "sample_interval_sec": 5,
        "quote_selection": (
            "latest BBO with recv_ts <= sample_ts; never nearest or forward-filled "
            "from a future row"
        ),
        "max_quote_age_ms": {"mexc": 6000, "gateio": 5000},
        "max_cross_venue_recv_ts_skew_ms": 2000,
        "max_spread_bps_each_venue": 3.0,
        "min_top_notional_quote_each_side": 25.0,
        "eligible_regime": "DENSE_BOTH",
        "one_snapshot_per_base_per_boundary": True,
        "stale_or_incomplete_snapshot_action": "exclude and count by reason",
        "minimum_eligible_snapshots": 180,
        "execution_mode_for_future_evaluation": "taker_at_opposite_top_of_book",
        "maker_fill_or_queue_assumption": False,
    }
    cost_risk = {
        "cost": {
            "base_tier_only": True,
            "normal": {
                "round_trip_fee_bps": 39.0,
                "slippage_bps": 10.0,
                "inventory_rebalance_buffer_bps": 20.0,
                "total_cost_bps": 69.0,
            },
            "stress": {
                "round_trip_fee_bps": 39.0,
                "slippage_bps": 20.0,
                "inventory_rebalance_buffer_bps": 30.0,
                "total_cost_bps": 89.0,
            },
            "fee_tier_optimism": False,
            "maker_rebate_credit": False,
            "transfer_latency_benefit": False,
        },
        "risk": {
            "research_simulation_only": True,
            "direction": "long_only_spot_no_short",
            "notional_quote_per_synthetic_trade": 50.0,
            "max_concurrent_synthetic_positions": 3,
            "max_gross_synthetic_exposure_quote": 150.0,
            "max_holding_sec": 25,
            "cooldown_sec_per_base": 60,
            "one_position_per_base": True,
            "leverage": False,
            "margin": False,
            "real_capital": False,
        },
        "no_grid": {
            "parameter_combinations": 1,
            "grid_search": False,
            "retune": False,
            "threshold_selection_from_returns_or_pnl": False,
            "threshold_selection_from_oos": False,
        },
    }
    evidence = {
        "future_split_if_separately_authorized": {
            "ordering": "valid observations sorted by causal sample_ts",
            "train_fraction": 0.7,
            "oos_fraction": 0.3,
            "split_type": "single contiguous chronological split",
            "embargo_sec": 300,
            "regime_parameters_refit_on_oos": False,
        },
        "strategy_accepted": False,
    }
    contract = {
        "schema": campaign.CONTRACT_SCHEMA,
        "campaign_id": campaign.AEF_CAMPAIGN_ID,
        "hypothesis_id": campaign.HYPOTHESIS_ID,
        "data_type": campaign.DATA_TYPE,
        "execution_sampling_contract": execution,
        "cost_risk_no_grid_contract": cost_risk,
        "evidence_and_acceptance_contract": evidence,
    }
    contract["contract_hash"] = campaign.canonical_contract_hash(contract)
    plan = {
        "schema": campaign.PLAN_SCHEMA,
        "campaign_id": campaign.AEF_CAMPAIGN_ID,
        "hypothesis_id": campaign.HYPOTHESIS_ID,
        "data_type": campaign.DATA_TYPE,
        "contract": {"contract_hash": contract["contract_hash"]},
    }
    plan["plan_hash"] = campaign.canonical_plan_hash(plan)
    return plan, contract


def _draft() -> dict:
    plan, contract = _campaign_sources()
    return build_review_draft(
        campaign_plan=plan,
        campaign_contract=contract,
        plan_path="E:/evidence/plan.json",
        plan_file_sha256="1" * 64,
        contract_path="E:/evidence/contract.json",
        contract_file_sha256="2" * 64,
    )


class DenseWsSignalEvaluatorContractTests(unittest.TestCase):
    def test_builds_deterministic_review_only_draft(self) -> None:
        first = _draft()
        second = _draft()

        self.assertEqual(first, second)
        self.assertEqual(first["schema"], DRAFT_SCHEMA)
        self.assertEqual(first["status"], "DRAFT_NOT_FROZEN_NOT_AUTHORIZED")
        self.assertEqual(first["draft_hash"], canonical_draft_hash(first))
        self.assertFalse(first["evaluation_authorization"]["authorized"])
        self.assertEqual(
            first["next_allowed_action"],
            "USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT",
        )
        validate_review_draft(first)

    def test_freezes_one_cross_venue_formula_and_existing_costs(self) -> None:
        draft = _draft()
        signal = draft["signal_contract"]

        self.assertEqual(signal["eligible_regime"], "DENSE_BOTH")
        self.assertEqual(
            signal["directions"],
            ["buy_mexc_sell_gateio", "buy_gateio_sell_mexc"],
        )
        self.assertEqual(
            signal["gross_edge_bps_formula"],
            "(sell_bid / buy_ask - 1) * 10000",
        )
        self.assertEqual(
            signal["capacity_quote_formula"],
            "min(buy_ask * buy_ask_qty, sell_bid * sell_bid_qty)",
        )
        self.assertEqual(signal["minimum_capacity_quote"], 50.0)
        self.assertEqual(signal["normal_total_cost_bps"], 69.0)
        self.assertEqual(signal["stress_total_cost_bps"], 89.0)
        self.assertEqual(signal["parameter_combinations"], 1)

    def test_keeps_acceptance_thresholds_unset_until_user_review(self) -> None:
        draft = _draft()

        self.assertEqual(
            draft["acceptance_review"]["minimum_trade_events"],
            "UNSET_REQUIRES_USER_REVIEW",
        )
        self.assertEqual(
            draft["acceptance_review"]["minimum_net_expectancy_bps"],
            "UNSET_REQUIRES_USER_REVIEW",
        )
        self.assertFalse(draft["safety"]["returns_read"])
        self.assertFalse(draft["safety"]["pnl_computed"])
        self.assertFalse(draft["safety"]["oos_read"])

    def test_rejects_semantic_tampering_even_with_recomputed_hash(self) -> None:
        draft = copy.deepcopy(_draft())
        draft["signal_contract"]["normal_total_cost_bps"] = 1.0
        draft["draft_hash"] = canonical_draft_hash(draft)

        with self.assertRaisesRegex(DraftIntegrityError, "normal_total_cost_bps"):
            validate_review_draft(draft)

    def test_rejects_any_attempt_to_authorize_evaluation(self) -> None:
        draft = copy.deepcopy(_draft())
        draft["evaluation_authorization"]["authorized"] = True
        draft["safety"]["oos_read"] = True
        draft["draft_hash"] = canonical_draft_hash(draft)

        with self.assertRaisesRegex(DraftIntegrityError, "authorized"):
            validate_review_draft(draft)

    def test_rejects_modified_draft_hash(self) -> None:
        draft = _draft()
        draft["signal_contract"]["minimum_capacity_quote"] = 25.0

        with self.assertRaisesRegex(DraftIntegrityError, "draft hash mismatch"):
            validate_review_draft(draft)

    def test_rejects_source_risk_tampering_with_recomputed_hash(self) -> None:
        draft = copy.deepcopy(_draft())
        draft["source_scope"]["cost_risk_no_grid_contract"]["risk"][
            "max_concurrent_synthetic_positions"
        ] = 99
        draft["draft_hash"] = canonical_draft_hash(draft)

        with self.assertRaisesRegex(DraftIntegrityError, "source_scope"):
            validate_review_draft(draft)

    def test_rejects_unknown_top_level_field_with_recomputed_hash(self) -> None:
        draft = copy.deepcopy(_draft())
        draft["hidden_override"] = {"evaluation_allowed": True}
        draft["draft_hash"] = canonical_draft_hash(draft)

        with self.assertRaisesRegex(DraftIntegrityError, "top-level fields"):
            validate_review_draft(draft)


if __name__ == "__main__":
    unittest.main()
