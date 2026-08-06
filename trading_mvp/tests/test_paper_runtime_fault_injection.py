from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import paper_observer_runtime as runtime  # noqa: E402
from test_paper_observer_runtime import _plan, _sample  # noqa: E402


class PaperRuntimeFaultInjectionTests(unittest.TestCase):
    def test_bounded_interruption_resumes_without_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2), _sample(3)])
            partial = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                max_new_samples=1,
            )
            self.assertEqual(partial["stop_reason"], "bounded_interruption")
            resumed = runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertTrue(resumed["final"])
            self.assertEqual(len(runtime._read_jsonl(root / "audit.jsonl")), 3)
            self.assertEqual(len(runtime._read_jsonl(root / "accepted.jsonl")), 3)

    def test_duplicate_fixture_sequence_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(1)])
            with self.assertRaisesRegex(ValueError, "contiguous"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                )
            self.assertFalse((root / "audit.jsonl").exists())
            self.assertFalse((root / "accepted.jsonl").exists())

    def test_existing_writer_lock_fails_closed_without_manifest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1)])
            lock = (root / "manifest.json").with_suffix(".json.writer.lock")
            lock.write_text(
                json.dumps(
                    {
                        "schema": "fault-injection",
                        "run_id": plan["run_id"],
                        "lock_id": "held",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "writer lock is already held"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                )
            self.assertFalse((root / "manifest.json").exists())

    def test_truncated_audit_blocks_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1), _sample(2)])
            runtime.run_fixture_observer_segment(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                max_new_samples=1,
            )
            with (root / "audit.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"truncated":')
            with self.assertRaisesRegex(ValueError, "invalid JSONL"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                )
            self.assertEqual(
                runtime._read_json(root / "manifest.json")["status"],
                "STOPPED_INCOMPLETE",
            )

    def test_disk_write_failure_records_integrity_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1)])
            with patch.object(
                runtime,
                "_append_jsonl",
                side_effect=OSError(28, "No space left on device"),
            ):
                with self.assertRaisesRegex(OSError, "No space left"):
                    runtime.run_fixture_observer_segment(
                        plan_path=plan_path,
                        expected_plan_hash=plan["plan_hash"],
                    )
            manifest = runtime._read_json(root / "manifest.json")
            self.assertEqual(manifest["stop_reason"], "validation_or_integrity_failure")
            self.assertIn("No space left", manifest["errors"][0])
            self.assertFalse((root / "accepted.jsonl").exists())

    def test_fixture_and_plan_hash_drift_fail_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _plan(root, [_sample(1)])
            fixture_path = Path(plan["fixture"]["path"])
            with fixture_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_sample(2)) + "\n")
            with self.assertRaisesRegex(ValueError, "input hash mismatch"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash"],
                )
            with self.assertRaisesRegex(ValueError, "expected hash"):
                runtime.run_fixture_observer_segment(
                    plan_path=plan_path,
                    expected_plan_hash="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
