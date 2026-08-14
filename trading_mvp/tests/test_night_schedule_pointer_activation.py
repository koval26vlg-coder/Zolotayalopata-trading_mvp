from __future__ import annotations

import hashlib
import json
import os
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

from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402
from night_schedule_plan import build_night_schedule_plan  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NightSchedulePointerActivationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, str, Path, Path, Path]:
        local_tz = timezone(timedelta(hours=3))
        schedule_start_date = (
            datetime.now(local_tz) + timedelta(days=2)
        ).date().isoformat()
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
        ledger = root / "quality-certifications.jsonl"
        ledger.write_text("", encoding="utf-8")
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
            quality_ledger_path=ledger,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        gate = root / "active-run-gate.json"
        gate.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "completed_other_run",
                    "status": "READY_FOR_POSTPROCESS",
                    "gate_status": "READY_FOR_POSTPROCESS",
                    "next_goal_decision": "OTHER_RUN_COMPLETE",
                    "replay_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        return (
            plan_path,
            result["plan_hash"],
            gate,
            root / "approvals",
            root / "schedule-pointer.json",
        )

    def _invoke(
        self,
        pwsh: str,
        plan: Path,
        plan_hash: str,
        gate: Path,
        approval_root: Path,
        pointer: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        script = (
            REPO_ROOT
            / "tools"
            / "activate_approved_trading_night_schedule_pointer.ps1"
        )
        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = sys.executable
        return subprocess.run(
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
                "-SchedulePointerPath",
                str(pointer),
                "-GlobalWriterClaimPath",
                str(pointer.parent / "active-market-data-writer-claim.json"),
                *extra,
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            env=env,
        )

    def _approve_only(
        self,
        pwsh: str,
        plan: Path,
        plan_hash: str,
        gate: Path,
        approval_root: Path,
    ) -> Path:
        script = REPO_ROOT / "tools" / "approve_trading_night_schedule.ps1"
        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = sys.executable
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
            capture_output=True,
            timeout=60,
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return Path(json.loads(completed.stdout)["approval_record_path"])

    def test_activation_creates_receipt_gate_binding_and_dynamic_pointer(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            completed = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            receipt = Path(result["approval_record_path"])
            gate_payload = json.loads(gate.read_text(encoding="utf-8-sig"))
            pointer_payload = json.loads(pointer.read_text(encoding="utf-8-sig"))

            self.assertEqual(result["decision"], "NIGHT_SCHEDULE_POINTER_ACTIVATED")
            self.assertTrue(result["approval_created"])
            self.assertEqual(pointer_payload["plan_hash"], plan_hash)
            self.assertEqual(pointer_payload["approval_path"], str(receipt.resolve()))
            self.assertEqual(pointer_payload["approval_sha256"], _sha256(receipt))
            self.assertEqual(
                gate_payload["approved_night_schedule"]["plan_hash"], plan_hash
            )
            self.assertFalse(result["collection_started"])
            self.assertFalse(result["network_access"])

    def test_preflight_has_no_side_effects(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            gate_sha_before = _sha256(gate)

            completed = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-PreflightOnly",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                result["decision"], "READY_TO_CREATE_APPROVAL_AND_ACTIVATE"
            )
            self.assertEqual(result["side_effects"], "NONE")
            self.assertEqual(_sha256(gate), gate_sha_before)
            self.assertFalse(pointer.exists())
            self.assertFalse(approval_root.exists())

    def test_activation_recovers_existing_receipt_and_stale_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            receipt = self._approve_only(
                pwsh, plan, plan_hash, gate, approval_root
            )
            stale_gate = json.loads(gate.read_text(encoding="utf-8-sig"))
            stale_gate.pop("approved_night_schedule")
            stale_gate["next_goal_decision"] = "INTERRUPTED_AFTER_RECEIPT"
            gate.write_text(json.dumps(stale_gate), encoding="utf-8")

            completed = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            restored_gate = json.loads(gate.read_text(encoding="utf-8-sig"))
            self.assertFalse(result["approval_created"])
            self.assertTrue(result["partial_activation_recovered"])
            self.assertEqual(
                restored_gate["approved_night_schedule"]["plan_hash"], plan_hash
            )
            self.assertEqual(
                json.loads(pointer.read_text(encoding="utf-8-sig"))["approval_sha256"],
                _sha256(receipt),
            )

    def test_repeated_exact_activation_is_idempotent(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            first = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            gate_sha_before = _sha256(gate)
            pointer_sha_before = _sha256(pointer)
            receipt_path = Path(json.loads(first.stdout)["approval_record_path"])
            receipt_sha_before = _sha256(receipt_path)

            second = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                json.loads(second.stdout)["decision"],
                "NIGHT_SCHEDULE_POINTER_ALREADY_ACTIVE",
            )
            self.assertEqual(_sha256(gate), gate_sha_before)
            self.assertEqual(_sha256(pointer), pointer_sha_before)
            self.assertEqual(_sha256(receipt_path), receipt_sha_before)

    def test_tampered_existing_receipt_fails_without_pointer_write(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            receipt = self._approve_only(
                pwsh, plan, plan_hash, gate, approval_root
            )
            approval = json.loads(receipt.read_text(encoding="utf-8-sig"))
            approval["segment_run_ids"] = ["different_run"]
            receipt.write_text(json.dumps(approval), encoding="utf-8")
            gate_sha_before = _sha256(gate)

            completed = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("segment_run_ids", completed.stderr)
            self.assertEqual(_sha256(gate), gate_sha_before)
            self.assertFalse(pointer.exists())

    def test_expanded_existing_receipt_expiry_fails_closed(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            receipt = self._approve_only(
                pwsh, plan, plan_hash, gate, approval_root
            )
            approval = json.loads(receipt.read_text(encoding="utf-8-sig"))
            approval["expires_at"] = (
                datetime.fromisoformat(approval["expires_at"]) + timedelta(days=1)
            ).isoformat()
            receipt.write_text(json.dumps(approval), encoding="utf-8")
            gate_sha_before = _sha256(gate)

            completed = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("expires_at does not equal", completed.stderr)
            self.assertEqual(_sha256(gate), gate_sha_before)
            self.assertFalse(pointer.exists())

    def test_global_writer_claim_blocks_activation_without_writes(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            claim = pointer.parent / "active-market-data-writer-claim.json"
            claim.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_global_market_writer_claim_v1",
                        "status": "CLAIMED",
                        "run_id": "other_writer",
                    }
                ),
                encoding="utf-8",
            )
            gate_sha_before = _sha256(gate)

            completed = self._invoke(
                pwsh,
                plan,
                plan_hash,
                gate,
                approval_root,
                pointer,
                "-ConfirmedNightScheduleActivation",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Global market writer claim exists", completed.stderr)
            self.assertEqual(_sha256(gate), gate_sha_before)
            self.assertFalse(pointer.exists())
            self.assertFalse(approval_root.exists())

    def test_refuses_activation_without_confirmation(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, plan_hash, gate, approval_root, pointer = self._fixture(
                Path(temp_dir)
            )
            gate_sha_before = _sha256(gate)

            completed = self._invoke(
                pwsh, plan, plan_hash, gate, approval_root, pointer
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ConfirmedNightScheduleActivation", completed.stderr)
            self.assertEqual(_sha256(gate), gate_sha_before)
            self.assertFalse(pointer.exists())
            self.assertFalse(approval_root.exists())


if __name__ == "__main__":
    unittest.main()
