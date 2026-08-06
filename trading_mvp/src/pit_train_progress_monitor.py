from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from night_schedule_plan import validate_night_schedule_plan


REPORT_SCHEMA = "trading_mvp_pit_train_progress_monitor_v1"
VOLGOGRAD_TZ = timezone(timedelta(hours=3), name="Europe/Volgograd")
TRAIN_TARGET_DATES = 20


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


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {target}")
    return payload


def _parse_local(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"schedule timestamp lacks timezone: {value}")
    return parsed.astimezone(VOLGOGRAD_TZ)


def _validate_approval_pointer(
    *,
    gate: Mapping[str, Any],
    schedule_path: Path,
    plan_hash: str,
    plan_file_sha256: str,
) -> dict[str, Any]:
    approval = gate.get("approved_night_schedule")
    if not isinstance(approval, Mapping):
        raise ValueError("active gate has no approved night schedule")
    if approval.get("status") != "ACTIVE":
        raise ValueError("approved night schedule is not ACTIVE")
    if Path(str(approval.get("plan_path") or "")).expanduser().resolve() != schedule_path:
        raise ValueError("approved night schedule path mismatch")
    if approval.get("plan_hash") != plan_hash:
        raise ValueError("approved night schedule hash mismatch")
    if approval.get("plan_file_sha256") != plan_file_sha256:
        raise ValueError("approved night schedule file hash mismatch")
    record_path = Path(
        str(approval.get("approval_record_path") or "")
    ).expanduser().resolve()
    if not record_path.is_file():
        raise ValueError("immutable night schedule approval record is missing")
    observed_record_hash = sha256_file(record_path)
    if observed_record_hash != approval.get("approval_record_sha256"):
        raise ValueError("immutable night schedule approval record hash mismatch")
    return {
        "status": "HASH_VALID_ACTIVE",
        "approval_record_path": str(record_path),
        "approval_record_sha256": observed_record_hash,
        "expires_at": approval.get("expires_at"),
    }


def _project_train_eta(
    *,
    accepted_dates: set[str],
    segments: list[Mapping[str, Any]],
    target_dates: int,
    now_local: datetime,
) -> dict[str, Any]:
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    now_local = now_local.astimezone(VOLGOGRAD_TZ)
    remaining = max(0, target_dates - len(accepted_dates))
    available_new_dates: list[str] = []
    expired_uncertified_dates: list[str] = []
    for segment in segments:
        scheduled_date = str(segment["start_local"])[:10]
        if scheduled_date in accepted_dates:
            continue
        deadline = _parse_local(str(segment["hard_deadline_local"]))
        if deadline < now_local:
            if scheduled_date not in expired_uncertified_dates:
                expired_uncertified_dates.append(scheduled_date)
            continue
        if (
            scheduled_date not in available_new_dates
        ):
            available_new_dates.append(scheduled_date)
    projected_at_schedule_end = min(
        target_dates, len(accepted_dates) + len(available_new_dates)
    )
    uncovered = max(0, target_dates - projected_at_schedule_end)
    if remaining == 0:
        earliest_checkpoint = max(accepted_dates) if accepted_dates else None
    elif len(available_new_dates) >= remaining:
        earliest_checkpoint = available_new_dates[remaining - 1]
    elif available_new_dates:
        last_date = date.fromisoformat(available_new_dates[-1])
        earliest_checkpoint = (
            last_date + timedelta(days=uncovered)
        ).isoformat()
    elif accepted_dates:
        earliest_checkpoint = (
            date.fromisoformat(max(accepted_dates))
            + timedelta(days=remaining)
        ).isoformat()
    else:
        earliest_checkpoint = None
    return {
        "target_accepted_dates": target_dates,
        "accepted_dates": len(accepted_dates),
        "remaining_dates": remaining,
        "scheduled_new_dates_available": len(available_new_dates),
        "expired_uncertified_schedule_dates_excluded": len(
            expired_uncertified_dates
        ),
        "expired_uncertified_dates": expired_uncertified_dates,
        "projected_accepted_dates_at_schedule_end": projected_at_schedule_end,
        "additional_dates_needed_after_schedule": uncovered,
        "earliest_possible_train_checkpoint_date_if_each_future_date_passes": earliest_checkpoint,
        "calendar_projection_only": True,
        "quality_acceptance_not_assumed": True,
    }


def summarize_progress(
    *,
    plan: Mapping[str, Any],
    validation: Mapping[str, Any],
    gate: Mapping[str, Any],
    now_local: datetime,
    approval_status: Mapping[str, Any],
) -> dict[str, Any]:
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    now_local = now_local.astimezone(VOLGOGRAD_TZ)
    segments = list(plan["sealed_schedule"]["segments"])
    accepted_certifications = list(
        validation.get("current_accepted_certifications") or []
    )
    accepted_dates = {
        str(item["scheduled_date"]) for item in accepted_certifications
    }
    segment_statuses: list[dict[str, Any]] = []
    due: list[Mapping[str, Any]] = []
    countdown: list[Mapping[str, Any]] = []
    upcoming: list[Mapping[str, Any]] = []
    for segment in segments:
        start = _parse_local(str(segment["start_local"]))
        deadline = _parse_local(str(segment["hard_deadline_local"]))
        scheduled_date = start.date().isoformat()
        if scheduled_date in accepted_dates:
            status = "CERTIFIED"
        elif start <= now_local <= deadline:
            status = "DUE"
            due.append(segment)
        elif start - timedelta(minutes=5) <= now_local < start:
            status = "COUNTDOWN_WINDOW"
            countdown.append(segment)
        elif now_local < start:
            status = "UPCOMING"
            upcoming.append(segment)
        else:
            status = "EXPIRED_UNCERTIFIED"
        segment_statuses.append(
            {
                "sequence": int(segment["sequence"]),
                "run_id": str(segment["run_id"]),
                "scheduled_date": scheduled_date,
                "start_local": str(segment["start_local"]),
                "hard_deadline_local": str(segment["hard_deadline_local"]),
                "status": status,
            }
        )
    if len(due) > 1 or len(countdown) > 1:
        raise ValueError("schedule has overlapping actionable segments")
    gate_status = str(
        gate.get("gate_status") or gate.get("status") or "UNKNOWN"
    )
    actionable = due[0] if due else countdown[0] if countdown else None
    next_segment = (
        actionable
        if actionable is not None
        else (upcoming[0] if upcoming else None)
    )
    if gate_status == "RUNNING":
        decision = "STATUS_ONLY_ACTIVE_RUN"
        next_allowed_action = "monitor_current_visible_run_only"
    elif gate_status == "STOPPED_INCOMPLETE":
        decision = "BLOCKED_STOPPED_INCOMPLETE"
        next_allowed_action = "visible_resolve_or_reject_incomplete_run"
    elif due:
        decision = "DUE_SEGMENT_VISIBLE_START"
        next_allowed_action = str(due[0]["run_id"])
    elif countdown:
        decision = "COUNTDOWN_WINDOW_VISIBLE_START"
        next_allowed_action = str(countdown[0]["run_id"])
    else:
        decision = "SCHEDULE_WAIT_OFFLINE_AUTOPILOT_ACTIVE"
        next_allowed_action = "continue_bounded_offline_research_backlog"
    seconds_to_next_start = None
    if next_segment is not None:
        seconds_to_next_start = max(
            0,
            int(
                (
                    _parse_local(str(next_segment["start_local"])) - now_local
                ).total_seconds()
            ),
        )
    deterministic = {
        "schema": REPORT_SCHEMA,
        "decision": decision,
        "now_local": now_local.isoformat(),
        "gate": {
            "status": gate_status,
            "run_id": gate.get("run_id"),
            "replay_allowed": bool(gate.get("replay_allowed", False)),
            "live_process_count": len(gate.get("process_ids") or []),
        },
        "approval": dict(approval_status),
        "schedule": {
            "plan_path": validation["plan_path"],
            "plan_hash": validation["plan_hash"],
            "plan_file_sha256": validation["plan_file_sha256"],
            "collection_stage": validation["collection_stage"],
            "segments": len(segments),
        },
        "quality": {
            "accepted_distinct_dates": len(accepted_dates),
            "accepted_dates": sorted(accepted_dates),
            "rejected_or_uncertified_dates_not_counted": True,
        },
        "train_eta": _project_train_eta(
            accepted_dates=accepted_dates,
            segments=segments,
            target_dates=TRAIN_TARGET_DATES,
            now_local=now_local,
        ),
        "segment_statuses": segment_statuses,
        "actionable_segment": (
            {
                "run_id": str(actionable["run_id"]),
                "start_local": str(actionable["start_local"]),
                "hard_deadline_local": str(
                    actionable["hard_deadline_local"]
                ),
            }
            if actionable is not None
            else None
        ),
        "next_segment": (
            {
                "run_id": str(next_segment["run_id"]),
                "start_local": str(next_segment["start_local"]),
                "seconds_to_start": seconds_to_next_start,
            }
            if next_segment is not None
            else None
        ),
        "evidence_boundaries": {
            "returns_read": False,
            "pnl_read": False,
            "signals_read": False,
            "market_payloads_read": False,
            "quality_metadata_only": True,
        },
        "next_allowed_action": next_allowed_action,
    }
    return {
        **deterministic,
        "deterministic_result_hash": sha256_json(deterministic),
    }


def build_progress_report(
    *,
    schedule_path: str | Path,
    expected_plan_hash: str,
    gate_path: str | Path,
    output_path: str | Path | None = None,
    now_local: datetime | None = None,
) -> dict[str, Any]:
    schedule_target = Path(schedule_path).expanduser().resolve()
    gate_target = Path(gate_path).expanduser().resolve()
    validation = validate_night_schedule_plan(
        schedule_target, expected_plan_hash
    )
    plan = _read_json(schedule_target)
    gate = _read_json(gate_target)
    approval = _validate_approval_pointer(
        gate=gate,
        schedule_path=schedule_target,
        plan_hash=expected_plan_hash,
        plan_file_sha256=validation["plan_file_sha256"],
    )
    report = summarize_progress(
        plan=plan,
        validation=validation,
        gate=gate,
        now_local=now_local or datetime.now(VOLGOGRAD_TZ),
        approval_status=approval,
    )
    report["gate_path"] = str(gate_target)
    report["gate_file_sha256"] = sha256_file(gate_target)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    if output_path is not None:
        _write_json_immutable(output_path, report)
    return report


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
        description="Read-only PIT train technical progress monitor"
    )
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_progress_report(
        schedule_path=args.schedule,
        expected_plan_hash=args.expected_plan_hash,
        gate_path=args.gate,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
