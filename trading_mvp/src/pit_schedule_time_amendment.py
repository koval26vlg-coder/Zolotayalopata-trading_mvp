from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import night_schedule_plan as schedule
from feasibility_gate import read_json


AMENDMENT_SCHEMA = "fast_first_night_schedule_time_amendment_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _parse_local_timestamp(value: str, *, label: str) -> datetime:
    try:
        observed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must use ISO-8601 local time with UTC offset") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return observed


def _find_exact_segment(segments: list[Any], run_id: str, *, label: str) -> tuple[int, dict[str, Any]]:
    matches = [
        (index, segment)
        for index, segment in enumerate(segments)
        if isinstance(segment, dict) and str(segment.get("run_id") or "") == run_id
    ]
    if len(matches) != 1:
        raise ValueError(f"{label} must contain exactly one segment for run_id={run_id}")
    return matches[0]


def _assert_unchanged_except_time_override(
    base_sealed: dict[str, Any],
    amended_sealed: dict[str, Any],
    *,
    run_id: str,
) -> None:
    allowed_top_level_changes = {"segments", "schedule_amendment"}
    for key in sorted(set(base_sealed) | set(amended_sealed)):
        if key in allowed_top_level_changes:
            continue
        if base_sealed.get(key) != amended_sealed.get(key):
            raise ValueError(f"time amendment changed sealed field outside scope: {key}")

    base_segments = base_sealed.get("segments")
    amended_segments = amended_sealed.get("segments")
    if not isinstance(base_segments, list) or not isinstance(amended_segments, list):
        raise ValueError("sealed schedule segments must be lists")
    if len(base_segments) != len(amended_segments):
        raise ValueError("time amendment changed the segment count")
    for base_segment, amended_segment in zip(base_segments, amended_segments, strict=True):
        if not isinstance(base_segment, dict) or not isinstance(amended_segment, dict):
            raise ValueError("sealed schedule segment must be an object")
        if str(base_segment.get("run_id") or "") != run_id:
            if base_segment != amended_segment:
                raise ValueError(
                    f"time amendment changed an unrelated segment: {base_segment.get('run_id')}"
                )
            continue
        for key in sorted(set(base_segment) | set(amended_segment)):
            if key in {"start_local", "end_local"}:
                continue
            if base_segment.get(key) != amended_segment.get(key):
                raise ValueError(f"time amendment changed {run_id}.{key}")


def build_time_amendment_plan(
    *,
    base_plan_path: str | Path,
    expected_base_plan_hash: str,
    run_id: str,
    new_start_local: str,
    output_path: str | Path,
    created_at_utc: str,
) -> dict[str, Any]:
    """Freeze a one-segment deferred-time PlanOnly schedule without changing its trade contract."""

    base_target = Path(base_plan_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise ValueError(f"refusing to overwrite immutable amended PIT PlanOnly artifact: {output_target}")

    schedule.validate_night_schedule_plan(base_target, expected_base_plan_hash)
    base = read_json(base_target)
    base_sealed = base.get("sealed_schedule")
    if not isinstance(base_sealed, dict):
        raise ValueError("base schedule sealed_schedule is required")
    sealed_segments = base_sealed.get("segments")
    runtime_segments = base.get("segments")
    if not isinstance(sealed_segments, list) or not isinstance(runtime_segments, list):
        raise ValueError("base schedule segments are required")
    if len(sealed_segments) != len(runtime_segments):
        raise ValueError("base schedule sealed/runtime segment count mismatch")

    sealed_index, base_segment = _find_exact_segment(sealed_segments, run_id, label="base sealed schedule")
    runtime_index, base_runtime_segment = _find_exact_segment(
        runtime_segments,
        run_id,
        label="base runtime schedule",
    )
    if sealed_index != runtime_index:
        raise ValueError("base schedule sealed/runtime segment ordering mismatch")
    runtime_base = {
        key: value for key, value in base_runtime_segment.items() if key != "command_after_approval"
    }
    if runtime_base != base_segment:
        raise ValueError("base schedule selected runtime segment does not match the seal")

    original_start = _parse_local_timestamp(str(base_segment.get("start_local") or ""), label="base start_local")
    original_end = _parse_local_timestamp(str(base_segment.get("end_local") or ""), label="base end_local")
    hard_deadline = _parse_local_timestamp(
        str(base_segment.get("hard_deadline_local") or ""),
        label="base hard_deadline_local",
    )
    deferred_start = _parse_local_timestamp(new_start_local, label="new_start_local")
    if deferred_start.utcoffset() != original_start.utcoffset():
        raise ValueError("new_start_local must preserve the original UTC offset")
    if deferred_start.date() != original_start.date():
        raise ValueError("time amendment must preserve the PIT calendar date")
    if deferred_start < original_end:
        raise ValueError("time amendment must defer the segment until after its original end")
    if not (deferred_start.hour >= 23 or deferred_start.hour < 7):
        raise ValueError("new_start_local must remain inside the 23:00-07:00 PIT night window")

    duration_sec = int(base_segment.get("duration_sec") or 0)
    if duration_sec <= 0:
        raise ValueError("base segment duration_sec must be positive")
    deferred_end = deferred_start + (original_end - original_start)
    if deferred_end > hard_deadline:
        raise ValueError("deferred PIT segment would finish after its hard deadline")

    amended = copy.deepcopy(base)
    amended_sealed = amended["sealed_schedule"]
    amended_segment = amended_sealed["segments"][sealed_index]
    amended_segment["start_local"] = deferred_start.isoformat()
    amended_segment["end_local"] = deferred_end.isoformat()
    amendment = {
        "schema": AMENDMENT_SCHEMA,
        "kind": "DEFER_ONE_PIT_SEGMENT_WITHIN_SAME_NIGHT",
        "base_plan_path": str(base_target),
        "base_plan_hash": expected_base_plan_hash,
        "run_id": run_id,
        "original_start_local": original_start.isoformat(),
        "original_end_local": original_end.isoformat(),
        "new_start_local": deferred_start.isoformat(),
        "new_end_local": deferred_end.isoformat(),
        "hard_deadline_local": hard_deadline.isoformat(),
        "reason": "PRESERVE_GLOBAL_SINGLE_WRITER_WITHOUT_SKIPPING_PIT_DATE",
        "trade_contract_changed": False,
    }
    amended_sealed["schedule_amendment"] = amendment
    _assert_unchanged_except_time_override(base_sealed, amended_sealed, run_id=run_id)

    amended_hash = schedule._json_hash(amended_sealed)
    visible_wrapper = Path(str(amended_sealed["runtime_tools"]["visible_wrapper"]["path"])).resolve()
    execution_config = amended_sealed["execution_config"]
    output_root = str(amended_sealed["output_root"])
    amended_runtime_segments = []
    for segment in amended_sealed["segments"]:
        amended_runtime_segments.append(
            {
                **segment,
                "command_after_approval": schedule._runtime_command(
                    segment=segment,
                    visible_wrapper=visible_wrapper,
                    output_root=output_root,
                    plan_path=output_target,
                    plan_hash=amended_hash,
                    execution_config=execution_config,
                ),
            }
        )

    amended["created_at_utc"] = created_at_utc
    amended["plan_artifact_path"] = str(output_target)
    amended["plan_hash"] = amended_hash
    amended["sealed_schedule_hash"] = amended_hash
    amended["segments"] = amended_runtime_segments
    amended["time_only_amendment"] = amendment
    for flag in (
        "schedule_approved",
        "collection_started",
        "network_access",
        "oos_returns_read",
        "pnl_or_returns_read",
        "grid_search",
        "retune",
        "paper_forward",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        amended[flag] = False

    _write_json_atomic(output_target, amended)
    validation = schedule.validate_night_schedule_plan(output_target, amended_hash)
    return {
        "schema": AMENDMENT_SCHEMA,
        "mode": "PlanOnly",
        "verdict": "TIME_ONLY_AMENDMENT_VALID",
        "plan_path": str(output_target),
        "plan_file_sha256": schedule.sha256_file(output_target),
        "plan_hash": amended_hash,
        "base_plan_path": str(base_target),
        "base_plan_hash": expected_base_plan_hash,
        "time_only_amendment": amendment,
        "validated_segments": validation["segments"],
        "actual_collection_allowed": False,
        "network_access": False,
        "returns_read": False,
        "pnl_read": False,
        "oos_run": False,
        "grid_or_retune": False,
        "paper_or_live": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze a one-segment PIT time-only amendment without launching collection."
    )
    parser.add_argument("--base-plan", required=True)
    parser.add_argument("--expected-base-plan-hash", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--new-start-local", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--created-at-utc", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_time_amendment_plan(
        base_plan_path=args.base_plan,
        expected_base_plan_hash=args.expected_base_plan_hash,
        run_id=args.run_id,
        new_start_local=args.new_start_local,
        output_path=args.output,
        created_at_utc=args.created_at_utc,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
