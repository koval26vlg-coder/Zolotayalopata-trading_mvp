from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TRADING_ROOT = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# The sibling test module below is imported by bare name, which only resolves when
# this directory is on sys.path. Discovery puts it there; running the suite from the
# repository root does not, and the file then fails to import for a reason that has
# nothing to do with what it tests. Stating it here makes the module work either way.
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import gate_membership_momentum_v2_execution_probe as probe  # noqa: E402
import gate_historical_membership_v3_history_plan as v3_history_plan  # noqa: E402
from gate_membership_momentum import DAY_SEC  # noqa: E402
import gate_membership_momentum_v2_train as v2_train  # noqa: E402
from gate_membership_momentum_v2_oos import (  # noqa: E402
    build_oos_plan,
    evaluate_oos_plan,
)
from test_gate_membership_momentum_v2_oos import (  # noqa: E402
    START_DAY,
    _authorized_inputs,
)


def _historical_accept(root: Path) -> tuple[Path, dict, Path, dict]:
    quality_path, train_plan, train_result_path, train_result = _authorized_inputs(root)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    oos_plan_path = root / "oos-plan.json"
    oos_plan = build_oos_plan(
        quality_report_path=quality_path,
        expected_quality_hash=quality["artifact_hash"],
        train_plan_path=root / "train-plan.json",
        expected_train_plan_hash=train_plan["plan_hash"],
        train_result_path=train_result_path,
        expected_train_result_hash=train_result["deterministic_result_hash"],
        output_path=oos_plan_path,
        run_id="membership-momentum-v2-oos",
        max_runtime_sec=120,
    )
    oos_result_path = root / "oos-result.json"
    oos_result = evaluate_oos_plan(
        plan_path=oos_plan_path,
        expected_plan_hash=oos_plan["plan_hash"],
        output_path=oos_result_path,
        max_runtime_sec=120,
    )
    return oos_plan_path, oos_plan, oos_result_path, oos_result


class GateMembershipMomentumV2ExecutionProbeTests(unittest.TestCase):
    def test_planonly_module_exists(self) -> None:
        try:
            module = importlib.import_module("gate_membership_momentum_v2_execution_probe")
        except ModuleNotFoundError:
            module = None

        self.assertIsNotNone(module, "momentum-v2 execution-probe PlanOnly module is missing")

    def test_plan_is_causal_hash_bound_and_globally_anchored(self) -> None:
        builder = getattr(probe, "build_execution_probe_plan", None)
        self.assertTrue(callable(builder), "execution-probe PlanOnly builder is missing")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
            not_before_day = START_DAY + 223
            plan = builder(
                oos_plan_path=oos_plan_path,
                expected_oos_plan_hash=oos_plan["plan_hash"],
                oos_result_path=oos_result_path,
                expected_oos_result_hash=oos_result["deterministic_result_hash"],
                output_path=root / "probe-plan.json",
                run_id="membership-momentum-v2-probe",
                not_before_day=not_before_day,
                generated_at_utc="2026-07-17T09:00:00Z",
            )

            self.assertEqual(plan["decision"], probe.PLAN_DECISION)
            self.assertEqual(plan["plan_hash"], probe.execution_probe_plan_hash(plan))
            self.assertNotIn("candidates", plan)
            self.assertNotIn("events", plan)
            target = plan["target_event_contract"]
            self.assertEqual(target["anchor_day"], oos_plan["rebalance_schedule_contract"]["anchor_day"])
            self.assertEqual(target["cadence_days"], 7)
            self.assertEqual(target["not_before_day"], not_before_day)
            self.assertEqual(target["target_signal_day"], START_DAY + 226)
            self.assertEqual(target["target_entry_day"], START_DAY + 227)
            self.assertEqual((target["target_signal_day"] - target["anchor_day"]) % 7, 0)

            selection = plan["selection_contract"]
            self.assertFalse(selection["oos_event_frequency_used"])
            self.assertIn("oos_event_asset_names_used", selection)
            self.assertFalse(selection["oos_event_asset_names_used"])
            self.assertNotIn("oos_event_asset_names_read", selection)
            self.assertFalse(selection["manual_shortlist"])
            self.assertTrue(selection["selection_artifact_required"])
            self.assertTrue(selection["selection_artifact_frozen_before_first_snapshot"])
            self.assertEqual(selection["selection_price"], "target_signal_closed_daily_close")
            self.assertEqual(selection["strategy"], oos_plan["strategy"])

            execution = plan["execution_contract"]
            self.assertEqual(execution["selected_buckets"], ["long", "short"])
            self.assertEqual(execution["book_walk_sides"], ["buy", "sell"])
            self.assertEqual(execution["notional_quote_per_asset"], 500.0)
            windows = execution["windows"]
            self.assertEqual(len(windows), 3)
            starts = [datetime.fromisoformat(row["start_utc"].replace("Z", "+00:00")) for row in windows]
            self.assertTrue(all(value.tzinfo == timezone.utc for value in starts))
            self.assertEqual([int((value - starts[0]).total_seconds()) for value in starts], [0, 14_400, 28_800])
            self.assertEqual(execution["duration_sec"], 1_200)
            self.assertEqual(execution["interval_sec"], 5)
            self.assertEqual(execution["minimum_valid_snapshots_per_asset_per_window"], 180)
            self.assertEqual(execution["minimum_coverage_per_asset"], 0.80)
            self.assertEqual(execution["maximum_p95_impact_bps"], 10.0)
            self.assertEqual(execution["target_entry_ts"], target["target_entry_day"] * DAY_SEC)

    def test_validator_rejects_rehashed_loosened_execution_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
            plan_path = root / "probe-plan.json"
            plan = probe.build_execution_probe_plan(
                oos_plan_path=oos_plan_path,
                expected_oos_plan_hash=oos_plan["plan_hash"],
                oos_result_path=oos_result_path,
                expected_oos_result_hash=oos_result["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-probe",
                not_before_day=START_DAY + 223,
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["frozen_contract"]["execution_contract"]["maximum_p95_impact_bps"] = 100.0
            payload["execution_contract"] = payload["frozen_contract"]["execution_contract"]
            payload["plan_hash"] = v3_history_plan.sha256_json(payload["frozen_contract"])
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "execution contract"):
                probe.validate_execution_probe_plan(plan_path, payload["plan_hash"])

            self.assertNotEqual(plan["plan_hash"], payload["plan_hash"])

    def test_validator_rejects_rehashed_selection_strategy_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
            plan_path = root / "probe-plan.json"
            probe.build_execution_probe_plan(
                oos_plan_path=oos_plan_path,
                expected_oos_plan_hash=oos_plan["plan_hash"],
                oos_result_path=oos_result_path,
                expected_oos_result_hash=oos_result["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-probe",
                not_before_day=START_DAY + 223,
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["frozen_contract"]["selection_contract"]["strategy"]["lookback_days"] = 1
            payload["selection_contract"] = payload["frozen_contract"]["selection_contract"]
            payload["plan_hash"] = v3_history_plan.sha256_json(payload["frozen_contract"])
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "selection contract"):
                probe.validate_execution_probe_plan(plan_path, payload["plan_hash"])

    def test_validator_rejects_rehashed_input_merkle_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
            plan_path = root / "probe-plan.json"
            probe.build_execution_probe_plan(
                oos_plan_path=oos_plan_path,
                expected_oos_plan_hash=oos_plan["plan_hash"],
                oos_result_path=oos_result_path,
                expected_oos_result_hash=oos_result["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-probe",
                not_before_day=START_DAY + 223,
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["frozen_contract"]["input_merkle_sha256"] = "f" * 64
            payload["input_merkle_sha256"] = "f" * 64
            payload["plan_hash"] = v3_history_plan.sha256_json(payload["frozen_contract"])
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "input merkle"):
                probe.validate_execution_probe_plan(plan_path, payload["plan_hash"])

    def test_plan_hash_is_independent_of_generated_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
            common = {
                "oos_plan_path": oos_plan_path,
                "expected_oos_plan_hash": oos_plan["plan_hash"],
                "oos_result_path": oos_result_path,
                "expected_oos_result_hash": oos_result["deterministic_result_hash"],
                "output_path": None,
                "run_id": "membership-momentum-v2-probe",
                "not_before_day": START_DAY + 223,
            }
            first = probe.build_execution_probe_plan(
                **common,
                generated_at_utc="2026-07-17T09:00:00Z",
            )
            second = probe.build_execution_probe_plan(
                **common,
                generated_at_utc="2026-07-17T10:00:00Z",
            )

            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertEqual(first["frozen_contract"], second["frozen_contract"])
            self.assertNotEqual(first["generated_at_utc"], second["generated_at_utc"])

    def test_non_accept_oos_result_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oos_plan_path, oos_plan, oos_result_path, oos_result = _historical_accept(root)
            oos_result["decision"] = "GATE_MEMBERSHIP_MOMENTUM_V2_OOS_REJECTED_NO_RETUNE"
            oos_result["deterministic_result_hash"] = v2_train._deterministic_result_hash(oos_result)
            oos_result_path.write_text(json.dumps(oos_result), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "historical ACCEPT"):
                probe.build_execution_probe_plan(
                    oos_plan_path=oos_plan_path,
                    expected_oos_plan_hash=oos_plan["plan_hash"],
                    oos_result_path=oos_result_path,
                    expected_oos_result_hash=oos_result["deterministic_result_hash"],
                    output_path=None,
                    run_id="membership-momentum-v2-probe",
                    not_before_day=START_DAY + 223,
                )

    def test_run_mvp_exposes_plan_and_validate_actions(self) -> None:
        script = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((TRADING_ROOT / "run_mvp.ps1"))

        self.assertIn('"fast-edge-membership-momentum-v2-execution-probe-plan"', script)
        self.assertIn('"fast-edge-membership-momentum-v2-execution-probe-validate"', script)
        self.assertIn("gate_membership_momentum_v2_execution_probe.py", script)
        self.assertIn('"--not-before-day", $NotBeforeDay', script)


if __name__ == "__main__":
    unittest.main()
