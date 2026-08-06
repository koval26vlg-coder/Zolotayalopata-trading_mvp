from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "resolve_active_run.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "pwsh is required")
class ResolveActiveRunTests(unittest.TestCase):
    def _write_gate(self, root: Path, *, run_id: str, process_ids: list[int] | None = None) -> tuple[Path, Path]:
        gate = root / "active-run-gate.json"
        pointer = root / "current-run.json"
        common = {
            "project": "trading_mvp",
            "run_id": run_id,
            "status": "STOPPED_INCOMPLETE",
            "collector_pid": None,
            "monitor_pid": None,
            "process_ids": process_ids or [],
        }
        gate.write_text(
            json.dumps({"schema": "active_run_gate_v2", "gate_status": "STOPPED_INCOMPLETE", **common}),
            encoding="utf-8",
        )
        pointer.write_text(
            json.dumps({"schema": "active_run_pointer_v1", **common}),
            encoding="utf-8",
        )
        return gate, pointer

    def _run(self, gate: Path, pointer: Path, archive: Path, run_id: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-RunId",
                run_id,
                "-RejectIncomplete",
                "-Reason",
                "fixture rejection",
                "-GatePath",
                str(gate),
                "-PointerPath",
                str(pointer),
                "-ArchiveDir",
                str(archive),
                "-Json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_rejects_and_archives_incomplete_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gate, pointer = self._write_gate(root, run_id="fixture_run")
            archive = root / "archive"

            completed = self._run(gate, pointer, archive, "fixture_run")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result["ok"])
            self.assertEqual(result["rejected_run_id"], "fixture_run")
            active = json.loads(gate.read_text(encoding="utf-8-sig"))
            current = json.loads(pointer.read_text(encoding="utf-8-sig"))
            self.assertEqual(active["status"], "READY_FOR_POSTPROCESS")
            self.assertFalse(active["replay_allowed"])
            self.assertEqual(current["run_id"], active["run_id"])
            archived_gate = json.loads(Path(result["archived_gate_path"]).read_text(encoding="utf-8-sig"))
            self.assertEqual(archived_gate["status"], "REJECTED_INCOMPLETE")
            self.assertEqual(archived_gate["original_status"], "STOPPED_INCOMPLETE")

    def test_run_id_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gate, pointer = self._write_gate(root, run_id="fixture_run")
            completed = self._run(gate, pointer, root / "archive", "wrong_run")
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("run_id mismatch", completed.stderr)


if __name__ == "__main__":
    unittest.main()
