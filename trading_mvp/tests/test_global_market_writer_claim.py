from __future__ import annotations

import json
import hashlib
import sys
import tempfile
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
