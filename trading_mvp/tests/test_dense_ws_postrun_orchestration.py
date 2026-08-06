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
    / "dense-ws-postrun-runtime-refreeze-proposal-20260802-v1.json"
)
APPROVAL = (
    ROOT
    / "docs"
    / "agent-log"
    / "approvals"
    / "2026-08-02-dense-ws-postrun-runtime-refreeze-approval.json"
)
PROPOSAL_HASH = "0a5884a3599a52e39b6fce438e945743f5bf6bfa2a7cbea779dd0ca54cf40662"


class DenseWsPostrunOrchestrationTests(unittest.TestCase):
    def test_policy_binds_exact_visible_orchestrator(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        config = policy["dense_ws_postrun"]

        self.assertEqual(Path(config["orchestrator_path"]).resolve(), SCRIPT.resolve())
        self.assertEqual(
            config["orchestrator_sha256"],
            hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        )
        self.assertTrue(config["automatic_same_hash_through_materialization"])
        self.assertTrue(config["visible_terminal_required"])
        self.assertEqual(config["status"], "READY_AUTOMATIC_SAME_HASH_RUNTIME_REFROZEN")

        runtime = config["runtime_contract"]
        self.assertEqual(runtime["status"], "APPROVED")
        self.assertEqual(runtime["proposal_hash"], PROPOSAL_HASH)
        self.assertEqual(Path(runtime["proposal_path"]).resolve(), PROPOSAL.resolve())
        self.assertEqual(Path(runtime["approval_receipt_path"]).resolve(), APPROVAL.resolve())
        self.assertEqual(
            runtime["approval_receipt_sha256"],
            hashlib.sha256(APPROVAL.read_bytes()).hexdigest(),
        )
        self.assertEqual(runtime["quality_max_runtime_sec"], 1_800)
        self.assertEqual(runtime["materialization_max_runtime_sec"], 1_800)
        self.assertEqual(runtime["total_max_runtime_sec"], 3_600)
        self.assertEqual(
            runtime["total_max_runtime_sec"],
            runtime["quality_max_runtime_sec"]
            + runtime["materialization_max_runtime_sec"],
        )
        self.assertEqual(
            runtime["postrun_not_before_local"], "2026-08-04T01:30:00+03:00"
        )
        self.assertEqual(
            runtime["postrun_hard_deadline_local"], "2026-08-04T02:30:00+03:00"
        )
        self.assertTrue(runtime["stages_are_sequential"])
        self.assertTrue(runtime["one_visible_terminal"])
        self.assertTrue(runtime["stopped_incomplete_recovery_requires_new_exact_approval"])
        self.assertFalse(config["evaluator_authorized"])
        self.assertFalse(config["returns_pnl_oos_allowed"])
        self.assertFalse(config["network_collector_allowed"])
        self.assertFalse(config["grid_or_retune_allowed"])

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
        self.assertIn('if (-not $ReservationPath)', source)
        self.assertIn('throw "VisibleChild requires ReservationPath."', source)

    def test_runtime_contract_has_independent_stage_and_total_deadlines(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("[int]$TotalMaxRuntimeSec = 3600", source)
        self.assertIn("[int]$QualityMaxRuntimeSec = 1800", source)
        self.assertIn("[int]$MaterializationMaxRuntimeSec = 1800", source)
        self.assertIn("$TotalDeadline", source)
        self.assertIn("$QualityDeadline", source)
        self.assertIn("$MaterializationDeadline", source)
        self.assertIn("$PostrunHardDeadline", source)
        self.assertIn("[DateTimeOffset]::ParseExact", source)
        self.assertIn("[Globalization.CultureInfo]::InvariantCulture", source)
        self.assertIn("ConvertFrom-Json -DateKind String", source)
        self.assertIn("postrun_window_not_open", source)
        self.assertIn("postrun_hard_deadline_passed", source)
        self.assertIn("candidateReservation.total_max_runtime_sec", source)
        self.assertIn("candidateReservation.quality_max_runtime_sec", source)
        self.assertIn("candidateReservation.materialization_max_runtime_sec", source)
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
