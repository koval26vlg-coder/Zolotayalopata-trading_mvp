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
SCRIPT = REPO_ROOT / "tools" / "run_pit_train_feasibility_visible.ps1"
RUN_MVP = REPO_ROOT / "trading_mvp" / "run_mvp.ps1"


class PitTrainFeasibilityVisibleTests(unittest.TestCase):
    def _base_command(self, pwsh: str, root: Path) -> list[str]:
        artifact_root = root / "artifacts"
        ledger = root / "quality.jsonl"
        ledger.write_text("", encoding="utf-8")
        gate = root / "active-run-gate.json"
        gate.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "previous-run",
                    "status": "READY_FOR_POSTPROCESS",
                    "gate_status": "READY_FOR_POSTPROCESS",
                    "replay_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        current = root / "current-run.json"
        current.write_text(gate.read_text(encoding="utf-8"), encoding="utf-8")
        return [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RunId",
            "pit_train_feasibility_test",
            "-ArtifactRoot",
            str(artifact_root),
            "-QualityLedgerPath",
            str(ledger),
            "-HypothesisBankPath",
            str(REPO_ROOT / "docs" / "research" / "trading_mvp_hypothesis_bank_v1.json"),
            "-GatePath",
            str(gate),
            "-CurrentRunPath",
            str(current),
            "-HoldOpenSec",
            "0",
            "-MaxRuntimeSec",
            "1800",
        ]

    def test_planonly_is_read_only_and_describes_visible_owned_train_only_run(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command = self._base_command(pwsh, root) + ["-PlanOnly"]
            gate = root / "active-run-gate.json"
            current = root / "current-run.json"
            gate_sha = hashlib.sha256(gate.read_bytes()).hexdigest()
            current_sha = hashlib.sha256(current.read_bytes()).hexdigest()

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
            self.assertEqual(payload["stage"], "train_feasibility")
            self.assertTrue(payload["visible_terminal"])
            self.assertEqual(payload["deterministic_repeats"], 2)
            self.assertFalse(payload["network_access"])
            self.assertFalse(payload["oos_returns_read"])
            self.assertFalse(payload["grid_search"])
            self.assertFalse(payload["paper_forward"])
            self.assertFalse(payload["live_orders"])
            self.assertEqual(payload["oos_schedule_stage"], "oos_accrual")
            self.assertFalse(Path(payload["oos_schedule_path"]).exists())
            self.assertFalse(Path(payload["plan_path"]).exists())
            self.assertFalse(Path(payload["feasibility_path"]).exists())
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_sha)
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), current_sha)

    def test_worker_refuses_missing_ownership_token(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed = subprocess.run(
                self._base_command(pwsh, root) + ["-Worker"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ownership token", completed.stderr)

    def test_script_contains_only_train_feasibility_and_oos_planonly_transition_actions(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"fast-edge-pit-input-plan"', source)
        self.assertIn('"fast-edge-pit-feasibility"', source)
        self.assertIn('"fast-edge-night-schedule-plan"', source)
        self.assertIn('"oos_accrual"', source)
        self.assertIn("deterministic_result_hash", source)
        self.assertIn("oos_dates_read", source)
        self.assertIn("returns_read", source)
        self.assertIn("Start-Process", source)
        self.assertIn("-WindowStyle Normal", source)
        self.assertNotIn('"fast-edge-pit-evaluate"', source)
        self.assertNotIn('"ws-grid-search"', source)
        self.assertNotIn('"paper-forward-segment"', source)

    def test_owned_child_actions_are_bound_to_visible_run_gate(self) -> None:
        wrapper = SCRIPT.read_text(encoding="utf-8")
        run_mvp = RUN_MVP.read_text(encoding="utf-8")

        self.assertGreaterEqual(wrapper.count('"-RunId", $RunId'), 4)
        self.assertIn("$ownedPitTrainFeasibilityRun", run_mvp)
        self.assertIn(
            '"fast-edge-pit-input-plan", "fast-edge-pit-feasibility", "fast-edge-night-schedule-plan"',
            run_mvp,
        )
        self.assertIn('"PIT_TRAIN_FEASIBILITY_RUNNING"', run_mvp)
        self.assertIn("-not $ownedPitTrainFeasibilityRun", run_mvp)

    def test_launcher_closes_gate_on_timeout_or_nonzero_worker(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('StopReason "train_feasibility_timeout"', source)
        self.assertIn('StopReason "worker_exit_nonzero"', source)
        self.assertIn("$runtimeDeadline", source)
        self.assertIn("$approvedDeadline", source)

    def test_worker_completes_owned_train_only_transition_on_twenty_date_fixture(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = pit_fixture.PitMembershipDriftPipelineTests()
            bank, ledger, contract = fixture._dataset(root, days=20)
            artifact_root = root / "artifacts"
            run_id = "pit_train_feasibility_fixture"
            plan = artifact_root / f"{run_id}.input-plan.json"
            feasibility = artifact_root / f"{run_id}.feasibility.json"
            repeat = artifact_root / f"{run_id}.feasibility.repeat.json"
            oos_schedule = artifact_root / f"{run_id}.oos-accrual-plan.json"
            oos_data_root = root / "oos-data"
            manifest = artifact_root / f"{run_id}.manifest.json"
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            current = agent_log / "current-run.json"
            initial_gate = {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "previous-run",
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "replay_allowed": False,
            }
            gate.write_text(json.dumps(initial_gate), encoding="utf-8")
            current.write_text(json.dumps(initial_gate), encoding="utf-8")
            real_gate = REPO_ROOT / "docs" / "agent-log" / "active-run-gate.json"
            real_gate_sha = hashlib.sha256(real_gate.read_bytes()).hexdigest()
            token = "fixture-owned-token"
            launch_record = agent_log / f"{run_id}.launch.json"
            launch_record.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "plan_path": str(plan.resolve()),
                        "feasibility_path": str(feasibility.resolve()),
                        "repeat_feasibility_path": str(repeat.resolve()),
                        "oos_schedule_path": str(oos_schedule.resolve()),
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
                    "-PlanPath",
                    str(plan),
                    "-FeasibilityPath",
                    str(feasibility),
                    "-RepeatFeasibilityPath",
                    str(repeat),
                    "-OosSchedulePath",
                    str(oos_schedule),
                    "-OosOutputRoot",
                    str(oos_data_root),
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
                timeout=180,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(manifest.read_text(encoding="utf-8"))
            first = json.loads(feasibility.read_text(encoding="utf-8"))
            second = json.loads(repeat.read_text(encoding="utf-8"))
            schedule = json.loads(oos_schedule.read_text(encoding="utf-8"))
            final_gate = json.loads(gate.read_text(encoding="utf-8"))
            final_current = json.loads(current.read_text(encoding="utf-8"))
            self.assertTrue(result["final"])
            self.assertEqual(result["verdict"], "FEASIBLE_FOR_OOS")
            self.assertTrue(result["deterministic_repeats_match"])
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(result["train_dates_read"], 20)
            self.assertEqual(result["oos_dates_read"], 0)
            self.assertFalse(result["returns_read"])
            self.assertFalse(result["pnl_computed"])
            self.assertEqual(result["oos_schedule_path"], str(oos_schedule.resolve()))
            self.assertEqual(result["oos_schedule_plan_hash"], schedule["plan_hash"])
            self.assertEqual(result["next_allowed_action"], "await_explicit_night_schedule_approval")
            self.assertEqual(schedule["mode"], "PlanOnly")
            self.assertEqual(schedule["collection_stage"], "oos_accrual")
            self.assertFalse(schedule["schedule_approved"])
            self.assertFalse(schedule["collection_started"])
            self.assertFalse(schedule["network_access"])
            self.assertFalse(schedule["oos_returns_read"])
            stage = schedule["sealed_schedule"]["collection_stage"]
            self.assertEqual(stage["initial_accepted_distinct_dates"], 20)
            self.assertEqual(stage["stage_target_distinct_dates"], 120)
            self.assertEqual(stage["upstream_train_feasibility"]["verdict"], "FEASIBLE_FOR_OOS")
            self.assertEqual(final_gate["gate_status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(final_current["gate_status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(final_gate["run_id"], run_id)
            self.assertEqual(final_gate["next_goal_decision"], "PIT_OOS_ACCRUAL_PLAN_READY_FOR_APPROVAL")
            self.assertEqual(hashlib.sha256(real_gate.read_bytes()).hexdigest(), real_gate_sha)

    def test_run_mvp_blocks_mismatched_run_id_on_owned_gate_override(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            current = agent_log / "current-run.json"
            owned_gate = {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "owned-run",
                "status": "RUNNING",
                "gate_status": "RUNNING",
                "next_goal_decision": "PIT_TRAIN_FEASIBILITY_RUNNING",
                "monitor_pid": 0,
                "process_ids": [],
                "replay_allowed": False,
            }
            gate.write_text(json.dumps(owned_gate), encoding="utf-8")
            current.write_text(json.dumps(owned_gate), encoding="utf-8")
            ledger = root / "quality.jsonl"
            ledger.write_text("", encoding="utf-8")
            output = root / "must-not-exist.json"
            real_gate = REPO_ROOT / "docs" / "agent-log" / "active-run-gate.json"
            real_gate_sha = hashlib.sha256(real_gate.read_bytes()).hexdigest()

            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RUN_MVP),
                    "-Action",
                    "fast-edge-pit-input-plan",
                    "-RunId",
                    "intruder-run",
                    "-ActiveRunGatePath",
                    str(gate),
                    "-QualityLedgerPath",
                    str(ledger),
                    "-HypothesisBankPath",
                    str(REPO_ROOT / "docs" / "research" / "trading_mvp_hypothesis_bank_v1.json"),
                    "-Hypothesis",
                    "pit_universe_membership_drift_reversion_v1",
                    "-PitPlanStage",
                    "train_feasibility",
                    "-OutputPath",
                    str(output),
                    "-MaxRuntimeSec",
                    "1200",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("blocked by active run gate", completed.stderr + completed.stdout)
            self.assertFalse(output.exists())
            self.assertEqual(hashlib.sha256(real_gate.read_bytes()).hexdigest(), real_gate_sha)


if __name__ == "__main__":
    unittest.main()
