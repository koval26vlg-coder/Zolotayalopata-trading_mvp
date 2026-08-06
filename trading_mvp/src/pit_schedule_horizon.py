from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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


def _write_json_immutable(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"Refusing to overwrite immutable horizon artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        target.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected object at {target}:{line_number}")
        rows.append(value)
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
    return [
        row
        for row in rows
        if str(row.get("schema") or "") == QUALITY_SCHEMA
        and str(row.get("hypothesis_id") or "") == hypothesis_id
        and str(row.get("data_type") or "") == data_type
        and str(row.get("hypothesis_contract_sha256") or "") == contract_hash
        and str(row.get("scheduled_date") or "")
    ]


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

    hypothesis_id = str(sealed.get("hypothesis_id") or "")
    data_type = str(sealed.get("data_type") or "")
    contract_hash = str(sealed.get("hypothesis_contract_sha256") or "")
    if not hypothesis_id or not data_type or not contract_hash:
        raise ValueError("Plan is missing the frozen track identity")

    matched_rows = _matching_quality_rows(
        quality_rows,
        hypothesis_id=hypothesis_id,
        data_type=data_type,
        contract_hash=contract_hash,
    )
    accepted_dates = {
        str(row["scheduled_date"])
        for row in matched_rows
        if bool(row.get("technical_quality_accepted"))
    }
    rejected_dates = {
        str(row["scheduled_date"])
        for row in matched_rows
        if not bool(row.get("technical_quality_accepted"))
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
        len(accepted_dates) / completed_attempts
        if completed_attempts
        else 1.0
    )
    planning_rate = min(1.0, max(0.5, acceptance_rate))
    recommended_nights = (
        min(MAX_SCHEDULE_NIGHTS, math.ceil(shortfall / planning_rate))
        if shortfall
        else 0
    )
    last_scheduled_date = max(date.fromisoformat(value) for value in scheduled_dates)
    extension_start_date = (last_scheduled_date + timedelta(days=1)).isoformat()

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
        "recommended_extension_nights": recommended_nights,
        "extension_start_date": extension_start_date if shortfall else None,
        "single_plan_extension_capacity_sufficient": (
            recommended_nights >= shortfall
        ),
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
        raise ValueError(f"Refusing to overwrite immutable horizon audit: {audit_target}")
    if extension_target and extension_target.exists():
        raise ValueError(
            f"Refusing to overwrite immutable extension proposal: {extension_target}"
        )

    validation = validate_night_schedule_plan(
        plan_target,
        expected_plan_hash,
    )
    plan = _load_json(plan_target)
    sealed = plan["sealed_schedule"]
    ledger_path = Path(
        sealed["collection_stage"]["quality_ledger"]["path"]
    ).expanduser().resolve()
    quality_rows = _load_jsonl(ledger_path)
    horizon = compute_schedule_horizon(
        plan,
        quality_rows,
        observed_at=observed_at,
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
        extension_result = build_night_schedule_plan(
            hypothesis_bank_path=plan["hypothesis_bank"]["path"],
            hypothesis_id=horizon["hypothesis_id"],
            data_type=horizon["data_type"],
            goal_path=plan["goal_document"]["path"],
            output_path=extension_target,
            schedule_start_date=horizon["extension_start_date"],
            nights=int(horizon["recommended_extension_nights"]),
            segment_start_local=segment_start_local,
            segment_duration_sec=int(sealed["segment_duration_sec"]),
            interval_sec=int(sealed["interval_sec"]),
            output_root=str(sealed["output_root"]),
            collection_stage=str(sealed["collection_stage"]["name"]),
            quality_ledger_path=ledger_path,
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
                int(horizon["maximum_reachable_distinct_dates"])
                + int(extension_result["nights"])
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
            "file_sha256": validation["plan_file_sha256"],
            "plan_hash": expected_plan_hash,
        },
        "quality_ledger": {
            "path": str(ledger_path),
            "file_sha256": _sha256_file(ledger_path),
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
        "maximum_reachable_distinct_dates": horizon[
            "maximum_reachable_distinct_dates"
        ],
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
