from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from night_schedule_plan import build_night_schedule_plan  # noqa: E402
from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402


class NightScheduleApprovalTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, str, Path, Path]:
        local_tz = timezone(timedelta(hours=3))
        schedule_start_date = (datetime.now(local_tz) + timedelta(days=1)).date().isoformat()
        bank = root / "bank.json"
        bank.write_text(
            json.dumps(
                {
                    "version": "fixture-v1",
                    "hypotheses": [
                        {
                            "id": "pit_universe_membership_drift_reversion_v1",
                            "status": "BANKED_NEEDS_NEW_DATA",
                            "required_data_type": "PIT_UNIVERSE_V2_FORWARD",
                            "contract": build_pit_membership_drift_contract(),
                            "minimum_data": {"days": 120},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        goal = root / "goal.md"
        goal.write_text("# Immutable goal fixture\n", encoding="utf-8")
        plan_path = root / "schedule.json"
        result = build_night_schedule_plan(
            hypothesis_bank_path=bank,
            hypothesis_id="pit_universe_membership_drift_reversion_v1",
            data_type="PIT_UNIVERSE_V2_FORWARD",
            goal_path=goal,
            output_path=plan_path,
            schedule_start_date=schedule_start_date,
            nights=2,
            segment_start_local="23:00",
            segment_duration_sec=1200,
            interval_sec=300,
            output_root=str(root / "data"),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        gate = root / "active-run-gate.json"
        gate.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "status": "READY_FOR_POSTPROCESS",
                    "gate_status": "READY_FOR_POSTPROCESS",
                    "next_goal_decision": "NO_FAST_EDGE_FOUND",
                    "replay_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        return plan_path, result["plan_hash"], gate, root / "approvals"

    def test_explicit_approval_writes_immutable_record_and_updates_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        script = REPO_ROOT / "tools" / "approve_trading_night_schedule.ps1"
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root = self._fixture(Path(temp_dir))
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-PlanPath",
                    str(plan),
                    "-ExpectedPlanHash",
                    plan_hash,
                    "-GatePath",
                    str(gate),
                    "-ApprovalRecordRoot",
                    str(approval_root),
                    "-ConfirmedNightScheduleApproval",
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            gate_payload = json.loads(gate.read_text(encoding="utf-8-sig"))
            approval = json.loads(Path(payload["approval_record_path"]).read_text(encoding="utf-8-sig"))

        self.assertEqual(payload["decision"], "NIGHT_SCHEDULE_APPROVED")
        self.assertEqual(approval["plan_hash"], plan_hash)
        self.assertEqual(approval["status"], "ACTIVE")
        self.assertEqual(gate_payload["approved_night_schedule"]["plan_hash"], plan_hash)
        self.assertEqual(approval["collection_stage"], "train_accrual")
        self.assertEqual(gate_payload["approved_night_schedule"]["collection_stage"], "train_accrual")
        self.assertEqual(
            approval["quality_ledger_path"],
            gate_payload["approved_night_schedule"]["quality_ledger_path"],
        )
        self.assertEqual(gate_payload["next_goal_decision"], "PIT_UNIVERSE_V2_NIGHT_SCHEDULE_APPROVED")
        self.assertFalse(gate_payload["replay_allowed"])

    def test_refuses_approval_without_explicit_confirmation(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        script = REPO_ROOT / "tools" / "approve_trading_night_schedule.ps1"
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root = self._fixture(Path(temp_dir))
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-PlanPath",
                    str(plan),
                    "-ExpectedPlanHash",
                    plan_hash,
                    "-GatePath",
                    str(gate),
                    "-ApprovalRecordRoot",
                    str(approval_root),
                ],
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("ConfirmedNightScheduleApproval", completed.stderr)


if __name__ == "__main__":
    unittest.main()
