from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "check_trading_mvp_autopilot.ps1"
PLAN_HASH = "a" * 64
RUN_ID = "pit_n03"


class AutopilotGuardWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pwsh = shutil.which("pwsh")
        if self.pwsh is None:
            self.skipTest("pwsh is unavailable")

    def _write_inputs(
        self, root: Path
    ) -> tuple[Path, Path, Path, Path, Path]:
        ledger_path = root / "quality.jsonl"
        ledger_path.write_text("", encoding="utf-8")
        plan_path = root / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "plan_hash": PLAN_HASH,
                    "collection_stage": "train_accrual",
                    "hypothesis": {
                        "id": "pit",
                        "required_data_type": "PIT_FORWARD",
                    },
                    "segments": [{"run_id": RUN_ID}],
                }
            ),
            encoding="utf-8",
        )
        pointer_path = root / "pointer.json"
        pointer_path.write_text(
            json.dumps(
                {
                    "schema": "trading_mvp_autopilot_schedule_pointer_v1",
                    "status": "ACTIVE",
                    "plan_path": str(plan_path.resolve()),
                    "plan_hash": PLAN_HASH,
                    "hypothesis_id": "pit",
                    "data_type": "PIT_FORWARD",
                    "collection_stage": "train_accrual",
                    "quality_ledger_path": str(ledger_path.resolve()),
                }
            ),
            encoding="utf-8",
        )
        policy_path = root / "policy.json"
        policy_path.write_text("{}", encoding="utf-8")
        gate_path = root / "gate.json"
        gate_path.write_text("{}", encoding="utf-8")
        session_root = root / "sessions"
        session_root.mkdir()
        return plan_path, ledger_path, pointer_path, policy_path, gate_path

    def _guard(
        self,
        plan_path: Path,
        pointer_path: Path,
        *,
        run_id: str = RUN_ID,
    ) -> dict[str, object]:
        return {
            "schema": "trading_mvp_autopilot_state_v1",
            "project": "trading_mvp",
            "status": "ACTIVE",
            "decision": "WAITING_SCHEDULE_WINDOW",
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "stop_new_actions": False,
            "action_due": False,
            "critical_checkpoint_notification_required": False,
            "next_action": "run_next_due_hash_bound_visible_segment",
            "usage": {
                "status": "AVAILABLE",
                "remaining_percent": 80,
            },
            "gate": {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": run_id,
            },
            "schedule_window": {
                "status": "WAITING",
                "plan_path": str(plan_path.resolve()),
                "plan_hash": PLAN_HASH,
                "pointer_path": str(pointer_path.resolve()),
            },
        }

    def _summary(self, plan_path: Path, ledger_path: Path) -> dict[str, object]:
        return {
            "schema": "trading_mvp_pit_postrun_v1",
            "project": "trading_mvp",
            "run_id": RUN_ID,
            "decision": "WAITING_EVENT",
            "next_allowed_action": "run_next_due_hash_bound_visible_segment",
            "schedule_plan_path": str(plan_path.resolve()),
            "schedule_plan_hash": PLAN_HASH,
            "quality_ledger_path": str(ledger_path.resolve()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "returns_read": False,
            "pnl_read": False,
            "oos_run": False,
            "grid_search": False,
            "live_orders": False,
            "private_api_keys": False,
        }

    def _run_wrapper(
        self,
        root: Path,
        guard: dict[str, object],
        policy_path: Path,
        gate_path: Path,
        summary_path: Path,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object], Path]:
        readiness_dir = root / "readiness"
        readiness_dir.mkdir(exist_ok=True)
        readiness_report = readiness_dir / "report.json"
        readiness_report.write_text("{}\n", encoding="utf-8")
        readiness_pointer = root / "readiness-pointer.json"
        readiness_pointer.write_text("{}\n", encoding="utf-8")
        guard_output_path = root / "fake-guard-output.json"
        guard_output_path.write_text(json.dumps(guard), encoding="utf-8")
        fake_python = root / "fake-python.cmd"
        fake_python.write_text(
            '@echo off\r\ntype "%FAKE_GUARD_OUTPUT%"\r\nexit /b 0\r\n',
            encoding="ascii",
        )
        state_path = root / "state.json"
        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = str(fake_python)
        env["FAKE_GUARD_OUTPUT"] = str(guard_output_path)
        completed = subprocess.run(
            [
                self.pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WRAPPER),
                "-PolicyPath",
                str(policy_path),
                "-GatePath",
                str(gate_path),
                "-StatePath",
                str(state_path),
                "-CurrentReadinessPointerPath",
                str(readiness_pointer),
                "-GlobalWriterClaimPath",
                str(root / "writer-claim.json"),
                "-SessionRoot",
                str(root / "sessions"),
                "-PitPostrunSummaryPath",
                str(summary_path),
                "-Json",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            env=env,
        )
        payload = json.loads(completed.stdout)
        return completed, payload, state_path

    def test_wrapper_passes_current_readiness_and_writer_claim_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, _, pointer, policy, gate = self._write_inputs(root)
            capture_path = root / "args.txt"
            guard_output_path = root / "fake-guard-output.json"
            guard_output_path.write_text(
                json.dumps(self._guard(plan, pointer)),
                encoding="utf-8",
            )
            fake_python = root / "fake-python.cmd"
            fake_python.write_text(
                '@echo off\r\necho %* > "%FAKE_GUARD_ARGS%"\r\n'
                'type "%FAKE_GUARD_OUTPUT%"\r\nexit /b 0\r\n',
                encoding="ascii",
            )
            readiness_dir = root / "readiness"
            readiness_dir.mkdir()
            readiness_pointer = root / "readiness-pointer.json"
            readiness_pointer.write_text("{}\n", encoding="utf-8")
            state_path = root / "state.json"
            env = os.environ.copy()
            env["TRADING_MVP_PYTHON"] = str(fake_python)
            env["FAKE_GUARD_OUTPUT"] = str(guard_output_path)
            env["FAKE_GUARD_ARGS"] = str(capture_path)

            completed = subprocess.run(
                [
                    self.pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(WRAPPER),
                    "-PolicyPath",
                    str(policy),
                    "-GatePath",
                    str(gate),
                    "-StatePath",
                    str(state_path),
                    "-CurrentReadinessPointerPath",
                    str(readiness_pointer),
                    "-GlobalWriterClaimPath",
                    str(root / "writer-claim.json"),
                    "-SessionRoot",
                    str(root / "sessions"),
                    "-Json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                env=env,
            )
            captured = capture_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--current-readiness-pointer", captured)
        self.assertIn(str(readiness_pointer), captured)
        self.assertIn("--global-writer-claim", captured)
        self.assertIn(str(root / "writer-claim.json"), captured)

    def test_missing_readiness_pointer_reaches_fail_closed_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, _, pointer, policy, gate = self._write_inputs(root)
            capture_path = root / "args.txt"
            guard_output_path = root / "fake-guard-output.json"
            guard_output_path.write_text(
                json.dumps(
                    self._guard(plan, pointer, run_id="paper_public_probe")
                ),
                encoding="utf-8",
            )
            fake_python = root / "fake-python.cmd"
            fake_python.write_text(
                '@echo off\r\necho %* > "%FAKE_GUARD_ARGS%"\r\n'
                'type "%FAKE_GUARD_OUTPUT%"\r\nexit /b 0\r\n',
                encoding="ascii",
            )
            missing_pointer = root / "missing-readiness-pointer.json"
            state_path = root / "state.json"
            env = os.environ.copy()
            env["TRADING_MVP_PYTHON"] = str(fake_python)
            env["FAKE_GUARD_OUTPUT"] = str(guard_output_path)
            env["FAKE_GUARD_ARGS"] = str(capture_path)

            completed = subprocess.run(
                [
                    self.pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(WRAPPER),
                    "-PolicyPath",
                    str(policy),
                    "-GatePath",
                    str(gate),
                    "-StatePath",
                    str(state_path),
                    "-CurrentReadinessPointerPath",
                    str(missing_pointer),
                    "-GlobalWriterClaimPath",
                    str(root / "writer-claim.json"),
                    "-SessionRoot",
                    str(root / "sessions"),
                    "-PitPostrunSummaryPath",
                    str(root / "missing-summary.json"),
                    "-Json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                env=env,
            )
            captured = capture_path.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(missing_pointer.exists())
        self.assertIn(str(missing_pointer), captured)

    def test_unrelated_ready_gate_is_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, _, pointer, policy, gate = self._write_inputs(root)
            completed, payload, state_path = self._run_wrapper(
                root,
                self._guard(plan, pointer, run_id="paper_public_probe"),
                policy,
                gate,
                root / "missing.json",
            )
            persisted = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            payload["pit_postrun_disposition"]["status"],
            "NOT_APPLICABLE",
        )
        self.assertEqual(
            payload["pit_postrun_disposition"]["reason"],
            "gate_run_not_in_active_pit_schedule",
        )
        self.assertEqual(persisted, payload)

    def test_exact_ready_gate_exposes_missing_and_complete_dispositions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, ledger, pointer, policy, gate = self._write_inputs(root)
            summary_path = root / "summary.json"
            missing_completed, missing, _ = self._run_wrapper(
                root,
                self._guard(plan, pointer),
                policy,
                gate,
                summary_path,
            )
            summary_path.write_text(
                json.dumps(self._summary(plan, ledger)),
                encoding="utf-8",
            )
            complete_completed, complete, _ = self._run_wrapper(
                root,
                self._guard(plan, pointer),
                policy,
                gate,
                summary_path,
            )

        self.assertEqual(missing_completed.returncode, 0, missing_completed.stderr)
        self.assertEqual(
            missing["pit_postrun_disposition"]["status"],
            "MISSING",
        )
        self.assertTrue(
            missing["pit_postrun_disposition"]["exact_postrun_allowed"]
        )
        self.assertEqual(
            complete_completed.returncode,
            0,
            complete_completed.stderr,
        )
        self.assertEqual(
            complete["pit_postrun_disposition"]["status"],
            "COMPLETE",
        )
        self.assertFalse(
            complete["pit_postrun_disposition"]["exact_postrun_allowed"]
        )

    def test_integrity_conflict_is_critical_and_notified_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, ledger, pointer, policy, gate = self._write_inputs(root)
            summary = self._summary(plan, ledger)
            summary["returns_read"] = True
            summary_path = root / "summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            first_completed, first, _ = self._run_wrapper(
                root,
                self._guard(plan, pointer),
                policy,
                gate,
                summary_path,
            )
            second_completed, second, _ = self._run_wrapper(
                root,
                self._guard(plan, pointer),
                policy,
                gate,
                summary_path,
            )

        self.assertEqual(first_completed.returncode, 0, first_completed.stderr)
        self.assertEqual(
            first["decision"],
            "CRITICAL_STOP_PIT_POSTRUN_INTEGRITY_CONFLICT",
        )
        self.assertTrue(first["critical_checkpoint_notification_required"])
        self.assertTrue(
            first["pit_postrun_disposition"]["notification_required"]
        )
        self.assertEqual(second_completed.returncode, 0, second_completed.stderr)
        self.assertFalse(second["critical_checkpoint_notification_required"])
        self.assertFalse(
            second["pit_postrun_disposition"]["notification_required"]
        )

    def test_failed_postrun_requires_recovery_approval_and_notifies_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, ledger, pointer, policy, gate = self._write_inputs(root)
            summary = self._summary(plan, ledger)
            summary["decision"] = "PIT_POSTRUN_FAILED"
            summary[
                "next_allowed_action"
            ] = "user_review_required_before_any_new_collector"
            summary["failure"] = (
                "RuntimeException: PIT post-run requires final, complete, "
                "successfully completed output."
            )
            summary_path = root / "summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            first_completed, first, _ = self._run_wrapper(
                root,
                self._guard(plan, pointer),
                policy,
                gate,
                summary_path,
            )
            second_completed, second, _ = self._run_wrapper(
                root,
                self._guard(plan, pointer),
                policy,
                gate,
                summary_path,
            )

        self.assertEqual(first_completed.returncode, 0, first_completed.stderr)
        self.assertEqual(
            first["decision"],
            "USER_REVIEW_REQUIRED_PIT_POSTRUN_RECOVERY",
        )
        self.assertTrue(first["critical_checkpoint_notification_required"])
        self.assertTrue(
            first["pit_postrun_disposition"]["notification_required"]
        )
        self.assertEqual(second_completed.returncode, 0, second_completed.stderr)
        self.assertFalse(second["critical_checkpoint_notification_required"])
        self.assertFalse(
            second["pit_postrun_disposition"]["notification_required"]
        )


if __name__ == "__main__":
    unittest.main()
