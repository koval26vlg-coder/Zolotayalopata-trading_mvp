from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import global_market_writer_claim as writer_claim_module  # noqa: E402
from global_market_writer_claim import (  # noqa: E402
    GlobalMarketWriterClaimError,
    attach_writer_pid,
    claim_global_market_writer,
    inspect_global_market_writer_claim,
    release_global_market_writer,
)


class GlobalMarketWriterClaimTests(unittest.TestCase):
    def test_worker_handoff_is_bound_to_live_claim_and_consumed_once(self) -> None:
        consume = getattr(writer_claim_module, "consume_worker_handoff_receipt", None)
        self.assertTrue(callable(consume), "worker handoff consume API is missing")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            claim_path = root / "active-market-data-writer-claim.json"
            receipt_path = root / "python-worker-handoffs" / "attempt-a.json"
            consumed_dir = receipt_path.parent / "consumed"
            claim = claim_global_market_writer(
                claim_path,
                run_id="attempt-a",
                owner_pid=os.getpid(),
                owner_kind="fixture_worker",
                plan_hash="a" * 64,
                output_namespace=root / "output",
                ownership_token="1" * 32,
            )
            receipt = {
                "schema": "trading_mvp_market_data_worker_handoff_v1",
                "status": "ISSUED",
                "project": "trading_mvp",
                "automation_id": "fixture-automation",
                "attempt_id": "attempt-a",
                "plan_hash": "a" * 64,
                "wrapper_pid": os.getpid(),
                "wrapper_process_started_at_utc": claim["owner_process_started_at_utc"],
                "handoff_token_sha256": hashlib.sha256(b"2" * 32).hexdigest(),
                "claim_run_id": "attempt-a",
                "claim_owner_kind": "fixture_worker",
                "claim_owner_pid": os.getpid(),
                "claim_owner_process_started_at_utc": claim["owner_process_started_at_utc"],
                "claim_ownership_token_sha256": hashlib.sha256(b"1" * 32).hexdigest(),
                "claim_output_namespace": str((root / "output").resolve()),
                "claim_must_exist": True,
                "issued_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            receipt_path.parent.mkdir(parents=True)
            original = (json.dumps(receipt, indent=2) + "\n").encode("utf-8")
            receipt_path.write_bytes(original)

            result = consume(
                claim_path,
                receipt_path=receipt_path,
                consumed_dir=consumed_dir,
                handoff_token="2" * 32,
                attempt_id="attempt-a",
                plan_hash="a" * 64,
                automation_id="fixture-automation",
            )

            self.assertEqual("CONSUMED", result["status"])
            self.assertFalse(receipt_path.exists())
            archived = list(consumed_dir.glob("*.json"))
            self.assertEqual(1, len(archived))
            self.assertEqual(original, archived[0].read_bytes())
            self.assertEqual(claim, inspect_global_market_writer_claim(claim_path))
            with self.assertRaises(GlobalMarketWriterClaimError):
                consume(
                    claim_path,
                    receipt_path=receipt_path,
                    consumed_dir=consumed_dir,
                    handoff_token="2" * 32,
                    attempt_id="attempt-a",
                    plan_hash="a" * 64,
                    automation_id="fixture-automation",
                )

    def test_invalid_worker_handoff_preserves_receipt_claim_and_archive(self) -> None:
        consume = getattr(writer_claim_module, "consume_worker_handoff_receipt", None)
        self.assertTrue(callable(consume), "worker handoff consume API is missing")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            claim_path = root / "active-market-data-writer-claim.json"
            receipt_path = root / "python-worker-handoffs" / "attempt-b.json"
            consumed_dir = receipt_path.parent / "consumed"
            claim = claim_global_market_writer(
                claim_path,
                run_id="attempt-b",
                owner_pid=os.getpid(),
                owner_kind="fixture_worker",
                plan_hash="b" * 64,
                output_namespace=root / "output",
                ownership_token="3" * 32,
            )
            receipt = {
                "schema": "trading_mvp_market_data_worker_handoff_v1",
                "status": "ISSUED",
                "project": "trading_mvp",
                "automation_id": "fixture-automation",
                "attempt_id": "attempt-b",
                "plan_hash": "b" * 64,
                "wrapper_pid": os.getpid(),
                "wrapper_process_started_at_utc": claim["owner_process_started_at_utc"],
                "handoff_token_sha256": hashlib.sha256(b"4" * 32).hexdigest(),
                "claim_run_id": "attempt-b",
                "claim_owner_kind": "fixture_worker",
                "claim_owner_pid": os.getpid(),
                "claim_owner_process_started_at_utc": claim["owner_process_started_at_utc"],
                "claim_ownership_token_sha256": hashlib.sha256(b"3" * 32).hexdigest(),
                "claim_output_namespace": str((root / "output").resolve()),
                "claim_must_exist": True,
                "issued_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            receipt_before = receipt_path.read_bytes()
            claim_before = claim_path.read_bytes()

            with self.assertRaisesRegex(GlobalMarketWriterClaimError, "handoff token"):
                consume(
                    claim_path,
                    receipt_path=receipt_path,
                    consumed_dir=consumed_dir,
                    handoff_token="5" * 32,
                    attempt_id="attempt-b",
                    plan_hash="b" * 64,
                    automation_id="fixture-automation",
                )

            self.assertEqual(receipt_before, receipt_path.read_bytes())
            self.assertEqual(claim_before, claim_path.read_bytes())
            self.assertFalse(consumed_dir.exists())

    def test_spot_worker_handoff_binds_the_future_claim_token_and_namespace(self) -> None:
        consume = writer_claim_module.consume_worker_handoff_receipt
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            claim_path = root / "active-market-data-writer-claim.json"
            receipt_path = root / "python-worker-handoffs" / "spot-tick-a.json"
            consumed_dir = receipt_path.parent / "consumed"
            output = (root / "ticks" / "spot-tick-a").resolve()
            wrapper_started = writer_claim_module._process_started_at_utc(os.getpid())
            self.assertIsNotNone(wrapper_started)
            receipt = {
                "schema": "trading_mvp_market_data_worker_handoff_v1",
                "status": "ISSUED",
                "project": "trading_mvp",
                "automation_id": "spot-fixture",
                "attempt_id": "spot-tick-a",
                "plan_hash": "c" * 64,
                "wrapper_pid": os.getpid(),
                "wrapper_process_started_at_utc": wrapper_started,
                "handoff_token_sha256": hashlib.sha256(b"6" * 32).hexdigest(),
                "claim_run_id": "spot-plan__spot-tick-a",
                "claim_owner_kind": "spot_fixture_worker",
                "claim_owner_pid": None,
                "claim_owner_process_started_at_utc": None,
                "claim_ownership_token_sha256": hashlib.sha256(b"7" * 32).hexdigest(),
                "claim_output_namespace": str(output),
                "claim_must_exist": False,
                "issued_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            result = consume(
                claim_path,
                receipt_path=receipt_path,
                consumed_dir=consumed_dir,
                handoff_token="6" * 32,
                attempt_id="spot-tick-a",
                plan_hash="c" * 64,
                automation_id="spot-fixture",
            )
            self.assertFalse(result["claim_must_exist"])
            self.assertFalse(claim_path.exists())

            claim = claim_global_market_writer(
                claim_path,
                run_id=result["claim_run_id"],
                owner_pid=os.getpid(),
                owner_kind=result["claim_owner_kind"],
                plan_hash="c" * 64,
                output_namespace=result["claim_output_namespace"],
                ownership_token="7" * 32,
            )
            self.assertEqual("7" * 32, claim["ownership_token"])
            self.assertEqual(str(output), claim["output_namespace"])

    def recover_stale_claim(
        self,
        path: Path,
        *,
        archive_dir: Path | None = None,
    ) -> dict[str, object]:
        recovery = getattr(
            writer_claim_module,
            "recover_stale_global_market_writer_claim",
            None,
        )
        self.assertTrue(
            callable(recovery),
            "recover-stale global writer claim API is missing",
        )
        return recovery(path, archive_dir=archive_dir)

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
                owner_pid=os.getpid(),
                owner_kind="pit",
                plan_hash="a" * 64,
                output_namespace=Path(temp_dir) / "pit",
                ownership_token="1" * 32,
            )
            self.assertEqual(first["status"], "CLAIMED")
            self.assertIn("owner_process_started_at_utc", first)
            self.assertIsNotNone(first["owner_process_started_at_utc"])
            datetime.fromisoformat(first["owner_process_started_at_utc"].replace("Z", "+00:00"))

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

    def test_claim_transactions_fail_closed_while_interprocess_lock_is_held(self) -> None:
        holder_source = r"""
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import global_market_writer_claim as claims

claim_path = Path(sys.argv[2])
ready_path = Path(sys.argv[3])
with claims._claim_transaction_lock(claim_path, timeout_seconds=5.0):
    ready_path.write_text("ready", encoding="utf-8")
    time.sleep(2.0)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            ready = root / "holder-ready"
            claim_global_market_writer(
                path,
                run_id="transaction_owner",
                owner_pid=os.getpid(),
                owner_kind="fixture",
                plan_hash="d" * 64,
                output_namespace=root / "output",
                ownership_token="a" * 32,
            )
            original = path.read_bytes()
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    holder_source,
                    str(SRC),
                    str(path),
                    str(ready),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 10.0
                while not ready.exists() and holder.poll() is None:
                    if time.monotonic() >= deadline:
                        self.fail("transaction-lock holder did not become ready")
                    time.sleep(0.01)
                self.assertIsNone(holder.poll())

                blocked_operations = (
                    lambda: attach_writer_pid(
                        path,
                        run_id="transaction_owner",
                        owner_pid=os.getpid(),
                        ownership_token="a" * 32,
                        writer_pid=os.getpid(),
                        lock_timeout_seconds=0.05,
                    ),
                    lambda: release_global_market_writer(
                        path,
                        run_id="transaction_owner",
                        owner_pid=os.getpid(),
                        ownership_token="a" * 32,
                        final_status="READY_FOR_POSTPROCESS",
                        archive_dir=root / "archive",
                        lock_timeout_seconds=0.05,
                    ),
                    lambda: writer_claim_module.recover_stale_global_market_writer_claim(
                        path,
                        archive_dir=root / "archive",
                        lock_timeout_seconds=0.05,
                    ),
                )
                for operation in blocked_operations:
                    with self.assertRaisesRegex(
                        GlobalMarketWriterClaimError,
                        "transaction lock",
                    ):
                        operation()
                    self.assertEqual(original, path.read_bytes())
                    self.assertFalse((root / "archive").exists())
            finally:
                holder.wait(timeout=10)
                if holder.returncode != 0:
                    stdout, stderr = holder.communicate()
                    self.fail(f"holder failed: {stdout}\n{stderr}")

            attached = attach_writer_pid(
                path,
                run_id="transaction_owner",
                owner_pid=os.getpid(),
                ownership_token="a" * 32,
                writer_pid=os.getpid(),
                lock_timeout_seconds=1.0,
            )
            self.assertEqual(os.getpid(), attached["writer_pid"])

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

    def test_atomic_claim_records_writer_and_release_validates_expected_plan_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            claim = claim_global_market_writer(
                path,
                run_id="exact_release_identity",
                owner_pid=os.getpid(),
                owner_kind="fixture",
                plan_hash="b" * 64,
                output_namespace=root / "output",
                ownership_token="c" * 32,
                writer_pid=os.getpid(),
            )
            self.assertEqual(os.getpid(), claim["writer_pid"])

            with self.assertRaisesRegex(
                GlobalMarketWriterClaimError,
                "plan_hash mismatch",
            ):
                release_global_market_writer(
                    path,
                    run_id="exact_release_identity",
                    owner_pid=os.getpid(),
                    ownership_token="c" * 32,
                    final_status="COMPLETE",
                    archive_dir=root / "archive",
                    expected_plan_hash="f" * 64,
                    expected_owner_process_started_at_utc=claim[
                        "owner_process_started_at_utc"
                    ],
                )
            self.assertEqual("b" * 64, inspect_global_market_writer_claim(path)["plan_hash"])

    def test_release_moves_claim_before_best_effort_metadata_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            archive_dir = root / "archive"
            claim_global_market_writer(
                path,
                run_id="release_interrupted",
                owner_pid=701,
                owner_kind="fixture",
                plan_hash=None,
                output_namespace=root / "output",
                ownership_token="7" * 32,
            )
            rewrite_observation: dict[str, object] = {}

            def fail_released_metadata_rewrite(
                rewrite_path: Path,
                payload: object,
            ) -> None:
                rewrite_observation["path"] = Path(rewrite_path)
                rewrite_observation["payload"] = payload
                rewrite_observation["active_exists"] = path.exists()
                raise OSError("simulated post-move metadata interruption")

            with mock.patch.object(
                writer_claim_module,
                "_write_json_atomic",
                side_effect=fail_released_metadata_rewrite,
            ):
                archive = None
                try:
                    archive = release_global_market_writer(
                        path,
                        run_id="release_interrupted",
                        owner_pid=701,
                        ownership_token="7" * 32,
                        final_status="STOPPED_INCOMPLETE",
                        archive_dir=archive_dir,
                    )
                except OSError:
                    pass

            self.assertFalse(path.exists())
            archived_paths = list(archive_dir.glob("*.json"))
            self.assertEqual(1, len(archived_paths))
            archive = archive or archived_paths[0]
            self.assertEqual(archive, rewrite_observation["path"])
            self.assertFalse(rewrite_observation["active_exists"])
            self.assertEqual(
                "RELEASED",
                rewrite_observation["payload"]["status"],
            )
            archived_claim = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual("CLAIMED", archived_claim["status"])
            self.assertEqual(701, archived_claim["owner_pid"])

    def test_release_metadata_rewrite_preserves_substituted_active_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            claim_global_market_writer(
                path,
                run_id="release_original",
                owner_pid=801,
                owner_kind="fixture",
                plan_hash=None,
                output_namespace=root / "original-output",
                ownership_token="8" * 32,
            )
            substitute = {
                "schema": writer_claim_module.CLAIM_SCHEMA,
                "project": "trading_mvp",
                "status": "CLAIMED",
                "run_id": "substituted_claim",
                "owner_pid": 802,
                "ownership_token": "9" * 32,
            }
            real_write_json_atomic = writer_claim_module._write_json_atomic

            def substitute_before_rewrite(
                rewrite_path: Path,
                payload: object,
            ) -> None:
                path.write_text(
                    json.dumps(substitute, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                real_write_json_atomic(Path(rewrite_path), payload)

            with mock.patch.object(
                writer_claim_module,
                "_write_json_atomic",
                side_effect=substitute_before_rewrite,
            ):
                archive = release_global_market_writer(
                    path,
                    run_id="release_original",
                    owner_pid=801,
                    ownership_token="8" * 32,
                    final_status="READY_FOR_POSTPROCESS",
                    archive_dir=root / "archive",
                )

            self.assertTrue(path.is_file())
            active_claim = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("substituted_claim", active_claim["run_id"])
            released_claim = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual("release_original", released_claim["run_id"])
            self.assertEqual("RELEASED", released_claim["status"])

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

    def test_recover_stale_absent_claim_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            archive_dir = root / "archive"

            result = self.recover_stale_claim(path, archive_dir=archive_dir)

            self.assertEqual("ABSENT", result["status"])
            self.assertFalse(result["recovered"])
            self.assertEqual("claim_absent", result["reason"])
            self.assertFalse(archive_dir.exists())

    def test_recover_stale_preserves_live_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            claim = claim_global_market_writer(
                path,
                run_id="live_exact",
                owner_pid=os.getpid(),
                owner_kind="fixture",
                plan_hash="a" * 64,
                output_namespace=root / "output",
                ownership_token="a" * 32,
            )
            self.assertIsNotNone(claim["owner_process_started_at_utc"])
            original_bytes = path.read_bytes()

            result = self.recover_stale_claim(path, archive_dir=root / "archive")

            self.assertEqual("LIVE_PRESERVED", result["status"])
            self.assertEqual("owner_process_live_exact_identity", result["reason"])
            self.assertFalse(result["recovered"])
            self.assertEqual(original_bytes, path.read_bytes())
            self.assertFalse((root / "archive").exists())

    def test_recover_stale_preserves_live_missing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            claim = claim_global_market_writer(
                path,
                run_id="live_legacy",
                owner_pid=os.getpid(),
                owner_kind="fixture",
                plan_hash="b" * 64,
                output_namespace=root / "output",
                ownership_token="b" * 32,
            )
            claim.pop("owner_process_started_at_utc")
            path.write_text(
                json.dumps(claim, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            original_bytes = path.read_bytes()

            result = self.recover_stale_claim(path, archive_dir=root / "archive")

            self.assertEqual("LIVE_PRESERVED", result["status"])
            self.assertEqual("owner_process_live_missing_identity", result["reason"])
            self.assertFalse(result["recovered"])
            self.assertEqual(original_bytes, path.read_bytes())
            self.assertFalse((root / "archive").exists())

    def test_recover_stale_archives_dead_and_reused_claimed_evidence(self) -> None:
        cases = (
            ("dead_owner", 2_147_483_647, None, "owner_process_dead"),
            (
                "reused_owner_pid",
                os.getpid(),
                "2000-01-01T00:00:00+00:00",
                "owner_process_identity_mismatch",
            ),
        )
        for run_id, owner_pid, started_at, expected_reason in cases:
            with self.subTest(run_id=run_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                path = root / "active-market-data-writer-claim.json"
                archive_dir = root / "archive"
                claim_global_market_writer(
                    path,
                    run_id=run_id,
                    owner_pid=owner_pid,
                    owner_kind="fixture",
                    plan_hash="c" * 64,
                    output_namespace=root / "output",
                    owner_process_started_at_utc=started_at,
                    ownership_token="c" * 32,
                )
                original_bytes = path.read_bytes()
                original_sha256 = hashlib.sha256(original_bytes).hexdigest()

                result = self.recover_stale_claim(path, archive_dir=archive_dir)

                self.assertEqual("STALE_RECOVERED", result["status"])
                self.assertEqual(expected_reason, result["reason"])
                self.assertTrue(result["recovered"])
                self.assertEqual(original_sha256, result["claim_sha256"])
                archive_path = Path(result["archive_path"])
                self.assertFalse(path.exists())
                self.assertTrue(archive_path.is_file())
                self.assertEqual(original_bytes, archive_path.read_bytes())
                archived_claim = json.loads(archive_path.read_text(encoding="utf-8"))
                self.assertEqual("CLAIMED", archived_claim["status"])
                self.assertEqual(run_id, archived_claim["run_id"])

    def test_recover_stale_blocks_corrupt_schema_pid_and_start_identity(self) -> None:
        valid = {
            "schema": writer_claim_module.CLAIM_SCHEMA,
            "project": "trading_mvp",
            "status": "CLAIMED",
            "run_id": "validation_fixture",
            "owner_pid": os.getpid(),
            "owner_process_started_at_utc": "2000-01-01T00:00:00+00:00",
            "ownership_token": "d" * 32,
            "plan_hash": "e" * 64,
            "owner_kind": "fixture",
            "output_namespace": str(Path.cwd().resolve()),
            "claimed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        cases: tuple[tuple[str, bytes], ...] = (
            ("json", b"not-json\n"),
            (
                "schema",
                (json.dumps({**valid, "schema": "wrong"}) + "\n").encode("utf-8"),
            ),
            (
                "project",
                (json.dumps({**valid, "project": "wrong"}) + "\n").encode("utf-8"),
            ),
            (
                "status",
                (json.dumps({**valid, "status": "RELEASED"}) + "\n").encode("utf-8"),
            ),
            (
                "run_id",
                (json.dumps({**valid, "run_id": "unsafe run/id"}) + "\n").encode("utf-8"),
            ),
            (
                "pid",
                (json.dumps({**valid, "owner_pid": "not-a-pid"}) + "\n").encode(
                    "utf-8"
                ),
            ),
            (
                "start",
                (
                    json.dumps(
                        {**valid, "owner_process_started_at_utc": "not-a-time"}
                    )
                    + "\n"
                ).encode("utf-8"),
            ),
            (
                "missing_token",
                (
                    json.dumps({key: value for key, value in valid.items() if key != "ownership_token"})
                    + "\n"
                ).encode("utf-8"),
            ),
            (
                "token",
                (json.dumps({**valid, "ownership_token": "D" * 32}) + "\n").encode("utf-8"),
            ),
            (
                "missing_plan_hash",
                (
                    json.dumps({key: value for key, value in valid.items() if key != "plan_hash"})
                    + "\n"
                ).encode("utf-8"),
            ),
            (
                "plan_hash",
                (json.dumps({**valid, "plan_hash": "not-a-sha256"}) + "\n").encode("utf-8"),
            ),
            (
                "claimed_at",
                (json.dumps({**valid, "claimed_at_utc": "2026-08-20T00:00:00"}) + "\n").encode("utf-8"),
            ),
            (
                "owner_kind",
                (json.dumps({**valid, "owner_kind": ""}) + "\n").encode("utf-8"),
            ),
            (
                "output_namespace",
                (json.dumps({**valid, "output_namespace": ""}) + "\n").encode("utf-8"),
            ),
        )
        for label, raw_claim in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                path = root / "active-market-data-writer-claim.json"
                archive_dir = root / "archive"
                path.write_bytes(raw_claim)

                result = self.recover_stale_claim(path, archive_dir=archive_dir)

                self.assertEqual("BLOCKED", result["status"])
                self.assertEqual("claim_unreadable_or_invalid", result["reason"])
                self.assertFalse(result["recovered"])
                self.assertEqual(raw_claim, path.read_bytes())
                self.assertFalse(archive_dir.exists())

    def test_recover_stale_blocks_claim_changed_between_double_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            archive_dir = root / "archive"
            claim_global_market_writer(
                path,
                run_id="stale_before_change",
                owner_pid=2_147_483_647,
                owner_kind="fixture",
                plan_hash="f" * 64,
                output_namespace=root / "output",
                ownership_token="e" * 32,
            )
            substituted_claim = {
                "schema": writer_claim_module.CLAIM_SCHEMA,
                "project": "trading_mvp",
                "status": "CLAIMED",
                "run_id": "substituted_during_recovery",
                "owner_pid": os.getpid(),
                "owner_process_started_at_utc": None,
                "ownership_token": "f" * 32,
            }
            substituted_bytes = (
                json.dumps(substituted_claim, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            real_read_bytes = Path.read_bytes
            target_reads = 0

            def substitute_on_second_read(candidate: Path) -> bytes:
                nonlocal target_reads
                if candidate.resolve() == path.resolve():
                    target_reads += 1
                    if target_reads == 2:
                        path.write_bytes(substituted_bytes)
                return real_read_bytes(candidate)

            with mock.patch.object(Path, "read_bytes", new=substitute_on_second_read):
                result = self.recover_stale_claim(path, archive_dir=archive_dir)

            self.assertGreaterEqual(target_reads, 2)
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual("claim_changed_before_archive", result["reason"])
            self.assertFalse(result["recovered"])
            self.assertEqual(substituted_bytes, path.read_bytes())
            self.assertFalse(archive_dir.exists())

    def test_recover_stale_cli_emits_machine_readable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "active-market-data-writer-claim.json"
            archive_dir = root / "archive"
            claim_global_market_writer(
                path,
                run_id="cli_dead_owner",
                owner_pid=2_147_483_647,
                owner_kind="fixture",
                plan_hash="1" * 64,
                output_namespace=root / "output",
                ownership_token="1" * 32,
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SRC / "global_market_writer_claim.py"),
                    "recover-stale",
                    "--path",
                    str(path),
                    "--archive-dir",
                    str(archive_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                "trading_mvp_global_market_writer_claim_recovery_v1",
                result["schema"],
            )
            self.assertEqual("STALE_RECOVERED", result["status"])
            self.assertEqual("owner_process_dead", result["reason"])
            self.assertTrue(result["recovered"])
            self.assertFalse(path.exists())
            self.assertTrue(Path(result["archive_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
