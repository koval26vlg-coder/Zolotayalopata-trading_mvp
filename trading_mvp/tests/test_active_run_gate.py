from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "tools" / "check_active_run_gate.ps1"
MONITOR_SCRIPT = REPO_ROOT / "tools" / "trading_active_run_monitor.ps1"
COMPLETION_AUDIT_SCRIPT = REPO_ROOT / "tools" / "trading_goal_completion_audit.ps1"


class ActiveRunGateTests(unittest.TestCase):
    def test_gate_read_rejects_incomplete_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / "active-run-gate.json"
            gate.write_text(
                json.dumps({"status": "READY_FOR_POSTPROCESS"}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(GATE_SCRIPT),
                    "-GatePath",
                    str(gate),
                    "-Json",
                    "-StableReadAttempts",
                    "2",
                    "-StableReadDelayMs",
                    "0",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "ACTIVE_RUN_GATE_UNSTABLE_OR_INVALID",
            completed.stderr + completed.stdout,
        )

    def test_invalid_current_run_pointer_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_log = Path(tmp) / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "gate-fixture",
                        "status": "READY_FOR_POSTPROCESS",
                    }
                ),
                encoding="utf-8",
            )
            (agent_log / "current-run.json").write_text(
                '{"schema":"active_run_pointer_v1"}\n{"torn":true}',
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(GATE_SCRIPT),
                    "-GatePath",
                    str(gate),
                    "-Json",
                    "-StableReadAttempts",
                    "2",
                    "-StableReadDelayMs",
                    "0",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "ACTIVE_RUN_POINTER_UNSTABLE_OR_INVALID",
            completed.stderr + completed.stdout,
        )

    def test_terminal_pointer_for_different_run_overrides_ready_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_log = Path(tmp) / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "stale-ready-run",
                        "status": "READY_FOR_POSTPROCESS",
                    }
                ),
                encoding="utf-8",
            )
            (agent_log / "current-run.json").write_text(
                json.dumps(
                    {
                        "schema": "active_run_pointer_v1",
                        "project": "trading_mvp",
                        "run_id": "current-stopped-run",
                        "status": "STOPPED_INCOMPLETE",
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["gate_source"], "current_run_pointer")
        self.assertEqual(result["run_id"], "current-stopped-run")
        self.assertEqual(result["status"], "STOPPED_INCOMPLETE")


    def test_gate_read_retries_transient_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                '{"schema":"active_run_gate_v2"}\n{"torn":true}', encoding="utf-8"
            )

            valid_gate = json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": "stable-read-fixture",
                    "status": "READY_FOR_POSTPROCESS",
                }
            )

            def replace_gate() -> None:
                time.sleep(2.0)
                replacement = gate.with_suffix(".json.tmp")
                replacement.write_text(valid_gate, encoding="utf-8")
                os.replace(replacement, gate)

            writer = threading.Thread(target=replace_gate)
            writer.start()
            try:
                result = self._run_gate(
                    gate,
                    "-StableReadAttempts",
                    "50",
                    "-StableReadDelayMs",
                    "100",
                )
            finally:
                writer.join(timeout=2)

        self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
        self.assertEqual(result["run_id"], "stable-read-fixture")
        self.assertGreater(result["gate_read_attempts"], 2)

    def test_gate_read_fails_closed_when_json_stays_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                '{"schema":"active_run_gate_v2"}\n{"torn":true}', encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(GATE_SCRIPT),
                    "-GatePath",
                    str(gate),
                    "-Json",
                    "-StableReadAttempts",
                    "3",
                    "-StableReadDelayMs",
                    "10",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "ACTIVE_RUN_GATE_UNSTABLE_OR_INVALID",
            completed.stderr + completed.stdout,
        )
    def test_current_run_pointer_does_not_inherit_stale_completion_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            active = root / "active"
            stale = root / "stale"
            agent_log.mkdir(parents=True)
            active.mkdir(parents=True)
            stale.mkdir(parents=True)
            snapshots = active / "snapshots.jsonl"
            snapshots.write_text("{}\n", encoding="utf-8")
            manifest = active / "manifest.json"
            manifest.write_text(json.dumps({"run_id": "new", "final": False}), encoding="utf-8")
            completed = stale / "completed.json"
            completed.write_text("{}", encoding="utf-8")
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "old",
                        "status": "READY_FOR_POSTPROCESS",
                        "expected_outputs_complete": True,
                        "expected_outputs": {"result": str(completed)},
                    }
                ),
                encoding="utf-8",
            )
            (agent_log / "current-run.json").write_text(
                json.dumps(
                    {
                        "schema": "active_run_pointer_v1",
                        "project": "trading_mvp",
                        "run_id": "new",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "output": {"path": str(snapshots), "kind": "file"},
                        "monitor_pid": os.getpid(),
                        "process_ids": [],
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["run_id"], "new")
        self.assertEqual(result["status"], "RUNNING")
        self.assertFalse(result["expected_outputs_complete"])

    def test_same_run_pointer_ignores_outputs_from_mismatched_launch_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            current = root / "current"
            stale = root / "stale"
            agent_log.mkdir(parents=True)
            current.mkdir(parents=True)
            stale.mkdir(parents=True)

            snapshots = current / "snapshots.jsonl"
            snapshots.write_text("{}\n", encoding="utf-8")
            manifest = current / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "pit_universe_snapshot_manifest_v2",
                        "mode": "pit_universe_snapshot_collect",
                        "run_id": "current_pit",
                        "final": False,
                        "snapshots_path": str(snapshots),
                    }
                ),
                encoding="utf-8",
            )
            stale_outputs = {}
            for name in ("manifest", "snapshots", "errors"):
                path = stale / f"{name}.json"
                path.write_text("{}\n", encoding="utf-8")
                stale_outputs[name] = str(path)

            launch_record = agent_log / "current_pit.launch.json"
            launch_record.write_text(
                json.dumps(
                    {
                        "schema": "active_run_launch_record_v1",
                        "project": "trading_mvp",
                        "run_id": "current_pit",
                        "run_type": "pit_universe_snapshot_collect",
                        "manifest_path": str(manifest),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "current_pit",
                        "run_type": "paper_public_readonly_probe",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "output_path": str(snapshots),
                        "expected_outputs_complete": True,
                        "expected_outputs": stale_outputs,
                        "readiness_output_path": str(stale / "readiness.json"),
                        "process_ids": [],
                    }
                ),
                encoding="utf-8",
            )
            (agent_log / "current-run.json").write_text(
                json.dumps(
                    {
                        "schema": "active_run_pointer_v1",
                        "project": "trading_mvp",
                        "run_id": "current_pit",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "process_ids": [],
                        "launch_record_path": str(launch_record),
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["run_type"], "pit_universe_snapshot_collect")
        self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
        self.assertFalse(result["expected_outputs_complete"])
        self.assertFalse(result["expected_outputs_applicable"])
        self.assertIsNone(result["readiness_output_path"])
        self.assertIn("expected_outputs", result["stale_run_metadata_ignored"])
        self.assertIsNone(result["launch_record_error"])

    def test_invalid_current_launch_record_cannot_open_gate_from_old_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({"run_id": "current", "final": False}),
                encoding="utf-8",
            )
            old_output = root / "old-output.json"
            old_output.write_text("{}\n", encoding="utf-8")
            launch_record = root / "launch.json"
            launch_record.write_text(
                json.dumps(
                    {
                        "schema": "active_run_launch_record_v1",
                        "project": "trading_mvp",
                        "run_id": "wrong",
                        "run_type": "old_type",
                        "manifest_path": str(manifest),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "current",
                        "run_type": "old_type",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "expected_outputs_complete": True,
                        "expected_outputs": {"result": str(old_output)},
                        "process_ids": [],
                    }
                ),
                encoding="utf-8",
            )
            (agent_log / "current-run.json").write_text(
                json.dumps(
                    {
                        "schema": "active_run_pointer_v1",
                        "project": "trading_mvp",
                        "run_id": "current",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "process_ids": [],
                        "launch_record_path": str(launch_record),
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
        self.assertFalse(result["expected_outputs_applicable"])
        self.assertFalse(result["expected_outputs_complete"])
        self.assertIn("identity mismatch", result["launch_record_error"])

    def test_running_gate_allows_only_disjoint_declared_offline_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            active = root / "active-run"
            agent_log.mkdir(parents=True)
            active.mkdir(parents=True)
            output = active / "snapshots.jsonl"
            output.write_text("{}\n", encoding="utf-8")
            manifest = active / "manifest.json"
            manifest.write_text(json.dumps({"final": False}), encoding="utf-8")
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "active",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "output": {"path": str(output), "kind": "file"},
                        "monitor_pid": os.getpid(),
                        "process_ids": [],
                    }
                ),
                encoding="utf-8",
            )
            disjoint_in = root / "immutable-cache"
            disjoint_out = root / "worktree-output"
            result = self._run_gate(
                gate,
                "-OfflineWork",
                "-ReadResourcePath",
                str(disjoint_in),
                "-WriteResourcePath",
                str(disjoint_out),
            )
            overlapping = self._run_gate(
                gate,
                "-OfflineWork",
                "-ReadResourcePath",
                str(active / "child.json"),
                "-WriteResourcePath",
                str(disjoint_out),
            )
            legacy = self._run_gate(gate)

        self.assertEqual(result["status"], "RUNNING")
        self.assertTrue(result["scope_decision"]["allowed"])
        self.assertEqual(result["scope_decision"]["decision"], "ALLOW_DISJOINT_OFFLINE_WORK")
        self.assertFalse(overlapping["scope_decision"]["allowed"])
        self.assertIn("read", overlapping["scope_decision"]["conflicts"][0]["access"])
        self.assertNotIn("scope_decision", legacy)

    def test_resource_overlap_is_case_insensitive_and_segment_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            agent_log.mkdir(parents=True)
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "active",
                        "status": "RUNNING",
                        "output": {"path": r"C:\Data\Run\snapshots.jsonl", "kind": "file"},
                        "manifest_path": r"C:\Data\Run\manifest.json",
                        "monitor_pid": os.getpid(),
                        "process_ids": [],
                    }
                ),
                encoding="utf-8",
            )
            conflict = self._run_gate(
                gate,
                "-OfflineWork",
                "-ReadResourcePath",
                r"c:\data\run\Child\input.json",
                "-WriteResourcePath",
                r"C:\Elsewhere\out.json",
            )
            sibling = self._run_gate(
                gate,
                "-OfflineWork",
                "-ReadResourcePath",
                r"C:\Data\Runner\input.json",
                "-WriteResourcePath",
                r"C:\Elsewhere\out.json",
            )

        self.assertFalse(conflict["scope_decision"]["allowed"])
        self.assertTrue(sibling["scope_decision"]["allowed"])

    def test_current_run_pointer_overrides_stale_legacy_run_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            current = root / "current"
            agent_log.mkdir(parents=True)
            current.mkdir(parents=True)
            snapshots = current / "snapshots.jsonl"
            snapshots.write_text("{}\n{}\n", encoding="utf-8")
            manifest = current / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "pit_universe_snapshot_manifest_v2",
                        "mode": "pit_universe_snapshot_collect",
                        "run_id": "current_pit",
                        "final": False,
                        "cycle_count": 2,
                        "rows_total": 2,
                        "errors_total": 0,
                        "snapshots_path": str(snapshots),
                    }
                ),
                encoding="utf-8",
            )
            legacy_gate = agent_log / "active-run-gate.json"
            legacy_gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "stale_run",
                        "status": "RUNNING",
                        "collector_pid": 999999,
                        "process_ids": [999999],
                        "monitor_pid": None,
                        "output_path": str(root / "stale.jsonl"),
                        "manifest_path": str(root / "stale.manifest.json"),
                    }
                ),
                encoding="utf-8",
            )
            pointer = agent_log / "current-run.json"
            pointer.write_text(
                json.dumps(
                    {
                        "schema": "active_run_pointer_v1",
                        "project": "trading_mvp",
                        "run_id": "current_pit",
                        "status": "RUNNING",
                        "manifest_path": str(manifest),
                        "output": {"path": str(snapshots), "kind": "file"},
                        "collector_pid": os.getpid(),
                        "monitor_pid": None,
                        "process_ids": [os.getpid()],
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(legacy_gate)

        self.assertEqual(result["gate_source"], "current_run_pointer")
        self.assertEqual(result["current_run_pointer_path"], str(pointer))
        self.assertEqual(result["run_id"], "current_pit")
        self.assertEqual(result["status"], "RUNNING")
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["output"]["path"], str(snapshots))
        self.assertIn(os.getpid(), result["live_process_ids"])

    def test_pit_gate_prefers_manifest_output_and_collector_pid_over_stale_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            current = root / "current"
            stale = root / "stale.jsonl"
            agent_log.mkdir(parents=True)
            current.mkdir(parents=True)
            stale.write_text("{}\n{}\n", encoding="utf-8")
            snapshots = current / "snapshots.jsonl"
            snapshots.write_text("{}\n{}\n{}\n", encoding="utf-8")
            manifest = current / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "pit_universe_snapshot_collect",
                        "final": False,
                        "cycle_count": 4,
                        "rows_total": 3,
                        "errors_total": 2,
                        "snapshots_path": str(snapshots),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "pit_fixture",
                        "status": "RUNNING",
                        "collector_pid": os.getpid(),
                        "process_ids": [],
                        "monitor_pid": None,
                        "output_path": str(stale),
                        "output": {"path": str(snapshots), "kind": "file"},
                        "manifest_path": str(manifest),
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["status"], "RUNNING")
        self.assertEqual(result["completed_cycles"], 4)
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["output"]["path"], str(snapshots))
        self.assertIn(os.getpid(), result["live_process_ids"])

    def test_manifest_zero_errors_is_not_overridden_by_stale_gate_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            run_dir = root / "pit-run"
            agent_log.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            snapshots = run_dir / "snapshots.jsonl"
            snapshots.write_text("{}\n", encoding="utf-8")
            manifest = run_dir / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "pit_universe_snapshot_manifest_v2",
                        "final": True,
                        "cycle_count": 1,
                        "rows_total": 1,
                        "errors_total": 0,
                        "snapshots_path": str(snapshots),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "pit_zero_error_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "errors": 1,
                        "manifest_path": str(manifest),
                        "output": {"path": str(snapshots), "kind": "file"},
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["errors"], 0)

    def test_pit_gate_infers_progress_from_manifest_duration_and_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            run_dir = root / "pit-run"
            agent_log.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            snapshots = run_dir / "snapshots.jsonl"
            snapshots.write_text("{}\n", encoding="utf-8")
            manifest = run_dir / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "pit_universe_snapshot_manifest_v2",
                        "mode": "pit_universe_snapshot_collect",
                        "final": False,
                        "cycle_count": 21,
                        "rows_total": 35_637,
                        "errors_total": 0,
                        "duration_sec": 10_800,
                        "elapsed_active_sec": 6_108.7,
                        "interval_sec": 300,
                        "snapshots_path": str(snapshots),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "pit_progress_fixture",
                        "status": "RUNNING",
                        "collector_pid": os.getpid(),
                        "process_ids": [os.getpid()],
                        "monitor_pid": None,
                        "manifest_path": str(manifest),
                        "output_path": str(snapshots),
                        "total_cycles": 2,
                        "completed_cycles": 2,
                        "requested_duration_sec": 1_200,
                        "actual_duration_sec": 13.266,
                        "poll_interval_sec": 300,
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["completed_cycles"], 21)
        self.assertEqual(result["total_cycles"], 36)
        self.assertEqual(result["remaining_cycles"], 15)
        self.assertEqual(result["remaining_hours"], 1.3)
        self.assertEqual(result["requested_duration_sec"], 10_800)
        self.assertEqual(result["actual_duration_sec"], 6_108.7)

    def test_pit_visible_wrapper_has_resume_and_failure_safe_gate_contract(self) -> None:
        wrapper = REPO_ROOT / "tools" / "start_pit_universe_snapshot_collect_visible.ps1"
        text = wrapper.read_text(encoding="utf-8")

        for needle in (
            "ResumeIncomplete",
            "collector_pid",
            "process_ids",
            "output_path",
            "-NoNewWindow",
            "STOPPED_INCOMPLETE",
            "manifest.final",
            "pit_universe_snapshot_manifest_v2",
            "cycles.jsonl",
            "incompatible",
            "START_NEW_VISIBLE_PIT_UNIVERSE_SNAPSHOT_COLLECT_AFTER_FIX_APPROVAL",
            "current-run.json",
            "run-gates",
            "active_run_pointer_v1",
            "ApprovedNotBefore",
            "ApprovedNotLaterThan",
            "MinFreeDiskGiB",
            "Get-FreeDiskGiB",
            "--min-free-disk-gib",
            "SchedulePlanPath",
            "ExpectedSchedulePlanHash",
            "night-schedule-approvals",
            "approved_night_schedule",
            "ConvertFrom-JsonPreserveDateStrings",
            "authorize-segment",
            "collection_stage",
            "quality_ledger_path",
        ):
            self.assertIn(needle, text)

    def test_final_zero_event_manifest_preserves_semantic_counters_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            artifacts = root / "artifacts"
            agent_log.mkdir(parents=True)
            artifacts.mkdir(parents=True)
            evaluation = artifacts / "evaluation.json"
            repeat = artifacts / "evaluation.repeat.json"
            evaluation.write_text("{\n  \"verdict\": \"INSUFFICIENT_DATA\"\n}\n", encoding="utf-8")
            repeat.write_text(evaluation.read_text(encoding="utf-8"), encoding="utf-8")
            manifest = artifacts / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "fast_first_v2_residual_dispersion_manifest_v1",
                        "final": True,
                        "completed_cycles": 2,
                        "cycles": 2,
                        "rows": 0,
                        "errors": 0,
                        "output_path": str(evaluation),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "fast_first_v2_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "manifest_path": str(manifest),
                        "output": {"path": str(evaluation), "kind": "file"},
                        "expected_outputs_complete": True,
                        "expected_outputs": {
                            "evaluation": str(evaluation),
                            "repeat": str(repeat),
                            "manifest": str(manifest),
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["completed_cycles"], 2)
        self.assertEqual(result["total_cycles"], 2)
        self.assertEqual(result["remaining_cycles"], 0)
        self.assertEqual(result["rows"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertTrue(result["expected_outputs_complete"])

    def test_final_terminal_manifest_falls_back_to_gate_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            artifacts = root / "artifacts"
            agent_log.mkdir(parents=True)
            artifacts.mkdir(parents=True)
            closure = artifacts / "closure.json"
            closure.write_text("{}\n", encoding="utf-8")
            manifest = artifacts / "closure.manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "terminal_closure_manifest_v1",
                        "status": "BRANCH_CLOSED_TRAIN_INFEASIBLE",
                        "final": True,
                        "closure_path": str(closure),
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "run_id": "terminal_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "manifest_path": str(manifest),
                        "output": {"path": str(closure), "kind": "file"},
                        "completed_cycles": 1,
                        "total_cycles": 1,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

        self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
        self.assertEqual(result["completed_cycles"], 1)
        self.assertEqual(result["total_cycles"], 1)
        self.assertEqual(result["remaining_cycles"], 0)

    def setUp(self) -> None:
        if shutil.which("pwsh") is None:
            self.skipTest("PowerShell 7 (pwsh) is required for active-run gate wrapper tests")

    def _run_gate(self, gate_path: Path, *extra_args: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(GATE_SCRIPT),
                "-GatePath",
                str(gate_path),
                "-Json",
                *extra_args,
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def _run_monitor_once(self, gate_path: Path) -> dict[str, object]:
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(MONITOR_SCRIPT),
                "-GatePath",
                str(gate_path),
                "-Once",
                "-Json",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        return json.loads(completed.stdout)

    def _run_completion_audit(self, gate_path: Path) -> dict[str, object]:
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(COMPLETION_AUDIT_SCRIPT),
                "-GatePath",
                str(gate_path),
                "-SkipHeavyGates",
                "-SkipSwarm",
                "-Json",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        return json.loads(completed.stdout)

    def _write_completed_funding_gate(self, root: Path) -> tuple[Path, Path, Path]:
        agent_log = root / "docs" / "agent-log"
        funding_dir = root / "exports" / "trading-mvp" / "funding"
        agent_log.mkdir(parents=True)
        funding_dir.mkdir(parents=True)

        output = funding_dir / "funding_collect_fixture.jsonl"
        output.write_text("{}\n{}\n", encoding="utf-8")
        manifest = funding_dir / "funding_collect_fixture.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "final": True,
                    "cycles": 2,
                    "completed_cycles": 2,
                    "rows": 2,
                    "errors": 0,
                }
            ),
            encoding="utf-8",
        )
        gate = agent_log / "active-run-gate.json"
        gate.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v1",
                    "project": "trading_mvp",
                    "run_id": "funding_collect_fixture",
                    "status": "READY_FOR_POSTPROCESS",
                    "monitor_pid": 999999,
                    "process_ids": [999999],
                    "output_path": str(output),
                    "manifest_path": str(manifest),
                    "total_cycles": 2,
                    "poll_interval_sec": 300,
                    "next_step_after_ready": "Run guarded funding-final-review on the completed JSONL.",
                }
            ),
            encoding="utf-8",
        )
        return gate, output, manifest

    def test_completed_funding_gate_reports_guard_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate, output, manifest = self._write_completed_funding_gate(root)
            guard = root / "exports" / "trading-mvp" / "funding" / "funding_final_review_guard_stop_verify.json"
            guard.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "status": "not_ready_for_postprocess",
                        "input": str(output),
                        "manifest": str(manifest),
                        "collect_status": {
                            "ready_for_postprocess": False,
                            "readiness": {"reasons": ["data_quality:min_min_rows_per_cycle"]},
                            "data_quality": {
                                "reasons": ["min_min_rows_per_cycle"],
                                "metrics": {"min_rows_per_cycle": 9},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertIn("blocked by guard review", result["warning"])
            self.assertEqual(result["postprocess_block"]["status"], "not_ready_for_postprocess")
            self.assertEqual(result["postprocess_block"]["min_rows_per_cycle"], 9)
            self.assertIn("do not use this funding dataset", result["next_step_after_ready"])
            self.assertIn("Run guarded funding-final-review", result["raw_gate_next_step_after_ready"])

    def test_completed_funding_gate_without_guard_keeps_raw_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate, _, _ = self._write_completed_funding_gate(Path(tmp))

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertIsNone(result["postprocess_block"])
            self.assertEqual(result["next_step_after_ready"], "Run guarded funding-final-review on the completed JSONL.")

    def test_stopped_incomplete_ws_gate_handles_directory_output_and_error_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            raw_dir = root / "exports" / "trading-mvp" / "raw"
            agent_log.mkdir(parents=True)
            raw_dir.mkdir(parents=True)

            raw_file = raw_dir / "ws_mexc_fixture.jsonl"
            raw_file.write_text("{}\n", encoding="utf-8")
            manifest = raw_dir / "ws_collect_fixture.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "public_ws_collect",
                        "duration_sec": 21600,
                        "actual_duration_sec": 13554.7,
                        "total_events": 10,
                        "errors": {
                            "mexc": [{"type": "ConnectionResetError"}],
                            "gateio": [
                                {"type": "WebSocketAddressException"},
                                {"type": "WebSocketAddressException"},
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "ws_collect_fixture",
                        "status": "STOPPED_INCOMPLETE",
                        "monitor_pid": os.getpid(),
                        "stale_monitor_pid": os.getpid(),
                        "process_ids": [os.getpid()],
                        "output_path": str(raw_dir),
                        "manifest_path": str(manifest),
                        "stop_reason": "collector_stopped_before_requested_duration",
                        "requested_duration_sec": 21600,
                        "actual_duration_sec": 13554.7,
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
            self.assertEqual(result["gate_status"], "STOPPED_INCOMPLETE")
            self.assertEqual(result["rows"], 10)
            self.assertEqual(result["errors"], 3)
            self.assertEqual(result["output"]["kind"], "directory")
            self.assertEqual(result["output"]["file_count"], 2)
            self.assertEqual(result["stop_reason"], "collector_stopped_before_requested_duration")
            self.assertEqual(result["requested_duration_sec"], 21600)
            self.assertEqual(result["actual_duration_sec"], 13554.7)

    def test_ready_ws_gate_without_final_field_is_ready_for_postprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            raw_dir = root / "exports" / "trading-mvp" / "raw"
            agent_log.mkdir(parents=True)
            raw_dir.mkdir(parents=True)

            raw_file = raw_dir / "ws_mexc_fixture.jsonl"
            raw_file.write_text("{}\n", encoding="utf-8")
            manifest = raw_dir / "ws_collect_fixture.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "public_ws_collect",
                        "duration_sec": 21600,
                        "total_events": 2745067,
                        "errors": {},
                        "results": [
                            {
                                "exchange": "mexc",
                                "events": 2083425,
                                "errors": [],
                                "duration_sec": 21602.1,
                            },
                            {
                                "exchange": "gateio",
                                "events": 661642,
                                "errors": [],
                                "duration_sec": 21601.8,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "ws_collect_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "monitor_pid": None,
                        "process_ids": [],
                        "output_path": str(raw_dir),
                        "manifest_path": str(manifest),
                        "requested_duration_sec": 21600,
                        "actual_duration_sec": 21602.1,
                        "next_step_after_ready": "Run guarded ws-postprocess.",
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(result["gate_status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(result["rows"], 2745067)
            self.assertEqual(result["errors"], 0)
            self.assertIn("Next goal step may proceed", result["warning"])
            self.assertEqual(result["next_step_after_ready"], "Run guarded ws-postprocess.")

    def test_ready_listing_history_gate_reports_ohlcv_rows_and_primary_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            run_dir = root / "exports" / "trading-mvp" / "listing-history" / "listing_fixture"
            agent_log.mkdir(parents=True)
            run_dir.mkdir(parents=True)

            output = run_dir / "ohlcv.jsonl"
            output.write_text("{}\n{}\n{}\n", encoding="utf-8")
            manifest = run_dir / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "listing_event_history_collect",
                        "final": True,
                        "decision": "LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY",
                        "ohlcv_rows": 3,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "listing_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "monitor_pid": None,
                        "process_ids": [],
                        "output_path": str(output),
                        "manifest_path": str(manifest),
                        "replay_allowed": False,
                        "next_goal_decision": "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE",
                        "next_step_after_ready": "Await explicit confirmation for public probe.",
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(result["rows"], 3)
            self.assertTrue(result["primary_output_complete"])
            self.assertFalse(result["expected_outputs_complete"])
            self.assertFalse(result["replay_allowed"])
            self.assertIn("replay/grid are blocked", result["warning"])

    def test_rejected_ws_postprocess_gate_blocks_replay_grid_and_exposes_next_collect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            backtests_dir = root / "exports" / "trading-mvp" / "backtests"
            analysis_dir = root / "exports" / "trading-mvp" / "analysis"
            agent_log.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)
            analysis_dir.mkdir(parents=True)

            postprocess = backtests_dir / "ws_postprocess_rejected.json"
            postprocess.write_text(json.dumps({"replay_allowed": False}), encoding="utf-8")
            readiness = analysis_dir / "trading_ws_collect_readiness_current.json"
            readiness.write_text(json.dumps({"ok": True}), encoding="utf-8")
            command = "pwsh -File start_ws_collect_visible.ps1 -Hours 72 -ConfirmedLongRun"
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "ws_postprocess_rejected_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "monitor_pid": None,
                        "process_ids": [],
                        "output_path": str(postprocess),
                        "next_goal_decision": "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL",
                        "next_goal_reason": "Previous ws-postprocess completed but replay_allowed=false.",
                        "next_step_after_ready": "Do not rerun postprocess/replay on the rejected output.",
                        "replay_allowed": False,
                        "requires_explicit_user_approval_for_actual_collect": True,
                        "readiness_output_path": str(readiness),
                        "command_after_explicit_approval": command,
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertFalse(result["replay_allowed"])
            self.assertTrue(result["requires_explicit_user_approval_for_actual_collect"])
            self.assertEqual(
                result["next_goal_decision"],
                "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL",
            )
            self.assertEqual(result["readiness_output_path"], str(readiness))
            self.assertEqual(result["command_after_explicit_approval"], command)
            self.assertIn("replay/grid are blocked", result["warning"])
            self.assertIn("explicit user approval", result["warning"])

    def test_active_run_monitor_is_read_only_for_rejected_ws_postprocess_gate(self) -> None:
        self.assertTrue(MONITOR_SCRIPT.exists())
        shortcut = REPO_ROOT / "TRADING_ACTIVE_RUN_MONITOR.cmd"
        self.assertTrue(shortcut.exists())
        script_text = MONITOR_SCRIPT.read_text(encoding="utf-8")
        shortcut_text = shortcut.read_text(encoding="utf-8")
        for needle in (
            "trading_active_run_monitor",
            "read_only",
            "would_start",
            "postprocess_while_running",
            "replay_or_grid_while_running",
            "new_collector_while_running",
            "do_not_replay_rejected_artifact_start_new_visible_collect_after_explicit_approval",
        ):
            self.assertIn(needle, script_text)
        self.assertIn("trading_active_run_monitor.ps1", shortcut_text)
        self.assertIn("read-only", shortcut_text)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            backtests_dir = root / "exports" / "trading-mvp" / "backtests"
            agent_log.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)

            postprocess = backtests_dir / "ws_postprocess_rejected.json"
            postprocess.write_text(json.dumps({"replay_allowed": False}), encoding="utf-8")
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "ws_postprocess_rejected_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "monitor_pid": None,
                        "process_ids": [],
                        "output_path": str(postprocess),
                        "next_goal_decision": "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL",
                        "replay_allowed": False,
                        "requires_explicit_user_approval_for_actual_collect": True,
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_monitor_once(gate)

            self.assertEqual(result["mode"], "trading_active_run_monitor")
            self.assertTrue(result["read_only"])
            self.assertFalse(result["would_start"])
            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertFalse(result["replay_allowed"])
            self.assertEqual(
                result["next_action"],
                "do_not_replay_rejected_artifact_start_new_visible_collect_after_explicit_approval",
            )
            self.assertIn("postprocess_while_running", result["blocked_actions"])
            self.assertIn("replay_or_grid_while_running", result["blocked_actions"])

    def test_goal_completion_audit_refuses_completion_on_rejected_ws_postprocess(self) -> None:
        self.assertTrue(COMPLETION_AUDIT_SCRIPT.exists())
        shortcut = REPO_ROOT / "TRADING_GOAL_COMPLETION_AUDIT.cmd"
        self.assertTrue(shortcut.exists())
        script_text = COMPLETION_AUDIT_SCRIPT.read_text(encoding="utf-8")
        shortcut_text = shortcut.read_text(encoding="utf-8")
        for needle in (
            "trading_goal_completion_audit",
            "can_mark_goal_complete",
            "accepted_edge_proven",
            "data_quality_replay_allowed",
            "paper_forward_gate",
            "swarm_independent_review",
            "mark_goal_complete_without_all_requirements_passed",
            "START72H",
        ):
            self.assertIn(needle, script_text)
        self.assertIn("trading_goal_completion_audit.ps1", shortcut_text)
        self.assertIn("read-only", shortcut_text)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            backtests_dir = root / "exports" / "trading-mvp" / "backtests"
            agent_log.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)

            postprocess = backtests_dir / "ws_postprocess_rejected.json"
            postprocess.write_text(json.dumps({"replay_allowed": False}), encoding="utf-8")
            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "ws_postprocess_rejected_fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "monitor_pid": None,
                        "process_ids": [],
                        "output_path": str(postprocess),
                        "next_goal_decision": "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL",
                        "replay_allowed": False,
                        "requires_explicit_user_approval_for_actual_collect": True,
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_completion_audit(gate)

            self.assertEqual(result["mode"], "trading_goal_completion_audit")
            self.assertEqual(result["status"], "NOT_COMPLETE")
            self.assertFalse(result["can_mark_goal_complete"])
            self.assertFalse(result["accepted_edge_proven"])
            self.assertFalse(result["would_start"])
            self.assertIn("mark_goal_complete_without_all_requirements_passed", result["blocked_actions"])
            requirements = {item["name"]: item for item in result["requirements"]}
            self.assertEqual(requirements["active_run_gate"]["status"], "pass")
            self.assertEqual(requirements["data_quality_replay_allowed"]["status"], "fail")
            self.assertEqual(requirements["paper_forward_gate"]["status"], "fail")

    def test_running_noexit_validation_gate_opens_when_expected_outputs_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_log = root / "docs" / "agent-log"
            raw_dir = root / "exports" / "trading-mvp" / "raw"
            backtests_dir = root / "exports" / "trading-mvp" / "backtests"
            agent_log.mkdir(parents=True)
            raw_dir.mkdir(parents=True)
            backtests_dir.mkdir(parents=True)

            manifest = raw_dir / "ws_collect_fixture.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "public_ws_collect",
                        "duration_sec": 21600,
                        "total_events": 100,
                        "errors": {},
                    }
                ),
                encoding="utf-8",
            )
            expected_outputs: dict[str, str] = {}
            for name in (
                "event_quality",
                "event_slice",
                "event_validation",
                "ws_grid",
                "sweep_gate",
            ):
                path = backtests_dir / f"{name}.json"
                path.write_text(json.dumps({"ok": True}), encoding="utf-8")
                expected_outputs[name] = str(path)
            validation_summary = backtests_dir / "ws_replay_validation_fixture.json"
            validation_summary.write_text(json.dumps({"ok": True}), encoding="utf-8")
            expected_outputs["validation_summary"] = str(validation_summary)
            expected_outputs["console_log"] = str(backtests_dir / "console.log")

            gate = agent_log / "active-run-gate.json"
            gate.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v1",
                        "project": "trading_mvp",
                        "run_id": "ws_confirmed_research_fixture",
                        "status": "RUNNING",
                        "monitor_pid": os.getpid(),
                        "process_ids": [os.getpid()],
                        "output_path": str(backtests_dir),
                        "manifest_path": str(manifest),
                        "expected_outputs": expected_outputs,
                        "next_step_after_ready": "Review validation artifacts.",
                    }
                ),
                encoding="utf-8",
            )

            result = self._run_gate(gate)

            self.assertEqual(result["status"], "READY_FOR_POSTPROCESS")
            self.assertEqual(result["gate_status"], "RUNNING")
            self.assertTrue(result["monitor_pid_alive"])
            self.assertTrue(result["expected_outputs_complete"])
            self.assertIn("expected output artifacts are complete", result["warning"])


if __name__ == "__main__":
    unittest.main()
