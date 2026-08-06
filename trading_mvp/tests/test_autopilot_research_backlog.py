from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autopilot_research_backlog import (  # noqa: E402
    claim_task,
    complete_task,
    ensure_backlog,
    next_task,
)


def _write_backlog(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_autopilot_research_backlog_v1",
                "tasks": [
                    {
                        "id": "first",
                        "status": "PENDING",
                        "max_runtime_sec": 300,
                        "output_path": str(path.parent / "first.json"),
                    },
                    {
                        "id": "second",
                        "status": "PENDING",
                        "max_runtime_sec": 600,
                        "output_path": str(path.parent / "second.json"),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_catalog(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_autopilot_research_catalog_v1",
                "tasks": [
                    {
                        "id": "refill-one",
                        "max_runtime_sec": 300,
                        "output_path": str(path.parent / "refill-one.json"),
                        "objective": "bounded fixture task",
                        "allowed_inputs": ["trading_mvp/src"],
                    },
                    {
                        "id": "refill-two",
                        "max_runtime_sec": 600,
                        "output_path": str(path.parent / "refill-two.json"),
                        "objective": "bounded static audit",
                        "allowed_inputs": ["trading_mvp/tests"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


class AutopilotResearchBacklogTests(unittest.TestCase):
    def test_claim_and_complete_are_atomic_and_non_repeating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backlog = root / "backlog.json"
            _write_backlog(backlog)

            self.assertEqual(next_task(backlog)["task"]["id"], "first")
            claimed = claim_task(backlog, "first", owner="test")
            self.assertEqual(claimed["status"], "RUNNING")
            self.assertEqual(next_task(backlog)["status"], "IN_PROGRESS")

            artifact = root / "first.json"
            artifact.write_text('{"result":"ok"}\n', encoding="utf-8")
            completed = complete_task(backlog, "first", artifact)
            self.assertEqual(completed["status"], "COMPLETED")
            self.assertEqual(next_task(backlog)["task"]["id"], "second")

            with self.assertRaisesRegex(ValueError, "not RUNNING"):
                complete_task(backlog, "first", artifact)

    def test_runtime_above_thirty_minutes_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backlog = Path(temp_dir) / "backlog.json"
            _write_backlog(backlog)
            payload = json.loads(backlog.read_text(encoding="utf-8"))
            payload["tasks"][0]["max_runtime_sec"] = 1_801
            backlog.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "max_runtime_sec"):
                next_task(backlog)

    def test_next_auto_refills_exact_hash_bound_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "catalog.json"
            _write_catalog(catalog)
            backlog = root / "backlog.json"
            backlog.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_autopilot_research_backlog_v1",
                        "auto_refill": True,
                        "catalog_path": str(catalog),
                        "catalog_file_sha256": __import__("hashlib").sha256(
                            catalog.read_bytes()
                        ).hexdigest(),
                        "tasks": [],
                    }
                ),
                encoding="utf-8",
            )

            result = next_task(backlog)

            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["task"]["id"], "refill-one")
            persisted = json.loads(backlog.read_text(encoding="utf-8"))
            self.assertEqual([row["status"] for row in persisted["tasks"]], ["PENDING", "PENDING"])
            self.assertEqual(persisted["refill_count"], 1)

    def test_auto_refill_never_repeats_completed_catalog_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "catalog.json"
            _write_catalog(catalog)
            backlog = root / "backlog.json"
            backlog.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_autopilot_research_backlog_v1",
                        "auto_refill": True,
                        "catalog_path": str(catalog),
                        "catalog_file_sha256": __import__("hashlib").sha256(
                            catalog.read_bytes()
                        ).hexdigest(),
                        "tasks": [
                            {
                                "id": "refill-one",
                                "status": "COMPLETED",
                                "max_runtime_sec": 300,
                                "output_path": str(root / "refill-one.json"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            ensured = ensure_backlog(backlog)

            self.assertEqual(ensured["status"], "REFILLED")
            self.assertEqual(ensured["added_task_ids"], ["refill-two"])
            persisted = json.loads(backlog.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["id"] for row in persisted["tasks"]],
                ["refill-one", "refill-two"],
            )

    def test_catalog_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "catalog.json"
            _write_catalog(catalog)
            backlog = root / "backlog.json"
            backlog.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_autopilot_research_backlog_v1",
                        "auto_refill": True,
                        "catalog_path": str(catalog),
                        "catalog_file_sha256": "0" * 64,
                        "tasks": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "catalog file hash mismatch"):
                next_task(backlog)


if __name__ == "__main__":
    unittest.main()
