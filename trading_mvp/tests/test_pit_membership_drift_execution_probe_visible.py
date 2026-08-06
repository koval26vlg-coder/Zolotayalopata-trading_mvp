from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from trading_mvp.tests import test_pit_membership_drift_pipeline as pit_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "start_pit_membership_drift_execution_probe_visible.ps1"
RUN_MVP = REPO_ROOT / "trading_mvp" / "run_mvp.ps1"


class PitMembershipDriftExecutionProbeVisibleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        root = Path(cls._temp.name)
        fixture = pit_fixture.PitMembershipDriftPipelineTests()
        train_path, train, bank, ledger, contract = fixture._train_plan(root, days=120)
        feasibility_path = root / "feasibility.json"
        feasibility = pit_fixture.run_train_feasibility(
            train_path,
            expected_plan_hash=train["plan_hash"],
            output_path=feasibility_path,
        )
        full_path = root / "full.json"
        full = pit_fixture.build_evaluation_input_plan(
            quality_ledger_path=ledger,
            hypothesis_bank_path=bank,
            hypothesis_id=contract["id"],
            output_path=full_path,
            plan_stage="full_evaluation",
            train_plan_path=train_path,
            feasibility_path=feasibility_path,
        )
        evaluation_path = root / "evaluation.json"
        pit_fixture.run_oos_evaluation(
            full_path,
            expected_plan_hash=full["plan_hash"],
            feasibility_path=feasibility_path,
            output_path=evaluation_path,
        )
        from pit_membership_drift_execution_probe import build_execution_probe_plan

        plan_path = root / "probe-plan.json"
        plan = build_execution_probe_plan(evaluation_path, plan_path)
        cls.root = root
        cls.plan_path = plan_path
        cls.plan = plan

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    @staticmethod
    def _write_gate(path: Path, *, status: str = "READY_FOR_POSTPROCESS") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "historical-evaluation",
                    "status": status,
                    "gate_status": status,
                    "next_goal_decision": "PIT_ACCEPT_FOR_SHORT_EXECUTION_PROBE_REQUIRES_EXPLICIT_APPROVAL",
                    "evaluation_result_hash": "fixture",
                    "replay_allowed": False,
                }
            ),
            encoding="utf-8",
        )

    def test_planonly_is_read_only_and_exposes_exact_confirmation(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"missing visible execution-probe wrapper: {SCRIPT}")
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        root = self.root / "planonly-wrapper"
        root.mkdir()
        gate = root / "active-run-gate.json"
        current = root / "current-run.json"
        self._write_gate(gate)
        current.write_bytes(gate.read_bytes())
        gate_hash = hashlib.sha256(gate.read_bytes()).hexdigest()
        output_root = root / "output"

        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-PlanPath",
                str(self.plan_path),
                "-ExpectedPlanHash",
                self.plan["plan_hash"],
                "-OutputRoot",
                str(output_root),
                "-RunId",
                "probe-planonly",
                "-GatePath",
                str(gate),
                "-CurrentRunPath",
                str(current),
                "-PlanOnly",
                "-HoldOpenSec",
                "0",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["decision"], "PLAN_ONLY")
        self.assertFalse(payload["would_start"])
        self.assertTrue(payload["visible_terminal"])
        self.assertEqual(payload["duration_sec"], 1200)
        self.assertEqual(payload["plan_hash"], self.plan["plan_hash"])
        self.assertEqual(payload["approval_phrase"], self.plan["approval_phrase"])
        self.assertFalse(payload["network_access"])
        self.assertFalse(payload["paper_forward"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(output_root.exists())
        self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_hash)

    def test_wrapper_and_run_mvp_enforce_owned_visible_probe_scope(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"missing visible execution-probe wrapper: {SCRIPT}")
        source = SCRIPT.read_text(encoding="utf-8")
        run_mvp = RUN_MVP.read_text(encoding="utf-8")

        self.assertIn("ConfirmedExecutionProbe", source)
        self.assertIn("Start-Process", source)
        self.assertIn("-WindowStyle Normal", source)
        self.assertIn("attempted_snapshots", source)
        self.assertIn("elapsed_active_sec", source)
        self.assertIn("PIT_MEMBERSHIP_DRIFT_EXECUTION_PROBE_RUNNING", source)
        self.assertNotIn('"ws-grid-search"', source)
        self.assertNotIn('"paper-forward-segment"', source)
        self.assertIn('"fast-edge-pit-execution-probe-plan"', run_mvp)
        self.assertIn('"fast-edge-pit-execution-probe-evaluate"', run_mvp)
        self.assertIn('"fast-edge-pit-paper-plan"', run_mvp)
        self.assertIn("$ownedPitExecutionProbeRun", run_mvp)
        self.assertIn("paper-forward-plan.json", source)
        self.assertIn("-Action fast-edge-pit-paper-plan", source)
        self.assertIn("paper_forward_plan_hash", source)
        self.assertIn("paper_forward_approval_phrase", source)
        self.assertNotIn("-Action fast-edge-pit-paper-evaluate", source)
        self.assertNotIn("create_paper_forward_approval", source)
        self.assertNotIn('"approve"', source)


if __name__ == "__main__":
    unittest.main()
