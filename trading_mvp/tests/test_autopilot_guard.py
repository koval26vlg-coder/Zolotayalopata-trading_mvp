from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autopilot_guard import (  # noqa: E402
    evaluate_autopilot_state,
    resolve_dense_ws_postrun,
    resolve_long_campaign_approval,
    resolve_productive_fallback,
    resolve_research_critical_checkpoint,
    resolve_schedule_window,
    resolve_pit_schedule_extension,
)


POLICY = {
    "policy_id": "test-policy",
    "thread_id": "test-thread",
    "recovery": {
        "same_immutable_run_auto_recovery": True,
    },
    "productive_fallback_queue": {
        "tasks": [
            {
                "id": "baseline",
                "runner": "code_baseline_manifest",
                "max_runtime_sec": 300,
                "max_attempts": 1,
            },
            {
                "id": "regression",
                "runner": "python_unittest",
                "max_runtime_sec": 600,
                "max_attempts": 1,
            },
        ]
    },
}


def _usage(decision: str, remaining: float = 85.0) -> dict:
    return {
        "decision": decision,
        "remaining_percent": remaining,
        "window_minutes": 10_080,
    }


def _extension_policy_fixture(
    root: Path,
    *,
    audit_observed_at: str,
) -> tuple[dict, Path]:
    ledger = root / "quality-certifications.jsonl"
    ledger.write_text('{"certification_id":"one"}\n', encoding="utf-8")
    ledger_sha = hashlib.sha256(ledger.read_bytes()).hexdigest()

    plan = root / "extension.json"
    plan.write_text(
        json.dumps(
            {
                "plan_hash": "d" * 64,
                "schedule_approved": False,
                "collection_started": False,
                "approval_phrase": "approve exact extension",
            }
        ),
        encoding="utf-8",
    )
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()

    audit = root / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_pit_schedule_horizon_audit_v1",
                "mode": "PlanOnly",
                "observed_at": audit_observed_at,
                "source_schedule": {
                    "plan_hash": "e" * 64,
                },
                "quality_ledger": {
                    "path": str(ledger),
                    "file_sha256": ledger_sha,
                },
                "horizon": {
                    "decision": "PLANONLY_EXTENSION_REQUIRED",
                    "target_distinct_dates": 20,
                    "maximum_reachable_distinct_dates": 16,
                    "train_gate_shortfall_dates": 4,
                    "recommended_extension_nights": 5,
                },
                "extension_proposal": {
                    "plan_hash": "d" * 64,
                    "output_path": str(plan),
                    "output_sha256": plan_sha,
                    "nights": 5,
                    "combined_maximum_reachable_distinct_dates": 21,
                    "activated": False,
                    "requires_explicit_schedule_approval": True,
                },
            }
        ),
        encoding="utf-8",
    )
    audit_sha = hashlib.sha256(audit.read_bytes()).hexdigest()
    return (
        {
            "pit_schedule_extension_candidate": {
                "horizon_audit_path": str(audit),
                "horizon_audit_sha256": audit_sha,
                "plan_path": str(plan),
                "plan_file_sha256": plan_sha,
                "plan_hash": "d" * 64,
                "source_plan_hash": "e" * 64,
                "nights": 5,
                "segment_duration_sec": 1_200,
                "approval_request_not_before_local": (
                    "2026-08-10T19:00:00+03:00"
                ),
                "start_local": "2026-08-12T01:00:00+03:00",
                "hard_deadline_local": "2026-08-16T07:00:00+03:00",
                "requires_fresh_horizon_audit_before_approval": True,
                "fresh_horizon_audit_max_age_sec": 3_600,
                "fresh_horizon_audit_must_not_predate_approval_window": True,
                "fresh_horizon_audit_must_match_current_quality_ledger": True,
            }
        },
        ledger,
    )


class AutopilotGuardTests(unittest.TestCase):
    def _evaluate(
        self,
        gate: dict,
        *,
        usage: dict | None = None,
        prior: dict | None = None,
        schedule_window: dict | None = None,
        campaign_window: dict | None = None,
        productive_fallback: dict | None = None,
        research_fallback: dict | None = None,
        pit_schedule_extension: dict | None = None,
    ) -> dict:
        return evaluate_autopilot_state(
            policy=POLICY,
            policy_hash="abc",
            gate=gate,
            usage=usage or _usage("CONTINUE"),
            prior_state=prior,
            observed_at_utc="2026-07-28T08:00:00Z",
            schedule_window=schedule_window,
            campaign_window=campaign_window,
            productive_fallback=productive_fallback,
            research_fallback=research_fallback,
            pit_schedule_extension=pit_schedule_extension,
        )

    def test_ready_gate_continues_without_human_confirmation(self) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
                "next_step_after_ready": "run bounded next step",
            }
        )
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["decision"], "CONTINUE_NEXT_ALLOWED_ACTION")
        self.assertFalse(result["stop_new_actions"])
        self.assertTrue(result["action_due"])

    def test_ready_gate_runs_productive_fallback_while_schedule_waits(self) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
                "next_step_after_ready": "run bounded next step",
            },
            schedule_window={
                "status": "WAITING",
                "run_id": "next",
                "start_local": "2026-07-29T01:00:00+03:00",
                "hard_deadline_local": "2026-07-29T07:00:00+03:00",
                "eta_sec": 61_200,
            },
            productive_fallback={
                "status": "READY",
                "task": {
                    "id": "baseline",
                    "runner": "code_baseline_manifest",
                    "max_runtime_sec": 300,
                },
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["decision"], "CONTINUE_PRODUCTIVE_FALLBACK")
        self.assertFalse(result["stop_new_actions"])
        self.assertTrue(result["action_due"])
        self.assertEqual(result["next_action"], "baseline")
        self.assertEqual(result["productive_fallback"]["task"]["id"], "baseline")
        self.assertEqual(result["schedule_window"]["run_id"], "next")

    def test_ready_gate_refreshes_research_when_both_queues_are_exhausted(self) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
            },
            schedule_window={
                "status": "WAITING",
                "run_id": "next",
                "eta_sec": 61_200,
            },
            productive_fallback={
                "status": "EXHAUSTED",
                "task": None,
            },
            research_fallback={
                "status": "EXHAUSTED",
                "task": None,
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["decision"], "REFRESH_BOUNDED_RESEARCH_CATALOG")
        self.assertTrue(result["action_due"])
        self.assertEqual(
            result["next_action"],
            "derive_next_catalog_from_latest_readiness_audit",
        )

    def test_ready_gate_waits_when_latest_audit_has_no_material_gap(
        self,
    ) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
            },
            schedule_window={
                "status": "WAITING",
                "run_id": "next",
                "eta_sec": 61_200,
            },
            productive_fallback={
                "status": "EXHAUSTED",
                "task": None,
            },
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
        )
        self.assertFalse(result["stop_new_actions"])
        self.assertFalse(result["action_due"])
        self.assertEqual(
            result["next_action"],
            "wait_for_exact_pit_segment_due",
        )

    def test_open_campaign_window_without_candidate_stays_active(self) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-07-30T16:00:00Z",
            schedule_window={
                "status": "WAITING",
                "run_id": "pit_next",
            },
            campaign_window={
                "status": "OPEN",
                "window_id": "WEEKNIGHT_2026-07-30_2026-07-31",
                "approval_request_status": "DUE",
            },
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "ACTIVE_NO_POSITIVE_RUN_CANDIDATE",
        )
        self.assertFalse(result["action_due"])
        self.assertFalse(result["run_approval_notification_required"])
        self.assertEqual(
            result["next_action"],
            "prepare_next_long_campaign_planonly_without_start",
        )

    def test_ready_long_candidate_requests_one_exact_approval(self) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": "dense_ws_weekend_01",
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-07-30T16:00:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={
                "status": "OPEN",
                "window_id": "WEEKNIGHT_2026-07-30_2026-07-31",
                "approval_request_status": "DUE",
            },
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )

        self.assertEqual(
            result["decision"],
            "AWAIT_EXPLICIT_LONG_CAMPAIGN_APPROVAL",
        )
        self.assertTrue(result["action_due"])
        self.assertTrue(result["run_approval_notification_required"])
        self.assertEqual(
            result["next_action"],
            "prepare_and_request_exact_approval_for_dense_ws_weekend_01",
        )

        repeated = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=result,
            observed_at_utc="2026-07-30T16:20:00Z",
            schedule_window={
                "status": "WAITING",
                "run_id": "pit_next",
            },
            campaign_window=result["campaign_window"],
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )
        self.assertFalse(repeated["action_due"])
        self.assertFalse(repeated["run_approval_notification_required"])

    def test_unapproved_long_campaign_window_expires_fail_closed(self) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": "dense_ws_weekend_01",
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "start_local": "2026-08-03T01:30:00+03:00",
                "latest_launch_local": "2026-08-03T01:35:00+03:00",
                "hard_deadline_local": "2026-08-04T02:00:00+03:00",
                "max_runtime_sec": 86_400,
            },
        }

        waiting = resolve_long_campaign_approval(
            policy,
            observed_at_utc="2026-08-02T21:59:00Z",
        )
        due = resolve_long_campaign_approval(
            policy,
            observed_at_utc="2026-08-02T22:32:00Z",
        )
        expired = resolve_long_campaign_approval(
            policy,
            observed_at_utc="2026-08-02T22:36:00Z",
        )

        self.assertEqual(waiting["status"], "NOT_APPROVED")
        self.assertEqual(waiting["launch_window_status"], "WAITING")
        self.assertEqual(due["launch_window_status"], "DUE")
        self.assertEqual(expired["launch_window_status"], "EXPIRED")

        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-02T22:36:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={
                "status": "OPEN",
                "window_id": "WEEKNIGHT_2026-08-03_2026-08-04",
                "approval_request_status": "DUE",
            },
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
            long_campaign_approval=expired,
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_WINDOW_EXPIRED",
        )
        self.assertTrue(result["action_due"])
        self.assertTrue(result["critical_checkpoint_notification_required"])
        self.assertEqual(
            result["next_action"],
            "prepare_new_exact_long_campaign_window_without_resume",
        )

    def test_hash_bound_long_campaign_approval_waits_then_becomes_due(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = root / "plan.json"
            plan.write_text('{"plan_hash":"' + "a" * 64 + '"}\n', encoding="utf-8")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            receipt = root / "approval.json"
            receipt_payload = {
                "schema": "trading_mvp_long_campaign_approval_v1",
                "status": "APPROVED",
                "campaign_id": "dense_ws_weekend_01",
                "plan_path": str(plan.resolve()),
                "plan_file_sha256": plan_sha,
                "plan_hash": "a" * 64,
                "earliest_launch_local": "2026-08-03T01:00:00+03:00",
                "writer_start_local": "2026-08-03T01:30:00+03:00",
                "latest_launch_local": "2026-08-03T01:35:00+03:00",
                "hard_deadline_local": "2026-08-04T02:00:00+03:00",
                "single_use": True,
                "stop_incomplete_recovery_authorized": False,
            }
            receipt.write_text(
                json.dumps(receipt_payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
            policy = {
                **POLICY,
                "next_long_campaign": {
                    "status": "READY_FOR_APPROVAL",
                    "campaign_id": "dense_ws_weekend_01",
                    "plan_path": str(plan.resolve()),
                    "plan_file_sha256": plan_sha,
                    "plan_hash": "a" * 64,
                    "start_local": "2026-08-03T01:30:00+03:00",
                    "hard_deadline_local": "2026-08-04T02:00:00+03:00",
                    "max_runtime_sec": 86_400,
                    "user_launch_approval": {
                        "status": "APPROVED",
                        "receipt_path": str(receipt.resolve()),
                        "receipt_sha256": receipt_sha,
                    },
                },
            }

            waiting = resolve_long_campaign_approval(
                policy,
                observed_at_utc="2026-08-02T20:00:00Z",
            )
            due = resolve_long_campaign_approval(
                policy,
                observed_at_utc="2026-08-02T22:25:00Z",
            )
            receipt.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt hash mismatch"):
                resolve_long_campaign_approval(
                    policy,
                    observed_at_utc="2026-08-02T22:25:00Z",
                )

        self.assertEqual(waiting["status"], "APPROVED")
        self.assertEqual(waiting["launch_window_status"], "WAITING")
        self.assertEqual(due["status"], "APPROVED")
        self.assertEqual(due["launch_window_status"], "DUE")
        self.assertEqual(due["plan_hash"], "a" * 64)
        self.assertFalse(due["stop_incomplete_recovery_authorized"])

    def test_approved_long_campaign_is_not_re_requested_and_starts_only_when_due(
        self,
    ) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": "dense_ws_weekend_01",
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        common = {
            "policy": policy,
            "policy_hash": "abc",
            "gate": {"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            "usage": _usage("CONTINUE"),
            "prior_state": None,
            "schedule_window": {"status": "WAITING", "run_id": "pit_next"},
            "campaign_window": {"status": "OPEN"},
            "productive_fallback": {"status": "EXHAUSTED", "task": None},
            "research_fallback": {
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        }
        waiting = evaluate_autopilot_state(
            **common,
            observed_at_utc="2026-08-02T20:00:00Z",
            long_campaign_approval={
                "status": "APPROVED",
                "launch_window_status": "WAITING",
                "campaign_id": "dense_ws_weekend_01",
                "plan_hash": "a" * 64,
            },
        )
        due = evaluate_autopilot_state(
            **common,
            observed_at_utc="2026-08-02T22:25:00Z",
            long_campaign_approval={
                "status": "APPROVED",
                "launch_window_status": "DUE",
                "campaign_id": "dense_ws_weekend_01",
                "plan_hash": "a" * 64,
            },
        )

        self.assertEqual(
            waiting["decision"],
            "WAIT_APPROVED_LONG_CAMPAIGN_WINDOW",
        )
        self.assertFalse(waiting["action_due"])
        self.assertFalse(waiting["run_approval_notification_required"])
        self.assertEqual(
            due["decision"],
            "START_APPROVED_LONG_CAMPAIGN_VISIBLE",
        )
        self.assertTrue(due["action_due"])
        self.assertEqual(
            due["next_action"],
            "start_approved_long_campaign_dense_ws_weekend_01",
        )

    def test_due_preapproved_pit_segment_preempts_approved_long_campaign(
        self,
    ) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "current_pit_schedule": {
                "all_listed_segments_are_preapproved": True,
                "per_segment_launch_approval_required": False,
                "automatic_launch_allowed": True,
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": "dense_ws_weekend_01",
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-02T22:00:00Z",
            schedule_window={
                "status": "DUE",
                "run_id": "pit_n06",
                "duration_sec": 1_200,
            },
            campaign_window={"status": "OPEN"},
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
            long_campaign_approval={
                "status": "APPROVED",
                "launch_window_status": "DUE",
                "campaign_id": "dense_ws_weekend_01",
                "plan_hash": "a" * 64,
            },
        )

        self.assertEqual(
            result["decision"],
            "START_PREAPPROVED_SHORT_SEGMENT_VISIBLE",
        )
        self.assertEqual(
            result["next_action"],
            "start_preapproved_short_segment_pit_n06",
        )

    def test_completed_dense_campaign_dispatches_hash_bound_quality_stage(self) -> None:
        campaign_id = "dense_ws_weekend_01"
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": campaign_id,
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={
                "status": "READY_FOR_POSTPROCESS",
                "run_id": campaign_id,
                "run_type": "dense_ws_campaign",
                "manifest_path": "campaign-manifest.json",
                "completed": True,
                "final": True,
            },
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-03T04:31:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "OPEN"},
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "RUN_DENSE_WS_CAMPAIGN_DATA_QUALITY",
        )
        self.assertTrue(result["action_due"])
        self.assertFalse(result["stop_new_actions"])
        self.assertEqual(
            result["next_action"],
            "run_dense_ws_postrun_visible",
        )
        self.assertFalse(result["run_approval_notification_required"])

    def test_dense_ws_quality_acceptance_dispatches_causal_materialization(self) -> None:
        campaign_id = "dense_ws_weekend_01"
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": campaign_id,
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={
                "status": "READY_FOR_POSTPROCESS",
                "run_id": campaign_id,
                "run_type": "dense_ws_campaign",
                "manifest_path": "campaign-manifest.json",
                "completed": True,
                "final": True,
            },
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-04T01:31:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "OPEN"},
            dense_ws_postrun={
                "schema": "trading_mvp_dense_ws_postrun_disposition_v1",
                "status": "QUALITY_ACCEPTED",
                "campaign_id": campaign_id,
                "plan_hash": "a" * 64,
            },
        )

        self.assertEqual(result["decision"], "RUN_DENSE_WS_CAUSAL_MATERIALIZATION")
        self.assertEqual(result["next_action"], "run_dense_ws_postrun_visible")
        self.assertTrue(result["action_due"])

    def test_dense_ws_materialization_prepares_bound_evaluator_planonly(self) -> None:
        campaign_id = "dense_ws_weekend_01"
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": campaign_id,
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
            "dense_ws_signal_evaluator_freeze": {
                "status": "FROZEN_NOT_AUTHORIZED",
                "plan_hash": "b" * 64,
                "executable": False,
                "evaluation_authorized": False,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={
                "status": "READY_FOR_POSTPROCESS",
                "run_id": campaign_id,
                "run_type": "dense_ws_campaign",
                "manifest_path": "campaign-manifest.json",
                "completed": True,
                "final": True,
            },
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-04T01:31:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "OPEN"},
            dense_ws_postrun={
                "schema": "trading_mvp_dense_ws_postrun_disposition_v1",
                "status": "MATERIALIZATION_ACCEPTED",
                "campaign_id": campaign_id,
                "plan_hash": "a" * 64,
                "deterministic_result_hash": "c" * 64,
            },
        )

        self.assertEqual(
            result["decision"],
            "BUILD_DENSE_WS_MATERIALIZATION_BOUND_EVALUATOR_PLANONLY",
        )
        self.assertEqual(
            result["next_action"],
            "run_dense_ws_materialization_bound_planonly_visible",
        )
        self.assertTrue(result["action_due"])
        self.assertFalse(result["stop_new_actions"])

    def test_dense_ws_bound_planonly_requires_exact_evaluator_approval(self) -> None:
        campaign_id = "dense_ws_weekend_01"
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": campaign_id,
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={
                "status": "READY_FOR_POSTPROCESS",
                "run_id": campaign_id,
                "run_type": "dense_ws_campaign",
                "manifest_path": "campaign-manifest.json",
                "completed": True,
                "final": True,
            },
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-04T01:31:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "OPEN"},
            dense_ws_postrun={
                "schema": "trading_mvp_dense_ws_postrun_disposition_v1",
                "status": "MATERIALIZATION_BOUND_PLANONLY_READY",
                "campaign_id": campaign_id,
                "plan_hash": "a" * 64,
                "materialization_bound_plan_hash": "d" * 64,
            },
        )

        self.assertEqual(
            result["decision"],
            "USER_REVIEW_REQUIRED_EXACT_DENSE_WS_EVALUATOR_APPROVAL",
        )
        self.assertEqual(
            result["next_action"],
            "request_exact_hash_bound_evaluator_approval",
        )
        self.assertTrue(result["critical_checkpoint_notification_required"])
        self.assertFalse(result["stop_new_actions"])

    def test_dense_ws_postrun_failure_stops_only_dense_branch(self) -> None:
        campaign_id = "dense_ws_weekend_01"
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "next_long_campaign": {
                "status": "READY_FOR_APPROVAL",
                "campaign_id": campaign_id,
                "plan_path": "sealed-plan.json",
                "plan_hash": "a" * 64,
                "max_runtime_sec": 86_400,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={
                "status": "READY_FOR_POSTPROCESS",
                "run_id": campaign_id,
                "run_type": "dense_ws_campaign",
                "manifest_path": "campaign-manifest.json",
                "completed": True,
                "final": True,
            },
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-04T01:31:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "OPEN"},
            dense_ws_postrun={
                "schema": "trading_mvp_dense_ws_postrun_disposition_v1",
                "status": "STOPPED_INCOMPLETE",
                "campaign_id": campaign_id,
                "plan_hash": "a" * 64,
                "reason": "dead_terminal",
            },
        )

        self.assertEqual(
            result["decision"],
            "USER_REVIEW_REQUIRED_DENSE_WS_POSTRUN_RECOVERY",
        )
        self.assertTrue(result["critical_checkpoint_notification_required"])
        self.assertFalse(result["stop_new_actions"])

    def test_resolves_dense_ws_postrun_evidence_progression(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            campaign_root = root / "campaign"
            campaign_root.mkdir()
            campaign_manifest = campaign_root / "campaign-manifest.json"
            campaign_manifest.write_text("{}\n", encoding="utf-8")
            campaign_id = "dense_ws_weekend_01"
            plan_hash = "a" * 64
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "plan_hash": plan_hash,
                        "outputs": {"campaign_root": str(campaign_root.resolve())},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            policy = {
                "next_long_campaign": {
                    "campaign_id": campaign_id,
                    "plan_path": str(plan_path.resolve()),
                    "plan_file_sha256": hashlib.sha256(
                        plan_path.read_bytes()
                    ).hexdigest(),
                    "plan_hash": plan_hash,
                },
                "dense_ws_postrun": {
                    "automatic_same_hash_through_materialization": True,
                    "output_names": {
                        "quality_report": "campaign-quality.json",
                        "regime_labels": "causal-regime-labels.jsonl",
                        "execution_snapshots": "execution-snapshots.jsonl",
                        "materialization_manifest": (
                            "causal-materialization-manifest.json"
                        ),
                        "owner": "owner.json",
                    },
                },
            }
            gate = {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": campaign_id,
                "run_type": "dense_ws_campaign",
                "manifest_path": str(campaign_manifest.resolve()),
                "completed": True,
                "final": True,
            }

            missing = resolve_dense_ws_postrun(policy, gate)
            self.assertEqual(missing["status"], "QUALITY_MISSING")
            postrun_root = campaign_root / "_postrun"
            postrun_root.mkdir()
            quality_path = postrun_root / "campaign-quality.json"
            quality_path.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_dense_ws_campaign_quality_v1",
                        "campaign_id": campaign_id,
                        "plan_hash": plan_hash,
                        "accepted": True,
                        "decision": "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            quality_ready = resolve_dense_ws_postrun(policy, gate)
            self.assertEqual(quality_ready["status"], "QUALITY_ACCEPTED")

            labels_path = postrun_root / "causal-regime-labels.jsonl"
            snapshots_path = postrun_root / "execution-snapshots.jsonl"
            labels_path.write_text("{}\n", encoding="utf-8")
            snapshots_path.write_text("{}\n", encoding="utf-8")
            materialization_path = (
                postrun_root / "causal-materialization-manifest.json"
            )
            materialization_path.write_text(
                json.dumps(
                    {
                        "schema": (
                            "trading_mvp_dense_ws_causal_materialization_v1"
                        ),
                        "campaign_id": campaign_id,
                        "plan_hash": plan_hash,
                        "accepted": True,
                        "decision": "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW",
                        "deterministic_result_hash": "b" * 64,
                        "quality_report": {
                            "path": str(quality_path.resolve()),
                            "sha256": hashlib.sha256(
                                quality_path.read_bytes()
                            ).hexdigest(),
                        },
                        "labels": {
                            "path": str(labels_path.resolve()),
                            "sha256": hashlib.sha256(
                                labels_path.read_bytes()
                            ).hexdigest(),
                        },
                        "execution_snapshots": {
                            "path": str(snapshots_path.resolve()),
                            "sha256": hashlib.sha256(
                                snapshots_path.read_bytes()
                            ).hexdigest(),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            complete = resolve_dense_ws_postrun(policy, gate)
            self.assertEqual(complete["status"], "MATERIALIZATION_ACCEPTED")
            self.assertTrue(
                complete["full_data_hash_revalidation_required_before_evaluator"]
            )

            builder_path = root / "bound-builder.py"
            wrapper_path = root / "bound-wrapper.ps1"
            builder_path.write_text("# builder\n", encoding="utf-8")
            wrapper_path.write_text("# wrapper\n", encoding="utf-8")
            frozen_plan_hash = "c" * 64
            frozen_contract_hash = "d" * 64
            policy["dense_ws_signal_evaluator_freeze"] = {
                "plan_hash": frozen_plan_hash,
                "contract_hash": frozen_contract_hash,
            }
            policy["dense_ws_materialization_bound_planonly"] = {
                "status": "READY_CONTRACT_FREEZE_ONLY",
                "automatic_same_hash_planonly_build_authorized": True,
                "builder_path": str(builder_path.resolve()),
                "builder_sha256": hashlib.sha256(
                    builder_path.read_bytes()
                ).hexdigest(),
                "visible_wrapper_path": str(wrapper_path.resolve()),
                "visible_wrapper_sha256": hashlib.sha256(
                    wrapper_path.read_bytes()
                ).hexdigest(),
                "output_name": "materialization-bound-evaluator-planonly.json",
                "owner_name": "materialization-bound-planonly-owner.json",
                "evaluation_authorized": False,
                "returns_pnl_oos_allowed": False,
                "network_collector_allowed": False,
                "grid_or_retune_allowed": False,
                "paper_live_private_api_real_capital_leverage_margin_allowed": False,
            }
            bound_path = postrun_root / policy[
                "dense_ws_materialization_bound_planonly"
            ]["output_name"]
            bound_path.write_text(
                json.dumps(
                    {
                        "identity": {"campaign_id": campaign_id},
                        "campaign": {"plan": {"plan_hash": plan_hash}},
                        "frozen_signal_evaluator_plan": {
                            "plan_hash": frozen_plan_hash
                        },
                        "frozen_signal_evaluator_contract": {
                            "contract_hash": frozen_contract_hash
                        },
                        "materialization": {
                            "manifest": {
                                "path": str(materialization_path.resolve()),
                                "file_sha256": hashlib.sha256(
                                    materialization_path.read_bytes()
                                ).hexdigest(),
                                "deterministic_result_hash": "b" * 64,
                            }
                        },
                        "plan_hash": "e" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            owner_path = postrun_root / policy[
                "dense_ws_materialization_bound_planonly"
            ]["owner_name"]
            owner_path.write_text(
                json.dumps(
                    {
                        "schema": (
                            "trading_mvp_dense_ws_"
                            "materialization_bound_plan_owner_v1"
                        ),
                        "campaign_id": campaign_id,
                        "campaign_plan_hash": plan_hash,
                        "frozen_plan_hash": frozen_plan_hash,
                        "status": "COMPLETE",
                        "final": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch(
                "autopilot_guard.dense_ws_bound_plan."
                "validate_materialization_bound_plan"
            ):
                bound_ready = resolve_dense_ws_postrun(policy, gate)
            self.assertEqual(
                bound_ready["status"],
                "MATERIALIZATION_BOUND_PLANONLY_READY",
            )
            self.assertFalse(bound_ready["evaluation_authorized"])
            self.assertFalse(bound_ready["returns_pnl_oos_allowed"])
            self.assertEqual(
                bound_ready["next_allowed_action"],
                "REQUEST_EXACT_HASH_BOUND_EVALUATOR_APPROVAL",
            )

    def test_long_campaign_contract_review_does_not_block_short_track(
        self,
    ) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
            "next_long_campaign": {
                "status": "USER_REVIEW_REQUIRED_CONTRACT_FREEZE",
                "campaign_id": "dense_ws_weekend_01",
                "candidate_contract_hash": "b" * 64,
                "requested_action": "authorize_dense_ws_contract_freeze",
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-07-30T16:00:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={
                "status": "OPEN",
                "window_id": "WEEKNIGHT_2026-07-30_2026-07-31",
            },
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT",
        )
        self.assertFalse(result["stop_new_actions"])
        self.assertTrue(result["action_due"])
        self.assertTrue(
            result["critical_checkpoint_notification_required"]
        )
        self.assertEqual(
            result["next_action"],
            "authorize_dense_ws_contract_freeze",
        )

    def test_due_pit_extension_preempts_already_notified_long_review(
        self,
    ) -> None:
        policy = {
            **POLICY,
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
            "next_long_campaign": {
                "status": "USER_REVIEW_REQUIRED_CONTRACT_FREEZE",
                "campaign_id": "dense_ws_weekend_01",
                "candidate_contract_hash": "b" * 64,
                "requested_action": "authorize_dense_ws_contract_freeze",
            },
        }
        extension = {
            "status": "READY_FOR_APPROVAL",
            "approval_request_status": "DUE",
            "plan_hash": "c" * 64,
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-10T16:00:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "CLOSED"},
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
            pit_schedule_extension=extension,
        )

        self.assertEqual(
            result["decision"],
            "AWAIT_EXPLICIT_PIT_SCHEDULE_EXTENSION_APPROVAL",
        )
        self.assertTrue(result["action_due"])
        self.assertTrue(result["run_approval_notification_required"])
        self.assertFalse(result["stop_new_actions"])

        repeated = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=result,
            observed_at_utc="2026-08-10T16:20:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "CLOSED"},
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
            pit_schedule_extension=extension,
        )
        self.assertFalse(repeated["action_due"])
        self.assertFalse(repeated["run_approval_notification_required"])

    def test_resolves_hash_bound_inactive_pit_extension_candidate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy, _ledger = _extension_policy_fixture(
                root,
                audit_observed_at="2026-07-30T21:00:00+03:00",
            )

            result = resolve_pit_schedule_extension(
                policy,
                observed_at_utc="2026-07-30T18:00:00Z",
            )

        self.assertEqual(result["status"], "READY_FOR_APPROVAL")
        self.assertEqual(result["approval_request_status"], "NOT_DUE")
        self.assertEqual(
            result["horizon_freshness"]["status"],
            "REFRESH_REQUIRED_AT_APPROVAL_WINDOW",
        )
        self.assertFalse(result["schedule_approved"])
        self.assertFalse(result["automatic_launch_allowed"])
        self.assertEqual(result["approval_phrase"], "")

    def test_due_pit_extension_blocks_stale_horizon_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, _ledger = _extension_policy_fixture(
                Path(temp_dir),
                audit_observed_at="2026-07-30T21:00:00+03:00",
            )

            result = resolve_pit_schedule_extension(
                policy,
                observed_at_utc="2026-08-10T16:10:00Z",
            )

        self.assertEqual(result["status"], "REFRESH_REQUIRED")
        self.assertEqual(
            result["approval_request_status"],
            "BLOCKED_STALE_HORIZON",
        )
        self.assertEqual(result["horizon_freshness"]["status"], "STALE")
        self.assertIn(
            "audit_predates_approval_window",
            result["horizon_freshness"]["reasons"],
        )
        self.assertIn(
            "audit_age_exceeds_limit",
            result["horizon_freshness"]["reasons"],
        )
        self.assertEqual(result["approval_phrase"], "")

    def test_due_pit_extension_exposes_only_fresh_approval_phrase(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, _ledger = _extension_policy_fixture(
                Path(temp_dir),
                audit_observed_at="2026-08-10T19:05:00+03:00",
            )

            result = resolve_pit_schedule_extension(
                policy,
                observed_at_utc="2026-08-10T16:10:00Z",
            )

        self.assertEqual(result["status"], "READY_FOR_APPROVAL")
        self.assertEqual(result["approval_request_status"], "DUE")
        self.assertEqual(result["horizon_freshness"]["status"], "FRESH")
        self.assertEqual(
            result["approval_phrase"],
            "approve exact extension",
        )

    def test_due_pit_extension_blocks_quality_ledger_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            policy, ledger = _extension_policy_fixture(
                Path(temp_dir),
                audit_observed_at="2026-08-10T19:05:00+03:00",
            )
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write('{"certification_id":"two"}\n')

            result = resolve_pit_schedule_extension(
                policy,
                observed_at_utc="2026-08-10T16:10:00Z",
            )

        self.assertEqual(result["status"], "REFRESH_REQUIRED")
        self.assertIn(
            "quality_ledger_hash_changed",
            result["horizon_freshness"]["reasons"],
        )
        self.assertEqual(result["approval_phrase"], "")

    def test_stale_due_extension_requests_routine_refresh_not_approval(
        self,
    ) -> None:
        result = evaluate_autopilot_state(
            policy={
                **POLICY,
                "continuous_production_policy": {
                    "path": "not-used-by-direct-evaluation",
                },
            },
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-08-10T16:10:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={"status": "CLOSED"},
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
            pit_schedule_extension={
                "status": "REFRESH_REQUIRED",
                "approval_request_status": "BLOCKED_STALE_HORIZON",
                "source_plan_hash": "e" * 64,
            },
        )

        self.assertEqual(
            result["decision"],
            "REFRESH_PIT_SCHEDULE_EXTENSION_HORIZON",
        )
        self.assertTrue(result["action_due"])
        self.assertFalse(result["run_approval_notification_required"])
        self.assertFalse(
            result["critical_checkpoint_notification_required"]
        )
        self.assertEqual(
            result["next_action"],
            "derive_fresh_hash_bound_pit_schedule_extension_" + "e" * 64,
        )

    def test_due_preapproved_short_segment_starts_without_new_approval(
        self,
    ) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
                "preapproved_short_segment_max_runtime_sec": 1_800,
            },
            "current_pit_schedule": {
                "all_listed_segments_are_preapproved": True,
                "per_segment_launch_approval_required": False,
                "automatic_launch_allowed": True,
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-07-31T00:00:00Z",
            schedule_window={
                "status": "DUE",
                "run_id": "pit_due",
                "duration_sec": 1_200,
                "classification": "PREAPPROVED_SHORT_SEGMENT",
            },
            campaign_window={
                "status": "OPEN",
                "window_id": "WEEKNIGHT_2026-07-30_2026-07-31",
            },
        )

        self.assertEqual(
            result["decision"],
            "START_PREAPPROVED_SHORT_SEGMENT_VISIBLE",
        )
        self.assertEqual(
            result["next_action"],
            "start_preapproved_short_segment_pit_due",
        )
        self.assertFalse(result["stop_new_actions"])
        self.assertTrue(result["action_due"])

    def test_closed_window_avoids_blocked_and_busywork(self) -> None:
        policy = {
            **POLICY,
            "run_policy": {
                "long_run_requires_explicit_per_campaign_approval": True,
            },
            "continuous_production_policy": {
                "path": "not-used-by-direct-evaluation",
            },
        }
        result = evaluate_autopilot_state(
            policy=policy,
            policy_hash="abc",
            gate={"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("CONTINUE"),
            prior_state=None,
            observed_at_utc="2026-07-30T08:00:00Z",
            schedule_window={"status": "WAITING", "run_id": "pit_next"},
            campaign_window={
                "status": "CLOSED",
                "approval_request_status": "NOT_DUE",
            },
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(
            result["decision"],
            "ACTIVE_NO_POSITIVE_RUN_CANDIDATE",
        )
        self.assertFalse(result["action_due"])
        self.assertFalse(result["stop_new_actions"])

    def test_ready_gate_runs_research_when_productive_queue_is_exhausted(self) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
            },
            schedule_window={
                "status": "WAITING",
                "run_id": "next",
                "eta_sec": 61_200,
            },
            productive_fallback={
                "status": "EXHAUSTED",
                "task": None,
            },
            research_fallback={
                "status": "READY",
                "task": {
                    "id": "research-audit",
                    "max_runtime_sec": 1_800,
                },
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["decision"], "CONTINUE_BOUNDED_RESEARCH")
        self.assertTrue(result["action_due"])
        self.assertEqual(result["next_action"], "research-audit")

    def test_ready_gate_stops_at_research_user_review_checkpoint(self) -> None:
        checkpoint = {
            "status": "USER_REVIEW_REQUIRED",
            "requested_action": "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE",
        }
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
            },
            schedule_window={
                "status": "WAITING",
                "run_id": "next",
                "eta_sec": 61_200,
            },
            productive_fallback={
                "status": "EXHAUSTED",
                "task": None,
            },
            research_fallback={
                "status": "USER_REVIEW_REQUIRED",
                "task": None,
                "critical_checkpoint": checkpoint,
            },
        )

        self.assertEqual(result["status"], "CRITICAL_STOP")
        self.assertEqual(result["decision"], "USER_REVIEW_REQUIRED")
        self.assertTrue(result["stop_new_actions"])
        self.assertFalse(result["action_due"])
        self.assertEqual(
            result["next_action"],
            "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE",
        )

    def test_ready_gate_continues_claimed_research_task(self) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "ready",
            },
            schedule_window={
                "status": "WAITING",
                "run_id": "next",
                "eta_sec": 61_200,
            },
            productive_fallback={
                "status": "EXHAUSTED",
                "task": None,
            },
            research_fallback={
                "status": "IN_PROGRESS",
                "task": {
                    "id": "research-audit",
                    "max_runtime_sec": 1_800,
                },
            },
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["decision"], "CONTINUE_BOUNDED_RESEARCH")
        self.assertTrue(result["action_due"])
        self.assertEqual(result["next_action"], "research-audit")

    def test_ready_gate_continues_when_schedule_window_is_due(self) -> None:
        result = self._evaluate(
            {"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            schedule_window={
                "status": "DUE",
                "run_id": "next",
                "eta_sec": 0,
            },
        )

        self.assertEqual(result["decision"], "CONTINUE_NEXT_ALLOWED_ACTION")
        self.assertTrue(result["action_due"])

    def test_ready_gate_fails_closed_when_schedule_pointer_is_invalid(self) -> None:
        result = self._evaluate(
            {"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            schedule_window={
                "status": "INVALID",
                "error": "pointer/plan hash mismatch",
            },
        )

        self.assertEqual(result["status"], "CRITICAL_STOP")
        self.assertEqual(result["decision"], "CRITICAL_STOP_INVALID_SCHEDULE")
        self.assertTrue(result["stop_new_actions"])
        self.assertFalse(result["action_due"])

    def test_weekly_limit_pauses_new_actions_but_does_not_kill_writer(self) -> None:
        result = self._evaluate(
            {"status": "RUNNING", "run_id": "writer"},
            usage=_usage("PAUSE_WEEKLY_LIMIT", remaining=15),
        )
        self.assertEqual(result["status"], "PAUSED_WEEKLY_LIMIT")
        self.assertTrue(result["stop_new_actions"])
        self.assertTrue(result["allow_running_writer_to_finish"])
        self.assertTrue(result["pause_notification_required"])

        repeated = self._evaluate(
            {"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            usage=_usage("PAUSE_WEEKLY_LIMIT", remaining=15),
            prior={"status": "PAUSED_WEEKLY_LIMIT"},
        )
        self.assertFalse(repeated["pause_notification_required"])

    def test_limit_reset_resumes_goal(self) -> None:
        result = self._evaluate(
            {"status": "READY_FOR_POSTPROCESS", "run_id": "ready"},
            prior={"status": "PAUSED_WEEKLY_LIMIT"},
        )
        self.assertEqual(result["status"], "ACTIVE")
        self.assertTrue(result["resumed_after_limit"])

    def test_running_gate_is_monitor_only(self) -> None:
        result = self._evaluate({"status": "RUNNING", "run_id": "writer"})
        self.assertEqual(result["status"], "RUNNING_MONITOR_ONLY")
        self.assertEqual(result["next_action"], "status_eta_only")

    def test_incomplete_run_requires_safe_recovery_preflight(self) -> None:
        result = self._evaluate(
            {
                "status": "STOPPED_INCOMPLETE",
                "run_id": "broken",
                "resume_command": "resume exact immutable run",
            }
        )
        self.assertEqual(result["status"], "RECOVERY_PREFLIGHT")
        self.assertEqual(result["decision"], "SAFE_RECOVERY_PREFLIGHT_REQUIRED")

    def test_incomplete_run_without_resume_path_is_critical(self) -> None:
        result = self._evaluate(
            {
                "status": "STOPPED_INCOMPLETE",
                "run_id": "broken",
            }
        )
        self.assertEqual(result["decision"], "CRITICAL_STOP_INCOMPLETE")

    def test_resolves_next_uncertified_schedule_window_and_eta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger = root / "quality.jsonl"
            ledger.write_text(
                json.dumps(
                    {
                        "hypothesis_id": "pit",
                        "data_type": "PIT_FORWARD",
                        "hypothesis_contract_sha256": "c" * 64,
                        "scheduled_date": "2026-07-28",
                        "technical_quality_accepted": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            plan = root / "schedule.json"
            plan.write_text(
                json.dumps(
                    {
                        "plan_hash": "sealed",
                        "collection_stage": "train_accrual",
                        "hypothesis": {
                            "id": "pit",
                            "required_data_type": "PIT_FORWARD",
                        },
                        "sealed_schedule": {
                            "hypothesis_contract_sha256": "c" * 64,
                            "quality_policy": {
                                "train_feasibility_distinct_days": 20,
                            },
                            "collection_stage": {
                                "name": "train_accrual",
                                "quality_ledger": {"path": str(ledger)},
                                "stage_target_distinct_dates": 20,
                            },
                        },
                        "segments": [
                            {
                                "run_id": "accepted",
                                "start_local": "2026-07-28T01:00:00+03:00",
                                "end_local": "2026-07-28T01:20:00+03:00",
                                "hard_deadline_local": "2026-07-28T07:00:00+03:00",
                            },
                            {
                                "run_id": "next",
                                "start_local": "2026-07-29T01:00:00+03:00",
                                "end_local": "2026-07-29T01:20:00+03:00",
                                "hard_deadline_local": "2026-07-29T07:00:00+03:00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pointer = root / "pointer.json"
            pointer.write_text(
                json.dumps(
                    {
                        "status": "ACTIVE",
                        "plan_path": str(plan),
                        "plan_hash": "sealed",
                        "quality_ledger_path": str(ledger),
                        "hypothesis_id": "pit",
                        "data_type": "PIT_FORWARD",
                        "collection_stage": "train_accrual",
                    }
                ),
                encoding="utf-8",
            )
            policy = {
                "current_pit_schedule": {
                    "pointer_path": str(pointer),
                }
            }

            result = resolve_schedule_window(
                policy,
                observed_at_utc="2026-07-28T20:00:00Z",
            )

        self.assertEqual(result["status"], "WAITING")
        self.assertEqual(result["run_id"], "next")
        self.assertEqual(result["eta_sec"], 7_200)
        self.assertEqual(result["accepted_distinct_dates"], 1)
        self.assertEqual(result["duration_sec"], 1_200)
        self.assertEqual(result["classification"], "PREAPPROVED_SHORT_SEGMENT")

    def test_schedule_target_reached_suppresses_extra_approved_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger = root / "quality.jsonl"
            entries = [
                {
                    "hypothesis_id": "pit",
                    "data_type": "PIT_FORWARD",
                    "hypothesis_contract_sha256": "c" * 64,
                    "scheduled_date": f"2026-07-{day:02d}",
                    "technical_quality_accepted": True,
                }
                for day in range(1, 21)
            ]
            ledger.write_text(
                "".join(json.dumps(entry) + "\n" for entry in entries),
                encoding="utf-8",
            )
            plan = root / "schedule.json"
            plan.write_text(
                json.dumps(
                    {
                        "plan_hash": "sealed",
                        "collection_stage": "train_accrual",
                        "hypothesis": {
                            "id": "pit",
                            "required_data_type": "PIT_FORWARD",
                        },
                        "sealed_schedule": {
                            "hypothesis_contract_sha256": "c" * 64,
                            "quality_policy": {
                                "train_feasibility_distinct_days": 20,
                            },
                            "collection_stage": {
                                "name": "train_accrual",
                                "quality_ledger": {"path": str(ledger)},
                                "stage_target_distinct_dates": 20,
                            },
                        },
                        "segments": [
                            {
                                "run_id": "unneeded-extra",
                                "start_local": "2026-07-21T01:00:00+03:00",
                                "end_local": "2026-07-21T01:20:00+03:00",
                                "hard_deadline_local": (
                                    "2026-07-21T07:00:00+03:00"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pointer = root / "pointer.json"
            pointer.write_text(
                json.dumps(
                    {
                        "status": "ACTIVE",
                        "plan_path": str(plan),
                        "plan_hash": "sealed",
                        "quality_ledger_path": str(ledger),
                        "hypothesis_id": "pit",
                        "data_type": "PIT_FORWARD",
                        "collection_stage": "train_accrual",
                    }
                ),
                encoding="utf-8",
            )
            result = resolve_schedule_window(
                {"current_pit_schedule": {"pointer_path": str(pointer)}},
                observed_at_utc="2026-07-20T20:00:00Z",
            )

        self.assertEqual(result["status"], "STAGE_TARGET_REACHED")
        self.assertEqual(result["accepted_distinct_dates"], 20)
        self.assertEqual(result["stage_target_distinct_dates"], 20)
        self.assertNotIn("run_id", result)

    def test_train_target_routes_to_feasibility_not_extension_or_collector(
        self,
    ) -> None:
        result = self._evaluate(
            {
                "status": "READY_FOR_POSTPROCESS",
                "run_id": "last-train-segment",
            },
            schedule_window={
                "status": "STAGE_TARGET_REACHED",
                "collection_stage": "train_accrual",
                "accepted_distinct_dates": 20,
                "stage_target_distinct_dates": 20,
            },
            productive_fallback={"status": "EXHAUSTED", "task": None},
            research_fallback={
                "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                "task": None,
            },
            pit_schedule_extension={
                "status": "READY_FOR_APPROVAL",
                "approval_request_status": "DUE",
                "plan_hash": "e" * 64,
            },
        )

        self.assertEqual(result["decision"], "RUN_PIT_TRAIN_FEASIBILITY")
        self.assertEqual(
            result["next_action"],
            "run_visible_deterministic_train_only_feasibility",
        )
        self.assertTrue(result["action_due"])
        self.assertFalse(result["stop_new_actions"])

    def test_train_verdict_preempts_collectors_and_notifies_once(self) -> None:
        gate = {
            "status": "READY_FOR_POSTPROCESS",
            "run_id": "pit_train_feasibility_ledger",
            "next_goal_decision": "PIT_OOS_ACCRUAL_PLAN_READY_FOR_APPROVAL",
            "manifest_path": "manifest.json",
            "verdict": "FEASIBLE_FOR_OOS",
            "feasibility_result_hash": "f" * 64,
            "oos_schedule_path": "oos-plan.json",
            "oos_schedule_plan_hash": "a" * 64,
        }
        schedule = {
            "status": "STAGE_TARGET_REACHED",
            "collection_stage": "train_accrual",
            "accepted_distinct_dates": 20,
            "stage_target_distinct_dates": 20,
        }
        result = self._evaluate(gate, schedule_window=schedule)
        repeated = self._evaluate(
            gate,
            schedule_window=schedule,
            prior=result,
        )

        self.assertEqual(
            result["decision"],
            "PIT_OOS_ACCRUAL_PLAN_READY_FOR_APPROVAL",
        )
        self.assertEqual(
            result["next_action"],
            "request_exact_pit_oos_schedule_approval",
        )
        self.assertTrue(result["critical_checkpoint_notification_required"])
        self.assertFalse(
            repeated["critical_checkpoint_notification_required"]
        )
        self.assertEqual(result["gate"]["manifest_path"], "manifest.json")
        self.assertEqual(result["gate"]["oos_schedule_path"], "oos-plan.json")

    def test_productive_fallback_skips_completed_and_exhausted_attempts(self) -> None:
        ledger = [
            {"task_id": "baseline", "status": "COMPLETED"},
            {"task_id": "regression", "status": "STARTED"},
            {"task_id": "regression", "status": "FAILED"},
        ]

        result = resolve_productive_fallback(POLICY, ledger_entries=ledger)

        self.assertEqual(result["status"], "EXHAUSTED")

    def test_resolves_hash_bound_research_user_review_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "audit.json"
            deterministic = {
                "schema": "audit-v1",
                "critical_checkpoint": {
                    "status": "USER_REVIEW_REQUIRED",
                    "requested_action": "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE",
                },
            }
            canonical = json.dumps(
                deterministic,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            payload = {
                **deterministic,
                "deterministic_result_hash": hashlib.sha256(
                    canonical
                ).hexdigest(),
                "generated_at_utc": "2026-07-29T05:00:00Z",
            }
            artifact.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            backlog = root / "backlog.json"
            backlog.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "audit-v1",
                                "status": "COMPLETED",
                                "artifact_path": str(artifact),
                                "artifact_sha256": artifact_hash,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = resolve_research_critical_checkpoint(
                backlog,
                {"status": "EXHAUSTED", "task": None},
            )

        self.assertEqual(result["status"], "USER_REVIEW_REQUIRED")
        self.assertEqual(
            result["critical_checkpoint"]["requested_action"],
            "AUTHORIZE_BOUNDED_PUBLIC_READONLY_PROBE",
        )
        self.assertIsNone(result["task"])

    def test_resolves_hash_bound_no_material_gap_wait_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "audit.json"
            deterministic = {
                "schema": "audit-v9",
                "critical_checkpoint": None,
                "offline_gap_assessment": {
                    "materially_useful_same_contract_tasks_remaining": False,
                },
                "next_bounded_catalog_requirement": [],
                "next_allowed_action": (
                    "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
                ),
            }
            canonical = json.dumps(
                deterministic,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            payload = {
                **deterministic,
                "deterministic_result_hash": hashlib.sha256(
                    canonical
                ).hexdigest(),
                "generated_at_utc": "2026-07-30T16:00:00Z",
            }
            artifact.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            artifact_hash = hashlib.sha256(
                artifact.read_bytes()
            ).hexdigest()
            backlog = root / "backlog.json"
            backlog.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "audit-v9",
                                "status": "COMPLETED",
                                "artifact_path": str(artifact),
                                "artifact_sha256": artifact_hash,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = resolve_research_critical_checkpoint(
                backlog,
                {"status": "EXHAUSTED", "task": None},
            )

        self.assertEqual(
            result["status"],
            "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
        )
        self.assertIsNone(result["task"])

    def test_productive_fallback_selects_first_unfinished_task(self) -> None:
        result = resolve_productive_fallback(
            POLICY,
            ledger_entries=[{"task_id": "baseline", "status": "COMPLETED"}],
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["task"]["id"], "regression")


if __name__ == "__main__":
    unittest.main()
