from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from feasibility_gate import read_json, sha256_file
from hypothesis_contract import validate_hypothesis_contract


PLAN_SCHEMA = "fast_first_night_schedule_plan_v2"
SUPPORTED_DATA_TYPE = "PIT_UNIVERSE_V2_FORWARD"
MAX_SCHEDULE_NIGHTS = 14
MAX_SEGMENT_RUNTIME_SEC = 10_800
QUALITY_POLICY_VERSION = "pit_universe_v2_segment_quality_v3"
QUALITY_CERTIFICATION_SCHEMA = "pit_universe_v2_quality_certification_v1"
TRAIN_ACCRUAL_STAGE = "train_accrual"
OOS_ACCRUAL_STAGE = "oos_accrual"
COLLECTION_STAGES = frozenset({TRAIN_ACCRUAL_STAGE, OOS_ACCRUAL_STAGE})
VOLGOGRAD_TZ = timezone(timedelta(hours=3), name="Europe/Volgograd")
RUNTIME_TOOL_NAMES = (
    "schedule_planner",
    "visible_wrapper",
    "collector",
    "public_probe_client",
    "approval_script",
    "status_tool",
    "quality_certifier",
    "segment_quality_evaluator",
    "hypothesis_contract_validator",
    "costs_module",
    "feasibility_estimator",
    "membership_drift_evaluator",
)
COLLECTION_DATA_PLANE_TOOL_NAMES = frozenset(
    {"visible_wrapper", "collector", "public_probe_client"}
)


def _validate_train_feasibility_evidence(
    train_plan_path: str | Path,
    feasibility_path: str | Path,
) -> dict[str, Any]:
    # Train accrual must not depend on the heavier evaluator import path.
    from pit_membership_drift_evaluator import validate_train_feasibility_evidence

    return validate_train_feasibility_evidence(train_plan_path, feasibility_path)


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _load_hypothesis(bank_path: str | Path, hypothesis_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    bank = read_json(bank_path)
    hypotheses = bank.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("Hypothesis bank must contain a hypotheses list")
    for hypothesis in hypotheses:
        if isinstance(hypothesis, dict) and hypothesis.get("id") == hypothesis_id:
            return bank, hypothesis
    raise ValueError(f"Hypothesis id not found in bank: {hypothesis_id}")


def _load_quality_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError(f"quality ledger is not a file: {path}")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_runs: dict[tuple[str, str], str] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid quality ledger JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(entry, dict) or entry.get("schema") != QUALITY_CERTIFICATION_SCHEMA:
                raise ValueError(f"invalid quality ledger entry at {path}:{line_number}")
            certification_id = str(entry.get("certification_id") or "")
            body = {key: value for key, value in entry.items() if key != "certification_id"}
            observed_id = _json_hash(body)
            if certification_id != observed_id:
                raise ValueError(
                    f"quality certification_id mismatch at {path}:{line_number}: "
                    f"expected={certification_id}, observed={observed_id}"
                )
            if certification_id in seen_ids:
                raise ValueError(f"duplicate quality certification_id at {path}:{line_number}")
            run_key = (str(entry.get("data_type") or ""), str(entry.get("segment_run_id") or ""))
            prior = seen_runs.get(run_key)
            if prior is not None and prior != certification_id:
                raise ValueError(f"conflicting quality certification for run_id={run_key[1]}")
            seen_ids.add(certification_id)
            seen_runs[run_key] = certification_id
            entries.append(entry)
    return entries


def _quality_state(
    ledger_path: Path,
    *,
    hypothesis_id: str,
    data_type: str,
    contract_hash: str,
) -> dict[str, Any]:
    entries = _load_quality_ledger(ledger_path)
    expected_track = f"{hypothesis_id}|{data_type}"
    accepted_by_date: dict[str, dict[str, str]] = {}
    certification_ids: list[str] = []
    for entry in entries:
        if str(entry.get("track_key") or "") != expected_track:
            raise ValueError("quality ledger contains entries from another hypothesis/data track")
        if str(entry.get("hypothesis_id") or "") != hypothesis_id:
            raise ValueError("quality ledger hypothesis id mismatch")
        if str(entry.get("data_type") or "") != data_type:
            raise ValueError("quality ledger data type mismatch")
        if str(entry.get("hypothesis_contract_sha256") or "") != contract_hash:
            raise ValueError("quality ledger hypothesis contract hash mismatch")
        certification_id = str(entry["certification_id"])
        certification_ids.append(certification_id)
        if not bool(entry.get("technical_quality_accepted")):
            continue
        scheduled_date = str(entry.get("scheduled_date") or "")
        _parse_date(scheduled_date)
        descriptor = {
            "certification_id": certification_id,
            "scheduled_date": scheduled_date,
            "segment_run_id": str(entry.get("segment_run_id") or ""),
        }
        prior = accepted_by_date.get(scheduled_date)
        if prior is not None and prior != descriptor:
            raise ValueError(f"duplicate accepted quality certification date: {scheduled_date}")
        accepted_by_date[scheduled_date] = descriptor
    accepted = [accepted_by_date[value] for value in sorted(accepted_by_date)]
    return {
        "ledger_path": str(ledger_path),
        "ledger_exists": ledger_path.is_file(),
        "ledger_sha256": sha256_file(ledger_path) if ledger_path.is_file() else None,
        "certification_ids": certification_ids,
        "accepted_certifications": accepted,
        "accepted_distinct_dates": len(accepted),
    }


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("schedule_start_date must use YYYY-MM-DD") from exc


def _parse_time(value: str) -> time:
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("segment_start_local must use HH:MM") from exc
    if not (parsed.hour >= 23 or parsed.hour < 7):
        raise ValueError("segment_start_local must be inside the 23:00-07:00 night window")
    return parsed


def _night_deadline(start: datetime) -> datetime:
    deadline_date = start.date() + timedelta(days=1) if start.hour >= 23 else start.date()
    return datetime.combine(deadline_date, time(hour=7), tzinfo=VOLGOGRAD_TZ)


def _powershell_quote(value: str) -> str:
    return '"' + value.replace('"', '`"') + '"'


def _runtime_command(
    *,
    segment: dict[str, Any],
    visible_wrapper: Path,
    output_root: str,
    plan_path: Path,
    plan_hash: str,
    execution_config: dict[str, Any],
) -> str:
    return " ".join(
        (
            "pwsh -NoProfile -ExecutionPolicy Bypass -File",
            _powershell_quote(str(visible_wrapper)),
            f"-DurationSec {int(segment['duration_sec'])}",
            f"-IntervalSec {int(segment['interval_sec'])}",
            f"-TimeoutSec {int(execution_config['timeout_sec'])}",
            f"-MinContractsPerExchange {int(execution_config['min_contracts_per_exchange'])}",
            "-OutputRoot",
            _powershell_quote(output_root),
            f"-RunId {segment['run_id']}",
            f"-MinFreeDiskGiB {float(execution_config['min_free_disk_gib']):g}",
            "-ApprovedNotBefore",
            _powershell_quote(str(segment["start_local"])),
            "-ApprovedNotLaterThan",
            _powershell_quote(str(segment["hard_deadline_local"])),
            "-SchedulePlanPath",
            _powershell_quote(str(plan_path)),
            f"-ExpectedSchedulePlanHash {plan_hash}",
            "-ConfirmedPitUniverseSnapshotCollect",
        )
    )


def _validate_source_hash(path_value: Any, expected_hash: Any, label: str) -> None:
    if not path_value or not expected_hash:
        raise ValueError(f"{label} provenance is incomplete")
    target = Path(str(path_value)).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"{label} provenance file is missing: {target}")
    observed = sha256_file(target)
    if observed != str(expected_hash):
        raise ValueError(f"{label} provenance hash mismatch: expected={expected_hash}, observed={observed}")


def _validate_recorded_source(path_value: Any, expected_hash: Any, label: str) -> Path:
    if not path_value or not expected_hash:
        raise ValueError(f"{label} provenance is incomplete")
    target = Path(str(path_value)).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"{label} provenance file is missing: {target}")
    digest = str(expected_hash).strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{label} provenance hash is not SHA-256")
    return target


def _validate_runtime_tools(runtime_tools: Any) -> None:
    if not isinstance(runtime_tools, dict):
        raise ValueError("sealed runtime_tools are required")
    for tool_name in RUNTIME_TOOL_NAMES:
        tool = runtime_tools.get(tool_name)
        if not isinstance(tool, dict):
            raise ValueError(f"sealed runtime tool is missing: {tool_name}")
        label = f"runtime tool {tool_name}"
        _validate_recorded_source(tool.get("path"), tool.get("sha256"), label)
        if tool_name in COLLECTION_DATA_PLANE_TOOL_NAMES:
            _validate_source_hash(tool.get("path"), tool.get("sha256"), label)


def _build_collection_stage(
    *,
    stage_name: str,
    ledger_path: Path,
    hypothesis_id: str,
    data_type: str,
    contract: dict[str, Any],
    contract_hash: str,
    nights: int,
    first_date: date,
    train_plan_path: str | Path | None,
    feasibility_path: str | Path | None,
) -> dict[str, Any]:
    if stage_name not in COLLECTION_STAGES:
        raise ValueError(f"unsupported collection_stage: {stage_name}")
    state = _quality_state(
        ledger_path,
        hypothesis_id=hypothesis_id,
        data_type=data_type,
        contract_hash=contract_hash,
    )
    accepted = list(state["accepted_certifications"])
    accepted_count = int(state["accepted_distinct_dates"])
    if accepted and first_date <= _parse_date(str(accepted[-1]["scheduled_date"])):
        raise ValueError("schedule_start_date must be after every already accepted quality date")

    train_target = int(contract["sample_plan"]["train_eligibility_days"])
    full_target = int(contract["sample_plan"]["required_quality_dates"])
    upstream: dict[str, Any] | None = None
    if stage_name == TRAIN_ACCRUAL_STAGE:
        if train_plan_path or feasibility_path:
            raise ValueError("train_accrual must not bind train_plan_path or feasibility_path")
        if accepted_count >= train_target:
            raise ValueError("train feasibility gate has already been reached; more train accrual is forbidden")
        stage_target = train_target
    else:
        if not train_plan_path or not feasibility_path:
            raise ValueError("oos_accrual requires train_plan_path and feasibility_path")
        if accepted_count < train_target:
            raise ValueError(
                f"oos_accrual requires {train_target} accepted train dates, observed={accepted_count}"
            )
        evidence = _validate_train_feasibility_evidence(train_plan_path, feasibility_path)
        if evidence["hypothesis_id"] != hypothesis_id or evidence["data_type"] != data_type:
            raise ValueError("upstream train feasibility track mismatch")
        if evidence["hypothesis_contract_sha256"] != contract_hash:
            raise ValueError("upstream train feasibility contract mismatch")
        if int(evidence["train_dates"]) != train_target:
            raise ValueError("upstream train feasibility date count mismatch")
        upstream = evidence
        stage_target = full_target

    remaining = stage_target - accepted_count
    if remaining <= 0:
        raise ValueError(f"collection stage {stage_name} is already complete")
    if int(nights) > remaining:
        label = "accepted train" if stage_name == TRAIN_ACCRUAL_STAGE else "accepted total"
        raise ValueError(
            f"only {remaining} {label} dates remain before the {stage_name} gate; requested nights={nights}"
        )
    return {
        "name": stage_name,
        "quality_ledger": {
            "path": str(ledger_path),
            "existed_at_plan": bool(state["ledger_exists"]),
            "file_sha256_at_plan": state["ledger_sha256"],
            "initial_certification_ids": list(state["certification_ids"]),
            "initial_accepted_certifications": accepted,
        },
        "initial_accepted_distinct_dates": accepted_count,
        "train_feasibility_distinct_days": train_target,
        "required_distinct_days": full_target,
        "stage_target_distinct_dates": stage_target,
        "maximum_new_accepted_dates": remaining,
        "upstream_train_feasibility": upstream,
        "more_collection_requires_stage_authorization": True,
    }


def _validate_collection_stage(
    sealed: dict[str, Any],
    *,
    contract: dict[str, Any],
    contract_hash: str,
) -> dict[str, Any]:
    stage = sealed.get("collection_stage")
    if not isinstance(stage, dict):
        raise ValueError("sealed collection_stage is required")
    stage_name = str(stage.get("name") or "")
    if stage_name not in COLLECTION_STAGES:
        raise ValueError(f"unsupported sealed collection_stage: {stage_name}")
    ledger_info = stage.get("quality_ledger")
    if not isinstance(ledger_info, dict) or not ledger_info.get("path"):
        raise ValueError("collection_stage quality ledger provenance is required")
    ledger_path = Path(str(ledger_info["path"])).expanduser().resolve()
    state = _quality_state(
        ledger_path,
        hypothesis_id=str(sealed.get("hypothesis_id") or ""),
        data_type=str(sealed.get("data_type") or ""),
        contract_hash=contract_hash,
    )
    current_ids = set(str(value) for value in state["certification_ids"])
    initial_ids = [str(value) for value in ledger_info.get("initial_certification_ids") or []]
    if not set(initial_ids).issubset(current_ids):
        raise ValueError("quality ledger no longer contains every certification sealed at schedule planning")
    current_accepted_by_id = {
        str(item["certification_id"]): item for item in state["accepted_certifications"]
    }
    initial_accepted = ledger_info.get("initial_accepted_certifications")
    if not isinstance(initial_accepted, list):
        raise ValueError("initial accepted quality certifications must be a list")
    for descriptor in initial_accepted:
        if not isinstance(descriptor, dict):
            raise ValueError("initial accepted quality certification descriptor must be an object")
        certification_id = str(descriptor.get("certification_id") or "")
        if current_accepted_by_id.get(certification_id) != descriptor:
            raise ValueError("initial accepted quality certification changed or disappeared")
    initial_count = int(stage.get("initial_accepted_distinct_dates") or 0)
    if initial_count != len(initial_accepted):
        raise ValueError("collection_stage initial accepted date count mismatch")
    train_target = int(contract["sample_plan"]["train_eligibility_days"])
    full_target = int(contract["sample_plan"]["required_quality_dates"])
    expected_target = train_target if stage_name == TRAIN_ACCRUAL_STAGE else full_target
    if int(stage.get("train_feasibility_distinct_days") or 0) != train_target:
        raise ValueError("collection_stage train target mismatch")
    if int(stage.get("required_distinct_days") or 0) != full_target:
        raise ValueError("collection_stage full target mismatch")
    if int(stage.get("stage_target_distinct_dates") or 0) != expected_target:
        raise ValueError("collection_stage target mismatch")
    if int(stage.get("maximum_new_accepted_dates") or 0) != expected_target - initial_count:
        raise ValueError("collection_stage maximum new date count mismatch")
    if stage.get("more_collection_requires_stage_authorization") is not True:
        raise ValueError("collection_stage must require segment authorization")
    if stage_name == TRAIN_ACCRUAL_STAGE:
        if initial_count >= train_target:
            raise ValueError("train schedule was planned after the feasibility gate")
        if stage.get("upstream_train_feasibility") is not None:
            raise ValueError("train_accrual must not contain upstream OOS authorization")
    else:
        if initial_count < train_target or initial_count >= full_target:
            raise ValueError("oos schedule initial accepted date count is outside the OOS accrual window")
        upstream = stage.get("upstream_train_feasibility")
        if not isinstance(upstream, dict):
            raise ValueError("oos_accrual requires upstream train feasibility evidence")
        observed = _validate_train_feasibility_evidence(
            str(upstream.get("train_plan_path") or ""),
            str(upstream.get("feasibility_path") or ""),
        )
        if observed != upstream:
            raise ValueError("upstream train feasibility evidence changed after schedule planning")
        if observed["hypothesis_id"] != sealed.get("hypothesis_id"):
            raise ValueError("upstream train feasibility hypothesis mismatch")
        if observed["hypothesis_contract_sha256"] != contract_hash:
            raise ValueError("upstream train feasibility contract mismatch")
    segments = sealed.get("segments") or []
    if len(segments) > int(stage["maximum_new_accepted_dates"]):
        raise ValueError("schedule contains more segments than the sealed collection stage allows")
    return {
        "name": stage_name,
        "quality_ledger_path": str(ledger_path),
        "initial_accepted_distinct_dates": initial_count,
        "current_accepted_distinct_dates": int(state["accepted_distinct_dates"]),
        "stage_target_distinct_dates": expected_target,
        "remaining_stage_dates": max(0, expected_target - int(state["accepted_distinct_dates"])),
        "current_accepted_certifications": list(state["accepted_certifications"]),
    }


def validate_night_schedule_plan(
    plan_path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan = read_json(target)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError(f"Expected {PLAN_SCHEMA} PlanOnly artifact")
    plan_hash = str(plan.get("plan_hash") or "")
    if expected_plan_hash and plan_hash != expected_plan_hash:
        raise ValueError(f"Plan hash mismatch: expected={expected_plan_hash}, observed={plan_hash}")
    sealed = plan.get("sealed_schedule")
    if not isinstance(sealed, dict):
        raise ValueError("sealed_schedule is required")
    observed_hash = _json_hash(sealed)
    if observed_hash != plan_hash or plan.get("sealed_schedule_hash") != plan_hash:
        raise ValueError(f"Sealed schedule hash mismatch: expected={plan_hash}, observed={observed_hash}")

    artifact_path = Path(str(plan.get("plan_artifact_path") or "")).expanduser().resolve()
    if artifact_path != target:
        raise ValueError(f"Plan artifact path mismatch: sealed runtime path={artifact_path}, observed={target}")
    _validate_recorded_source(
        (plan.get("hypothesis_bank") or {}).get("path"),
        (plan.get("hypothesis_bank") or {}).get("sha256"),
        "hypothesis bank",
    )
    _validate_recorded_source(
        (plan.get("goal_document") or {}).get("path"),
        (plan.get("goal_document") or {}).get("sha256"),
        "canonical goal",
    )
    runtime_tools = sealed.get("runtime_tools")
    _validate_runtime_tools(runtime_tools)

    hypothesis_id = str(sealed.get("hypothesis_id") or "")
    data_type = str(sealed.get("data_type") or "")
    bank_path = (plan.get("hypothesis_bank") or {}).get("path")
    _bank, current_hypothesis = _load_hypothesis(str(bank_path), hypothesis_id)
    current_contract = current_hypothesis.get("contract")
    sealed_contract = sealed.get("hypothesis_contract")
    if not isinstance(sealed_contract, dict):
        raise ValueError("sealed hypothesis_contract is required")
    if current_contract != sealed_contract:
        raise ValueError("sealed hypothesis contract differs from the current hash-bound bank entry")
    contract_validation = validate_hypothesis_contract(
        sealed_contract,
        expected_id=hypothesis_id,
        expected_data_type=data_type,
    )
    if sealed.get("hypothesis_contract_sha256") != contract_validation["contract_hash"]:
        raise ValueError("sealed hypothesis_contract_sha256 mismatch")
    stage_validation = _validate_collection_stage(
        sealed,
        contract=sealed_contract,
        contract_hash=contract_validation["contract_hash"],
    )

    execution_config = sealed.get("execution_config")
    if not isinstance(execution_config, dict):
        raise ValueError("sealed execution_config is required")
    if int(execution_config.get("timeout_sec") or 0) <= 0:
        raise ValueError("execution_config.timeout_sec must be positive")
    if int(execution_config.get("min_contracts_per_exchange") or 0) <= 0:
        raise ValueError("execution_config.min_contracts_per_exchange must be positive")
    if float(execution_config.get("min_free_disk_gib") or -1) < 0:
        raise ValueError("execution_config.min_free_disk_gib must be non-negative")

    quality_policy = sealed.get("quality_policy")
    if not isinstance(quality_policy, dict):
        raise ValueError("sealed quality_policy is required")
    if quality_policy.get("policy_version") != QUALITY_POLICY_VERSION:
        raise ValueError("unsupported quality_policy.policy_version")
    if int(quality_policy.get("min_exchanges_per_cycle") or 0) < 2:
        raise ValueError("quality_policy.min_exchanges_per_cycle must be at least two")
    max_error_cycle_ratio = quality_policy.get("max_error_cycle_ratio")
    if max_error_cycle_ratio is None or float(max_error_cycle_ratio) < 0:
        raise ValueError("quality_policy.max_error_cycle_ratio must be non-negative")
    max_duplicate_snapshot_keys = quality_policy.get("max_duplicate_snapshot_keys")
    if max_duplicate_snapshot_keys is None or int(max_duplicate_snapshot_keys) < 0:
        raise ValueError("quality_policy.max_duplicate_snapshot_keys must be non-negative")
    bbo_coverage = quality_policy.get("minimum_dual_venue_bbo_size_coverage")
    if bbo_coverage is None or not 0.95 <= float(bbo_coverage) <= 1.0:
        raise ValueError("quality_policy.minimum_dual_venue_bbo_size_coverage must be in [0.95, 1]")
    for required_true in ("require_final", "require_positive_rows", "reject_any_thin_exchange_cycle"):
        if quality_policy.get(required_true) is not True:
            raise ValueError(f"quality_policy.{required_true} must be true")
    if int(quality_policy.get("max_clock_skew_sec") or 0) < 0:
        raise ValueError("quality_policy.max_clock_skew_sec must be non-negative")
    if int(quality_policy.get("required_distinct_days") or 0) <= 0:
        raise ValueError("quality_policy.required_distinct_days must be positive")
    if int(quality_policy["required_distinct_days"]) != int(contract_validation["required_quality_dates"]):
        raise ValueError("quality_policy.required_distinct_days must match the frozen hypothesis contract")
    if int(quality_policy.get("train_feasibility_distinct_days") or 0) != int(
        sealed_contract["sample_plan"]["train_eligibility_days"]
    ):
        raise ValueError("quality_policy.train_feasibility_distinct_days must match the frozen contract")
    if quality_policy.get("oos_accrual_requires_feasibility_pass") is not True:
        raise ValueError("quality_policy must stop OOS accrual until train feasibility passes")
    coverage_projection = sealed.get("coverage_projection")
    if not isinstance(coverage_projection, dict):
        raise ValueError("sealed coverage_projection is required")
    if int(coverage_projection.get("required_days") or 0) != int(contract_validation["required_quality_dates"]):
        raise ValueError("coverage_projection.required_days must match the frozen hypothesis contract")
    if int(coverage_projection.get("train_feasibility_required_days") or 0) != int(
        sealed_contract["sample_plan"]["train_eligibility_days"]
    ):
        raise ValueError("coverage_projection train gate must match the frozen hypothesis contract")
    if int(coverage_projection.get("existing_qualified_days_assumed") or 0) != int(
        stage_validation["initial_accepted_distinct_dates"]
    ):
        raise ValueError("coverage_projection initial accepted dates mismatch")
    if str(coverage_projection.get("collection_stage") or "") != stage_validation["name"]:
        raise ValueError("coverage_projection collection stage mismatch")

    sealed_segments = sealed.get("segments")
    runtime_segments = plan.get("segments")
    if not isinstance(sealed_segments, list) or not isinstance(runtime_segments, list):
        raise ValueError("sealed and runtime segments must be lists")
    if len(sealed_segments) != len(runtime_segments):
        raise ValueError("runtime segment count mismatch")
    for index, (sealed_segment, runtime_segment) in enumerate(zip(sealed_segments, runtime_segments, strict=True)):
        if not isinstance(sealed_segment, dict) or not isinstance(runtime_segment, dict):
            raise ValueError(f"segment {index + 1} must be an object")
        runtime_base = {key: value for key, value in runtime_segment.items() if key != "command_after_approval"}
        if runtime_base != sealed_segment:
            raise ValueError(f"runtime segment mismatch at sequence={index + 1}")
        command = str(runtime_segment.get("command_after_approval") or "")
        for required in (str(target), plan_hash, str(sealed_segment.get("run_id") or "")):
            if required not in command:
                raise ValueError(f"runtime command binding mismatch at sequence={index + 1}: missing {required}")

    for flag in ("schedule_approved", "collection_started", "network_access", "oos_returns_read", "pnl_or_returns_read"):
        if plan.get(flag) is not False:
            raise ValueError(f"{flag} must be false in PlanOnly schedule")
    return {
        "schema": PLAN_SCHEMA,
        "verdict": "VALID",
        "plan_path": str(target),
        "plan_hash": plan_hash,
        "plan_file_sha256": sha256_file(target),
        "segments": len(runtime_segments),
        "first_start_local": runtime_segments[0]["start_local"] if runtime_segments else None,
        "last_deadline_local": runtime_segments[-1]["hard_deadline_local"] if runtime_segments else None,
        "collection_stage": stage_validation["name"],
        "quality_ledger_path": stage_validation["quality_ledger_path"],
        "current_accepted_distinct_dates": stage_validation["current_accepted_distinct_dates"],
        "current_accepted_certifications": stage_validation["current_accepted_certifications"],
        "remaining_stage_dates": stage_validation["remaining_stage_dates"],
        "schedule_approved": False,
        "collection_started": False,
    }


def authorize_collection_segment(
    plan_path: str | Path,
    expected_plan_hash: str,
    run_id: str,
) -> dict[str, Any]:
    validation = validate_night_schedule_plan(plan_path, expected_plan_hash)
    target = Path(plan_path).expanduser().resolve()
    plan = read_json(target)
    sealed = plan["sealed_schedule"]
    stage = sealed["collection_stage"]
    stage_name = str(stage["name"])
    current_count = int(validation["current_accepted_distinct_dates"])
    target_count = int(stage["stage_target_distinct_dates"])
    if stage_name == TRAIN_ACCRUAL_STAGE and current_count >= target_count:
        raise ValueError("train feasibility gate has already been reached; more collection is forbidden")
    if stage_name == OOS_ACCRUAL_STAGE:
        train_target = int(stage["train_feasibility_distinct_days"])
        if current_count < train_target:
            raise ValueError("OOS collection lost its accepted train evidence")
        if current_count >= target_count:
            raise ValueError("full OOS quality-date target has already been reached")
    segments = [item for item in plan.get("segments") or [] if str(item.get("run_id") or "") == run_id]
    if len(segments) != 1:
        raise ValueError(f"expected exactly one segment for run_id={run_id}")
    segment = segments[0]
    scheduled_date = str(segment.get("start_local") or "")[:10]
    accepted_dates = {
        str(item["scheduled_date"])
        for item in validation.get("current_accepted_certifications") or []
    }
    if scheduled_date in accepted_dates:
        raise ValueError(f"segment scheduled date is already quality accepted: {scheduled_date}")
    return {
        "schema": PLAN_SCHEMA,
        "verdict": "AUTHORIZED",
        "plan_path": str(target),
        "plan_hash": expected_plan_hash,
        "run_id": run_id,
        "collection_stage": stage_name,
        "quality_ledger_path": validation["quality_ledger_path"],
        "accepted_distinct_dates_before_run": current_count,
        "remaining_stage_dates_before_run": target_count - current_count,
        "stage_target_distinct_dates": target_count,
        "oos_returns_read": False,
        "pnl_or_returns_read": False,
    }


def build_night_schedule_plan(
    *,
    hypothesis_bank_path: str | Path,
    hypothesis_id: str,
    data_type: str,
    goal_path: str | Path,
    output_path: str | Path,
    schedule_start_date: str,
    nights: int = MAX_SCHEDULE_NIGHTS,
    segment_start_local: str = "23:00",
    segment_duration_sec: int = 1_200,
    interval_sec: int = 300,
    output_root: str = r"E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2",
    collection_stage: str = TRAIN_ACCRUAL_STAGE,
    quality_ledger_path: str | Path | None = None,
    train_plan_path: str | Path | None = None,
    feasibility_path: str | Path | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    if not 1 <= int(nights) <= MAX_SCHEDULE_NIGHTS:
        raise ValueError(f"nights must be in [1, {MAX_SCHEDULE_NIGHTS}]")
    if not 1 <= int(segment_duration_sec) <= MAX_SEGMENT_RUNTIME_SEC:
        raise ValueError(f"segment_duration_sec must be in [1, {MAX_SEGMENT_RUNTIME_SEC}]")
    if not 1 <= int(interval_sec) <= int(segment_duration_sec):
        raise ValueError("interval_sec must be in [1, segment_duration_sec]")

    bank, hypothesis = _load_hypothesis(hypothesis_bank_path, hypothesis_id)
    required_data_type = str(hypothesis.get("required_data_type") or "")
    if required_data_type != data_type:
        raise ValueError(f"Hypothesis {hypothesis_id} requires data_type={required_data_type}, got {data_type}")
    if data_type != SUPPORTED_DATA_TYPE:
        raise ValueError(f"Night schedule v1 supports data_type={SUPPORTED_DATA_TYPE}, got {data_type}")
    hypothesis_contract = hypothesis.get("contract")
    if not isinstance(hypothesis_contract, dict):
        raise ValueError("Banked hypothesis must contain a full frozen contract")
    contract_validation = validate_hypothesis_contract(
        hypothesis_contract,
        expected_id=hypothesis_id,
        expected_data_type=data_type,
    )

    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"Refusing to overwrite immutable night schedule PlanOnly artifact: {target}")
    first_date = _parse_date(schedule_start_date)
    start_clock = _parse_time(segment_start_local)
    ledger_target = (
        Path(quality_ledger_path).expanduser().resolve()
        if quality_ledger_path
        else (Path(output_root).expanduser().resolve() / "quality-certifications.jsonl")
    )
    collection_stage_contract = _build_collection_stage(
        stage_name=collection_stage,
        ledger_path=ledger_target,
        hypothesis_id=hypothesis_id,
        data_type=data_type,
        contract=hypothesis_contract,
        contract_hash=contract_validation["contract_hash"],
        nights=int(nights),
        first_date=first_date,
        train_plan_path=train_plan_path,
        feasibility_path=feasibility_path,
    )
    bank_target = Path(hypothesis_bank_path).expanduser().resolve()
    goal_target = Path(goal_path).expanduser().resolve()
    project_root = Path(__file__).resolve().parents[2]
    schedule_planner = Path(__file__).resolve()
    visible_wrapper = project_root / "tools" / "start_pit_universe_snapshot_collect_visible.ps1"
    collector = project_root / "trading_mvp" / "src" / "pit_universe_snapshot_collector.py"
    public_probe_client = project_root / "trading_mvp" / "src" / "pit_universe_public_probe.py"
    approval_script = project_root / "tools" / "approve_trading_night_schedule.ps1"
    status_tool = project_root / "trading_mvp" / "src" / "night_schedule_status.py"
    quality_certifier = project_root / "trading_mvp" / "src" / "night_schedule_quality.py"
    segment_quality_evaluator = project_root / "trading_mvp" / "src" / "pit_universe_snapshot_quality.py"
    hypothesis_contract_validator = project_root / "trading_mvp" / "src" / "hypothesis_contract.py"
    costs_module = project_root / "trading_mvp" / "src" / "costs.py"
    feasibility_estimator = project_root / "trading_mvp" / "src" / "feasibility_gate.py"
    membership_drift_evaluator = project_root / "trading_mvp" / "src" / "pit_membership_drift_evaluator.py"
    runtime_tool_paths = {
        "schedule_planner": schedule_planner,
        "visible_wrapper": visible_wrapper,
        "collector": collector,
        "public_probe_client": public_probe_client,
        "approval_script": approval_script,
        "status_tool": status_tool,
        "quality_certifier": quality_certifier,
        "segment_quality_evaluator": segment_quality_evaluator,
        "hypothesis_contract_validator": hypothesis_contract_validator,
        "costs_module": costs_module,
        "feasibility_estimator": feasibility_estimator,
        "membership_drift_evaluator": membership_drift_evaluator,
    }
    for tool_name, tool_path in runtime_tool_paths.items():
        if not tool_path.is_file():
            raise ValueError(f"Required runtime tool is missing: {tool_name}={tool_path}")
    runtime_tools = {
        name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
        for name, path in runtime_tool_paths.items()
    }
    execution_config = {
        "timeout_sec": 10,
        "min_contracts_per_exchange": 50,
        "min_free_disk_gib": 5.0,
    }

    sealed_segments: list[dict[str, Any]] = []
    for index in range(int(nights)):
        local_date = first_date + timedelta(days=index)
        start = datetime.combine(local_date, start_clock, tzinfo=VOLGOGRAD_TZ)
        end = start + timedelta(seconds=int(segment_duration_sec))
        deadline = _night_deadline(start)
        if end > deadline:
            raise ValueError(
                f"Night segment starting {start.isoformat()} must finish by 07:00; "
                f"requested end={end.isoformat()}"
            )
        run_id = f"pit_universe_v2_forward_{local_date.strftime('%Y%m%d')}_n{index + 1:02d}"
        sealed_segments.append(
            {
                "sequence": index + 1,
                "run_id": run_id,
                "start_local": start.isoformat(),
                "end_local": end.isoformat(),
                "hard_deadline_local": deadline.isoformat(),
                "duration_sec": int(segment_duration_sec),
                "interval_sec": int(interval_sec),
                "expected_cycles_floor": max(1, int(segment_duration_sec) // int(interval_sec)),
                "output_dir": str(Path(output_root) / run_id),
                "visible_terminal_required": True,
                "end_before_night_deadline": end <= deadline,
            }
        )

    minimum_data = hypothesis.get("minimum_data") if isinstance(hypothesis.get("minimum_data"), dict) else {}
    required_days = int(contract_validation["required_quality_dates"])
    train_feasibility_days = int(hypothesis_contract["sample_plan"]["train_eligibility_days"])
    if int(minimum_data.get("days") or 0) != required_days:
        raise ValueError("Hypothesis minimum_data.days must match contract sample_plan.required_quality_dates")
    coverage_projection = {
        "collection_stage": collection_stage,
        "existing_qualified_days_assumed": int(
            collection_stage_contract["initial_accepted_distinct_dates"]
        ),
        "scheduled_unique_dates": int(nights),
        "required_days": required_days,
        "train_feasibility_required_days": train_feasibility_days,
        "train_feasibility_reached_by_this_schedule": (
            int(collection_stage_contract["initial_accepted_distinct_dates"]) + int(nights)
            >= train_feasibility_days
        ),
        "minimum_data_reached_by_this_schedule": (
            int(collection_stage_contract["initial_accepted_distinct_dates"]) + int(nights)
            >= required_days
        ),
        "note": (
            "Existing PIT runs are not counted until data-quality certification binds their hashes. "
            "Collection must pause at the train-feasibility gate before any OOS accrual."
        ),
    }
    quality_policy = {
        "policy_version": QUALITY_POLICY_VERSION,
        "min_exchanges_per_cycle": 2,
        "max_error_cycle_ratio": 0.05,
        "max_duplicate_snapshot_keys": 0,
        "minimum_dual_venue_bbo_size_coverage": 0.95,
        "require_final": True,
        "require_positive_rows": True,
        "reject_any_thin_exchange_cycle": True,
        "max_clock_skew_sec": 60,
        "required_distinct_days": required_days,
        "train_feasibility_distinct_days": train_feasibility_days,
        "oos_accrual_requires_feasibility_pass": True,
    }
    if required_days <= 0:
        raise ValueError("Hypothesis minimum_data.days must be positive for a night schedule")
    sealed_schedule = {
        "schema": PLAN_SCHEMA,
        "hypothesis_id": hypothesis_id,
        "data_type": data_type,
        "hypothesis_contract": hypothesis_contract,
        "hypothesis_contract_sha256": contract_validation["contract_hash"],
        "hypothesis_bank_sha256": sha256_file(bank_target),
        "goal_sha256": sha256_file(goal_target),
        "timezone": "Europe/Volgograd",
        "window_local": "23:00-07:00",
        "schedule_start_date": schedule_start_date,
        "nights": int(nights),
        "segment_start_local": segment_start_local,
        "segment_duration_sec": int(segment_duration_sec),
        "interval_sec": int(interval_sec),
        "output_root": output_root,
        "runtime_tools": runtime_tools,
        "execution_config": execution_config,
        "quality_policy": quality_policy,
        "collection_stage": collection_stage_contract,
        "segments": sealed_segments,
        "coverage_projection": coverage_projection,
    }
    plan_hash = _json_hash(sealed_schedule)
    runtime_segments = [
        {
            **segment,
            "command_after_approval": _runtime_command(
                segment=segment,
                visible_wrapper=visible_wrapper,
                output_root=output_root,
                plan_path=target,
                plan_hash=plan_hash,
                execution_config=execution_config,
            ),
        }
        for segment in sealed_segments
    ]
    created = created_at_utc or datetime.now(timezone.utc).isoformat()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "created_at_utc": created,
        "mode": "PlanOnly",
        "research_only": True,
        "plan_artifact_path": str(target),
        "plan_hash": plan_hash,
        "sealed_schedule_hash": plan_hash,
        "sealed_schedule": sealed_schedule,
        "schedule_approved": False,
        "collection_started": False,
        "network_access": False,
        "oos_returns_read": False,
        "pnl_or_returns_read": False,
        "grid_search": False,
        "retune": False,
        "paper_forward": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "collection_stage": collection_stage,
        "hypothesis": {
            "id": hypothesis_id,
            "status": str(hypothesis.get("status") or ""),
            "required_data_type": required_data_type,
            "minimum_data": minimum_data,
            "contract_hash": contract_validation["contract_hash"],
        },
        "hypothesis_bank": {
            "path": str(bank_target),
            "version": str(bank.get("version") or ""),
            "sha256": sealed_schedule["hypothesis_bank_sha256"],
        },
        "goal_document": {
            "path": str(goal_target),
            "sha256": sealed_schedule["goal_sha256"],
        },
        "timezone": sealed_schedule["timezone"],
        "night_window_local": sealed_schedule["window_local"],
        "approval_horizon_nights": int(nights),
        "output_root": output_root,
        "segments": runtime_segments,
        "coverage_projection": coverage_projection,
        "guards": {
            "active_run_gate_before_each_segment": True,
            "visible_terminal_only": True,
            "hard_deadline_0700_local": True,
            "max_segment_runtime_sec": MAX_SEGMENT_RUNTIME_SEC,
            "timeout_or_network_failure": "STOPPED_INCOMPLETE",
            "resume_requires_same_run_id_and_matching_hashes": True,
            "forward_returns_embargoed": True,
            "partial_output_is_not_accepted_evidence": True,
            "single_schedule_approval_bound_to_plan_hash": True,
            "collection_stage_authorization_before_each_segment": True,
        },
        "explicit_approval_required": True,
        "approval_phrase": (
            f"Подтверждаю ночное расписание trading_mvp plan_hash={plan_hash} на "
            f"{runtime_segments[0]['start_local']}..{runtime_segments[-1]['end_local']}, "
            f"data_type={data_type}, stage={collection_stage}, visible terminal, "
            "без grid/live/API keys."
        ),
        "next_allowed_action": "await_explicit_night_schedule_approval",
    }
    _write_json_atomic(target, plan)
    validation = validate_night_schedule_plan(target, plan_hash)
    return {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "decision": "AWAIT_EXPLICIT_SCHEDULE_APPROVAL",
        "output_path": str(target),
        "output_sha256": validation["plan_file_sha256"],
        "plan_hash": plan_hash,
        "hypothesis_id": hypothesis_id,
        "data_type": data_type,
        "collection_stage": collection_stage,
        "quality_ledger_path": str(ledger_target),
        "nights": int(nights),
        "segment_duration_sec": int(segment_duration_sec),
        "segments": runtime_segments,
        "sealed_schedule": sealed_schedule,
        "schedule_approved": False,
        "collection_started": False,
        "next_allowed_action": "await_explicit_night_schedule_approval",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate a Fast-First night schedule PlanOnly artifact")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Freeze a bounded PIT-universe night schedule proposal")
    build.add_argument("--hypothesis-bank", required=True)
    build.add_argument("--hypothesis-id", required=True)
    build.add_argument("--data-type", required=True)
    build.add_argument("--goal", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--schedule-start-date", required=True)
    build.add_argument("--nights", type=int, default=MAX_SCHEDULE_NIGHTS)
    build.add_argument("--segment-start-local", default="23:00")
    build.add_argument("--segment-duration-sec", type=int, default=1_200)
    build.add_argument("--interval-sec", type=int, default=300)
    build.add_argument("--output-root", default=r"E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2")
    build.add_argument("--collection-stage", choices=sorted(COLLECTION_STAGES), default=TRAIN_ACCRUAL_STAGE)
    build.add_argument("--quality-ledger")
    build.add_argument("--train-plan")
    build.add_argument("--feasibility")
    validate = subparsers.add_parser("validate", help="Validate schedule seal and current source hashes")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash", required=True)
    authorize = subparsers.add_parser("authorize-segment", help="Fail closed at train/OOS accrual gates")
    authorize.add_argument("--plan", required=True)
    authorize.add_argument("--expected-plan-hash", required=True)
    authorize.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        result = build_night_schedule_plan(
            hypothesis_bank_path=args.hypothesis_bank,
            hypothesis_id=args.hypothesis_id,
            data_type=args.data_type,
            goal_path=args.goal,
            output_path=args.output,
            schedule_start_date=args.schedule_start_date,
            nights=args.nights,
            segment_start_local=args.segment_start_local,
            segment_duration_sec=args.segment_duration_sec,
            interval_sec=args.interval_sec,
            output_root=args.output_root,
            collection_stage=args.collection_stage,
            quality_ledger_path=args.quality_ledger,
            train_plan_path=args.train_plan,
            feasibility_path=args.feasibility,
        )
    elif args.command == "validate":
        result = validate_night_schedule_plan(args.plan, args.expected_plan_hash)
    elif args.command == "authorize-segment":
        result = authorize_collection_segment(args.plan, args.expected_plan_hash, args.run_id)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
