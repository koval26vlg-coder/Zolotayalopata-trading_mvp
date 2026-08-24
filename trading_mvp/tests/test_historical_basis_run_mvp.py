from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_MVP = REPO_ROOT / "trading_mvp" / "run_mvp.ps1"


class HistoricalBasisRunMvpTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("pwsh") is None:
            self.skipTest("PowerShell 7 is required")

    def test_wrapper_exposes_all_seven_basis_actions(self) -> None:
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(RUN_MVP)
        for action in (
            "fast-edge-basis-plan",
            "fast-edge-basis-history-collect",
            "fast-edge-basis-history-quality",
            "fast-edge-basis-evaluate",
            "fast-edge-basis-probe-plan",
            "fast-edge-basis-probe",
            "fast-edge-basis-report",
        ):
            self.assertIn(f'"{action}"', text)
        for module in (
            "historical_basis_edge.py",
            "historical_basis_collector.py",
            "historical_basis_quality.py",
            "historical_basis_evaluator.py",
            "historical_basis_probe.py",
        ):
            self.assertIn(module, text)

    def test_wrapper_exposes_paper_only_oms_actions(self) -> None:
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(RUN_MVP)
        for action in (
            "fast-edge-basis-paper-init",
            "fast-edge-basis-paper-observe",
            "fast-edge-basis-paper-status",
        ):
            self.assertIn(f'"{action}"', text)
        self.assertIn("basis_paper_oms.py", text)

    def test_wrapper_exposes_bounded_universe_availability_builder(self) -> None:
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(RUN_MVP)
        self.assertIn('"fast-edge-basis-universe-build"', text)
        self.assertIn("historical_basis_universe.py", text)
        self.assertIn("MaxRuntimeSec must be <= 600 for fast-edge-basis-universe-build", text)

    def test_full_frozen_pipeline_executes_from_content_addressed_code_snapshot(self) -> None:
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(RUN_MVP)
        self.assertIn("historical_basis_code_snapshot.py", text)
        self.assertIn("New-BasisCodeSnapshot", text)
        self.assertGreaterEqual(text.count("$codeSnapshot = New-BasisCodeSnapshot"), 8)
        for module in (
            "historical_basis_edge.py",
            "historical_basis_collector.py",
            "historical_basis_quality.py",
            "historical_basis_evaluator.py",
            "historical_basis_probe.py",
        ):
            self.assertIn(f'Join-Path $codeSnapshot.snapshot_path "{module}"', text)

    def test_wrapper_plan_smoke_creates_frozen_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe = root / "universe.json"
            output = root / "plan.json"
            snapshot_root = root / "snapshots"
            universe.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "canonical_asset_id": f"asset:a{index}",
                                "base": f"A{index}",
                                "quote": "USDT",
                                "mexc_symbol": f"A{index}_USDT",
                                "gateio_symbol": f"A{index}_USDT",
                                "mexc_status": "trading",
                                "gateio_status": "trading",
                                "common_history_days": 400,
                                "binance_spot": False,
                                "categories": [],
                                "liquidity_rank": index,
                            }
                            for index in range(8)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RUN_MVP),
                    "-Action",
                    "fast-edge-basis-plan",
                    "-InputPath",
                    str(universe),
                    "-OutputPath",
                    str(output),
                    "-MaxRuntimeSec",
                    "60",
                    "-BasisCodeSnapshotRoot",
                    str(snapshot_root),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["hypothesis"]["id"], "cross_venue_perp_basis_convergence_history_v1")
            self.assertEqual(plan["next_allowed_command"], "fast-edge-basis-history-collect")
            self.assertTrue(plan["code_provenance"]["immutable_snapshot"])
            self.assertTrue(Path(plan["code_provenance"]["code_snapshot_manifest"]).exists())


if __name__ == "__main__":
    unittest.main()
