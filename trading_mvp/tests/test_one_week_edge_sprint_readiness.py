from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import one_week_edge_sprint_readiness as readiness_module  # noqa: E402
from one_week_edge_sprint_readiness import (  # noqa: E402
    PrimaryBasisTrustAnchor,
    ReadinessError,
    build_readiness,
    canonical_hash_without,
    main,
    write_readiness_bundle,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReadinessFixture:
    plan_hash = "a" * 64
    pit_plan_hash = "b" * 64
    identity_proposal_hash = "c" * 64
    dense_proposal_hash = "d" * 64
    source_pit_plan_hash = "e" * 64
    contract_hash = "f" * 64
    primary_basis_artifact_hash = "1" * 64
    run_id = "slow_liquidity_history_recollect_fixture_v6"
    quality_decision = (
        "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
        "AWAIT_OFFICIAL_IDENTITY_APPROVAL"
    )

    def __init__(self, root: Path) -> None:
        self.root = root
        self.plan_path = root / "plan.json"
        self.receipt_path = root / "approval.json"
        self.launch_path = root / "launch.json"
        self.output_path = root / "ohlcv.jsonl"
        self.manifest_path = root / "manifest.json"
        self.quality_path = root / "quality.json"
        self.gate_path = root / "gate.json"
        self.writer_claim_path = root / "writer-claim.json"
        self.identity_proposal_path = root / "identity-proposal.json"
        self.pit_pointer_path = root / "pit-pointer.json"
        self.pit_ledger_path = root / "quality-ledger.jsonl"
        self.pit_plan_path = root / "pit-extension-plan.json"
        self.dense_proposal_path = root / "dense-proposal.json"
        self.sprint_plan_path = root / "one-week-sprint.md"
        self.primary_basis_currentness_audit_path = (
            root / "primary-basis-currentness-audit.json"
        )
        self.primary_basis_terminal_report_path = (
            root / "primary-basis-terminal-report.json"
        )
        self.output_path.write_text('{"close":"not_parsed"}\n', encoding="utf-8")
        write_json(self.receipt_path, {"status": "APPROVED", "run_id": self.run_id})
        write_json(
            self.launch_path,
            {"status": "COMPLETE", "run_id": self.run_id},
        )
        write_json(
            self.manifest_path,
            {
                "run_id": self.run_id,
                "final": True,
                "decision": "COMPLETE",
                "rows": 30_021,
                "errors": 0,
                "selected_bases": [
                    "STETH",
                    "WEETH",
                    "CC",
                    "OKB",
                    "RAIN",
                    "MNT",
                    "USDD",
                    "BDX",
                    "EDGE",
                ],
                "exchanges": ["mexc", "gateio"],
                "granularities": ["1h", "4h"],
                "history_days": 56,
            },
        )
        write_json(
            self.plan_path,
            {
                "schema": "trading_mvp_slow_liquidity_history_recollect_planonly_v1",
                "mode": "PlanOnly",
                "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                "actual_collection_allowed": False,
                "plan_hash": self.plan_hash,
                "approval_receipt": {"path": str(self.receipt_path)},
                "execution": {
                    "run_id": self.run_id,
                    "output_jsonl": str(self.output_path),
                    "manifest_path": str(self.manifest_path),
                    "launch_record_path": str(self.launch_path),
                },
                "data_quality_after_success": {
                    "output_path": str(self.quality_path),
                    "evaluator_or_oos_authorized": False,
                    "official_identity_verification_authorized_by_this_plan": False,
                },
            },
        )
        write_json(
            self.quality_path,
            {
                "decision": self.quality_decision,
                "accepted": True,
                "terminal": False,
                "identity_verification_required": True,
                "identity_verification_authorized": False,
                "retry_authorized": False,
                "rescope_authorized": False,
                "evaluator_or_oos_authorized": False,
                "replay_allowed": False,
                "grid_allowed": False,
                "paper_forward_allowed": False,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
                "metrics": {
                    "line_count": 30_021,
                    "manifest_errors": 0,
                    "ok_rows": 30_021,
                    "ok_bases": 9,
                    "ok_exchanges": 2,
                    "two_exchange_full_coverage_1h4h_bases": 9,
                    "duplicate_candles": 0,
                },
                "exact_recollect_provenance": {
                    "run_id": self.run_id,
                    "plan_path": str(self.plan_path),
                    "plan_file_sha256": sha256(self.plan_path),
                    "plan_hash": self.plan_hash,
                    "approval_receipt_path": str(self.receipt_path),
                    "approval_receipt_file_sha256": sha256(self.receipt_path),
                    "launch_record_path": str(self.launch_path),
                    "launch_record_file_sha256": sha256(self.launch_path),
                    "manifest_path": str(self.manifest_path),
                    "manifest_file_sha256": sha256(self.manifest_path),
                    "output_jsonl_path": str(self.output_path),
                    "output_jsonl_file_sha256": sha256(self.output_path),
                    "technical_quality_only": True,
                    "official_identity_verification_authorized": False,
                    "evaluator_or_oos_authorized": False,
                    "stopped_incomplete_retry_authorized": False,
                },
            },
        )
        self._write_gate()
        self._write_primary_basis_terminal()
        self._write_identity_proposal()
        self._write_pit_state()
        self._write_dense_proposal()

    def _write_primary_basis_terminal(self) -> None:
        self.sprint_plan_path.write_text(
            "# One-Week Historical Edge Sprint\n\n"
            "hypothesis_id: cross_venue_perp_basis_convergence_history_v1\n"
            "required_history_days: 220\n",
            encoding="utf-8",
        )
        write_json(
            self.primary_basis_terminal_report_path,
            {
                "schema": "trading_mvp_historical_basis_retention_closure_v1",
                "hypothesis_id": (
                    "cross_venue_perp_basis_convergence_history_v1"
                ),
                "final": True,
                "verdict": "INSUFFICIENT_DATA",
                "reason_code": (
                    "GATE_5M_PUBLIC_HISTORY_RETENTION_LT_FROZEN_220D"
                ),
                "edge_evaluated": False,
                "pnl_read": False,
                "frozen_contract": {
                    "interval": "5m",
                    "required_history_days": 220,
                    "warmup_days": 20,
                    "train_days": 100,
                    "oos_days": 100,
                    "strategy_change_allowed": False,
                },
                "gate_public_api_evidence": {
                    "venue": "gateio",
                    "endpoint_family": "/api/v4/futures/usdt/candlesticks",
                    "old_boundary_status": 400,
                    "old_boundary_label": "INVALID_PARAM_VALUE",
                    "old_boundary_message": (
                        "Candlestick too long ago. Maximum 10000 points "
                        "recently are allowed"
                    ),
                    "recent_status": 200,
                    "recent_rows": 13,
                    "maximum_recent_points": 10_000,
                    "maximum_recent_days_at_5m": 34.722,
                    "required_days": 220,
                },
                "safety": {
                    "research_only": True,
                    "public_api_only": True,
                    "live_orders": False,
                    "api_keys": False,
                    "leverage_or_margin": False,
                },
                "forbidden_actions": [
                    "historical_collect_220d_5m_gate_public",
                    "train_evaluation",
                    "oos_evaluation",
                    "execution_probe",
                    "paper_forward",
                    "live_orders",
                    "retune_frozen_contract",
                ],
                "next_allowed_command": "none_branch_closed_insufficient_data",
                "artifact_hash": self.primary_basis_artifact_hash,
            },
        )

        write_json(
            self.primary_basis_currentness_audit_path,
            {
                "schema": (
                    "trading_mvp_cross_venue_basis_terminal_currentness_audit_v1"
                ),
                "goal_binding": {
                    "named_primary_hypothesis": (
                        "cross_venue_perp_basis_convergence_history_v1"
                    ),
                    "original_sprint_plan_path": str(self.sprint_plan_path),
                    "original_sprint_plan_sha256": sha256(self.sprint_plan_path),
                },
                "v1_terminal_evidence": {
                    "hypothesis_id": (
                        "cross_venue_perp_basis_convergence_history_v1"
                    ),
                    "report_path": str(self.primary_basis_terminal_report_path),
                    "report_file_sha256": sha256(
                        self.primary_basis_terminal_report_path
                    ),
                    "artifact_hash": self.primary_basis_artifact_hash,
                    "final": True,
                    "verdict": "INSUFFICIENT_DATA",
                    "reason_code": (
                        "GATE_5M_PUBLIC_HISTORY_RETENTION_LT_FROZEN_220D"
                    ),
                    "required_history_days": 220,
                    "maximum_recent_gate_history_days_at_5m": 34.722,
                    "edge_evaluated": False,
                    "pnl_read": False,
                    "next_allowed_command": (
                        "none_branch_closed_insufficient_data"
                    ),
                    "retune_or_repeat_same_contract_allowed": False,
                },
                "verdict": {
                    "v1_may_be_reopened_without_new_contract": False,
                    "basis_oos_or_pnl_action_due": False,
                },
                "safety": {
                    "network_access": False,
                    "new_collector_started": False,
                    "market_rows_read": False,
                    "oos_read": False,
                    "returns_read": False,
                    "pnl_read": False,
                    "grid_or_retune": False,
                    "paper_or_live": False,
                    "private_api_keys": False,
                    "real_capital": False,
                    "leverage_or_margin": False,
                },
            },
        )
        self.primary_basis_trust_anchor = self._current_primary_basis_anchor()

    def _current_primary_basis_anchor(self) -> PrimaryBasisTrustAnchor:
        return PrimaryBasisTrustAnchor(
            sprint_plan_path=self.sprint_plan_path.resolve(),
            sprint_plan_file_sha256=sha256(self.sprint_plan_path),
            currentness_audit_path=(
                self.primary_basis_currentness_audit_path.resolve()
            ),
            currentness_audit_file_sha256=sha256(
                self.primary_basis_currentness_audit_path
            ),
            terminal_report_path=self.primary_basis_terminal_report_path.resolve(),
            terminal_report_file_sha256=sha256(
                self.primary_basis_terminal_report_path
            ),
            artifact_hash=self.primary_basis_artifact_hash,
        )

    def trust_anchor_patch(
        self,
        *,
        current_files: bool = False,
    ) -> mock._patch:
        anchor = (
            self._current_primary_basis_anchor()
            if current_files
            else self.primary_basis_trust_anchor
        )
        return mock.patch.object(
            readiness_module,
            "PRODUCTION_PRIMARY_BASIS_TRUST_ANCHOR",
            anchor,
        )

    def _write_gate(self) -> None:
        write_json(
            self.gate_path,
            {
                "schema": "trading_mvp_active_run_gate_v1",
                "project": "trading_mvp",
                "status": "READY_FOR_POSTPROCESS",
                "run_id": self.run_id,
                "next_goal_decision": self.quality_decision,
                "manifest_path": str(self.manifest_path),
                "replay_allowed": False,
                "grid_allowed": False,
                "paper_forward_allowed": False,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
                "identity_verification_required": True,
                "identity_verification_authorized": False,
                "last_slow_liquidity_history_data_quality_output_path": str(
                    self.quality_path
                ),
                "last_slow_liquidity_history_data_quality_output_sha256": sha256(
                    self.quality_path
                ),
            },
        )

    def _write_identity_proposal(self) -> None:
        proposal = {
            "schema": "trading_mvp_slow_liquidity_official_identity_proposal_v1",
            "mode": "PlanOnlyReviewProposal",
            "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
            "source_bindings": {
                "recollect_plan": {
                    "path": str(self.plan_path),
                    "file_sha256": sha256(self.plan_path),
                    "plan_hash": self.plan_hash,
                },
                "approval_receipt": {
                    "path": str(self.receipt_path),
                    "file_sha256": sha256(self.receipt_path),
                },
                "completed_launch": {
                    "path": str(self.launch_path),
                    "file_sha256": sha256(self.launch_path),
                    "run_id": self.run_id,
                    "status": "COMPLETE",
                },
                "collection_manifest": {
                    "path": str(self.manifest_path),
                    "file_sha256": sha256(self.manifest_path),
                    "run_id": self.run_id,
                    "final": True,
                },
                "technical_quality": {
                    "path": str(self.quality_path),
                    "file_sha256": sha256(self.quality_path),
                    "decision": self.quality_decision,
                    "accepted": True,
                },
            },
            "authorization_now": {
                "offline_runtime_implementation_allowed": False,
                "synthetic_runtime_tests_allowed": False,
                "official_source_content_read_allowed": False,
                "actual_network_run_allowed": False,
                "identity_claim_allowed": False,
                "candidate_planonly_creation_allowed": False,
                "evaluator_or_oos_allowed": False,
                "returns_or_pnl_allowed": False,
                "grid_or_retune_allowed": False,
                "execution_probe_allowed": False,
                "paper_or_live_allowed": False,
                "private_api_keys_allowed": False,
                "real_capital_allowed": False,
                "leverage_or_margin_allowed": False,
                "exact_user_approval_required": True,
            },
            "next_checkpoint": {
                "required_action": "REQUEST_EXACT_HASH_BOUND_IDENTITY_APPROVAL"
            },
            "proposal_hash_method": (
                "sha256_canonical_json_excluding_proposal_hash"
            ),
        }
        proposal["proposal_hash"] = canonical_hash_without(
            proposal,
            "proposal_hash",
        )
        self.identity_proposal_hash = proposal["proposal_hash"]
        write_json(self.identity_proposal_path, proposal)

    def _write_pit_state(self) -> None:
        accepted = []
        ledger_lines = []
        for index in range(10):
            certification_id = hashlib.sha256(
                f"cert-{index}".encode("ascii")
            ).hexdigest()
            accepted.append(
                {
                    "certification_id": certification_id,
                    "scheduled_date": f"2026-08-{index + 1:02d}",
                    "segment_run_id": f"pit_{index + 1}",
                }
            )
            ledger_lines.append(
                json.dumps(
                    {
                        "track_key": (
                            "pit_universe_membership_drift_reversion_v1|"
                            "PIT_UNIVERSE_V2_FORWARD"
                        ),
                        "hypothesis_contract_sha256": self.contract_hash,
                        "certification_id": certification_id,
                        "scheduled_date": f"2026-08-{index + 1:02d}",
                        "technical_quality_accepted": True,
                    },
                    separators=(",", ":"),
                )
            )
        self.pit_ledger_path.write_text(
            "\n".join(ledger_lines) + "\n",
            encoding="utf-8",
        )
        write_json(
            self.pit_pointer_path,
            {
                "schema": "trading_mvp_autopilot_schedule_pointer_v1",
                "status": "ACTIVE",
                "project": "trading_mvp",
                "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
                "data_type": "PIT_UNIVERSE_V2_FORWARD",
                "collection_stage": "train_accrual",
                "plan_hash": self.source_pit_plan_hash,
                "quality_ledger_path": str(self.pit_ledger_path),
                "train_target_distinct_dates": 20,
            },
        )
        segments = [
            {
                "sequence": index + 1,
                "run_id": f"pit_extension_{index + 1}",
                "start_local": f"2026-08-{14 + index:02d}T01:00:00+03:00",
                "end_local": f"2026-08-{14 + index:02d}T01:20:00+03:00",
                "hard_deadline_local": (
                    f"2026-08-{14 + index:02d}T07:00:00+03:00"
                ),
                "duration_sec": 1200,
            }
            for index in range(10)
        ]
        sealed = {
            "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
            "data_type": "PIT_UNIVERSE_V2_FORWARD",
            "hypothesis_contract_sha256": self.contract_hash,
            "collection_stage": {
                "name": "train_accrual",
                "initial_accepted_distinct_dates": 10,
                "stage_target_distinct_dates": 20,
                "maximum_new_accepted_dates": 10,
                "quality_ledger": {
                    "path": str(self.pit_ledger_path),
                    "file_sha256_at_plan": sha256(self.pit_ledger_path),
                    "initial_accepted_certifications": accepted,
                },
            },
            "segments": segments,
        }
        self.pit_plan_hash = canonical_hash_without(sealed, "never-present")
        write_json(
            self.pit_plan_path,
            {
                "schema": "fast_first_night_schedule_plan_v2",
                "mode": "PlanOnly",
                "plan_hash": self.pit_plan_hash,
                "sealed_schedule_hash": self.pit_plan_hash,
                "sealed_schedule": sealed,
                "schedule_approved": False,
                "collection_started": False,
                "network_access": False,
                "oos_returns_read": False,
                "pnl_or_returns_read": False,
                "grid_search": False,
                "retune": False,
                "paper_forward": False,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
                "explicit_approval_required": True,
                "next_allowed_action": "await_explicit_night_schedule_approval",
            },
        )

    def _write_dense_proposal(self) -> None:
        proposal = {
            "schema": (
                "trading_mvp_dense_ws_three_hour_segmented_refreeze_proposal_v1"
            ),
            "mode": "PlanOnly",
            "status": "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
            "authorization_boundary": {
                "proposal_preparation_authorized": True,
                "implementation_authorized": False,
                "contract_refreeze_authorized": False,
                "runtime_manifest_creation_authorized": False,
                "collector_launch_authorized": False,
                "network_access": False,
                "market_data_read": False,
                "returns_or_pnl_read": False,
                "oos_read": False,
                "grid_or_retune": False,
                "paper_or_live": False,
                "private_api_keys": False,
                "real_capital": False,
                "leverage_or_margin": False,
                "stopped_incomplete_retry_authorized": False,
            },
            "approval_checkpoint": {
                "phase_1_does_not_authorize_collection": True,
                "phase_2_required": "separate exact launch approval",
            },
            "next_allowed_action": (
                "request_exact_proposal_bound_segmented_refreeze_"
                "implementation_approval"
            ),
            "proposal_hash_method": (
                "sha256_canonical_json_excluding_proposal_hash"
            ),
        }
        proposal["proposal_hash"] = canonical_hash_without(
            proposal,
            "proposal_hash",
        )
        self.dense_proposal_hash = proposal["proposal_hash"]
        write_json(self.dense_proposal_path, proposal)

    def kwargs(self) -> dict[str, object]:
        return {
            "gate_path": self.gate_path,
            "writer_claim_path": self.writer_claim_path,
            "slow_plan_path": self.plan_path,
            "expected_slow_plan_hash": self.plan_hash,
            "expected_slow_plan_file_sha256": sha256(self.plan_path),
            "identity_proposal_path": self.identity_proposal_path,
            "expected_identity_proposal_hash": self.identity_proposal_hash,
            "expected_identity_proposal_file_sha256": sha256(
                self.identity_proposal_path
            ),
            "pit_pointer_path": self.pit_pointer_path,
            "pit_extension_plan_path": self.pit_plan_path,
            "expected_pit_extension_plan_hash": self.pit_plan_hash,
            "expected_pit_extension_plan_file_sha256": sha256(
                self.pit_plan_path
            ),
            "dense_proposal_path": self.dense_proposal_path,
            "expected_dense_proposal_hash": self.dense_proposal_hash,
            "expected_dense_proposal_file_sha256": sha256(
                self.dense_proposal_path
            ),
            "generated_at_utc": "2026-08-13T11:00:00+00:00",
        }


class OneWeekEdgeSprintReadinessTests(unittest.TestCase):
    def test_builds_current_fail_closed_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            with fixture.trust_anchor_patch():
                report = build_readiness(**fixture.kwargs())

        self.assertEqual(
            report["status"],
            "QUALITY_ACCEPTED_SEPARATE_APPROVALS_PENDING_NO_EXECUTION_AUTHORIZED",
        )
        self.assertEqual(report["slow_liquidity"]["technical_quality"]["ok_rows"], 30_021)
        self.assertEqual(report["pit_shadow_track"]["accepted_distinct_dates"], 10)
        self.assertEqual(report["pit_shadow_track"]["extension_segments"], 10)
        self.assertEqual(
            report["primary_frozen_basis_terminal"]["status"],
            "TERMINAL_CLOSED_INSUFFICIENT_DATA",
        )
        self.assertFalse(
            report["primary_frozen_basis_terminal"]["edge_evaluated"]
        )
        self.assertFalse(
            report["primary_frozen_basis_terminal"][
                "repeat_same_contract_authorized"
            ]
        )
        self.assertFalse(report["permissions"]["identity_verification_authorized"])
        self.assertFalse(report["permissions"]["evaluator_or_oos_authorized"])
        self.assertEqual(
            report["readiness_hash"],
            canonical_hash_without(report, "readiness_hash"),
        )

    def test_phase1_runtime_freeze_keeps_network_execution_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            runtime_path = fixture.root / "identity-runtime.json"
            write_json(runtime_path, {})
            runtime_state = {
                "path": str(runtime_path.resolve()),
                "file_sha256": "2" * 64,
                "size_bytes": 2,
                "manifest_hash": "3" * 64,
                "status": (
                    "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_"
                    "EXECUTION_APPROVAL"
                ),
                "offline_approval_receipt": {
                    "path": str((fixture.root / "approval.json").resolve()),
                    "file_sha256": "4" * 64,
                    "size_bytes": 2,
                    "receipt_hash": "5" * 64,
                },
            }
            kwargs = fixture.kwargs()
            kwargs["identity_runtime_manifest_path"] = runtime_path
            with (
                fixture.trust_anchor_patch(),
                mock.patch.object(
                    readiness_module,
                    "_validate_identity_runtime_manifest",
                    return_value=runtime_state,
                ),
            ):
                report = build_readiness(**kwargs)

        self.assertEqual(
            report["status"],
            "IDENTITY_RUNTIME_FROZEN_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
        )
        self.assertFalse(report["permissions"]["identity_verification_authorized"])
        self.assertEqual(
            report["approval_checkpoints"][1]["status"],
            "AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
        )
        self.assertNotIn("official_identity_phase_2", report)

    def test_phase2_requires_exact_validated_execution_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            runtime_path = fixture.root / "identity-runtime.json"
            execution_path = fixture.root / "identity-execution.json"
            write_json(runtime_path, {})
            write_json(execution_path, {})
            runtime_state = {
                "path": str(runtime_path.resolve()),
                "file_sha256": "2" * 64,
                "size_bytes": 2,
                "manifest_hash": "3" * 64,
                "status": (
                    "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_"
                    "EXECUTION_APPROVAL"
                ),
                "offline_approval_receipt": {
                    "path": str((fixture.root / "approval.json").resolve()),
                    "file_sha256": "4" * 64,
                    "size_bytes": 2,
                    "receipt_hash": "5" * 64,
                },
            }
            execution_state = {
                "status": "FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
                "execution_manifest": {
                    "path": str(execution_path.resolve()),
                    "file_sha256": "6" * 64,
                    "size_bytes": 2,
                    "manifest_hash": "7" * 64,
                },
                "runtime_manifest_file_sha256": "2" * 64,
                "runtime_manifest_hash": "3" * 64,
                "execution_approval_receipt": {
                    "path": str((fixture.root / "execution-receipt.json").resolve()),
                    "file_sha256": "8" * 64,
                    "size_bytes": 2,
                    "receipt_hash": "9" * 64,
                },
                "execution_approval_receipt_file_sha256": "8" * 64,
                "execution_approval_receipt_hash": "9" * 64,
                "request_plan_sha256": "a" * 64,
                "output_path": str((fixture.root / "output").resolve()),
            }
            kwargs = fixture.kwargs()
            kwargs["identity_runtime_manifest_path"] = runtime_path
            kwargs["identity_execution_manifest_path"] = execution_path
            with (
                fixture.trust_anchor_patch(),
                mock.patch.object(
                    readiness_module,
                    "_validate_identity_runtime_manifest",
                    return_value=runtime_state,
                ),
                mock.patch.object(
                    readiness_module,
                    "_validate_identity_execution_manifest",
                    return_value=execution_state,
                ),
            ):
                report = build_readiness(**kwargs)

        self.assertEqual(
            report["status"],
            "IDENTITY_RUNTIME_FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
        )
        self.assertTrue(report["permissions"]["identity_verification_authorized"])
        self.assertEqual(
            report["approval_checkpoints"][1]["status"],
            "APPROVED_SINGLE_USE",
        )
        self.assertEqual(
            report["official_identity_phase_2"]["request_plan_sha256"],
            "a" * 64,
        )

    def test_rejects_quality_provenance_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            quality = json.loads(fixture.quality_path.read_text(encoding="utf-8"))
            quality["exact_recollect_provenance"]["run_id"] = "foreign-run"
            write_json(fixture.quality_path, quality)
            fixture._write_gate()
            kwargs = fixture.kwargs()
            with self.assertRaisesRegex(ReadinessError, "quality run binding"):
                with fixture.trust_anchor_patch():
                    build_readiness(**kwargs)

    def test_rejects_pit_schedule_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            plan = json.loads(fixture.pit_plan_path.read_text(encoding="utf-8"))
            plan["sealed_schedule"]["segments"][0]["duration_sec"] = 1300
            write_json(fixture.pit_plan_path, plan)
            kwargs = fixture.kwargs()
            kwargs["expected_pit_extension_plan_file_sha256"] = sha256(
                fixture.pit_plan_path
            )
            with self.assertRaisesRegex(ReadinessError, "sealed schedule hash"):
                with fixture.trust_anchor_patch():
                    build_readiness(**kwargs)

    def test_rejects_identity_proposal_permission_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            proposal = json.loads(
                fixture.identity_proposal_path.read_text(encoding="utf-8")
            )
            proposal["authorization_now"]["actual_network_run_allowed"] = True
            proposal["proposal_hash"] = canonical_hash_without(
                proposal,
                "proposal_hash",
            )
            write_json(fixture.identity_proposal_path, proposal)
            kwargs = fixture.kwargs()
            kwargs["expected_identity_proposal_hash"] = proposal["proposal_hash"]
            kwargs["expected_identity_proposal_file_sha256"] = sha256(
                fixture.identity_proposal_path
            )
            with self.assertRaisesRegex(ReadinessError, "network run"):
                with fixture.trust_anchor_patch():
                    build_readiness(**kwargs)

    def test_rejects_primary_basis_terminal_semantic_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            report = json.loads(
                fixture.primary_basis_terminal_report_path.read_text(
                    encoding="utf-8"
                )
            )
            report["edge_evaluated"] = True
            write_json(fixture.primary_basis_terminal_report_path, report)
            audit = json.loads(
                fixture.primary_basis_currentness_audit_path.read_text(
                    encoding="utf-8"
                )
            )
            audit["v1_terminal_evidence"]["report_file_sha256"] = sha256(
                fixture.primary_basis_terminal_report_path
            )
            write_json(fixture.primary_basis_currentness_audit_path, audit)
            kwargs = fixture.kwargs()

            with self.assertRaisesRegex(ReadinessError, "edge was evaluated"):
                with fixture.trust_anchor_patch(current_files=True):
                    build_readiness(**kwargs)

    def test_rejects_primary_basis_reopen_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            audit = json.loads(
                fixture.primary_basis_currentness_audit_path.read_text(
                    encoding="utf-8"
                )
            )
            audit["v1_terminal_evidence"][
                "retune_or_repeat_same_contract_allowed"
            ] = True
            write_json(fixture.primary_basis_currentness_audit_path, audit)
            kwargs = fixture.kwargs()

            with self.assertRaisesRegex(
                ReadinessError,
                "retune_or_repeat_same_contract_allowed",
            ):
                with fixture.trust_anchor_patch(current_files=True):
                    build_readiness(**kwargs)

    def test_rejects_primary_basis_true_permission_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            report = json.loads(
                fixture.primary_basis_terminal_report_path.read_text(
                    encoding="utf-8"
                )
            )
            report["execution_authorized"] = True
            write_json(fixture.primary_basis_terminal_report_path, report)
            audit = json.loads(
                fixture.primary_basis_currentness_audit_path.read_text(
                    encoding="utf-8"
                )
            )
            audit["v1_terminal_evidence"]["report_file_sha256"] = sha256(
                fixture.primary_basis_terminal_report_path
            )
            write_json(fixture.primary_basis_currentness_audit_path, audit)

            with self.assertRaisesRegex(ReadinessError, "unsafe true flag"):
                with fixture.trust_anchor_patch(current_files=True):
                    build_readiness(**fixture.kwargs())

    def test_rejects_primary_basis_reversed_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            report = json.loads(
                fixture.primary_basis_terminal_report_path.read_text(
                    encoding="utf-8"
                )
            )
            report["gate_public_api_evidence"]["old_boundary_status"] = 200
            report["gate_public_api_evidence"]["recent_status"] = 400
            write_json(fixture.primary_basis_terminal_report_path, report)
            audit = json.loads(
                fixture.primary_basis_currentness_audit_path.read_text(
                    encoding="utf-8"
                )
            )
            audit["v1_terminal_evidence"]["report_file_sha256"] = sha256(
                fixture.primary_basis_terminal_report_path
            )
            write_json(fixture.primary_basis_currentness_audit_path, audit)

            with self.assertRaisesRegex(ReadinessError, "retention evidence"):
                with fixture.trust_anchor_patch(current_files=True):
                    build_readiness(**fixture.kwargs())

    def test_forward_accrual_inputs_bind_v2_monitor_plan(self) -> None:
        refs = readiness_module._forward_accrual_era_inputs(REPO_ROOT)

        self.assertIsNotNone(refs)
        assert refs is not None
        expected_path = (
            REPO_ROOT
            / "docs"
            / "plans"
            / (
                "slow-liquidity-listing-momentum-forward-monitor-"
                "planonly-20260817-v2.json"
            )
        ).resolve()
        monitor_plan = json.loads(expected_path.read_text(encoding="utf-8"))
        monitor_ref = refs["forward_monitor_plan"]

        self.assertEqual(Path(monitor_ref["path"]).resolve(), expected_path)
        self.assertEqual(monitor_ref["plan_id"], monitor_plan["plan_id"])
        self.assertEqual(monitor_ref["plan_hash"], monitor_plan["plan_hash"])
        self.assertEqual(monitor_ref["schema"], monitor_plan["schema"])

    def test_forward_accrual_resolver_rejects_stale_monitor_plan_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gate_path = root / "gate.json"
            write_json(gate_path, {"status": "READY_FOR_POSTPROCESS"})
            refs = {
                "identity_acceptance_receipt": {
                    "receipt_hash": "receipt-hash",
                },
                "replay_volatility_expansion": {
                    "file_sha256": "1" * 64,
                },
                "replay_liquidity_shock": {
                    "file_sha256": "2" * 64,
                },
                "forward_monitor_plan": {
                    "path": str(root / "v2-plan.json"),
                    "file_sha256": "3" * 64,
                    "plan_id": "forward-v2",
                    "plan_hash": "4" * 64,
                    "schema": (
                        "trading_mvp_slow_liquidity_listing_momentum_"
                        "forward_monitor_planonly_v2"
                    ),
                },
                "forward_evaluator_plan": {
                    "path": str(root / "evaluator.json"),
                    "file_sha256": "5" * 64,
                },
                "forward_state": {
                    "path": str(root / "state.json"),
                    "file_sha256": "6" * 64,
                    "tick_count": 4,
                    "complete_window_count": 0,
                    "state_hash": "7" * 64,
                },
            }
            report = {
                "permissions": {
                    field: False
                    for field in readiness_module.CURRENT_PERMISSION_FIELDS
                },
                "next_safe_action": (
                    "wait_forward_sample_and_run_scheduled_ticks_"
                    "no_peeking_below_30"
                ),
                "slow_liquidity": {
                    "retrospective_verdict": (
                        "both_families_rejected_no_robust_edge"
                    ),
                    "identity_verification_authorized": True,
                    "identity_verification_required": False,
                    "identity_acceptance_receipt": {
                        "receipt_hash": "receipt-hash",
                    },
                    "retrospective_replays": {
                        "volatility_expansion_continuation_v1": {
                            "file_sha256": "1" * 64,
                        },
                        "liquidity_shock_reclaim_long_v1": {
                            "file_sha256": "2" * 64,
                        },
                    },
                },
                "forward_accrual": {
                    "monitor_plan": {
                        "path": str(root / "stale-v1-plan.json"),
                        "file_sha256": "8" * 64,
                    },
                    "evaluator_plan": refs["forward_evaluator_plan"],
                    "state": refs["forward_state"],
                },
                "readiness_hash": "9" * 64,
                "generated_at_utc": "2026-08-17T12:00:00Z",
                "status": readiness_module.FORWARD_ACCRUAL_READINESS_STATUS,
            }

            with mock.patch.object(
                readiness_module,
                "_forward_accrual_era_inputs",
                return_value=refs,
            ):
                with self.assertRaisesRegex(
                    readiness_module.CurrentSprintReadinessError,
                    "forward monitor plan binding mismatch",
                ):
                    readiness_module._resolve_forward_accrual_readiness(
                        report,
                        pointer_file=root / "pointer.json",
                        pointer_sha="a" * 64,
                        readiness_path=root / "readiness.json",
                        report_sha="b" * 64,
                        gate_file=gate_path,
                        writer_claim_file=root / "writer-claim.json",
                        repo_root=root,
                    )

    def test_writes_immutable_report_and_pointer_last(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            with fixture.trust_anchor_patch():
                report = build_readiness(**fixture.kwargs())
            output = fixture.root / "readiness" / "readiness.json"
            pointer = fixture.root / "readiness-pointer.json"

            result = write_readiness_bundle(report, output, pointer)
            persisted_pointer = json.loads(pointer.read_text(encoding="utf-8"))

            self.assertEqual(result["readiness_file_sha256"], sha256(output))
            self.assertEqual(
                persisted_pointer["readiness_file_sha256"],
                sha256(output),
            )
            self.assertEqual(
                persisted_pointer["readiness_hash"],
                report["readiness_hash"],
            )
            with self.assertRaisesRegex(ReadinessError, "already exists"):
                write_readiness_bundle(report, output, pointer)

    def test_rejects_bundle_path_resolver_would_not_accept(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            with fixture.trust_anchor_patch():
                report = build_readiness(**fixture.kwargs())

            with self.assertRaisesRegex(ReadinessError, "readiness directory"):
                write_readiness_bundle(
                    report,
                    fixture.root / "wrong-place.json",
                    fixture.root / "readiness-pointer.json",
                )

    def test_cli_preflight_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReadinessFixture(Path(temporary))
            output = fixture.root / "readiness" / "readiness.json"
            pointer = fixture.root / "readiness-pointer.json"
            kwargs = fixture.kwargs()
            command = [
                sys.executable,
                str(SRC_ROOT / "one_week_edge_sprint_readiness.py"),
                "--gate",
                str(kwargs["gate_path"]),
                "--writer-claim",
                str(kwargs["writer_claim_path"]),
                "--slow-plan",
                str(kwargs["slow_plan_path"]),
                "--expected-slow-plan-hash",
                str(kwargs["expected_slow_plan_hash"]),
                "--expected-slow-plan-file-sha256",
                str(kwargs["expected_slow_plan_file_sha256"]),
                "--identity-proposal",
                str(kwargs["identity_proposal_path"]),
                "--expected-identity-proposal-hash",
                str(kwargs["expected_identity_proposal_hash"]),
                "--expected-identity-proposal-file-sha256",
                str(kwargs["expected_identity_proposal_file_sha256"]),
                "--pit-pointer",
                str(kwargs["pit_pointer_path"]),
                "--pit-extension-plan",
                str(kwargs["pit_extension_plan_path"]),
                "--expected-pit-extension-plan-hash",
                str(kwargs["expected_pit_extension_plan_hash"]),
                "--expected-pit-extension-plan-file-sha256",
                str(kwargs["expected_pit_extension_plan_file_sha256"]),
                "--dense-proposal",
                str(kwargs["dense_proposal_path"]),
                "--expected-dense-proposal-hash",
                str(kwargs["expected_dense_proposal_hash"]),
                "--expected-dense-proposal-file-sha256",
                str(kwargs["expected_dense_proposal_file_sha256"]),
                "--generated-at-utc",
                str(kwargs["generated_at_utc"]),
                "--output",
                str(output),
                "--pointer-output",
                str(pointer),
                "--preflight-only",
            ]
            stdout = StringIO()
            with fixture.trust_anchor_patch(), redirect_stdout(stdout):
                return_code = main(command[2:])

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["decision"], "READY_TO_WRITE_CURRENT_READINESS")
            self.assertEqual(payload["side_effects"], "NONE")
            self.assertFalse(output.exists())
            self.assertFalse(pointer.exists())


if __name__ == "__main__":
    unittest.main()
