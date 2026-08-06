from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feasibility_gate import (  # noqa: E402
    CANONICAL_MIN_TOTAL_EVENTS,
    evaluate_feasibility,
    plan_hash,
    validate_frozen_plan,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _plan(**feasibility_inputs: object) -> dict:
    payload: dict = {
        "schema": "fixture_fast_first_plan_v1",
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "evaluation_allowed": False,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_metrics": {},
        "observed_performance": {},
        "hypothesis": {"id": "fixture_hypothesis_v1"},
        "sealed_input": {"input_merkle_sha256": "a" * 64},
        "signal": {"venues": ["mexc", "gateio"]},
        "validation": {
            "acceptance_gates": {
                "minimum_oos_portfolio_events_total": 20,
                "minimum_oos_portfolio_events_per_venue": 10,
                "minimum_unique_oos_signal_dates": 10,
                "minimum_capacity_proxy_quote_per_selected_leg": 500.0,
            }
        },
        "feasibility_inputs": feasibility_inputs,
        "data_access_audit": {
            "oos_returns_read": False,
            "pnl_computed": False,
            "signal_scores_computed": False,
            "performance_metrics_computed": False,
        },
    }
    payload["plan_hash"] = plan_hash(payload)
    return payload


class FeasibilityGateTests(unittest.TestCase):
    def test_feasible_plan_passes_without_reading_oos_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = root / "plan.json"
            output_path = root / "feasibility.json"
            _write_json(
                plan_path,
                _plan(
                    train_candidate_events=200,
                    train_valid_events=200,
                    oos_candidate_events=40,
                    per_venue_oos_candidate_events={"mexc": 20, "gateio": 20},
                    unique_oos_dates=20,
                    dual_venue_coverage=1.0,
                    capacity_proxy_quote_per_selected_leg=750.0,
                ),
            )

            result = evaluate_feasibility(plan_path, output_path=output_path)

            self.assertEqual(result["schema"], "fast_first_feasibility_gate_v1")
            self.assertEqual(result["verdict"], "FEASIBLE_FOR_OOS")
            self.assertEqual(result["rejection_reasons"], [])
            self.assertFalse(result["oos_metrics_read"])
            self.assertFalse(result["pnl_or_returns_read"])
            self.assertFalse(result["grid_search"])
            self.assertFalse(result["retune"])
            self.assertEqual(result["next_allowed_action"], "run_visible_owned_no_grid_oos")
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["deterministic_result_hash"], result["deterministic_result_hash"])

    def test_infeasible_plan_blocks_oos_on_conservative_lower_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "plan.json"
            _write_json(
                plan_path,
                _plan(
                    train_candidate_events=20,
                    train_valid_events=10,
                    oos_candidate_events=20,
                    per_venue_oos_candidate_events={"mexc": 10, "gateio": 10},
                    unique_oos_dates=10,
                    dual_venue_coverage=1.0,
                    capacity_proxy_quote_per_selected_leg=500.0,
                ),
            )

            result = evaluate_feasibility(plan_path)

            self.assertEqual(result["verdict"], "INFEASIBLE_ON_CURRENT_DATA")
            self.assertIn("lower_bound_oos_portfolio_events_total_below_minimum", result["rejection_reasons"])
            self.assertLess(
                result["forecast"]["conservative_90_lower_oos_event_count"],
                CANONICAL_MIN_TOTAL_EVENTS,
            )
            self.assertEqual(
                result["next_allowed_action"],
                "bank_hypothesis_with_data_requirements_do_not_run_oos",
            )

    def test_canonical_gates_override_relaxed_plan_thresholds(self) -> None:
        plan = _plan(
            train_candidate_events=200,
            train_valid_events=200,
            oos_candidate_events=12,
            per_venue_oos_candidate_events={"mexc": 6, "gateio": 6},
            unique_oos_dates=6,
            dual_venue_coverage=1.0,
            capacity_proxy_quote_per_selected_leg=500.0,
        )
        plan["validation"]["acceptance_gates"]["minimum_oos_portfolio_events_total"] = 8
        plan["validation"]["acceptance_gates"]["minimum_oos_portfolio_events_per_venue"] = 4
        plan["validation"]["acceptance_gates"]["minimum_unique_oos_signal_dates"] = 4
        plan["plan_hash"] = plan_hash(plan)

        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "plan.json"
            _write_json(plan_path, plan)

            result = evaluate_feasibility(plan_path)

        self.assertEqual(result["acceptance_gates"]["minimum_oos_portfolio_events_total"], 20)
        self.assertEqual(result["acceptance_gates"]["minimum_oos_portfolio_events_per_venue"], 10)
        self.assertEqual(result["verdict"], "INFEASIBLE_ON_CURRENT_DATA")

    def test_plan_with_observed_oos_metrics_is_rejected_before_feasibility(self) -> None:
        plan = _plan(
            train_candidate_events=200,
            train_valid_events=200,
            oos_candidate_events=40,
            per_venue_oos_candidate_events={"mexc": 20, "gateio": 20},
            unique_oos_dates=20,
        )
        plan["oos_metrics"] = {"net_pnl_quote": 1.0}
        plan["plan_hash"] = plan_hash(plan)

        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "plan.json"
            _write_json(plan_path, plan)

            with self.assertRaisesRegex(ValueError, "OOS/observed performance"):
                evaluate_feasibility(plan_path)

    def test_missing_explicit_feasibility_inputs_blocks_oos_fail_closed(self) -> None:
        plan = _plan(
            train_candidate_events=200,
            train_valid_events=200,
            oos_candidate_events=40,
            per_venue_oos_candidate_events={"mexc": 20, "gateio": 20},
            unique_oos_dates=20,
        )
        del plan["feasibility_inputs"]
        plan["data_availability"] = {"candidate_weekend_entry_days": 40}
        plan["plan_hash"] = plan_hash(plan)

        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "plan.json"
            _write_json(plan_path, plan)

            result = evaluate_feasibility(plan_path)

        self.assertEqual(result["verdict"], "FEASIBILITY_BLOCKED_BAD_INPUT")
        self.assertIn("missing_explicit_feasibility_inputs", result["rejection_reasons"])
        self.assertEqual(result["next_allowed_action"], "fix_planonly_feasibility_inputs_before_oos")

    def test_plan_hash_tampering_is_rejected(self) -> None:
        plan = _plan(train_candidate_events=1, train_valid_events=1, oos_candidate_events=1)
        plan["signal"]["venues"] = ["mexc"]

        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_frozen_plan(plan)

    def test_deterministic_result_hash_ignores_timestamp_and_output_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = root / "plan.json"
            _write_json(
                plan_path,
                _plan(
                    train_candidate_events=200,
                    train_valid_events=200,
                    oos_candidate_events=40,
                    per_venue_oos_candidate_events={"mexc": 20, "gateio": 20},
                    unique_oos_dates=20,
                ),
            )

            first = evaluate_feasibility(plan_path)
            second = evaluate_feasibility(plan_path)

            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(len(hashlib.sha256(first["deterministic_result_hash"].encode()).hexdigest()), 64)


if __name__ == "__main__":
    unittest.main()
