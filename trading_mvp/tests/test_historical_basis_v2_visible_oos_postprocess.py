from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "start_historical_basis_v2_oos_postprocess_visible.ps1"


class HistoricalBasisV2VisibleOosPostprocessTests(unittest.TestCase):
    def test_script_has_visible_bounded_hash_bound_guards(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[ValidateRange(1, 1800)][int]$MaxRuntimeSec", text)
        self.assertIn("Start-Process", text)
        self.assertIn("-WindowStyle Normal", text)
        self.assertNotIn("-WindowStyle Hidden", text)
        self.assertIn('$env:PYTHONUNBUFFERED = "1"', text)
        self.assertIn("WaitForExit", text)
        self.assertIn("[switch]$PlanOnly", text)
        self.assertIn("--plan-only", text)
        self.assertIn("fast-edge-basis-v2-oos-postprocess", text)
        self.assertIn("STOPPED_INCOMPLETE", text)
        self.assertNotIn("ConfirmedPublicHistoryCollect", text)

    def test_planonly_is_read_only_and_does_not_open_oos(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is required")
        from trading_mvp.tests.test_historical_basis_v2_oos_postprocess import _fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)
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
            output_root = root / "oos-postprocess"
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
                    "-TrainPostprocessManifestPath",
                    str(train_manifest),
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

            self.assertEqual(preview["decision"], "READY_FOR_VISIBLE_OOS_POSTPROCESS")
            self.assertFalse(preview["network_access"])
            self.assertFalse(preview["oos_read"])
            self.assertFalse(preview["full_evaluation"])
            self.assertFalse(output_root.exists())
            self.assertFalse(launch_record.exists())


if __name__ == "__main__":
    unittest.main()
