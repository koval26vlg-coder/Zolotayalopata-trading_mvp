from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from trading_mvp.tests import test_pit_membership_drift_pipeline as pit_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "run_pit_full_evaluation_visible.ps1"
RUN_MVP = REPO_ROOT / "trading_mvp" / "run_mvp.ps1"


class PitFullEvaluationVisibleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"missing visible full-evaluation wrapper: {SCRIPT}")

    @staticmethod
    def _gate(path: Path, *, run_id: str = "previous-run", status: str = "READY_FOR_POSTPROCESS") -> None:
        path.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": run_id,
                    "status": status,
                    "gate_status": status,
                    "replay_allowed": False,
                }
            ),
            encoding="utf-8",
        )

    def _base_command(self, pwsh: str, root: Path) -> list[str]:
        artifact_root = root / "artifacts"
        ledger = root / "quality.jsonl"
        bank = root / "bank.json"
        train_plan = root / "train-plan.json"
        feasibility = root / "feasibility.json"
        for path in (ledger, bank, train_plan, feasibility):
            path.write_text("{}\n" if path.suffix == ".json" else "", encoding="utf-8")
        gate = root / "active-run-gate.json"
        current = root / "current-run.json"
        self._gate(gate)
        current_payload = json.loads(gate.read_text(encoding="utf-8"))
        current_payload["schema"] = "active_run_pointer_v1"
        current.write_text(json.dumps(current_payload), encoding="utf-8")
        return [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RunId",
            "pit_full_evaluation_test",
            "-ArtifactRoot",
            str(artifact_root),
            "-QualityLedgerPath",
            str(ledger),
            "-HypothesisBankPath",
            str(bank),
            "-TrainPlanPath",
            str(train_plan),
            "-FeasibilityPath",
            str(feasibility),
            "-GatePath",
            str(gate),
            "-CurrentRunPath",
            str(current),
            "-HoldOpenSec",
            "0",
            "-MaxRuntimeSec",
            "1800",
        ]

    def test_planonly_is_read_only_and_describes_visible_owned_oos_run(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command = self._base_command(pwsh, root) + ["-PlanOnly"]
            gate = root / "active-run-gate.json"
            gate_sha = hashlib.sha256(gate.read_bytes()).hexdigest()

            completed = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"], "PLAN_ONLY")
            self.assertEqual(payload["stage"], "full_evaluation")
            self.assertTrue(payload["visible_terminal"])
            self.assertEqual(payload["external_deterministic_repeats"], 2)
            self.assertFalse(payload["network_access"])
            self.assertFalse(payload["grid_search"])
            self.assertFalse(payload["retune"])
            self.assertFalse(payload["paper_forward"])
            self.assertFalse(payload["live_orders"])
            self.assertFalse(Path(payload["full_plan_path"]).exists())
            self.assertFalse(Path(payload["evaluation_path"]).exists())
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_sha)

    def test_worker_refuses_missing_ownership_token(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                self._base_command(pwsh, Path(temp_dir)) + ["-Worker"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ownership token", completed.stderr + completed.stdout)

    def test_wrapper_has_only_frozen_full_evaluation_actions(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"fast-edge-pit-input-plan"', source)
        self.assertIn('"fast-edge-pit-evaluate"', source)
        self.assertIn('"fast-edge-pit-execution-probe-plan"', source)
        self.assertIn('"full_evaluation"', source)
        self.assertIn("deterministic_result_hash", source)
        self.assertIn("Start-Process", source)
        self.assertIn("-WindowStyle Normal", source)
        self.assertNotIn('"fast-edge-pit-feasibility"', source)
        self.assertNotIn('"ws-grid-search"', source)
        self.assertNotIn('"paper-forward-segment"', source)

    def test_owned_actions_are_scoped_to_full_evaluation_gate(self) -> None:
        source = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(RUN_MVP)
        self.assertIn("$ownedPitFullEvaluationRun", source)
        self.assertIn('"fast-edge-pit-input-plan", "fast-edge-pit-evaluate", "fast-edge-pit-execution-probe-plan"', source)
        self.assertIn('"PIT_FULL_EVALUATION_RUNNING"', source)
        self.assertIn("-not $ownedPitFullEvaluationRun", source)

    def test_worker_completes_owned_full_evaluation_on_120_date_fixture(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = pit_fixture.PitMembershipDriftPipelineTests()
            train_plan_path, train_plan, bank, ledger, contract = fixture._train_plan(root, days=120)
            feasibility_path = root / "train-feasibility.json"
            feasibility = pit_fixture.run_train_feasibility(
                train_plan_path,
                expected_plan_hash=train_plan["plan_hash"],
                output_path=feasibility_path,
            )
            self.assertEqual(feasibility["verdict"], "FEASIBLE_FOR_OOS")

            artifact_root = root / "artifacts"
            run_id = "pit_full_evaluation_fixture"
            full_plan = artifact_root / f"{run_id}.full-input-plan.json"
            evaluation = artifact_root / f"{run_id}.evaluation.json"
            repeat = artifact_root / f"{run_id}.evaluation.repeat.json"
            manifest = artifact_root / f"{run_id}.manifest.json"
            probe_plan = artifact_root / f"{run_id}.execution-probe-plan.json"
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            current = agent_log / "current-run.json"
            self._gate(gate)
            current_payload = json.loads(gate.read_text(encoding="utf-8"))
            current_payload["schema"] = "active_run_pointer_v1"
            current.write_text(json.dumps(current_payload), encoding="utf-8")
            real_gate = REPO_ROOT / "docs" / "agent-log" / "active-run-gate.json"
            real_gate_sha = hashlib.sha256(real_gate.read_bytes()).hexdigest()
            token = "fixture-full-evaluation-token"
            launch_record = agent_log / f"{run_id}.launch.json"
            launch_record.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "full_plan_path": str(full_plan.resolve()),
                        "evaluation_path": str(evaluation.resolve()),
                        "repeat_evaluation_path": str(repeat.resolve()),
                        "execution_probe_plan_path": str(probe_plan.resolve()),
                        "worker_token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPT),
                    "-Worker",
                    "-WorkerToken",
                    token,
                    "-RunId",
                    run_id,
                    "-ArtifactRoot",
                    str(artifact_root),
                    "-QualityLedgerPath",
                    str(ledger),
                    "-HypothesisBankPath",
                    str(bank),
                    "-Hypothesis",
                    contract["id"],
                    "-TrainPlanPath",
                    str(train_plan_path),
                    "-FeasibilityPath",
                    str(feasibility_path),
                    "-FullPlanPath",
                    str(full_plan),
                    "-EvaluationPath",
                    str(evaluation),
                    "-RepeatEvaluationPath",
                    str(repeat),
                    "-ManifestPath",
                    str(manifest),
                    "-LaunchRecordPath",
                    str(launch_record),
                    "-GatePath",
                    str(gate),
                    "-CurrentRunPath",
                    str(current),
                    "-HoldOpenSec",
                    "0",
                    "-MaxRuntimeSec",
                    "1800",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=300,
                env={**os.environ, "TRADING_MVP_PYTHON": sys.executable},
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(manifest.read_text(encoding="utf-8"))
            first = json.loads(evaluation.read_text(encoding="utf-8"))
            second = json.loads(repeat.read_text(encoding="utf-8"))
            plan = json.loads(full_plan.read_text(encoding="utf-8"))
            probe = json.loads(probe_plan.read_text(encoding="utf-8"))
            final_gate = json.loads(gate.read_text(encoding="utf-8"))
            self.assertTrue(result["final"])
            self.assertEqual(result["verdict"], "ACCEPT_FOR_SHORT_EXECUTION_PROBE")
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertTrue(first["deterministic_repeats_match"])
            self.assertEqual(plan["sealed_input"]["plan_stage"], "full_evaluation")
            self.assertEqual(len(plan["sealed_input"]["split"]["train_dates"]), 20)
            self.assertEqual(len(plan["sealed_input"]["split"]["oos_dates"]), 100)
            self.assertEqual(first["metrics"]["oos_closed_days"], 100)
            self.assertEqual(probe["source"]["evaluation_result_hash"], first["deterministic_result_hash"])
            self.assertEqual(probe["collection_contract"]["duration_sec"], 1200)
            self.assertEqual(result["execution_probe_plan_path"], str(probe_plan.resolve()))
            self.assertEqual(result["execution_probe_plan_hash"], probe["plan_hash"])
            self.assertEqual(result["execution_probe_approval_phrase"], probe["approval_phrase"])
            self.assertFalse(first["network_access"])
            self.assertFalse(first["grid_search"])
            self.assertFalse(first["retune"])
            self.assertFalse(first["paper_forward_allowed"])
            self.assertFalse(first["live_orders"])
            self.assertEqual(final_gate["gate_status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(final_gate["run_id"], run_id)
            self.assertEqual(
                final_gate["next_goal_decision"],
                "PIT_ACCEPT_FOR_SHORT_EXECUTION_PROBE_REQUIRES_EXPLICIT_APPROVAL",
            )
            self.assertEqual(final_gate["execution_probe_plan_path"], str(probe_plan.resolve()))
            self.assertEqual(final_gate["execution_probe_plan_hash"], probe["plan_hash"])
            self.assertEqual(final_gate["execution_probe_approval_phrase"], probe["approval_phrase"])
            self.assertEqual(hashlib.sha256(real_gate.read_bytes()).hexdigest(), real_gate_sha)


if __name__ == "__main__":
    unittest.main()
