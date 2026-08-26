from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2 import DAY_SEC, build_historical_basis_v2_plan  # noqa: E402
from historical_basis_v2_collector import SCHEMA as COLLECTOR_SCHEMA  # noqa: E402


SCRIPT = REPO_ROOT / "tools" / "start_historical_basis_v2_train_postprocess_visible.ps1"


def _asset(index: int) -> dict[str, object]:
    base = f"A{index:02d}"
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": 179,
        "binance_spot": False,
        "categories": [],
        "availability_rank": index,
    }


class HistoricalBasisV2VisiblePostprocessTests(unittest.TestCase):
    def test_script_has_visible_bounded_train_only_guards(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[ValidateRange(1, 1800)][int]$MaxRuntimeSec", text)
        self.assertIn("Start-Process", text)
        self.assertIn("-WindowStyle Normal", text)
        self.assertNotIn("-WindowStyle Hidden", text)
        self.assertIn("$env:PYTHONUNBUFFERED = \"1\"", text)
        self.assertIn("WaitForExit", text)
        self.assertIn("[switch]$PlanOnly", text)
        self.assertIn("--plan-only", text)
        self.assertIn("fast-edge-basis-v2-train-postprocess", text)
        self.assertNotIn("full_evaluation", text)
        self.assertIn("STOPPED_INCOMPLETE", text)
        self.assertIn('(Join-Path $ProjectRoot "trading_mvp\\.venv\\Scripts\\python.exe")', text)
        self.assertIn('"C:\\Users\\koval\\Documents\\ОК.ру\\.venv\\Scripts\\python.exe"', text)
        self.assertIn('"import requests"', text)
        self.assertIn('$env:TRADING_MVP_PYTHON = $python', text)

    def test_preview_runs_from_hash_bound_snapshot_when_plan_is_frozen(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$provenance = $plan.code_provenance", text)
        self.assertIn("$provenance.immutable_snapshot -eq $true", text)
        self.assertIn("$provenance.code_snapshot_manifest", text)
        self.assertIn("$snapshotManifest.code_snapshot_hash", text)
        self.assertIn('"historical_basis_v2_postprocess.py"', text)

    def test_planonly_is_read_only_and_reports_no_oos(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = build_historical_basis_v2_plan(
                [_asset(index) for index in range(8)],
                output_path=plan_path,
                window_end_ts=179 * DAY_SEC,
                frozen_at_utc="2026-07-16T00:00:00+00:00",
            )
            manifest_path = root / "collector-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": COLLECTOR_SCHEMA,
                        "run_id": "basis-v2-visible-fixture",
                        "status": "READY_FOR_POSTPROCESS",
                        "final": True,
                        "plan_hash": plan["plan_hash"],
                        "expected_plan_hash": plan["plan_hash"],
                        "expected_items": 144,
                        "completed_items": 144,
                        "error_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            gate_path = root / "active-run-gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "status": "READY_FOR_POSTPROCESS",
                        "gate_status": "READY_FOR_POSTPROCESS",
                        "run_id": "fixture-gate",
                    }
                ),
                encoding="utf-8",
            )
            output_root = root / "postprocess"
            launch_record = root / "launch.json"
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPT),
                    "-PlanPath",
                    str(plan_path),
                    "-ExpectedPlanHash",
                    str(plan["plan_hash"]),
                    "-CollectorManifestPath",
                    str(manifest_path),
                    "-OutputRoot",
                    str(output_root),
                    "-GatePath",
                    str(gate_path),
                    "-LaunchRecordPath",
                    str(launch_record),
                    "-MaxRuntimeSec",
                    "60",
                    "-PlanOnly",
                ],
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            preview = json.loads(completed.stdout)

            self.assertEqual(preview["decision"], "READY_FOR_VISIBLE_TRAIN_POSTPROCESS")
            self.assertFalse(preview["network_access"])
            self.assertFalse(preview["oos_read"])
            self.assertFalse(preview["full_evaluation"])
            self.assertTrue(Path(preview["python_runtime"]).is_file())
            self.assertFalse(output_root.exists())
            self.assertFalse(launch_record.exists())


if __name__ == "__main__":
    unittest.main()
