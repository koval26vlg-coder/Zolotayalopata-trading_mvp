from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "run_dense_ws_postrun_visible.ps1"
POLICY = ROOT / "docs" / "plans" / "trading-mvp-autopilot-policy-v1.json"
PROPOSAL = (
    ROOT
    / "docs"
    / "plans"
    / "drafts"
    / "dense-ws-deferred-postrun-handoff-freeze-proposal-20260809-v1.json"
)
FREEZE_APPROVAL = (
    ROOT
    / "docs"
    / "agent-log"
    / "approvals"
    / "2026-08-09-dense-ws-deferred-postrun-handoff-freeze-v1-approval.json"
)
HANDOFF_MANIFEST = (
    ROOT
    / "docs"
    / "plans"
    / "dense-ws-deferred-postrun-handoff-manifest-20260810-aef-24h-n14-v1.json"
)
PROPOSAL_HASH = "2d4765d115ceee5a1f4e0e74841830d8aa2e2c26bfd761bdabd5b8e8b335439f"
PROFILE_HASH = "10addf47520a8a2e697e786214e45295cd301756206297ee9018b8f8c85f16e6"
N14_PLAN_HASH = "2db541dcdec6f2462d0798807b107784baf385689255af27f14036c2421c83ca"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DenseWsPostrunOrchestrationTests(unittest.TestCase):
    def test_policy_freezes_deferred_handoff_without_execution_approval(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        config = policy["dense_ws_postrun"]
        handoff = config["deferred_handoff"]
        candidate = policy["next_long_campaign"]

        self.assertEqual(Path(config["orchestrator_path"]).resolve(), SCRIPT.resolve())
        self.assertEqual(config["orchestrator_sha256"], _sha256(SCRIPT))
        self.assertTrue(config["automatic_same_hash_through_materialization"])
        self.assertTrue(config["visible_terminal_required"])
        self.assertEqual(
            config["status"],
            "DEFERRED_HANDOFF_FROZEN_AWAITING_MANIFEST_BOUND_EXECUTION_APPROVAL",
        )
        self.assertEqual(
            handoff["status"],
            "FROZEN_IMPLEMENTATION_ONLY_AWAITING_EXECUTION_APPROVAL",
        )
        self.assertTrue(handoff["implementation_authorized"])
        self.assertFalse(handoff["postrun_execution_authorized"])
        self.assertEqual(handoff["execution_approval"]["status"], "NOT_APPROVED")
        self.assertTrue(
            handoff["future_execution_requires_exact_manifest_bound_approval"]
        )
        self.assertFalse(handoff["stopped_incomplete_retry_authorized"])
        self.assertEqual(handoff["handoff_profile_hash"], PROFILE_HASH)

        self.assertEqual(handoff["proposal"]["proposal_hash"], PROPOSAL_HASH)
        self.assertEqual(Path(handoff["proposal"]["path"]).resolve(), PROPOSAL.resolve())
        self.assertEqual(handoff["proposal"]["file_sha256"], _sha256(PROPOSAL))
        self.assertEqual(
            Path(handoff["approval_receipt"]["path"]).resolve(),
            FREEZE_APPROVAL.resolve(),
        )
        self.assertEqual(
            handoff["approval_receipt"]["file_sha256"], _sha256(FREEZE_APPROVAL)
        )
        self.assertEqual(
            Path(handoff["canonical_manifest"]["path"]).resolve(),
            HANDOFF_MANIFEST.resolve(),
        )
        self.assertEqual(
            handoff["canonical_manifest"]["file_sha256"], _sha256(HANDOFF_MANIFEST)
        )

        manifest = json.loads(HANDOFF_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["schema"],
            "trading_mvp_dense_ws_deferred_postrun_handoff_manifest_v1",
        )
        self.assertEqual(manifest["mode"], "IMMUTABLE_PLANONLY_RUNTIME_BINDING")
        self.assertEqual(manifest["proposal"]["proposal_hash"], PROPOSAL_HASH)
        self.assertEqual(manifest["handoff_profile_hash"], PROFILE_HASH)
        self.assertEqual(manifest["campaign"]["campaign_id"], candidate["campaign_id"])
        self.assertEqual(manifest["campaign"]["plan_hash"], candidate["plan_hash"])
        self.assertFalse(manifest["authorization"]["postrun_execution_authorized"])
        self.assertTrue(
            manifest["authorization"][
                "future_execution_requires_exact_manifest_bound_approval"
            ]
        )

        for key in (
            "evaluator_authorized",
            "returns_pnl_oos_allowed",
            "network_collector_allowed",
            "grid_or_retune_allowed",
            "paper_live_private_api_real_capital_leverage_margin_allowed",
        ):
            self.assertFalse(config[key])

    def test_n14_and_runtime_window_are_exact_and_not_moved(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        handoff = policy["dense_ws_postrun"]["deferred_handoff"]
        n14 = handoff["required_pit_completion"]
        runtime = handoff["runtime_window"]

        self.assertEqual(n14["run_id"], "pit_universe_v2_forward_20260811_n14")
        self.assertEqual(n14["schedule_plan_hash"], N14_PLAN_HASH)
        self.assertEqual(n14["start_local"], "2026-08-11T02:15:00+03:00")
        self.assertEqual(n14["end_local"], "2026-08-11T02:35:00+03:00")
        schedule_path = Path(n14["schedule_path"])
        self.assertTrue(schedule_path.is_file())
        self.assertEqual(n14["schedule_file_sha256"], _sha256(schedule_path))

        self.assertEqual(
            runtime["postrun_not_before_local"], "2026-08-11T02:40:00+03:00"
        )
        self.assertEqual(
            runtime["latest_full_runtime_start_local"],
            "2026-08-11T03:10:00+03:00",
        )
        self.assertEqual(
            runtime["postrun_hard_deadline_local"], "2026-08-11T04:10:00+03:00"
        )
        self.assertEqual(runtime["quality_max_runtime_sec"], 1_800)
        self.assertEqual(runtime["materialization_max_runtime_sec"], 1_800)
        self.assertEqual(runtime["total_max_runtime_sec"], 3_600)
        self.assertEqual(
            runtime["total_max_runtime_sec"],
            runtime["quality_max_runtime_sec"]
            + runtime["materialization_max_runtime_sec"],
        )
        self.assertTrue(runtime["stages_are_sequential"])
        self.assertTrue(runtime["one_visible_terminal"])
        self.assertTrue(runtime["one_postrun_owner"])

    def test_top_level_launch_is_visible_and_preflight_is_write_free(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("-WindowStyle Normal", source)
        self.assertIn('status = "VISIBLE_TERMINAL_LAUNCHED"', source)
        self.assertIn("terminal_ownership_verified = $true", source)
        self.assertIn("if ($PreflightOnly)", source)
        self.assertIn("no_run_or_output_writes = [bool]$PreflightOnly", source)
        self.assertLess(
            source.index("if ($PreflightOnly)"),
            source.index("[System.IO.Directory]::CreateDirectory($PostrunRoot)"),
        )
        self.assertIn("manifest_bound_execution_not_authorized", source)
        self.assertIn("postrun_latest_full_runtime_start_passed", source)
        self.assertIn(
            "IMMUTABLE_COMPLETED_CAMPAIGN_MANIFEST_AFTER_PIT",
            source,
        )
        self.assertIn("Assert-DenseCampaignManifestBinding", source)
        self.assertIn("Test-LiveGlobalWriterClaim", source)
        self.assertIn("execution_approval_campaign_manifest_mismatch", source)

    def test_runtime_contract_has_independent_stage_and_total_deadlines(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("[int]$TotalMaxRuntimeSec = 3600", source)
        self.assertIn("[int]$QualityMaxRuntimeSec = 1800", source)
        self.assertIn("[int]$MaterializationMaxRuntimeSec = 1800", source)
        self.assertIn("$TotalDeadline", source)
        self.assertIn("$QualityDeadline", source)
        self.assertIn("$MaterializationDeadline", source)
        self.assertIn("$PostrunLatestFullStart", source)
        self.assertIn("$PostrunHardDeadline", source)
        self.assertIn("[DateTimeOffset]::ParseExact", source)
        self.assertIn("[Globalization.CultureInfo]::InvariantCulture", source)
        self.assertIn("ConvertFrom-Json -DateKind String", source)
        self.assertIn("candidateReservation.campaign_manifest_sha256", source)
        self.assertIn("completed after its bounded stage or total deadline", source)

    def test_pipeline_stops_before_evaluator(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("dense_ws_campaign_quality.py", source)
        self.assertIn("dense_ws_causal_materializer.py", source)
        self.assertNotIn("dense_ws_execution_realization.py", source)
        self.assertNotIn("--stage", source)
        self.assertNotIn("--oos", source.lower())
        self.assertNotIn("--grid", source.lower())
        self.assertNotIn("--retune", source.lower())

    def test_immutable_output_names_are_distinct(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        names = policy["dense_ws_postrun"]["output_names"]

        self.assertEqual(len(names), len(set(names.values())))
        for name in names.values():
            self.assertEqual(Path(name).name, name)


if __name__ == "__main__":
    unittest.main()
