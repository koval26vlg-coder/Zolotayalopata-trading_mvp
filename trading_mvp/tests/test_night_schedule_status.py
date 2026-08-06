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


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from night_schedule_plan import build_night_schedule_plan  # noqa: E402
from night_schedule_status import evaluate_night_schedule_status  # noqa: E402
from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class NightScheduleStatusTests(unittest.TestCase):
    def _fixture(self, root: Path, *, days: int = 120) -> tuple[Path, str, dict]:
        bank = root / "bank.json"
        _write_json(
            bank,
            {
                "version": "fixture-v1",
                "hypotheses": [
                    {
                        "id": "pit_universe_membership_drift_reversion_v1",
                        "status": "BANKED_NEEDS_NEW_DATA",
                        "required_data_type": "PIT_UNIVERSE_V2_FORWARD",
                        "contract": build_pit_membership_drift_contract(),
                        "minimum_data": {"days": days},
                    }
                ],
            },
        )
        goal = root / "goal.md"
        goal.write_text("# Goal fixture\n", encoding="utf-8")
        plan_path = root / "schedule.json"
        built = build_night_schedule_plan(
            hypothesis_bank_path=bank,
            hypothesis_id="pit_universe_membership_drift_reversion_v1",
            data_type="PIT_UNIVERSE_V2_FORWARD",
            goal_path=goal,
            output_path=plan_path,
            schedule_start_date="2026-07-14",
            nights=2,
            segment_start_local="23:00",
            segment_duration_sec=1200,
            interval_sec=300,
            output_root=str(root / "data"),
            created_at_utc="2026-07-14T13:00:00+00:00",
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        return plan_path, built["plan_hash"], plan

    def _approve(self, root: Path, plan_path: Path, plan_hash: str, plan: dict) -> Path:
        approval_path = root / "approvals" / f"{plan_hash}.approval.json"
        _write_json(
            approval_path,
            {
                "schema": "trading_mvp_night_schedule_approval_v1",
                "status": "ACTIVE",
                "approved_at": "2026-07-14T17:00:00+03:00",
                "expires_at": plan["segments"][-1]["hard_deadline_local"],
                "approved_by": "User",
                "approval_scope": "one frozen schedule; no auto-resume; no OOS/grid/paper/live/API keys",
                "plan_path": str(plan_path.resolve()),
                "plan_hash": plan_hash,
                "plan_file_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "data_type": "PIT_UNIVERSE_V2_FORWARD",
                "segment_run_ids": [item["run_id"] for item in plan["segments"]],
                "visible_terminal_required": True,
                "data_embargo": True,
                "auto_resume_allowed": False,
            },
        )
        return approval_path.parent

    def _manifest(self, plan: dict, sequence: int, **overrides: object) -> Path:
        segment = plan["segments"][sequence - 1]
        path = Path(plan["output_root"]) / segment["run_id"] / "manifest.json"
        payload: dict[str, object] = {
            "schema": "pit_universe_snapshot_manifest_v2",
            "mode": "pit_universe_snapshot_collect",
            "run_id": segment["run_id"],
            "started_at_utc": "2026-07-14T20:00:00+00:00",
            "updated_at_utc": "2026-07-14T20:20:00+00:00",
            "finished_at_utc": "2026-07-14T20:20:00+00:00",
            "stopped_at_utc": None,
            "final": True,
            "incomplete": False,
            "status": "COMPLETED",
            "stop_condition": "duration_sec",
            "stop_reason": None,
            "duration_sec": segment["duration_sec"],
            "interval_sec": segment["interval_sec"],
            "timeout_sec": 10,
            "min_contracts_per_exchange": 50,
            "cycle_count": segment["expected_cycles_floor"],
            "rows_total": 100,
            "errors_total": 0,
            "last_successful_exchanges": ["gateio", "mexc"],
        }
        payload.update(overrides)
        _write_json(path, payload)
        return path

    def test_unapproved_schedule_is_fail_closed_without_market_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, _plan = self._fixture(root)
            report = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=root / "approvals",
                now="2026-07-14T22:00:00+03:00",
            )

        self.assertEqual(report["decision"], "AWAIT_EXPLICIT_SCHEDULE_APPROVAL")
        self.assertFalse(report["approval"]["valid"])
        self.assertEqual(report["summary"]["PLANNED"], 2)
        self.assertFalse(report["collection_started"])
        self.assertFalse(report["oos_allowed"])
        self.assertFalse(report["returns_read"])
        self.assertFalse(report["pnl_read"])
        self.assertEqual(report["next_allowed_action"], "await_explicit_night_schedule_approval")

    def test_approved_segment_becomes_due_only_inside_its_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan = self._fixture(root)
            approval_root = self._approve(root, plan_path, plan_hash, plan)
            report = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-14T23:10:00+03:00",
            )

        self.assertTrue(report["approval"]["valid"])
        self.assertEqual(report["decision"], "NIGHT_SEGMENT_DUE")
        self.assertEqual(report["summary"]["DUE"], 1)
        self.assertEqual(report["summary"]["PLANNED"], 1)
        self.assertEqual(report["segments"][0]["status"], "DUE")
        self.assertEqual(report["next_allowed_action"], "start_due_segment_in_visible_terminal")

    def test_live_lock_marks_segment_running_and_monitor_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan = self._fixture(root)
            approval_root = self._approve(root, plan_path, plan_hash, plan)
            manifest_path = self._manifest(
                plan,
                1,
                final=False,
                incomplete=False,
                status="RUNNING",
                stop_condition=None,
                finished_at_utc=None,
                cycle_count=1,
            )
            _write_json(manifest_path.parent / "collector.lock", {"pid": os.getpid()})
            report = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-14T23:10:00+03:00",
            )

        self.assertEqual(report["decision"], "NIGHT_SEGMENT_RUNNING")
        self.assertEqual(report["segments"][0]["status"], "RUNNING")
        self.assertTrue(report["segments"][0]["collector_pid_alive"])
        self.assertEqual(report["next_allowed_action"], "monitor_running_segment_only")

    def test_final_manifest_counts_only_technical_completion_not_quality_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan = self._fixture(root)
            approval_root = self._approve(root, plan_path, plan_hash, plan)
            self._manifest(plan, 1)
            report = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-15T08:00:00+03:00",
            )

        self.assertEqual(report["segments"][0]["status"], "COMPLETED")
        self.assertEqual(report["coverage"]["technically_completed_dates"], 1)
        self.assertEqual(report["coverage"]["quality_certified_dates"], 0)
        self.assertEqual(report["coverage"]["train_feasibility_required_days"], 20)
        self.assertFalse(report["coverage"]["train_feasibility_gate_satisfied"])
        self.assertFalse(report["coverage"]["minimum_data_gate_satisfied"])
        self.assertFalse(report["oos_allowed"])

    def test_incomplete_manifest_requires_same_run_id_visible_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan = self._fixture(root)
            approval_root = self._approve(root, plan_path, plan_hash, plan)
            self._manifest(
                plan,
                1,
                final=False,
                incomplete=True,
                status="STOPPED_INCOMPLETE",
                stop_condition="collector_exception",
                stop_reason="ConnectionError: VPN unavailable",
                finished_at_utc=None,
            )
            report = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-14T23:15:00+03:00",
            )

        self.assertEqual(report["decision"], "NIGHT_SEGMENT_STOPPED_INCOMPLETE")
        self.assertEqual(report["segments"][0]["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(report["segments"][0]["stop_reason"], "ConnectionError: VPN unavailable")
        self.assertEqual(report["next_allowed_action"], "resume_incomplete_segment_visible_same_run_id")

    def test_missing_manifest_after_deadline_is_recorded_as_missed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan = self._fixture(root)
            approval_root = self._approve(root, plan_path, plan_hash, plan)
            report = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-15T08:00:00+03:00",
            )

        self.assertEqual(report["segments"][0]["status"], "MISSED")
        self.assertEqual(report["summary"]["MISSED"], 1)
        self.assertEqual(report["decision"], "NIGHT_SEGMENT_MISSED")
        self.assertEqual(report["next_allowed_action"], "record_missed_segment_and_wait_for_next_window")

    def test_output_is_deterministic_for_fixed_now_and_does_not_mutate_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, plan = self._fixture(root)
            approval_root = self._approve(root, plan_path, plan_hash, plan)
            original = plan_path.read_bytes()
            first = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-14T22:00:00+03:00",
            )
            second = evaluate_night_schedule_status(
                plan_path,
                plan_hash,
                approval_record_root=approval_root,
                now="2026-07-14T22:00:00+03:00",
            )

            self.assertEqual(plan_path.read_bytes(), original)

        self.assertEqual(first, second)

    def test_run_mvp_exposes_short_status_action_without_starting_collection(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, plan_hash, _plan = self._fixture(root)
            output_path = root / "status.json"
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "trading_mvp" / "run_mvp.ps1"),
                    "-Action",
                    "fast-edge-night-schedule-status",
                    "-PlanPath",
                    str(plan_path),
                    "-ExpectedPlanHash",
                    plan_hash,
                    "-ApprovalRecordRoot",
                    str(root / "approvals"),
                    "-OutputPath",
                    str(output_path),
                    "-MaxRuntimeSec",
                    "120",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload.get("decision"), "AWAIT_EXPLICIT_SCHEDULE_APPROVAL")
        self.assertFalse(payload.get("collection_started", True))
        self.assertFalse(payload.get("returns_read", True))


if __name__ == "__main__":
    unittest.main()
