from __future__ import annotations

import csv
import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN = (
    ROOT
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
)
UNIVERSE = (
    ROOT
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-universe-20260812-pagecapfix-v1.csv"
)
LAUNCHER = ROOT / "tools" / "start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
FREEZER = ROOT / "tools" / "freeze_exact_approved_slow_liquidity_history_recollect.ps1"
CONTROL_PLANE = ROOT / "trading_mvp" / "src" / "slow_liquidity_recollect_control_plane.py"
QUALITY_RUNNER = ROOT / "tools" / "run_exact_slow_liquidity_recollect_quality.ps1"
QUALITY_WRAPPER = ROOT / "tools" / "trading_slow_liquidity_history_data_quality.ps1"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SlowLiquidityRecollectPlanTests(unittest.TestCase):
    def test_frozen_universe_has_exact_identity_bound_assets(self) -> None:
        with UNIVERSE.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(
            [row["symbol"] for row in rows],
            ["STETH", "WEETH", "CC", "OKB", "RAIN", "MNT", "USDD", "BDX", "EDGE"],
        )
        self.assertEqual(len({row["symbol"] for row in rows}), 9)
        self.assertEqual(
            {row["symbol"]: row["coin_id"] for row in rows},
            {
                "STETH": "steth-lido-staked-ether",
                "WEETH": "weeth-wrapped-eeth",
                "CC": "cc-canton-network",
                "OKB": "okb-okb",
                "RAIN": "rain-rain-protocol",
                "MNT": "mnt-mantle",
                "USDD": "usdd-usdd",
                "BDX": "bdx-beldex",
                "EDGE": "edge-edgex",
            },
        )

    def test_plan_is_hash_bound_planonly_with_fixed_costs_and_scope(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(
            plan["schema"],
            "trading_mvp_slow_liquidity_history_recollect_planonly_v1",
        )
        self.assertEqual(plan["status"], "AWAIT_EXACT_HASH_BOUND_APPROVAL")
        self.assertFalse(plan["actual_collection_allowed"])
        self.assertEqual(plan["universe"]["bases"], [
            "STETH", "WEETH", "CC", "OKB", "RAIN", "MNT", "USDD", "BDX", "EDGE"
        ])
        self.assertFalse(plan["universe"]["identity_bound"])
        self.assertFalse(plan["universe"]["ticker_match_is_identity_evidence"])
        self.assertEqual(plan["universe"]["known_source_symbol_collisions"], ["EDGE", "RAIN"])
        self.assertTrue(plan["universe"]["official_identity_verification_required_after_quality"])
        self.assertFalse(
            plan["data_quality_after_success"][
                "fixed_signal_plan_allowed_before_identity_verification"
            ]
        )
        approval_template = plan["approval_request"]["exact_user_text_template"]
        self.assertEqual(approval_template.count("<PLAN_HASH>"), 1)
        self.assertEqual(approval_template.count("<PLAN_FILE_SHA256>"), 1)
        quality_command = plan["commands"]["data_quality_after_complete"]
        self.assertIn(str(QUALITY_RUNNER), quality_command)
        self.assertIn("<RECEIPT_SHA256>", quality_command)
        self.assertNotIn("trading_slow_liquidity_history_data_quality.ps1", quality_command)
        self.assertEqual(
            plan["commands"]["data_quality_after_complete_runner"],
            str(QUALITY_RUNNER),
        )
        self.assertFalse(
            plan["data_quality_after_success"]["direct_generic_wrapper_actual_allowed"]
        )
        self.assertTrue(
            plan["data_quality_after_success"]["active_gate_update_requires_exact_runner"]
        )
        self.assertIn(
            "freeze_exact_approved_slow_liquidity_history_recollect.ps1",
            plan["commands"]["freeze_after_exact_approval"],
        )
        execution = plan["execution"]
        self.assertEqual(execution["exchanges"], ["mexc", "gateio"])
        self.assertEqual(execution["timeframes"], ["1h", "4h"])
        self.assertEqual(execution["history_days"], 56)
        self.assertEqual(execution["target_bases"], 9)
        self.assertEqual(execution["logical_requests"], 63)
        self.assertEqual(execution["maximum_http_attempts"], 126)
        self.assertEqual(execution["max_runtime_sec"], 900)
        self.assertEqual(execution["hard_output_cap_bytes"], 100_000_000)
        self.assertFalse(execution["resume_allowed"])
        self.assertTrue(execution["visible_terminal_required"])
        self.assertTrue(execution["single_global_writer_required"])

        canonical_plan = dict(plan)
        expected_hash = canonical_plan.pop("plan_hash")
        canonical = json.dumps(
            canonical_plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected_hash)

        self.assertEqual(plan["universe"]["sha256"], file_sha256(UNIVERSE))
        self.assertEqual(plan["launcher"]["sha256"], file_sha256(LAUNCHER))
        for binding in plan["implementation"]["files"]:
            path = Path(binding["path"])
            self.assertTrue(path.is_file(), binding["path"])
            if binding["role"] == "active_run_gate_checker":
                self.assertNotEqual(binding["sha256"], file_sha256(path))
                continue
            self.assertEqual(binding["sha256"], file_sha256(path))

    def test_v6_binds_provenance_slot_integrity_and_unique_quality_namespace(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        run_id = (
            "slow_liquidity_history_recollect_20260813_"
            "pagecap_provenance_slotintegrity_v6"
        )
        self.assertEqual(plan["plan_id"], run_id)
        self.assertEqual(plan["execution"]["run_id"], run_id)

        quality_output = plan["data_quality_after_success"]["output_path"]
        self.assertIn("provenance_slotintegrity_v6", quality_output)
        self.assertNotIn("pagecapfix_v1", quality_output)
        self.assertNotIn("alignmentfix_v2", quality_output)
        self.assertNotIn("qualitygridfix_v3", quality_output)
        self.assertNotIn("qualityintegrityfix_v4", quality_output)
        self.assertNotIn("qualityintegrity_rangefix_v5", quality_output)

        wrapper_text = QUALITY_WRAPPER.read_text(encoding="utf-8-sig")
        self.assertIn(run_id, wrapper_text)
        self.assertIn(quality_output, wrapper_text)

        row_integrity = plan["implementation"]["row_integrity"]
        for required in (
            "exact_quote_symbol_job_key_binding_required",
            "finite_numeric_ohlcv_required",
            "positive_prices_required",
            "nonnegative_volumes_required",
            "trade_count_optional_nonnegative_integer_required",
            "ok_error_must_be_empty",
            "placeholder_market_payload_must_be_null",
        ):
            self.assertTrue(row_integrity[required], required)
        self.assertFalse(row_integrity["invalid_rows_count_toward_quality_thresholds"])
        for required in (
            "manifest_rows_match_output",
            "manifest_ohlcv_rows_match_ok_status",
            "manifest_placeholder_rows_match_non_ok_status",
            "manifest_errors_match_api_error_status",
            "manifest_status_counts_match_output",
            "all_expected_cartesian_slots_required",
        ):
            self.assertTrue(row_integrity[required], required)
        self.assertFalse(row_integrity["mixed_ok_and_placeholder_slots_allowed"])
        self.assertFalse(row_integrity["duplicate_placeholder_slots_allowed"])

        timestamp_integrity = plan["implementation"]["timestamp_integrity"]
        self.assertTrue(
            timestamp_integrity[
                "row_history_window_matches_manifest_days_required"
            ]
        )
        self.assertTrue(
            timestamp_integrity["normal_wall_clock_start_must_be_quality_compatible"]
        )
        for required in (
            "history_anchor_bound_to_collection_start",
            "history_anchor_iso_matches_timestamp",
            "row_ranges_match_anchor_and_history_days",
            "row_iso_fields_match_integer_timestamps",
            "launch_manifest_time_chain_required",
        ):
            self.assertTrue(timestamp_integrity[required], required)
        quality_timestamp_integrity = plan["data_quality_after_success"][
            "timestamp_integrity"
        ]
        self.assertEqual(
            quality_timestamp_integrity["max_history_window_mismatch_slots"],
            0,
        )
        self.assertTrue(
            quality_timestamp_integrity[
                "history_window_must_match_manifest_days"
            ]
        )

        limits = plan["data_quality_after_success"]["row_integrity"]
        for key, value in limits.items():
            if key.startswith("max_"):
                self.assertEqual(value, 0, key)
        self.assertTrue(limits["valid_ok_rows_only_for_thresholds"])

        self.assertEqual(
            plan["supersedes"]["disposition"],
            "SUPERSEDED_PROVENANCE_AND_SLOT_INTEGRITY_"
            "FAIL_CLOSED_NOT_LAUNCHABLE",
        )

    def test_launcher_is_visible_single_use_and_fail_closed(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8-sig")
        for required in (
            "VISIBLE_TERMINAL_LAUNCHED",
            "terminal_ownership_verified",
            "WindowStyle Normal",
            '"-NoExit"',
            "active-market-data-writer-claim.json",
            "global_market_writer_claim.py",
            "MaxRuntimeSec",
            "Hard output cap exceeded",
            "STOPPED_INCOMPLETE_NO_RETRY",
            "BLOCKED_AWAITING_EXACT_APPROVAL",
            "ExpectedApprovalReceiptSha256",
            "slow_liquidity_recollect_control_plane.py",
            "policy_rebind_missing_or_invalid",
            "guard.policy_hash",
            "GetConsoleWindow",
            "IsWindowVisible",
            "visible_console_not_verified",
            "current-run.json",
            "active_run_pointer_v1",
        ):
            self.assertIn(required, text)

        self.assertNotIn("--resume", text)
        self.assertNotIn("-ResumeIncomplete", text)

    def test_launcher_auto_limits_kill_writer_before_terminal_cleanup(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8-sig")
        limit_blocks = (
            (
                r"if \(\$size -gt \$hardOutputCapBytes\) \{.*?"
                r"Stop-Process -Id \$writerProcess\.Id -Force.*?"
                r'throw "Hard output cap exceeded:',
                "output cap",
            ),
            (
                r"if \(\$stopwatch\.Elapsed\.TotalSeconds -ge \$maxRuntimeSec\) \{.*?"
                r"Stop-Process -Id \$writerProcess\.Id -Force.*?"
                r'throw "Exact recollect exceeded MaxRuntimeSec=',
                "runtime cap",
            ),
            (
                r"if \(\[DateTimeOffset\]::Now -ge \$hardDeadline\) \{.*?"
                r"Stop-Process -Id \$writerProcess\.Id -Force.*?"
                r'throw "Exact recollect reached its hard deadline',
                "hard deadline",
            ),
        )
        for pattern, label in limit_blocks:
            self.assertRegex(text, re.compile(pattern, re.DOTALL), label)

        catch_block = re.search(r"\} catch \{(?P<body>.*)\}\s*$", text, re.DOTALL)
        self.assertIsNotNone(catch_block)
        body = catch_block.group("body")
        for required in (
            '"--final-status", "STOPPED_INCOMPLETE"',
            'Set-LaunchRecord $launchRecord $launchRecordPath "STOPPED_INCOMPLETE"',
            '"SLOW_LIQUIDITY_HISTORY_RECOLLECT_STOPPED_INCOMPLETE_NO_RETRY"',
            '"$failure No retry is authorized."',
        ):
            self.assertIn(required, body)

    def test_approval_freezer_is_offline_fail_closed_and_bound(self) -> None:
        self.assertTrue(FREEZER.is_file())
        self.assertTrue(CONTROL_PLANE.is_file())
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        bindings = {item["role"]: item for item in plan["implementation"]["files"]}
        self.assertEqual(
            bindings["approval_control_plane"]["sha256"],
            file_sha256(CONTROL_PLANE),
        )
        self.assertEqual(
            bindings["approval_rebind_tool"]["sha256"], file_sha256(FREEZER)
        )
        self.assertEqual(
            bindings["exact_quality_runner"]["sha256"], file_sha256(QUALITY_RUNNER)
        )

        text = FREEZER.read_text(encoding="utf-8-sig")
        for required in (
            "AWAIT_EXACT_USER_APPROVAL",
            "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL",
            "check_trading_mvp_autopilot.ps1",
            "active-market-data-writer-claim.json",
            "Write-FileCreateNew",
            '"render"',
            '"validate"',
            "precommit_source_state_changed",
            "Rollback-AppliedControlPlane",
            "receipt_created_by_this_process",
        ):
            self.assertIn(required, text)
        self.assertNotIn("Start-Process", text)
        self.assertNotIn("Invoke-WebRequest", text)

    def test_exact_quality_runner_is_bound_and_fail_closed(self) -> None:
        self.assertTrue(QUALITY_RUNNER.is_file())
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.assertEqual(
            plan["data_quality_after_success"]["exact_runner_sha256"],
            file_sha256(QUALITY_RUNNER),
        )

        text = QUALITY_RUNNER.read_text(encoding="utf-8-sig")
        for required in (
            "validate-quality",
            "ExpectedApprovalReceiptSha256",
            "launch_record_path",
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
            "TERMINAL_DATA_QUALITY_REJECT_NO_RETRY_WITHOUT_NEW_EXACT_APPROVAL",
            "retry_authorized",
            "rescope_authorized",
            "originalGateBytes",
            "originalPointerBytes",
            "current-run.json",
            "active_run_pointer_v1",
        ):
            self.assertIn(required, text)
        self.assertNotIn("-UpdateGate", text)
        self.assertNotIn("Invoke-WebRequest", text)
        self.assertIn(
            "quality_output_sha256_mismatch",
            CONTROL_PLANE.read_text(encoding="utf-8-sig"),
        )

        wrapper_text = QUALITY_WRAPPER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "Exact recollect gate updates require "
            "run_exact_slow_liquidity_recollect_quality.ps1",
            wrapper_text,
        )
        self.assertIn(
            "The exact recollect final quality report is owned by "
            "run_exact_slow_liquidity_recollect_quality.ps1",
            wrapper_text,
        )


if __name__ == "__main__":
    unittest.main()
