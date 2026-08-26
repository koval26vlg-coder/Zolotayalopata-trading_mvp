from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "tools" / "check_trading_mvp_pit_postrun_summary.ps1"
PLAN_HASH = "a" * 64
RUN_ID = "pit_n03"


class PitPostrunSummaryCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pwsh = shutil.which("pwsh")
        if self.pwsh is None:
            self.skipTest("pwsh is unavailable")

    def _write_plan(self, root: Path) -> tuple[Path, Path, Path]:
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
        return plan_path, ledger_path, pointer_path

    def _summary(
        self,
        plan_path: Path,
        ledger_path: Path,
        *,
        decision: str = "WAITING_EVENT",
        next_action: str = "run_next_due_hash_bound_visible_segment",
    ) -> dict[str, object]:
        return {
            "schema": "trading_mvp_pit_postrun_v1",
            "project": "trading_mvp",
            "run_id": RUN_ID,
            "decision": decision,
            "next_allowed_action": next_action,
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

    def _run(
        self,
        plan_path: Path,
        summary_path: Path,
        pointer_path: Path,
        reconciliation_path: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        command = [
            self.pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CHECKER),
            "-SchedulePlanPath",
            str(plan_path),
            "-ExpectedSchedulePlanHash",
            PLAN_HASH,
            "-RunId",
            RUN_ID,
            "-SummaryPath",
            str(summary_path),
            "-SchedulePointerPath",
            str(pointer_path),
            "-Json",
        ]
        if reconciliation_path is not None:
            command.extend(
                ["-ReconciliationPath", str(reconciliation_path)]
            )
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        payload = json.loads(completed.stdout)
        return completed, payload

    def _run_guard(
        self,
        root: Path,
        plan_path: Path,
        pointer_path: Path,
        summary_path: Path,
        *,
        run_id: str = RUN_ID,
        gate_status: str = "READY_FOR_POSTPROCESS",
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        guard_path = root / "guard.json"
        guard_path.write_text(
            json.dumps(
                {
                    "schema": "trading_mvp_autopilot_state_v1",
                    "project": "trading_mvp",
                    "gate": {
                        "status": gate_status,
                        "run_id": run_id,
                    },
                    "schedule_window": {
                        "plan_path": str(plan_path.resolve()),
                        "plan_hash": PLAN_HASH,
                        "pointer_path": str(pointer_path.resolve()),
                    },
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                self.pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(CHECKER),
                "-GuardStatePath",
                str(guard_path),
                "-SummaryPath",
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
        )
        payload = json.loads(completed.stdout)
        return completed, payload

    def test_missing_summary_allows_only_exact_postrun(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, _, pointer_path = self._write_plan(root)
            completed, payload = self._run(
                plan_path, root / "missing.json", pointer_path
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "MISSING")
        self.assertTrue(payload["exact_postrun_allowed"])
        self.assertFalse(payload["new_collector_allowed"])
        self.assertFalse(payload["market_rows_read"])

    def test_bound_non_deferred_summary_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, ledger_path, pointer_path = self._write_plan(root)
            summary_path = root / "summary.json"
            summary_path.write_text(
                json.dumps(self._summary(plan_path, ledger_path)),
                encoding="utf-8",
            )
            completed, payload = self._run(
                plan_path, summary_path, pointer_path
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "COMPLETE")
        self.assertFalse(payload["exact_postrun_allowed"])
        self.assertEqual(
            payload["next_action"],
            "follow_bound_summary_next_allowed_action",
        )
        self.assertEqual(len(payload["summary_sha256"]), 64)

    def test_quota_outcomes_are_deferred(self) -> None:
        cases = [
            (
                "PAUSED_WEEKLY_LIMIT",
                "wait_for_fresh_weekly_quota_above_15_percent_then_retry_postrun",
            ),
            (
                "WAITING_EVENT",
                "run_train_feasibility_after_weekly_quota_reset",
            ),
            (
                "WAITING_EVENT",
                "refresh_horizon_after_weekly_quota_reset_then_request_exact_schedule_approval",
            ),
        ]
        for decision, next_action in cases:
            with self.subTest(decision=decision, next_action=next_action):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    plan_path, ledger_path, pointer_path = self._write_plan(root)
                    summary_path = root / "summary.json"
                    summary_path.write_text(
                        json.dumps(
                            self._summary(
                                plan_path,
                                ledger_path,
                                decision=decision,
                                next_action=next_action,
                            )
                        ),
                        encoding="utf-8",
                    )
                    completed, payload = self._run(
                        plan_path, summary_path, pointer_path
                    )

                self.assertEqual(completed.returncode, 0)
                self.assertEqual(payload["status"], "DEFERRED")
                self.assertFalse(payload["exact_postrun_allowed"])
                self.assertEqual(
                    payload["exact_postrun_retry_requires_quota_above_percent"],
                    15,
                )
                self.assertFalse(payload["new_collector_allowed"])

    def test_identity_or_embargo_drift_is_integrity_conflict(self) -> None:
        mutators = {
            "run_id": lambda payload: payload.update(run_id="foreign"),
            "plan_hash": lambda payload: payload.update(
                schedule_plan_hash="b" * 64
            ),
            "returns_read": lambda payload: payload.update(returns_read=True),
        }
        for name, mutate in mutators.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    plan_path, ledger_path, pointer_path = self._write_plan(root)
                    payload = self._summary(plan_path, ledger_path)
                    mutate(payload)
                    summary_path = root / "summary.json"
                    summary_path.write_text(
                        json.dumps(payload),
                        encoding="utf-8",
                    )
                    completed, result = self._run(
                        plan_path, summary_path, pointer_path
                    )

                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(result["status"], "INTEGRITY_CONFLICT")
                self.assertFalse(result["exact_postrun_allowed"])
                self.assertFalse(result["new_collector_allowed"])

    def test_guard_mode_ignores_unrelated_ready_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, _, pointer_path = self._write_plan(root)
            completed, payload = self._run_guard(
                root,
                plan_path,
                pointer_path,
                root / "missing.json",
                run_id="paper_public_probe",
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "NOT_APPLICABLE")
        self.assertEqual(
            payload["reason"],
            "gate_run_not_in_active_pit_schedule",
        )
        self.assertFalse(payload["exact_postrun_allowed"])
        self.assertFalse(payload["new_collector_allowed"])

    def test_failed_summary_requires_exact_approved_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, ledger_path, pointer_path = self._write_plan(root)
            summary_path = root / "summary.json"
            failed = self._summary(
                plan_path,
                ledger_path,
                decision="PIT_POSTRUN_FAILED",
                next_action="user_review_required_before_any_new_collector",
            )
            failed["failure"] = (
                "RuntimeException: PIT post-run requires final, complete, "
                "successfully completed output."
            )
            summary_path.write_text(json.dumps(failed), encoding="utf-8")
            completed, payload = self._run(
                plan_path,
                summary_path,
                pointer_path,
                root / "reconciliation.json",
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["status"], "RECOVERY_REQUIRED")
        self.assertFalse(payload["exact_postrun_allowed"])
        self.assertTrue(payload["reconciliation_requires_user_approval"])
        self.assertFalse(payload["new_collector_allowed"])
        self.assertEqual(
            payload["next_action"],
            "request_exact_postrun_reconciliation_approval",
        )

    def test_valid_reconciliation_supersedes_failed_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, ledger_path, pointer_path = self._write_plan(root)
            summary_path = root / "summary.json"
            reconciliation_path = root / "reconciliation.json"
            failed = self._summary(
                plan_path,
                ledger_path,
                decision="PIT_POSTRUN_FAILED",
                next_action="user_review_required_before_any_new_collector",
            )
            failed["failure"] = (
                "RuntimeException: PIT post-run requires final, complete, "
                "successfully completed output."
            )
            summary_path.write_text(json.dumps(failed), encoding="utf-8")
            import hashlib

            failed_sha256 = hashlib.sha256(summary_path.read_bytes()).hexdigest()
            reconciled = self._summary(plan_path, ledger_path)
            reconciled["reconciliation"] = {
                "schema": "trading_mvp_pit_postrun_reconciliation_v1",
                "supersedes_summary_path": str(summary_path.resolve()),
                "supersedes_summary_sha256": failed_sha256,
                "reconciliation_reason": (
                    "recover_exact_final_output_after_control_plane_"
                    "readiness_mismatch"
                ),
            }
            reconciliation_path.write_text(
                json.dumps(reconciled),
                encoding="utf-8",
            )
            completed, payload = self._run(
                plan_path,
                summary_path,
                pointer_path,
                reconciliation_path,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["status"], "COMPLETE")
        self.assertEqual(
            payload["summary_path"],
            str(reconciliation_path.resolve()),
        )
        self.assertEqual(
            payload["canonical_summary_sha256"],
            failed_sha256,
        )
        self.assertFalse(payload["exact_postrun_allowed"])
        self.assertFalse(payload["new_collector_allowed"])

    def test_reconciliation_binding_drift_is_integrity_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, ledger_path, pointer_path = self._write_plan(root)
            summary_path = root / "summary.json"
            reconciliation_path = root / "reconciliation.json"
            failed = self._summary(
                plan_path,
                ledger_path,
                decision="PIT_POSTRUN_FAILED",
                next_action="user_review_required_before_any_new_collector",
            )
            summary_path.write_text(json.dumps(failed), encoding="utf-8")
            reconciled = self._summary(plan_path, ledger_path)
            reconciled["reconciliation"] = {
                "schema": "trading_mvp_pit_postrun_reconciliation_v1",
                "supersedes_summary_path": str(summary_path.resolve()),
                "supersedes_summary_sha256": "b" * 64,
                "reconciliation_reason": (
                    "recover_exact_final_output_after_control_plane_"
                    "readiness_mismatch"
                ),
            }
            reconciliation_path.write_text(
                json.dumps(reconciled),
                encoding="utf-8",
            )
            completed, payload = self._run(
                plan_path,
                summary_path,
                pointer_path,
                reconciliation_path,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "INTEGRITY_CONFLICT")
        self.assertFalse(payload["exact_postrun_allowed"])
        self.assertFalse(payload["new_collector_allowed"])

    def test_guard_mode_resolves_exact_missing_and_complete_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, ledger_path, pointer_path = self._write_plan(root)
            summary_path = root / "summary.json"
            missing_completed, missing = self._run_guard(
                root,
                plan_path,
                pointer_path,
                summary_path,
            )
            summary_path.write_text(
                json.dumps(self._summary(plan_path, ledger_path)),
                encoding="utf-8",
            )
            complete_completed, complete = self._run_guard(
                root,
                plan_path,
                pointer_path,
                summary_path,
            )

        self.assertEqual(missing_completed.returncode, 0)
        self.assertEqual(missing["status"], "MISSING")
        self.assertTrue(missing["exact_postrun_allowed"])
        self.assertEqual(complete_completed.returncode, 0)
        self.assertEqual(complete["status"], "COMPLETE")
        self.assertFalse(complete["exact_postrun_allowed"])

    def test_guard_mode_fails_closed_on_bound_summary_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, ledger_path, pointer_path = self._write_plan(root)
            summary = self._summary(plan_path, ledger_path)
            summary["returns_read"] = True
            summary_path = root / "summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            completed, payload = self._run_guard(
                root,
                plan_path,
                pointer_path,
                summary_path,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "INTEGRITY_CONFLICT")
        self.assertFalse(payload["exact_postrun_allowed"])
        self.assertFalse(payload["new_collector_allowed"])


if __name__ == "__main__":
    unittest.main()
