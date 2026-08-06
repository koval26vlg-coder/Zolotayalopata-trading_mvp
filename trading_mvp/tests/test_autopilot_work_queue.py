from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autopilot_work_queue import parse_git_status_lines, run_task  # noqa: E402


class AutopilotWorkQueueTests(unittest.TestCase):
    def test_code_baseline_manifest_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "src"
            source.mkdir()
            (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            output = root / "output"
            ledger = root / "ledger.jsonl"
            task = {
                "id": "baseline",
                "runner": "code_baseline_manifest",
                "max_runtime_sec": 30,
                "max_attempts": 1,
                "include": ["src/**/*.py"],
            }

            first = run_task(
                task,
                repo_root=root,
                output_dir=output,
                ledger_path=ledger,
            )
            second_ledger = root / "second-ledger.jsonl"
            second = run_task(
                task,
                repo_root=root,
                output_dir=output,
                ledger_path=second_ledger,
            )

            self.assertEqual(first["status"], "COMPLETED")
            self.assertEqual(first["result"]["file_count"], 1)
            self.assertEqual(
                first["result"]["content_hash"],
                second["result"]["content_hash"],
            )
            manifest = json.loads(
                Path(first["result"]["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["files"][0]["path"], "src/module.py")

    def test_completed_task_is_not_executed_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "value.txt").write_text("one\n", encoding="utf-8")
            output = root / "output"
            ledger = root / "ledger.jsonl"
            task = {
                "id": "baseline",
                "runner": "code_baseline_manifest",
                "max_runtime_sec": 30,
                "max_attempts": 1,
                "include": ["*.txt"],
            }

            run_task(task, repo_root=root, output_dir=output, ledger_path=ledger)
            with self.assertRaisesRegex(ValueError, "already completed"):
                run_task(task, repo_root=root, output_dir=output, ledger_path=ledger)

    def test_unknown_runner_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "unsupported fallback runner"):
                run_task(
                    {
                        "id": "unsafe",
                        "runner": "shell",
                        "max_runtime_sec": 30,
                        "max_attempts": 1,
                    },
                    repo_root=root,
                    output_dir=root / "output",
                    ledger_path=root / "ledger.jsonl",
                )

    def test_git_status_parser_classifies_code_and_artifacts(self) -> None:
        rows = parse_git_status_lines(
            [
                " M trading_mvp/src/module.py",
                "?? docs/agent-log/run.json",
                "?? exports/trading-mvp/raw.jsonl",
            ]
        )

        self.assertEqual(rows[0]["status"], " M")
        self.assertEqual(rows[0]["scope"], "code")
        self.assertEqual(rows[1]["scope"], "control_or_documentation")
        self.assertEqual(rows[2]["scope"], "data_artifact")

    def test_evidence_manifest_hashes_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence.json"
            evidence.write_text('{"verdict":"REJECT"}\n', encoding="utf-8")
            task = {
                "id": "evidence",
                "runner": "evidence_manifest",
                "max_runtime_sec": 30,
                "max_attempts": 1,
                "inputs": ["evidence.json"],
            }

            result = run_task(
                task,
                repo_root=root,
                output_dir=root / "output",
                ledger_path=root / "ledger.jsonl",
            )

            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["result"]["input_count"], 1)
            self.assertTrue(Path(result["result"]["manifest_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
