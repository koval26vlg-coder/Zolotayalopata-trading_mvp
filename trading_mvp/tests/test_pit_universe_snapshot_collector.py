from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_universe_snapshot_collector import _next_cycle_sleep_sec, collect_snapshots  # noqa: E402


class PitUniverseSnapshotCollectorTests(unittest.TestCase):
    def test_cycle_cadence_subtracts_cycle_runtime_from_interval(self) -> None:
        self.assertEqual(_next_cycle_sleep_sec(300.0, 60.0, 1_000.0), 240.0)
        self.assertEqual(_next_cycle_sleep_sec(300.0, 350.0, 1_000.0), 0.0)
        self.assertEqual(_next_cycle_sleep_sec(300.0, 60.0, 100.0), 100.0)

    @staticmethod
    def _row(snapshot_ts: str, symbol: str = "HYPE_USDT") -> dict[str, object]:
        return {
            "snapshot_ts": snapshot_ts,
            "exchange": "mexc",
            "symbol": symbol,
            "base": symbol.removesuffix("_USDT"),
            "quote": "USDT",
            "contract_type": "linear_perp",
            "status": "trading",
            "listed_now": True,
            "inactive_or_delisted": False,
            "volume_24h_quote": 1000.0,
            "bid_price": 9.99,
            "ask_price": 10.01,
            "mid_price": 10.0,
            "spread_bps": 20.0,
            "binance_spot_listed": False,
            "excluded_by_binance_spot": False,
            "eligible_non_binance_spot": True,
            "source_endpoint": "fixture",
            "raw_status": 0,
            "first_seen_ts": None,
            "last_seen_ts": snapshot_ts,
        }

    def test_collect_snapshots_writes_jsonl_and_final_manifest(self) -> None:
        fake_report = {
            "decision": "PIT_UNIVERSE_PUBLIC_PROBE_ACCEPTED_READY_FOR_VISIBLE_SNAPSHOT_COLLECT_APPROVAL",
            "errors": {},
            "depth_errors": {"HYPE_USDT": "fixture depth error"},
            "summary": {
                "mexc_depth": {"targets": 2, "complete": 1, "missing": 1, "coverage": 0.5}
            },
            "rows": [
                {
                    "snapshot_ts": "2026-07-09T00:00:00+00:00",
                    "exchange": "mexc",
                    "symbol": "HYPE_USDT",
                    "base": "HYPE",
                    "quote": "USDT",
                    "contract_type": "linear_perp",
                    "status": "trading",
                    "listed_now": True,
                    "inactive_or_delisted": False,
                    "volume_24h_quote": 1000.0,
                    "source_endpoint": "fixture",
                    "raw_status": 0,
                    "first_seen_ts": "2026-07-09T00:00:00+00:00",
                    "last_seen_ts": "2026-07-09T00:00:00+00:00",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pit_universe_snapshot_collector.run_public_probe",
            return_value=fake_report,
        ) as probe:
            manifest = collect_snapshots(
                output_root=Path(tmp),
                run_id="test_run",
                duration_sec=0,
                interval_sec=300,
                timeout_sec=1,
                min_contracts_per_exchange=1,
            )
            run_dir = Path(tmp) / "test_run"
            rows = (run_dir / "snapshots.jsonl").read_text(encoding="utf-8").splitlines()
            saved_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            cycle_rows = (run_dir / "cycles.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertTrue(manifest["final"])
        self.assertTrue(saved_manifest["final"])
        self.assertEqual(manifest["cycle_count"], 1)
        self.assertEqual(manifest["rows_total"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["run_id"], "test_run")
        self.assertEqual(len(cycle_rows), 1)
        self.assertEqual(json.loads(cycle_rows[0])["cycle"], 1)
        self.assertEqual(saved_manifest["cycles_path"], str(run_dir / "cycles.jsonl"))
        self.assertEqual(saved_manifest["depth_errors_total"], 1)
        self.assertEqual(saved_manifest["depth_error_cycles"], 1)
        self.assertEqual(saved_manifest["last_mexc_depth_coverage"], 0.5)
        self.assertTrue(probe.call_args.kwargs["include_mexc_depth"])

    def test_disk_guard_stops_incomplete_before_network_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pit_universe_snapshot_collector._free_disk_gib",
            return_value=0.25,
        ), patch("pit_universe_snapshot_collector.run_public_probe") as probe:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "disk_space_below_threshold"):
                collect_snapshots(
                    output_root=root,
                    run_id="disk_guard_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                    min_free_disk_gib=5.0,
                )
            manifest = json.loads((root / "disk_guard_run" / "manifest.json").read_text(encoding="utf-8"))

        probe.assert_not_called()
        self.assertFalse(manifest["final"])
        self.assertEqual(manifest["status"], "STOPPED_INCOMPLETE")
        self.assertIn("disk_space_below_threshold", manifest["stop_reason"])
        self.assertEqual(manifest["min_free_disk_gib"], 5.0)

    def test_visible_output_failure_records_stage_and_errno(self) -> None:
        report = {
            "decision": "accepted",
            "errors": {},
            "rows": [self._row("2026-07-09T00:00:00+00:00")],
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pit_universe_snapshot_collector.run_public_probe",
            return_value=report,
        ), patch("builtins.print", side_effect=OSError(22, "Invalid argument")):
            root = Path(tmp)
            with self.assertRaises(OSError):
                collect_snapshots(
                    output_root=root,
                    run_id="invalid_console_handle",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                )
            manifest = json.loads(
                (root / "invalid_console_handle" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(manifest["status"], "STOPPED_INCOMPLETE")
        self.assertFalse(manifest["final"])
        self.assertEqual(manifest["failure_stage"], "visible_progress_output")
        self.assertEqual(manifest["exception_type"], "OSError")
        self.assertEqual(manifest["exception_errno"], 22)
        self.assertIn("pit_universe_snapshot_collector.py", manifest["failure_traceback"])
        self.assertIn("OSError: [Errno 22] Invalid argument", manifest["failure_traceback"])

    def test_resume_preserves_run_identity_counts_and_monotonic_cycles(self) -> None:
        reports = [
            {"decision": "accepted", "errors": {}, "rows": [self._row("2026-07-09T00:00:00+00:00")]},
            {"decision": "accepted", "errors": {}, "rows": [self._row("2026-07-09T00:05:00+00:00")]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("pit_universe_snapshot_collector.run_public_probe", side_effect=reports):
                first = collect_snapshots(
                    output_root=root,
                    run_id="resume_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                )
                manifest_path = root / "resume_run" / "manifest.json"
                stopped = json.loads(manifest_path.read_text(encoding="utf-8"))
                stopped.update({"final": False, "status": "STOPPED_INCOMPLETE"})
                manifest_path.write_text(json.dumps(stopped), encoding="utf-8")

                resumed = collect_snapshots(
                    output_root=root,
                    run_id="resume_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                    resume=True,
                )

            rows = [json.loads(line) for line in (root / "resume_run" / "snapshots.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(first["cycle_count"], 1)
        self.assertEqual(resumed["cycle_count"], 2)
        self.assertEqual(resumed["rows_total"], 2)
        self.assertEqual(resumed["resume_count"], 1)
        self.assertEqual(resumed["started_at_utc"], first["started_at_utc"])
        self.assertEqual([row["cycle"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["first_seen_ts"], rows[1]["first_seen_ts"])

    def test_existing_run_requires_explicit_resume(self) -> None:
        report = {"decision": "accepted", "errors": {}, "rows": [self._row("2026-07-09T00:00:00+00:00")]}
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pit_universe_snapshot_collector.run_public_probe", return_value=report
        ):
            root = Path(tmp)
            collect_snapshots(
                output_root=root,
                run_id="existing_run",
                duration_sec=0,
                interval_sec=300,
                timeout_sec=1,
                min_contracts_per_exchange=1,
            )
            with self.assertRaisesRegex(FileExistsError, "resume"):
                collect_snapshots(
                    output_root=root,
                    run_id="existing_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                )

    def test_resume_rejects_incompatible_manifest_without_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "legacy_run"
            run_dir.mkdir(parents=True)
            snapshots_path = run_dir / "snapshots.jsonl"
            original_snapshots = '{"cycle":1,"exchange":"mexc","symbol":"HYPE_USDT"}\n'
            snapshots_path.write_text(original_snapshots, encoding="utf-8")
            manifest_path = run_dir / "manifest.json"
            legacy_manifest = {
                "schema": "pit_universe_snapshot_manifest_v1",
                "mode": "pit_universe_snapshot_collect",
                "run_id": "legacy_run",
                "final": False,
                "duration_sec": 300,
                "interval_sec": 300,
                "timeout_sec": 1,
                "min_contracts_per_exchange": 1,
                "cycle_count": 1,
                "rows_total": 1,
            }
            manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "resume schema mismatch"):
                collect_snapshots(
                    output_root=root,
                    run_id="legacy_run",
                    duration_sec=300,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                    resume=True,
                    stop_requested=lambda: True,
                )

            self.assertEqual(snapshots_path.read_text(encoding="utf-8"), original_snapshots)
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                legacy_manifest,
            )

    def test_resume_rejects_missing_cycle_journal(self) -> None:
        report = {"decision": "accepted", "errors": {}, "rows": [self._row("2026-07-09T00:00:00+00:00")]}
        with tempfile.TemporaryDirectory() as tmp, patch(
            "pit_universe_snapshot_collector.run_public_probe", return_value=report
        ):
            root = Path(tmp)
            collect_snapshots(
                output_root=root,
                run_id="missing_journal",
                duration_sec=0,
                interval_sec=300,
                timeout_sec=1,
                min_contracts_per_exchange=1,
            )
            manifest_path = root / "missing_journal" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update({"final": False, "status": "STOPPED_INCOMPLETE"})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "missing_journal" / "cycles.jsonl").unlink()

            with self.assertRaisesRegex(ValueError, "cycle journal missing"):
                collect_snapshots(
                    output_root=root,
                    run_id="missing_journal",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                    resume=True,
                    stop_requested=lambda: True,
                )

    def test_live_writer_lock_rejects_duplicate_collector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "locked_run"
            run_dir.mkdir(parents=True)
            (run_dir / "collector.lock").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "already active"):
                collect_snapshots(
                    output_root=Path(tmp),
                    run_id="locked_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                    resume=True,
                )

    def test_resume_emits_tombstone_without_resetting_last_seen(self) -> None:
        reports = [
            {"decision": "accepted", "errors": {}, "rows": [self._row("2026-07-09T00:00:00+00:00")]},
            {"decision": "accepted", "errors": {}, "rows": []},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("pit_universe_snapshot_collector.run_public_probe", side_effect=reports):
                collect_snapshots(
                    output_root=root,
                    run_id="tombstone_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                )
                manifest_path = root / "tombstone_run" / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["final"] = False
                manifest["status"] = "STOPPED_INCOMPLETE"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                collect_snapshots(
                    output_root=root,
                    run_id="tombstone_run",
                    duration_sec=0,
                    interval_sec=300,
                    timeout_sec=1,
                    min_contracts_per_exchange=1,
                    resume=True,
                )
            rows = [json.loads(line) for line in (root / "tombstone_run" / "snapshots.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[1]["observed_now"])
        self.assertTrue(rows[1]["tombstone"])
        self.assertEqual(rows[1]["first_seen_ts"], "2026-07-09T00:00:00+00:00")
        self.assertEqual(rows[1]["last_seen_ts"], "2026-07-09T00:00:00+00:00")
        self.assertEqual(rows[1]["missing_since_ts"], rows[1]["snapshot_ts"])


if __name__ == "__main__":
    unittest.main()
