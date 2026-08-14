from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_recollect_control_plane import (  # noqa: E402
    build_approval_bundle,
    canonical_json_hash,
    expected_approval_text,
)


SOURCE_RUNNER = ROOT / "tools" / "run_exact_slow_liquidity_recollect_quality.ps1"
SOURCE_CONTROL_PLANE = SRC / "slow_liquidity_recollect_control_plane.py"
PWSH = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class SlowLiquidityRecollectQualityRunnerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        if not PWSH.is_file():
            self.skipTest("PowerShell 7 is not available")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "fixture repo"
        self.tools = self.root / "tools"
        self.plans = self.root / "docs" / "plans"
        self.agent_log = self.root / "docs" / "agent-log"
        self.src = self.root / "trading_mvp" / "src"
        self.output_dir = self.root / "run-output"
        self.analysis_dir = self.root / "analysis"
        self.runner = self.tools / SOURCE_RUNNER.name
        self.control_plane = self.src / SOURCE_CONTROL_PLANE.name
        self.quality_wrapper = (
            self.tools / "trading_slow_liquidity_history_data_quality.ps1"
        )
        self.guard = self.tools / "check_trading_mvp_autopilot.ps1"
        self.policy_path = self.plans / "trading-mvp-autopilot-policy-v1.json"
        self.gate_path = self.agent_log / "active-run-gate.json"
        self.current_run_path = self.agent_log / "current-run.json"
        self.receipt_path = self.agent_log / "approvals" / "approval.json"
        self.launch_path = self.agent_log / "run-gates" / "launch.json"
        self.manifest_path = self.output_dir / "manifest.json"
        self.output_path = self.output_dir / "ohlcv.jsonl"
        self.quality_path = self.analysis_dir / "quality.json"
        self.universe_path = self.plans / "universe.csv"
        self.plan_path = self.plans / "plan.json"

        self.tools.mkdir(parents=True)
        self.plans.mkdir(parents=True)
        self.agent_log.mkdir(parents=True)
        self.src.mkdir(parents=True)
        self.output_dir.mkdir(parents=True)
        shutil.copy2(SOURCE_RUNNER, self.runner)
        shutil.copy2(SOURCE_CONTROL_PLANE, self.control_plane)
        self.universe_path.write_text(
            "base,quote\n" + "\n".join(f"{base},USDT" for base in self.bases) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        self._write_fake_quality_wrapper()
        self._write_fake_guard()
        self.plan, self.plan_hash, self.plan_file_sha256 = self._write_plan()
        self.receipt_sha256 = self._write_approved_completed_context()
        self.original_gate = self.gate_path.read_bytes()
        self.original_pointer = self.current_run_path.read_bytes()

    @property
    def bases(self) -> list[str]:
        return ["STETH", "WEETH", "CC", "OKB", "RAIN", "MNT", "USDD", "BDX", "EDGE"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fake_quality_wrapper(self) -> None:
        self.quality_wrapper.write_text(
            r'''param(
    [string]$InputJsonl,
    [string]$ManifestPath,
    [string]$OutputPath,
    [int]$MinOkRows,
    [int]$MinOkBases,
    [int]$MinOkExchanges,
    [int]$MinOkMarketGranularitySlots,
    [double]$MinOkSlotFraction,
    [double]$MaxApiErrorSlotRate,
    [int]$MinTwoExchangeBases,
    [int]$MinTwoExchangeFullCoverage1h4hBases,
    [double]$MinFullCoverageRatio,
    [switch]$RequireOfficialIdentityAfterQuality,
    [int]$MaxDuplicateCandles,
    [switch]$Json
)
$fixtureRoot = Split-Path -Parent $PSScriptRoot
$forceReject = Test-Path -LiteralPath (Join-Path $fixtureRoot '.force-quality-reject')
$accepted = -not $forceReject
$decision = if ($accepted) {
    'SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL'
} else {
    'SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE'
}
$reasons = if ($accepted) { @() } else { @('fixture_reject') }
$result = [ordered]@{
    mode = 'slow_liquidity_history_data_quality'
    decision = $decision
    accepted = $accepted
    fixed_signal_plan_allowed = $false
    normalizer_allowed = $false
    replay_allowed = $false
    grid_allowed = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    identity_verification_required = $accepted
    identity_verification_authorized = $false
    reasons = $reasons
    warnings = @()
    config = [ordered]@{
        min_ok_rows = $MinOkRows
        min_ok_bases = $MinOkBases
        min_ok_exchanges = $MinOkExchanges
        min_ok_market_granularity_slots = $MinOkMarketGranularitySlots
        min_ok_slot_fraction = $MinOkSlotFraction
        max_api_error_slot_rate = $MaxApiErrorSlotRate
        min_two_exchange_bases = $MinTwoExchangeBases
        min_two_exchange_full_coverage_1h4h_bases = $MinTwoExchangeFullCoverage1h4hBases
        min_full_coverage_ratio = $MinFullCoverageRatio
        max_duplicate_candles = $MaxDuplicateCandles
    }
    metrics = [ordered]@{
        ok_rows = 30000
        ok_bases = 9
        ok_exchanges = 2
        ok_market_granularity_slots = 36
        two_exchange_bases = 9
        two_exchange_full_coverage_1h4h_bases = 9
    }
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding utf8
if (Test-Path -LiteralPath (Join-Path $fixtureRoot '.mutate-manifest-during-quality')) {
    Add-Content -LiteralPath $ManifestPath -Value ' ' -Encoding utf8
}
if (Test-Path -LiteralPath (Join-Path $fixtureRoot '.mutate-output-during-quality')) {
    Add-Content -LiteralPath $InputJsonl -Value '{"data_status":"late_tamper"}' -Encoding utf8
}
$result | ConvertTo-Json -Depth 10
''',
            encoding="utf-8",
            newline="\n",
        )

    def _write_fake_guard(self) -> None:
        self.guard.write_text(
            r'''param([switch]$Json)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$policyPath = Join-Path $root 'docs/plans/trading-mvp-autopilot-policy-v1.json'
$gatePath = Join-Path $root 'docs/agent-log/active-run-gate.json'
$policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json -Depth 100
$gate = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json -Depth 100
[ordered]@{
    status = 'ACTIVE'
    stop_new_actions = $false
    policy_id = [string]$policy.policy_id
    policy_hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $policyPath).Hash.ToLowerInvariant()
    usage = [ordered]@{
        status = 'AVAILABLE'
        remaining_percent = 100.0
        event_age_sec = 0.0
        decision = 'CONTINUE'
    }
    gate = $gate
} | ConvertTo-Json -Depth 30
''',
            encoding="utf-8",
            newline="\n",
        )

    def _write_plan(self) -> tuple[dict[str, object], str, str]:
        run_id = "slow_liquidity_history_recollect_20260813_pagecap_provenance_slotintegrity_v6"
        plan: dict[str, object] = {
            "schema": "trading_mvp_slow_liquidity_history_recollect_planonly_v1",
            "plan_id": run_id,
            "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
            "actual_collection_allowed": False,
            "approval_request": {
                "exact_user_text_template": (
                    "Разрешаю exact recollect по plan_hash=<PLAN_HASH> и "
                    "plan_file_sha256=<PLAN_FILE_SHA256>."
                )
            },
            "approval_receipt": {
                "path": str(self.receipt_path),
                "status": "NOT_CREATED",
                "single_use": True,
                "stopped_incomplete_retry_authorized": False,
            },
            "universe": {
                "path": str(self.universe_path),
                "sha256": sha256(self.universe_path),
                "quote": "USDT",
                "bases": self.bases,
            },
            "implementation": {
                "files": [
                    {
                        "role": "approval_control_plane",
                        "path": str(self.control_plane),
                        "sha256": sha256(self.control_plane),
                    },
                    {
                        "role": "exact_quality_runner",
                        "path": str(self.runner),
                        "sha256": sha256(self.runner),
                    },
                    {
                        "role": "data_quality_wrapper",
                        "path": str(self.quality_wrapper),
                        "sha256": sha256(self.quality_wrapper),
                    },
                ]
            },
            "execution": {
                "run_id": run_id,
                "output_path": str(self.output_dir),
                "output_jsonl": str(self.output_path),
                "manifest_path": str(self.manifest_path),
                "launch_record_path": str(self.launch_path),
                "history_days": 56,
                "target_bases": 9,
                "candles_per_request": 1000,
                "logical_requests": 63,
                "maximum_http_attempts": 126,
                "max_runtime_sec": 900,
                "hard_output_cap_bytes": 100_000_000,
                "single_use": True,
                "resume_allowed": False,
                "stopped_incomplete_retry_authorized": False,
                "exchanges": ["mexc", "gateio"],
                "timeframes": ["1h", "4h"],
            },
            "data_quality_after_success": {
                "output_path": str(self.quality_path),
                "exact_runner_sha256": sha256(self.runner),
                "pass_disposition": (
                    "READY_FOR_SEPARATE_OFFICIAL_IDENTITY_VERIFICATION_ONLY"
                ),
                "reject_disposition": (
                    "TERMINAL_DATA_QUALITY_REJECT_NO_RETRY_WITHOUT_NEW_EXACT_APPROVAL"
                ),
                "evaluator_or_oos_authorized": False,
                "official_identity_verification_authorized_by_this_plan": False,
                "fixed_signal_plan_allowed_before_identity_verification": False,
                "direct_generic_wrapper_actual_allowed": False,
                "thresholds": {
                    "min_ok_rows": 25_000,
                    "min_ok_bases": 8,
                    "min_ok_exchanges": 2,
                    "min_ok_market_granularity_slots": 32,
                    "min_ok_slot_fraction": 0.8,
                    "max_api_error_slot_rate": 0.2,
                    "min_two_exchange_bases": 8,
                    "min_two_exchange_full_coverage_1h4h_bases": 8,
                    "min_full_coverage_ratio": 0.8,
                    "duplicate_candles": 0,
                },
            },
            "guard_contract": {
                "preapproval_decision": (
                    "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE"
                ),
                "required_decision_after_approval": (
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6"
                ),
                "required_policy_rebind_status": (
                    "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
                ),
            },
            "commands": {"data_quality_after_complete_runner": str(self.runner)},
            "forbidden": ["evaluator", "OOS", "returns or PnL"],
            "plan_hash_method": "sha256_canonical_json_excluding_plan_hash",
        }
        plan["plan_hash"] = canonical_json_hash(plan, excluded_key="plan_hash")
        write_json(self.plan_path, plan)
        return plan, str(plan["plan_hash"]), sha256(self.plan_path)

    def _write_approved_completed_context(self) -> str:
        preapproval_gate = {
            "schema": "active_run_gate_v1",
            "project": "trading_mvp",
            "status": "READY_FOR_POSTPROCESS",
            "next_goal_decision": self.plan["guard_contract"]["preapproval_decision"],
            "replay_allowed": False,
            "grid_allowed": False,
            "paper_forward_allowed": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
        }
        initial_policy = {
            "schema": "trading_mvp_autopilot_policy_v1",
            "policy_id": "fixture-policy",
        }
        user_text = expected_approval_text(
            self.plan,
            plan_hash=self.plan_hash,
            plan_file_sha256=self.plan_file_sha256,
        )
        bundle = build_approval_bundle(
            plan=self.plan,
            plan_path=self.plan_path,
            plan_file_sha256=self.plan_file_sha256,
            active_policy=initial_policy,
            active_gate=preapproval_gate,
            user_approval_text=user_text,
            approved_at_utc="2026-08-12T08:00:00Z",
        )
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        self.receipt_path.write_bytes(bundle.receipt_bytes)
        receipt_sha256 = sha256(self.receipt_path)
        write_json(self.policy_path, bundle.policy)

        self.output_path.write_text('{"data_status":"ok"}\n', encoding="utf-8")
        manifest = {
            "mode": "slow_liquidity_history_collect",
            "run_id": self.plan["execution"]["run_id"],
            "final": True,
            "decision": "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY",
            "quality_contract_version": "slow_liquidity_history_exact_v2",
            "started_at": "2026-08-12T08:00:01Z",
            "finished_at": "2026-08-12T08:10:00Z",
            "history_anchor_ts": 1786521600,
            "history_anchor_iso": "2026-08-12T08:00:00Z",
            "universe_path": str(self.universe_path),
            "output_jsonl": str(self.output_path),
            "manifest_path": str(self.manifest_path),
            "history_days": 56,
            "selected_bases": self.bases,
            "quote": "USDT",
            "exchanges": ["mexc", "gateio"],
            "granularities": ["1h", "4h"],
            "candles_per_request": 1000,
            "planned_market_granularity_requests": 36,
            "completed_market_granularity_requests": 36,
            "http_requests": 63,
        }
        write_json(self.manifest_path, manifest)
        launch = {
            "schema": "trading_mvp_slow_liquidity_recollect_launch_v1",
            "status": "COMPLETE",
            "run_id": self.plan["execution"]["run_id"],
            "terminal_ownership_verified": True,
            "plan_path": str(self.plan_path),
            "plan_file_sha256": self.plan_file_sha256,
            "plan_hash": self.plan_hash,
            "approval_receipt_path": str(self.receipt_path),
            "approval_receipt_sha256": receipt_sha256,
            "output_path": str(self.output_dir),
            "output_jsonl": str(self.output_path),
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": sha256(self.manifest_path),
            "output_jsonl_sha256": sha256(self.output_path),
            "started_at_utc": "2026-08-12T07:59:59Z",
            "finished_at_utc": "2026-08-12T08:10:01Z",
            "retry_authorized": False,
        }
        write_json(self.launch_path, launch)
        gate = bundle.gate
        gate.update(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": self.plan["execution"]["run_id"],
                "final": True,
                "next_goal_decision": (
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
                ),
                "plan_path": str(self.plan_path),
                "plan_hash": self.plan_hash,
                "output_path": str(self.output_path),
                "manifest_path": str(self.manifest_path),
            }
        )
        write_json(self.gate_path, gate)
        write_json(
            self.current_run_path,
            {
                "schema": "active_run_pointer_v1",
                "project": "trading_mvp",
                "run_id": self.plan["execution"]["run_id"],
                "status": "READY_FOR_POSTPROCESS",
                "updated_at": "2026-08-12T08:10:00+00:00",
                "manifest_path": str(self.manifest_path),
                "output": {"path": str(self.output_path), "kind": "file"},
                "collector_pid": None,
                "monitor_pid": None,
                "process_ids": [],
                "launch_record_path": str(self.launch_path),
            },
        )
        return receipt_sha256

    def _run(self, *, preflight: bool = False) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = sys.executable
        env["PATH"] = os.pathsep.join(
            [str(PWSH.parent), os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"]
        )
        command = [
            str(PWSH),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.runner),
            "-PlanPath",
            str(self.plan_path),
            "-ExpectedPlanHash",
            self.plan_hash,
            "-ExpectedPlanFileSha256",
            self.plan_file_sha256,
            "-ExpectedApprovalReceiptSha256",
            self.receipt_sha256,
            "-Json",
        ]
        if preflight:
            command.append("-PreflightOnly")
        return subprocess.run(
            command,
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )

    def test_preflight_validates_exact_context_without_writes(self) -> None:
        result = self._run(preflight=True)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "READY_FOR_EXACT_TECHNICAL_QUALITY")
        self.assertFalse(payload["would_write"])
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), self.original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), self.original_pointer)

    def test_actual_writes_provenance_and_identity_checkpoint_atomically(self) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        report = json.loads(self.quality_path.read_text(encoding="utf-8"))
        gate = json.loads(self.gate_path.read_text(encoding="utf-8"))
        pointer = json.loads(self.current_run_path.read_text(encoding="utf-8"))
        provenance = report["exact_recollect_provenance"]
        self.assertEqual(provenance["plan_hash"], self.plan_hash)
        self.assertEqual(provenance["output_jsonl_file_sha256"], sha256(self.output_path))
        self.assertFalse(provenance["official_identity_verification_authorized"])
        self.assertFalse(report["fixed_signal_plan_allowed"])
        self.assertEqual(
            gate["next_goal_decision"],
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
        )
        self.assertTrue(gate["identity_verification_required"])
        self.assertFalse(gate["identity_verification_authorized"])
        self.assertFalse(gate["replay_allowed"])
        self.assertEqual(pointer["run_id"], self.plan["execution"]["run_id"])
        self.assertEqual(pointer["status"], "READY_FOR_POSTPROCESS")
        self.assertEqual(pointer["process_ids"], [])
        self.assertIsNone(pointer["collector_pid"])
        self.assertIsNone(pointer["monitor_pid"])

    def test_output_substitution_fails_without_report_or_gate_change(self) -> None:
        self.output_path.write_text('{"data_status":"tampered"}\n', encoding="utf-8")

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quality_output_sha256_mismatch", result.stdout + result.stderr)
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), self.original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), self.original_pointer)

    def test_manifest_substitution_fails_without_report_or_gate_change(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["selected_bases"] = manifest["selected_bases"][:-1]
        write_json(self.manifest_path, manifest)

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("quality_manifest_sha256_mismatch", output)
        self.assertIn("quality_manifest_bases_mismatch", output)
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), self.original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), self.original_pointer)

    def test_launch_record_substitution_fails_without_report_or_gate_change(self) -> None:
        launch = json.loads(self.launch_path.read_text(encoding="utf-8"))
        launch["terminal_ownership_verified"] = False
        write_json(self.launch_path, launch)

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "quality_launch_terminal_ownership_verified_mismatch",
            result.stdout + result.stderr,
        )
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), self.original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), self.original_pointer)

    def test_manifest_change_during_quality_fails_precommit_without_state_change(self) -> None:
        (self.root / ".mutate-manifest-during-quality").write_text(
            "1\n", encoding="ascii"
        )

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Exact quality context is invalid: ValueError: manifest file SHA256 mismatch",
            result.stdout + result.stderr,
        )
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), self.original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), self.original_pointer)
        self.assertEqual(list(self.analysis_dir.glob(".slow-quality-*.json")), [])

    def test_output_change_during_quality_fails_precommit_without_state_change(self) -> None:
        (self.root / ".mutate-output-during-quality").write_text(
            "1\n", encoding="ascii"
        )

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Exact quality context is invalid: ValueError: output file SHA256 mismatch",
            result.stdout + result.stderr,
        )
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), self.original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), self.original_pointer)
        self.assertEqual(list(self.analysis_dir.glob(".slow-quality-*.json")), [])

    def test_reject_is_terminal_and_does_not_open_retry_or_rescope(self) -> None:
        (self.root / ".force-quality-reject").write_text("1\n", encoding="ascii")

        result = self._run()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        report = json.loads(self.quality_path.read_text(encoding="utf-8"))
        gate = json.loads(self.gate_path.read_text(encoding="utf-8"))
        pointer = json.loads(self.current_run_path.read_text(encoding="utf-8"))
        self.assertFalse(report["accepted"])
        self.assertTrue(report["terminal"])
        self.assertFalse(report["retry_authorized"])
        self.assertFalse(report["rescope_authorized"])
        self.assertEqual(
            report["decision"],
            "TERMINAL_DATA_QUALITY_REJECT_NO_RETRY_WITHOUT_NEW_EXACT_APPROVAL",
        )
        self.assertEqual(gate["next_goal_decision"], report["decision"])
        self.assertFalse(gate["identity_verification_required"])
        self.assertFalse(gate["replay_allowed"])
        self.assertEqual(pointer["run_id"], self.plan["execution"]["run_id"])
        self.assertEqual(pointer["status"], "READY_FOR_POSTPROCESS")
        self.assertEqual(pointer["process_ids"], [])

    def test_pointer_commit_failure_rolls_back_report_gate_and_pointer(self) -> None:
        runner_text = self.runner.read_text(encoding="utf-8")
        commit_line = "    Write-JsonAtomic -Path $currentRunPath -Object $pointer"
        self.assertIn(commit_line, runner_text)
        self.runner.write_text(
            runner_text.replace(
                commit_line,
                "    throw 'fixture_pointer_commit_failure'\n" + commit_line,
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.plan, self.plan_hash, self.plan_file_sha256 = self._write_plan()
        self.receipt_sha256 = self._write_approved_completed_context()
        original_gate = self.gate_path.read_bytes()
        original_pointer = self.current_run_path.read_bytes()

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture_pointer_commit_failure", result.stdout + result.stderr)
        self.assertFalse(self.quality_path.exists())
        self.assertEqual(self.gate_path.read_bytes(), original_gate)
        self.assertEqual(self.current_run_path.read_bytes(), original_pointer)
        self.assertEqual(list(self.analysis_dir.glob(".slow-quality-*.json")), [])


if __name__ == "__main__":
    unittest.main()
