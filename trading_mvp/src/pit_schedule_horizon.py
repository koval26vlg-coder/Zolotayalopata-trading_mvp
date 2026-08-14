from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from night_schedule_plan import (
    MAX_SCHEDULE_NIGHTS,
    build_night_schedule_plan,
    validate_night_schedule_plan,
)


AUDIT_SCHEMA = "trading_mvp_pit_schedule_horizon_audit_v1"
QUALITY_SCHEMA = "pit_universe_v2_quality_certification_v1"


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_file_sha256(
    path: str | Path,
    expected_sha256: str,
    *,
    label: str,
) -> None:
    observed_sha256 = _sha256_file(path)
    if observed_sha256 != expected_sha256:
        raise ValueError(
            f"{label} changed during horizon build: "
            f"expected={expected_sha256}, observed={observed_sha256}"
        )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _strict_json_loads(raw: str, *, source: str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at {source}: {exc}") from exc


def _read_bytes(path: str | Path) -> bytes:
    target = Path(path).expanduser().resolve()
    try:
        return target.read_bytes()
    except OSError as exc:
        raise ValueError(f"unable to read file: {target}: {exc}") from exc


def _decode_utf8_json(raw: bytes, *, source: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid UTF-8 at {source}: {exc}") from exc


def _write_json_immutable(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"Refusing to overwrite immutable horizon artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.tmp.",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(str(temporary), str(target))
        except FileExistsError as exc:
            raise ValueError(
                f"Refusing to overwrite immutable horizon artifact: {target}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _replace_string_value(
    value: Any,
    *,
    old: str,
    new: str,
) -> tuple[Any, int]:
    if isinstance(value, dict):
        replaced: dict[str, Any] = {}
        total = 0
        for key, item in value.items():
            replaced_item, count = _replace_string_value(item, old=old, new=new)
            replaced[key] = replaced_item
            total += count
        return replaced, total
    if isinstance(value, list):
        replaced_items: list[Any] = []
        total = 0
        for item in value:
            replaced_item, count = _replace_string_value(item, old=old, new=new)
            replaced_items.append(replaced_item)
            total += count
        return replaced_items, total
    if isinstance(value, str):
        return value.replace(old, new), value.count(old)
    return value, 0


def _build_extension_plan_immutable(
    *,
    extension_target: Path,
    plan_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    if extension_target.exists():
        raise ValueError(
            f"Refusing to overwrite immutable extension proposal: {extension_target}"
        )
    extension_target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{extension_target.name}.build.",
        suffix=".json",
        dir=extension_target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name).resolve()
    temporary.unlink()
    try:
        kwargs = dict(plan_kwargs)
        if "output_path" in kwargs:
            raise ValueError("plan_kwargs must not supply output_path")
        kwargs["output_path"] = temporary
        result = build_night_schedule_plan(**kwargs)

        temporary_plan, temporary_sha256 = _load_json_with_sha(temporary)
        if Path(str(result.get("output_path") or "")).resolve() != temporary:
            raise ValueError("extension builder returned an unexpected output path")
        if str(result.get("output_sha256") or "") != temporary_sha256:
            raise ValueError("extension builder output SHA-256 mismatch")
        if (
            Path(str(temporary_plan.get("plan_artifact_path") or "")).resolve()
            != temporary
        ):
            raise ValueError("temporary extension self-path mismatch")
        if (
            str(temporary_plan.get("mode") or "") != "PlanOnly"
            or bool(temporary_plan.get("schedule_approved"))
            or bool(temporary_plan.get("collection_started"))
        ):
            raise ValueError("temporary extension is not an inactive PlanOnly")

        plan_hash = str(result.get("plan_hash") or "")
        temporary_validation = validate_night_schedule_plan(temporary, plan_hash)
        if str(temporary_validation.get("plan_file_sha256") or "") != temporary_sha256:
            raise ValueError("temporary extension validation SHA-256 mismatch")

        rebound, replacements = _replace_string_value(
            temporary_plan,
            old=str(temporary),
            new=str(extension_target),
        )
        segments = rebound.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError("extension plan is missing runtime segments")
        expected_replacements = 1 + len(segments)
        if replacements != expected_replacements:
            raise ValueError(
                "extension self-path replacement count mismatch: "
                f"expected={expected_replacements}, observed={replacements}"
            )
        if str(rebound.get("plan_artifact_path") or "") != str(extension_target):
            raise ValueError("extension final self-path mismatch")

        expected_final_sha256 = _sha256_bytes(
            (json.dumps(rebound, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        published = False
        try:
            _write_json_immutable(extension_target, rebound)
            published = True
            final_sha256 = _sha256_file(extension_target)
            if final_sha256 != expected_final_sha256:
                raise ValueError("immutable extension publish SHA-256 mismatch")
            final_validation = validate_night_schedule_plan(
                extension_target,
                plan_hash,
            )
            if str(final_validation.get("plan_file_sha256") or "") != final_sha256:
                raise ValueError("immutable extension validation SHA-256 mismatch")
        except Exception:
            if published and extension_target.is_file():
                if _sha256_file(extension_target) == expected_final_sha256:
                    extension_target.unlink()
            raise

        return {
            **result,
            "output_path": str(extension_target),
            "output_sha256": final_sha256,
        }
    finally:
        temporary.unlink(missing_ok=True)


def _load_json_with_sha(path: str | Path) -> tuple[dict[str, Any], str]:
    target = Path(path).expanduser().resolve()
    raw = _read_bytes(target)
    value = _strict_json_loads(
        _decode_utf8_json(raw, source=str(target)),
        source=str(target),
    )
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {target}")
    return value, _sha256_bytes(raw)


def _load_json(path: str | Path) -> dict[str, Any]:
    value, _digest = _load_json_with_sha(path)
    return value


def _load_jsonl_with_sha(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return [], _sha256_bytes(b"")
    raw = _read_bytes(target)
    text = _decode_utf8_json(raw, source=str(target))
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        value = _strict_json_loads(
            raw_line,
            source=f"{target}:{line_number}",
        )
        if not isinstance(value, dict):
            raise ValueError(f"Expected object at {target}:{line_number}")
        rows.append(value)
    return rows, _sha256_bytes(raw)


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows, _digest = _load_jsonl_with_sha(path)
    return rows


def _parse_aware_datetime(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed


def _matching_quality_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    hypothesis_id: str,
    data_type: str,
    contract_hash: str,
) -> list[Mapping[str, Any]]:
    matching: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"quality row {index} must be an object")
        if row.get("schema") != QUALITY_SCHEMA:
            continue
        for field in (
            "hypothesis_id",
            "data_type",
            "hypothesis_contract_sha256",
            "scheduled_date",
        ):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"quality row {index}.{field} must be a non-empty string"
                )
        accepted = row.get("technical_quality_accepted")
        if not isinstance(accepted, bool):
            raise ValueError(
                f"quality row {index}.technical_quality_accepted must be boolean"
            )
        scheduled_date = str(row["scheduled_date"])
        try:
            parsed_date = date.fromisoformat(scheduled_date)
        except ValueError as exc:
            raise ValueError(
                f"quality row {index}.scheduled_date must use YYYY-MM-DD"
            ) from exc
        if parsed_date.isoformat() != scheduled_date:
            raise ValueError(
                f"quality row {index}.scheduled_date must use canonical YYYY-MM-DD"
            )
        observed_contract_hash = str(row["hypothesis_contract_sha256"])
        if len(observed_contract_hash) != 64 or any(
            character not in "0123456789abcdef" for character in observed_contract_hash
        ):
            raise ValueError(
                f"quality row {index}.hypothesis_contract_sha256 must be lowercase SHA-256"
            )
        if (
            row["hypothesis_id"] == hypothesis_id
            and row["data_type"] == data_type
            and observed_contract_hash == contract_hash
        ):
            matching.append(row)
    return matching


def compute_schedule_horizon(
    plan: Mapping[str, Any],
    quality_rows: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    sealed = plan.get("sealed_schedule")
    if not isinstance(sealed, Mapping):
        raise ValueError("Plan is missing sealed_schedule")
    stage = sealed.get("collection_stage")
    if not isinstance(stage, Mapping):
        raise ValueError("Plan is missing sealed collection_stage")
    segments = sealed.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Plan must contain sealed schedule segments")

    identity_fields: dict[str, str] = {}
    for field in ("hypothesis_id", "data_type", "hypothesis_contract_sha256"):
        value = sealed.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"sealed_schedule.{field} must be a non-empty string")
        identity_fields[field] = value
    hypothesis_id = identity_fields["hypothesis_id"]
    data_type = identity_fields["data_type"]
    contract_hash = identity_fields["hypothesis_contract_sha256"]
    if len(contract_hash) != 64 or any(
        character not in "0123456789abcdef" for character in contract_hash
    ):
        raise ValueError(
            "sealed_schedule.hypothesis_contract_sha256 must be lowercase SHA-256"
        )

    matched_rows = _matching_quality_rows(
        quality_rows,
        hypothesis_id=hypothesis_id,
        data_type=data_type,
        contract_hash=contract_hash,
    )
    accepted_dates = {
        row["scheduled_date"]
        for row in matched_rows
        if row["technical_quality_accepted"] is True
    }
    rejected_dates = {
        row["scheduled_date"]
        for row in matched_rows
        if row["technical_quality_accepted"] is False
    } - accepted_dates

    scheduled_dates: set[str] = set()
    reachable_dates: set[str] = set()
    expired_unaccepted_dates: set[str] = set()
    segment_statuses: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise ValueError("Schedule segment must be an object")
        start = _parse_aware_datetime(
            str(segment.get("start_local") or ""),
            field="segment.start_local",
        )
        deadline = _parse_aware_datetime(
            str(segment.get("hard_deadline_local") or ""),
            field="segment.hard_deadline_local",
        )
        scheduled_date = start.date().isoformat()
        if scheduled_date in scheduled_dates:
            raise ValueError(f"Duplicate scheduled date: {scheduled_date}")
        scheduled_dates.add(scheduled_date)
        if scheduled_date in accepted_dates:
            status = "ACCEPTED"
        elif observed_at > deadline:
            status = "EXPIRED_UNACCEPTED"
            expired_unaccepted_dates.add(scheduled_date)
        else:
            status = "REACHABLE"
            reachable_dates.add(scheduled_date)
        segment_statuses.append(
            {
                "sequence": int(segment.get("sequence") or 0),
                "run_id": str(segment.get("run_id") or ""),
                "scheduled_date": scheduled_date,
                "hard_deadline_local": deadline.isoformat(),
                "status": status,
            }
        )

    target_dates = int(stage.get("stage_target_distinct_dates") or 0)
    if target_dates <= 0:
        raise ValueError("stage_target_distinct_dates must be positive")
    maximum_reachable_dates = accepted_dates | reachable_dates
    maximum_reachable_count = len(maximum_reachable_dates)
    shortfall = max(0, target_dates - maximum_reachable_count)

    completed_attempts = len(accepted_dates | rejected_dates)
    acceptance_rate = (
        len(accepted_dates) / completed_attempts if completed_attempts else 1.0
    )
    planning_rate = min(1.0, max(0.5, acceptance_rate))
    rate_adjusted_nights = (
        min(MAX_SCHEDULE_NIGHTS, math.ceil(shortfall / planning_rate))
        if shortfall
        else 0
    )
    remaining_stage_capacity = max(0, target_dates - len(accepted_dates))
    recommended_nights = min(rate_adjusted_nights, remaining_stage_capacity)
    last_scheduled_date = max(date.fromisoformat(value) for value in scheduled_dates)
    first_segment_start = _parse_aware_datetime(
        str(segments[0].get("start_local") or ""),
        field="segment.start_local",
    )
    observed_in_schedule_tz = observed_at.astimezone(first_segment_start.tzinfo)
    candidate_start_today = datetime.combine(
        observed_in_schedule_tz.date(),
        first_segment_start.timetz(),
    )
    earliest_unexpired_date = observed_in_schedule_tz.date()
    if candidate_start_today <= observed_in_schedule_tz:
        earliest_unexpired_date += timedelta(days=1)
    extension_start_date = max(
        last_scheduled_date + timedelta(days=1),
        earliest_unexpired_date,
    ).isoformat()

    return {
        "decision": (
            "PLANONLY_EXTENSION_REQUIRED"
            if shortfall
            else "CURRENT_SCHEDULE_SUFFICIENT_FOR_TRAIN_GATE"
        ),
        "hypothesis_id": hypothesis_id,
        "data_type": data_type,
        "hypothesis_contract_sha256": contract_hash,
        "collection_stage": str(stage.get("name") or ""),
        "target_distinct_dates": target_dates,
        "accepted_distinct_dates": len(accepted_dates),
        "accepted_dates": sorted(accepted_dates),
        "rejected_quality_dates": sorted(rejected_dates),
        "scheduled_unique_dates": len(scheduled_dates),
        "reachable_scheduled_dates": len(reachable_dates),
        "reachable_dates": sorted(reachable_dates),
        "expired_unaccepted_dates": sorted(expired_unaccepted_dates),
        "maximum_reachable_distinct_dates": maximum_reachable_count,
        "train_gate_shortfall_dates": shortfall,
        "completed_quality_attempts": completed_attempts,
        "observed_quality_acceptance_rate": acceptance_rate,
        "planning_acceptance_rate_floor": planning_rate,
        "minimum_extension_nights": shortfall,
        "rate_adjusted_extension_nights": rate_adjusted_nights,
        "remaining_stage_capacity_nights": remaining_stage_capacity,
        "recommended_extension_nights": recommended_nights,
        "extension_capacity_limited_by_stage": (
            recommended_nights < rate_adjusted_nights
        ),
        "extension_start_date": extension_start_date if shortfall else None,
        "single_plan_extension_capacity_sufficient": (recommended_nights >= shortfall),
        "segments": segment_statuses,
    }


def build_horizon_audit(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    observed_at: datetime,
    audit_output_path: str | Path,
    extension_output_path: str | Path | None = None,
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    audit_target = Path(audit_output_path).expanduser().resolve()
    extension_target = (
        Path(extension_output_path).expanduser().resolve()
        if extension_output_path
        else None
    )
    if audit_target.exists():
        raise ValueError(
            f"Refusing to overwrite immutable horizon audit: {audit_target}"
        )
    if extension_target and extension_target.exists():
        raise ValueError(
            f"Refusing to overwrite immutable extension proposal: {extension_target}"
        )
    audit_tool_path = Path(__file__).resolve()
    audit_tool_sha256 = _sha256_file(audit_tool_path)

    plan, source_plan_file_sha256 = _load_json_with_sha(plan_target)
    sealed = plan["sealed_schedule"]
    ledger_path = (
        Path(sealed["collection_stage"]["quality_ledger"]["path"])
        .expanduser()
        .resolve()
    )
    if not ledger_path.is_file():
        raise ValueError(f"quality ledger is missing: {ledger_path}")
    quality_rows, quality_ledger_file_sha256 = _load_jsonl_with_sha(ledger_path)
    validation = validate_night_schedule_plan(plan_target, expected_plan_hash)
    if validation["plan_file_sha256"] != source_plan_file_sha256:
        raise ValueError("source schedule changed while it was being validated")
    validation_ledger_path = (
        Path(str(validation["quality_ledger_path"])).expanduser().resolve()
    )
    if validation_ledger_path != ledger_path:
        raise ValueError("validated quality ledger path differs from the sealed path")
    horizon = compute_schedule_horizon(
        plan,
        quality_rows,
        observed_at=observed_at,
    )
    if int(validation["current_accepted_distinct_dates"]) != int(
        horizon["accepted_distinct_dates"]
    ):
        raise ValueError(
            "quality ledger changed while the schedule was being validated"
        )
    _assert_file_sha256(
        plan_target,
        source_plan_file_sha256,
        label="source schedule",
    )
    _assert_file_sha256(
        ledger_path,
        quality_ledger_file_sha256,
        label="quality ledger",
    )

    extension: dict[str, Any] | None = None
    if extension_target:
        if horizon["decision"] != "PLANONLY_EXTENSION_REQUIRED":
            raise ValueError("Current schedule is sufficient; extension is not allowed")
        first_start = _parse_aware_datetime(
            str(sealed["segments"][0]["start_local"]),
            field="segment.start_local",
        )
        segment_start_local = first_start.strftime("%H:%M")
        extension_result = _build_extension_plan_immutable(
            extension_target=extension_target,
            plan_kwargs={
                "hypothesis_bank_path": plan["hypothesis_bank"]["path"],
                "hypothesis_id": horizon["hypothesis_id"],
                "data_type": horizon["data_type"],
                "goal_path": plan["goal_document"]["path"],
                "schedule_start_date": horizon["extension_start_date"],
                "nights": int(horizon["recommended_extension_nights"]),
                "segment_start_local": segment_start_local,
                "segment_duration_sec": int(sealed["segment_duration_sec"]),
                "interval_sec": int(sealed["interval_sec"]),
                "output_root": str(sealed["output_root"]),
                "collection_stage": str(sealed["collection_stage"]["name"]),
                "quality_ledger_path": ledger_path,
            },
        )
        _assert_file_sha256(
            plan_target,
            source_plan_file_sha256,
            label="source schedule",
        )
        _assert_file_sha256(
            ledger_path,
            quality_ledger_file_sha256,
            label="quality ledger",
        )
        extension = {
            "mode": "PlanOnly",
            "activated": False,
            "requires_explicit_schedule_approval": True,
            "output_path": str(extension_target),
            "output_sha256": str(extension_result["output_sha256"]),
            "plan_hash": str(extension_result["plan_hash"]),
            "start_date": horizon["extension_start_date"],
            "nights": int(extension_result["nights"]),
            "combined_maximum_reachable_distinct_dates": (
                min(
                    int(horizon["target_distinct_dates"]),
                    int(horizon["maximum_reachable_distinct_dates"])
                    + int(extension_result["nights"]),
                )
            ),
            "collection_stops_at_train_gate": True,
            "next_allowed_action": "await_explicit_night_schedule_approval",
        }

    core = {
        "schema": AUDIT_SCHEMA,
        "mode": "PlanOnly",
        "research_only": True,
        "source_schedule": {
            "path": str(plan_target),
            "file_sha256": source_plan_file_sha256,
            "plan_hash": expected_plan_hash,
        },
        "audit_tool": {
            "path": str(audit_tool_path),
            "file_sha256": audit_tool_sha256,
        },
        "quality_ledger": {
            "path": str(ledger_path),
            "file_sha256": quality_ledger_file_sha256,
            "rows_read": len(quality_rows),
        },
        "observed_at": observed_at.isoformat(),
        "horizon": horizon,
        "extension_proposal": extension,
        "authority": {
            "current_schedule_modified": False,
            "extension_activated": False,
            "collection_authorized": False,
            "new_schedule_requires_explicit_approval": bool(extension),
        },
        "safety": {
            "network_access": False,
            "returns_or_pnl_read": False,
            "oos_read": False,
            "signals_read": False,
            "hypothesis_changed": False,
            "venue_changed": False,
            "universe_changed": False,
            "cost_or_risk_changed": False,
            "grid_or_retune": False,
            "paper_forward_started": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
    }
    result_hash = _json_hash(core)
    artifact = {
        **core,
        "deterministic_result_hash": result_hash,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_immutable(audit_target, artifact)
    return {
        "decision": horizon["decision"],
        "audit_output_path": str(audit_target),
        "audit_output_sha256": _sha256_file(audit_target),
        "deterministic_result_hash": result_hash,
        "source_plan_hash": expected_plan_hash,
        "accepted_distinct_dates": horizon["accepted_distinct_dates"],
        "maximum_reachable_distinct_dates": horizon["maximum_reachable_distinct_dates"],
        "target_distinct_dates": horizon["target_distinct_dates"],
        "train_gate_shortfall_dates": horizon["train_gate_shortfall_dates"],
        "extension_proposal": extension,
        "safety": artifact["safety"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit PIT train-gate calendar coverage without reading market outcomes."
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--audit-output", required=True)
    parser.add_argument("--extension-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_horizon_audit(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        observed_at=_parse_aware_datetime(
            args.observed_at,
            field="observed_at",
        ),
        audit_output_path=args.audit_output,
        extension_output_path=args.extension_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
