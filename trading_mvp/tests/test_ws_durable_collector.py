from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ws_durable_collector import (  # noqa: E402
    STALE_HEARTBEAT_SEC,
    DurableRun,
    atomic_write_json,
    free_gb,
    infer_exit_reason,
    parse_symbols_arg,
    segment_dir_for,
    state_path_for,
    stitch_run,
)
import ws_durable_collector  # noqa: E402


class DiskGuardTests(unittest.TestCase):
    def test_free_gb_positive_for_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertGreater(free_gb(tmp), 0.0)

    def test_free_gb_resolves_nonexistent_child_to_existing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # несуществующий вложенный путь -> меряем по существующему родителю
            self.assertGreater(free_gb(Path(tmp) / "a" / "b" / "c"), 0.0)

    def test_guard_stops_cleanly_before_any_collect(self) -> None:
        # Огромный порог => guard срабатывает на сегменте 1 ДО сетевого сбора.
        with tempfile.TemporaryDirectory() as tmp:
            run = DurableRun(
                run_id="guard_test",
                out_root=Path(tmp),
                symbols_by_exchange={"mexc": ["BTC_USDT"]},
                total_duration_sec=120,
                segment_sec=60,
                heartbeat_sec=1000,
                min_free_gb=10 ** 9,
            )
            manifest = run.run()
            state = json.loads(state_path_for(run.run_dir).read_text(encoding="utf-8"))
        self.assertIn("disk_space_below_threshold", manifest["collector_exit_reason"])
        self.assertFalse(manifest["completed"])
        self.assertEqual(manifest["segments_total"], 0)
        self.assertEqual(state["status"], "terminated")
        self.assertIn("disk_space_below_threshold", state["exit_reason"])


class ParseSymbolsTests(unittest.TestCase):
    def test_two_exchanges(self) -> None:
        parsed = parse_symbols_arg("mexc:AAA_USDT,BBB_USDT;gateio:CCC_USDT")
        self.assertEqual(parsed, {"mexc": ["AAA_USDT", "BBB_USDT"], "gateio": ["CCC_USDT"]})

    def test_bad_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_symbols_arg("mexc AAA")
        with self.assertRaises(ValueError):
            parse_symbols_arg(";")


class AtomicWriteTests(unittest.TestCase):
    def test_write_and_no_tmp_left(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            atomic_write_json(path, {"a": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1})
            self.assertFalse(path.with_suffix(".json.tmp").exists())


class InferExitReasonTests(unittest.TestCase):
    def test_no_state(self) -> None:
        self.assertEqual(infer_exit_reason(None), "no_state_file")

    def test_completed_passthrough(self) -> None:
        state = {"status": "completed", "exit_reason": "completed_all_segments"}
        self.assertEqual(infer_exit_reason(state), "completed_all_segments")

    def test_running_stale_heartbeat_is_killed(self) -> None:
        now = time.time()
        state = {"status": "running", "exit_reason": "unknown", "heartbeat_epoch": now - STALE_HEARTBEAT_SEC - 10}
        self.assertEqual(infer_exit_reason(state, now_epoch=now), "killed_externally_inferred_stale_heartbeat")

    def test_running_fresh_heartbeat(self) -> None:
        now = time.time()
        state = {"status": "running", "exit_reason": "unknown", "heartbeat_epoch": now - 5}
        self.assertEqual(infer_exit_reason(state, now_epoch=now), "still_running")


def _write_segment_manifest(
    run_dir: Path,
    index: int,
    *,
    events: int,
    start: float,
    end: float,
    completed: bool = True,
    duration_completed: bool | None = None,
    liveness_clean: bool | None = None,
    quality_eligible: bool | None = None,
) -> None:
    seg = segment_dir_for(run_dir, index)
    seg.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        seg / "manifest.json",
        {
            "total_events": events,
            "completed": completed,
            "duration_completed": (
                completed if duration_completed is None else duration_completed
            ),
            "liveness_clean": completed if liveness_clean is None else liveness_clean,
            "quality_eligible": (
                completed if quality_eligible is None else quality_eligible
            ),
            "transport_rows": events,
            "market_envelope_rows": events,
            "normalized_events": events,
            "control_rows": 0,
            "unclassified_messages": 0,
            "market_silence_events": 0 if completed else 1,
            "reconnect_attempts": 0,
            "actual_duration_sec": end - start,
            "segment_started_epoch": start,
            "segment_finished_epoch": end,
            "results": [{"exchange": "mexc", "output": str(seg / "ws_mexc.jsonl"), "events": events}],
        },
    )


class StitchTests(unittest.TestCase):
    def test_stitch_full_run_with_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            t0 = 1_000_000.0
            _write_segment_manifest(run_dir, 1, events=100, start=t0, end=t0 + 100)
            # gap 50 сек между сегментами
            _write_segment_manifest(run_dir, 2, events=200, start=t0 + 150, end=t0 + 250)
            atomic_write_json(
                state_path_for(run_dir),
                {"status": "completed", "exit_reason": "completed_all_segments", "requested_total_sec": 200},
            )
            manifest = stitch_run(run_dir, expected_total_sec=200)
            stitched_exists = (run_dir / f"ws_collect_{run_dir.name}.json").exists()
        self.assertEqual(manifest["segments_total"], 2)
        self.assertEqual(manifest["total_events"], 300)
        self.assertEqual(len(manifest["gaps"]), 1)
        self.assertAlmostEqual(manifest["gaps"][0]["gap_sec"], 50.0)
        self.assertAlmostEqual(manifest["coverage_ratio"], 1.0)
        self.assertTrue(manifest["completed"])
        self.assertEqual(manifest["collector_exit_reason"], "completed_all_segments")
        self.assertTrue(stitched_exists)

    def test_stitch_postmortem_incomplete_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run2"
            t0 = 1_000_000.0
            _write_segment_manifest(run_dir, 1, events=100, start=t0, end=t0 + 100)
            # сегмент 2: raw есть, manifest нет (процесс убит)
            seg2 = segment_dir_for(run_dir, 2)
            seg2.mkdir(parents=True, exist_ok=True)
            (seg2 / "ws_mexc.jsonl").write_text("x\n" * 10, encoding="utf-8")
            atomic_write_json(
                state_path_for(run_dir),
                {
                    "status": "running",
                    "exit_reason": "unknown",
                    "requested_total_sec": 400,
                    "heartbeat_epoch": time.time() - STALE_HEARTBEAT_SEC - 60,
                },
            )
            manifest = stitch_run(run_dir, expected_total_sec=400)
        self.assertEqual(manifest["segments_total"], 2)
        self.assertEqual(manifest["segments_incomplete"], 1)
        self.assertEqual(manifest["segments_with_manifest"], 1)
        # события неполного сегмента неизвестны -> total только по известным
        self.assertEqual(manifest["total_events"], 100)
        self.assertEqual(manifest["events_known_for_segments"], 1)
        self.assertFalse(manifest["completed"])
        self.assertEqual(
            manifest["collector_exit_reason"],
            "killed_externally_inferred_stale_heartbeat",
        )

    def test_stitch_empty_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run3"
            run_dir.mkdir(parents=True)
            manifest = stitch_run(run_dir, expected_total_sec=100)
        self.assertEqual(manifest["segments_total"], 0)
        self.assertFalse(manifest["completed"])
        self.assertEqual(manifest["collector_exit_reason"], "no_state_file")

    def test_stitch_ignores_archived_incomplete_retry_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run4"
            t0 = 1_000_000.0
            _write_segment_manifest(run_dir, 1, events=100, start=t0, end=t0 + 100)
            archived = run_dir / "seg_002_incomplete_20260703_120000"
            archived.mkdir(parents=True)
            (archived / "ws_mexc.jsonl").write_text("x\n" * 10, encoding="utf-8")
            atomic_write_json(
                state_path_for(run_dir),
                {"status": "completed", "exit_reason": "completed_all_segments", "requested_total_sec": 100},
            )
            manifest = stitch_run(run_dir, expected_total_sec=100)
        self.assertEqual(manifest["segments_total"], 1)
        self.assertEqual(manifest["segments_with_manifest"], 1)
        self.assertTrue(manifest["completed"])
        self.assertEqual(manifest["total_events"], 100)

    def test_stitch_keeps_duration_complete_dirty_segment_diagnostic_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "dirty"
            _write_segment_manifest(
                run_dir,
                1,
                events=10,
                start=1_000.0,
                end=1_100.0,
                completed=False,
                duration_completed=True,
                liveness_clean=False,
                quality_eligible=False,
            )
            atomic_write_json(
                state_path_for(run_dir),
                {
                    "status": "completed",
                    "exit_reason": "completed_all_segments",
                    "requested_total_sec": 100,
                },
            )
            manifest = stitch_run(run_dir, expected_total_sec=100)

        self.assertTrue(manifest["runtime_completed"])
        self.assertFalse(manifest["liveness_clean"])
        self.assertFalse(manifest["quality_eligible"])
        self.assertFalse(manifest["completed"])
        self.assertEqual(manifest["segments_incomplete"], 0)
        self.assertEqual(manifest["dirty_segment_ids"], ["seg_001"])


class DurableLivenessContinuationTests(unittest.TestCase):
    @staticmethod
    def _result(*, clean: bool) -> dict:
        return {
            "actual_duration_sec": 10.0,
            "duration_completed": True,
            "liveness_clean": clean,
            "quality_eligible": clean,
            "completed": clean,
            "final": clean,
            "total_events": 10,
            "transport_rows": 10,
            "market_envelope_rows": 8 if clean else 0,
            "normalized_events": 8 if clean else 0,
            "control_rows": 2,
            "unclassified_messages": 0,
            "market_silence_events": 0 if clean else 1,
            "reconnect_attempts": 0 if clean else 1,
            "errors": {} if clean else {"gateio": ["market silence"]},
            "results": [],
            "stop_reasons": ["duration_sec"],
        }

    def test_dirty_completed_segment_does_not_block_next_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = DurableRun(
                run_id="dirty_continue",
                out_root=Path(tmp),
                symbols_by_exchange={"gateio": ["HYPE_USDT"]},
                total_duration_sec=20,
                segment_sec=10,
                heartbeat_sec=1000,
                min_free_gb=0.0,
            )
            with mock.patch.object(
                ws_durable_collector,
                "collect_ws_markets",
                side_effect=[self._result(clean=False), self._result(clean=True)],
            ) as collect:
                manifest = run.run()

        self.assertEqual(collect.call_count, 2)
        self.assertTrue(manifest["runtime_completed"])
        self.assertFalse(manifest["quality_eligible"])
        self.assertEqual(manifest["dirty_segment_ids"], ["seg_001"])


class DurableWrapperTests(unittest.TestCase):
    def test_planonly_exposes_guards_resume_and_replacement_path(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        script = REPO_ROOT / "tools" / "start_ws_collect_durable.ps1"
        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-TotalSec",
                "7200",
                "-SegmentSec",
                "3600",
                "-PlanOnly",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["mode"], "ws_collect_durable_plan")
        self.assertFalse(payload["would_start"])
        self.assertEqual(payload["total_sec"], 7200)
        self.assertEqual(payload["segment_sec"], 3600)
        self.assertEqual(payload["segments_planned"], 2)
        self.assertIn("self_preflight_guard", payload)
        self.assertIn("early_density_guard", payload)
        self.assertIn("zero_line_guard", payload)
        self.assertIn("schema_probe", payload)
        self.assertTrue(payload["notification_policy"]["gate_notification_required"])
        self.assertIn("STOPPED_INCOMPLETE.txt", payload["notification_policy"]["stopped_alert_file"])
        self.assertIn("start_ws_collect_durable.ps1", payload["resume_command"])
        self.assertIn("-Resume", payload["resume_command"])
        self.assertIn("-ConfirmedLongRun", payload["command_after_explicit_approval"])
        if payload.get("gate_status") == "STOPPED_INCOMPLETE":
            self.assertIn("-ReplaceStoppedIncomplete", payload["command_after_explicit_approval"])
            self.assertTrue(payload["replace_stopped_incomplete_available"])
        else:
            self.assertNotIn("-ReplaceStoppedIncomplete", payload["command_after_explicit_approval"])

    def test_wrapper_default_is_visible_not_hidden_detached(self) -> None:
        text = (REPO_ROOT / "tools" / "start_ws_collect_durable.ps1").read_text(encoding="utf-8")
        for needle in (
            "ConfirmedLongRun",
            "PlanOnly",
            "ReplaceStoppedIncomplete",
            "Resume",
            "STOPPED_INCOMPLETE.txt",
            "Test-WsRawSchema",
            "EarlyDensityCheckAfterMinutes",
            "trading_edge_preflight.ps1",
            "watch_ws_collect_durable.ps1",
            "notification_required",
        ):
            self.assertIn(needle, text)
        self.assertNotIn("-WindowStyle Hidden", text)


if __name__ == "__main__":
    unittest.main()
