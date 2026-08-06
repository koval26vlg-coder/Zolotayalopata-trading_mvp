from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


RUNBOOK_SCHEMA = "trading_mvp_paper_forward_failure_runbook_v1"
FAULT_EVIDENCE_SCHEMA = "trading_mvp_paper_runtime_fault_injection_evidence_v1"
REQUIRED_INCIDENTS = {
    "stale_data",
    "schema_drift",
    "disk_pressure",
    "reconciliation_mismatch",
    "writer_lock_contention",
    "weekly_quota_stop",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runbook_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "runbook_hash_sha256"}
        }
    )


def _incident_definitions() -> dict[str, dict[str, Any]]:
    return {
        "stale_data": {
            "severity": "HIGH",
            "detectors": [
                "consecutive_stale_samples >= 3",
                "no_successful_write_for_two_expected_intervals",
                "quote_age_ms > frozen_maximum_quote_age_ms",
            ],
            "state": "PERSISTENT_STALE_DATA",
            "immediate_actions": [
                "block_paper_oms_transition",
                "append_incident_audit_row",
                "finalize_segment_STOPPED_INCOMPLETE",
                "preserve_run_id_and_partial_artifacts",
            ],
            "forbidden_actions": [
                "accept_stale_snapshot",
                "auto_promote_to_live",
                "consume_partial_segment_as_complete",
            ],
            "recovery_preconditions": [
                "public_reader_contract_hash_matches",
                "venue_quotes_are_fresh_and_non_crossed",
                "writer_pid_is_not_alive",
                "resume_uses_same_run_id",
            ],
            "resume_policy": "VISIBLE_BOUNDED_RESUME_AFTER_PRECONDITIONS",
            "notification": "NOTIFY_WITH_LAST_WRITE_AGE_AND_VENUE",
        },
        "schema_drift": {
            "severity": "CRITICAL",
            "detectors": [
                "response_schema_hash_mismatch",
                "required_field_missing",
                "fixture_or_contract_hash_drift",
            ],
            "state": "STOPPED_INCOMPLETE",
            "immediate_actions": [
                "reject_payload_before_oms",
                "append_payload_hash_and_endpoint_id_to_audit",
                "finalize_segment_STOPPED_INCOMPLETE",
                "freeze_automatic_resume",
            ],
            "forbidden_actions": [
                "relax_schema_automatically",
                "retune_strategy",
                "read_partial_result_as_evidence",
            ],
            "recovery_preconditions": [
                "classify_exchange_change_or_local_bug",
                "create_new_hash_bound_contract_if_schema_materially_changed",
                "pass_fixture_and_fast_regression",
            ],
            "resume_policy": "REQUIRES_CRITICAL_CONTRACT_DECISION",
            "notification": "NOTIFY_IMMEDIATELY_WITH_SCHEMA_DIFF",
        },
        "disk_pressure": {
            "severity": "CRITICAL",
            "detectors": [
                "free_disk_gib < 5 before start",
                "write_failure_errno_28",
                "atomic_replace_or_fsync_failure",
            ],
            "state": "STOPPED_INCOMPLETE",
            "immediate_actions": [
                "stop_new_writes",
                "preserve_existing_files_without_truncation",
                "finalize_manifest_if_atomic_write_is_possible",
                "mark_output_unusable_until_integrity_check",
            ],
            "forbidden_actions": [
                "delete_user_files_automatically",
                "overwrite_completed_segment",
                "continue_with_partial_write",
            ],
            "recovery_preconditions": [
                "free_disk_gib >= 5",
                "partial_jsonl_tail_integrity_verified",
                "writer_pid_is_not_alive",
                "resume_uses_same_run_id",
            ],
            "resume_policy": "VISIBLE_BOUNDED_RESUME_AFTER_STORAGE_RECOVERY",
            "notification": "NOTIFY_IMMEDIATELY_WITH_DRIVE_AND_FREE_SPACE",
        },
        "reconciliation_mismatch": {
            "severity": "CRITICAL",
            "detectors": [
                "paper_state_not_equal_replayed_ledger",
                "dual_leg_notional_or_direction_mismatch",
                "unexpected_open_order_or_balance_delta",
            ],
            "state": "HALT_PAPER_OMS",
            "immediate_actions": [
                "activate_kill_switch",
                "block_all_paper_state_mutations",
                "append_read_only_reconciliation_report",
                "preserve_ledger_and_state",
            ],
            "forbidden_actions": [
                "repair_ledger_silently",
                "submit_order",
                "clear_kill_switch_automatically",
            ],
            "recovery_preconditions": [
                "root_cause_classified",
                "deterministic_replay_matches_state",
                "new_reconciliation_report_matched_true",
                "explicit_critical_checkpoint_review",
            ],
            "resume_policy": "REQUIRES_CRITICAL_RECONCILIATION_DECISION",
            "notification": "NOTIFY_IMMEDIATELY_WITH_MISMATCH_CLASSES",
        },
        "writer_lock_contention": {
            "severity": "HIGH",
            "detectors": [
                "writer_lock_already_exists",
                "second_market_data_writer_requested",
                "lock_owner_cannot_be_verified",
            ],
            "state": "FAIL_CLOSED_NO_SECOND_WRITER",
            "immediate_actions": [
                "reject_second_writer",
                "inspect_recorded_owner_pid_read_only",
                "leave_current_writer_untouched",
                "record_lock_contention",
            ],
            "forbidden_actions": [
                "break_live_lock_automatically",
                "launch_duplicate_collector",
                "write_same_output_namespace",
            ],
            "recovery_preconditions": [
                "recorded_owner_pid_is_dead",
                "output_last_write_is_stale",
                "lock_ownership_record_is_hash_valid",
            ],
            "resume_policy": "REMOVE_STALE_LOCK_ONLY_IN_BOUNDED_CLEANUP",
            "notification": "NOTIFY_IF_OWNER_DEAD_OR_LOCK_UNVERIFIABLE",
        },
        "weekly_quota_stop": {
            "severity": "HIGH",
            "detectors": [
                "weekly_remaining_percent <= 15 before new task",
                "weekly_remaining_percent <= 15 at safe task checkpoint",
            ],
            "state": "PAUSED_QUOTA_GUARD",
            "immediate_actions": [
                "do_not_claim_new_backlog_task",
                "finish_current_atomic_file_operation_only",
                "persist_current_task_and_gate_state",
                "schedule_automatic_guard_recheck_after_quota_reset",
                "notify_user_with_remaining_percent_and_reset_time",
            ],
            "forbidden_actions": [
                "start_new_collector_or_evaluator",
                "consume_reserved_weekly_limit",
                "kill_healthy_visible_collector_only_to_save_agent_tokens",
            ],
            "recovery_preconditions": [
                "weekly_quota_has_reset_or_remaining_percent > 15",
                "active_run_gate_rechecked",
                "prior_task_state_is_not_ambiguous",
            ],
            "resume_policy": "AUTOMATIC_RESUME_FROM_PERSISTED_BACKLOG_AFTER_RESET",
            "notification": "NOTIFY_AT_THRESHOLD_AND_ON_AUTOMATIC_RESUME",
        },
    }


def _validate_fault_evidence(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if payload.get("schema") != FAULT_EVIDENCE_SCHEMA:
        raise ValueError("unexpected fault-injection evidence schema")
    if payload.get("verdict") != "FAIL_CLOSED_RECOVERY_VERIFIED":
        raise ValueError("fault-injection evidence did not pass")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, Mapping):
        raise ValueError("fault-injection scenarios are missing")
    required = {
        "bounded_interruption_resume",
        "duplicate_sample_sequence",
        "existing_writer_lock",
        "truncated_jsonl",
        "disk_write_failure",
        "fixture_hash_drift",
        "expected_plan_hash_drift",
    }
    if not required.issubset(scenarios):
        raise ValueError("fault-injection evidence is incomplete")
    return payload


def build_failure_runbook(
    *,
    observer_runtime_path: str | Path,
    observer_monitor_path: str | Path,
    reconciliation_adapter_path: str | Path,
    fault_evidence_path: str | Path,
    output_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    source_paths = [
        Path(observer_runtime_path).expanduser().resolve(),
        Path(observer_monitor_path).expanduser().resolve(),
        Path(reconciliation_adapter_path).expanduser().resolve(),
    ]
    for source in source_paths:
        if not source.is_file():
            raise FileNotFoundError(source)
    evidence_path = Path(fault_evidence_path).expanduser().resolve()
    evidence = _validate_fault_evidence(evidence_path)
    payload: dict[str, Any] = {
        "schema": RUNBOOK_SCHEMA,
        "task_id": "paper_forward_failure_runbook_v1",
        "status": "FROZEN_MACHINE_READABLE_FAIL_CLOSED",
        "incidents": _incident_definitions(),
        "global_invariants": {
            "live_orders": False,
            "private_api_keys": False,
            "automatic_live_promotion": False,
            "consume_partial_output": False,
            "silent_schema_relaxation": False,
            "automatic_user_file_deletion": False,
            "visible_writer_required": True,
            "single_writer_required": True,
        },
        "critical_user_checkpoints": [
            "schema_or_hypothesis_contract_change",
            "reconciliation_mismatch",
            "historical_edge_accept_or_reject",
            "live_review_eligibility",
        ],
        "automatic_noncritical_actions": [
            "technical_status_check",
            "bounded_offline_backlog_progress",
            "fast_regression",
            "cache_integrity_check",
            "quota_recheck_after_reset",
        ],
        "fault_evidence": {
            "path": str(evidence_path),
            "file_sha256": sha256_file(evidence_path),
            "verdict": evidence["verdict"],
            "scenario_count": len(evidence["scenarios"]),
        },
        "source_provenance": [
            {"path": str(path), "sha256": sha256_file(path)}
            for path in source_paths
        ],
        "process_launches": 0,
        "network_requests": 0,
        "verdict": "FAILURE_RUNBOOK_FROZEN_FAIL_CLOSED",
        "next_allowed_action": "paper_product_readiness_audit_v3",
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }
    payload["runbook_hash_sha256"] = runbook_hash(payload)
    validate_failure_runbook(payload)
    if output_path is not None:
        _write_json_immutable(output_path, payload)
    return payload


def validate_failure_runbook(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != RUNBOOK_SCHEMA:
        raise ValueError(f"expected {RUNBOOK_SCHEMA}")
    if payload.get("runbook_hash_sha256") != runbook_hash(payload):
        raise ValueError("failure runbook hash mismatch")
    if payload.get("status") != "FROZEN_MACHINE_READABLE_FAIL_CLOSED":
        raise ValueError("failure runbook status changed")
    if payload.get("incidents") != _incident_definitions():
        raise ValueError("frozen incident definitions changed")
    if set(payload["incidents"]) != REQUIRED_INCIDENTS:
        raise ValueError("failure runbook incident coverage changed")
    invariants = payload.get("global_invariants")
    if not isinstance(invariants, Mapping):
        raise ValueError("failure runbook invariants are missing")
    for key in (
        "live_orders",
        "private_api_keys",
        "automatic_live_promotion",
        "consume_partial_output",
        "silent_schema_relaxation",
        "automatic_user_file_deletion",
    ):
        if invariants.get(key) is not False:
            raise ValueError(f"failure runbook invariant loosened: {key}")
    for key in ("visible_writer_required", "single_writer_required"):
        if invariants.get(key) is not True:
            raise ValueError(f"failure runbook invariant loosened: {key}")
    if payload.get("process_launches") != 0:
        raise ValueError("failure runbook builder launched a process")
    if payload.get("network_requests") != 0:
        raise ValueError("failure runbook builder performed network requests")
    return dict(payload)


def incident_action(
    runbook: Mapping[str, Any], incident_id: str
) -> dict[str, Any]:
    validated = validate_failure_runbook(runbook)
    incident = validated["incidents"].get(incident_id)
    if incident is None:
        raise ValueError(f"unknown incident: {incident_id}")
    deterministic = {
        "schema": "trading_mvp_paper_incident_action_v1",
        "incident_id": incident_id,
        "runbook_hash_sha256": validated["runbook_hash_sha256"],
        "severity": incident["severity"],
        "state": incident["state"],
        "immediate_actions": incident["immediate_actions"],
        "resume_policy": incident["resume_policy"],
        "notification": incident["notification"],
        "process_launched": False,
    }
    return {
        **deterministic,
        "action_hash_sha256": sha256_json(deterministic),
    }


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the machine-readable paper-forward failure runbook"
    )
    parser.add_argument("--observer-runtime", required=True)
    parser.add_argument("--observer-monitor", required=True)
    parser.add_argument("--reconciliation-adapter", required=True)
    parser.add_argument("--fault-evidence", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    runbook = build_failure_runbook(
        observer_runtime_path=args.observer_runtime,
        observer_monitor_path=args.observer_monitor,
        reconciliation_adapter_path=args.reconciliation_adapter,
        fault_evidence_path=args.fault_evidence,
        output_path=args.output,
    )
    print(json.dumps(runbook, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
