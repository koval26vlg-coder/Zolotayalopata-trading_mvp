from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    automation = importlib.import_module("listing_automation_state")
except ModuleNotFoundError:
    automation = None


class ListingAutomationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(automation, "isolated listing automation state engine is missing")
        self.temp = tempfile.TemporaryDirectory(prefix="listing-state-tests-")
        self.addCleanup(self.temp.cleanup)
        self.clock = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)
        self.processes = {}
        self.paths = automation.AutomationPaths(Path(self.temp.name) / "automation")
        self.binding = automation.Binding("fixture_plan", "a" * 64, "b" * 64)
        self.engine = automation.AutomationEngine(
            self.paths,
            self.binding,
            now=lambda: self.clock,
            process_probe=lambda pid: self.processes.get(pid, automation.ProbeResult("DEAD")),
        )

    def identity(self, pid: int, offset: int = 0):
        return automation.ProcessIdentity(
            pid, (self.clock + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
        )

    def begin_running(self):
        self.engine.initialize()
        attempt = self.engine.begin_attempt()
        worker = self.identity(101)
        self.processes[101] = automation.ProbeResult("LIVE", worker)
        self.engine.bind_worker(attempt["attempt_id"], attempt["handoff_token"], worker)
        return attempt, worker

    def rows(self):
        if not self.paths.ledger.exists():
            return []
        return [json.loads(line) for line in self.paths.ledger.read_text().splitlines()]

    def files(self):
        if not self.paths.root.exists():
            return {}
        return {
            str(path.relative_to(self.paths.root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.paths.root.rglob("*") if path.is_file()
        }

    def test_initialize_is_immediately_due_and_utc_z_bound(self):
        result = self.engine.initialize()
        state = json.loads(self.paths.state.read_text())
        self.assertEqual(result["status"], "DUE")
        self.assertEqual(state["next_interval_at_utc"], "2026-08-26T00:00:00.000000Z")
        self.assertEqual(state["plan_id"], self.binding.plan_id)
        self.assertEqual(state["plan_hash"], self.binding.plan_hash)
        self.assertEqual(state["child_plan_hash"], self.binding.child_plan_hash)
        before = self.files()
        self.engine.initialize()
        self.assertEqual(before, self.files())

    def test_not_due_does_not_create_mutex_claim_or_touch_any_file(self):
        self.engine.initialize()
        self.engine.record_preflight_failure("gate_closed")
        self.paths.mutex.unlink()  # Remove only this disposable fixture's mutex.
        before = self.files()
        self.assertEqual(self.engine.read_due()["status"], "NOT_DUE")
        self.assertEqual(self.engine.status()["status"], "NOT_DUE")
        self.assertEqual(self.engine.begin_attempt()["status"], "NOT_DUE")
        self.assertEqual(before, self.files())
        self.assertFalse(self.paths.mutex.exists())
        self.assertFalse(self.paths.claim.exists())

    def test_handoff_persists_attempt_before_return_and_only_hashes_token(self):
        result = self.engine.begin_attempt()
        self.assertEqual(result["status"], "LAUNCHING")
        claim = json.loads(self.paths.claim.read_text())
        state = json.loads(self.paths.state.read_text())
        self.assertEqual(state["last_attempt_id"], result["attempt_id"])
        self.assertEqual(claim["handoff_token_sha256"], hashlib.sha256(result["handoff_token"].encode()).hexdigest())
        self.assertEqual(self.rows()[0]["kind"], "ATTEMPT_STARTED")
        self.assertTrue(all(result["handoff_token"] not in raw.decode() for raw, _ in self.files().values()))

    def test_wrong_token_or_attempt_cannot_bind_and_duplicate_is_read_only(self):
        attempt, worker = self.begin_running()
        before = self.files()
        with self.assertRaisesRegex(automation.AutomationStateError, "HANDOFF_MISMATCH"):
            self.engine.bind_worker(attempt["attempt_id"], "wrong", worker)
        with self.assertRaisesRegex(automation.AutomationStateError, "HANDOFF_MISMATCH"):
            self.engine.bind_worker("different", attempt["handoff_token"], worker)
        self.assertEqual(self.engine.begin_attempt()["status"], "ALREADY_RUNNING")
        self.assertEqual(before, self.files())

    def test_two_concurrent_ticks_create_exactly_one_handoff(self):
        self.engine.initialize()
        barrier = threading.Barrier(2)
        def tick():
            barrier.wait(timeout=5)
            return self.engine.begin_attempt()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: tick(), range(2)))
        self.assertEqual(sum(row["status"] == "LAUNCHING" for row in results), 1)
        self.assertEqual(sum("handoff_token" in row for row in results), 1)
        self.assertEqual(sum(row["kind"] == "ATTEMPT_STARTED" for row in self.rows()), 1)
        self.assertTrue(self.paths.mutex.exists())

    def test_unknown_unbound_handoff_is_preserved_without_timeout_reaping(self):
        self.engine.begin_attempt()
        before = self.files()
        self.clock += timedelta(days=2)
        self.assertEqual(self.engine.begin_attempt()["status"], "CLAIM_UNRESOLVED")
        self.assertEqual(self.engine.reconcile()["status"], "CLAIM_UNRESOLVED")
        self.assertEqual(before, self.files())

    def test_pid_reuse_means_old_owner_dead_not_same_live_worker(self):
        attempt, _ = self.begin_running()
        self.clock += timedelta(minutes=3)
        self.processes[101] = automation.ProbeResult("LIVE", self.identity(101))
        result = self.engine.reconcile()
        self.assertEqual(result["state_status"], "RETRY_NEXT_INTERVAL")
        self.assertTrue(result["pending_retry"])
        self.assertFalse(self.paths.claim.exists())
        self.assertEqual(len(list(self.paths.claim_archive.glob("*.json"))), 1)
        self.assertEqual(json.loads(self.paths.state.read_text())["last_attempt_id"], attempt["attempt_id"])
        self.assertEqual(result["next_interval_at_utc"], "2026-08-26T06:03:00.000000Z")

    def test_unknown_probe_retains_bound_owner(self):
        self.begin_running()
        self.processes[101] = automation.ProbeResult("UNKNOWN")
        before = self.files()
        self.assertEqual(self.engine.reconcile()["status"], "CLAIM_UNRESOLVED")
        self.assertEqual(before, self.files())

    def test_complete_rejected_while_child_live_and_retry_retains_claim_until_both_exit(self):
        attempt, worker = self.begin_running()
        child = self.identity(202)
        self.processes[202] = automation.ProbeResult("LIVE", child)
        self.engine.attach_child(attempt["attempt_id"], attempt["handoff_token"], child)
        before = self.files()
        with self.assertRaisesRegex(automation.AutomationStateError, "CHILD_NOT_EXITED"):
            self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="COMPLETE")
        self.assertEqual(before, self.files())
        result = self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="RETRY_NEXT_INTERVAL", reason="timeout")
        self.assertEqual(result["state_status"], "RETRY_NEXT_INTERVAL")
        self.assertIsNone(json.loads(self.paths.state.read_text())["worker_pid"])
        claim = json.loads(self.paths.claim.read_text())
        self.assertEqual(claim["worker"]["pid"], worker.pid)
        self.assertEqual(claim["child"]["pid"], child.pid)
        self.processes[101] = automation.ProbeResult("DEAD")
        self.assertEqual(self.engine.reconcile()["status"], "ALREADY_RUNNING")
        self.assertTrue(self.paths.claim.exists())
        self.processes[202] = automation.ProbeResult("DEAD")
        self.engine.reconcile()
        self.assertFalse(self.paths.claim.exists())
        self.assertEqual(len(list(self.paths.claim_archive.glob("*.json"))), 1)

    def test_completion_while_worker_alive_records_terminal_but_retains_identity(self):
        attempt, _ = self.begin_running()
        self.clock += timedelta(minutes=5)
        result = self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="COMPLETE", cadence_seconds=300)
        self.assertFalse(result["pending_retry"])
        self.assertEqual(result["next_interval_at_utc"], "2026-08-26T00:10:00.000000Z")
        self.assertTrue(self.paths.claim.exists())
        self.assertIsNone(json.loads(self.paths.state.read_text())["worker_pid"])
        self.processes[101] = automation.ProbeResult("DEAD")
        self.engine.reconcile()
        self.assertFalse(self.paths.claim.exists())

    def test_partial_next_interval_is_completion_plus_current_cadence(self):
        attempt, _ = self.begin_running()
        self.clock += timedelta(hours=1)
        result = self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="PARTIAL_RETRY_NEXT_INTERVAL", cadence_seconds=10800, reason="one venue failed")
        self.assertTrue(result["pending_retry"])
        self.assertEqual(result["next_interval_at_utc"], "2026-08-26T04:00:00.000000Z")

    def test_terminal_ledger_precedes_state_and_recovers_failed_state_persistence(self):
        attempt, _ = self.begin_running()
        self.clock += timedelta(minutes=2)
        with mock.patch.object(self.engine, "_write_state", side_effect=OSError("simulated state disk failure")):
            with self.assertRaises(OSError):
                self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="COMPLETE", cadence_seconds=3600)
        self.assertEqual(self.rows()[-1]["kind"], "TERMINAL")
        self.assertEqual(json.loads(self.paths.state.read_text())["status"], "RUNNING")
        self.processes[101] = automation.ProbeResult("DEAD")
        self.clock += timedelta(minutes=1)
        recovered = self.engine.reconcile()
        self.assertEqual(recovered["state_status"], "COMPLETE")
        self.assertEqual(recovered["next_interval_at_utc"], "2026-08-26T01:02:00.000000Z")
        self.assertFalse(self.paths.claim.exists())
        self.assertEqual(sum(row["kind"] == "TERMINAL" for row in self.rows()), 1)

    def test_old_complete_cannot_complete_new_attempt(self):
        first, _ = self.begin_running()
        self.engine.finish_attempt(first["attempt_id"], first["handoff_token"], outcome="COMPLETE", cadence_seconds=300)
        self.processes[101] = automation.ProbeResult("DEAD")
        self.engine.reconcile()
        self.clock += timedelta(minutes=6)
        second = self.engine.begin_attempt()
        identity = self.identity(303)
        self.processes[303] = automation.ProbeResult("LIVE", identity)
        self.engine.bind_worker(second["attempt_id"], second["handoff_token"], identity)
        self.processes[303] = automation.ProbeResult("DEAD")
        result = self.engine.reconcile()
        self.assertEqual(result["state_status"], "RETRY_NEXT_INTERVAL")
        self.assertEqual(result["last_attempt_id"], second["attempt_id"])

    def test_explicit_no_spawn_failure_releases_unbound_claim_but_generic_failure_does_not(self):
        attempt = self.engine.begin_attempt()
        self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="RETRY_NEXT_INTERVAL", reason="ambiguous spawn")
        self.assertTrue(self.paths.claim.exists())
        self.assertEqual(self.engine.reconcile()["status"], "CLAIM_UNRESOLVED")
        other_paths = automation.AutomationPaths(Path(self.temp.name) / "known-no-spawn")
        other = automation.AutomationEngine(other_paths, self.binding, now=lambda: self.clock, process_probe=lambda _: automation.ProbeResult("UNKNOWN"))
        attempt = other.begin_attempt()
        other.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="RETRY_NEXT_INTERVAL", reason="spawn failed before creation", no_worker_spawned=True)
        self.assertFalse(other_paths.claim.exists())
        self.assertEqual(len(list(other_paths.claim_archive.glob("*.json"))), 1)

    def test_corrupt_or_old_binding_state_never_gets_overwritten(self):
        self.engine.initialize()
        original = self.paths.state.read_bytes()
        state = json.loads(original)
        state["plan_hash"] = "c" * 64
        for raw in (b"{corrupt", json.dumps(state).encode()):
            self.paths.state.write_bytes(raw)
            before = self.files()
            with self.assertRaises(automation.AutomationStateError):
                self.engine.begin_attempt()
            self.assertEqual(before, self.files())

    def test_preflight_failure_has_terminal_ledger_and_persists_retry(self):
        self.engine.initialize()
        result = self.engine.record_preflight_failure("plan mismatch", cadence_seconds=3600)
        self.assertEqual(result["state_status"], "RETRY_NEXT_INTERVAL")
        self.assertEqual(result["next_interval_at_utc"], "2026-08-26T01:00:00.000000Z")
        self.assertFalse(self.paths.claim.exists())
        self.assertEqual(self.rows()[-1]["kind"], "PREFLIGHT_FAILURE")
        self.assertEqual(self.rows()[-1]["plan_hash"], self.binding.plan_hash)

    def test_preflight_terminal_can_recover_failure_before_state_write(self):
        self.engine.initialize()
        with mock.patch.object(self.engine, "_write_state", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.engine.record_preflight_failure("gate", cadence_seconds=300)
        self.assertEqual(self.engine.reconcile()["state_status"], "RETRY_NEXT_INTERVAL")
        self.assertEqual(json.loads(self.paths.state.read_text())["next_interval_at_utc"], "2026-08-26T00:05:00.000000Z")

    def test_only_frozen_cadences_are_accepted(self):
        for invalid in (0, 1, 299, 301, 7200, True):
            with self.assertRaisesRegex(automation.AutomationStateError, "CADENCE_INVALID"):
                self.engine.initialize(cadence_seconds=invalid)
        self.assertFalse(self.paths.root.exists())

    def test_tampered_terminal_record_is_not_reconciled(self):
        attempt, _ = self.begin_running()
        with mock.patch.object(self.engine, "_write_state", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.engine.finish_attempt(attempt["attempt_id"], attempt["handoff_token"], outcome="RETRY_NEXT_INTERVAL")
        rows = self.rows()
        rows[-1]["state_after"]["status"] = "COMPLETE"
        self.paths.ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.processes[101] = automation.ProbeResult("DEAD")
        before = self.files()
        with self.assertRaisesRegex(automation.AutomationStateError, "LEDGER_HASH_MISMATCH"):
            self.engine.reconcile()
        self.assertEqual(before, self.files())


if __name__ == "__main__":
    unittest.main()
