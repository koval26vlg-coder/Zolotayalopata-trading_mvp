from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class VisibleWsCollectWrapperTests(unittest.TestCase):
    def test_slow_liquidity_history_data_plan_is_planonly(self) -> None:
        script = REPO_ROOT / "tools" / "trading_slow_liquidity_history_data_plan.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_slow_liquidity_history_data_plan_planonly",
            "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL",
            "would_start = $false",
            "collect_allowed_now = $false",
            "replay_allowed_now = $false",
            "grid_allowed_now = $false",
            "paper_forward_allowed = $false",
            "actual_collect_command_emitted = $false",
            "command_after_explicit_approval = \"not emitted",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertTrue(payload["requires_explicit_user_approval_for_actual_collect"])
        self.assertFalse(payload["actual_collect_command_emitted"])

    def test_slow_liquidity_history_visible_collect_wrapper_is_guarded_planonly(self) -> None:
        script = REPO_ROOT / "tools" / "start_slow_liquidity_history_collect_visible.ps1"
        collector = REPO_ROOT / "trading_mvp" / "src" / "slow_liquidity_history_collector.py"
        self.assertTrue(script.exists())
        self.assertTrue(collector.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "ConfirmedSlowLiquidityHistoryCollect",
            "подтверждаю visible slow-liquidity OHLCV history collect",
            "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL",
            "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY",
            "SLOW_LIQUIDITY_HISTORY_COLLECT_STOPPED_INCOMPLETE",
            "Start-Process",
            "-NoExit",
            "replay_allowed = $false",
            "grid_allowed = $false",
            "live_orders = $false",
            "api_keys = $false",
            "leverage_or_margin = $false",
            "ResumeIncomplete",
            "E:\\trading_mvp\\slow-liquidity-history",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-PlanOnly",
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertEqual(
            payload["required_approval_text"],
            "подтверждаю visible slow-liquidity OHLCV history collect",
        )
        self.assertEqual(payload["history_days"], 56)
        self.assertEqual(payload["target_bases"], 50)
        self.assertEqual(payload["timeframes"], ["15m", "1h", "4h"])

        help_result = subprocess.run(
            [sys.executable, str(collector), "--help"],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, msg=help_result.stderr)
        self.assertIn("--resume", help_result.stdout)
        self.assertIn("--max-jobs", help_result.stdout)

    def test_trading_swarm_status_marks_runtime_failure_as_limited(self) -> None:
        script = REPO_ROOT / "tools" / "trading_swarm_status.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_swarm_status",
            "SWARM_LIMITED",
            "swarm_limited",
            "independent_review_available",
            "continue_manual_codex_until_swarm_runtime_recovers",
            "empty stdout",
            "no DB response",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            workflow_root = Path(tmp) / "agent-workflows"
            workflow_dir = workflow_root / "2026-06-30-test-trading-mvp-start72h"
            handoff_dir = workflow_dir / "levels" / "L1"
            handoff_dir.mkdir(parents=True)
            (workflow_dir / "brief.md").write_text(
                "trading_mvp START72H readiness gate review",
                encoding="utf-8",
            )
            (workflow_dir / "contract.json").write_text(
                json.dumps(
                    {
                        "workflow_id": workflow_dir.name,
                        "title": "trading_mvp START72H readiness gate review",
                        "state": "revision_requested",
                        "current_level": "L1",
                        "last_event": "revision_requested",
                        "last_handoff": "levels/L1/handoff.md",
                        "allowed_next_agents": ["Antigravity CLI"],
                        "blockers": [
                            {
                                "level": "L1",
                                "reason": "swarm_limited: Antigravity CLI returned empty stdout",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (handoff_dir / "handoff.md").write_text(
                "\n".join(
                    [
                        "## Что было сделано",
                        "Runtime failed.",
                        "## На чем основан вывод",
                        "`agy --print returned empty stdout and no DB response was recovered`.",
                        "## Что получилось хорошо",
                        "No market jobs started.",
                        "## Что требует доработки",
                        "Fix Antigravity.",
                        "## Какие есть риски",
                        "Do not treat as approval.",
                        "## Что нельзя потерять/исказить дальше",
                        "`swarm_limited`.",
                        "## Решение",
                        "block",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-WorkflowRoot",
                    str(workflow_root),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "SWARM_LIMITED")
        self.assertTrue(payload["swarm_limited"])
        self.assertFalse(payload["independent_review_available"])
        self.assertEqual(payload["latest_workflow"]["decision"], "block")
        self.assertEqual(
            payload["recommended_action"],
            "continue_manual_codex_until_swarm_runtime_recovers",
        )

    def test_trading_swarm_status_respects_user_cancellation(self) -> None:
        script = REPO_ROOT / "tools" / "trading_swarm_status.ps1"
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            workflow_root = Path(tmp) / "agent-workflows"
            workflow_dir = workflow_root / "2026-07-12-test-trading-mvp-cancelled"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "brief.md").write_text("trading_mvp audit", encoding="utf-8")
            (workflow_dir / "contract.json").write_text(
                json.dumps(
                    {
                        "workflow_id": workflow_dir.name,
                        "title": "trading_mvp cancelled audit",
                        "state": "cancelled",
                        "current_level": "L2",
                        "last_event": "cancelled_by_user",
                        "allowed_next_agents": [],
                        "blockers": [],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-WorkflowRoot",
                    str(workflow_root),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "SWARM_CANCELLED_BY_USER")
        self.assertFalse(payload["swarm_limited"])
        self.assertFalse(payload["independent_review_available"])
        self.assertEqual(
            payload["recommended_action"],
            "continue_manual_codex_control_do_not_restart_swarm_without_user_request",
        )

    def test_trading_test_runner_selects_python_with_requests_planonly(self) -> None:
        script = REPO_ROOT / "tools" / "run_trading_tests.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "run_trading_tests",
            "TRADING_MVP_PYTHON",
            "C:\\Program Files\\Python313\\python.exe",
            "requests",
            "PlanOnly",
            "NO_PYTHON_WITH_REQUESTS",
            "unittest",
            "discover",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-PlanOnly",
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "READY")
        self.assertTrue(payload["selected_python"])
        self.assertTrue(payload["requests_version"])
        self.assertIn("-m unittest", payload["command"])
        self.assertEqual(payload["shard"], "all")
        self.assertGreater(payload["timeout_sec"], 0)
        self.assertEqual(len(payload["commands"]), 4)
        self.assertIn("trading_mvp", payload["start_directory"])
        self.assertEqual(payload["pattern"], "test_*.py")
        self.assertTrue(any(candidate["has_requests"] for candidate in payload["candidates"]))

    def test_structural_branch_planonly_selects_cross_venue_without_starting(self) -> None:
        script = REPO_ROOT / "tools" / "trading_structural_branch_planonly.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_structural_branch_planonly",
            "cross_venue_spot_dislocation_inventory_rebalance",
            "CROSS_VENUE_SPOT_DISLOCATION_PLANONLY_SELECTED",
            "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_SELECTED",
            "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE",
            "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_SELECTED",
            "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH",
            "would_start",
            "collect_allowed_now",
            "grid_allowed_now",
            "paper_forward_allowed",
            "base/VIP0/no-volume",
            "listing_event_drift_reversal",
            "UpdateGate",
            "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH",
            "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_RESEARCH",
            "spot_perp_basis_rejected",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "structural_branch_planonly.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(output_path.exists())

        if payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertFalse(payload["would_start"])
            self.assertFalse(payload["collect_allowed_now"])
            self.skipTest("active run gate blocks structural branch PlanOnly")

        self.assertEqual(payload["mode"], "trading_structural_branch_planonly")
        if payload["selected_branch"] == "pit_linear_perp_cross_venue_forward_oos":
            self.assertEqual(
                payload["decision"],
                "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION",
            )
            self.assertFalse(payload["would_start"])
            self.assertFalse(payload["collect_allowed_now"])
            self.assertFalse(payload["replay_allowed_now"])
            self.assertFalse(payload["grid_allowed_now"])
            self.assertFalse(payload["paper_forward_allowed"])
            self.assertIn("command_after_explicit_approval", payload["commands"])
            self.assertIn("start_pit_cross_venue_forward_oos_visible.ps1", payload["commands"]["command_after_explicit_approval"])
            return
        self.assertIn(
            payload["selected_branch"],
            {
                "cross_venue_spot_dislocation_inventory_rebalance",
                "listing_event_drift_reversal",
                "spot_perp_basis_mean_reversion_no_funding",
                "slow_liquidity_regime_breakout_retest",
                "forward_pit_universe_event_liquidity_anomaly",
            },
        )
        if payload["selected_branch"] == "forward_pit_universe_event_liquidity_anomaly":
            self.assertEqual(
                payload["decision"],
                "PIT_UNIVERSE_BRANCH_ALREADY_SELECTED_AWAITING_NEW_CLEAN_COLLECT_APPROVAL",
            )
            self.assertFalse(payload["would_start"])
            self.assertFalse(payload["live_orders"])
            self.assertFalse(payload["api_keys"])
            self.assertFalse(payload["collect_allowed_now"])
            self.assertFalse(payload["replay_allowed_now"])
            self.assertFalse(payload["grid_allowed_now"])
            self.assertFalse(payload["paper_forward_allowed"])
            self.assertIn("pit_universe_visible_collect_planonly", payload["commands"])
            return
        if payload.get("spot_perp_basis_rejected"):
            self.assertEqual(payload["selected_branch"], "slow_liquidity_regime_breakout_retest")
            self.assertNotEqual(payload["selected_branch"], "spot_perp_basis_mean_reversion_no_funding")
        elif payload["decision"] == "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_SELECTED":
            self.assertEqual(payload["selected_branch"], "slow_liquidity_regime_breakout_retest")
        elif payload["decision"] == "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_SELECTED":
            self.assertEqual(payload["selected_branch"], "spot_perp_basis_mean_reversion_no_funding")
        elif payload["decision"] == "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_SELECTED":
            self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
        else:
            self.assertEqual(payload["selected_branch"], "cross_venue_spot_dislocation_inventory_rebalance")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["gate_updated"])
        branches = {candidate["branch"] for candidate in payload["branch_candidates"]}
        self.assertIn("cross_venue_spot_dislocation_inventory_rebalance", branches)
        self.assertIn("listing_event_drift_reversal", branches)
        self.assertIn("spot_perp_basis_mean_reversion_no_funding", branches)
        self.assertIn("slow_liquidity_regime_breakout_retest", branches)
        self.assertIn("net_expectancy_after_costs", payload["selected_branch_plan"]["economics_policy"]["optimize_for"])
        self.assertIn("live_orders", payload["blocked_moves"])

    def test_slow_liquidity_planonly_is_non_starting_and_cost_gated(self) -> None:
        script = REPO_ROOT / "tools" / "trading_slow_liquidity_regime_breakout_retest_planonly.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_slow_liquidity_regime_breakout_retest_planonly",
            "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT",
            "slow_liquidity_regime_breakout_retest",
            "base/VIP0/no-volume",
            "would_start",
            "collect_allowed_now",
            "grid_allowed_now",
            "paper_forward_allowed",
            "OOS",
            "walk_forward",
            "stress",
            "build_slow_liquidity_data_availability_preflight_planonly",
            "replay_before_data_availability_preflight",
            "resurrecting_rejected_spot_perp_basis_without_new_evidence",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "slow_liquidity_planonly.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(output_path.exists())

        if payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertFalse(payload["would_start"])
            self.assertFalse(payload["collect_allowed_now"])
            self.skipTest("active run gate blocks slow liquidity PlanOnly")

        self.assertEqual(payload["mode"], "trading_slow_liquidity_regime_breakout_retest_planonly")
        self.assertEqual(payload["selected_branch"], "slow_liquidity_regime_breakout_retest")
        self.assertEqual(
            payload["decision"],
            "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT",
        )
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["strategy_accepted"])
        self.assertFalse(payload["gate_updated"])
        self.assertGreaterEqual(payload["cost_hurdle"]["minimum_gross_move_hurdle_bps"], 200)
        self.assertIn("live_orders", payload["blocked_moves"])
        self.assertIn("replay_before_data_availability_preflight", payload["blocked_moves"])
        self.assertTrue(
            any("Build read-only slow-liquidity data availability preflight PlanOnly" in move for move in payload["next_valid_moves"])
        )

    def test_slow_liquidity_data_availability_preflight_is_non_starting(self) -> None:
        script = REPO_ROOT / "tools" / "trading_slow_liquidity_data_availability_preflight.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_slow_liquidity_data_availability_preflight_planonly",
            "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_HISTORY_PLAN",
            "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY",
            "slow_liquidity_regime_breakout_retest",
            "multi_week_ohlcv",
            "required_timeframes",
            "independent_events",
            "spread_or_book_layer",
            "base/VIP0/no-volume",
            "15m",
            "1h",
            "4h",
            "walk_forward",
            "stress",
            "line_count",
            "schema_keys",
            "collect_allowed_now",
            "replay_allowed_now",
            "grid_allowed_now",
            "paper_forward_allowed",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "slow_liquidity_data_availability_preflight.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(output_path.exists())

        if payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertFalse(payload["would_start"])
            self.assertFalse(payload["collect_allowed_now"])
            self.skipTest("active run gate blocks slow liquidity data availability preflight")
        if payload["decision"] == "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_NOT_SELECTED":
            self.assertFalse(payload["would_start"])
            self.skipTest("slow liquidity branch is not selected in current gate")

        self.assertEqual(payload["mode"], "trading_slow_liquidity_data_availability_preflight_planonly")
        self.assertEqual(payload["selected_branch"], "slow_liquidity_regime_breakout_retest")
        self.assertIn(
            payload["decision"],
            {
                "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_HISTORY_PLAN",
                "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY",
            },
        )
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["strategy_accepted"])
        self.assertFalse(payload["gate_updated"])
        self.assertIn("data_sufficiency_checks", payload)
        self.assertGreaterEqual(len(payload["data_sufficiency_checks"]), 5)
        self.assertIn("listing_history_ohlcv", payload["artifacts"])
        self.assertIn("market_filter_reports", payload["artifacts"])

    def test_listing_event_planonly_is_no_start_and_requires_bias_control(self) -> None:
        script = REPO_ROOT / "tools" / "trading_listing_event_planonly.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_listing_event_drift_reversal_planonly",
            "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_NEEDS_BIAS_CONTROLLED_EVENT_CALENDAR",
            "listing_event_drift_reversal",
            "survivorship_status",
            "minimum_gross_move_hurdle_bps",
            "base/VIP0/no-volume",
            "collect_allowed_now",
            "grid_allowed_now",
            "paper_forward_allowed",
            "live_orders",
            "api_keys",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "listing_event_planonly.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(output_path.exists())

        if payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertFalse(payload["would_start"])
            self.skipTest("active run gate blocks listing event PlanOnly")

        self.assertEqual(payload["mode"], "trading_listing_event_drift_reversal_planonly")
        self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["gate_updated"])
        self.assertGreaterEqual(payload["cost_hurdle"]["minimum_gross_move_hurdle_bps"], 150)
        self.assertTrue(payload["local_event_calendar"]["required"])
        self.assertIn("survivorship_status", payload["local_event_calendar"]["required_schema"])
        self.assertIn("live_orders", payload["blocked_moves"])

    def test_listing_event_history_collect_preview_blocks_stale_replay_gate(self) -> None:
        script = REPO_ROOT / "tools" / "trading_listing_event_history_collect_preview.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "listing_event_history_collect_preview_planonly",
            "Set-JsonProperty -Object $gateDoc -Name \"replay_allowed\" -Value $false",
            "Set-JsonProperty -Object $gateDoc -Name \"collect_allowed\" -Value $false",
            "Set-JsonProperty -Object $gateDoc -Name \"grid_allowed\" -Value $false",
            "Set-JsonProperty -Object $gateDoc -Name \"paper_forward_allowed\" -Value $false",
            "Set-JsonProperty -Object $gateDoc -Name \"requires_explicit_user_approval_for_actual_collect\" -Value $true",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "listing_event_history_collect_preview.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            self.assertIn(result.returncode, {0, 2}, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            output_exists = output_path.exists()

        if payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertFalse(payload["collect_allowed_now"])
            self.skipTest("active run gate blocks listing event history collect preview")

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        self.assertTrue(output_exists)
        self.assertEqual(payload["mode"], "listing_event_history_collect_preview_planonly")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertTrue(payload["actual_collect_requires_explicit_user_approval"])
        self.assertFalse(payload["gate_updated"])

    def test_listing_event_history_planonly_reflects_quality_rejection(self) -> None:
        script = REPO_ROOT / "tools" / "trading_listing_event_history_planonly.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN",
            "listing_event_history_data_quality_*.json",
            "revised_collection_strategy",
            "two_venue_coverage",
            "do_not_run_same_event_sample_with_same_gateio_endpoint_behavior",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "listing_event_history_planonly.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            output_exists = output_path.exists()

        self.assertTrue(output_exists)
        self.assertEqual(payload["mode"], "listing_event_history_planonly")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])

        if payload["decision"] == "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN":
            self.assertTrue(payload["evidence"]["data_quality_rejected"])
            reasons = set(payload["evidence"]["data_quality_reasons"])
            self.assertTrue(
                reasons
                & {
                    "min_ok_exchanges",
                    "min_ok_events",
                    "min_ok_bases",
                    "min_ok_event_granularity_slots",
                }
            )
            if "min_ok_exchanges" in reasons:
                self.assertIn("MEXC-only", payload["revised_collection_strategy"]["reason"])
                self.assertIn(
                    "add_preflight_symbol_history_probe_per_exchange_before_full_ohlcv_collection",
                    payload["revised_collection_strategy"]["required_plan_changes"],
                )
        elif payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertIn(payload["gate_status"], {"RUNNING", "STOPPED_INCOMPLETE"})
            self.assertFalse(payload["collect_allowed_now"])
            self.assertFalse(payload["replay_allowed_now"])
        else:
            self.assertEqual(
                payload["decision"],
                "LISTING_EVENT_HISTORY_PLANONLY_READY_FOR_VISIBLE_HISTORY_COLLECT_APPROVAL",
            )

    def test_listing_event_history_collect_approval_packet_is_non_starting(self) -> None:
        script = REPO_ROOT / "tools" / "trading_listing_event_history_collect_approval_packet.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_listing_event_history_collect_approval_packet",
            "READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET",
            "подтверждаю visible listing-event OHLCV history collect",
            "would_start = $false",
            "collect_allowed_now = $false",
            "replay_allowed_now = $false",
            "preview_selection_contract",
            "calendar_survivorship_contract",
            "critical_file_fingerprints",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "listing_event_history_collect_approval_packet.json"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            self.assertIn(result.returncode, {0, 2}, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(output_path.exists())

        if payload["gate"]["next_goal_decision"] != "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL":
            self.skipTest("current gate is not on listing-event history collect approval")

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "READY_FOR_LISTING_EVENT_HISTORY_COLLECT_APPROVAL_PACKET")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["collect_allowed_now"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["leverage_or_margin"])
        self.assertTrue(payload["requires_explicit_user_approval_for_actual_collect"])
        self.assertEqual(payload["start_requires_exact_user_input"], "подтверждаю visible listing-event OHLCV history collect")
        self.assertGreaterEqual(payload["preview"]["selected_events"], 100)
        self.assertGreaterEqual(payload["preview"]["selected_unique_bases"], 30)
        self.assertGreaterEqual(payload["preview"]["selected_exchange_count"], 2)
        self.assertGreaterEqual(payload["preview"]["selected_nontradable_or_delisted_events"], 1)
        checks = {item["name"]: item for item in payload["checks"]}
        for name in (
            "gate_listing_history_contract",
            "next_goal_listing_history_contract",
            "goal_status_listing_history_contract",
            "branch_selector_listing_history_contract",
            "preview_selection_contract",
            "calendar_survivorship_contract",
            "critical_file_fingerprints",
        ):
            self.assertEqual(checks[name]["status"], "pass", msg=f"{name}: {checks[name]}")

    def test_listing_event_history_visible_wrapper_quotes_approval_text(self) -> None:
        script = REPO_ROOT / "tools" / "start_listing_event_history_collect_visible.ps1"
        self.assertTrue(script.exists())

        text = script.read_text(encoding="utf-8")
        self.assertIn("ConvertTo-ProcessArgument", text)
        self.assertIn("$argumentLine =", text)
        self.assertIn("-ArgumentList $argumentLine", text)
        self.assertNotIn("-ArgumentList $argsList", text)
        self.assertIn("LISTING_EVENT_HISTORY_COLLECT_STOPPED_INCOMPLETE", text)
        self.assertIn("Archived partial listing-history artifacts before fresh restart", text)
        self.assertIn("Reusing listing-event preview from STOPPED_INCOMPLETE gate", text)

    def test_trading_quick_status_is_no_start_and_avoids_heavy_checks(self) -> None:
        script = REPO_ROOT / "tools" / "trading_quick_status.ps1"
        shortcut = REPO_ROOT / "TRADING_QUICK_STATUS.cmd"
        self.assertTrue(script.exists())
        self.assertTrue(shortcut.exists())

        text = script.read_text(encoding="utf-8")
        shortcut_text = shortcut.read_text(encoding="utf-8")
        for needle in (
            "trading_quick_status",
            "safe_for_frequent_checks",
            "would_start",
            "STALE_DENSE_WS_PLAN_REQUIRES_NEW_HASH_BOUND_PLAN",
            "AWAITING_EXACT_CAMPAIGN_APPROVAL",
            "eligible_dense_hypothesis_ids",
            "heavy_checks_skipped",
            "trading_ws_collect_approval_packet.ps1",
        ):
            self.assertIn(needle, text)
        self.assertIn("trading_quick_status.ps1", shortcut_text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gate_path = tmp_path / "docs" / "agent-log" / "active-run-gate.json"
            gate_path.parent.mkdir(parents=True)
            gate_path.write_text(
                json.dumps(
                    {
                        "status": "READY_FOR_POSTPROCESS",
                        "run_id": "unit_test_rejected_postprocess",
                        "replay_allowed": False,
                        "next_goal_decision": "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL",
                        "requires_explicit_user_approval_for_actual_collect": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preview_path = tmp_path / "ws_collect_plan_preview_latest.json"
            preview_path.write_text(
                json.dumps(
                    {
                        "mode": "ws_collect_visible_plan",
                        "would_start": False,
                        "hours": 72,
                        "max_pairs_per_exchange": 16,
                        "universe_path": "C:\\test\\no_binance_dense_ws_sweep.csv",
                        "selected_branch": "spot_maker_liquidity_sweep_reversal_event_quality",
                        "command_after_explicit_approval": "pwsh -File start_ws_collect_visible.ps1 -Hours 72 -ConfirmedLongRun",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-GatePath",
                    str(gate_path),
                    "-PlanPreviewPath",
                    str(preview_path),
                    "-SkipSwarm",
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "trading_quick_status")
        self.assertTrue(payload["safe_for_frequent_checks"])
        self.assertFalse(payload["would_start"])
        self.assertEqual(payload["status"], "STALE_DENSE_WS_PLAN_REQUIRES_NEW_HASH_BOUND_PLAN")
        self.assertEqual(payload["required_user_input"], "")
        self.assertIsNone(payload["visible_start_shortcut"])
        self.assertEqual(payload["plan_preview"]["hours"], 72)
        self.assertEqual(payload["plan_preview"]["max_pairs_per_exchange"], 16)
        self.assertFalse(payload["plan_preview"]["frozen_hypothesis_eligible"])
        self.assertFalse(payload["plan_preview"]["fits_any_approved_window"])
        self.assertIsNone(payload["plan_preview"]["command_after_explicit_approval"])
        self.assertIn("trading_ws_collect_approval_packet.ps1", payload["heavy_checks_skipped"])

    def test_wrapper_exposes_early_density_and_schema_guards(self) -> None:
        text = (REPO_ROOT / "tools" / "start_ws_collect_visible.ps1").read_text(encoding="utf-8")

        for needle in (
            "EarlyDensityCheckAfterMinutes",
            "EarlyDensityMinLinesPerMinute",
            "early_density_guard",
            "ZeroLineAbortAfterMinutes",
            "zero_line_guard",
            "SchemaProbeAfterMinutes",
            "Test-WsRawSchema",
            "schema_probe",
            "zero_line_guard_failed",
            "early_density_guard_failed",
            "schema_probe_failed",
            "self_preflight_guard",
            "readiness_guard",
            "ResumeIncomplete",
            "resumed_from_run_id",
            "ResumeIncomplete was requested",
            "trading_edge_preflight.ps1",
            "trading_ws_collect_readiness.ps1",
            "current_scorecard_freshness",
            "Confirmed WS collect refused",
            "Confirmed WS collect refused: readiness",
            "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION",
            "refuse_confirmed_long_run_before_start",
            "ws_collect_plan_preview_latest.json",
            "ws_collect_6h_plan_preview_latest.json",
            "plan_preview_latest_path",
            "plan_preview_legacy_path",
            "Get-WsCollectManifestReadiness",
            "manifest_readiness",
            "duration_sec_completed",
            "manifest_not_final",
            "collector_exited_before_requested_duration",
            "requested_duration_sec",
            "actual_duration_sec",
            "UniversePath",
            "dense_collect_plan",
            "trading_dense_ws_collect_plan.ps1",
            "recommended_command_after_explicit_approval",
            "Set-Content",
        ):
            self.assertIn(needle, text)

    def test_wrapper_blocks_terminally_rejected_legacy_ws_route(self) -> None:
        text = (REPO_ROOT / "tools" / "start_ws_collect_visible.ps1").read_text(encoding="utf-8")

        self.assertIn("STALE_REJECTED_WS_ROUTE_DISABLED", text)
        self.assertIn("no_binance_dense_ws_sweep_20260628.csv", text)
        self.assertIn(
            "if ((-not $PlanOnly) -and ($staleRejectedUniverseNames -contains $universeLeaf))",
            text,
        )
        self.assertNotIn(
            "(-not $PlanOnly) -and (-not $ResumeIncomplete)",
            text,
        )

    def test_run_mvp_ws_collect_forwards_universe_input_path(self) -> None:
        text = (REPO_ROOT / "trading_mvp" / "run_mvp.ps1").read_text(encoding="utf-8")

        ws_collect_start = text.index('"ws-collect" {')
        ws_collect_end = text.index('"ws-normalize" {', ws_collect_start)
        ws_collect_block = text[ws_collect_start:ws_collect_end]

        self.assertIn('if ($InputPath)', ws_collect_block)
        self.assertIn('"--universe", $InputPath', ws_collect_block)

    def test_run_mvp_python_cli_exit_codes_are_propagated(self) -> None:
        text = (REPO_ROOT / "trading_mvp" / "run_mvp.ps1").read_text(encoding="utf-8")

        for needle in (
            "function Invoke-TradingMvpCli",
            "[System.Diagnostics.ProcessStartInfo]::new()",
            "$process.WaitForExit($MaxRuntimeSec * 1000)",
            "exit $process.ExitCode",
            "Set-RunTimedOutIncomplete",
        ):
            self.assertIn(needle, text)

        self.assertNotIn("& $python $cli @argsList", text)
        self.assertIn('Invoke-TradingMvpCli -ArgsList @("--config", $Config, "collect"', text)
        self.assertIn("Invoke-TradingMvpCli -ArgsList $argsList", text)

    def test_ws_collect_planonly_exposes_branch_context(self) -> None:
        script = REPO_ROOT / "tools" / "start_ws_collect_visible.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "branch_source",
            "trading_next_goal_step",
            "spot_maker_liquidity_sweep_reversal_event_quality",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        gate_result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "check_active_run_gate.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(gate_result.returncode, 0, msg=gate_result.stderr)
        gate = json.loads(gate_result.stdout)
        if gate.get("status") in {"RUNNING", "STOPPED_INCOMPLETE"}:
            self.skipTest("active run gate blocks PlanOnly preview")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Hours",
                "0.01",
                "-PlanOnly",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)

        self.assertFalse(payload["would_start"])
        self.assertEqual(payload["branch_source"], "trading_next_goal_step")
        self.assertEqual(payload["self_preflight_guard"]["required_status"], "READY_FOR_EDGE_PROOF_STEP")
        self.assertEqual(payload["self_preflight_guard"]["required_check"], "current_scorecard_freshness")
        self.assertEqual(
            payload["readiness_guard"]["required_status"],
            "READY_FOR_VISIBLE_72H_WS_COLLECT_CONFIRMATION",
        )
        self.assertEqual(payload["readiness_guard"]["action"], "refuse_confirmed_long_run_before_start")
        self.assertIn("ws_collect_plan_preview_latest.json", payload["plan_preview_latest_path"])
        self.assertIn("ws_collect_6h_plan_preview_latest.json", payload["plan_preview_legacy_path"])
        self.assertIn("dense_collect_plan", payload)
        self.assertFalse(payload["dense_collect_plan"]["would_start"])
        self.assertIn("recommended_command_after_explicit_approval", payload)
        self.assertIn("start_ws_collect_visible.ps1", payload["recommended_command_after_explicit_approval"])
        self.assertTrue(payload["branch_decision"])
        self.assertTrue(payload["selected_branch"])
        if payload["next_goal_decision"] == "SWEEP_REVERSAL_CURRENT_DATA_REJECTED_PLAN_VISIBLE_DENSE_COLLECT":
            self.assertEqual(payload["selected_branch"], "spot_maker_liquidity_sweep_reversal_event_quality")

    def test_preflight_locks_ws_and_funding_guard_readback(self) -> None:
        text = (REPO_ROOT / "tools" / "trading_edge_preflight.ps1").read_text(encoding="utf-8")

        for needle in (
            "visible_ws_collect_early_quality_guard",
            "visible_ws_collect_preview_command",
            "visible_ws_collect_command",
            "visible_ws_collect_command_resolution",
            "visible_ws_collect_self_preflight_guard",
            "visible_ws_collect_shortcut_alignment",
            "visible_ws_collect_mexc_chunking",
            "TRADING_PREVIEW_DENSE_WS.cmd",
            "TRADING_START_DENSE_WS_CONFIRMED.cmd",
            "visible_ws_collect_plan_preview_freshness",
            "visible_ws_collect_readiness_verifier",
            "collect_approval_contract_verifier",
            "trading_collect_approval_contract.ps1",
            "collect_approval_contract_command",
            "ws_collect_approval_packet",
            "trading_ws_collect_approval_packet.ps1",
            "ws_collect_approval_packet_command",
            "trading_swarm_status.ps1",
            "swarm_status_readback",
            "swarm_status_command",
            "run_trading_tests.ps1",
            "trading_test_runner",
            "trading_test_runner_command",
            "trading_test_full_command",
            "swarm_independent_review_available",
            "visible_ws_collect_confirmed_readiness_guard",
            "visible_ws_collect_readiness_command",
            "trading_ws_collect_readiness.ps1",
            "visible_ws_postprocess_shortcut_alignment",
            "data_sufficiency_planner",
            "data_sufficiency_plan_command",
            "dense_ws_collect_planner",
            "dense_ws_collect_plan_command",
            "ws_postprocess_command",
            "ws_postprocess_shortcut_command",
            "ws_replay_validation_plan_command",
            "Current proof branch is guarded visible dense WS collect planning",
            "funding_postprocess_block_readback",
            "final_review_blocked_dataset_self_refuse",
            "AllowBlockedFundingDataset",
            "branch_selector_funding_block_override",
            "blocked_by_swarm_do_not_run_7d_funding_collect_or_final_review",
            "gate_postprocess_block",
            "gate_raw_next_step_after_ready",
            "current_scorecard_freshness",
            "anufriev_strategy_scorecard_current_20260628.csv",
            "ws_grid_search_ws_confirmed_research_6h_20260628_103700.json",
            "sweep_reversal_acceptance_ws_confirmed_research_6h_20260628_103700_gatefixed.json",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "trading_edge_preflight.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            try:
                blocked_payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                blocked_payload = {}
            if blocked_payload.get("status") == "BLOCKED_STOPPED_INCOMPLETE":
                self.skipTest("active run gate is STOPPED_INCOMPLETE; preflight is correctly blocked")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertEqual(checks["branch_selector_funding_block_override"]["status"], "pass")
        self.assertEqual(checks["current_scorecard_freshness"]["status"], "pass")
        self.assertIn(checks["swarm_status_readback"]["status"], {"pass", "warn"})
        self.assertEqual(checks["trading_test_runner"]["status"], "pass")
        self.assertEqual(checks["visible_ws_collect_self_preflight_guard"]["status"], "pass")
        self.assertEqual(checks["visible_ws_collect_shortcut_alignment"]["status"], "pass")
        self.assertEqual(checks["visible_ws_collect_mexc_chunking"]["status"], "pass")
        self.assertIn(checks["visible_ws_collect_plan_preview_freshness"]["status"], {"pass", "warn"})
        self.assertEqual(checks["visible_ws_collect_readiness_verifier"]["status"], "pass")
        self.assertEqual(checks["collect_approval_contract_verifier"]["status"], "pass")
        self.assertEqual(checks["ws_collect_approval_packet"]["status"], "pass")
        self.assertEqual(checks["visible_ws_collect_confirmed_readiness_guard"]["status"], "pass")
        self.assertEqual(checks["visible_ws_postprocess_shortcut_alignment"]["status"], "pass")
        self.assertEqual(checks["data_sufficiency_planner"]["status"], "pass")
        self.assertEqual(checks["dense_ws_collect_planner"]["status"], "pass")
        self.assertIn("anufriev_strategy_scorecard_current_20260628.csv", payload["current_scorecard"])
        self.assertIn(
            "ws_collect_plan_preview_latest.json",
            payload["visible_ws_collect_plan_preview_latest"],
        )
        self.assertIn("trading_data_sufficiency_plan.ps1", payload["data_sufficiency_plan_command"])
        self.assertIn("trading_dense_ws_collect_plan.ps1", payload["dense_ws_collect_plan_command"])
        self.assertIn("TRADING_WS_POSTPROCESS_FROM_GATE.cmd", payload["ws_postprocess_shortcut_command"])
        resolution = payload["visible_ws_collect_command_resolution"]
        self.assertEqual(resolution["source"], "latest_plan_preview")
        self.assertEqual(resolution["effective_hours"], 72)
        self.assertEqual(resolution["effective_max_pairs_per_exchange"], 16)
        self.assertIn("no_binance_dense_ws_sweep_20260628.csv", resolution["effective_universe_path"])
        self.assertIn("ws_collect_plan_preview_latest.json", resolution["plan_preview_path"])
        self.assertIn("-Hours 72", payload["visible_ws_collect_preview_command"])
        self.assertIn("-Hours 72", payload["visible_ws_collect_command"])
        self.assertIn("-UniversePath", payload["visible_ws_collect_command"])
        self.assertNotIn("-Hours 6 -ConfirmedLongRun", payload["visible_ws_collect_command"])
        self.assertIn("TRADING_PREVIEW_DENSE_WS.cmd", payload["visible_ws_collect_preview_shortcut"])
        self.assertIn("TRADING_START_DENSE_WS_CONFIRMED.cmd", payload["visible_ws_collect_confirmed_shortcut"])
        self.assertIn("trading_ws_collect_readiness.ps1", payload["visible_ws_collect_readiness_command"])
        self.assertIn("trading_collect_approval_contract.ps1", payload["collect_approval_contract_command"])
        self.assertIn("trading_ws_collect_approval_packet.ps1", payload["ws_collect_approval_packet_command"])
        self.assertIn("trading_swarm_status.ps1", payload["swarm_status_command"])
        self.assertIn("run_trading_tests.ps1", payload["trading_test_runner_command"])
        self.assertIn("-PlanOnly", payload["trading_test_runner_command"])
        self.assertIn("run_trading_tests.ps1", payload["trading_test_full_command"])
        self.assertIn(payload["swarm_status"], {"SWARM_LIMITED", "SWARM_REVIEW_INCOMPLETE", "SWARM_APPROVED", "SWARM_CANCELLED_BY_USER"})
        self.assertEqual(payload["swarm_limited"], payload["swarm_status"] == "SWARM_LIMITED")
        self.assertIsInstance(payload["swarm_independent_review_available"], bool)
        self.assertEqual(checks["final_review_blocked_dataset_self_refuse"]["status"], "pass")

    def test_dense_ws_shortcuts_replace_stale_6h_confirmed_shortcut(self) -> None:
        preview_dense = (REPO_ROOT / "TRADING_PREVIEW_DENSE_WS.cmd").read_text(encoding="utf-8")
        start_dense = (REPO_ROOT / "TRADING_START_DENSE_WS_CONFIRMED.cmd").read_text(encoding="utf-8")
        preview_6h = (REPO_ROOT / "TRADING_PREVIEW_6H_WS.cmd").read_text(encoding="utf-8")
        start_6h = (REPO_ROOT / "TRADING_START_6H_WS_CONFIRMED.cmd").read_text(encoding="utf-8")

        self.assertIn("start_ws_collect_visible.ps1", preview_dense)
        self.assertIn("-Hours 72", preview_dense)
        self.assertIn("no_binance_dense_ws_sweep_20260628.csv", preview_dense)
        self.assertIn("-PlanOnly", preview_dense)

        self.assertIn("START72H", start_dense)
        self.assertIn("Running pre-start readiness check", start_dense)
        self.assertIn("trading_ws_collect_readiness.ps1", start_dense)
        self.assertIn("Readiness check failed", start_dense)
        self.assertIn("Running approval contract check", start_dense)
        self.assertIn("trading_collect_approval_contract.ps1", start_dense)
        self.assertIn("Approval contract check failed", start_dense)
        self.assertIn("Building approval evidence packet", start_dense)
        self.assertIn("trading_ws_collect_approval_packet.ps1", start_dense)
        self.assertIn("Approval evidence packet failed", start_dense)
        start_prompt_index = start_dense.index("set /p CONFIRM=Type START72H")
        self.assertLess(start_dense.index("trading_ws_collect_readiness.ps1"), start_prompt_index)
        self.assertLess(start_dense.index("trading_collect_approval_contract.ps1"), start_prompt_index)
        self.assertLess(start_dense.index("trading_ws_collect_approval_packet.ps1"), start_prompt_index)
        self.assertIn("start_ws_collect_visible.ps1", start_dense)
        self.assertIn("-Hours 72", start_dense)
        self.assertIn("-MaxPairsPerExchange 16", start_dense)
        self.assertIn("no_binance_dense_ws_sweep_20260628.csv", start_dense)
        self.assertIn("-ConfirmedLongRun", start_dense)

        self.assertIn("Superseded", preview_6h)
        self.assertIn("TRADING_PREVIEW_DENSE_WS.cmd", preview_6h)
        self.assertIn("Superseded", start_6h)
        self.assertIn("START72H", start_6h)
        self.assertIn("exit /b 1", start_6h)
        self.assertNotIn("-ConfirmedLongRun", start_6h)

    def test_ws_collect_readiness_verifier_blocks_stale_or_unsafe_start(self) -> None:
        script = REPO_ROOT / "tools" / "trading_ws_collect_readiness.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "READY_FOR_VISIBLE_WS_COLLECT_APPROVAL_PACKET",
            "STALE_DENSE_WS_PLAN_REQUIRES_NEW_HASH_BOUND_PLAN",
            "REQUESTED_RUNTIME_OUTSIDE_APPROVED_WINDOWS",
            "requires_explicit_user_approval_for_actual_collect",
            "frozen_hypothesis_binding",
            "campaign_window_capacity",
            "stale_6h_confirmed_route",
            "plan_preview_alignment",
            "mexc_channel_chunking",
            "dense_universe",
            "confirmed_shortcut",
            "exit 2",
            "would_start = $false",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        gate_result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "check_active_run_gate.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(gate_result.returncode, 0, msg=gate_result.stderr)
        gate = json.loads(gate_result.stdout)
        if gate.get("status") in {"RUNNING", "STOPPED_INCOMPLETE"}:
            self.skipTest("active run gate blocks readiness verification")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 2, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        checks = {check["name"]: check for check in payload["checks"]}

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["leverage_or_margin"])
        self.assertTrue(payload["requires_explicit_user_approval_for_actual_collect"])
        self.assertEqual(payload["status"], "STALE_DENSE_WS_PLAN_REQUIRES_NEW_HASH_BOUND_PLAN")
        self.assertEqual(payload["hours"], 72)
        self.assertEqual(payload["max_pairs_per_exchange"], 16)
        self.assertIn("no_binance_dense_ws_sweep_20260628.csv", payload["universe_path"])
        self.assertIn("-ConfirmedLongRun", payload["command_after_explicit_approval"])
        self.assertNotIn("-Hours 6 -ConfirmedLongRun", payload["command_after_explicit_approval"])
        self.assertEqual(checks["frozen_hypothesis_binding"]["status"], "fail")
        self.assertEqual(checks["campaign_window_capacity"]["status"], "fail")

        for name in (
            "active_run_gate",
            "plan_preview_alignment",
            "dense_plan_safety",
            "postprocess_chain",
            "mexc_channel_chunking",
            "dense_universe",
            "preview_shortcut",
            "confirmed_shortcut",
            "stale_6h_confirmed_route",
        ):
            self.assertEqual(checks[name]["status"], "pass", msg=f"{name}: {checks[name]}")

    def test_collect_approval_contract_blocks_actual_collect_without_start72h(self) -> None:
        script = REPO_ROOT / "tools" / "trading_collect_approval_contract.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_collect_approval_contract",
            "APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT",
            "requires_user_approval_for_actual_collect",
            "requires_explicit_user_approval_for_actual_collect",
            "START72H",
            "replay_allowed",
            "would_start",
            "-PlanOnly",
            "-ConfirmedLongRun",
            "-Hours 6 -ConfirmedLongRun",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        gate_result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "check_active_run_gate.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(gate_result.returncode, 0, msg=gate_result.stderr)
        gate = json.loads(gate_result.stdout)
        if gate.get("status") in {"RUNNING", "STOPPED_INCOMPLETE"}:
            self.skipTest("active run gate blocks approval-contract verification")
        if gate.get("next_goal_decision") != "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL":
            self.skipTest("current gate is not on the visible 72h approval branch")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        checks = {check["name"]: check for check in payload["checks"]}

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["applicable"])
        self.assertEqual(payload["status"], "APPROVAL_REQUIRED_FOR_VISIBLE_72H_COLLECT")
        self.assertFalse(payload["gate_replay_allowed"])
        self.assertTrue(payload["requires_explicit_user_approval_for_actual_collect"])
        self.assertIn("-PlanOnly", payload["preview_command"])
        self.assertNotIn("-ConfirmedLongRun", payload["preview_command"])
        self.assertIn("-Hours 72", payload["command_after_explicit_approval"])
        self.assertIn("-ConfirmedLongRun", payload["command_after_explicit_approval"])
        self.assertNotIn("-Hours 6 -ConfirmedLongRun", payload["command_after_explicit_approval"])

        for name in (
            "gate_rejected_artifact_contract",
            "gate_actual_collect_command",
            "next_goal_approval_contract",
            "next_goal_primary_preview_command",
            "next_goal_actual_collect_command",
            "goal_status_approval_contract",
            "goal_status_preview_command",
            "goal_status_actual_collect_command",
            "branch_selector_approval_contract",
            "branch_selector_preview_command",
            "branch_selector_actual_collect_command",
            "readiness_approval_contract",
            "readiness_actual_collect_command",
            "confirmed_shortcut_start72h_contract",
        ):
            self.assertEqual(checks[name]["status"], "pass", msg=f"{name}: {checks[name]}")

    def test_ws_collect_approval_packet_records_start72h_evidence_fingerprints(self) -> None:
        script = REPO_ROOT / "tools" / "trading_ws_collect_approval_packet.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_ws_collect_approval_packet",
            "READY_FOR_START72H_APPROVAL_PACKET",
            "Get-FileFingerprint",
            "sha256",
            "critical_file_fingerprints",
            "start_requires_exact_user_input",
            "START72H",
            "would_start = $false",
            "command_after_explicit_approval",
            "no_binance_dense_ws_sweep_20260628.csv",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        gate_result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "check_active_run_gate.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(gate_result.returncode, 0, msg=gate_result.stderr)
        gate = json.loads(gate_result.stdout)
        if gate.get("status") in {"RUNNING", "STOPPED_INCOMPLETE"}:
            self.skipTest("active run gate blocks approval packet")
        if gate.get("next_goal_decision") != "START_NEW_VISIBLE_72H_DENSE_WS_COLLECT_AFTER_EXPLICIT_APPROVAL":
            self.skipTest("current gate is not on the visible 72h approval branch")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        checks = {check["name"]: check for check in payload["checks"]}

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "READY_FOR_START72H_APPROVAL_PACKET")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertFalse(payload["leverage_or_margin"])
        self.assertTrue(payload["requires_explicit_user_approval_for_actual_collect"])
        self.assertEqual(payload["start_requires_exact_user_input"], "START72H")
        self.assertEqual(payload["branch"]["selected_branch"], "spot_maker_liquidity_sweep_reversal_event_quality")
        self.assertEqual(payload["branch"]["accepted_trading_strategies"], 0)
        self.assertIn("-Hours 72", payload["commands"]["preview"])
        self.assertIn("-PlanOnly", payload["commands"]["preview"])
        self.assertIn("-Hours 72", payload["commands"]["command_after_explicit_approval"])
        self.assertIn("-ConfirmedLongRun", payload["commands"]["command_after_explicit_approval"])
        self.assertIn("ExpectedManifestPath", payload["commands"]["replay_validation_plan_after_postprocess"])
        self.assertIn("Python313", payload["test_runner"]["selected_python"])
        self.assertTrue(payload["test_runner"]["requests_version"])
        self.assertGreaterEqual(len(payload["fingerprints"]), 15)
        self.assertTrue(all(item["exists"] and item["sha256"] for item in payload["fingerprints"]))
        self.assertTrue(Path(payload["paths"]["output_path"]).exists())

        for name in (
            "active_run_gate",
            "edge_preflight",
            "next_goal_step",
            "goal_status",
            "ws_collect_readiness",
            "approval_contract",
            "test_runner_plan",
            "plan_preview",
            "command_after_explicit_approval",
            "universe_coverage",
            "critical_file_fingerprints",
        ):
            self.assertEqual(checks[name]["status"], "pass", msg=f"{name}: {checks[name]}")

    def test_data_sufficiency_planner_estimates_ws_sample_size(self) -> None:
        script = REPO_ROOT / "tools" / "trading_data_sufficiency_plan.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "TargetSweeps",
            "sweep_rate_per_market_hour",
            "estimated_hours_for_target_sweeps_current_markets",
            "next_collect_6h_is_likely_insufficient_for_event_gate",
            "paper_forward_allowed",
        ):
            self.assertIn(needle, text)

        artifacts = [
            REPO_ROOT
            / "exports"
            / "trading-mvp"
            / "backtests"
            / "event_quality_ws_confirmed_research_6h_20260628_103700.json",
            REPO_ROOT
            / "exports"
            / "trading-mvp"
            / "backtests"
            / "sweep_reversal_acceptance_ws_confirmed_research_6h_20260628_103700_gatefixed.json",
            REPO_ROOT / "exports" / "trading-mvp" / "raw" / "ws_collect_20260628_000346.json",
        ]
        if not all(path.exists() for path in artifacts):
            self.skipTest("current WS artifacts are unavailable")

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertEqual(payload["current"]["total_sweeps"], 43)
        self.assertEqual(payload["targets"]["target_sweeps"], 1000)
        self.assertGreater(payload["estimates"]["estimated_hours_for_target_sweeps_current_markets"], 100)
        self.assertTrue(payload["verdict"]["next_collect_6h_is_likely_insufficient_for_event_gate"])

    def test_dense_ws_collect_planner_builds_dense_universe_and_command(self) -> None:
        script = REPO_ROOT / "tools" / "trading_dense_ws_collect_plan.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "dense_ws_collect_plan",
            "dense_universe_output",
            "recommended_command_after_explicit_approval",
            "another_blind_6h_collect_rejected",
            "sweep_rate_per_market_hour",
        ):
            self.assertIn(needle, text)

        artifacts = [
            REPO_ROOT
            / "exports"
            / "trading-mvp"
            / "backtests"
            / "event_quality_ws_confirmed_research_6h_20260628_103700.json",
            REPO_ROOT
            / "exports"
            / "trading-mvp"
            / "analysis"
            / "trading_data_sufficiency_plan_ws_confirmed_research_6h_20260628.json",
        ]
        if not all(path.exists() for path in artifacts):
            self.skipTest("current WS density artifacts are unavailable")

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["mode"], "dense_ws_collect_plan")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertTrue(payload["verdict"]["another_blind_6h_collect_rejected"])
        self.assertGreaterEqual(payload["selected_option"]["total_markets"], 32)
        self.assertGreaterEqual(payload["recommended_wrapper_args"]["hours"], 48)
        self.assertIn("UniversePath", payload["recommended_command_after_explicit_approval"])
        self.assertTrue(Path(payload["dense_universe_output"]).exists())

    def test_replay_validation_requires_expected_manifest_for_confirmed_run(self) -> None:
        script = REPO_ROOT / "tools" / "run_ws_replay_validation_visible.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "expected_manifest_required_for_confirmed_research_run",
            "ExpectedManifestPath",
            "ConfirmedResearchRun",
            "stale postprocess artifact",
            "ws_market_filter_postprocess_guarded",
            "sha256_skipped",
            "file_too_large",
            "skip_reasons",
            "requires_ws_grid",
            "Assert-ExpectedOutput",
            "ExpectedOutput",
            "stage_output_missing",
            "stage_output_empty",
            "stage_output_stale",
            "Get-Item -LiteralPath",
            "output_check",
        ):
            self.assertIn(needle, text)

        artifact = (
            REPO_ROOT
            / "exports"
            / "trading-mvp"
            / "backtests"
            / "ws_postprocess_ws_collect_20260628_000346_postprocess_20260628_100805.json"
        )
        if not artifact.exists():
            self.skipTest("current ws postprocess artifact is unavailable")

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        gate_result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "check_active_run_gate.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(gate_result.returncode, 0, msg=gate_result.stderr)
        gate = json.loads(gate_result.stdout)
        if gate.get("status") in {"RUNNING", "STOPPED_INCOMPLETE"}:
            self.skipTest("active run gate blocks replay validation")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-PostprocessPath",
                str(artifact),
                "-ConfirmedResearchRun",
                "-NoPause",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["would_run"])
        self.assertEqual(payload["reason"], "expected_manifest_required_for_confirmed_research_run")

    def test_funding_final_review_refuses_blocked_dataset_by_default(self) -> None:
        script = REPO_ROOT / "tools" / "run_funding_final_review_visible.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "AllowBlockedFundingDataset",
            "Funding dataset is blocked by guard review",
            "Refusing funding final-review/rank/backtest/paper-forward",
            "trading_next_goal_step.ps1",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        gate_result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "tools" / "check_active_run_gate.ps1"),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(gate_result.returncode, 0, msg=gate_result.stderr)
        gate = json.loads(gate_result.stdout)
        if not gate.get("postprocess_block"):
            self.skipTest("current gate is not a blocked funding dataset")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-NoPause",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Funding dataset is blocked by guard review", result.stderr + result.stdout)
        self.assertIn("Refusing funding final-review/rank/backtest/paper-forward", result.stderr + result.stdout)

    def test_goal_status_legacy_visible_collect_follows_active_branch(self) -> None:
        script = REPO_ROOT / "tools" / "trading_goal_status.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "visible_collect_command_legacy_resolution",
            "visible_ws_collect_command_resolution",
            "visible_ws_collect_readiness_command",
            "collect_approval_contract_command",
            "ws_collect_approval_packet_command",
            "trading_ws_collect_approval_packet.ps1",
            "swarm_status_command",
            "swarm_limited",
            "swarm_independent_review_available",
            "trading_test_runner_command",
            "trading_test_full_command",
            "run_trading_tests.ps1",
            "funding_visible_collect_preview_command",
            "funding_visible_collect_command",
            "funding_visible_collect_preview_shortcut",
            "funding_visible_collect_confirmed_shortcut",
            "funding_basis_planonly_command",
            "structural_branch_planonly_command",
            "slow_liquidity_regime_planonly_command",
            "slow_liquidity_data_availability_preflight_command",
            "slow_liquidity_history_data_plan_command",
            "slow_liquidity_history_data_plan_ready_gate",
            "slow_liquidity_data_availability_rejected_gate",
            "cross_venue_rejected_gate",
            "listing_event_selected_gate",
            "slow_liquidity_regime_breakout_retest_planonly_selected_no_collect",
            "listing_event_drift_reversal_planonly_after_cross_venue_rejected",
            "funding_basis_planonly_after_liquidity_sweep_rejected",
            "redirected_to_ws_collect_because_funding_blocked_by_swarm",
            "visible_collect_command = $legacyVisibleCollectCommand",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)

        if payload.get("forward_oos_approval_ready_gate"):
            self.assertEqual(
                payload["primary_edge_status"],
                "forward_oos_approval_packet_ready_awaiting_explicit_visible_confirmation",
            )
            self.assertEqual(
                payload["primary_edge_candidate"],
                "MEXC/Gate linear-perp cross-venue forward-OOS evidence collect",
            )
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "pit_linear_perp_forward_oos_awaiting_explicit_visible_confirmation",
            )
            self.assertIn("start_pit_cross_venue_forward_oos_visible.ps1", payload["visible_collect_preview_command"])
            self.assertIn("-PlanOnly", payload["visible_collect_preview_command"])
            self.assertIn("start_pit_cross_venue_forward_oos_visible.ps1", payload["visible_collect_command"])
            self.assertIn("-ConfirmedForwardOosCollect", payload["visible_collect_command"])
            self.assertEqual(payload["accepted_trading_strategies"], 0)
            return
        if payload.get("slow_liquidity_regime_selected_gate"):
            if payload.get("slow_liquidity_history_data_plan_ready_gate"):
                self.assertEqual(
                    payload["primary_edge_status"],
                    "slow_liquidity_history_data_plan_ready_awaiting_explicit_approval",
                )
                self.assertEqual(
                    payload["primary_edge_candidate"],
                    "Slow liquidity history data plan awaiting explicit approval",
                )
                self.assertTrue(payload["requires_user_approval_for_actual_collect"])
                self.assertIn("await explicit user approval", payload["visible_collect_command"])
            elif payload.get("slow_liquidity_data_availability_rejected_gate"):
                self.assertEqual(payload["primary_edge_status"], "slow_liquidity_data_availability_rejected_needs_history_plan")
                self.assertEqual(payload["primary_edge_candidate"], "Slow liquidity data availability rejected; history plan needed")
                self.assertIn("trading_slow_liquidity_history_data_plan.ps1", payload["visible_collect_command"])
            elif payload.get("slow_liquidity_data_availability_accepted_gate"):
                self.assertEqual(
                    payload["primary_edge_status"],
                    "slow_liquidity_data_availability_accepted_ready_for_fixed_signal_planonly",
                )
                self.assertEqual(
                    payload["primary_edge_candidate"],
                    "Slow liquidity data availability accepted; fixed signal PlanOnly needed",
                )
                self.assertIn("fixed v0 slow-liquidity signal", payload["visible_collect_command"])
            else:
                self.assertEqual(
                    payload["primary_edge_status"],
                    "slow_liquidity_regime_breakout_retest_planonly_ready_for_data_availability_preflight",
                )
                self.assertEqual(payload["primary_edge_candidate"], "Slow liquidity regime breakout/retest PlanOnly")
                self.assertIn("trading_slow_liquidity_data_availability_preflight.ps1", payload["visible_collect_command"])
            if not payload.get("slow_liquidity_history_data_plan_ready_gate"):
                self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "slow_liquidity_regime_breakout_retest_planonly_selected_no_collect",
            )
            self.assertIn("trading_slow_liquidity_regime_breakout_retest_planonly.ps1", payload["slow_liquidity_regime_planonly_command"])
            self.assertIn(
                "trading_slow_liquidity_data_availability_preflight.ps1",
                payload["slow_liquidity_data_availability_preflight_command"],
            )
        elif payload.get("listing_event_history_data_quality_rejected_gate"):
            self.assertEqual(
                payload["primary_edge_status"],
                "listing_event_history_data_quality_rejected_revise_collect_plan",
            )
            self.assertEqual(
                payload["primary_edge_candidate"],
                "Listing event history data-quality rejected; revise collect plan",
            )
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("trading_listing_event_history_data_quality.ps1", payload["listing_event_history_data_quality_command"])
            self.assertIn("trading_listing_event_history_planonly.ps1", payload["listing_event_history_recollect_plan_command"])
        elif payload.get("listing_event_history_data_quality_pending_gate"):
            self.assertEqual(payload["primary_edge_status"], "listing_event_history_data_quality_required")
            self.assertEqual(payload["primary_edge_candidate"], "Listing event history data-quality")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("trading_listing_event_history_data_quality.ps1", payload["listing_event_history_data_quality_command"])
        elif payload.get("listing_event_history_plan_ready_gate"):
            if payload.get("listing_event_history_collect_preview_awaiting_approval_gate"):
                self.assertEqual(
                    payload["primary_edge_status"],
                    "listing_event_history_collect_preview_awaiting_explicit_approval",
                )
                self.assertEqual(
                    payload["primary_edge_candidate"],
                    "Listing event OHLCV history collect preview awaiting approval",
                )
                self.assertTrue(payload["requires_user_approval_for_actual_collect"])
                self.assertIn("start_listing_event_history_collect_visible.ps1", payload["visible_collect_command"])
                self.assertIn("-ConfirmedListingHistoryCollect", payload["visible_collect_command"])
            else:
                self.assertEqual(payload["primary_edge_status"], "listing_event_history_collect_preview_planonly_ready")
                self.assertEqual(payload["primary_edge_candidate"], "Listing event OHLCV history collect preview PlanOnly")
                self.assertFalse(payload["requires_user_approval_for_actual_collect"])
                self.assertIn("trading_listing_event_history_collect_preview.ps1", payload["visible_collect_command"])
            self.assertIn("trading_listing_event_history_collect_preview.ps1", payload["visible_collect_preview_command"])
        elif payload.get("listing_event_normalizer_ready_gate"):
            self.assertEqual(payload["primary_edge_status"], "listing_event_normalizer_planonly_ready")
            self.assertEqual(payload["primary_edge_candidate"], "Listing event normalizer PlanOnly")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("trading_listing_event_normalizer_planonly.ps1", payload["visible_collect_command"])
            self.assertIn("trading_listing_event_normalizer_planonly.ps1", payload["visible_collect_preview_command"])
        elif payload.get("listing_event_history_availability_ready_gate"):
            self.assertEqual(
                payload["primary_edge_status"],
                "listing_event_history_availability_preflight_awaiting_public_probe_confirmation",
            )
            self.assertEqual(
                payload["primary_edge_candidate"],
                "Listing event history availability public probe awaiting confirmation",
            )
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("trading_listing_event_history_availability_preflight.ps1", payload["visible_collect_command"])
            self.assertIn("-ConfirmedPublicProbe", payload["visible_collect_command"])
        elif payload.get("current_cross_venue_spot_closure_gate"):
            self.assertEqual(
                payload["primary_edge_status"],
                "cross_venue_spot_verified_rejected_select_new_structural_hypothesis_planonly",
            )
            self.assertEqual(
                payload["primary_edge_candidate"],
                "New structural hypothesis PlanOnly after verified MEXC/Gate spot rejection",
            )
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "verified_cross_venue_spot_closure_select_new_structural_hypothesis_planonly",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_preview_command"])
        elif payload.get("spot_perp_basis_availability_rejected_gate") or payload.get("spot_perp_basis_rejected_gate"):
            self.assertEqual(payload["primary_edge_status"], "spot_perp_basis_public_probe_rejected_rescope")
            self.assertEqual(payload["primary_edge_candidate"], "Spot/perp basis availability/public probe rejected; rescope branch")
            self.assertFalse(payload["spot_perp_basis_selected_gate"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "spot_perp_basis_public_probe_rejected_select_next_non_hft_branch",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_preview_command"])
        elif payload.get("listing_event_replay_rejected_gate"):
            self.assertEqual(payload["primary_edge_status"], "listing_event_replay_rejected_select_next_branch")
            self.assertEqual(
                payload["primary_edge_candidate"],
                "New non-HFT structural branch PlanOnly after listing-event replay rejection",
            )
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "listing_event_replay_rejected_select_next_non_hft_branch",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_preview_command"])
        elif payload.get("cross_venue_rejected_gate") or payload.get("listing_event_selected_gate"):
            self.assertEqual(payload["primary_edge_status"], "listing_event_drift_reversal_planonly_research")
            self.assertEqual(payload["primary_edge_candidate"], "Listing event drift/reversal PlanOnly")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "listing_event_drift_reversal_planonly_after_cross_venue_rejected",
            )
            self.assertIn("trading_listing_event_planonly.ps1", payload["visible_collect_command"])
            self.assertIn("trading_listing_event_planonly.ps1", payload["visible_collect_preview_command"])
        elif payload.get("funding_rejected_base_fees_gate"):
            self.assertEqual(payload["primary_edge_status"], "select_next_non_hft_structural_branch_planonly")
            self.assertEqual(payload["primary_edge_candidate"], "New non-HFT structural branch PlanOnly")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "next_non_hft_structural_branch_planonly_after_funding_rejected_base_fees",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", payload["visible_collect_preview_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", payload["structural_branch_planonly_command"])
        elif payload.get("cross_venue_structural_selected_gate"):
            self.assertEqual(
                payload["primary_edge_status"],
                "implement_cross_venue_dislocation_planonly_research",
            )
            self.assertEqual(
                payload["primary_edge_candidate"],
                "Cross-venue spot dislocation inventory-rebalance PlanOnly",
            )
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "cross_venue_dislocation_planonly_selected_no_collect",
            )
            self.assertIn("cross-venue spot dislocation", payload["visible_collect_command"])
            self.assertIn("do not start collect/grid/live/API", payload["visible_collect_command"])
            self.assertIn("start_funding_collect_visible.ps1", payload["funding_visible_collect_command"])
            self.assertIn("start_ws_collect_visible.ps1", payload["visible_ws_collect_command"])
        elif payload.get("liquidity_sweep_rejected_gate"):
            self.assertEqual(payload["primary_edge_status"], "funding_basis_carry_structural_planonly")
            self.assertEqual(payload["primary_edge_candidate"], "Funding/basis carry structural PlanOnly diagnostics")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "funding_basis_planonly_after_liquidity_sweep_rejected",
            )
            self.assertEqual(payload["visible_collect_command"], payload["funding_basis_planonly_command"])
            self.assertEqual(payload["visible_collect_preview_command"], payload["funding_basis_planonly_command"])
            self.assertIn("trading_funding_basis_planonly.ps1", payload["funding_basis_planonly_command"])
            self.assertIn("start_funding_collect_visible.ps1", payload["funding_visible_collect_command"])
            self.assertIn("start_ws_collect_visible.ps1", payload["visible_ws_collect_command"])
        elif payload["funding_blocked_by_swarm"]:
            resolution = payload["visible_ws_collect_command_resolution"]
            self.assertEqual(resolution["source"], "latest_plan_preview")
            self.assertEqual(resolution["effective_hours"], 72)
            self.assertIn("no_binance_dense_ws_sweep_20260628.csv", resolution["effective_universe_path"])
            self.assertTrue(payload["visible_ws_collect_requires_user_approval"])
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                payload["visible_collect_command_legacy_resolution"],
                "redirected_to_ws_collect_because_funding_blocked_by_swarm",
            )
            self.assertEqual(payload["visible_collect_command"], payload["visible_ws_collect_command"])
            self.assertIn("-Hours 72", payload["visible_collect_command"])
            self.assertNotIn("-Hours 6 -ConfirmedLongRun", payload["visible_collect_command"])
            self.assertIn("TRADING_PREVIEW_DENSE_WS.cmd", payload["visible_ws_collect_preview_shortcut"])
            self.assertIn("TRADING_START_DENSE_WS_CONFIRMED.cmd", payload["visible_ws_collect_confirmed_shortcut"])
            self.assertIn("trading_ws_collect_readiness.ps1", payload["visible_ws_collect_readiness_command"])
            self.assertIn("trading_collect_approval_contract.ps1", payload["collect_approval_contract_command"])
            self.assertIn("trading_ws_collect_approval_packet.ps1", payload["ws_collect_approval_packet_command"])
            self.assertIn("trading_swarm_status.ps1", payload["swarm_status_command"])
            self.assertIn("run_trading_tests.ps1", payload["trading_test_runner_command"])
            self.assertIn("-PlanOnly", payload["trading_test_runner_command"])
            self.assertIn("run_trading_tests.ps1", payload["trading_test_full_command"])
            self.assertIn(payload["swarm_status"], {"SWARM_LIMITED", "SWARM_REVIEW_INCOMPLETE", "SWARM_CANCELLED_BY_USER"})
            self.assertEqual(payload["swarm_limited"], payload["swarm_status"] == "SWARM_LIMITED")
            self.assertFalse(payload["swarm_independent_review_available"])
            self.assertEqual(
                payload["visible_collect_preview_shortcut"],
                payload["visible_ws_collect_preview_shortcut"],
            )
            self.assertEqual(
                payload["visible_collect_confirmed_shortcut"],
                payload["visible_ws_collect_confirmed_shortcut"],
            )
            self.assertIn("start_ws_collect_visible.ps1", payload["visible_collect_command"])
            self.assertIn("start_funding_collect_visible.ps1", payload["funding_visible_collect_command"])
            self.assertIn("TRADING_PREVIEW_7D_FUNDING.cmd", payload["funding_visible_collect_preview_shortcut"])
            self.assertIn(
                "TRADING_START_7D_FUNDING_CONFIRMED.cmd",
                payload["funding_visible_collect_confirmed_shortcut"],
            )
        else:
            self.assertEqual(payload["visible_collect_command"], payload["funding_visible_collect_command"])
            self.assertEqual(
                payload["visible_collect_preview_shortcut"],
                payload["funding_visible_collect_preview_shortcut"],
            )

    def test_next_goal_legacy_visible_collect_follows_active_branch(self) -> None:
        script = REPO_ROOT / "tools" / "trading_next_goal_step.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "visible_collect_legacy_resolution",
            "visible_ws_collect_command_resolution",
            "visible_ws_collect_readiness",
            "collect_approval_contract",
            "ws_collect_approval_packet",
            "trading_ws_collect_approval_packet.ps1",
            "swarm_status",
            "swarm_limited",
            "swarm_independent_review_available",
            "trading_test_runner_plan",
            "trading_test_full",
            "run_trading_tests.ps1",
            "funding_visible_collect_preview",
            "funding_visible_collect_after_approval",
            "funding_visible_collect_preview_shortcut",
            "funding_visible_collect_confirmed_shortcut",
            "funding_basis_planonly",
            "structural_branch_planonly",
            "slow_liquidity_regime_planonly",
            "slow_liquidity_data_availability_preflight",
            "slow_liquidity_history_data_plan",
            "slow_liquidity_data_availability_rejected_gate",
            "slow_liquidity_history_data_plan_ready_gate",
            "cross_venue_rejected_gate",
            "listing_event_selected_gate",
            "slow_liquidity_regime_breakout_retest_planonly_selected_no_collect",
            "listing_event_drift_reversal_planonly_after_cross_venue_rejected",
            "funding_basis_planonly_after_liquidity_sweep_rejected",
            "redirected_to_ws_collect_because_funding_blocked_by_swarm",
            "visible_collect_after_approval = $visibleCollectCommand",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        commands = payload["commands"]
        if payload.get("decision") == "RESUME_OR_REJECT_INCOMPLETE_DATASET":
            self.assertEqual(payload["state"]["gate_status"], "STOPPED_INCOMPLETE")
            self.assertIn("visible_resume_current_run", payload["allowed_actions"])
            self.skipTest("active run gate is STOPPED_INCOMPLETE; next goal is resume/reject, not 72h command")

        if payload.get("decision") == "CROSS_VENUE_SPOT_BRANCH_CLOSED_SELECT_NEW_STRUCTURAL_HYPOTHESIS_PLANONLY":
            self.assertEqual(
                payload["state"]["branch_verdict"],
                "verified_rejected_no_net_edge_after_base_costs",
            )
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("preserve_verified_spot_branch_rejection", payload["allowed_actions"])
            self.assertIn("trading_structural_branch_planonly.ps1", payload["primary_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["structural_branch_planonly"])
            return

        if payload["state"].get("selected_branch") == "pit_linear_perp_cross_venue_forward_oos":
            self.assertEqual(
                payload["decision"],
                "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION",
            )
            self.assertTrue(payload["requires_user_approval"])
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("await_explicit_visible_collect_confirmation", payload["allowed_actions"])
            self.assertIn("start_pit_cross_venue_forward_oos_visible.ps1", commands["command_after_explicit_approval"])
            self.assertFalse(payload["state"]["strategy_accepted"])
            self.assertFalse(payload["state"]["replay_allowed"])
            return
        if payload["state"].get("selected_branch") == "forward_pit_universe_event_liquidity_anomaly":
            self.assertEqual(
                payload["decision"],
                "PIT_UNIVERSE_SNAPSHOT_COLLECT_AWAITING_EXPLICIT_CONFIRMATION",
            )
            self.assertTrue(payload["requires_user_approval"])
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "await_explicit_confirmation_for_visible_pit_snapshot_collect",
                payload["allowed_actions"],
            )
            self.assertIn("start_pit_universe_snapshot_collect_visible.ps1", commands["pit_universe_visible_collect"])
            self.assertIn("-PlanOnly", commands["pit_universe_visible_collect"])
        elif payload["state"].get("slow_liquidity_regime_selected_gate"):
            if payload["state"].get("slow_liquidity_history_data_plan_ready_gate"):
                self.assertEqual(
                    payload["decision"],
                    "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_AWAITING_EXPLICIT_APPROVAL",
                )
                self.assertTrue(payload["requires_user_approval"])
                self.assertTrue(payload["requires_user_approval_for_actual_collect"])
                self.assertIn("await explicit user approval", payload["primary_command"])
            elif payload["state"].get("slow_liquidity_data_availability_rejected_gate"):
                self.assertEqual(
                    payload["decision"],
                    "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_BUILD_HISTORY_PLAN",
                )
                self.assertIn("trading_slow_liquidity_history_data_plan.ps1", payload["primary_command"])
            elif payload["state"].get("slow_liquidity_data_availability_accepted_gate"):
                self.assertEqual(payload["decision"], "SLOW_LIQUIDITY_DATA_AVAILABILITY_ACCEPTED_DEFINE_FIXED_SIGNAL")
                self.assertIn("fixed v0 slow-liquidity signal", payload["primary_command"])
            else:
                self.assertEqual(
                    payload["decision"],
                    "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT",
                )
                self.assertIn("trading_slow_liquidity_data_availability_preflight.ps1", payload["primary_command"])
            if not payload["state"].get("slow_liquidity_history_data_plan_ready_gate"):
                self.assertFalse(payload["requires_user_approval"])
                self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_slow_liquidity_regime_breakout_retest_planonly", payload["allowed_actions"])
            self.assertIn("run_slow_liquidity_data_availability_preflight_planonly", payload["allowed_actions"])
            self.assertIn("trading_slow_liquidity_regime_breakout_retest_planonly.ps1", commands["slow_liquidity_regime_planonly"])
            self.assertIn(
                "trading_slow_liquidity_data_availability_preflight.ps1",
                commands["slow_liquidity_data_availability_preflight"],
            )
            self.assertIn(
                "trading_slow_liquidity_history_data_plan.ps1",
                commands["slow_liquidity_history_data_plan"],
            )
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "slow_liquidity_regime_breakout_retest_planonly_selected_no_collect",
            )
        elif payload["state"].get("spot_perp_basis_availability_awaiting_probe_gate"):
            self.assertEqual(
                payload["decision"],
                "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION",
            )
            self.assertTrue(payload["requires_user_approval"])
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "await_explicit_confirmation_for_short_public_spot_perp_availability_probe",
                payload["allowed_actions"],
            )
            self.assertIn("await explicit confirmation", payload["primary_command"])
            self.assertIn(
                "trading_spot_perp_basis_public_probe.ps1",
                commands["spot_perp_basis_public_probe_after_confirmation"],
            )
            self.assertIn("-ConfirmedPublicProbe", commands["spot_perp_basis_public_probe_after_confirmation"])
            self.assertEqual(payload["state"]["preflight_status"], "skipped_fast_path")
        elif payload["state"].get("listing_event_history_data_quality_rejected_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("revise_listing_event_history_collect_plan_planonly", payload["allowed_actions"])
            self.assertIn("trading_listing_event_history_data_quality.ps1", commands["listing_event_history_data_quality"])
            self.assertIn("trading_listing_event_history_planonly.ps1", commands["listing_event_history_recollect_plan"])
        elif payload["state"].get("listing_event_history_data_quality_pending_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_DATA_QUALITY_REQUIRED")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_listing_event_history_data_quality_gate", payload["allowed_actions"])
            self.assertIn("trading_listing_event_history_data_quality.ps1", commands["listing_event_history_data_quality"])
        elif payload["state"].get("listing_event_history_plan_ready_gate"):
            if payload["state"].get("listing_event_history_collect_preview_awaiting_approval_gate"):
                self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL")
                self.assertTrue(payload["requires_user_approval"])
                self.assertTrue(payload["requires_user_approval_for_actual_collect"])
                self.assertIn(
                    "await_explicit_user_approval_before_visible_history_collect",
                    payload["allowed_actions"],
                )
                self.assertIn("await explicit user approval", payload["primary_command"])
                self.assertIn("start_listing_event_history_collect_visible.ps1", commands["visible_collect_after_approval"])
                self.assertIn("-ConfirmedListingHistoryCollect", commands["visible_collect_after_approval"])
            else:
                self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_PLANONLY_RESEARCH")
                self.assertFalse(payload["requires_user_approval"])
                self.assertFalse(payload["requires_user_approval_for_actual_collect"])
                self.assertIn("run_listing_event_history_collect_preview_planonly", payload["allowed_actions"])
                self.assertIn("trading_listing_event_history_collect_preview.ps1", payload["primary_command"])
                self.assertIn("trading_listing_event_history_collect_preview.ps1", commands["visible_collect_after_approval"])
            self.assertIn("trading_listing_event_history_collect_preview.ps1", commands["visible_collect_preview"])
        elif payload["state"].get("listing_event_normalizer_ready_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_NORMALIZER_PLANONLY_RESEARCH")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_listing_event_normalizer_planonly", payload["allowed_actions"])
            self.assertIn("trading_listing_event_normalizer_planonly.ps1", payload["primary_command"])
            self.assertIn("trading_listing_event_normalizer_planonly.ps1", commands["visible_collect_after_approval"])
            self.assertIn("trading_listing_event_normalizer_planonly.ps1", commands["visible_collect_preview"])
        elif payload["state"].get("listing_event_history_availability_ready_gate"):
            self.assertEqual(
                payload["decision"],
                "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION",
            )
            self.assertTrue(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("await_explicit_confirmation_for_public_history_availability_probe", payload["allowed_actions"])
            self.assertIn("trading_listing_event_history_availability_preflight.ps1", payload["primary_command"])
            self.assertIn("-ConfirmedPublicProbe", payload["primary_command"])
        elif payload["state"].get("spot_perp_basis_availability_rejected_gate") or payload["state"].get("spot_perp_basis_rejected_gate"):
            self.assertEqual(payload["decision"], "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE")
            self.assertFalse(payload["state"]["spot_perp_basis_selected_gate"])
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("accept_spot_perp_basis_rejection_on_current_public_probe", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "spot_perp_basis_public_probe_rejected_select_next_non_hft_branch",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["primary_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["visible_collect_after_approval"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["visible_collect_preview"])
        elif payload["state"].get("listing_event_replay_rejected_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_SELECT_NEXT_BRANCH")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("accept_listing_event_drift_reversal_rejection_on_current_sample", payload["allowed_actions"])
            self.assertIn("run_structural_branch_planonly", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "listing_event_replay_rejected_select_next_non_hft_branch",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["primary_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["visible_collect_after_approval"])
        elif payload["state"].get("cross_venue_rejected_gate") or payload["state"].get("listing_event_selected_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_RESEARCH")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("build_listing_event_drift_reversal_planonly_scaffold", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "listing_event_drift_reversal_planonly_after_cross_venue_rejected",
            )
            self.assertIn("trading_listing_event_planonly.ps1", payload["primary_command"])
            self.assertIn("trading_listing_event_planonly.ps1", commands["visible_collect_after_approval"])
        elif payload["state"].get("funding_rejected_base_fees_gate"):
            self.assertEqual(payload["decision"], "DESIGN_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_structural_branch_planonly", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "next_non_hft_structural_branch_planonly_after_funding_rejected_base_fees",
            )
            self.assertIn("trading_structural_branch_planonly.ps1", payload["primary_command"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["visible_collect_after_approval"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["visible_collect_preview"])
            self.assertIn("trading_structural_branch_planonly.ps1", commands["structural_branch_planonly"])
        elif payload["state"].get("cross_venue_structural_selected_gate"):
            self.assertEqual(payload["decision"], "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("implement_cross_venue_dislocation_planonly_detector", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "cross_venue_dislocation_planonly_selected_no_collect",
            )
            self.assertIn("cross-venue spot dislocation", payload["primary_command"])
            self.assertIn("do not start collect/grid/live/API", commands["visible_collect_after_approval"])
        elif payload["state"].get("liquidity_sweep_rejected_gate"):
            self.assertEqual(payload["decision"], "FUNDING_BASIS_CARRY_STRUCTURAL_PLANONLY")
            self.assertFalse(payload["requires_user_approval"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_funding_basis_planonly", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "funding_basis_planonly_after_liquidity_sweep_rejected",
            )
            self.assertEqual(payload["primary_command"], commands["funding_basis_planonly"])
            self.assertEqual(commands["visible_collect_after_approval"], commands["funding_basis_planonly"])
            self.assertEqual(commands["visible_collect_preview"], commands["funding_basis_planonly"])
            self.assertIn("trading_funding_basis_planonly.ps1", commands["funding_basis_planonly"])
            self.assertIn("start_funding_collect_visible.ps1", commands["funding_visible_collect_after_approval"])
            self.assertIn("start_ws_collect_visible.ps1", commands["visible_ws_collect_after_approval"])
        elif payload["state"]["funding_blocked_by_swarm"]:
            resolution = commands["visible_ws_collect_command_resolution"]
            self.assertEqual(resolution["source"], "latest_plan_preview")
            self.assertEqual(resolution["effective_hours"], 72)
            self.assertIn("no_binance_dense_ws_sweep_20260628.csv", resolution["effective_universe_path"])
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertEqual(
                commands["visible_collect_legacy_resolution"],
                "redirected_to_ws_collect_because_funding_blocked_by_swarm",
            )
            self.assertEqual(commands["visible_collect_preview"], commands["visible_ws_collect_preview"])
            self.assertEqual(commands["visible_collect_after_approval"], commands["visible_ws_collect_after_approval"])
            self.assertIn("-Hours 72", payload["primary_command"])
            self.assertIn("-Hours 72", commands["visible_collect_after_approval"])
            self.assertNotIn("-Hours 6 -ConfirmedLongRun", commands["visible_collect_after_approval"])
            self.assertIn("TRADING_PREVIEW_DENSE_WS.cmd", commands["visible_ws_collect_preview_shortcut"])
            self.assertIn("TRADING_START_DENSE_WS_CONFIRMED.cmd", commands["visible_ws_collect_confirmed_shortcut"])
            self.assertIn("trading_ws_collect_readiness.ps1", commands["visible_ws_collect_readiness"])
            self.assertIn("trading_collect_approval_contract.ps1", commands["collect_approval_contract"])
            self.assertIn("trading_ws_collect_approval_packet.ps1", commands["ws_collect_approval_packet"])
            self.assertIn("trading_swarm_status.ps1", commands["swarm_status"])
            self.assertIn("run_trading_tests.ps1", commands["trading_test_runner_plan"])
            self.assertIn("-PlanOnly", commands["trading_test_runner_plan"])
            self.assertIn("run_trading_tests.ps1", commands["trading_test_full"])
            self.assertIn(payload["state"]["swarm_status"], {"SWARM_LIMITED", "SWARM_REVIEW_INCOMPLETE", "SWARM_CANCELLED_BY_USER"})
            self.assertEqual(
                payload["state"]["swarm_limited"],
                payload["state"]["swarm_status"] == "SWARM_LIMITED",
            )
            self.assertFalse(payload["state"]["swarm_independent_review_available"])
            self.assertIn("continue_manual_codex_when_swarm_limited", payload["allowed_actions"])
            self.assertEqual(
                commands["visible_collect_preview_shortcut"],
                commands["visible_ws_collect_preview_shortcut"],
            )
            self.assertEqual(
                commands["visible_collect_confirmed_shortcut"],
                commands["visible_ws_collect_confirmed_shortcut"],
            )
            self.assertEqual(payload["primary_command"], commands["visible_ws_collect_preview"])
            self.assertIn("start_ws_collect_visible.ps1", commands["visible_collect_after_approval"])
            self.assertIn(
                "start_funding_collect_visible.ps1",
                commands["funding_visible_collect_after_approval"],
            )
            self.assertIn(
                "TRADING_PREVIEW_7D_FUNDING.cmd",
                commands["funding_visible_collect_preview_shortcut"],
            )
            self.assertIn(
                "TRADING_START_7D_FUNDING_CONFIRMED.cmd",
                commands["funding_visible_collect_confirmed_shortcut"],
            )
        else:
            self.assertEqual(
                commands["visible_collect_after_approval"],
                commands["funding_visible_collect_after_approval"],
            )
            self.assertEqual(
                commands["visible_collect_confirmed_shortcut"],
                commands["funding_visible_collect_confirmed_shortcut"],
            )

    def test_branch_selector_blocks_stale_funding_next_action(self) -> None:
        script = REPO_ROOT / "tools" / "trading_branch_selector.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "branch_status_override",
            "original_scorecard_next_action",
            "blocked_by_swarm_do_not_run_7d_funding_collect_or_final_review",
            "postprocess_block_reasons",
            "visible_ws_collect_command_resolution",
            "funding_basis_carry_structural_planonly",
            "funding_basis_planonly_command",
            "structural_branch_planonly_command",
            "slow_liquidity_regime_planonly_command",
            "slow_liquidity_data_availability_preflight_command",
            "slow_liquidity_history_data_plan_command",
            "slow_liquidity_history_data_plan_ready_gate",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        if payload.get("decision") == "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION":
            self.assertEqual(payload["selected_branch"], "pit_linear_perp_cross_venue_forward_oos")
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("explicitly_confirm_visible_forward_oos_collect", payload["allowed_immediate_work"])
            self.assertIn("start_pit_cross_venue_forward_oos_visible.ps1", payload["primary_command"])
            self.assertFalse(payload["research_accepted"])
            self.assertFalse(payload["live_orders"])
            self.assertFalse(payload["api_keys"])
            self.assertFalse(payload["leverage_or_margin"])
            return
        funding = payload["selected_evidence"]["funding"]
        spot = payload["selected_evidence"]["spot_maker_liquidity_sweep_reversal"]

        self.assertIn("anufriev_strategy_scorecard_current_20260628.csv", payload["artifacts"]["scorecard"])
        if payload.get("decision") == "RESUME_OR_REJECT_INCOMPLETE_DATASET":
            self.skipTest("active run gate is STOPPED_INCOMPLETE; branch selector must resume/reject before selecting research branch")

        if payload.get("pit_universe_collect_ready_gate"):
            self.assertEqual(
                payload["decision"],
                "PIT_UNIVERSE_SNAPSHOT_COLLECT_AWAITING_EXPLICIT_CONFIRMATION",
            )
            self.assertEqual(payload["selected_branch"], "forward_pit_universe_event_liquidity_anomaly")
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "await_explicit_confirmation_for_visible_pit_snapshot_collect",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "start_pit_universe_snapshot_collect_visible.ps1",
                payload["artifacts"]["pit_universe_visible_collect_planonly_command"],
            )
            self.assertFalse(payload["research_accepted"])
            self.assertFalse(payload["live_orders"])
            self.assertFalse(payload["api_keys"])
            self.assertFalse(payload["leverage_or_margin"])
            self.assertIn("replay", payload["blocked_work"])
            self.assertIn("grid_search", payload["blocked_work"])
            return
        elif payload.get("slow_liquidity_regime_selected_gate"):
            if payload.get("slow_liquidity_history_data_plan_ready_gate"):
                self.assertEqual(
                    payload["decision"],
                    "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_AWAITING_EXPLICIT_APPROVAL",
                )
                self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            elif payload.get("slow_liquidity_data_availability_rejected_gate"):
                self.assertEqual(
                    payload["decision"],
                    "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_BUILD_HISTORY_PLAN",
                )
            elif payload.get("slow_liquidity_data_availability_accepted_gate"):
                self.assertEqual(payload["decision"], "SLOW_LIQUIDITY_DATA_AVAILABILITY_ACCEPTED_DEFINE_FIXED_SIGNAL")
            else:
                self.assertEqual(payload["decision"], "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_RESEARCH")
            self.assertEqual(payload["selected_branch"], "slow_liquidity_regime_breakout_retest")
            if not payload.get("slow_liquidity_history_data_plan_ready_gate"):
                self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "run_slow_liquidity_regime_breakout_retest_planonly",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "run_slow_liquidity_data_availability_preflight_planonly",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "trading_slow_liquidity_regime_breakout_retest_planonly.ps1",
                payload["artifacts"]["slow_liquidity_regime_planonly_command"],
            )
            self.assertIn(
                "trading_slow_liquidity_data_availability_preflight.ps1",
                payload["artifacts"]["slow_liquidity_data_availability_preflight_command"],
            )
            self.assertIn(
                "trading_slow_liquidity_history_data_plan.ps1",
                payload["artifacts"]["slow_liquidity_history_data_plan_command"],
            )
        elif payload.get("spot_perp_basis_availability_awaiting_probe_gate"):
            self.assertEqual(
                payload["decision"],
                "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION",
            )
            self.assertEqual(payload["selected_branch"], "spot_perp_basis_mean_reversion_no_funding")
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "await_explicit_confirmation_for_short_public_spot_perp_availability_probe",
                payload["allowed_immediate_work"],
            )
            self.assertEqual(payload["acceptance_stage"], "skipped_fast_path")
            self.assertIn(
                "trading_spot_perp_basis_public_probe.ps1",
                payload["artifacts"]["spot_perp_basis_public_probe_after_confirmation_command"],
            )
            self.assertIn(
                "-ConfirmedPublicProbe",
                payload["artifacts"]["spot_perp_basis_public_probe_after_confirmation_command"],
            )
            return
        elif payload.get("listing_event_history_data_quality_rejected_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN")
            self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "revise_listing_event_history_collect_plan_planonly",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "trading_listing_event_history_data_quality.ps1",
                payload["artifacts"]["listing_event_history_data_quality_command"],
            )
            self.assertIn(
                "trading_listing_event_history_planonly.ps1",
                payload["artifacts"]["listing_event_history_recollect_plan_command"],
            )
        elif payload.get("listing_event_history_data_quality_pending_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_DATA_QUALITY_REQUIRED")
            self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "run_listing_event_history_data_quality_gate",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "trading_listing_event_history_data_quality.ps1",
                payload["artifacts"]["listing_event_history_data_quality_command"],
            )
        elif payload.get("listing_event_history_plan_ready_gate"):
            if payload.get("listing_event_history_collect_preview_awaiting_approval_gate"):
                self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_AWAITING_EXPLICIT_APPROVAL")
                self.assertTrue(payload["requires_user_approval_for_actual_collect"])
                self.assertIn(
                    "await_explicit_user_approval_before_visible_history_collect",
                    payload["allowed_immediate_work"],
                )
            else:
                self.assertEqual(payload["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_PLANONLY_RESEARCH")
                self.assertFalse(payload["requires_user_approval_for_actual_collect"])
                self.assertIn(
                    "run_listing_event_history_collect_preview_planonly",
                    payload["allowed_immediate_work"],
                )
            self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
            self.assertIn(
                "trading_listing_event_history_collect_preview.ps1",
                payload["artifacts"]["listing_event_history_collect_preview_command"],
            )
            if payload.get("listing_event_history_collect_preview_awaiting_approval_gate"):
                self.assertIn(
                    "start_listing_event_history_collect_visible.ps1",
                    payload["artifacts"]["listing_event_history_collect_visible_after_approval_command"],
                )
                self.assertIn(
                    "-ConfirmedListingHistoryCollect",
                    payload["artifacts"]["listing_event_history_collect_visible_after_approval_command"],
                )
        elif payload.get("listing_event_normalizer_ready_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_NORMALIZER_PLANONLY_RESEARCH")
            self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "run_listing_event_normalizer_planonly",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "trading_listing_event_normalizer_planonly.ps1",
                payload["artifacts"]["listing_event_normalizer_planonly_command"],
            )
        elif payload.get("listing_event_history_availability_ready_gate"):
            self.assertEqual(
                payload["decision"],
                "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_AWAITING_PUBLIC_PROBE_CONFIRMATION",
            )
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "await_explicit_confirmation_for_public_history_availability_probe",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "trading_listing_event_history_availability_preflight.ps1",
                payload["artifacts"]["listing_event_history_availability_public_probe_after_confirmation_command"],
            )
        elif payload.get("spot_perp_basis_availability_rejected_gate") or payload.get("spot_perp_basis_rejected_gate"):
            self.assertEqual(payload["decision"], "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE")
            self.assertEqual(payload["selected_branch"], "next_non_hft_structural_branch")
            self.assertFalse(payload["spot_perp_basis_selected_gate"])
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "accept_spot_perp_basis_rejection_on_current_public_probe",
                payload["allowed_immediate_work"],
            )
            self.assertIn(
                "trading_structural_branch_planonly.ps1",
                payload["artifacts"]["structural_branch_planonly_command"],
            )
        elif payload.get("listing_event_replay_rejected_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_SELECT_NEXT_BRANCH")
            self.assertEqual(payload["selected_branch"], "next_non_hft_structural_branch")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "accept_listing_event_drift_reversal_rejection_on_current_sample",
                payload["allowed_immediate_work"],
            )
            self.assertIn("run_structural_branch_planonly", payload["allowed_immediate_work"])
            self.assertIn(
                "trading_structural_branch_planonly.ps1",
                payload["artifacts"]["structural_branch_planonly_command"],
            )
        elif payload.get("cross_venue_rejected_gate") or payload.get("listing_event_selected_gate"):
            self.assertEqual(payload["decision"], "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_RESEARCH")
            self.assertEqual(payload["selected_branch"], "listing_event_drift_reversal")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "build_listing_event_drift_reversal_planonly_scaffold",
                payload["allowed_immediate_work"],
            )
        elif payload.get("funding_rejected_base_fees_gate"):
            self.assertEqual(payload["decision"], "SELECT_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY")
            self.assertEqual(payload["selected_branch"], "new_non_hft_structural_branch_planonly")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_structural_branch_planonly", payload["allowed_immediate_work"])
            self.assertIn(
                "trading_structural_branch_planonly.ps1",
                payload["artifacts"]["structural_branch_planonly_command"],
            )
        elif payload.get("cross_venue_structural_selected_gate"):
            self.assertEqual(payload["decision"], "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH")
            self.assertEqual(payload["selected_branch"], "cross_venue_spot_dislocation_inventory_rebalance")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn(
                "implement_cross_venue_dislocation_planonly_detector",
                payload["allowed_immediate_work"],
            )
        elif payload.get("liquidity_sweep_rejected_gate"):
            self.assertEqual(payload["decision"], "NEXT_BRANCH_FUNDING_BASIS_CARRY_PLANONLY")
            self.assertEqual(payload["selected_branch"], "funding_basis_carry_structural_planonly")
            self.assertFalse(payload["requires_user_approval_for_actual_collect"])
            self.assertIn("run_funding_basis_planonly", payload["allowed_immediate_work"])
            self.assertIn("trading_funding_basis_planonly.ps1", payload["artifacts"]["funding_basis_planonly_command"])
        else:
            resolution = payload["artifacts"]["visible_ws_collect_command_resolution"]
            self.assertEqual(resolution["source"], "latest_plan_preview")
            self.assertEqual(resolution["effective_hours"], 72)
            self.assertIn("no_binance_dense_ws_sweep_20260628.csv", resolution["effective_universe_path"])
            self.assertTrue(payload["requires_user_approval_for_actual_collect"])
            self.assertTrue(payload["artifacts"]["visible_ws_collect_requires_user_approval"])
            self.assertIn("-Hours 72", payload["artifacts"]["visible_ws_collect_plan"])
            self.assertIn("-Hours 72", payload["artifacts"]["visible_ws_collect_after_approval"])
            self.assertIn("-UniversePath", payload["artifacts"]["visible_ws_collect_after_approval"])
            self.assertNotIn("-Hours 6 -ConfirmedLongRun", payload["artifacts"]["visible_ws_collect_after_approval"])
            self.assertIn("TRADING_PREVIEW_DENSE_WS.cmd", payload["artifacts"]["visible_ws_collect_preview_shortcut"])
            self.assertIn("TRADING_START_DENSE_WS_CONFIRMED.cmd", payload["artifacts"]["visible_ws_collect_confirmed_shortcut"])
        self.assertEqual(spot["trades"], "11")
        self.assertEqual(spot["verdict"], "rejected")
        self.assertIn("ws_grid_search_ws_confirmed_research_6h_20260628_103700.json", spot["evidence"])

        if payload["funding_blocked_by_swarm"]:
            self.assertEqual(funding["branch_status_override"], "blocked_by_swarm")
            self.assertTrue(funding["original_scorecard_next_action"])
            self.assertIn("blocked_by_swarm_do_not_run_7d_funding_collect", funding["next_action"])
            if "visible 7d collect" in funding["original_scorecard_next_action"]:
                self.assertNotIn("visible 7d collect", funding["next_action"])
            if "postprocess_block_reasons" in funding:
                self.assertTrue(
                    any("min_min_rows_per_cycle" in reason for reason in funding["postprocess_block_reasons"])
                )
                self.assertEqual(funding["min_rows_per_cycle"], 9)

    def test_goal_status_uses_current_scorecard_not_active_gate_for_funding_summary(self) -> None:
        script = REPO_ROOT / "tools" / "trading_goal_status.ps1"
        text = script.read_text(encoding="utf-8")

        for needle in (
            "anufriev_strategy_scorecard_current_20260628.csv",
            "Get-SummaryMetric",
            "fundingSummaryFromScorecard",
            "gate_rows",
        ):
            self.assertIn(needle, text)

        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)

        self.assertIn("anufriev_strategy_scorecard_current_20260628.csv", payload["scorecard"])
        if payload["funding_blocked_by_swarm"]:
            summary_rows = re.search(
                r"(?:^|;\s*)rows=([0-9]+(?:\.[0-9]+)?)",
                payload["funding_current_summary"],
            )
            if summary_rows:
                self.assertEqual(float(payload["funding_rows"]), float(summary_rows.group(1)))
            else:
                self.assertEqual(payload["funding_rows"], payload["gate_rows"])
            if "min_rows_per_cycle=9.0" not in payload["funding_current_summary"]:
                self.assertIn("win_rate=", payload["funding_current_summary"])
            self.assertIn("Рой L1/L2 decision=block", payload["funding_current_summary"])


if __name__ == "__main__":
    unittest.main()
