from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import paper_observer_monitor as monitor  # noqa: E402
import paper_observer_runtime as runtime  # noqa: E402
from test_paper_observer_runtime import _plan, _sample  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


class PaperObserverMonitorTests(unittest.TestCase):
    def test_not_started_snapshot_has_eta_and_no_network_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, plan = _plan(Path(tmp), [_sample(1), _sample(2)])
            snapshot = monitor.build_monitor_snapshot(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual(snapshot["status"], "NOT_STARTED")
            self.assertEqual(snapshot["eta_sec"], 10)
            self.assertEqual(snapshot["completed_samples"], 0)
            self.assertFalse(snapshot["network_access"])
            self.assertFalse(snapshot["live_orders"])

    def test_partial_snapshot_uses_audit_as_progress_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2), _sample(3)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                max_new_samples=1,
            )
            snapshot = monitor.build_monitor_snapshot(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual(snapshot["completed_samples"], 1)
            self.assertEqual(snapshot["remaining_samples"], 2)
            self.assertEqual(snapshot["eta_sec"], 10)
            self.assertEqual(snapshot["accepted_samples"], 1)
            self.assertIsNotNone(snapshot["last_write_utc"]["audit"])

    def test_final_snapshot_reports_blocked_and_incident_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            degraded = _sample(1)
            degraded["mexc"]["transport_ok"] = False
            plan_path, plan = _plan(root, [degraded, _sample(2)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            snapshot = monitor.build_monitor_snapshot(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertTrue(snapshot["final"])
            self.assertEqual(snapshot["eta_sec"], 0)
            self.assertEqual(snapshot["blocked_samples"], 1)
            self.assertEqual(snapshot["incident_state"]["current_state"], "HEALTHY")
            self.assertEqual(snapshot["incident_state"]["recovery_count"], 1)
            self.assertIn("progress=2/2", monitor.format_monitor_line(snapshot))

    def test_watch_returns_immediately_for_final_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            lines: list[str] = []
            snapshot = monitor.watch_monitor(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                emit=lines.append,
                sleep_fn=lambda _seconds: self.fail("final monitor must not sleep"),
            )
            self.assertTrue(snapshot["final"])
            self.assertEqual(len(lines), 1)

    def test_visible_wrapper_does_not_launch_background_process(self) -> None:
        source = (
            REPO_ROOT / "tools" / "monitor_paper_observer_fixture_visible.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertNotIn("Start-Process", source)
        self.assertIn("--watch", source)
        self.assertIn("--max-runtime-sec", source)


if __name__ == "__main__":
    unittest.main()
