from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from trading_mvp.tests.test_historical_basis_v2_execution_probe import (
    _write_evaluation,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "start_historical_basis_v2_execution_probe_visible.ps1"


class HistoricalBasisV2ExecutionProbeVisibleTests(unittest.TestCase):
    def test_planonly_is_read_only_and_emits_exact_owned_launch_contract(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        self.assertTrue(SCRIPT.is_file(), f"missing visible execution-probe wrapper: {SCRIPT}")
        from historical_basis_v2_execution_probe import build_execution_probe_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            plan_path = root / "probe-plan.json"
            plan = build_execution_probe_plan(
                evaluation_path,
                plan_path,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )
            gate = root / "active-run-gate.json"
            current = root / "current-run.json"
            gate_payload = {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": "previous",
                "status": "READY_FOR_POSTPROCESS",
                "gate_status": "READY_FOR_POSTPROCESS",
                "final": True,
            }
            gate.write_text(json.dumps(gate_payload), encoding="utf-8")
            current.write_text(json.dumps(gate_payload), encoding="utf-8")
            gate_hash = hashlib.sha256(gate.read_bytes()).hexdigest()
            current_hash = hashlib.sha256(current.read_bytes()).hexdigest()
            output_root = root / "probe-output"

            command = [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-PlanPath",
                str(plan_path),
                "-ExpectedPlanHash",
                str(plan["probe_plan_hash"]),
                "-WindowIndex",
                "0",
                "-RunId",
                "basis-v2-probe-visible-fixture",
                "-OutputRoot",
                str(output_root),
                "-GatePath",
                str(gate),
                "-CurrentRunPath",
                str(current),
                "-LaunchRecordPath",
                str(root / "launch.json"),
                "-HoldOpenSec",
                "0",
                "-PlanOnly",
            ]
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            preview = json.loads(completed.stdout)
            self.assertEqual(preview["decision"], "AWAIT_EXPLICIT_BASIS_V2_EXECUTION_PROBE_APPROVAL")
            self.assertEqual(preview["probe_plan_hash"], plan["probe_plan_hash"])
            self.assertEqual(preview["window_index"], 0)
            self.assertEqual(preview["duration_sec"], 1200)
            self.assertEqual(preview["interval_sec"], 5)
            self.assertTrue(preview["visible_terminal_required"])
            self.assertFalse(preview["network_access"])
            self.assertFalse(preview["collector_started"])
            self.assertFalse(preview["live_orders"])
            self.assertFalse(preview["private_api_keys"])
            self.assertIn("ConfirmedExecutionProbe", preview["approval_command"])
            self.assertIn(str(plan["probe_plan_hash"]), preview["approval_phrase"])
            self.assertFalse(output_root.exists())
            self.assertFalse((root / "launch.json").exists())
            self.assertEqual(hashlib.sha256(gate.read_bytes()).hexdigest(), gate_hash)
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), current_hash)

    def test_actual_launch_requires_confirmation_and_source_is_never_hidden(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ConfirmedExecutionProbe", source)
        self.assertIn("Start-Process", source)
        self.assertIn("-WindowStyle Normal", source)
        self.assertNotIn("-WindowStyle Hidden", source)
        self.assertIn('$env:PYTHONUNBUFFERED = "1"', source)
        self.assertIn("STOPPED_INCOMPLETE", source)
        self.assertIn("worker_pid", source)
        self.assertIn("samples_path", source)
        self.assertIn("manifest_path", source)
        self.assertNotIn("live orders", source.lower())


if __name__ == "__main__":
    unittest.main()
