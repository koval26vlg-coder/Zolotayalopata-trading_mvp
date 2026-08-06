from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dense_ws_acceptance_proposal import (  # noqa: E402
    PROPOSAL_SCHEMA,
    ProposalIntegrityError,
    build_acceptance_proposal,
    canonical_proposal_hash,
    validate_acceptance_proposal,
)
from dense_ws_signal_evaluator_contract import (  # noqa: E402
    canonical_draft_hash,
)


def _review_draft() -> dict:
    draft = {
        "schema": "trading_mvp_dense_ws_signal_evaluator_review_draft_v1",
        "mode": "PlanOnlyReviewDraft",
        "status": "DRAFT_NOT_FROZEN_NOT_AUTHORIZED",
        "research_only": True,
        "source_campaign": {
            "campaign_id": "dense_ws_microstructure_regime_filter_v1_20260803_aef_24h",
            "hypothesis_id": "dense_ws_microstructure_regime_filter_v1",
            "data_type": "DENSE_WS_SEGMENTED",
            "plan": {
                "path": "E:/evidence/plan.json",
                "file_sha256": "1" * 64,
                "plan_hash": "2" * 64,
            },
            "contract": {
                "path": "E:/evidence/contract.json",
                "file_sha256": "3" * 64,
                "contract_hash": "4" * 64,
            },
        },
        "source_scope": {},
        "signal_contract": {
            "source_snapshot_schema": "trading_mvp_dense_ws_execution_snapshot_v1",
            "eligible_regime": "DENSE_BOTH",
            "directions": [
                "buy_mexc_sell_gateio",
                "buy_gateio_sell_mexc",
            ],
            "gross_edge_bps_formula": "(sell_bid / buy_ask - 1) * 10000",
            "capacity_quote_formula": (
                "min(buy_ask * buy_ask_qty, sell_bid * sell_bid_qty)"
            ),
            "minimum_capacity_quote": 50.0,
            "normal_total_cost_bps": 69.0,
            "stress_total_cost_bps": 89.0,
            "cooldown_sec_per_base_and_direction": 60,
            "parameter_combinations": 1,
        },
        "evaluation_design": {
            "primary_split": {
                "train_fraction": 0.7,
                "oos_fraction": 0.3,
                "split_type": "single contiguous chronological split",
                "embargo_sec": 300,
            },
            "walk_forward": {
                "folds": 5,
                "ordering": "chronological",
                "formula_refit_between_folds": False,
                "regime_parameters_refit_on_oos": False,
            },
        },
        "acceptance_review": {
            "minimum_trade_events": "UNSET_REQUIRES_USER_REVIEW",
        },
        "evaluation_authorization": {
            "authorized": False,
            "status": "USER_REVIEW_REQUIRED",
            "materialization_binding_present": False,
            "returns_pnl_oos_allowed": False,
        },
        "safety": {
            "network_access": False,
            "returns_read": False,
            "pnl_computed": False,
            "oos_read": False,
            "grid_or_retune": False,
            "paper_forward": False,
            "live_orders": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
        },
        "next_allowed_action": "USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT",
    }
    draft["draft_hash"] = canonical_draft_hash(draft)
    return draft


def _proposal() -> dict:
    draft = _review_draft()
    payload = json.dumps(draft, sort_keys=True, separators=(",", ":")).encode()
    return build_acceptance_proposal(
        review_draft=draft,
        review_draft_path="E:/evidence/review-draft.json",
        review_draft_file_sha256=hashlib.sha256(payload).hexdigest(),
    )


class DenseWsAcceptanceProposalTests(unittest.TestCase):
    def test_builds_deterministic_non_authorizing_proposal(self) -> None:
        first = _proposal()
        second = _proposal()

        self.assertEqual(first, second)
        self.assertEqual(first["schema"], PROPOSAL_SCHEMA)
        self.assertEqual(first["status"], "PROPOSAL_NOT_FROZEN_NOT_AUTHORIZED")
        self.assertEqual(first["proposal_hash"], canonical_proposal_hash(first))
        self.assertFalse(first["authorization"]["authorized"])
        self.assertFalse(first["authorization"]["returns_pnl_oos_allowed"])
        validate_acceptance_proposal(first)

    def test_defines_latency_aware_realization_before_results_exist(self) -> None:
        proposal = _proposal()
        execution = proposal["execution_realization_proposal"]

        self.assertEqual(execution["normal_latency_ms"], 250)
        self.assertEqual(execution["stress_latency_ms"], 1000)
        self.assertEqual(execution["normal_total_cost_bps"], 69.0)
        self.assertEqual(execution["stress_total_cost_bps"], 89.0)
        self.assertTrue(execution["both_legs_required"])
        self.assertTrue(execution["unfillable_events_remain_in_fill_rate_denominator"])
        self.assertEqual(
            execution["outcome_quote_selection"],
            "latest raw BBO with recv_ts <= execution_ts; no future quote",
        )

    def test_recommends_strict_but_day_compatible_sample_and_economics_gates(self) -> None:
        proposal = _proposal()
        sample = proposal["acceptance_threshold_proposal"]["sample"]
        economics = proposal["acceptance_threshold_proposal"]["economics"]
        robustness = proposal["acceptance_threshold_proposal"]["robustness"]

        self.assertEqual(sample["minimum_total_independent_events"], 60)
        self.assertEqual(sample["minimum_train_events"], 40)
        self.assertEqual(sample["minimum_oos_events"], 20)
        self.assertEqual(sample["minimum_events_per_walk_forward_fold"], 8)
        self.assertEqual(sample["minimum_distinct_utc_hours"], 8)
        self.assertEqual(sample["minimum_distinct_bases"], 8)
        self.assertEqual(economics["oos_normal_profit_factor_gte"], 1.2)
        self.assertEqual(economics["oos_stress_profit_factor_gte"], 1.0)
        self.assertEqual(robustness["minimum_positive_walk_forward_folds"], 4)
        self.assertEqual(robustness["maximum_drawdown_quote"], 15.0)

    def test_caps_historical_result_at_public_paper_forward(self) -> None:
        proposal = _proposal()
        decisions = proposal["decision_contract_proposal"]

        self.assertEqual(
            decisions["maximum_historical_verdict"],
            "ACCEPT_FOR_PUBLIC_READONLY_PAPER_FORWARD",
        )
        self.assertFalse(decisions["historical_result_can_accept_strategy"])
        self.assertEqual(
            decisions["insufficient_sample_verdict"],
            "INSUFFICIENT_DATA_NOT_REJECTED",
        )

    def test_rejects_semantic_tampering_even_with_recomputed_hash(self) -> None:
        proposal = copy.deepcopy(_proposal())
        proposal["acceptance_threshold_proposal"]["economics"][
            "oos_normal_profit_factor_gte"
        ] = 0.5
        proposal["proposal_hash"] = canonical_proposal_hash(proposal)

        with self.assertRaisesRegex(ProposalIntegrityError, "acceptance thresholds"):
            validate_acceptance_proposal(proposal)

    def test_rejects_attempt_to_authorize_with_recomputed_hash(self) -> None:
        proposal = copy.deepcopy(_proposal())
        proposal["authorization"]["authorized"] = True
        proposal["authorization"]["returns_pnl_oos_allowed"] = True
        proposal["proposal_hash"] = canonical_proposal_hash(proposal)

        with self.assertRaisesRegex(ProposalIntegrityError, "authorization"):
            validate_acceptance_proposal(proposal)

    def test_source_file_verification_is_optional_and_exact(self) -> None:
        draft = _review_draft()
        source_sha = "5" * 64
        proposal = build_acceptance_proposal(
            review_draft=draft,
            review_draft_path="E:/evidence/review.json",
            review_draft_file_sha256=source_sha,
        )

        with patch("dense_ws_acceptance_proposal._sha256_file", return_value=source_sha), patch(
            "dense_ws_acceptance_proposal._read_json", return_value=draft
        ):
            validate_acceptance_proposal(proposal, verify_source_file=True)

        with patch("dense_ws_acceptance_proposal._sha256_file", return_value="6" * 64):
            with self.assertRaisesRegex(ProposalIntegrityError, "source review file"):
                validate_acceptance_proposal(proposal, verify_source_file=True)


if __name__ == "__main__":
    unittest.main()
