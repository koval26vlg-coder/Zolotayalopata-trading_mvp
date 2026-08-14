from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from global_market_writer_claim import (  # noqa: E402
    GlobalMarketWriterClaimError,
    attach_writer_pid,
    claim_global_market_writer,
    inspect_global_market_writer_claim,
    release_global_market_writer,
)


class GlobalMarketWriterClaimTests(unittest.TestCase):
    def test_pit_countdown_uses_shared_claim_without_mutating_sealed_wrapper(self) -> None:
        wrapper_path = (
            ROOT / "tools" / "start_pit_universe_snapshot_collect_visible.ps1"
        )
        self.assertEqual(
            hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
            "79cabe555ee7931294d570a453da03063db9fa0728297547124d5e75c8dec371",
        )
        launcher = (
            ROOT / "tools" / "start_approved_pit_segment_countdown_visible.ps1"
        ).read_text(encoding="utf-8-sig")
        for expected in (
            "active-market-data-writer-claim.json",
            "global_market_writer_claim.py",
            '"claim"',
            '"release"',
            "GLOBAL_MARKET_WRITER_CLAIM_EXISTS",
        ):
            self.assertIn(expected, launcher)

    def test_claim_is_atomic_and_second_writer_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "active-market-data-writer-claim.json"
            first = claim_global_market_writer(
                path,
                run_id="pit_n05",
                owner_pid=101,
                owner_kind="pit",
                plan_hash="a" * 64,
                output_namespace=Path(temp_dir) / "pit",
                ownership_token="1" * 32,
            )
            self.assertEqual(first["status"], "CLAIMED")

            with self.assertRaisesRegex(
                GlobalMarketWriterClaimError,
                "GLOBAL_MARKET_WRITER_CLAIM_EXISTS",
            ):
                claim_global_market_writer(
                    path,
                    run_id="dense_phase_01",
                    owner_pid=202,
                    owner_kind="dense_ws",
                    plan_hash="b" * 64,
                    output_namespace=Path(temp_dir) / "dense",
                    ownership_token="2" * 32,
                )

    def test_concurrent_processes_allow_exactly_one_writer_claim(self) -> None:
        helper = """
import json
import sys
import time
from pathlib import Path

source, ready_value, gate_value, claim_value, run_id, owner_pid, output = sys.argv[1:]
sys.path.insert(0, source)
from global_market_writer_claim import claim_global_market_writer

ready = Path(ready_value)
gate = Path(gate_value)
ready.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15.0
while not gate.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("parent did not release claim race")
    time.sleep(0.002)

payload = claim_global_market_writer(
    claim_value,
    run_id=run_id,
    owner_pid=int(owner_pid),
    owner_kind="concurrency_fixture",
    plan_hash="d" * 64,
    output_namespace=output,
)
print(json.dumps(payload))
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            gate = root / "release"
            processes: list[subprocess.Popen[str]] = []
            participant_count = 8
            try:
                for index in range(participant_count):
                    ready = root / f"ready-{index}"
                    processes.append(
                        subprocess.Popen(
                            [
                                sys.executable,
                                "-c",
                                helper,
                                str(SRC),
                                str(ready),
                                str(gate),
                                str(path),
                                f"race_{index}",
                                str(1_000 + index),
                                str(root / f"output-{index}"),
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                        )
                    )

                ready_deadline = time.monotonic() + 15.0
                ready_paths = [root / f"ready-{index}" for index in range(participant_count)]
                while not all(item.exists() for item in ready_paths):
                    if time.monotonic() >= ready_deadline:
                        self.fail("not all claim-race participants became ready")
                    time.sleep(0.01)
                gate.write_text("go", encoding="utf-8")

                results = [process.communicate(timeout=20.0) for process in processes]
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5.0)

            successes = [
                (process, stdout, stderr)
                for process, (stdout, stderr) in zip(processes, results, strict=True)
                if process.returncode == 0
            ]
            failures = [
                (process, stdout, stderr)
                for process, (stdout, stderr) in zip(processes, results, strict=True)
                if process.returncode != 0
            ]
            diagnostics = [
                {
                    "returncode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                }
                for process, stdout, stderr in successes + failures
            ]

            self.assertEqual(1, len(successes), diagnostics)
            self.assertEqual(participant_count - 1, len(failures), diagnostics)
            winner = json.loads(successes[0][1])
            persisted = inspect_global_market_writer_claim(path)
            self.assertIsNotNone(persisted)
            self.assertEqual(winner["run_id"], persisted["run_id"])
            self.assertEqual(winner["ownership_token"], persisted["ownership_token"])
            for _, _, stderr in failures:
                self.assertIn("GLOBAL_MARKET_WRITER_CLAIM_EXISTS", stderr)

    def test_only_exact_owner_can_attach_or_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            claim_global_market_writer(
                path,
                run_id="dense_phase_01",
                owner_pid=303,
                owner_kind="dense_ws",
                plan_hash="c" * 64,
                output_namespace=root / "dense",
                ownership_token="3" * 32,
            )
            with self.assertRaisesRegex(
                GlobalMarketWriterClaimError,
                "token mismatch",
            ):
                attach_writer_pid(
                    path,
                    run_id="dense_phase_01",
                    owner_pid=303,
                    ownership_token="4" * 32,
                    writer_pid=404,
                )

            attached = attach_writer_pid(
                path,
                run_id="dense_phase_01",
                owner_pid=303,
                ownership_token="3" * 32,
                writer_pid=404,
            )
            self.assertEqual(attached["writer_pid"], 404)
            archive = release_global_market_writer(
                path,
                run_id="dense_phase_01",
                owner_pid=303,
                ownership_token="3" * 32,
                final_status="READY_FOR_POSTPROCESS",
                archive_dir=root / "archive",
            )
            self.assertFalse(path.exists())
            self.assertTrue(archive.is_file())
            released = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual(released["status"], "RELEASED")
            self.assertEqual(released["final_status"], "READY_FOR_POSTPROCESS")
            self.assertIsNone(inspect_global_market_writer_claim(path))

    def test_stale_claim_is_never_auto_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "active-market-data-writer-claim.json"
            claim_global_market_writer(
                path,
                run_id="dead_owner",
                owner_pid=999_999,
                owner_kind="fixture",
                plan_hash=None,
                output_namespace=temp_dir,
                ownership_token="5" * 32,
            )
            with self.assertRaises(GlobalMarketWriterClaimError):
                claim_global_market_writer(
                    path,
                    run_id="replacement",
                    owner_pid=505,
                    owner_kind="fixture",
                    plan_hash=None,
                    output_namespace=temp_dir,
                    ownership_token="6" * 32,
                )
            self.assertEqual(
                inspect_global_market_writer_claim(path)["run_id"],
                "dead_owner",
            )


if __name__ == "__main__":
    unittest.main()
