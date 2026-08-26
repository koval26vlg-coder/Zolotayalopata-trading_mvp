from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

import listing_automation_state as automation  # noqa: E402


class InspectTests(unittest.TestCase):
    """inspect() answers 'is anyone running' without becoming the one who is.

    A launcher standing in front of a scheduler has to distinguish not due, already
    running, and free to start. Only the first is visible in the state; the other two
    live in the claim. Reading the claim to find out must not create one, which is what
    calling begin_attempt to look would do."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="inspect-tests-")
        self.addCleanup(self.temp.cleanup)
        self.clock = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)
        self.processes: dict[int, automation.ProbeResult] = {}
        self.paths = automation.AutomationPaths(Path(self.temp.name) / "automation")
        self.engine = automation.AutomationEngine(
            self.paths,
            automation.Binding("fixture_plan", "a" * 64, "b" * 64),
            now=lambda: self.clock,
            process_probe=lambda pid: self.processes.get(pid, automation.ProbeResult("DEAD")),
        )

    def identity(self, pid: int, offset: int = 0) -> automation.ProcessIdentity:
        return automation.ProcessIdentity(
            pid, (self.clock + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
        )

    def start_worker(self, pid: int = 101, *, live: bool = True):
        self.engine.initialize()
        attempt = self.engine.begin_attempt()
        worker = self.identity(pid)
        if live:
            self.processes[pid] = automation.ProbeResult("LIVE", worker)
        self.engine.bind_worker(attempt["attempt_id"], attempt["handoff_token"], worker)
        return attempt, worker

    def test_a_fresh_automation_reports_due_with_no_claim(self) -> None:
        self.engine.initialize()
        verdict = self.engine.inspect()
        self.assertEqual(automation.STATUS_DUE, verdict["status"])
        self.assertEqual("ABSENT", verdict["claim"])
        self.assertNotIn("worker_pid", verdict)

    def test_a_live_worker_is_reported_as_running_with_its_pid(self) -> None:
        attempt, _ = self.start_worker(pid=4242)
        verdict = self.engine.inspect()
        self.assertEqual("RUNNING", verdict["claim"])
        self.assertEqual(4242, verdict["worker_pid"])
        self.assertEqual(attempt["attempt_id"], verdict["attempt_id"])

    def test_a_live_child_keeps_the_claim_running_even_when_the_worker_exited(self) -> None:
        attempt, _ = self.start_worker(pid=4242)
        child = self.identity(4343)
        self.processes[4343] = automation.ProbeResult("LIVE", child)
        self.engine.attach_child(attempt["attempt_id"], attempt["handoff_token"], child)
        self.processes.pop(4242)  # the wrapper is gone, the collector is not
        verdict = self.engine.inspect()
        self.assertEqual("RUNNING", verdict["claim"])
        self.assertEqual(4343, verdict["worker_pid"])

    def test_a_dead_owner_leaves_a_stale_claim_rather_than_a_running_one(self) -> None:
        self.start_worker(pid=4242, live=False)
        self.assertEqual("STALE", self.engine.inspect()["claim"])

    def test_an_unbound_handoff_is_unresolved_not_free(self) -> None:
        self.engine.initialize()
        self.engine.begin_attempt()  # claimed, no worker bound
        verdict = self.engine.inspect()
        self.assertEqual("UNRESOLVED", verdict["claim"])
        self.assertNotIn("worker_pid", verdict)

    def test_a_process_the_system_will_not_answer_for_is_unresolved_not_dead(self) -> None:
        self.start_worker(pid=4242, live=False)
        self.processes[4242] = automation.ProbeResult("UNKNOWN")
        self.assertEqual("UNRESOLVED", self.engine.inspect()["claim"])

    def test_a_recycled_pid_is_not_the_process_that_held_the_claim(self) -> None:
        self.start_worker(pid=4242, live=False)
        # Same number, different process: a later start time is a different identity.
        self.processes[4242] = automation.ProbeResult("LIVE", self.identity(4242, offset=99))
        self.assertEqual("STALE", self.engine.inspect()["claim"])

    def test_inspect_changes_nothing_on_disk(self) -> None:
        self.start_worker(pid=4242)

        def snapshot() -> dict[str, bytes]:
            return {
                str(path): path.read_bytes()
                for path in Path(self.temp.name).rglob("*")
                if path.is_file()
            }

        before = snapshot()
        first = self.engine.inspect()
        self.assertEqual(first, self.engine.inspect())
        self.assertEqual(before, snapshot())

    def test_not_due_is_still_reported_while_a_claim_is_held(self) -> None:
        attempt, _ = self.start_worker(pid=4242)
        self.engine.finish_attempt(
            attempt["attempt_id"], attempt["handoff_token"],
            outcome=automation.OUTCOME_COMPLETE, cadence_seconds=21600,
        )
        # The claim is released lazily, on the next attempt, so a finished run whose
        # process is somehow still alive is still reported as holding it. That is the
        # truth: the engine will not free a claim while its owner answers to being live.
        self.assertEqual("RUNNING", self.engine.inspect()["claim"])
        self.processes.pop(4242)
        verdict = self.engine.inspect()
        self.assertEqual(automation.STATUS_NOT_DUE, verdict["status"])
        self.assertEqual("STALE", verdict["claim"])

    def test_an_unreadable_claim_is_not_read_as_absence(self) -> None:
        self.start_worker(pid=4242)
        self.paths.claim.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(automation.AutomationStateError):
            self.engine.inspect()


if __name__ == "__main__":
    unittest.main()
