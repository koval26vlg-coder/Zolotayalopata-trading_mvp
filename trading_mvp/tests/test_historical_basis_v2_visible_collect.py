from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_mvp.tests.test_historical_basis_v2_collector import _write_plan


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "start_historical_basis_v2_collect_visible.ps1"
REAL_GATE = REPO_ROOT / "docs" / "agent-log" / "active-run-gate.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HistoricalBasisV2VisibleCollectTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict[str, object], Path, Path, Path]:
        plan, plan_path = _write_plan(root)
        agent_log = root / "docs" / "agent-log"
        agent_log.mkdir(parents=True, exist_ok=True)
        gate = agent_log / "active-run-gate.json"
        current = agent_log / "current-run.json"
        payload = {
            "schema": "active_run_gate_v2",
            "project": "trading_mvp",
            "run_id": "previous-run",
            "status": "READY_FOR_POSTPROCESS",
            "gate_status": "READY_FOR_POSTPROCESS",
            "final": True,
            "replay_allowed": False,
        }
        gate.write_text(json.dumps(payload), encoding="utf-8")
        current.write_text(
            json.dumps({**payload, "schema": "active_run_pointer_v1"}),
            encoding="utf-8",
        )
        return plan, plan_path, gate, current

    def _base_command(
        self,
        pwsh: str,
        *,
        root: Path,
        plan: dict[str, object],
        plan_path: Path,
        gate: Path,
        current: Path,
    ) -> list[str]:
        now = datetime.now(timezone.utc)
        return [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-PlanPath",
            str(plan_path),
            "-ExpectedPlanHash",
            str(plan["plan_hash"]),
            "-RunId",
            "basis_v2_visible_fixture",
            "-OutputRoot",
            str(root / "output"),
            "-GatePath",
            str(gate),
            "-CurrentRunPath",
            str(current),
            "-LaunchRecordPath",
            str(root / "launch.json"),
            "-MaxRuntimeSec",
            "1200",
            "-HoldOpenSec",
            "0",
            "-MinimumFreeGb",
            "0",
            "-ApprovedNotBefore",
            (now - timedelta(minutes=1)).isoformat(),
            "-ApprovedNotLaterThan",
            (now + timedelta(minutes=30)).isoformat(),
        ]

    def test_planonly_is_read_only_and_emits_exact_confirmation(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, gate, current = self._fixture(root)
            gate_before = _sha256(gate)
            current_before = _sha256(current)
            real_gate_before = _sha256(REAL_GATE)
            command = self._base_command(
                pwsh,
                root=root,
                plan=plan,
                plan_path=plan_path,
                gate=gate,
                current=current,
            ) + ["-PlanOnly"]

            completed = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            preview = json.loads(completed.stdout)
            self.assertEqual(
                preview["decision"],
                "AWAIT_EXPLICIT_BASIS_V2_HISTORY_COLLECT_APPROVAL",
            )
            self.assertEqual(preview["plan_hash"], plan["plan_hash"])
            self.assertEqual(preview["run_id"], "basis_v2_visible_fixture")
            self.assertEqual(preview["max_runtime_sec"], 1200)
            self.assertTrue(preview["visible_terminal_required"])
            self.assertTrue(Path(preview["python_runtime"]).is_file())
            self.assertFalse(preview["network_access"])
            self.assertFalse(preview["collector_started"])
            self.assertFalse(preview["auto_resume"])
            self.assertIn("ConfirmedPublicHistoryCollect", preview["approval_command"])
            self.assertIn(str(plan["plan_hash"]), preview["approval_phrase"])
            self.assertFalse((root / "output" / "runs" / "basis_v2_visible_fixture").exists())
            self.assertFalse((root / "launch.json").exists())
            self.assertEqual(_sha256(gate), gate_before)
            self.assertEqual(_sha256(current), current_before)
            self.assertEqual(_sha256(REAL_GATE), real_gate_before)

    def test_actual_launch_requires_explicit_confirmation_switch(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, gate, current = self._fixture(root)
            completed = subprocess.run(
                self._base_command(
                    pwsh,
                    root=root,
                    plan=plan,
                    plan_path=plan_path,
                    gate=gate,
                    current=current,
                ),
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "ConfirmedPublicHistoryCollect is required",
                completed.stdout + completed.stderr,
            )
            self.assertFalse((root / "output" / "runs" / "basis_v2_visible_fixture").exists())

    def test_planonly_can_seal_visible_train_only_continuation_without_oos(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, gate, current = self._fixture(root)
            postprocess_root = root / "postprocess"
            command = self._base_command(
                pwsh,
                root=root,
                plan=plan,
                plan_path=plan_path,
                gate=gate,
                current=current,
            ) + [
                "-ContinueToTrainPostprocess",
                "-TrainPostprocessOutputRoot",
                str(postprocess_root),
                "-TrainPostprocessMaxRuntimeSec",
                "1800",
                "-TrainPostprocessHoldOpenSec",
                "0",
                "-PlanOnly",
            ]

            completed = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            preview = json.loads(completed.stdout)
            self.assertTrue(preview["continue_to_train_postprocess"])
            self.assertEqual(preview["train_postprocess_output_root"], str(postprocess_root.resolve()))
            self.assertEqual(preview["train_postprocess_max_runtime_sec"], 1800)
            self.assertTrue(preview["train_postprocess_visible_terminal_required"])
            self.assertFalse(preview["train_postprocess_network_access"])
            self.assertFalse(preview["automatic_oos"])
            self.assertIn("ContinueToTrainPostprocess", preview["approval_command"])
            self.assertIn("train-only postprocess", preview["approval_phrase"])
            self.assertFalse(postprocess_root.exists())
            self.assertFalse((root / "launch.json").exists())

    def test_worker_rejects_unowned_token_before_collecting(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, gate, current = self._fixture(root)
            launch_record = root / "launch.json"
            launch_record.write_text(
                json.dumps(
                    {
                        "run_id": "basis_v2_visible_fixture",
                        "plan_path": str(plan_path.resolve()),
                        "plan_hash": plan["plan_hash"],
                        "worker_token_sha256": hashlib.sha256(b"owned-token").hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                self._base_command(
                    pwsh,
                    root=root,
                    plan=plan,
                    plan_path=plan_path,
                    gate=gate,
                    current=current,
                )
                + ["-Worker", "-WorkerToken", "wrong-token"],
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Worker token mismatch", completed.stdout + completed.stderr)
            self.assertFalse((root / "output" / "runs" / "basis_v2_visible_fixture").exists())

    def test_script_enforces_visible_unbuffered_deadline_and_failure_guards(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$env:PYTHONUNBUFFERED = \"1\"", text)
        self.assertIn("-WindowStyle Normal", text)
        self.assertNotIn("-WindowStyle Hidden", text)
        self.assertIn("WaitForExit", text)
        self.assertIn("ApprovedNotLaterThan", text)
        self.assertIn("ConfirmedPublicHistoryCollect", text)
        self.assertIn("STOPPED_INCOMPLETE", text)
        self.assertIn("MinimumFreeGb", text)
        self.assertIn(".historical-basis-v2-writer.lock", text)
        self.assertIn("start_historical_basis_v2_train_postprocess_visible.ps1", text)
        self.assertNotIn("start_historical_basis_v2_oos_postprocess_visible.ps1", text)
        self.assertIn("Assert-NoPitScheduleOverlap -Deadline $pipelineDeadline", text)
        self.assertIn("COLLECT_COMPLETED_TRAIN_POSTPROCESS_STOPPED_INCOMPLETE", text)
        self.assertIn("automatic_oos = $false", text)
        self.assertIn('(Join-Path $ProjectRoot "trading_mvp\\.venv\\Scripts\\python.exe")', text)
        self.assertIn('"C:\\Users\\koval\\Documents\\ОК.ру\\.venv\\Scripts\\python.exe"', text)
        self.assertIn('"import requests"', text)
        self.assertIn('$env:TRADING_MVP_PYTHON = $python', text)

    def test_worker_invokes_run_mvp_with_named_parameter_splatting(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$runParameters = @{", text)
        self.assertIn("& $RunMvp @runParameters", text)
        self.assertNotIn("& $RunMvp @arguments", text)


if __name__ == "__main__":
    unittest.main()
