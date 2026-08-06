from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from owned_run_gate import publish_owned_run_gate  # noqa: E402


class OwnedRunGateTests(unittest.TestCase):
    def test_market_writer_preserves_active_immutable_night_schedule_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / "docs" / "agent-log" / "active-run-gate.json"
            gate.parent.mkdir(parents=True)
            approval = {
                "status": "ACTIVE",
                "plan_path": str(root / "sealed-night-plan.json"),
                "plan_hash": "a" * 64,
                "approval_record_path": str(root / "approval.json"),
                "approval_record_sha256": "b" * 64,
                "auto_resume_allowed": False,
            }
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "previous-run",
                        "status": "READY_FOR_POSTPROCESS",
                        "approved_night_schedule": approval,
                    }
                ),
                encoding="utf-8",
            )

            publish_owned_run_gate(
                gate,
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "basis-v2-writer",
                    "status": "RUNNING",
                    "gate_status": "RUNNING",
                    "updated_at": "2026-07-16T07:00:00Z",
                    "manifest_path": str(root / "manifest.json"),
                    "output": {"path": str(root / "output"), "kind": "directory"},
                    "collector_pid": 123,
                    "process_ids": [123],
                },
                run_type="historical_basis_v2_history_collect",
            )

            published = json.loads(gate.read_text(encoding="utf-8"))
            self.assertEqual(published["run_id"], "basis-v2-writer")
            self.assertEqual(published["status"], "RUNNING")
            self.assertEqual(published["approved_night_schedule"], approval)

    def test_market_writer_cannot_replace_existing_night_schedule_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / "active-run-gate.json"
            original = {"status": "ACTIVE", "plan_hash": "a" * 64}
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "previous-run",
                        "status": "READY_FOR_POSTPROCESS",
                        "approved_night_schedule": original,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "approved_night_schedule"):
                publish_owned_run_gate(
                    gate,
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "intruder",
                        "status": "RUNNING",
                        "updated_at": "2026-07-16T07:00:00Z",
                        "approved_night_schedule": {
                            "status": "ACTIVE",
                            "plan_hash": "c" * 64,
                        },
                    },
                    run_type="historical_basis_v2_history_collect",
                )

            unchanged = json.loads(gate.read_text(encoding="utf-8"))
            self.assertEqual(unchanged["approved_night_schedule"], original)
            self.assertEqual(unchanged["run_id"], "previous-run")


if __name__ == "__main__":
    unittest.main()
