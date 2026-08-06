from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from night_schedule_plan import validate_night_schedule_plan
from night_schedule_status import evaluate_night_schedule_status
from pit_universe_snapshot_quality import PitQualityConfig, evaluate_pit_snapshot_quality


REPORT_SCHEMA = "fast_first_night_schedule_quality_v1"
LEDGER_ENTRY_SCHEMA = "pit_universe_v2_quality_certification_v1"
SUPPORTED_POLICY_VERSION = "pit_universe_v2_segment_quality_v3"


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


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_runs: dict[tuple[str, str], str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid quality ledger JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(entry, dict) or entry.get("schema") != LEDGER_ENTRY_SCHEMA:
                raise ValueError(f"invalid quality ledger entry at {path}:{line_number}")
            certification_id = str(entry.get("certification_id") or "")
            body = {key: value for key, value in entry.items() if key != "certification_id"}
            observed_id = _json_hash(body)
            if certification_id != observed_id:
                raise ValueError(
                    f"certification_id mismatch at {path}:{line_number}: expected={certification_id}, observed={observed_id}"
                )
            if certification_id in seen_ids:
                raise ValueError(f"duplicate certification_id at {path}:{line_number}: {certification_id}")
            run_key = (str(entry.get("data_type") or ""), str(entry.get("segment_run_id") or ""))
            prior_id = seen_runs.get(run_key)
            if prior_id is not None and prior_id != certification_id:
                raise ValueError(f"conflicting certification for run_id={run_key[1]}")
            seen_ids.add(certification_id)
            seen_runs[run_key] = certification_id
            entries.append(entry)
    return entries


def _append_ledger_entries(path: Path, existing: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> int:
    existing_by_id = {str(entry["certification_id"]): entry for entry in existing}
    existing_by_run = {
        (str(entry.get("data_type") or ""), str(entry.get("segment_run_id") or "")): str(entry["certification_id"])
        for entry in existing
    }
    pending: list[dict[str, Any]] = []
    for entry in proposed:
        certification_id = str(entry["certification_id"])
        run_key = (str(entry.get("data_type") or ""), str(entry.get("segment_run_id") or ""))
        if certification_id in existing_by_id:
            continue
        prior_id = existing_by_run.get(run_key)
        if prior_id is not None and prior_id != certification_id:
            raise ValueError(
                f"quality certification conflict for run_id={run_key[1]}: existing={prior_id}, proposed={certification_id}"
            )
        pending.append(entry)
        existing_by_id[certification_id] = entry
        existing_by_run[run_key] = certification_id
    if not pending:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"quality ledger is locked: {lock_path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
            lock.write(json.dumps({"pid": os.getpid(), "ledger": str(path)}) + "\n")
            lock.flush()
            os.fsync(lock.fileno())
        current = _load_ledger(path)
        if [entry["certification_id"] for entry in current] != [entry["certification_id"] for entry in existing]:
            raise RuntimeError("quality ledger changed while waiting for append lock")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for entry in pending:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        lock_path.unlink(missing_ok=True)
    return len(pending)


def _validate_quality_policy(plan: dict[str, Any]) -> dict[str, Any]:
    policy = ((plan.get("sealed_schedule") or {}).get("quality_policy") or {})
    if not isinstance(policy, dict) or policy.get("policy_version") != SUPPORTED_POLICY_VERSION:
        raise ValueError(f"sealed quality policy must use {SUPPORTED_POLICY_VERSION}")
    if int(policy.get("min_exchanges_per_cycle") or 0) < 2:
        raise ValueError("quality policy must require at least two exchanges per cycle")
    max_error_cycle_ratio = policy.get("max_error_cycle_ratio")
    if max_error_cycle_ratio is None or float(max_error_cycle_ratio) < 0:
        raise ValueError("quality policy max_error_cycle_ratio must be non-negative")
    max_duplicate_snapshot_keys = policy.get("max_duplicate_snapshot_keys")
    if max_duplicate_snapshot_keys is None or int(max_duplicate_snapshot_keys) < 0:
        raise ValueError("quality policy max_duplicate_snapshot_keys must be non-negative")
    bbo_coverage = policy.get("minimum_dual_venue_bbo_size_coverage")
    if bbo_coverage is None or not 0.95 <= float(bbo_coverage) <= 1.0:
        raise ValueError("quality policy minimum_dual_venue_bbo_size_coverage must be in [0.95, 1]")
    if policy.get("require_final") is not True:
        raise ValueError("quality policy must require final manifests")
    if policy.get("require_positive_rows") is not True:
        raise ValueError("quality policy must require positive rows")
    if policy.get("reject_any_thin_exchange_cycle") is not True:
        raise ValueError("quality policy must reject every thin exchange cycle")
    if int(policy.get("max_clock_skew_sec") or 0) < 0:
        raise ValueError("quality policy max_clock_skew_sec must be non-negative")
    if int(policy.get("required_distinct_days") or 0) <= 0:
        raise ValueError("quality policy required_distinct_days must be positive")
    train_days = int(policy.get("train_feasibility_distinct_days") or 0)
    if train_days <= 0 or train_days >= int(policy["required_distinct_days"]):
        raise ValueError("quality policy train_feasibility_distinct_days must be inside the full window")
    if policy.get("oos_accrual_requires_feasibility_pass") is not True:
        raise ValueError("quality policy must stop OOS accrual until feasibility passes")
    return policy


def _parse_timestamp(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label} timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timezone-aware {label} timestamp required: {value!r}")
    return parsed


def _artifact_time_bounds(snapshots_path: Path, cycles_path: Path) -> dict[str, str]:
    snapshot_times: list[datetime] = []
    with snapshots_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid snapshots JSON at {snapshots_path}:{line_number}: {exc}") from exc
            snapshot_times.append(_parse_timestamp(row.get("snapshot_ts"), "snapshot"))
    cycle_starts: list[datetime] = []
    cycle_finishes: list[datetime] = []
    with cycles_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid cycles JSON at {cycles_path}:{line_number}: {exc}") from exc
            started = _parse_timestamp(row.get("cycle_started_at_utc"), "cycle_started")
            finished = _parse_timestamp(row.get("cycle_finished_at_utc"), "cycle_finished")
            if finished < started:
                raise ValueError(f"cycle_finished precedes cycle_started at {cycles_path}:{line_number}")
            cycle_starts.append(started)
            cycle_finishes.append(finished)
    if not snapshot_times or not cycle_starts or not cycle_finishes:
        raise ValueError("completed segment must contain timestamped snapshot and cycle rows")
    return {
        "first_snapshot_ts": min(snapshot_times).isoformat(),
        "last_snapshot_ts": max(snapshot_times).isoformat(),
        "first_cycle_started_at": min(cycle_starts).isoformat(),
        "last_cycle_finished_at": max(cycle_finishes).isoformat(),
    }


def _build_certification(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    plan_hash: str,
    plan_file_sha256: str,
    segment: dict[str, Any],
    manifest_path: Path,
    quality_policy: dict[str, Any],
) -> dict[str, Any]:
    quality = evaluate_pit_snapshot_quality(
        manifest_path,
        PitQualityConfig(
            min_cycles=int(segment.get("expected_cycles_floor") or 0),
            min_exchanges_per_cycle=int(quality_policy["min_exchanges_per_cycle"]),
            max_error_cycle_ratio=float(quality_policy["max_error_cycle_ratio"]),
            max_duplicate_snapshot_keys=int(quality_policy["max_duplicate_snapshot_keys"]),
            min_dual_venue_bbo_size_coverage=float(
                quality_policy["minimum_dual_venue_bbo_size_coverage"]
            ),
            require_final=bool(quality_policy["require_final"]),
        ),
    )
    snapshots_path = Path(str(quality["snapshots_path"])).expanduser().resolve()
    cycles_path = Path(str(quality["cycles_path"])).expanduser().resolve()
    if not snapshots_path.is_file() or not cycles_path.is_file():
        raise ValueError(f"quality evaluator resolved missing artifacts for run_id={segment['run_id']}")
    time_bounds = _artifact_time_bounds(snapshots_path, cycles_path)
    approved_start = _parse_timestamp(segment["start_local"], "segment_start")
    approved_deadline = _parse_timestamp(segment["hard_deadline_local"], "segment_deadline")
    skew_sec = int(quality_policy["max_clock_skew_sec"])
    observed_times = [_parse_timestamp(value, name) for name, value in time_bounds.items()]
    time_bounds_valid = all(
        approved_start.timestamp() - skew_sec <= value.timestamp() <= approved_deadline.timestamp() + skew_sec
        for value in observed_times
    )
    reasons = list(quality["reasons"])
    if not time_bounds_valid:
        reasons.append("segment_time_bounds_mismatch")
    technical_quality_accepted = bool(quality["ok"] and time_bounds_valid)
    scheduled_date = str(segment["start_local"]).split("T", 1)[0]
    body = {
        "schema": LEDGER_ENTRY_SCHEMA,
        "track_key": (
            f"{(plan.get('hypothesis') or {}).get('id')}|"
            f"{(plan.get('hypothesis') or {}).get('required_data_type')}"
        ),
        "hypothesis_id": str((plan.get("hypothesis") or {}).get("id") or ""),
        "data_type": str((plan.get("hypothesis") or {}).get("required_data_type") or ""),
        "hypothesis_contract_sha256": str(
            ((plan.get("sealed_schedule") or {}).get("hypothesis_contract_sha256") or "")
        ),
        "plan_path": str(plan_path),
        "plan_hash": plan_hash,
        "plan_file_sha256": plan_file_sha256,
        "quality_policy": quality_policy,
        "quality_policy_sha256": _json_hash(quality_policy),
        "segment_sequence": int(segment.get("sequence") or 0),
        "segment_run_id": str(segment.get("run_id") or ""),
        "scheduled_date": scheduled_date,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "snapshots_path": str(snapshots_path),
        "snapshots_sha256": _sha256(snapshots_path),
        "cycles_path": str(cycles_path),
        "cycles_sha256": _sha256(cycles_path),
        "technical_quality_accepted": technical_quality_accepted,
        "reasons": reasons,
        "time_bounds": time_bounds,
        "approved_start_local": str(segment["start_local"]),
        "approved_deadline_local": str(segment["hard_deadline_local"]),
        "rows": int((quality.get("metrics") or {}).get("rows") or 0),
        "cycles": int((quality.get("metrics") or {}).get("cycles") or 0),
        "error_cycles": int((quality.get("metrics") or {}).get("error_cycles") or 0),
        "thin_exchange_cycles": int((quality.get("metrics") or {}).get("thin_exchange_cycles") or 0),
        "duplicate_snapshot_keys": int((quality.get("metrics") or {}).get("duplicate_snapshot_keys") or 0),
        "state_invariant_errors": int((quality.get("metrics") or {}).get("state_invariant_errors") or 0),
        "binance_membership_invariant_errors": int(
            (quality.get("metrics") or {}).get("binance_membership_invariant_errors") or 0
        ),
        "returns_read": False,
        "pnl_read": False,
    }
    return {**body, "certification_id": _json_hash(body)}


def _report_without_market_read(
    *,
    decision: str,
    status: dict[str, Any],
    plan_path: Path,
    plan_hash: str,
    plan_file_sha256: str,
    ledger_path: Path,
    quality_policy: dict[str, Any],
    output_path: str | Path | None,
) -> dict[str, Any]:
    report = {
        "schema": REPORT_SCHEMA,
        "mode": "embargo_safe_technical_quality_certification",
        "decision": decision,
        "plan_path": str(plan_path),
        "plan_hash": plan_hash,
        "plan_file_sha256": plan_file_sha256,
        "quality_policy": quality_policy,
        "schedule_status_decision": status["decision"],
        "approval": status["approval"],
        "segments_evaluated": 0,
        "segments_accepted": 0,
        "segments_rejected": 0,
        "technical_market_rows_read": False,
        "returns_read": False,
        "pnl_read": False,
        "ledger": {
            "path": str(ledger_path),
            "entries_appended": 0,
            "accepted_distinct_dates": 0,
            "required_distinct_days": int(quality_policy["required_distinct_days"]),
            "train_feasibility_required_days": int(
                quality_policy["train_feasibility_distinct_days"]
            ),
        },
        "train_feasibility_gate_satisfied": False,
        "minimum_data_gate_satisfied": False,
        "oos_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "next_allowed_action": "await_explicit_night_schedule_approval",
    }
    if output_path is not None:
        _write_json_atomic(Path(output_path).expanduser().resolve(), report)
    return report


def certify_night_schedule_quality(
    plan_path: str | Path,
    expected_plan_hash: str,
    *,
    approval_record_root: str | Path,
    ledger_path: str | Path,
    now: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    validation = validate_night_schedule_plan(target, expected_plan_hash)
    plan = _read_json(target)
    policy = _validate_quality_policy(plan)
    ledger_target = Path(ledger_path).expanduser().resolve()
    sealed_ledger = Path(str(validation["quality_ledger_path"])).expanduser().resolve()
    if ledger_target != sealed_ledger:
        raise ValueError(
            f"quality ledger path differs from the sealed collection stage: "
            f"expected={sealed_ledger}, observed={ledger_target}"
        )
    status = evaluate_night_schedule_status(
        target,
        expected_plan_hash,
        approval_record_root=approval_record_root,
        now=now,
    )
    if not bool((status.get("approval") or {}).get("valid")):
        decision = (
            "AWAIT_EXPLICIT_SCHEDULE_APPROVAL"
            if (status.get("approval") or {}).get("reasons") == ["approval_record_missing"]
            else "NIGHT_SCHEDULE_APPROVAL_INVALID"
        )
        return _report_without_market_read(
            decision=decision,
            status=status,
            plan_path=target,
            plan_hash=expected_plan_hash,
            plan_file_sha256=str(validation["plan_file_sha256"]),
            ledger_path=ledger_target,
            quality_policy=policy,
            output_path=output_path,
        )

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

    existing = _load_ledger(ledger_target)
    if existing:
        expected_track = (
            f"{(plan.get('hypothesis') or {}).get('id')}|"
            f"{(plan.get('hypothesis') or {}).get('required_data_type')}"
        )
        foreign = [entry for entry in existing if entry.get("track_key") != expected_track]
        if foreign:
            raise ValueError("quality ledger contains entries from another hypothesis/data track")
    appended = _append_ledger_entries(ledger_target, existing, proposed) if proposed else 0
    ledger_entries = _load_ledger(ledger_target)
    accepted_dates = sorted(
        {
            str(entry["scheduled_date"])
            for entry in ledger_entries
            if bool(entry.get("technical_quality_accepted"))
        }
    )
    rejected_entries = [entry for entry in proposed if not bool(entry["technical_quality_accepted"])]
    required_days = int(policy["required_distinct_days"])
    train_feasibility_days = int(policy["train_feasibility_distinct_days"])
    train_feasibility_satisfied = len(accepted_dates) >= train_feasibility_days
    minimum_days_satisfied = len(accepted_dates) >= required_days
    if rejected_entries:
        decision = "PIT_SEGMENT_QUALITY_REJECTED"
        next_action = "recollect_rejected_dates_under_new_explicit_schedule"
    elif not proposed:
        decision = "NO_COMPLETED_SEGMENTS_READY_FOR_QUALITY"
        next_action = "wait_for_completed_segment"
    elif minimum_days_satisfied:
        decision = "PIT_QUALITY_MINIMUM_DAYS_REACHED"
        next_action = "build_full_evaluation_input_plan_bound_to_passed_train_feasibility"
    elif train_feasibility_satisfied:
        decision = "PIT_TRAIN_FEASIBILITY_DAYS_REACHED"
        next_action = "build_train_feasibility_input_plan_and_run_train_feasibility_before_more_accrual"
    else:
        decision = "PARTIAL_PIT_QUALITY_CERTIFIED"
        next_action = "continue_approved_data_accrual"
    report = {
        "schema": REPORT_SCHEMA,
        "mode": "embargo_safe_technical_quality_certification",
        "decision": decision,
        "plan_path": str(target),
        "plan_hash": expected_plan_hash,
        "plan_file_sha256": str(validation["plan_file_sha256"]),
        "quality_policy": policy,
        "quality_policy_sha256": _json_hash(policy),
        "collection_stage": validation["collection_stage"],
        "schedule_status_decision": status["decision"],
        "approval": status["approval"],
        "segment_certifications": proposed,
        "segments_evaluated": len(proposed),
        "segments_accepted": sum(bool(item["technical_quality_accepted"]) for item in proposed),
        "segments_rejected": sum(not bool(item["technical_quality_accepted"]) for item in proposed),
        "technical_market_rows_read": bool(proposed),
        "returns_read": False,
        "pnl_read": False,
        "ledger": {
            "path": str(ledger_target),
            "sha256": _sha256(ledger_target) if ledger_target.exists() else None,
            "entries_appended": appended,
            "total_entries": len(ledger_entries),
            "accepted_distinct_dates": len(accepted_dates),
            "accepted_distinct_date_values": accepted_dates,
            "required_distinct_days": required_days,
            "train_feasibility_required_days": train_feasibility_days,
        },
        "train_feasibility_gate_satisfied": train_feasibility_satisfied,
        "minimum_data_gate_satisfied": minimum_days_satisfied,
        "oos_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "next_allowed_action": next_action,
    }
    if output_path is not None:
        _write_json_atomic(Path(output_path).expanduser().resolve(), report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Certify frozen PIT night segments without reading returns or PnL")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--approval-record-root", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--now")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = certify_night_schedule_quality(
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
