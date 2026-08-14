from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autopilot_guard import (  # noqa: E402
    CurrentSprintReadinessError,
    evaluate_autopilot_state,
    resolve_current_sprint_readiness,
)
from one_week_edge_sprint_readiness import (  # noqa: E402
    build_readiness,
    write_readiness_bundle,
)
import one_week_edge_sprint_readiness as readiness_module  # noqa: E402
from trading_mvp.tests.test_one_week_edge_sprint_readiness import (  # noqa: E402
    ReadinessFixture,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash_without(payload: dict, field: str) -> str:
    value = dict(payload)
    value.pop(field, None)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reseal_readiness_bundle(
    fixture: "CurrentSprintReadinessFixture",
    report: dict,
) -> None:
    report["readiness_hash"] = _canonical_hash_without(
        report,
        "readiness_hash",
    )
    _write_json(fixture.report, report)
    pointer = json.loads(fixture.pointer.read_text(encoding="utf-8"))
    pointer["readiness_file_sha256"] = _sha256(fixture.report)
    pointer["readiness_hash"] = report["readiness_hash"]
    _write_json(fixture.pointer, pointer)


class CurrentSprintReadinessFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        full = ReadinessFixture(root)
        self.writer_claim = full.writer_claim_path
        self.gate = full.gate_path
        self.active_pit_pointer = full.pit_pointer_path
        self.quality_ledger = full.pit_ledger_path
        self.extension_plan = full.pit_plan_path
        self.report = root / "readiness" / "readiness.json"
        self.pointer = root / "readiness-pointer.json"
        self.run_id = full.run_id
        self.active_plan_hash = full.source_pit_plan_hash
        self.extension_plan_hash = full.pit_plan_hash
        self.identity_proposal_hash = full.identity_proposal_hash
        self.dense_proposal_hash = full.dense_proposal_hash
        self.primary_basis_trust_anchor = full.primary_basis_trust_anchor
        with full.trust_anchor_patch():
            report = build_readiness(**full.kwargs())
            write_readiness_bundle(report, self.report, self.pointer)

    def trust_anchor_patch(self) -> mock._patch:
        return mock.patch.object(
            readiness_module,
            "PRODUCTION_PRIMARY_BASIS_TRUST_ANCHOR",
            self.primary_basis_trust_anchor,
        )

    def _ref(self, path: Path) -> dict:
        return {
            "path": str(path.resolve()),
            "file_sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }

    def _write_inputs(self) -> None:
        _write_json(
            self.gate,
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": self.run_id,
                "next_goal_decision": (
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
                    "AWAIT_OFFICIAL_IDENTITY_APPROVAL"
                ),
            },
        )
        _write_json(
            self.active_pit_pointer,
            {
                "status": "ACTIVE",
                "plan_hash": self.active_plan_hash,
                "quality_ledger_path": str(self.quality_ledger.resolve()),
            },
        )
        self.quality_ledger.write_text(
            json.dumps({"status": "ACCEPTED", "date": "2026-08-01"}) + "\n",
            encoding="utf-8",
        )
        _write_json(
            self.extension_plan,
            {
                "mode": "PlanOnly",
                "plan_hash": self.extension_plan_hash,
                "schedule_approved": False,
                "collection_started": False,
                "segments": [
                    {
                        "run_id": f"pit_{index:02d}",
                        "duration_sec": 1_200,
                    }
                    for index in range(10)
                ],
            },
        )
        _write_json(self.slow_plan, {"plan_hash": self.slow_plan_hash})
        _write_json(self.slow_approval, {"status": "APPROVED"})
        _write_json(self.slow_launch, {"status": "COMPLETE"})
        _write_json(
            self.slow_manifest,
            {"run_id": self.run_id, "final": True, "rows": 30_021, "errors": 0},
        )
        self.slow_output.write_text("{}\n", encoding="utf-8")
        _write_json(
            self.slow_quality,
            {
                "accepted": True,
                "decision": (
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
                    "AWAIT_OFFICIAL_IDENTITY_APPROVAL"
                ),
            },
        )
        _write_json(
            self.identity_proposal,
            {
                "proposal_hash": self.identity_proposal_hash,
                "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                "phase_1_approved": False,
                "network_execution_authorized": False,
                "identity_output_authorized": False,
            },
        )
        _write_json(
            self.dense_proposal,
            {
                "proposal_hash": self.dense_proposal_hash,
                "status": "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
                "phase_1_approved": False,
                "implementation_authorized": False,
                "collector_launch_authorized": False,
            },
        )

    def _write_bundle(self) -> None:
        report = {
            "schema": "trading_mvp_one_week_edge_sprint_current_readiness_v1",
            "status": (
                "QUALITY_ACCEPTED_SEPARATE_APPROVALS_PENDING_"
                "NO_EXECUTION_AUTHORIZED"
            ),
            "generated_at_utc": "2026-08-13T14:12:18+03:00",
            "project": "trading_mvp",
            "goal": "One-Week Historical Edge Sprint",
            "research_only": True,
            "slow_liquidity": {
                "run_id": self.run_id,
                "plan": {
                    **self._ref(self.slow_plan),
                    "plan_hash": self.slow_plan_hash,
                },
                "approval_receipt": self._ref(self.slow_approval),
                "launch_record": self._ref(self.slow_launch),
                "manifest": {
                    **self._ref(self.slow_manifest),
                    "final": True,
                    "rows": 30_021,
                    "errors": 0,
                },
                "output": self._ref(self.slow_output),
                "technical_quality": {
                    **self._ref(self.slow_quality),
                    "decision": (
                        "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
                        "AWAIT_OFFICIAL_IDENTITY_APPROVAL"
                    ),
                    "accepted": True,
                },
                "gate": self._ref(self.gate),
                "identity_verification_required": True,
                "identity_verification_authorized": False,
                "evaluator_or_oos_authorized": False,
            },
            "official_identity_phase_1": {
                **self._ref(self.identity_proposal),
                "proposal_hash": self.identity_proposal_hash,
                "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                "phase_1_approved": False,
                "network_execution_authorized": False,
                "identity_output_authorized": False,
            },
            "pit_shadow_track": {
                "active_pointer": {
                    **self._ref(self.active_pit_pointer),
                    "plan_hash": self.active_plan_hash,
                    "status": "ACTIVE",
                    "has_pending_segment": False,
                },
                "quality_ledger": {
                    **self._ref(self.quality_ledger),
                    "accepted_distinct_dates": 10,
                    "hypothesis_contract_sha256": "6" * 64,
                },
                "accepted_distinct_dates": 10,
                "train_target_distinct_dates": 20,
                "extension_plan": {
                    **self._ref(self.extension_plan),
                    "plan_hash": self.extension_plan_hash,
                    "mode": "PlanOnly",
                    "schedule_approved": False,
                },
                "extension_segments": 10,
                "extension_first_start_local": "2026-08-14T01:00:00+03:00",
                "extension_last_end_local": "2026-08-23T01:20:00+03:00",
                "extension_approval_required": True,
                "extension_activation_authorized": False,
                "collector_launch_authorized": False,
            },
            "dense_three_hour_refreeze_phase_1": {
                **self._ref(self.dense_proposal),
                "proposal_hash": self.dense_proposal_hash,
                "status": "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
                "phase_1_approved": False,
                "implementation_authorized": False,
                "collector_launch_authorized": False,
            },
            "permissions": {
                name: False
                for name in (
                    "global_writer_present",
                    "identity_offline_implementation_authorized",
                    "identity_verification_authorized",
                    "pit_extension_activation_authorized",
                    "dense_refreeze_implementation_authorized",
                    "collector_launch_authorized",
                    "evaluator_or_oos_authorized",
                    "returns_or_pnl_authorized",
                    "grid_or_retune_authorized",
                    "execution_probe_authorized",
                    "paper_or_live_authorized",
                    "private_api_or_real_capital_authorized",
                    "leverage_or_margin_authorized",
                    "stopped_incomplete_retry_authorized",
                )
            },
            "approval_checkpoints": [
                {
                    "id": "pit_extension_schedule_activation",
                    "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                    "plan_hash": self.extension_plan_hash,
                    "plan_file_sha256": _sha256(self.extension_plan),
                },
                {
                    "id": "slow_liquidity_identity_offline_phase_1",
                    "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                    "proposal_hash": self.identity_proposal_hash,
                    "proposal_file_sha256": _sha256(self.identity_proposal),
                },
                {
                    "id": "dense_three_hour_segmented_refreeze_phase_1",
                    "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                    "proposal_hash": self.dense_proposal_hash,
                    "proposal_file_sha256": _sha256(self.dense_proposal),
                },
            ],
            "next_safe_action": "await_one_exact_approval_checkpoint",
            "readiness_hash_method": (
                "sha256_canonical_json_excluding_readiness_hash"
            ),
        }
        report["readiness_hash"] = _canonical_hash_without(
            report,
            "readiness_hash",
        )
        _write_json(self.report, report)
        _write_json(
            self.pointer,
            {
                "schema": (
                    "trading_mvp_one_week_edge_sprint_readiness_pointer_v1"
                ),
                "status": "ACTIVE",
                "project": "trading_mvp",
                "readiness_path": str(self.report.resolve()),
                "readiness_file_sha256": _sha256(self.report),
                "readiness_hash": report["readiness_hash"],
                "updated_at_utc": "2026-08-13T11:12:18+00:00",
            },
        )


class CurrentSprintReadinessTests(unittest.TestCase):
    def test_missing_pointer_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaises(CurrentSprintReadinessError) as raised:
                resolve_current_sprint_readiness(
                    root / "missing-pointer.json",
                    gate_path=root / "gate.json",
                    pit_pointer_path=root / "pit-pointer.json",
                    writer_claim_path=root / "writer-claim.json",
                )

            self.assertEqual(raised.exception.status, "MISSING")

    def test_exact_bundle_resolves_without_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))

            with fixture.trust_anchor_patch():
                result = resolve_current_sprint_readiness(
                    fixture.pointer,
                    gate_path=fixture.gate,
                    pit_pointer_path=fixture.active_pit_pointer,
                    writer_claim_path=fixture.writer_claim,
                )

            self.assertEqual(result["status"], "READY")
            self.assertFalse(result["execution_authorized"])
            self.assertEqual(
                result["pit_schedule_extension_candidate"]["plan_hash"],
                fixture.extension_plan_hash,
            )
            self.assertFalse(
                result["pit_schedule_extension_candidate"][
                    "automatic_launch_allowed"
                ]
            )
            self.assertEqual(
                result["primary_frozen_basis_terminal"]["status"],
                "TERMINAL_CLOSED_INSUFFICIENT_DATA",
            )
            self.assertFalse(
                result["primary_frozen_basis_terminal"][
                    "repeat_same_contract_authorized"
                ]
            )

    def test_legacy_v1_readiness_requires_safe_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            report = json.loads(fixture.report.read_text(encoding="utf-8"))
            report["schema"] = (
                "trading_mvp_one_week_edge_sprint_current_readiness_v1"
            )
            _reseal_readiness_bundle(fixture, report)

            with self.assertRaisesRegex(
                CurrentSprintReadinessError,
                "superseded",
            ) as raised:
                with fixture.trust_anchor_patch():
                    resolve_current_sprint_readiness(
                        fixture.pointer,
                        gate_path=fixture.gate,
                        pit_pointer_path=fixture.active_pit_pointer,
                        writer_claim_path=fixture.writer_claim,
                    )

            self.assertEqual(raised.exception.status, "REFRESH_REQUIRED")

    def test_readiness_file_substitution_is_integrity_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            fixture.report.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(
                CurrentSprintReadinessError,
                "readiness file hash mismatch",
            ) as raised:
                with fixture.trust_anchor_patch():
                    resolve_current_sprint_readiness(
                        fixture.pointer,
                        gate_path=fixture.gate,
                        pit_pointer_path=fixture.active_pit_pointer,
                        writer_claim_path=fixture.writer_claim,
                    )

            self.assertEqual(raised.exception.status, "INVALID")

    def test_pointer_cannot_route_outside_readiness_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            escaped_report = fixture.root / "escaped-readiness.json"
            escaped_report.write_bytes(fixture.report.read_bytes())
            pointer = json.loads(fixture.pointer.read_text(encoding="utf-8"))
            pointer["readiness_path"] = str(escaped_report.resolve())
            pointer["readiness_file_sha256"] = _sha256(escaped_report)
            _write_json(fixture.pointer, pointer)

            with self.assertRaisesRegex(
                CurrentSprintReadinessError,
                "readiness path escapes the allowed directory",
            ) as raised:
                with fixture.trust_anchor_patch():
                    resolve_current_sprint_readiness(
                        fixture.pointer,
                        gate_path=fixture.gate,
                        pit_pointer_path=fixture.active_pit_pointer,
                        writer_claim_path=fixture.writer_claim,
                    )

            self.assertEqual(raised.exception.status, "INVALID")

    def test_resealed_permission_expansion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            report = json.loads(fixture.report.read_text(encoding="utf-8"))
            report["permissions"]["collector_launch_authorized"] = True
            _reseal_readiness_bundle(fixture, report)

            with self.assertRaisesRegex(
                CurrentSprintReadinessError,
                "readiness illegally enables collector_launch_authorized",
            ) as raised:
                with fixture.trust_anchor_patch():
                    resolve_current_sprint_readiness(
                        fixture.pointer,
                        gate_path=fixture.gate,
                        pit_pointer_path=fixture.active_pit_pointer,
                        writer_claim_path=fixture.writer_claim,
                    )

            self.assertEqual(raised.exception.status, "INVALID")

    def test_dynamic_gate_drift_requires_refresh_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            _write_json(
                fixture.gate,
                {"status": "READY_FOR_POSTPROCESS", "run_id": "new-run"},
            )

            with self.assertRaises(CurrentSprintReadinessError) as raised:
                with fixture.trust_anchor_patch():
                    resolve_current_sprint_readiness(
                        fixture.pointer,
                        gate_path=fixture.gate,
                        pit_pointer_path=fixture.active_pit_pointer,
                        writer_claim_path=fixture.writer_claim,
                    )

            self.assertEqual(raised.exception.status, "REFRESH_REQUIRED")

    def test_writer_claim_appearing_after_readiness_requires_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            _write_json(
                fixture.writer_claim,
                {"status": "RUNNING", "run_id": "another-market-data-writer"},
            )

            with self.assertRaisesRegex(
                CurrentSprintReadinessError,
                "global market-data writer claim appeared after readiness",
            ) as raised:
                with fixture.trust_anchor_patch():
                    resolve_current_sprint_readiness(
                        fixture.pointer,
                        gate_path=fixture.gate,
                        pit_pointer_path=fixture.active_pit_pointer,
                        writer_claim_path=fixture.writer_claim,
                    )

            self.assertEqual(raised.exception.status, "REFRESH_REQUIRED")

    def test_valid_readiness_supersedes_expired_legacy_dense_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = CurrentSprintReadinessFixture(Path(temp_dir))
            with fixture.trust_anchor_patch():
                readiness = resolve_current_sprint_readiness(
                    fixture.pointer,
                    gate_path=fixture.gate,
                    pit_pointer_path=fixture.active_pit_pointer,
                    writer_claim_path=fixture.writer_claim,
                )
            policy = {
                "policy_id": "legacy-policy",
                "thread_id": "thread",
                "run_policy": {
                    "long_run_requires_explicit_per_campaign_approval": True,
                    "preapproved_short_segment_max_runtime_sec": 1_800,
                },
                "continuous_production_policy": {"path": "legacy.json"},
                "next_long_campaign": {
                    "status": "READY_FOR_APPROVAL",
                    "campaign_id": "stale-dense-24h",
                    "plan_path": "stale-plan.json",
                    "plan_hash": "a" * 64,
                    "max_runtime_sec": 88_200,
                    "actual_collection_allowed": False,
                },
            }

            result = evaluate_autopilot_state(
                policy=policy,
                policy_hash="b" * 64,
                gate={"status": "READY_FOR_POSTPROCESS", "run_id": fixture.run_id},
                usage={"decision": "CONTINUE", "remaining_percent": 100.0},
                prior_state=None,
                observed_at_utc="2026-08-13T11:30:00Z",
                schedule_window={"status": "NO_PENDING_SEGMENT"},
                campaign_window={"status": "CLOSED"},
                productive_fallback={"status": "EXHAUSTED", "task": None},
                research_fallback={
                    "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                    "task": None,
                },
                pit_schedule_extension={"status": "REFRESH_REQUIRED"},
                long_campaign_approval={
                    "status": "NOT_APPROVED",
                    "launch_window_status": "EXPIRED",
                },
                current_sprint_readiness=readiness,
            )

            self.assertEqual(
                result["decision"],
                "AWAIT_EXACT_ONE_WEEK_EDGE_SPRINT_APPROVAL_CHECKPOINT",
            )
            self.assertEqual(
                result["next_action"],
                "await_one_exact_approval_checkpoint",
            )
            self.assertFalse(result["action_due"])
            self.assertFalse(result["run_approval_notification_required"])
            self.assertEqual(
                result["long_campaign_candidate"]["status"],
                "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
            )
            self.assertEqual(
                result["superseded_policy_candidates"]["long_campaign"][
                    "campaign_id"
                ],
                "stale-dense-24h",
            )
            self.assertIsNone(result["long_campaign_approval"])
            self.assertEqual(
                result["dense_ws_postrun_disposition"]["status"],
                "NOT_APPLICABLE_CURRENT_SPRINT_READINESS",
            )
            self.assertFalse(
                result["dense_ws_postrun_disposition"]["execution_authorized"]
            )
            self.assertEqual(
                result["superseded_policy_candidates"]["long_campaign_approval"][
                    "launch_window_status"
                ],
                "EXPIRED",
            )
            self.assertEqual(
                result["pit_schedule_extension_candidate"]["plan_hash"],
                fixture.extension_plan_hash,
            )

    def test_invalid_readiness_stops_stale_legacy_routing(self) -> None:
        result = evaluate_autopilot_state(
            policy={"policy_id": "policy", "thread_id": "thread"},
            policy_hash="a" * 64,
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage={"decision": "CONTINUE", "remaining_percent": 100.0},
            prior_state=None,
            observed_at_utc="2026-08-13T11:30:00Z",
            current_sprint_readiness={
                "status": "INVALID",
                "error": "readiness file hash mismatch",
            },
        )

        self.assertEqual(result["status"], "CRITICAL_STOP")
        self.assertEqual(
            result["decision"],
            "CRITICAL_STOP_CURRENT_SPRINT_READINESS_INTEGRITY",
        )
        self.assertTrue(result["stop_new_actions"])
        self.assertTrue(result["action_due"])
        self.assertTrue(result["critical_checkpoint_notification_required"])

    def test_phase1_identity_runtime_routes_to_exact_execution_approval(self) -> None:
        result = evaluate_autopilot_state(
            policy={"policy_id": "policy", "thread_id": "thread"},
            policy_hash="a" * 64,
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage={"decision": "CONTINUE", "remaining_percent": 100.0},
            prior_state=None,
            observed_at_utc="2026-08-13T11:30:00Z",
            current_sprint_readiness={
                "status": "READY",
                "source_status": (
                    "IDENTITY_RUNTIME_FROZEN_AWAIT_EXACT_CODE_BOUND_"
                    "EXECUTION_APPROVAL"
                ),
                "execution_authorized": False,
                "next_safe_action": (
                    "await_exact_code_bound_identity_execution_approval"
                ),
            },
        )

        self.assertEqual(
            result["decision"],
            "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_EXECUTION_APPROVAL",
        )
        self.assertFalse(result["action_due"])
        self.assertFalse(result["stop_new_actions"])

    def test_topology_v2_integrity_defect_waits_for_v3_offline_refreeze(self) -> None:
        result = evaluate_autopilot_state(
            policy={"policy_id": "policy", "thread_id": "thread"},
            policy_hash="a" * 64,
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage={"decision": "CONTINUE", "remaining_percent": 100.0},
            prior_state=None,
            observed_at_utc="2026-08-14T05:35:00Z",
            current_sprint_readiness={
                "status": "READY",
                "source_status": (
                    "TOPOLOGY_V2_LAUNCHER_REJECTED_AWAIT_V3_OFFLINE_"
                    "REFREEZE_APPROVAL"
                ),
                "execution_authorized": False,
                "next_safe_action": (
                    "await_exact_slow_liquidity_official_currentness_"
                    "topology_v3_offline_refreeze_approval"
                ),
            },
        )

        self.assertEqual(
            result["decision"],
            "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_"
            "V3_OFFLINE_REFREEZE_APPROVAL",
        )
        self.assertTrue(result["action_due"])
        self.assertFalse(result["stop_new_actions"])
        self.assertFalse(
            result["current_sprint_readiness"]["execution_authorized"]
        )

    def test_phase2_identity_runtime_routes_only_exact_visible_run(self) -> None:
        result = evaluate_autopilot_state(
            policy={"policy_id": "policy", "thread_id": "thread"},
            policy_hash="a" * 64,
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage={"decision": "CONTINUE", "remaining_percent": 100.0},
            prior_state=None,
            observed_at_utc="2026-08-13T11:30:00Z",
            current_sprint_readiness={
                "status": "READY",
                "source_status": (
                    "IDENTITY_RUNTIME_FROZEN_WITH_EXACT_CODE_BOUND_"
                    "EXECUTION_APPROVAL"
                ),
                "execution_authorized": True,
                "next_safe_action": (
                    "run_exact_approved_slow_liquidity_official_identity_visible"
                ),
            },
        )

        self.assertEqual(
            result["decision"],
            "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
        )
        self.assertTrue(result["action_due"])
        self.assertFalse(result["stop_new_actions"])

    def test_running_gate_has_monitor_only_priority_over_stale_readiness(self) -> None:
        result = evaluate_autopilot_state(
            policy={"policy_id": "policy", "thread_id": "thread"},
            policy_hash="a" * 64,
            gate={"status": "RUNNING", "run_id": "active-writer"},
            usage={"decision": "CONTINUE", "remaining_percent": 100.0},
            prior_state=None,
            observed_at_utc="2026-08-13T11:30:00Z",
            current_sprint_readiness={
                "status": "INVALID",
                "error": "stale readiness while writer is running",
            },
        )

        self.assertEqual(result["status"], "RUNNING_MONITOR_ONLY")
        self.assertEqual(result["decision"], "MONITOR_ACTIVE_RUN")
        self.assertTrue(result["stop_new_actions"])
        self.assertTrue(result["allow_running_writer_to_finish"])
        self.assertFalse(result["action_due"])

    def test_refresh_required_blocks_launch_but_is_not_integrity_alarm(self) -> None:
        result = evaluate_autopilot_state(
            policy={"policy_id": "policy", "thread_id": "thread"},
            policy_hash="a" * 64,
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage={"decision": "CONTINUE", "remaining_percent": 100.0},
            prior_state=None,
            observed_at_utc="2026-08-13T11:30:00Z",
            current_sprint_readiness={
                "status": "REFRESH_REQUIRED",
                "error": "current gate changed",
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "REFRESH_CURRENT_SPRINT_READINESS",
        )
        self.assertTrue(result["stop_new_actions"])
        self.assertTrue(result["action_due"])
        self.assertFalse(result["critical_checkpoint_notification_required"])


if __name__ == "__main__":
    unittest.main()
