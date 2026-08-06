from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import _latest_ws_input  # noqa: E402


def _touch(path: Path, mtime_offset_sec: float, content: str = "{}") -> None:
    path.write_text(content, encoding="utf-8")
    stamp = time.time() + mtime_offset_sec
    os.utime(path, (stamp, stamp))


class LatestWsInputGuardTests(unittest.TestCase):
    def test_picks_fresh_completed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            _touch(raw_dir / "ws_mexc_1.jsonl", -100, "x\n")
            _touch(raw_dir / "ws_collect_1.json", -50, json.dumps({"completed": True}))
            chosen = _latest_ws_input(raw_dir)
        self.assertEqual(chosen.name, "ws_collect_1.json")

    def test_refuses_when_raw_newer_than_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            _touch(raw_dir / "ws_collect_old.json", -3600, json.dumps({"completed": True}))
            _touch(raw_dir / "ws_mexc_new.jsonl", 0, "x\n")
            with self.assertRaisesRegex(RuntimeError, "partial run"):
                _latest_ws_input(raw_dir)

    def test_refuses_incomplete_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            _touch(raw_dir / "ws_collect_1.json", 0, json.dumps({"completed": False}))
            with self.assertRaisesRegex(RuntimeError, "completed=false"):
                _latest_ws_input(raw_dir)

    def test_unreadable_manifest_behaves_as_before(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            _touch(raw_dir / "ws_collect_1.json", 0, "not-json")
            chosen = _latest_ws_input(raw_dir)
        self.assertEqual(chosen.name, "ws_collect_1.json")

    def test_raw_fallback_and_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            _touch(raw_dir / "ws_mexc_1.jsonl", 0, "x\n")
            chosen = _latest_ws_input(raw_dir)
            self.assertEqual(chosen.name, "ws_mexc_1.jsonl")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                _latest_ws_input(Path(tmp))


if __name__ == "__main__":
    unittest.main()
