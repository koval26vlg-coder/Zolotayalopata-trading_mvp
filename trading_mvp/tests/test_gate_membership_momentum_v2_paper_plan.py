from __future__ import annotations

import json
import importlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
TRADING_ROOT = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import gate_historical_membership_v3_history_plan as v3_history_plan  # noqa: E402
import gate_membership_momentum_v2_execution_probe_runtime as runtime  # noqa: E402
from test_gate_membership_momentum_v2_execution_probe_runtime import (  # noqa: E402
    _selection,
    _window_plan,
    _write_samples,
)


PAPER_MODULE_AVAILABLE = importlib.util.find_spec(
    "gate_membership_momentum_v2_paper_plan"
) is not None
paper = (
    importlib.import_module("gate_membership_momentum_v2_paper_plan")
    if PAPER_MODULE_AVAILABLE
    else None
)


def _accepted_execution_report(root: Path) -> tuple[Path, dict]:
    probe_path, probe_plan, selection_path, selection_result = _selection(root)
    manifests: list[Path] = []
    for window_index in range(3):
        plan_path, plan = _window_plan(
            root,
            probe_path=probe_path,
            probe_plan=probe_plan,
            selection_path=selection_path,
            selection_result=selection_result,
            window_index=window_index,
        )
        _write_samples(plan)
        runtime.finalize_execution_probe_window(
            plan_path=plan_path,
            expected_plan_hash=plan["plan_hash"],
            completed_cycles=240,
            errors=[],
            critical_errors=[],
            runtime_sec=1200.0,
        )
        manifests.append(Path(plan["output_contract"]["manifest_path"]))
    report_path = root / "execution-report.json"
    report = runtime.evaluate_execution_probe_windows(
        probe_plan_path=probe_path,
        expected_probe_plan_hash=probe_plan["plan_hash"],
        selection_path=selection_path,
        expected_selection_hash=selection_result["artifact_hash"],
        manifest_paths=manifests,
        output_path=report_path,
    )
    return report_path, report


class GateMembershipMomentumV2PaperModuleTests(unittest.TestCase):
    def test_paper_plan_module_exists(self) -> None:
        self.assertTrue(PAPER_MODULE_AVAILABLE, "momentum-v2 paper PlanOnly module is missing")


@unittest.skipUnless(PAPER_MODULE_AVAILABLE, "paper PlanOnly module is not implemented yet")
class GateMembershipMomentumV2PaperPlanTests(unittest.TestCase):
    def test_ready_execution_report_builds_hash_bound_paper_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path, report = _accepted_execution_report(root)
            plan_path = root / "paper-plan.json"
            plan = paper.build_paper_plan(
                execution_report_path=report_path,
                expected_execution_report_hash=report["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-paper",
                generated_at_utc="2026-07-17T12:00:00Z",
            )

            self.assertEqual(plan["decision"], paper.PLAN_DECISION)
            self.assertEqual(plan["plan_hash"], paper.paper_plan_hash(plan))
            self.assertEqual(plan["paper_contract"]["minimum_independent_events"], 15)
            self.assertEqual(plan["paper_contract"]["notional_quote_per_asset"], 500.0)
            self.assertEqual(plan["paper_contract"]["event_cadence_days"], 7)
            self.assertTrue(plan["paper_contract"]["selection_artifact_required"])
            self.assertTrue(plan["paper_contract"]["entry_execution_evidence_required"])
            self.assertTrue(plan["paper_contract"]["exit_execution_evidence_required"])
            self.assertTrue(plan["paper_contract"]["funding_settlement_evidence_required"])
            self.assertFalse(plan["paper_contract"]["manual_pnl_allowed"])
            self.assertFalse(plan["network_access"])
            self.assertFalse(plan["paper_forward_started"])
            self.assertFalse(plan["live_orders"])
            self.assertIn(plan["plan_hash"], plan["approval_phrase"])
            self.assertEqual(plan["next_allowed_command"], plan["approval_phrase"])

            validated = paper.validate_paper_plan(plan_path, plan["plan_hash"])
            self.assertEqual(validated["plan_hash"], plan["plan_hash"])
            self.assertEqual(
                validated["execution_report_authorization"]["result_hash"],
                report["deterministic_result_hash"],
            )

    def test_plan_hash_is_independent_of_generated_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path, report = _accepted_execution_report(root)
            common = {
                "execution_report_path": report_path,
                "expected_execution_report_hash": report["deterministic_result_hash"],
                "output_path": None,
                "run_id": "membership-momentum-v2-paper",
            }
            first = paper.build_paper_plan(
                **common,
                generated_at_utc="2026-07-17T12:00:00Z",
            )
            second = paper.build_paper_plan(
                **common,
                generated_at_utc="2026-07-17T13:00:00Z",
            )
            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertEqual(first["frozen_contract"], second["frozen_contract"])
            self.assertNotEqual(first["generated_at_utc"], second["generated_at_utc"])

    def test_rejected_or_tampered_execution_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path, report = _accepted_execution_report(root)
            report["verdict"] = runtime.REJECT_DECISION
            report["deterministic_result_hash"] = runtime._artifact_hash(report)
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PAPER_FORWARD_READY"):
                paper.build_paper_plan(
                    execution_report_path=report_path,
                    expected_execution_report_hash=report["deterministic_result_hash"],
                    output_path=None,
                    run_id="rejected",
                )

            clean_root = root / "clean"
            clean_root.mkdir()
            clean_path, clean = _accepted_execution_report(clean_root)
            clean["selected_assets"] = clean["selected_assets"][:-1]
            clean_path.write_text(json.dumps(clean), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                paper.build_paper_plan(
                    execution_report_path=clean_path,
                    expected_execution_report_hash=clean["deterministic_result_hash"],
                    output_path=None,
                    run_id="tampered",
                )

    def test_validator_rejects_rehashed_relaxed_paper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path, report = _accepted_execution_report(root)
            plan_path = root / "paper-plan.json"
            paper.build_paper_plan(
                execution_report_path=report_path,
                expected_execution_report_hash=report["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-paper",
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["frozen_contract"]["paper_contract"]["minimum_independent_events"] = 1
            payload["paper_contract"] = payload["frozen_contract"]["paper_contract"]
            payload["plan_hash"] = v3_history_plan.sha256_json(payload["frozen_contract"])
            payload["approval_phrase"] = paper.approval_phrase(payload["plan_hash"])
            payload["next_allowed_command"] = payload["approval_phrase"]
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "minimum independent events"):
                paper.validate_paper_plan(plan_path, payload["plan_hash"])

    def test_run_mvp_exposes_paper_plan_and_validation_routes(self) -> None:
        wrapper = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((TRADING_ROOT / "run_mvp.ps1"))
        self.assertIn('"fast-edge-membership-momentum-v2-paper-plan"', wrapper)
        self.assertIn('"fast-edge-membership-momentum-v2-paper-validate"', wrapper)
        self.assertIn("gate_membership_momentum_v2_paper_plan.py", wrapper)


if __name__ == "__main__":
    unittest.main()
