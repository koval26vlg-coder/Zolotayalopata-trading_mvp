from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
POSTRUN_WRAPPER = REPO_ROOT / "tools" / "run_trading_mvp_pit_postrun.ps1"
AUTOPILOT_POLICY = (
    REPO_ROOT / "docs" / "plans" / "trading-mvp-autopilot-policy-v1.json"
)


class PitPostrunPolicyTests(unittest.TestCase):
    def test_exact_pointer_is_checked_before_plan_only_or_mutation(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        runtime_check = source.index(
            "$sealedRuntimeTools = Assert-SealedRuntimeTools -Plan $plan"
        )
        pointer_check = source.index("Assert-ExactSchedulePointer -Plan $plan")
        plan_only = source.index("if ($PlanOnly)", pointer_check)
        quality_output = source.index(
            'New-Item -ItemType Directory -Path $QualityReportRoot',
            plan_only,
        )

        self.assertLess(runtime_check, pointer_check)
        self.assertLess(pointer_check, plan_only)
        self.assertLess(plan_only, quality_output)
        self.assertIn("Dynamic PIT schedule pointer hash mismatch.", source)
        self.assertIn("Dynamic PIT schedule pointer quality ledger mismatch.", source)

    def test_every_sealed_runtime_tool_is_hash_checked_before_postrun(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("foreach ($property in $runtimeTools.PSObject.Properties)", source)
        self.assertIn(
            "Sealed runtime tool hash mismatch: $toolName",
            source,
        )
        self.assertIn("schedule_planner = $planCli", source)
        self.assertIn("quality_certifier = $qualityCli", source)
        self.assertIn(
            "sealed_runtime_tools_verified = $sealedRuntimeTools.Count",
            source,
        )

    def test_ready_gate_must_match_current_run_and_complete_output(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("check_active_run_gate.ps1", source)
        self.assertIn("PIT post-run current-run pointer mismatch", source)
        self.assertNotIn(
            "$observedGate.expected_outputs_complete -ne $true",
            source,
        )
        self.assertIn("$observedGate.primary_output_complete -ne $true", source)
        self.assertIn("$observedGate.stop_reason -ne \"completed\"", source)
        self.assertIn(
            "PIT post-run manifest path does not match the exact schedule segment.",
            source,
        )
        self.assertIn(
            "PIT post-run checker output path does not match the exact schedule segment.",
            source,
        )
        self.assertIn(
            "PIT post-run manifest output binding mismatch.",
            source,
        )

    def test_failed_summary_reconciliation_is_explicit_and_immutable(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("[switch]$ReconcileFailedSummary", source)
        self.assertIn(
            "$RunId.postrun.reconciliation.json",
            source,
        )
        self.assertIn(
            "Canonical PIT post-run summary already exists; refusing overwrite.",
            source,
        )
        self.assertIn(
            "PIT post-run reconciliation already exists; refusing overwrite.",
            source,
        )
        self.assertIn(
            '[string]$failedSummary.decision -ne "PIT_POSTRUN_FAILED"',
            source,
        )
        self.assertIn(
            "supersedes_summary_sha256 = $failedSummarySha256",
            source,
        )
        self.assertIn(
            "reconciliation_reason = "
            '"recover_exact_final_output_after_control_plane_readiness_mismatch"',
            source,
        )
        self.assertIn(
            '[string]$failedCheckpoint.decision -ne "PIT_POSTRUN_FAILED"',
            source,
        )
        self.assertIn(
            "[string]$failedCheckpoint.reason -ne "
            "[string]$failedSummary.failure",
            source,
        )

    def test_reconciliation_resolves_only_matching_failed_checkpoint(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn(
            '[string]$checkpoint.decision -ne "PIT_POSTRUN_FAILED"',
            source,
        )
        self.assertIn(
            '[string]$checkpoint.run_id -ne $RunId',
            source,
        )
        self.assertIn(
            'status = "RESOLVED"',
            source,
        )
        self.assertIn(
            'decision = "PIT_POSTRUN_RECOVERED"',
            source,
        )
        self.assertIn(
            "postrun_reconciliation_summary_sha256",
            source,
        )

    def test_schedule_extension_cannot_self_approve_or_advance_pointer(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertNotIn("-ConfirmedNightScheduleApproval", source)
        self.assertNotIn('"CONTINUATION_SCHEDULE_APPROVED"', source)
        self.assertIn(
            '"PIT_SCHEDULE_EXTENSION_REQUIRES_EXACT_USER_APPROVAL"',
            source,
        )
        self.assertIn("automatic_approval = $false", source)
        self.assertIn("pointer_advanced = $false", source)

    def test_standing_policy_does_not_authorize_extension_activation(self) -> None:
        import json

        policy = json.loads(AUTOPILOT_POLICY.read_text(encoding="utf-8-sig"))
        routine = policy["routine_actions_without_user_confirmation"]

        self.assertFalse(
            any("continuation schedule creation and approval" in item for item in routine)
        )
        self.assertTrue(
            any(
                "activation requires exact hash-bound user approval" in item
                for item in routine
            )
        )
        extension = policy["pit_schedule_extension_candidate"]
        self.assertFalse(extension["schedule_approved"])
        self.assertFalse(extension["automatic_launch_allowed"])
        self.assertTrue(
            extension["requires_fresh_horizon_audit_before_approval"]
        )
        self.assertGreater(
            extension["fresh_horizon_audit_max_age_sec"],
            0,
        )
        self.assertTrue(
            extension[
                "fresh_horizon_audit_must_not_predate_approval_window"
            ]
        )
        self.assertTrue(
            extension[
                "fresh_horizon_audit_must_match_current_quality_ledger"
            ]
        )

    def test_postrun_summary_preserves_embargo(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        self.assertIn("returns_read = $false", source)
        self.assertIn("pnl_read = $false", source)
        self.assertIn("oos_run = $false", source)
        self.assertIn("grid_search = $false", source)
        self.assertIn("live_orders = $false", source)
        self.assertIn("private_api_keys = $false", source)

    def test_reused_train_manifest_is_rebound_before_verdict(self) -> None:
        source = POSTRUN_WRAPPER.read_text(encoding="utf-8-sig")

        manifest_read = source.index(
            "Get-Content -LiteralPath $feasibilityManifest -Raw"
        )
        binding_check = source.index(
            "Assert-TrainFeasibilityManifestBinding",
            manifest_read,
        )
        verdict_read = source.index(
            "$verdict = [string]$feasibility.verdict",
            binding_check,
        )

        self.assertLess(manifest_read, binding_check)
        self.assertLess(binding_check, verdict_read)
        self.assertIn(
            "Train-only feasibility input plan is not bound to the exact ledger/contract/train split.",
            source,
        )
        self.assertIn(
            "[string]$sealedInput.quality_ledger.file_sha256_at_plan -ne $ExpectedLedgerHash",
            source,
        )
        self.assertIn(
            "$result.returns_read -ne $false",
            source,
        )
        self.assertIn(
            "$oosSchedule.schedule_approved -ne $false",
            source,
        )


if __name__ == "__main__":
    unittest.main()
