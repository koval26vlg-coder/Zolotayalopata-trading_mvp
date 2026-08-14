from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_MVP = REPO_ROOT / "trading_mvp" / "run_mvp.ps1"
DAY_SEC = 86_400


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


class HistoricalBasisV2RunMvpTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("pwsh") is None:
            self.skipTest("PowerShell 7 is required")

    def test_wrapper_exposes_v2_actions_and_modules_through_execution_probe(self) -> None:
        text = RUN_MVP.read_text(encoding="utf-8")
        for action in (
            "fast-edge-basis-v2-preflight",
            "fast-edge-basis-v2-plan",
            "fast-edge-basis-v2-cache-audit",
            "fast-edge-basis-v2-history-collect",
            "fast-edge-basis-v2-history-quality",
            "fast-edge-basis-v2-train-postprocess",
            "fast-edge-basis-v2-oos-postprocess",
            "fast-edge-basis-v2-evaluate",
            "fast-edge-basis-v2-report",
            "fast-edge-basis-v2-execution-probe-plan",
            "fast-edge-basis-v2-execution-probe",
            "fast-edge-basis-v2-execution-probe-evaluate",
            "fast-edge-basis-v2-paper-plan",
            "fast-edge-basis-v2-paper-init",
            "fast-edge-basis-v2-paper-observe",
            "fast-edge-basis-v2-paper-status",
        ):
            self.assertIn(f'"{action}"', text)
        for module in (
            "historical_basis_v2_preflight.py",
            "historical_basis_v2.py",
            "historical_basis_v2_collector.py",
            "historical_basis_v2_quality.py",
            "historical_basis_v2_postprocess.py",
            "historical_basis_v2_oos_postprocess.py",
            "historical_basis_v2_evaluator.py",
            "historical_basis_v2_report.py",
            "historical_basis_v2_execution_probe.py",
            "historical_basis_v2_paper_oms.py",
        ):
            self.assertIn(module, text)
            self.assertIn(f'Join-Path $codeSnapshot.snapshot_path "{module}"', text)
        self.assertIn("audit_historical_basis_v2_cache.py", text)

    def test_wrapper_enforces_runtime_and_separate_funding_output(self) -> None:
        text = RUN_MVP.read_text(encoding="utf-8")
        self.assertIn("MaxRuntimeSec must be <= 5400 for fast-edge-basis-v2-history-collect", text)
        self.assertIn("FundingOutputPath is required for v2 funding events JSONL", text)
        self.assertIn('"--funding-output", $FundingOutputPath', text)
        self.assertIn('"--stage", $PitPlanStage', text)
        self.assertIn("FeasibilityPath is required for v2 full_evaluation", text)
        self.assertIn("MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-train-postprocess", text)
        self.assertIn('"--collector-manifest", $ManifestPath', text)
        self.assertIn('"--output-root", $OutputPath', text)
        self.assertIn("MaxRuntimeSec must be <= 1800 for fast-edge-basis-v2-oos-postprocess", text)
        self.assertIn('"--train-postprocess-manifest", $ManifestPath', text)
        self.assertIn(
            "MaxRuntimeSec must be in [1200, 1800] for fast-edge-basis-v2-execution-probe",
            text,
        )
        self.assertIn(
            "MaxRuntimeSec must be <= 600 for fast-edge-basis-v2-execution-probe-plan",
            text,
        )
        self.assertIn('@("--run-id", $RunId)', text)
        self.assertIn(
            "InputPath is required for fast-edge-basis-v2-cache-audit cache root",
            text,
        )
        self.assertIn('$basisOutputRoot = $InputPath', text)
        self.assertIn('"--report-output", $OutputPath', text)
        self.assertIn('Exactly one of EvaluationPath or ClosurePath is required', text)
        self.assertIn('@("--closure-manifest", $ClosurePath)', text)
        self.assertIn('$EvaluationPath, $ClosurePath, $ProbePlanPath', text)

    def test_report_action_accepts_hash_bound_quality_closure_without_oos(self) -> None:
        from trading_mvp.tests.test_historical_basis_v2_report import _quality_reject_closure

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_manifest = _quality_reject_closure(root / "fixture")
            output = root / "terminal-report.json"
            snapshot_root = root / "snapshots"
            gate_path = root / "active-run-gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "status": "READY_FOR_POSTPROCESS",
                        "gate_status": "READY_FOR_POSTPROCESS",
                        "run_id": "fixture-gate",
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
                    "fast-edge-basis-v2-report",
                    "-ClosurePath",
                    str(closure_manifest),
                    "-OutputPath",
                    str(output),
                    "-ActiveRunGatePath",
                    str(gate_path),
                    "-BasisCodeSnapshotRoot",
                    str(snapshot_root),
                    "-MaxRuntimeSec",
                    "60",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "TERMINAL_PRE_OOS_QUALITY_VERDICT")
            self.assertEqual(report["verdict"], "INSUFFICIENT_EXECUTABLE_UNIVERSE")
            self.assertFalse(report["data_access_audit"]["oos_read"])
            self.assertTrue(any(snapshot_root.iterdir()))

    def test_wrapper_plan_smoke_uses_content_addressed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / "preflight.json"
            output = root / "plan.json"
            snapshot_root = root / "snapshots"
            payload: dict[str, object] = {
                "schema": "trading_mvp_historical_basis_v2_preflight_v2",
                "verdict": "PREFLIGHT_ACCEPTED_NOT_COLLECTED",
                "window": {
                    "window_start_sec": 0,
                    "window_end_sec": 179 * DAY_SEC,
                    "expected_candle_rows": 179 * 24,
                    "interval": "[start,end)",
                },
                "universe": {
                    "candidate_count": 8,
                    "candidates": [_asset(index) for index in range(8)],
                },
                "data_access_audit": {
                    "returns_read": False,
                    "pnl_read": False,
                    "signals_read": False,
                    "oos_metrics_read": False,
                    "liquidity_used_for_selection": False,
                },
            }
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            import hashlib

            payload["preflight_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            preflight.write_text(json.dumps(payload), encoding="utf-8")

            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RUN_MVP),
                    "-Action",
                    "fast-edge-basis-v2-plan",
                    "-InputPath",
                    str(preflight),
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
            self.assertEqual(
                plan["hypothesis"]["id"],
                "cross_venue_perp_basis_convergence_1h_v2",
            )
            self.assertEqual(plan["next_allowed_command"], "fast-edge-basis-v2-history-collect")
            self.assertTrue(plan["code_provenance"]["immutable_snapshot"])
            self.assertTrue(Path(plan["code_provenance"]["code_snapshot_manifest"]).is_file())

    def test_oos_postprocess_planonly_uses_snapshot_without_outputs(self) -> None:
        from trading_mvp.tests.test_historical_basis_v2_oos_postprocess import _fixture

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)
            output_root = root / "oos-postprocess"
            snapshot_root = root / "snapshots"
            gate_path = root / "active-run-gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "status": "READY_FOR_POSTPROCESS",
                        "gate_status": "READY_FOR_POSTPROCESS",
                        "run_id": "fixture-gate",
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
                    "fast-edge-basis-v2-oos-postprocess",
                    "-PlanPath",
                    str(plan_path),
                    "-ExpectedPlanHash",
                    str(plan["plan_hash"]),
                    "-ManifestPath",
                    str(train_manifest),
                    "-OutputPath",
                    str(output_root),
                    "-ActiveRunGatePath",
                    str(gate_path),
                    "-MaxRuntimeSec",
                    "60",
                    "-BasisCodeSnapshotRoot",
                    str(snapshot_root),
                    "-PlanOnly",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            json_lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
            self.assertTrue(json_lines, completed.stdout)
            preview = json.loads(json_lines[-1])
            self.assertEqual(preview["decision"], "READY_FOR_VISIBLE_OOS_POSTPROCESS")
            self.assertFalse(preview["oos_read"])
            self.assertFalse(output_root.exists())
            self.assertTrue(any(snapshot_root.iterdir()))

    def test_paper_plan_action_smoke_uses_snapshot_and_ready_probe_report(self) -> None:
        from trading_mvp.tests.test_historical_basis_v2_paper_oms import _write_probe_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _report, report_path = _write_probe_report(root / "fixture")
            output = root / "paper-plan.json"
            snapshot_root = root / "snapshots"
            gate_path = root / "active-run-gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "schema": "active_run_gate_v2",
                        "project": "trading_mvp",
                        "status": "READY_FOR_POSTPROCESS",
                        "gate_status": "READY_FOR_POSTPROCESS",
                        "run_id": "fixture-gate",
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
                    "fast-edge-basis-v2-paper-plan",
                    "-InputPath",
                    str(report_path),
                    "-OutputPath",
                    str(output),
                    "-ActiveRunGatePath",
                    str(gate_path),
                    "-BasisCodeSnapshotRoot",
                    str(snapshot_root),
                    "-MaxRuntimeSec",
                    "60",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["schema"], "trading_mvp_historical_basis_v2_paper_plan_v1")
            self.assertEqual(plan["next_allowed_command"], "fast-edge-basis-v2-paper-init")
            self.assertFalse(plan["safety"]["live_orders"])


if __name__ == "__main__":
    unittest.main()
