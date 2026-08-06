from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from night_schedule_plan import validate_night_schedule_plan
from night_schedule_quality import (
    _build_certification,
    _json_hash,
    _load_ledger,
    _read_json,
    _sha256,
    _validate_quality_policy,
    _write_json_atomic,
)
from night_schedule_status import evaluate_night_schedule_status


REPORT_SCHEMA = "fast_first_night_schedule_quality_dry_run_v1"


def _validate_ledger_contract(
    entries: list[dict[str, Any]], plan: dict[str, Any]
) -> None:
    if not entries:
        return
    expected_track = (
        f"{(plan.get('hypothesis') or {}).get('id')}|"
        f"{(plan.get('hypothesis') or {}).get('required_data_type')}"
    )
    expected_contract_hash = str(
        ((plan.get("sealed_schedule") or {}).get("hypothesis_contract_sha256") or "")
    )
    if not expected_contract_hash:
        raise ValueError("schedule plan has no sealed hypothesis contract hash")
    foreign = [
        entry
        for entry in entries
        if entry.get("track_key") != expected_track
        or str(entry.get("hypothesis_contract_sha256") or "")
        != expected_contract_hash
    ]
    if foreign:
        raise ValueError(
            "quality ledger contains entries from another hypothesis/data/contract track"
        )


def _run_key(entry: dict[str, Any]) -> tuple[str, str]:
    return str(entry.get("data_type") or ""), str(entry.get("segment_run_id") or "")


def _project_entries(
    existing: list[dict[str, Any]], proposed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    projected = {_run_key(entry): entry for entry in existing}
    for entry in proposed:
        key = _run_key(entry)
        prior = projected.get(key)
        if prior is not None and prior.get("certification_id") != entry.get("certification_id"):
            raise ValueError(f"quality certification conflict for run_id={key[1]}")
        projected[key] = entry
    return list(projected.values())


def _accepted_dates(entries: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(entry["scheduled_date"])
            for entry in entries
            if bool(entry.get("technical_quality_accepted"))
        }
    )


def _write_report(output_path: str | Path | None, report: dict[str, Any]) -> None:
    if output_path is not None:
        _write_json_atomic(Path(output_path).expanduser().resolve(), report)


def certify_night_schedule_quality_dry_run(
    plan_path: str | Path,
    expected_plan_hash: str,
    *,
    approval_record_root: str | Path,
    ledger_path: str | Path,
    now: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate completed PIT segments without mutating the sealed quality ledger."""
    target = Path(plan_path).expanduser().resolve()
    validation = validate_night_schedule_plan(target, expected_plan_hash)
    plan = _read_json(target)
    policy = _validate_quality_policy(plan)
    ledger_target = Path(ledger_path).expanduser().resolve()
    sealed_ledger = Path(str(validation["quality_ledger_path"])).expanduser().resolve()
    if ledger_target != sealed_ledger:
        raise ValueError(
            "quality ledger path differs from the sealed collection stage: "
            f"expected={sealed_ledger}, observed={ledger_target}"
        )

    status = evaluate_night_schedule_status(
        target,
        expected_plan_hash,
        approval_record_root=approval_record_root,
        now=now,
    )
    existing = _load_ledger(ledger_target)
    runtime_tools = (plan.get("sealed_schedule") or {}).get("runtime_tools") or {}
    provenance = {
        "dry_run_tool": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "sealed_quality_certifier": runtime_tools.get("quality_certifier"),
    }
    base_report = {
        "schema": REPORT_SCHEMA,
        "mode": "embargo_safe_technical_quality_dry_run",
        "plan_path": str(target),
        "plan_hash": expected_plan_hash,
        "plan_file_sha256": str(validation["plan_file_sha256"]),
        "quality_policy": policy,
        "quality_policy_sha256": _json_hash(policy),
        "collection_stage": validation["collection_stage"],
        "schedule_status_decision": status["decision"],
        "approval": status["approval"],
        "source_provenance": provenance,
        "returns_read": False,
        "pnl_read": False,
        "ledger": {
            "path": str(ledger_target),
            "sha256": _sha256(ledger_target) if ledger_target.exists() else None,
            "write_requested": False,
            "entries_appended": 0,
            "total_entries": len(existing),
            "accepted_distinct_dates": len(_accepted_dates(existing)),
            "accepted_distinct_date_values": _accepted_dates(existing),
            "required_distinct_days": int(policy["required_distinct_days"]),
            "train_feasibility_required_days": int(policy["train_feasibility_distinct_days"]),
        },
        "oos_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
    }
    if not bool((status.get("approval") or {}).get("valid")):
        report = {
            **base_report,
            "decision": "NIGHT_SCHEDULE_APPROVAL_INVALID",
            "segments_evaluated": 0,
            "segments_accepted": 0,
            "segments_rejected": 0,
            "segment_certifications": [],
            "technical_market_rows_read": False,
            "train_feasibility_gate_satisfied": False,
            "minimum_data_gate_satisfied": False,
            "projected_train_feasibility_gate_satisfied": False,
            "projected_minimum_data_gate_satisfied": False,
            "next_allowed_action": "restore_or_obtain_valid_approval_before_quality_commit",
        }
        _write_report(output_path, report)
        return report

    _validate_ledger_contract(existing, plan)

    plan_segments = {str(item["run_id"]): item for item in (plan.get("segments") or [])}
    completed = [item for item in (status.get("segments") or []) if item.get("status") == "COMPLETED"]
    proposed: list[dict[str, Any]] = []
    for status_segment in completed:
        run_id = str(status_segment["run_id"])
        segment = plan_segments[run_id]
        manifest_path = Path(str(status_segment["manifest_path"])).expanduser().resolve()
        proposed.append(
            _build_certification(
                plan=plan,
                plan_path=target,
                plan_hash=expected_plan_hash,
                plan_file_sha256=str(validation["plan_file_sha256"]),
                segment=segment,
                manifest_path=manifest_path,
                quality_policy=policy,
            )
        )

    projected = _project_entries(existing, proposed)
    actual_accepted_dates = _accepted_dates(existing)
    projected_accepted_dates = _accepted_dates(projected)
    rejected_entries = [entry for entry in proposed if not bool(entry["technical_quality_accepted"])]
    train_days = int(policy["train_feasibility_distinct_days"])
    required_days = int(policy["required_distinct_days"])
    if rejected_entries:
        decision = "PIT_SEGMENT_QUALITY_REJECTED"
        next_action = "recollect_rejected_dates_under_new_explicit_schedule"
    elif not proposed:
        decision = "NO_COMPLETED_SEGMENTS_READY_FOR_QUALITY"
        next_action = "wait_for_completed_segment"
    else:
        decision = "PIT_SEGMENT_QUALITY_DRY_RUN_ACCEPTED"
        next_action = "review_dry_run_then_run_sealed_quality_commit_once"

    report = {
        **base_report,
        "decision": decision,
        "segment_certifications": proposed,
        "segments_evaluated": len(proposed),
        "segments_accepted": sum(bool(entry["technical_quality_accepted"]) for entry in proposed),
        "segments_rejected": sum(not bool(entry["technical_quality_accepted"]) for entry in proposed),
        "technical_market_rows_read": bool(proposed),
        "ledger": {
            **base_report["ledger"],
            "projected_total_entries": len(projected),
            "projected_accepted_distinct_dates": len(projected_accepted_dates),
            "projected_accepted_distinct_date_values": projected_accepted_dates,
        },
        "train_feasibility_gate_satisfied": len(actual_accepted_dates) >= train_days,
        "minimum_data_gate_satisfied": len(actual_accepted_dates) >= required_days,
        "projected_train_feasibility_gate_satisfied": len(projected_accepted_dates) >= train_days,
        "projected_minimum_data_gate_satisfied": len(projected_accepted_dates) >= required_days,
        "commit_required": bool(proposed) and not bool(rejected_entries),
        "next_allowed_action": next_action,
    }
    _write_report(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Certify completed PIT night segments without mutating the quality ledger"
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--approval-record-root", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--now")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = certify_night_schedule_quality_dry_run(
        args.plan,
        args.expected_plan_hash,
        approval_record_root=args.approval_record_root,
        ledger_path=args.ledger,
        now=args.now,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
