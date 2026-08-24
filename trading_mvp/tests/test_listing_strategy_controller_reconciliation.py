from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "reconcile_listing_strategy_controller.ps1"
LISTING_POINTER_WRITER = (
    REPO_ROOT / "tools" / "start_listing_momentum_forward_tick_visible.ps1"
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ListingStrategyControllerReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gate = self.root / "active-run-gate.json"
        self.pointer = self.root / "current-run.json"
        self.state = self.root / "state.json"
        self.launch = self.root / "launch.json"
        self.receipt = self.root / "receipt.json"
        self.archive = self.root / "archive"
        write_json(
            self.gate,
            {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "resolved_incomplete_fixture",
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "final": True,
                "replay_allowed": False,
                "grid_allowed": False,
                "backtest_allowed": False,
                "paper_forward_allowed": False,
                "monitor_pid": None,
                "collector_pid": None,
                "process_ids": [],
                "updated_at": "2026-08-21T00:00:00Z",
            },
        )
        write_json(
            self.state,
            {
                "schema": "listing_state_v1",
                "tick_count": 13,
                "window_count": 6,
                "complete_window_count": 1,
                "acceptance_decision": "NONE_ACCRUAL_ONLY",
            },
        )
        write_json(
            self.launch,
            {
                "schema": "listing_launch_v1",
                "status": "FAILED",
                "run_id": "stopped_listing_fixture",
                "visible_terminal_pid": 999999,
                "tick_exit_code": 1,
            },
        )
        write_json(
            self.pointer,
            {
                "schema": "active_run_pointer_v1",
                "project": "trading_mvp",
                "run_id": "stopped_listing_fixture",
                "status": "STOPPED_INCOMPLETE",
                "updated_at": "2026-08-21T01:00:00Z",
                "manifest_path": str(self.state),
                "collector_pid": None,
                "monitor_pid": None,
                "process_ids": [],
                "launch_record_path": str(self.launch),
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def invoke(self, *extra: str) -> subprocess.CompletedProcess[str]:
        command = [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-GatePath",
            str(self.gate),
            "-CurrentRunPath",
            str(self.pointer),
            "-ArchiveDir",
            str(self.archive),
            "-ReceiptPath",
            str(self.receipt),
            "-ExpectedStoppedRunId",
            "stopped_listing_fixture",
            "-ExpectedNeutralRunId",
            "resolved_incomplete_fixture",
            "-Json",
            *extra,
        ]
        return subprocess.run(command, text=True, capture_output=True, check=False)

    @staticmethod
    def ps_literal(value: object) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def write_concurrent_winner_hook(self, *, mutate_gate: bool = False) -> Path:
        hook = self.root / (
            "concurrent-winner-mutate-gate.ps1"
            if mutate_gate
            else "concurrent-winner.ps1"
        )
        command = [
            "&",
            self.ps_literal(SCRIPT),
            "-GatePath",
            self.ps_literal(self.gate),
            "-CurrentRunPath",
            self.ps_literal(self.pointer),
            "-ArchiveDir",
            self.ps_literal(self.archive),
            "-ReceiptPath",
            self.ps_literal(self.receipt),
            "-ExpectedStoppedRunId",
            self.ps_literal("stopped_listing_fixture"),
            "-ExpectedNeutralRunId",
            self.ps_literal("resolved_incomplete_fixture"),
            "-Json",
            "|",
            "Out-Null",
        ]
        lines = [" ".join(command)]
        if mutate_gate:
            gate_literal = self.ps_literal(self.gate)
            lines.extend(
                [
                    f"$gateRecord = Get-Content -LiteralPath {gate_literal} -Raw | ConvertFrom-Json",
                    '$gateRecord.updated_at = "2026-08-21T03:00:00Z"',
                    "$gateText = $gateRecord | ConvertTo-Json -Depth 20",
                    "[System.IO.File]::WriteAllText(",
                    f"    {gate_literal},",
                    "    $gateText + [Environment]::NewLine,",
                    "    [System.Text.UTF8Encoding]::new($false)",
                    ")",
                ]
            )
        hook.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return hook

    def write_post_snapshot_pointer_writer_hook(
        self,
    ) -> tuple[Path, Path, Path, dict]:
        payload_path = self.root / "post-snapshot-live-pointer.json"
        ready_path = self.root / "post-snapshot-writer.ready"
        done_path = self.root / "post-snapshot-writer.done"
        pid_path = self.root / "post-snapshot-writer.pid"
        replacement = {
            "schema": "active_run_pointer_v1",
            "project": "trading_mvp",
            "run_id": "new_live_listing_after_final_snapshot",
            "status": "RUNNING",
            "updated_at": "2026-08-21T04:00:00Z",
            "collector_pid": None,
            "monitor_pid": os.getpid(),
            "process_ids": [os.getpid()],
        }
        payload_path.write_text(json.dumps(replacement), encoding="utf-8")
        hook = self.root / "post-final-snapshot-pointer-writer.ps1"
        arguments = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LISTING_POINTER_WRITER),
            "-CurrentRunPointerTestOnly",
            "-CurrentRunPointerPathOverride",
            str(self.pointer),
            "-CurrentRunPointerPayloadPath",
            str(payload_path),
            "-CurrentRunPointerReadyPath",
            str(ready_path),
            "-CurrentRunPointerDonePath",
            str(done_path),
        ]
        argument_lines = "\n".join(
            f"$startInfo.ArgumentList.Add({self.ps_literal(argument)})"
            for argument in arguments
        )
        hook.write_text(
            "$startInfo = [System.Diagnostics.ProcessStartInfo]::new()\n"
            "$startInfo.FileName = (Get-Process -Id $PID).Path\n"
            "$startInfo.UseShellExecute = $false\n"
            "$startInfo.CreateNoWindow = $true\n"
            "$startInfo.RedirectStandardOutput = $true\n"
            "$startInfo.RedirectStandardError = $true\n"
            f"{argument_lines}\n"
            "$writer = [System.Diagnostics.Process]::Start($startInfo)\n"
            "[System.IO.File]::WriteAllText(\n"
            f"    {self.ps_literal(pid_path)},\n"
            "    [string]$writer.Id,\n"
            "    [System.Text.UTF8Encoding]::new($false)\n"
            ")\n"
            "$deadline = [DateTimeOffset]::UtcNow.AddSeconds(5)\n"
            f"while (-not (Test-Path -LiteralPath {self.ps_literal(ready_path)})) {{\n"
            "    if ($writer.HasExited) {\n"
            "        throw ('pointer writer exited before ready: ' + $writer.StandardError.ReadToEnd())\n"
            "    }\n"
            "    if ([DateTimeOffset]::UtcNow -ge $deadline) {\n"
            "        throw 'pointer writer did not reach transaction boundary'\n"
            "    }\n"
            "    Start-Sleep -Milliseconds 10\n"
            "}\n"
            "Start-Sleep -Milliseconds 200\n",
            encoding="utf-8",
        )
        return hook, ready_path, done_path, replacement

    def test_planonly_is_read_only_and_reports_exact_disposition(self) -> None:
        before = self.pointer.read_bytes()
        result = self.invoke("-PlanOnly")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "RECONCILIATION_PLAN_VALID")
        self.assertEqual(payload["accrual_counts"]["tick_count"], 13)
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.pointer.read_bytes(), before)

    def test_apply_archives_stopped_pointer_and_points_to_neutral_gate(self) -> None:
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "RECONCILED")
        self.assertTrue(self.receipt.is_file())
        archived = list(self.archive.glob("current-run.stopped_listing_fixture.*.json"))
        self.assertEqual(len(archived), 1)
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        self.assertEqual(pointer["run_id"], "resolved_incomplete_fixture")
        self.assertEqual(pointer["status"], "READY_FOR_POSTPROCESS")
        self.assertNotIn("launch_record_path", pointer)
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["disposition"], "INCOMPLETE_ATTEMPT_REJECTED_ACCRUAL_PRESERVED")
        self.assertFalse(receipt["acceptance_authorized"])
        self.assertFalse(receipt["runtime_activated"])
        repeated = self.invoke()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_payload = json.loads(repeated.stdout)
        self.assertEqual(repeated_payload["status"], "RECONCILIATION_REUSED")
        self.assertEqual(
            repeated_payload["deterministic_result_hash"],
            payload["deterministic_result_hash"],
        )
        self.assertEqual(
            repeated_payload["deterministic_result_hash"],
            receipt["deterministic_result_hash"],
        )
        self.assertEqual(
            len(list(self.archive.glob("current-run.stopped_listing_fixture.*.json"))),
            1,
        )

    def test_live_declared_process_fails_closed_without_writes(self) -> None:
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        pointer["process_ids"] = [1]
        write_json(self.pointer, pointer)
        before = self.pointer.read_bytes()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declares process identity", result.stderr)
        self.assertEqual(self.pointer.read_bytes(), before)
        self.assertFalse(self.receipt.exists())

    def test_pointer_substitution_before_commit_fails_closed_without_controller_writes(self) -> None:
        replacement = {
            "schema": "active_run_pointer_v1",
            "project": "trading_mvp",
            "run_id": "new_live_listing_fixture",
            "status": "RUNNING",
            "updated_at": "2026-08-21T02:00:00Z",
            "collector_pid": os.getpid(),
            "monitor_pid": None,
            "process_ids": [os.getpid()],
        }
        replacement_text = json.dumps(replacement, indent=2) + "\n"
        hook = self.root / "substitute-pointer.ps1"
        pointer_literal = str(self.pointer).replace("'", "''")
        payload_literal = replacement_text.replace("'", "''")
        hook.write_text(
            "[System.IO.File]::WriteAllText(\n"
            f"    '{pointer_literal}',\n"
            f"    '{payload_literal}',\n"
            "    [System.Text.UTF8Encoding]::new($false)\n"
            ")\n",
            encoding="utf-8",
        )

        gate_before = self.gate.read_bytes()
        result = self.invoke("-BeforeCommitTestHookPath", str(hook))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Controller inputs changed during reconciliation", result.stderr)
        self.assertEqual(self.gate.read_bytes(), gate_before)
        self.assertEqual(
            json.loads(self.pointer.read_text(encoding="utf-8")), replacement
        )
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.archive.exists())

    def test_concurrent_reconciliation_winner_is_reused_without_duplicate_archive(self) -> None:
        hook = self.write_concurrent_winner_hook()

        result = self.invoke("-BeforeCommitTestHookPath", str(hook))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "RECONCILIATION_REUSED")
        self.assertFalse(payload["pointer_updated"])
        self.assertEqual(
            len(list(self.archive.glob("current-run.stopped_listing_fixture.*.json"))),
            1,
        )

    def test_gate_sha_change_is_not_hidden_by_concurrent_reuse(self) -> None:
        hook = self.write_concurrent_winner_hook(mutate_gate=True)

        result = self.invoke("-BeforeCommitTestHookPath", str(hook))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Controller inputs changed during reconciliation", result.stderr)
        self.assertTrue(self.receipt.is_file())
        self.assertEqual(
            len(list(self.archive.glob("current-run.stopped_listing_fixture.*.json"))),
            1,
        )
        pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
        self.assertEqual(pointer["run_id"], "resolved_incomplete_fixture")

    def test_after_final_snapshot_test_hook_runs_before_controller_mutation(self) -> None:
        marker = self.root / "after-final-snapshot.marker"
        marker_literal = self.ps_literal(marker)
        hook = self.root / "after-final-snapshot-marker.ps1"
        hook.write_text(
            "[System.IO.File]::WriteAllText(\n"
            f"    {marker_literal},\n"
            "    'HOOK_RAN',\n"
            "    [System.Text.UTF8Encoding]::new($false)\n"
            ")\n",
            encoding="utf-8",
        )

        result = self.invoke("-AfterFinalSnapshotTestHookPath", str(hook))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="utf-8"), "HOOK_RAN")

    def test_post_snapshot_listing_writer_is_not_overwritten_by_reconciliation(self) -> None:
        hook, ready_path, done_path, replacement = (
            self.write_post_snapshot_pointer_writer_hook()
        )

        result = self.invoke("-AfterFinalSnapshotTestHookPath", str(hook))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(ready_path.is_file())
        deadline = time.monotonic() + 5
        while not done_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(done_path.is_file(), "pointer writer did not complete")
        self.assertEqual(
            json.loads(self.pointer.read_text(encoding="utf-8-sig")), replacement
        )
        archived = list(
            self.archive.glob("current-run.stopped_listing_fixture.*.json")
        )
        self.assertEqual(len(archived), 1)
        archived_pointer = json.loads(archived[0].read_text(encoding="utf-8-sig"))
        self.assertEqual(archived_pointer["run_id"], "stopped_listing_fixture")


if __name__ == "__main__":
    unittest.main()
