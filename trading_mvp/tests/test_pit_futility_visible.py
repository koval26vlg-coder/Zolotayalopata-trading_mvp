from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from trading_mvp.tests import test_pit_membership_drift_futility as futility_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "run_pit_futility_visible.ps1"
RUN_MVP = REPO_ROOT / "trading_mvp" / "run_mvp.ps1"


class PitFutilityVisibleTests(unittest.TestCase):
    def _base_command(
        self,
        pwsh: str,
        root: Path,
        *,
        days: int,
    ) -> tuple[list[str], Path, Path, dict]:
        bank, ledger, contract = futility_fixture._dataset(root, days=days)
        artifact_root = root / "artifacts"
        gate = root / "active-run-gate.json"
        initial_gate = {
            "schema": "active_run_gate_v2",
            "project": "trading_mvp",
            "run_id": "previous-run",
            "status": "READY_FOR_POSTPROCESS",
            "gate_status": "READY_FOR_POSTPROCESS",
            "replay_allowed": False,
        }
        gate.write_text(json.dumps(initial_gate), encoding="utf-8")
        current = root / "current-run.json"
        current.write_text(
            json.dumps({**initial_gate, "schema": "active_run_pointer_v1"}),
            encoding="utf-8",
        )
        command = [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RunId",
            "pit_futility_test",
            "-ArtifactRoot",
            str(artifact_root),
            "-QualityLedgerPath",
            str(ledger),
            "-HypothesisBankPath",
            str(bank),
            "-Hypothesis",
            contract["id"],
            "-GatePath",
            str(gate),
            "-CurrentRunPath",
            str(current),
            "-HoldOpenSec",
            "0",
            "-MaxRuntimeSec",
            "1800",
        ]
        return command, gate, current, contract

    def test_planonly_is_read_only_and_reports_checkpoint_readiness(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command, gate, current, _ = self._base_command(pwsh, root, days=10)
            gate_sha = hashlib.sha256(gate.read_bytes()).hexdigest()
            current_sha = hashlib.sha256(current.read_bytes()).hexdigest()

            completed = subprocess.run(
                command + ["-PlanOnly"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"], "PLAN_ONLY")
            self.assertEqual(payload["stage"], "pit_10_date_futility")
            self.assertTrue(payload["checkpoint_ready"])
            self.assertEqual(payload["accepted_distinct_dates"], 10)
            self.assertTrue(payload["visible_terminal"])
            self.assertFalse(payload["network_access"])
            self.assertFalse(payload["returns_read"])
            self.assertFalse(payload["pnl_computed"])
            self.assertFalse(payload["oos_evaluation"])
            self.assertFalse(payload["grid_search"])
            self.assertFalse(Path(payload["plan_path"]).exists())
            self.assertFalse(Path(payload["result_path"]).exists())
            self.assertFalse(Path(payload["manifest_path"]).exists())
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_sha)
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), current_sha)

    def test_planonly_reports_not_due_before_ten_dates_without_mutation(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command, gate, current, _ = self._base_command(pwsh, root, days=9)
            gate_sha = hashlib.sha256(gate.read_bytes()).hexdigest()

            completed = subprocess.run(
                command + ["-PlanOnly"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["checkpoint_ready"])
            self.assertEqual(payload["accepted_distinct_dates"], 9)
            self.assertEqual(payload["next_allowed_action"], "wait_for_tenth_quality_date")
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_sha)
            self.assertFalse((root / "artifacts").exists())

    def test_default_run_identity_stays_stable_when_ledger_grows_after_checkpoint(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command, _, _, _ = self._base_command(pwsh, root, days=10)
            run_id_index = command.index("-RunId")
            del command[run_id_index : run_id_index + 2]

            first = subprocess.run(
                command + ["-PlanOnly"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_payload = json.loads(first.stdout)

            futility_fixture._dataset(root, days=11)
            second = subprocess.run(
                command + ["-PlanOnly"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            second_payload = json.loads(second.stdout)

            self.assertEqual(first_payload["accepted_distinct_dates"], 10)
            self.assertEqual(second_payload["accepted_distinct_dates"], 11)
            self.assertEqual(first_payload["run_id"], second_payload["run_id"])
            self.assertEqual(first_payload["plan_path"], second_payload["plan_path"])
            self.assertEqual(first_payload["result_path"], second_payload["result_path"])
            self.assertEqual(first_payload["manifest_path"], second_payload["manifest_path"])

    def test_planonly_reuses_completed_checkpoint_after_ledger_grows(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command, _, _, _ = self._base_command(pwsh, root, days=10)
            run_id_index = command.index("-RunId")
            del command[run_id_index : run_id_index + 2]

            first = subprocess.run(
                command + ["-PlanOnly"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            payload = json.loads(first.stdout)
            plan_path = Path(payload["plan_path"])
            result_path = Path(payload["result_path"])
            manifest_path = Path(payload["manifest_path"])
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps({"plan_hash": "plan-hash"}), encoding="utf-8")
            result_path.write_text(
                json.dumps(
                    {
                        "plan_hash": "plan-hash",
                        "deterministic_result_hash": "result-hash",
                        "verdict": "CONTINUE_TO_20_DATE_TRAIN_GATE",
                        "checkpoint_dates_read": 10,
                        "deterministic_repeats_match": True,
                        "returns_read": False,
                        "pnl_computed": False,
                        "oos_metrics_computed": False,
                        "network_access": False,
                        "grid_search": False,
                        "retune": False,
                    }
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "pit_futility_visible_manifest_v1",
                        "run_id": payload["run_id"],
                        "final": True,
                        "plan_path": str(plan_path.resolve()),
                        "plan_hash": "plan-hash",
                        "plan_file_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                        "result_path": str(result_path.resolve()),
                        "result_file_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
                        "deterministic_result_hash": "result-hash",
                        "deterministic_repeats_match": True,
                        "verdict": "CONTINUE_TO_20_DATE_TRAIN_GATE",
                        "checkpoint_dates_read": 10,
                        "returns_read": False,
                        "pnl_computed": False,
                        "oos_metrics_computed": False,
                        "network_access": False,
                        "grid_search": False,
                        "retune": False,
                    }
                ),
                encoding="utf-8",
            )

            futility_fixture._dataset(root, days=11)
            second = subprocess.run(
                command + ["-PlanOnly"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            second_payload = json.loads(second.stdout)
            self.assertEqual(second_payload["run_id"], payload["run_id"])
            self.assertTrue(second_payload["checkpoint_completed"])
            self.assertFalse(second_payload["checkpoint_ready"])
            self.assertEqual(
                second_payload["checkpoint_verdict"],
                "CONTINUE_TO_20_DATE_TRAIN_GATE",
            )
            self.assertEqual(second_payload["next_allowed_action"], "wait_for_next_quality_date")

    def test_worker_refuses_missing_ownership_token(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command, _, _, _ = self._base_command(pwsh, root, days=10)

            completed = subprocess.run(
                command + ["-Worker"],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ownership token", completed.stderr + completed.stdout)

    def test_script_is_visible_embargo_safe_and_futility_only(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"fast-edge-pit-futility-plan"', source)
        self.assertIn('"fast-edge-pit-futility-evaluate"', source)
        self.assertIn("deterministic_repeats_match", source)
        self.assertIn("checkpoint_dates_read", source)
        self.assertIn("Start-Process", source)
        self.assertIn("-WindowStyle Normal", source)
        self.assertIn('StopReason "pit_futility_timeout"', source)
        self.assertIn('StopReason "worker_exit_nonzero"', source)
        self.assertNotIn('"fast-edge-pit-evaluate"', source)
        self.assertNotIn('"ws-grid-search"', source)
        self.assertNotIn('"paper-forward-segment"', source)

    def test_owned_child_actions_are_bound_to_visible_futility_gate(self) -> None:
        wrapper = SCRIPT.read_text(encoding="utf-8")
        run_mvp = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(RUN_MVP)

        self.assertGreaterEqual(wrapper.count('"-RunId", $RunId'), 2)
        self.assertIn("$ownedPitFutilityRun", run_mvp)
        self.assertIn(
            '"fast-edge-pit-futility-plan", "fast-edge-pit-futility-evaluate"',
            run_mvp,
        )
        self.assertIn('"PIT_FUTILITY_RUNNING"', run_mvp)
        self.assertIn("-not $ownedPitFutilityRun", run_mvp)

    def test_worker_completes_owned_ten_date_futility_transition(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command, gate, current, contract = self._base_command(pwsh, root, days=10)
            artifact_root = root / "artifacts"
            run_id = "pit_futility_fixture"
            plan = artifact_root / f"{run_id}.plan.json"
            result = artifact_root / f"{run_id}.result.json"
            manifest = artifact_root / f"{run_id}.manifest.json"
            token = "fixture-owned-token"
            launch_record = root / f"{run_id}.launch.json"
            launch_record.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "plan_path": str(plan.resolve()),
                        "result_path": str(result.resolve()),
                        "manifest_path": str(manifest.resolve()),
                        "worker_token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            real_gate = REPO_ROOT / "docs" / "agent-log" / "active-run-gate.json"
            real_gate_sha = hashlib.sha256(real_gate.read_bytes()).hexdigest()

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
                    str(root / "quality-ledger.jsonl"),
                    "-HypothesisBankPath",
                    str(root / "bank.json"),
                    "-Hypothesis",
                    contract["id"],
                    "-PlanPath",
                    str(plan),
                    "-ResultPath",
                    str(result),
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
            final_manifest = json.loads(manifest.read_text(encoding="utf-8"))
            final_result = json.loads(result.read_text(encoding="utf-8"))
            final_gate = json.loads(gate.read_text(encoding="utf-8"))
            final_current = json.loads(current.read_text(encoding="utf-8"))
            self.assertTrue(final_manifest["final"])
            self.assertEqual(final_manifest["checkpoint_dates_read"], 10)
            self.assertTrue(final_manifest["deterministic_repeats_match"])
            self.assertEqual(final_manifest["plan_hash"], final_result["plan_hash"])
            self.assertEqual(
                final_manifest["deterministic_result_hash"],
                final_result["deterministic_result_hash"],
            )
            self.assertFalse(final_manifest["returns_read"])
            self.assertFalse(final_manifest["pnl_computed"])
            self.assertFalse(final_manifest["oos_metrics_computed"])
            self.assertFalse(final_manifest["network_access"])
            self.assertFalse(final_manifest["grid_search"])
            self.assertIn(
                final_manifest["verdict"],
                {"FUTILE_CLOSE_BRANCH_BEFORE_TRAIN", "CONTINUE_TO_20_DATE_TRAIN_GATE"},
            )
            expected_decision = (
                "PIT_FUTILITY_BRANCH_CLOSED"
                if final_manifest["verdict"] == "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN"
                else "PIT_FUTILITY_CONTINUE_TRAIN_ACCRUAL"
            )
            self.assertEqual(final_gate["gate_status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(final_current["gate_status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(final_gate["run_id"], run_id)
            self.assertEqual(final_gate["next_goal_decision"], expected_decision)
            self.assertEqual(hashlib.sha256(real_gate.read_bytes()).hexdigest(), real_gate_sha)

    def test_run_mvp_blocks_mismatched_run_id_on_owned_futility_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gate = root / "active-run-gate.json"
            owned_gate = {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "owned-run",
                "status": "RUNNING",
                "gate_status": "RUNNING",
                "next_goal_decision": "PIT_FUTILITY_RUNNING",
                "monitor_pid": 0,
                "process_ids": [],
                "replay_allowed": False,
            }
            gate.write_text(json.dumps(owned_gate), encoding="utf-8")
            output = root / "must-not-exist.json"

            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RUN_MVP),
                    "-Action",
                    "fast-edge-pit-futility-plan",
                    "-RunId",
                    "intruder-run",
                    "-ActiveRunGatePath",
                    str(gate),
                    "-QualityLedgerPath",
                    str(root / "missing-ledger.jsonl"),
                    "-HypothesisBankPath",
                    str(REPO_ROOT / "docs" / "research" / "trading_mvp_hypothesis_bank_v1.json"),
                    "-Hypothesis",
                    "pit_universe_membership_drift_reversion_v1",
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


if __name__ == "__main__":
    unittest.main()
