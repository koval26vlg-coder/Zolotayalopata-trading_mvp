from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from night_schedule_plan import validate_night_schedule_plan


STATUS_SCHEMA = "fast_first_night_schedule_status_v1"
APPROVAL_SCHEMA = "trading_mvp_night_schedule_approval_v1"
MANIFEST_SCHEMA = "pit_universe_snapshot_manifest_v2"
SEGMENT_STATUSES = (
    "PLANNED",
    "DUE",
    "RUNNING",
    "COMPLETED",
    "STOPPED_INCOMPLETE",
    "MISSED",
    "INVALID",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timezone-aware datetime required: {value!r}")
    return parsed


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _validate_approval(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    plan_hash: str,
    plan_file_sha256: str,
    approval_record_root: Path,
    now: datetime,
) -> dict[str, Any]:
    approval_path = approval_record_root / f"{plan_hash}.approval.json"
    reasons: list[str] = []
    approval: dict[str, Any] | None = None
    if not approval_path.is_file():
        reasons.append("approval_record_missing")
    else:
        try:
            approval = _read_json(approval_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"approval_record_invalid_json:{type(exc).__name__}")

    expires_at: datetime | None = None
    if approval is not None:
        expected_run_ids = [str(item.get("run_id") or "") for item in plan.get("segments") or []]
        checks = (
            (approval.get("schema") == APPROVAL_SCHEMA, "approval_schema_mismatch"),
            (approval.get("status") == "ACTIVE", "approval_status_not_active"),
            (Path(str(approval.get("plan_path") or "")).expanduser().resolve() == plan_path, "approval_plan_path_mismatch"),
            (str(approval.get("plan_hash") or "") == plan_hash, "approval_plan_hash_mismatch"),
            (str(approval.get("plan_file_sha256") or "") == plan_file_sha256, "approval_plan_file_hash_mismatch"),
            (
                str(approval.get("data_type") or "")
                == str((plan.get("hypothesis") or {}).get("required_data_type") or ""),
                "approval_data_type_mismatch",
            ),
            (list(approval.get("segment_run_ids") or []) == expected_run_ids, "approval_segment_run_ids_mismatch"),
            (approval.get("visible_terminal_required") is True, "approval_visible_terminal_not_required"),
            (approval.get("data_embargo") is True, "approval_data_embargo_not_enabled"),
            (approval.get("auto_resume_allowed") is False, "approval_auto_resume_not_disabled"),
        )
        reasons.extend(reason for passed, reason in checks if not passed)
        try:
            expires_at = _parse_datetime(str(approval.get("expires_at") or ""))
        except ValueError:
            reasons.append("approval_expiry_invalid")

    valid = not reasons
    return {
        "record_path": str(approval_path.resolve()),
        "record_exists": approval_path.is_file(),
        "record_sha256": _sha256(approval_path) if approval_path.is_file() else None,
        "valid": valid,
        "active": bool(valid and expires_at is not None and now <= expires_at),
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "reasons": reasons,
    }


def _lock_state(lock_path: Path) -> tuple[int | None, bool]:
    if not lock_path.is_file():
        return None, False
    try:
        payload = _read_json(lock_path)
        pid = int(payload.get("pid") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, False
    return (pid if pid > 0 else None), _pid_alive(pid)


def _manifest_status(segment: dict[str, Any], output_root: Path, now: datetime) -> dict[str, Any]:
    run_id = str(segment.get("run_id") or "")
    run_dir = output_root / run_id
    manifest_path = run_dir / "manifest.json"
    lock_path = run_dir / "collector.lock"
    start = _parse_datetime(str(segment["start_local"]))
    deadline = _parse_datetime(str(segment["hard_deadline_local"]))
    base = {
        "sequence": int(segment.get("sequence") or 0),
        "run_id": run_id,
        "start_local": start.isoformat(),
        "end_local": str(segment.get("end_local") or ""),
        "hard_deadline_local": deadline.isoformat(),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_exists": manifest_path.is_file(),
        "manifest_sha256": None,
        "collector_pid": None,
        "collector_pid_alive": False,
        "cycle_count": 0,
        "rows_total": 0,
        "errors_total": 0,
        "last_successful_exchanges": [],
        "updated_at_utc": None,
        "stop_condition": None,
        "stop_reason": None,
        "validation_reasons": [],
    }
    if not manifest_path.is_file():
        if now < start:
            base["status"] = "PLANNED"
        elif now <= deadline:
            base["status"] = "DUE"
        else:
            base["status"] = "MISSED"
        return base

    base["manifest_sha256"] = _sha256(manifest_path)
    try:
        manifest = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        base["status"] = "INVALID"
        base["validation_reasons"] = [f"manifest_invalid_json:{type(exc).__name__}"]
        return base

    pid, pid_alive = _lock_state(lock_path)
    base.update(
        {
            "collector_pid": pid,
            "collector_pid_alive": pid_alive,
            "cycle_count": int(manifest.get("cycle_count") or 0),
            "rows_total": int(manifest.get("rows_total") or 0),
            "errors_total": int(manifest.get("errors_total") or 0),
            "last_successful_exchanges": sorted(str(value) for value in (manifest.get("last_successful_exchanges") or [])),
            "updated_at_utc": manifest.get("updated_at_utc"),
            "stop_condition": manifest.get("stop_condition"),
            "stop_reason": manifest.get("stop_reason"),
        }
    )
    validation_reasons: list[str] = []
    expected_config = {
        "duration_sec": int(segment.get("duration_sec") or 0),
        "interval_sec": int(segment.get("interval_sec") or 0),
    }
    checks = (
        (manifest.get("schema") == MANIFEST_SCHEMA, "manifest_schema_mismatch"),
        (manifest.get("mode") == "pit_universe_snapshot_collect", "manifest_mode_mismatch"),
        (str(manifest.get("run_id") or "") == run_id, "manifest_run_id_mismatch"),
        (int(manifest.get("duration_sec") or 0) == expected_config["duration_sec"], "manifest_duration_mismatch"),
        (int(manifest.get("interval_sec") or 0) == expected_config["interval_sec"], "manifest_interval_mismatch"),
    )
    validation_reasons.extend(reason for passed, reason in checks if not passed)
    if validation_reasons:
        base["status"] = "INVALID"
        base["validation_reasons"] = validation_reasons
        return base

    if str(manifest.get("status") or "") == "RUNNING" and not bool(manifest.get("final")):
        if pid_alive:
            base["status"] = "RUNNING"
        else:
            base["status"] = "STOPPED_INCOMPLETE"
            base["validation_reasons"] = ["running_manifest_without_live_collector"]
            if not base["stop_reason"]:
                base["stop_reason"] = "Manifest says RUNNING but no live collector lock owner was found."
        return base

    if bool(manifest.get("incomplete")) or str(manifest.get("status") or "") == "STOPPED_INCOMPLETE":
        base["status"] = "STOPPED_INCOMPLETE"
        return base

    completion_checks = (
        (manifest.get("final") is True, "manifest_not_final"),
        (manifest.get("incomplete") is False, "manifest_marked_incomplete"),
        (manifest.get("status") == "COMPLETED", "manifest_status_not_completed"),
        (manifest.get("stop_condition") == "duration_sec", "manifest_stop_condition_mismatch"),
        (
            int(manifest.get("cycle_count") or 0) >= int(segment.get("expected_cycles_floor") or 0),
            "manifest_cycle_floor_not_met",
        ),
        (int(manifest.get("rows_total") or 0) > 0, "manifest_has_no_rows"),
    )
    completion_reasons = [reason for passed, reason in completion_checks if not passed]
    if completion_reasons:
        base["status"] = "INVALID"
        base["validation_reasons"] = completion_reasons
    else:
        base["status"] = "COMPLETED"
    return base


def _decision(summary: dict[str, int], approval: dict[str, Any]) -> tuple[str, str]:
    if not approval["valid"]:
        if approval["reasons"] == ["approval_record_missing"]:
            return "AWAIT_EXPLICIT_SCHEDULE_APPROVAL", "await_explicit_night_schedule_approval"
        return "NIGHT_SCHEDULE_APPROVAL_INVALID", "reject_invalid_schedule_approval"
    if summary["INVALID"]:
        return "NIGHT_SEGMENT_INVALID", "inspect_invalid_segment_metadata"
    if summary["RUNNING"]:
        return "NIGHT_SEGMENT_RUNNING", "monitor_running_segment_only"
    if summary["STOPPED_INCOMPLETE"]:
        return "NIGHT_SEGMENT_STOPPED_INCOMPLETE", "resume_incomplete_segment_visible_same_run_id"
    if summary["DUE"]:
        if approval["active"]:
            return "NIGHT_SEGMENT_DUE", "start_due_segment_in_visible_terminal"
        return "NIGHT_SCHEDULE_APPROVAL_EXPIRED", "do_not_start_expired_schedule_segment"
    if summary["MISSED"]:
        return "NIGHT_SEGMENT_MISSED", "record_missed_segment_and_wait_for_next_window"
    if summary["COMPLETED"] and not summary["PLANNED"]:
        return "NIGHT_SCHEDULE_TECHNICALLY_COMPLETED", "run_embargo_safe_segment_quality_certification"
    return "WAIT_FOR_NEXT_NIGHT_SEGMENT", "wait_for_next_approved_visible_segment_window"


def evaluate_night_schedule_status(
    plan_path: str | Path,
    expected_plan_hash: str,
    *,
    approval_record_root: str | Path,
    now: str | datetime | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    validation = validate_night_schedule_plan(target, expected_plan_hash)
    plan = _read_json(target)
    observed_now = _parse_datetime(now) if now is not None else datetime.now(timezone.utc)
    output_root = Path(str(plan.get("output_root") or "")).expanduser().resolve()
    approval = _validate_approval(
        plan=plan,
        plan_path=target,
        plan_hash=expected_plan_hash,
        plan_file_sha256=str(validation["plan_file_sha256"]),
        approval_record_root=Path(approval_record_root).expanduser().resolve(),
        now=observed_now,
    )
    segments = [_manifest_status(item, output_root, observed_now) for item in (plan.get("segments") or [])]
    counts = Counter(str(item["status"]) for item in segments)
    summary = {status: int(counts.get(status, 0)) for status in SEGMENT_STATUSES}
    decision, next_allowed_action = _decision(summary, approval)
    technically_completed_dates = sorted(
        {
            _parse_datetime(str(item["start_local"])).date().isoformat()
            for item in segments
            if item["status"] == "COMPLETED"
        }
    )
    coverage_projection = plan.get("coverage_projection") or {}
    required_days = int(coverage_projection.get("required_days") or 0)
    train_feasibility_days = int(coverage_projection.get("train_feasibility_required_days") or 0)
    report = {
        "schema": STATUS_SCHEMA,
        "mode": "embargo_safe_technical_status",
        "decision": decision,
        "observed_at": observed_now.isoformat(),
        "plan_path": str(target),
        "plan_hash": expected_plan_hash,
        "plan_file_sha256": str(validation["plan_file_sha256"]),
        "approval": approval,
        "output_root": str(output_root),
        "segments": segments,
        "summary": summary,
        "coverage": {
            "collection_stage": validation["collection_stage"],
            "scheduled_dates": len(segments),
            "technically_completed_dates": len(technically_completed_dates),
            "technically_completed_date_values": technically_completed_dates,
            "quality_certified_dates": 0,
            "quality_ledger_accepted_dates_now": validation["current_accepted_distinct_dates"],
            "remaining_collection_stage_dates": validation["remaining_stage_dates"],
            "required_days": required_days,
            "train_feasibility_required_days": train_feasibility_days,
            "train_feasibility_gate_satisfied": False,
            "minimum_data_gate_satisfied": False,
            "note": (
                "Technical completion is not data-quality certification. At the train threshold, "
                "quality certification must pause accrual and run feasibility before OOS collection."
            ),
        },
        "research_only": True,
        "data_embargo_enforced": True,
        "market_rows_read": False,
        "returns_read": False,
        "pnl_read": False,
        "collection_started": any(bool(item["manifest_exists"]) for item in segments),
        "oos_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "auto_resume": False,
        "next_allowed_action": next_allowed_action,
    }
    if output_path is not None:
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name(f"{output.name}.tmp.{os.getpid()}")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Embargo-safe technical status for a frozen night schedule")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--approval-record-root", required=True)
    parser.add_argument("--now")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = evaluate_night_schedule_status(
        args.plan,
        args.expected_plan_hash,
        approval_record_root=args.approval_record_root,
        now=args.now,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
