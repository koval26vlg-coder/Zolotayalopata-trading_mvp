from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402
from night_schedule_plan import build_night_schedule_plan  # noqa: E402


class NightSchedulePointerRestoreTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, str, Path, Path, str]:
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
        start_date = (date.today() + timedelta(days=2)).isoformat()
        result = build_night_schedule_plan(
            hypothesis_bank_path=bank,
            hypothesis_id="pit_universe_membership_drift_reversion_v1",
            data_type="PIT_UNIVERSE_V2_FORWARD",
            goal_path=goal,
            output_path=plan_path,
            schedule_start_date=start_date,
            nights=2,
            segment_start_local="23:00",
            segment_duration_sec=1200,
            interval_sec=300,
            output_root=str(root / "data"),
        )
        run_id = json.loads(plan_path.read_text(encoding="utf-8"))["segments"][0]["run_id"]
        gate = root / "active-run-gate.json"
        gate.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "completed_supplemental_run",
                    "status": "READY_FOR_POSTPROCESS",
                    "gate_status": "READY_FOR_POSTPROCESS",
                    "next_goal_decision": "SUPPLEMENTAL_COMPLETED",
                    "replay_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        return plan_path, result["plan_hash"], gate, root / "approvals", run_id

    def _approve(
        self,
        pwsh: str,
        plan: Path,
        plan_hash: str,
        gate: Path,
        approval_root: Path,
    ) -> Path:
        approval_script = REPO_ROOT / "tools" / "approve_trading_night_schedule.ps1"
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(approval_script),
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
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return Path(json.loads(completed.stdout)["approval_record_path"])

    def _restore(
        self,
        pwsh: str,
        plan: Path,
        plan_hash: str,
        gate: Path,
        approval: Path,
        run_id: str,
    ) -> subprocess.CompletedProcess[str]:
        restore_script = REPO_ROOT / "tools" / "restore_trading_night_schedule_pointer.ps1"
        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = sys.executable
        return subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(restore_script),
                "-PlanPath",
                str(plan),
                "-ExpectedPlanHash",
                plan_hash,
                "-ApprovalRecordPath",
                str(approval),
                "-GatePath",
                str(gate),
                "-RunId",
                run_id,
                "-ConfirmedPointerRestore",
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            env=env,
        )

    def test_restores_pointer_from_existing_immutable_approval(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, run_id = self._fixture(Path(temp_dir))
            approval = self._approve(pwsh, plan, plan_hash, gate, approval_root)
            approval_sha_before = hashlib.sha256(approval.read_bytes()).hexdigest()

            gate_payload = json.loads(gate.read_text(encoding="utf-8-sig"))
            gate_payload["approved_night_schedule"] = {
                "status": "ACTIVE",
                "plan_hash": "supplemental-plan-hash",
            }
            gate.write_text(json.dumps(gate_payload), encoding="utf-8")

            completed = self._restore(pwsh, plan, plan_hash, gate, approval, run_id)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            restored_gate = json.loads(gate.read_text(encoding="utf-8-sig"))

            self.assertEqual(result["decision"], "NIGHT_SCHEDULE_POINTER_RESTORED")
            self.assertEqual(result["previous_plan_hash"], "supplemental-plan-hash")
            self.assertEqual(restored_gate["approved_night_schedule"]["plan_hash"], plan_hash)
            self.assertEqual(restored_gate["run_id"], "completed_supplemental_run")
            self.assertEqual(restored_gate["status"], "READY_FOR_POSTPROCESS")
            self.assertFalse(result["collection_started"])
            self.assertEqual(hashlib.sha256(approval.read_bytes()).hexdigest(), approval_sha_before)

    def test_refuses_tampered_approval_without_changing_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, run_id = self._fixture(Path(temp_dir))
            approval = self._approve(pwsh, plan, plan_hash, gate, approval_root)
            approval_payload = json.loads(approval.read_text(encoding="utf-8-sig"))
            approval_payload["segment_run_ids"] = ["different_run"]
            approval.write_text(json.dumps(approval_payload), encoding="utf-8")

            gate_payload = json.loads(gate.read_text(encoding="utf-8-sig"))
            gate_payload["approved_night_schedule"] = {
                "status": "ACTIVE",
                "plan_hash": "supplemental-plan-hash",
            }
            gate.write_text(json.dumps(gate_payload), encoding="utf-8")
            gate_sha_before = hashlib.sha256(gate.read_bytes()).hexdigest()

            completed = self._restore(pwsh, plan, plan_hash, gate, approval, run_id)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "does not authorize run_id",
                " ".join(completed.stderr.replace("|", " ").split()),
            )
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_sha_before)

    def test_refuses_restore_while_gate_is_running(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, run_id = self._fixture(Path(temp_dir))
            approval = self._approve(pwsh, plan, plan_hash, gate, approval_root)
            gate_payload = json.loads(gate.read_text(encoding="utf-8-sig"))
            gate_payload["status"] = "RUNNING"
            gate_payload["gate_status"] = "RUNNING"
            gate.write_text(json.dumps(gate_payload), encoding="utf-8")

            completed = self._restore(pwsh, plan, plan_hash, gate, approval, run_id)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("RUNNING", completed.stderr)


if __name__ == "__main__":
    unittest.main()
