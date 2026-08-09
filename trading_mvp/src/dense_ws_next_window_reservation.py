from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import continuous_production
import night_schedule_plan as pit_schedule


SCHEMA = "trading_mvp_dense_ws_next_no_skip_window_reservation_v1"
HYPOTHESIS_ID = "dense_ws_microstructure_regime_filter_v1"
CAMPAIGN_PREFIX = "dense_ws_microstructure_regime_filter_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    value = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {target}")
    return value


def _write_json_atomic(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite immutable reservation: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must use ISO-8601 time with UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _segment_times(segment: Mapping[str, Any]) -> tuple[datetime, datetime, datetime]:
    run_id = str(segment.get("run_id") or "")
    if not run_id:
        raise ValueError("every PIT segment must have run_id")
    start = _parse_timestamp(segment.get("start_local"), label=f"{run_id}.start_local")
    end = _parse_timestamp(segment.get("end_local"), label=f"{run_id}.end_local")
    hard_deadline = _parse_timestamp(
        segment.get("hard_deadline_local"),
        label=f"{run_id}.hard_deadline_local",
    )
    if end <= start:
        raise ValueError(f"{run_id} must have positive duration")
    if hard_deadline < end:
        raise ValueError(f"{run_id} hard deadline precedes segment end")
    return start, end, hard_deadline


def _overlaps(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return max(left_start, right_start) < min(left_end, right_end)


def _extension_binding(
    policy: Mapping[str, Any],
    *,
    schedule_path: Path,
    schedule_plan_hash: str,
) -> dict[str, Any]:
    candidate = policy.get("pit_schedule_extension_candidate")
    if not isinstance(candidate, Mapping):
        return {
            "matches_policy_candidate": False,
            "fresh_horizon_required": False,
            "approval_request_not_before_local": None,
        }
    candidate_path = Path(str(candidate.get("plan_path") or "")).expanduser()
    try:
        path_matches = candidate_path.resolve() == schedule_path.resolve()
    except OSError:
        path_matches = False
    return {
        "matches_policy_candidate": (
            path_matches and str(candidate.get("plan_hash") or "") == schedule_plan_hash
        ),
        "candidate_status": candidate.get("status"),
        "fresh_horizon_required": (
            candidate.get("requires_fresh_horizon_audit_before_approval") is True
        ),
        "approval_request_not_before_local": candidate.get(
            "approval_request_not_before_local"
        ),
    }


def _candidate_for_preceding_segment(
    *,
    policy: Mapping[str, Any],
    segments: list[dict[str, Any]],
    preceding_index: int,
    not_before: datetime,
    writer_sec: int,
    max_runtime_sec: int,
    start_buffer_sec: int,
    global_writer_gap_sec: int,
) -> dict[str, Any] | None:
    preceding = segments[preceding_index]
    _, preceding_end, _ = _segment_times(preceding)
    dense_start = preceding_end + timedelta(seconds=start_buffer_sec)
    if dense_start < not_before:
        return None

    writer_deadline = dense_start + timedelta(seconds=writer_sec)
    hard_deadline = dense_start + timedelta(seconds=max_runtime_sec)
    try:
        window = continuous_production.validate_runtime_request(
            dict(policy),
            requested_start_local=dense_start.isoformat(),
            expected_duration_sec=writer_sec,
            max_runtime_sec=max_runtime_sec,
        )
    except ValueError:
        return None

    overlapping: list[tuple[int, dict[str, Any], datetime, datetime, datetime]] = []
    for index, segment in enumerate(segments):
        segment_start, segment_end, segment_hard_deadline = _segment_times(segment)
        if _overlaps(dense_start, hard_deadline, segment_start, segment_end):
            overlapping.append(
                (index, segment, segment_start, segment_end, segment_hard_deadline)
            )
    if len(overlapping) != 1:
        return None

    deferred_index, deferred, original_start, original_end, pit_hard_deadline = overlapping[0]
    if deferred_index != preceding_index + 1:
        return None
    deferred_duration = original_end - original_start
    deferred_start = hard_deadline + timedelta(seconds=global_writer_gap_sec)
    deferred_end = deferred_start + deferred_duration
    if deferred_end > pit_hard_deadline:
        return None

    for index, other in enumerate(segments):
        if index == deferred_index:
            continue
        other_start, other_end, _ = _segment_times(other)
        if _overlaps(deferred_start, deferred_end, other_start, other_end):
            return None

    campaign_date = dense_start.date().strftime("%Y%m%d")
    campaign_id = f"{CAMPAIGN_PREFIX}_{campaign_date}_aef_24h"
    return {
        "campaign_id": campaign_id,
        "window_id": str(window["window_id"]),
        "window_type": str(window["window_type"]),
        "start_local": dense_start.isoformat(),
        "writer_deadline_local": writer_deadline.isoformat(),
        "hard_deadline_local": hard_deadline.isoformat(),
        "writer_duration_sec": writer_sec,
        "max_runtime_sec": max_runtime_sec,
        "preceding_pit": {
            "run_id": preceding["run_id"],
            "end_local": preceding_end.isoformat(),
            "disposition": "PRESERVED_NOT_SKIPPED_BEFORE_DENSE",
        },
        "deferred_pit": {
            "run_id": deferred["run_id"],
            "original_start_local": original_start.isoformat(),
            "original_end_local": original_end.isoformat(),
            "new_start_local": deferred_start.isoformat(),
            "new_end_local": deferred_end.isoformat(),
            "hard_deadline_local": pit_hard_deadline.isoformat(),
            "global_writer_gap_sec": global_writer_gap_sec,
            "disposition": "PRESERVED_NOT_SKIPPED_AFTER_DENSE_FINALIZATION",
        },
    }


def build_reservation(
    *,
    continuous_policy_path: str | Path,
    expected_continuous_policy_sha256: str,
    autopilot_policy_path: str | Path,
    expected_autopilot_policy_sha256: str,
    pit_schedule_path: str | Path,
    expected_pit_schedule_sha256: str,
    expected_pit_plan_hash: str,
    not_before_local: str,
    output_path: str | Path,
    generated_at_utc: str,
    writer_sec: int = 86_400,
    max_runtime_sec: int = 88_200,
    start_buffer_sec: int = 1_200,
    global_writer_gap_sec: int = 300,
) -> dict[str, Any]:
    """Reserve the earliest no-skip Dense window without authorizing a run."""

    for label, value in (
        ("writer_sec", writer_sec),
        ("max_runtime_sec", max_runtime_sec),
        ("start_buffer_sec", start_buffer_sec),
        ("global_writer_gap_sec", global_writer_gap_sec),
    ):
        if int(value) <= 0:
            raise ValueError(f"{label} must be positive")
    if max_runtime_sec < writer_sec:
        raise ValueError("max_runtime_sec must be >= writer_sec")

    continuous_policy_target = Path(continuous_policy_path).expanduser().resolve()
    autopilot_policy_target = Path(autopilot_policy_path).expanduser().resolve()
    schedule_target = Path(pit_schedule_path).expanduser().resolve()
    if _sha256_file(continuous_policy_target) != expected_continuous_policy_sha256:
        raise ValueError("continuous policy file SHA-256 mismatch")
    if _sha256_file(autopilot_policy_target) != expected_autopilot_policy_sha256:
        raise ValueError("autopilot policy file SHA-256 mismatch")
    if _sha256_file(schedule_target) != expected_pit_schedule_sha256:
        raise ValueError("PIT schedule file SHA-256 mismatch")

    continuous_policy = _read_json(continuous_policy_target)
    autopilot_policy = _read_json(autopilot_policy_target)
    schedule = _read_json(schedule_target)
    pit_schedule.validate_night_schedule_plan(schedule_target, expected_pit_plan_hash)
    if str(schedule.get("plan_hash") or "") != expected_pit_plan_hash:
        raise ValueError("PIT schedule plan hash mismatch")
    if schedule.get("mode") != "PlanOnly":
        raise ValueError("PIT source schedule must remain PlanOnly")

    configured_grace = int(
        (continuous_policy.get("runtime") or {}).get("shutdown_grace_sec") or 0
    )
    if max_runtime_sec - writer_sec != configured_grace:
        raise ValueError("Dense max runtime must equal writer duration plus shutdown grace")
    hard_output_cap_bytes = int(
        (continuous_policy.get("accelerated_evidence_factory") or {}).get(
            "hard_campaign_output_cap_bytes"
        )
        or 0
    )
    if hard_output_cap_bytes <= 0:
        raise ValueError("hard campaign output cap must be positive")

    raw_segments = schedule.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) < 2:
        raise ValueError("PIT schedule must contain at least two segments")
    segments = [dict(item) for item in raw_segments if isinstance(item, Mapping)]
    if len(segments) != len(raw_segments):
        raise ValueError("every PIT segment must be an object")
    segments.sort(key=lambda item: _parse_timestamp(item.get("start_local"), label="start_local"))
    not_before = _parse_timestamp(not_before_local, label="not_before_local")

    candidate = None
    for index in range(len(segments) - 1):
        candidate = _candidate_for_preceding_segment(
            policy=continuous_policy,
            segments=segments,
            preceding_index=index,
            not_before=not_before,
            writer_sec=writer_sec,
            max_runtime_sec=max_runtime_sec,
            start_buffer_sec=start_buffer_sec,
            global_writer_gap_sec=global_writer_gap_sec,
        )
        if candidate is not None:
            break
    if candidate is None:
        raise ValueError("no feasible 24-hour no-skip Dense window exists in the PIT horizon")

    extension = _extension_binding(
        autopilot_policy,
        schedule_path=schedule_target,
        schedule_plan_hash=expected_pit_plan_hash,
    )
    schedule_approved = schedule.get("schedule_approved") is True
    needs_fresh_schedule = (
        not schedule_approved
        and extension["matches_policy_candidate"] is True
        and extension["fresh_horizon_required"] is True
    )
    status = (
        "READY_FOR_TIME_ONLY_REFREEZE_PROPOSAL"
        if schedule_approved
        else (
            "CONTINGENT_ON_FRESH_PIT_EXTENSION_APPROVAL"
            if needs_fresh_schedule
            else "CONTINGENT_ON_PIT_SCHEDULE_APPROVAL"
        )
    )
    next_action = (
        "REFRESH_AND_APPROVE_PIT_EXTENSION_THEN_REBUILD_EXACT_REFREEZE"
        if needs_fresh_schedule
        else (
            "APPROVE_PIT_SCHEDULE_THEN_REBUILD_EXACT_REFREEZE"
            if not schedule_approved
            else "BUILD_EXACT_TIME_ONLY_REFREEZE_PROPOSAL"
        )
    )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "PlanOnly",
        "status": status,
        "generated_at_utc": _parse_timestamp(
            generated_at_utc,
            label="generated_at_utc",
        ).astimezone(timezone.utc).isoformat(),
        "research_only": True,
        "hypothesis_id": HYPOTHESIS_ID,
        "source": {
            "continuous_policy_path": str(continuous_policy_target),
            "continuous_policy_sha256": expected_continuous_policy_sha256,
            "autopilot_policy_path": str(autopilot_policy_target),
            "autopilot_policy_sha256": expected_autopilot_policy_sha256,
            "pit_schedule_path": str(schedule_target),
            "pit_schedule_file_sha256": expected_pit_schedule_sha256,
            "pit_schedule_plan_hash": expected_pit_plan_hash,
            "pit_schedule_approved": schedule_approved,
            "extension_binding": extension,
        },
        "reservation": {
            **candidate,
            "hard_output_cap_bytes": hard_output_cap_bytes,
            "uninterrupted_required": True,
            "suppressed_pit_run_ids": [],
        },
        "frozen_invariants": {
            "hypothesis_changed": False,
            "venue_changed": False,
            "universe_changed": False,
            "signal_changed": False,
            "cost_changed": False,
            "risk_changed": False,
            "duration_changed": False,
            "output_cap_changed": False,
            "grid_or_retune": False,
        },
        "authorization_boundary": {
            "this_is_not_contract_refreeze_approval": True,
            "this_is_not_launch_approval": True,
            "collector_launch_allowed": False,
            "network_access": False,
            "market_data_read": False,
            "returns_or_pnl": False,
            "oos": False,
            "paper_or_live": False,
            "private_api": False,
            "real_capital": False,
            "leverage_or_margin": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "next_allowed_action": next_action,
        "reservation_hash_method": "sha256_canonical_json_excluding_reservation_hash",
    }
    payload["reservation_hash"] = _canonical_hash(payload)
    _write_json_atomic(output_path, payload)
    persisted = _read_json(output_path)
    observed_hash = str(persisted.pop("reservation_hash") or "")
    if observed_hash != _canonical_hash(persisted):
        raise ValueError("persisted reservation hash mismatch")
    return _read_json(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reserve the earliest 24-hour Dense window while preserving adjacent PIT runs."
    )
    parser.add_argument("--continuous-policy", type=Path, required=True)
    parser.add_argument("--expected-continuous-policy-sha256", required=True)
    parser.add_argument("--autopilot-policy", type=Path, required=True)
    parser.add_argument("--expected-autopilot-policy-sha256", required=True)
    parser.add_argument("--pit-schedule", type=Path, required=True)
    parser.add_argument("--expected-pit-schedule-sha256", required=True)
    parser.add_argument("--expected-pit-plan-hash", required=True)
    parser.add_argument("--not-before-local", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--writer-sec", type=int, default=86_400)
    parser.add_argument("--max-runtime-sec", type=int, default=88_200)
    parser.add_argument("--start-buffer-sec", type=int, default=1_200)
    parser.add_argument("--global-writer-gap-sec", type=int, default=300)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_reservation(
        continuous_policy_path=args.continuous_policy,
        expected_continuous_policy_sha256=args.expected_continuous_policy_sha256,
        autopilot_policy_path=args.autopilot_policy,
        expected_autopilot_policy_sha256=args.expected_autopilot_policy_sha256,
        pit_schedule_path=args.pit_schedule,
        expected_pit_schedule_sha256=args.expected_pit_schedule_sha256,
        expected_pit_plan_hash=args.expected_pit_plan_hash,
        not_before_local=args.not_before_local,
        output_path=args.output,
        generated_at_utc=args.generated_at_utc,
        writer_sec=args.writer_sec,
        max_runtime_sec=args.max_runtime_sec,
        start_buffer_sec=args.start_buffer_sec,
        global_writer_gap_sec=args.global_writer_gap_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
