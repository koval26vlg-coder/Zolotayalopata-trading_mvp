from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COUNTDOWN_WRAPPER = (
    REPO_ROOT / "tools" / "start_approved_pit_segment_countdown_visible.ps1"
)
VISIBLE_WRAPPER = (
    REPO_ROOT / "tools" / "start_pit_universe_snapshot_collect_visible.ps1"
)
SCHEDULE_PLANNER = REPO_ROOT / "trading_mvp" / "src" / "night_schedule_plan.py"


class AutopilotVisiblePipelineTests(unittest.TestCase):
    def test_countdown_authorizes_segment_before_plan_and_before_collect(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        initial_call = source.index(
            "$initialAuthorization = Invoke-SegmentAuthorization"
        )
        plan_only_exit = source.index("if ($PlanOnly)")
        window_call = source.index(
            "$windowAuthorization = Invoke-SegmentAuthorization"
        )
        collector_call = source.index(
            "& pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleWrapper `",
            window_call,
        )

        self.assertLess(initial_call, plan_only_exit)
        self.assertLess(window_call, collector_call)

    def test_authorization_failure_preserves_fail_closed_reason(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("2>&1", source)
        self.assertIn(
            'throw "Hash-bound segment authorization failed: $detail"',
            source,
        )

    def test_runtime_preflight_is_read_only_and_precedes_metadata_write(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("[switch]$PreflightOnly", source)
        preflight_call = source.index("$runtimePreflight = Invoke-RuntimePreflight")
        preflight_exit = source.index("if ($PreflightOnly)", preflight_call)
        metadata_write = source.index(
            'Set-MetadataStatus -Status "WAITING_FOR_APPROVED_WINDOW"',
            preflight_exit,
        )

        self.assertLess(preflight_call, preflight_exit)
        self.assertLess(preflight_exit, metadata_write)
        self.assertIn('side_effects = "NO_RUN_OR_OUTPUT_WRITES"', source)

    def test_runtime_preflight_binds_pointer_guard_and_duplicate_owner(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("trading-mvp-autopilot-schedule-pointer.json", source)
        self.assertIn(
            'classification -ne "PREAPPROVED_SHORT_SEGMENT"',
            source,
        )
        self.assertIn("Get-OtherCountdownOwners", source)
        self.assertIn('"COUNTDOWN_ALREADY_RUNNING"', source)
        self.assertIn("etaSec -le 300", source)

    def test_countdown_independently_verifies_all_sealed_runtime_tools(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        helper = source.index("function Assert-SealedRuntimeTools")
        runtime_preflight = source.index("function Invoke-RuntimePreflight")
        helper_call = source.index(
            "$sealedRuntimeTools = @(Assert-SealedRuntimeTools -Plan $Plan)",
            runtime_preflight,
        )
        pointer_check = source.index(
            "Dynamic PIT schedule pointer is missing",
            helper_call,
        )
        initial_audit = source.index(
            "$initialSealedRuntimeTools = @(Assert-SealedRuntimeTools -Plan $plan)"
        )
        initial_authorization = source.index(
            "$initialAuthorization = Invoke-SegmentAuthorization"
        )

        self.assertLess(helper, runtime_preflight)
        self.assertLess(helper_call, pointer_check)
        self.assertLess(initial_audit, initial_authorization)
        self.assertIn("$runtimeTools.PSObject.Properties", source)
        self.assertIn("Get-FileHash -LiteralPath $toolPath -Algorithm SHA256", source)
        self.assertIn("Sealed runtime tool hash mismatch", source)
        self.assertIn("schedule_planner = $planCli", source)
        self.assertIn("visible_wrapper = $visibleWrapper", source)
        self.assertIn("sealed_runtime_tools_verified", source)

    def test_countdown_opens_and_verifies_a_normal_visible_terminal(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        launch_allowed = source.index(
            'if (-not $runtimePreflight.launch_allowed_now) {'
        )
        visible_branch = source.index("if (-not $VisibleChild) {")
        terminal_launch = source.index(
            "$terminal = Start-Process",
            visible_branch,
        )
        ownership_check = source.index(
            "terminal_ownership_verified = $true",
            terminal_launch,
        )
        countdown_owner_write = source.index(
            'Set-MetadataStatus -Status "WAITING_FOR_APPROVED_WINDOW"',
            ownership_check,
        )

        self.assertLess(launch_allowed, visible_branch)
        self.assertLess(visible_branch, terminal_launch)
        self.assertLess(terminal_launch, ownership_check)
        self.assertLess(ownership_check, countdown_owner_write)
        self.assertIn("-WindowStyle Normal", source[terminal_launch:ownership_check])
        self.assertIn('"-NoExit"', source[visible_branch:terminal_launch])
        self.assertIn('"-VisibleChild"', source[visible_branch:terminal_launch])
        self.assertIn(
            "[int]$candidateMetadata.countdown_pid -eq $terminal.Id",
            source[terminal_launch:ownership_check],
        )
        self.assertIn(
            "did not claim the exact countdown within 30 seconds",
            source[terminal_launch:ownership_check],
        )

    def test_runtime_hash_drift_fails_before_authorization_or_writes(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")

        def sealed_entry(path: Path) -> dict[str, str]:
            return {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        run_id = f"countdown_hash_mismatch_{uuid.uuid4().hex}"
        metadata_path = (
            REPO_ROOT / "docs" / "agent-log" / "run-gates" / f"{run_id}.countdown.json"
        )
        launch_path = (
            REPO_ROOT / "docs" / "agent-log" / "run-gates" / f"{run_id}.launch.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "tampered-runtime-plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "sealed_schedule": {
                            "runtime_tools": {
                                "schedule_planner": sealed_entry(SCHEDULE_PLANNER),
                                "visible_wrapper": sealed_entry(VISIBLE_WRAPPER),
                                "collector": {
                                    "path": str(COUNTDOWN_WRAPPER.resolve()),
                                    "sha256": "0" * 64,
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(COUNTDOWN_WRAPPER),
                    "-SchedulePlanPath",
                    str(plan_path),
                    "-ExpectedSchedulePlanHash",
                    "0" * 64,
                    "-RunId",
                    run_id,
                    "-PlanOnly",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        output = f"{completed.stdout}\n{completed.stderr}"
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Sealed runtime tool hash mismatch: collector", output)
        self.assertNotIn("Hash-bound segment authorization failed", output)
        self.assertFalse(metadata_path.exists())
        self.assertFalse(launch_path.exists())

    def test_window_open_repeats_full_preflight_before_collector(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        window_authorization = source.index(
            "$windowAuthorization = Invoke-SegmentAuthorization"
        )
        launch_preflight = source.index(
            "$launchPreflight = Invoke-RuntimePreflight",
            window_authorization,
        )
        exact_due_check = source.index(
            '[string]$launchPreflight.schedule_status -ne "DUE"',
            launch_preflight,
        )
        collector_call = source.index(
            "& pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleWrapper `",
            exact_due_check,
        )

        self.assertLess(window_authorization, launch_preflight)
        self.assertLess(launch_preflight, exact_due_check)
        self.assertLess(exact_due_check, collector_call)
        self.assertIn(
            "Fresh launch preflight no longer authorizes the exact DUE segment",
            source,
        )
        self.assertEqual(source.count("Invoke-RuntimePreflight `"), 2)
        self.assertEqual(source.count("-Plan $plan `"), 2)

    def test_collector_and_postrun_are_exact_and_fail_closed(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        collector_call = source.index(
            "& pwsh -NoProfile -ExecutionPolicy Bypass -File $visibleWrapper `"
        )
        collector_exit = source.index(
            "if ($collectorExitCode -ne 0)",
            collector_call,
        )
        gate_check = source.index(
            "$collectorGateJson = & pwsh "
            "-NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json",
            collector_exit,
        )
        ready_check = source.index(
            '[string]$collectorGate.status -ne "READY_FOR_POSTPROCESS"',
            gate_check,
        )
        run_id_check = source.index(
            "[string]$collectorGate.run_id -ne $RunId",
            ready_check,
        )
        collector_finished = source.index(
            'Set-MetadataStatus -Status "COLLECTOR_FINISHED"',
            run_id_check,
        )
        postrun_running = source.index(
            'Set-MetadataStatus -Status "POSTRUN_RUNNING"',
            collector_finished,
        )
        postrun_call = source.index(
            "& pwsh -NoProfile -ExecutionPolicy Bypass -File $postRun `",
            postrun_running,
        )
        postrun_exit = source.index(
            'throw "PIT post-run failed with exit code $LASTEXITCODE."',
            postrun_call,
        )
        postrun_finished = source.index(
            '-Status "POSTRUN_FINISHED"',
            postrun_exit,
        )
        failure_handler = source.index(
            'Set-MetadataStatus -Status "FAILED"',
            postrun_finished,
        )

        self.assertLess(collector_call, collector_exit)
        self.assertLess(collector_exit, gate_check)
        self.assertLess(gate_check, ready_check)
        self.assertLess(ready_check, run_id_check)
        self.assertLess(run_id_check, collector_finished)
        self.assertLess(collector_finished, postrun_running)
        self.assertLess(postrun_running, postrun_call)
        self.assertLess(postrun_call, postrun_exit)
        self.assertLess(postrun_exit, postrun_finished)
        self.assertLess(postrun_finished, failure_handler)
        self.assertIn("-SchedulePlanPath $SchedulePlanPath `", source[postrun_call:])
        self.assertIn(
            "-ExpectedSchedulePlanHash $ExpectedSchedulePlanHash `",
            source[postrun_call:],
        )
        self.assertIn("-RunId $RunId `", source[postrun_call:])

    def test_postrun_zero_exit_requires_fresh_bound_summary(self) -> None:
        source = COUNTDOWN_WRAPPER.read_text(encoding="utf-8-sig")

        postrun_call = source.index(
            "& pwsh -NoProfile -ExecutionPolicy Bypass -File $postRun `"
        )
        exit_check = source.index(
            'throw "PIT post-run failed with exit code $LASTEXITCODE."',
            postrun_call,
        )
        summary_exists = source.index(
            "Test-Path -LiteralPath $postRunSummaryPath -PathType Leaf",
            exit_check,
        )
        summary_read = source.index(
            "Get-Content -LiteralPath $postRunSummaryPath -Raw",
            summary_exists,
        )
        identity_check = source.index(
            "PIT post-run durable summary identity or schedule binding mismatch.",
            summary_read,
        )
        freshness_check = source.index(
            "PIT post-run durable summary is stale.",
            identity_check,
        )
        embargo_check = source.index(
            "PIT post-run durable summary violated its decision or data embargo contract.",
            freshness_check,
        )
        summary_hash = source.index(
            '$script:metadata["postrun_summary_sha256"]',
            embargo_check,
        )
        deferred_status = source.index(
            '-Status "POSTRUN_DEFERRED"',
            summary_hash,
        )
        finished_status = source.index(
            '-Status "POSTRUN_FINISHED"',
            deferred_status,
        )

        self.assertLess(postrun_call, exit_check)
        self.assertLess(exit_check, summary_exists)
        self.assertLess(summary_exists, summary_read)
        self.assertLess(summary_read, identity_check)
        self.assertLess(identity_check, freshness_check)
        self.assertLess(freshness_check, embargo_check)
        self.assertLess(embargo_check, summary_hash)
        self.assertLess(summary_hash, deferred_status)
        self.assertLess(deferred_status, finished_status)
        self.assertIn(
            '"wait_for_fresh_weekly_quota_above_15_percent_then_retry_postrun"',
            source,
        )
        self.assertIn('"run_train_feasibility_after_weekly_quota_reset"', source)
        self.assertIn(
            '"refresh_horizon_after_weekly_quota_reset_then_request_exact_schedule_approval"',
            source,
        )
        for field in (
            "returns_read",
            "pnl_read",
            "oos_run",
            "grid_search",
            "live_orders",
            "private_api_keys",
        ):
            self.assertIn(f"$postRunSummary.{field} -ne $false", source)

    def test_visible_writer_reauthorizes_stage_before_gate_mutation(self) -> None:
        source = VISIBLE_WRAPPER.read_text(encoding="utf-8-sig")

        authorization = source.index(
            "$stageAuthorizationJson = & $Python "
            "$nightScheduleValidatorPath authorize-segment"
        )
        running_gate = source.index(
            'Set-JsonProperty -Object $gateDoc -Name "status" -Value "RUNNING"'
        )

        self.assertLess(authorization, running_gate)
        self.assertIn(
            "Collection-stage authorization did not return AUTHORIZED",
            source,
        )


if __name__ == "__main__":
    unittest.main()
