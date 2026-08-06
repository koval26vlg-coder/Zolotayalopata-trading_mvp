from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_forward_failure_runbook as runbook_module  # noqa: E402


def _inputs(root: Path) -> tuple[Path, Path, Path, Path]:
    runtime = root / "runtime.py"
    monitor = root / "monitor.py"
    reconciliation = root / "reconciliation.py"
    for path in (runtime, monitor, reconciliation):
        path.write_text("fixture\n", encoding="utf-8")
    evidence = root / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": runbook_module.FAULT_EVIDENCE_SCHEMA,
                "verdict": "FAIL_CLOSED_RECOVERY_VERIFIED",
                "scenarios": {
                    "bounded_interruption_resume": "PASS",
                    "duplicate_sample_sequence": "FAIL_CLOSED",
                    "existing_writer_lock": "FAIL_CLOSED",
                    "truncated_jsonl": "FAIL_CLOSED",
                    "disk_write_failure": "STOPPED_INCOMPLETE_INTEGRITY",
                    "fixture_hash_drift": "FAIL_CLOSED",
                    "expected_plan_hash_drift": "FAIL_CLOSED",
                },
            }
        ),
        encoding="utf-8",
    )
    return runtime, monitor, reconciliation, evidence


def _runbook(root: Path) -> dict:
    runtime, monitor, reconciliation, evidence = _inputs(root)
    return runbook_module.build_failure_runbook(
        observer_runtime_path=runtime,
        observer_monitor_path=monitor,
        reconciliation_adapter_path=reconciliation,
        fault_evidence_path=evidence,
        generated_at_utc="2026-07-28T21:30:00+00:00",
    )


class PaperForwardFailureRunbookTests(unittest.TestCase):
    def test_required_incidents_are_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        self.assertEqual(
            set(runbook["incidents"]),
            runbook_module.REQUIRED_INCIDENTS,
        )
        self.assertEqual(
            runbook["verdict"], "FAILURE_RUNBOOK_FROZEN_FAIL_CLOSED"
        )

    def test_schema_drift_and_reconciliation_require_critical_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        schema = runbook_module.incident_action(runbook, "schema_drift")
        reconciliation = runbook_module.incident_action(
            runbook, "reconciliation_mismatch"
        )
        self.assertEqual(schema["severity"], "CRITICAL")
        self.assertIn("CRITICAL", schema["resume_policy"])
        self.assertEqual(reconciliation["state"], "HALT_PAPER_OMS")

    def test_quota_stop_pauses_agent_not_healthy_collector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        quota = runbook["incidents"]["weekly_quota_stop"]
        self.assertIn(
            "do_not_claim_new_backlog_task", quota["immediate_actions"]
        )
        self.assertIn(
            "kill_healthy_visible_collector_only_to_save_agent_tokens",
            quota["forbidden_actions"],
        )
        self.assertEqual(
            quota["resume_policy"],
            "AUTOMATIC_RESUME_FROM_PERSISTED_BACKLOG_AFTER_RESET",
        )

    def test_disk_pressure_never_deletes_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        disk = runbook["incidents"]["disk_pressure"]
        self.assertIn(
            "delete_user_files_automatically", disk["forbidden_actions"]
        )
        self.assertFalse(
            runbook["global_invariants"][
                "automatic_user_file_deletion"
            ]
        )

    def test_rehashed_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        tampered = deepcopy(runbook)
        tampered["incidents"]["writer_lock_contention"][
            "forbidden_actions"
        ] = []
        tampered["runbook_hash_sha256"] = runbook_module.runbook_hash(
            tampered
        )
        with self.assertRaisesRegex(ValueError, "definitions changed"):
            runbook_module.validate_failure_runbook(tampered)

    def test_builder_launches_nothing_and_uses_no_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        self.assertEqual(runbook["process_launches"], 0)
        self.assertEqual(runbook["network_requests"], 0)
        self.assertFalse(runbook["global_invariants"]["live_orders"])
        self.assertFalse(runbook["global_invariants"]["private_api_keys"])

    def test_unknown_incident_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runbook = _runbook(Path(tmp))
        with self.assertRaisesRegex(ValueError, "unknown incident"):
            runbook_module.incident_action(runbook, "unknown")


if __name__ == "__main__":
    unittest.main()
