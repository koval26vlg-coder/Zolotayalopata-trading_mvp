from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PLAN_SCHEMA = "trading_mvp_slow_liquidity_history_recollect_planonly_v1"
RECEIPT_SCHEMA = "trading_mvp_slow_liquidity_history_recollect_approval_v1"
POLICY_REBIND_SCHEMA = (
    "trading_mvp_slow_liquidity_history_recollect_policy_rebind_v1"
)
EXACT_QUALITY_CONTRACT_VERSION = "slow_liquidity_history_exact_v2"


@dataclass(frozen=True)
class ApprovalBundle:
    receipt: dict[str, Any]
    policy: dict[str, Any]
    gate: dict[str, Any]
    receipt_bytes: bytes


def canonical_json_hash(
    value: Mapping[str, Any], *, excluded_key: str | None = None
) -> str:
    payload = copy.deepcopy(dict(value))
    if excluded_key is not None:
        payload.pop(excluded_key, None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_file_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")


def _normalize_approval_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _require_sha256(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{label} must be a lowercase SHA256 value")
    return normalized


def _same_path(left: str | Path, right: str | Path) -> bool:
    return str(Path(left)).casefold() == str(Path(right)).casefold()


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def expected_approval_text(
    plan: Mapping[str, Any], *, plan_hash: str, plan_file_sha256: str
) -> str:
    request = plan.get("approval_request")
    if not isinstance(request, Mapping):
        raise ValueError("plan.approval_request is missing")
    template = str(request.get("exact_user_text_template") or "")
    if template.count("<PLAN_HASH>") != 1:
        raise ValueError("approval template must contain one <PLAN_HASH>")
    if template.count("<PLAN_FILE_SHA256>") != 1:
        raise ValueError(
            "approval template must contain one <PLAN_FILE_SHA256>"
        )
    return _normalize_approval_text(
        template.replace(
            "<PLAN_HASH>", _require_sha256(plan_hash, label="plan_hash")
        ).replace(
            "<PLAN_FILE_SHA256>",
            _require_sha256(plan_file_sha256, label="plan_file_sha256"),
        )
    )


def _validate_plan_contract(
    plan: Mapping[str, Any], *, plan_file_sha256: str
) -> tuple[str, str]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("plan schema mismatch")
    if plan.get("status") != "AWAIT_EXACT_HASH_BOUND_APPROVAL":
        raise ValueError("plan status mismatch")
    if bool(plan.get("actual_collection_allowed")):
        raise ValueError("plan must remain PlanOnly")
    plan_hash = _require_sha256(str(plan.get("plan_hash") or ""), label="plan_hash")
    if canonical_json_hash(plan, excluded_key="plan_hash") != plan_hash:
        raise ValueError("plan canonical hash mismatch")
    return plan_hash, _require_sha256(
        plan_file_sha256, label="plan_file_sha256"
    )


def build_approval_bundle(
    *,
    plan: Mapping[str, Any],
    plan_path: str | Path,
    plan_file_sha256: str,
    active_policy: Mapping[str, Any],
    active_gate: Mapping[str, Any],
    user_approval_text: str,
    approved_at_utc: str,
) -> ApprovalBundle:
    plan_hash, plan_file_sha256 = _validate_plan_contract(
        plan, plan_file_sha256=plan_file_sha256
    )
    expected_text = expected_approval_text(
        plan,
        plan_hash=plan_hash,
        plan_file_sha256=plan_file_sha256,
    )
    normalized_user_text = _normalize_approval_text(user_approval_text)
    if normalized_user_text != expected_text:
        raise ValueError("user approval text mismatch")

    guard_contract = plan.get("guard_contract")
    if not isinstance(guard_contract, Mapping):
        raise ValueError("plan.guard_contract is missing")
    if active_gate.get("status") != "READY_FOR_POSTPROCESS":
        raise ValueError("preapproval gate status mismatch")
    if active_gate.get("next_goal_decision") != guard_contract.get(
        "preapproval_decision"
    ):
        raise ValueError("preapproval gate decision mismatch")

    execution = plan.get("execution")
    universe = plan.get("universe")
    approval_receipt = plan.get("approval_receipt")
    if not isinstance(execution, Mapping):
        raise ValueError("plan.execution is missing")
    if not isinstance(universe, Mapping):
        raise ValueError("plan.universe is missing")
    if not isinstance(approval_receipt, Mapping):
        raise ValueError("plan.approval_receipt is missing")

    receipt_path = str(approval_receipt.get("path") or "")
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "APPROVED",
        "approval_type": "EXACT_HASH_BOUND_VISIBLE_PUBLIC_RECOLLECT",
        "approved_by": "user",
        "approved_at_utc": approved_at_utc,
        "user_approval_text": normalized_user_text,
        "user_approval_text_sha256": hashlib.sha256(
            normalized_user_text.encode("utf-8")
        ).hexdigest(),
        "plan_path": str(plan_path),
        "plan_file_sha256": plan_file_sha256,
        "plan_hash": plan_hash,
        "run_id": execution.get("run_id"),
        "bases": copy.deepcopy(list(universe.get("bases") or [])),
        "exchanges": copy.deepcopy(list(execution.get("exchanges") or [])),
        "timeframes": copy.deepcopy(list(execution.get("timeframes") or [])),
        "history_days": execution.get("history_days"),
        "max_runtime_sec": execution.get("max_runtime_sec"),
        "hard_output_cap_bytes": execution.get("hard_output_cap_bytes"),
        "maximum_http_attempts": execution.get("maximum_http_attempts"),
        "policy_rebind_status": guard_contract.get(
            "required_policy_rebind_status"
        ),
        "required_guard_decision": guard_contract.get(
            "required_decision_after_approval"
        ),
        "single_use": True,
        "stop_incomplete_retry_authorized": False,
        "official_identity_verification_authorized": False,
        "evaluator_or_oos_authorized": False,
        "paper_or_live_authorized": False,
        "private_api_or_real_capital_authorized": False,
        "forbidden": copy.deepcopy(list(plan.get("forbidden") or [])),
        "receipt_hash_method": "sha256_canonical_json_excluding_receipt_hash",
    }
    receipt["receipt_hash"] = canonical_json_hash(
        receipt, excluded_key="receipt_hash"
    )
    receipt_bytes = json_file_bytes(receipt)
    receipt_file_sha256 = hashlib.sha256(receipt_bytes).hexdigest()

    policy = copy.deepcopy(dict(active_policy))
    policy["slow_liquidity_history_recollect"] = {
        "schema": POLICY_REBIND_SCHEMA,
        "status": guard_contract.get("required_policy_rebind_status"),
        "run_id": execution.get("run_id"),
        "plan_path": str(plan_path),
        "plan_file_sha256": plan_file_sha256,
        "plan_hash": plan_hash,
        "approval_receipt_path": receipt_path,
        "approval_receipt_file_sha256": receipt_file_sha256,
        "approval_receipt_hash": receipt["receipt_hash"],
        "required_guard_decision": guard_contract.get(
            "required_decision_after_approval"
        ),
        "single_use": True,
        "stop_incomplete_retry_authorized": False,
        "actual_collection_allowed": True,
        "official_identity_verification_authorized": False,
        "evaluator_or_oos_authorized": False,
        "paper_or_live_authorized": False,
    }

    gate = copy.deepcopy(dict(active_gate))
    gate.update(
        {
            "next_goal_decision": guard_contract.get(
                "required_decision_after_approval"
            ),
            "next_goal_reason": (
                "Exact single-use public recollect approval is bound to the "
                "immutable plan, receipt, and active policy."
            ),
            "slow_liquidity_recollect_policy_rebind_status": guard_contract.get(
                "required_policy_rebind_status"
            ),
            "slow_liquidity_recollect_plan_path": str(plan_path),
            "slow_liquidity_recollect_plan_file_sha256": plan_file_sha256,
            "slow_liquidity_recollect_plan_hash": plan_hash,
            "slow_liquidity_recollect_approval_receipt_path": receipt_path,
            "slow_liquidity_recollect_approval_receipt_sha256": (
                receipt_file_sha256
            ),
            "slow_liquidity_recollect_approval_receipt_hash": receipt[
                "receipt_hash"
            ],
            "requires_explicit_user_approval_for_actual_collect": False,
            "replay_allowed": False,
            "grid_allowed": False,
            "paper_forward_allowed": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
            "stopped_incomplete_retry_authorized": False,
        }
    )
    return ApprovalBundle(
        receipt=receipt,
        policy=policy,
        gate=gate,
        receipt_bytes=receipt_bytes,
    )


def validate_approval_bundle(
    *,
    plan: Mapping[str, Any],
    plan_path: str | Path,
    plan_file_sha256: str,
    receipt: Mapping[str, Any],
    receipt_path: str | Path,
    receipt_file_sha256: str,
    policy: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    try:
        plan_hash, normalized_plan_file_sha256 = _validate_plan_contract(
            plan, plan_file_sha256=plan_file_sha256
        )
    except ValueError as exc:
        return [str(exc).replace(" ", "_")]

    normalized_receipt_file_sha256 = _require_sha256(
        receipt_file_sha256, label="receipt_file_sha256"
    )
    guard_contract = plan.get("guard_contract")
    execution = plan.get("execution")
    universe = plan.get("universe")
    expected_receipt_path = str(
        (plan.get("approval_receipt") or {}).get("path") or ""
    )
    assert isinstance(guard_contract, Mapping)
    assert isinstance(execution, Mapping)
    assert isinstance(universe, Mapping)

    if receipt.get("schema") != RECEIPT_SCHEMA:
        errors.append("receipt_schema_mismatch")
    if receipt.get("status") != "APPROVED":
        errors.append("receipt_status_mismatch")
    if receipt.get("approval_type") != "EXACT_HASH_BOUND_VISIBLE_PUBLIC_RECOLLECT":
        errors.append("receipt_approval_type_mismatch")
    if not _same_path(str(receipt.get("plan_path") or ""), plan_path):
        errors.append("receipt_plan_path_mismatch")
    if receipt.get("plan_file_sha256") != normalized_plan_file_sha256:
        errors.append("receipt_plan_file_sha256_mismatch")
    if receipt.get("plan_hash") != plan_hash:
        errors.append("receipt_plan_hash_mismatch")
    if receipt.get("run_id") != execution.get("run_id"):
        errors.append("receipt_run_id_mismatch")
    if list(receipt.get("bases") or []) != list(universe.get("bases") or []):
        errors.append("receipt_bases_mismatch")
    if list(receipt.get("exchanges") or []) != list(
        execution.get("exchanges") or []
    ):
        errors.append("receipt_exchanges_mismatch")
    if list(receipt.get("timeframes") or []) != list(
        execution.get("timeframes") or []
    ):
        errors.append("receipt_timeframes_mismatch")
    for key in (
        "history_days",
        "max_runtime_sec",
        "hard_output_cap_bytes",
        "maximum_http_attempts",
    ):
        if receipt.get(key) != execution.get(key):
            errors.append(f"receipt_{key}_mismatch")
    if receipt.get("policy_rebind_status") != guard_contract.get(
        "required_policy_rebind_status"
    ):
        errors.append("receipt_policy_rebind_status_mismatch")
    if receipt.get("required_guard_decision") != guard_contract.get(
        "required_decision_after_approval"
    ):
        errors.append("receipt_guard_decision_mismatch")
    if receipt.get("single_use") is not True:
        errors.append("receipt_not_single_use")
    if receipt.get("stop_incomplete_retry_authorized") is not False:
        errors.append("receipt_retry_authorized")
    for key in (
        "official_identity_verification_authorized",
        "evaluator_or_oos_authorized",
        "paper_or_live_authorized",
        "private_api_or_real_capital_authorized",
    ):
        if receipt.get(key) is not False:
            errors.append(f"receipt_{key}")
    expected_text = expected_approval_text(
        plan,
        plan_hash=plan_hash,
        plan_file_sha256=normalized_plan_file_sha256,
    )
    if _normalize_approval_text(str(receipt.get("user_approval_text") or "")) != expected_text:
        errors.append("receipt_user_approval_text_mismatch")
    if receipt.get("user_approval_text_sha256") != hashlib.sha256(
        expected_text.encode("utf-8")
    ).hexdigest():
        errors.append("receipt_user_approval_text_sha256_mismatch")
    if receipt.get("receipt_hash") != canonical_json_hash(
        receipt, excluded_key="receipt_hash"
    ):
        errors.append("receipt_canonical_hash_mismatch")
    if not _same_path(receipt_path, expected_receipt_path):
        errors.append("receipt_path_mismatch")

    rebind = policy.get("slow_liquidity_history_recollect")
    if not isinstance(rebind, Mapping):
        errors.append("policy_rebind_missing")
    else:
        expected_rebind = {
            "schema": POLICY_REBIND_SCHEMA,
            "status": guard_contract.get("required_policy_rebind_status"),
            "run_id": execution.get("run_id"),
            "plan_path": str(plan_path),
            "plan_file_sha256": normalized_plan_file_sha256,
            "plan_hash": plan_hash,
            "approval_receipt_path": expected_receipt_path,
            "approval_receipt_file_sha256": normalized_receipt_file_sha256,
            "approval_receipt_hash": receipt.get("receipt_hash"),
            "required_guard_decision": guard_contract.get(
                "required_decision_after_approval"
            ),
            "single_use": True,
            "stop_incomplete_retry_authorized": False,
            "actual_collection_allowed": True,
            "official_identity_verification_authorized": False,
            "evaluator_or_oos_authorized": False,
            "paper_or_live_authorized": False,
        }
        for key, expected in expected_rebind.items():
            actual = rebind.get(key)
            if key.endswith("_path"):
                if not _same_path(str(actual or ""), str(expected or "")):
                    errors.append(f"policy_{key}_mismatch")
            elif actual != expected:
                errors.append(f"policy_{key}_mismatch")

    gate_expectations = {
        "next_goal_decision": guard_contract.get(
            "required_decision_after_approval"
        ),
        "slow_liquidity_recollect_policy_rebind_status": guard_contract.get(
            "required_policy_rebind_status"
        ),
        "slow_liquidity_recollect_plan_file_sha256": normalized_plan_file_sha256,
        "slow_liquidity_recollect_plan_hash": plan_hash,
        "slow_liquidity_recollect_approval_receipt_sha256": (
            normalized_receipt_file_sha256
        ),
        "slow_liquidity_recollect_approval_receipt_hash": receipt.get(
            "receipt_hash"
        ),
        "requires_explicit_user_approval_for_actual_collect": False,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "stopped_incomplete_retry_authorized": False,
    }
    for key, expected in gate_expectations.items():
        if gate.get(key) != expected:
            label = {
                "slow_liquidity_recollect_approval_receipt_sha256": (
                    "gate_receipt_sha256_mismatch"
                )
            }.get(key, f"gate_{key}_mismatch")
            errors.append(label)
    for key, expected in {
        "slow_liquidity_recollect_plan_path": str(plan_path),
        "slow_liquidity_recollect_approval_receipt_path": expected_receipt_path,
    }.items():
        if not _same_path(str(gate.get(key) or ""), expected):
            errors.append(f"gate_{key}_mismatch")
    return errors


def validate_postcollect_quality_context(
    *,
    plan: Mapping[str, Any],
    plan_path: str | Path,
    plan_file_sha256: str,
    receipt: Mapping[str, Any],
    receipt_path: str | Path,
    receipt_file_sha256: str,
    policy: Mapping[str, Any],
    gate: Mapping[str, Any],
    launch_record: Mapping[str, Any],
    launch_record_path: str | Path,
    manifest: Mapping[str, Any],
    manifest_path: str | Path,
    manifest_file_sha256: str,
    output_path: str | Path,
    output_file_sha256: str,
) -> list[str]:
    """Validate the immutable completed recollect before technical quality."""
    errors: list[str] = []
    try:
        plan_hash, normalized_plan_file_sha256 = _validate_plan_contract(
            plan, plan_file_sha256=plan_file_sha256
        )
        normalized_receipt_file_sha256 = _require_sha256(
            receipt_file_sha256, label="receipt_file_sha256"
        )
        normalized_manifest_file_sha256 = _require_sha256(
            manifest_file_sha256, label="manifest_file_sha256"
        )
        normalized_output_file_sha256 = _require_sha256(
            output_file_sha256, label="output_file_sha256"
        )
    except ValueError as exc:
        return [str(exc).replace(" ", "_")]

    execution = plan.get("execution")
    universe = plan.get("universe")
    guard_contract = plan.get("guard_contract")
    if not isinstance(execution, Mapping):
        return ["plan_execution_missing"]
    if not isinstance(universe, Mapping):
        return ["plan_universe_missing"]
    if not isinstance(guard_contract, Mapping):
        return ["plan_guard_contract_missing"]

    # Collection changes only the gate decision. Validate the original approval
    # binding against an otherwise identical view of the current gate.
    approval_gate = copy.deepcopy(dict(gate))
    approval_gate["next_goal_decision"] = guard_contract.get(
        "required_decision_after_approval"
    )
    errors.extend(
        validate_approval_bundle(
            plan=plan,
            plan_path=plan_path,
            plan_file_sha256=normalized_plan_file_sha256,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_file_sha256=normalized_receipt_file_sha256,
            policy=policy,
            gate=approval_gate,
        )
    )

    run_id = execution.get("run_id")
    expected_manifest_path = str(execution.get("manifest_path") or "")
    expected_output_path = str(execution.get("output_jsonl") or "")
    expected_launch_record_path = str(execution.get("launch_record_path") or "")
    expected_universe_path = str(universe.get("path") or "")
    expected_receipt_path = str(
        (plan.get("approval_receipt") or {}).get("path") or ""
    )

    gate_expectations = {
        "status": "READY_FOR_POSTPROCESS",
        "run_id": run_id,
        "final": True,
        "next_goal_decision": (
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
        ),
        "plan_hash": plan_hash,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "stopped_incomplete_retry_authorized": False,
    }
    for key, expected in gate_expectations.items():
        if gate.get(key) != expected:
            errors.append(f"quality_gate_{key}_mismatch")
    for key, expected in {
        "plan_path": str(plan_path),
        "manifest_path": expected_manifest_path,
        "output_path": expected_output_path,
    }.items():
        if not _same_path(str(gate.get(key) or ""), expected):
            errors.append(f"quality_gate_{key}_mismatch")

    launch_expectations = {
        "schema": "trading_mvp_slow_liquidity_recollect_launch_v1",
        "status": "COMPLETE",
        "run_id": run_id,
        "terminal_ownership_verified": True,
        "plan_file_sha256": normalized_plan_file_sha256,
        "plan_hash": plan_hash,
        "approval_receipt_sha256": normalized_receipt_file_sha256,
        "manifest_sha256": normalized_manifest_file_sha256,
        "output_jsonl_sha256": normalized_output_file_sha256,
        "retry_authorized": False,
    }
    for key, expected in launch_expectations.items():
        if launch_record.get(key) != expected:
            label = {
                "manifest_sha256": "quality_manifest_sha256_mismatch",
                "output_jsonl_sha256": "quality_output_sha256_mismatch",
            }.get(key, f"quality_launch_{key}_mismatch")
            errors.append(label)
    for key, expected in {
        "plan_path": str(plan_path),
        "approval_receipt_path": expected_receipt_path,
        "output_path": str(execution.get("output_path") or ""),
        "output_jsonl": expected_output_path,
        "manifest_path": expected_manifest_path,
    }.items():
        if not _same_path(str(launch_record.get(key) or ""), expected):
            errors.append(f"quality_launch_{key}_mismatch")
    if not _same_path(launch_record_path, expected_launch_record_path):
        errors.append("quality_launch_record_path_argument_mismatch")

    manifest_expectations = {
        "mode": "slow_liquidity_history_collect",
        "quality_contract_version": EXACT_QUALITY_CONTRACT_VERSION,
        "run_id": run_id,
        "final": True,
        "decision": (
            "SLOW_LIQUIDITY_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
        ),
        "history_days": execution.get("history_days"),
        "candles_per_request": execution.get("candles_per_request"),
        "selected_bases": list(universe.get("bases") or []),
        "quote": str(universe.get("quote") or ""),
        "exchanges": list(execution.get("exchanges") or []),
        "granularities": list(execution.get("timeframes") or []),
    }
    for key, expected in manifest_expectations.items():
        if manifest.get(key) != expected:
            label = {
                "selected_bases": "quality_manifest_bases_mismatch",
                "granularities": "quality_manifest_timeframes_mismatch",
            }.get(key, f"quality_manifest_{key}_mismatch")
            errors.append(label)
    for key, expected in {
        "universe_path": expected_universe_path,
        "output_jsonl": expected_output_path,
        "manifest_path": expected_manifest_path,
    }.items():
        if not _same_path(str(manifest.get(key) or ""), expected):
            errors.append(f"quality_manifest_{key}_mismatch")

    expected_jobs = (
        len(list(universe.get("bases") or []))
        * len(list(execution.get("exchanges") or []))
        * len(list(execution.get("timeframes") or []))
    )
    if manifest.get("planned_market_granularity_requests") != expected_jobs:
        errors.append("quality_manifest_planned_requests_mismatch")
    if manifest.get("completed_market_granularity_requests") != expected_jobs:
        errors.append("quality_manifest_completed_requests_mismatch")

    history_anchor_ts = manifest.get("history_anchor_ts")
    history_anchor_iso = str(manifest.get("history_anchor_iso") or "")
    if isinstance(history_anchor_ts, bool) or not isinstance(history_anchor_ts, int):
        errors.append("quality_manifest_history_anchor_ts_invalid")
        history_anchor = None
    else:
        try:
            history_anchor = datetime.fromtimestamp(
                history_anchor_ts, timezone.utc
            )
        except (OverflowError, OSError, ValueError):
            history_anchor = None
            errors.append("quality_manifest_history_anchor_ts_invalid")
    parsed_anchor_iso = _parse_utc_datetime(history_anchor_iso)
    if history_anchor is None or parsed_anchor_iso != history_anchor:
        errors.append("quality_manifest_history_anchor_iso_mismatch")

    launch_started = _parse_utc_datetime(launch_record.get("started_at_utc"))
    launch_finished = _parse_utc_datetime(launch_record.get("finished_at_utc"))
    manifest_started = _parse_utc_datetime(manifest.get("started_at"))
    manifest_finished = _parse_utc_datetime(manifest.get("finished_at"))
    timestamps = (
        launch_started,
        history_anchor,
        manifest_started,
        manifest_finished,
        launch_finished,
    )
    if any(value is None for value in timestamps):
        errors.append("quality_collection_timestamps_invalid")
    else:
        assert all(value is not None for value in timestamps)
        if not (
            launch_started
            <= history_anchor
            <= manifest_started
            <= manifest_finished
            <= launch_finished
        ):
            errors.append("quality_collection_time_chain_invalid")
        if (manifest_started - history_anchor).total_seconds() > 60:
            errors.append("quality_manifest_history_anchor_too_old")
    try:
        http_requests = int(manifest.get("http_requests"))
        request_cap = int(execution.get("logical_requests"))
        if http_requests < 0 or http_requests > request_cap:
            errors.append("quality_manifest_http_requests_out_of_bounds")
    except (TypeError, ValueError):
        errors.append("quality_manifest_http_requests_invalid")

    if not _same_path(manifest_path, expected_manifest_path):
        errors.append("quality_manifest_path_argument_mismatch")
    if not _same_path(output_path, expected_output_path):
        errors.append("quality_output_path_argument_mismatch")
    return sorted(set(errors))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()


def _render_command(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    plan_path = args.plan.resolve()
    policy_path = args.policy.resolve()
    gate_path = args.gate.resolve()
    expected_plan_file_sha256 = _require_sha256(
        args.expected_plan_file_sha256,
        label="expected_plan_file_sha256",
    )
    if _file_sha256(plan_path) != expected_plan_file_sha256:
        raise ValueError("plan file SHA256 mismatch")
    plan = _load_json(plan_path)
    expected_plan_hash = _require_sha256(
        args.expected_plan_hash, label="expected_plan_hash"
    )
    if plan.get("plan_hash") != expected_plan_hash:
        raise ValueError("plan hash mismatch")
    bundle = build_approval_bundle(
        plan=plan,
        plan_path=plan_path,
        plan_file_sha256=expected_plan_file_sha256,
        active_policy=_load_json(policy_path),
        active_gate=_load_json(gate_path),
        user_approval_text=args.user_approval_text_file.read_text(
            encoding="utf-8-sig"
        ),
        approved_at_utc=args.approved_at_utc,
    )
    receipt_output = args.receipt_output.resolve()
    policy_output = args.policy_output.resolve()
    gate_output = args.gate_output.resolve()
    policy_bytes = json_file_bytes(bundle.policy)
    gate_bytes = json_file_bytes(bundle.gate)
    _write_new(receipt_output, bundle.receipt_bytes)
    _write_new(policy_output, policy_bytes)
    _write_new(gate_output, gate_bytes)
    return 0, {
        "schema": "trading_mvp_slow_liquidity_recollect_control_plane_render_v1",
        "status": "CANDIDATE_BUNDLE_RENDERED",
        "plan_path": str(plan_path),
        "plan_file_sha256": expected_plan_file_sha256,
        "plan_hash": expected_plan_hash,
        "logical_receipt_path": str(
            (plan.get("approval_receipt") or {}).get("path") or ""
        ),
        "receipt_output": str(receipt_output),
        "receipt_file_sha256": hashlib.sha256(bundle.receipt_bytes).hexdigest(),
        "receipt_hash": bundle.receipt["receipt_hash"],
        "policy_output": str(policy_output),
        "policy_file_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "gate_output": str(gate_output),
        "gate_file_sha256": hashlib.sha256(gate_bytes).hexdigest(),
        "active_policy_mutated": False,
        "active_gate_mutated": False,
    }


def _validate_command(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    plan_path = args.plan.resolve()
    receipt_path = args.receipt.resolve()
    policy_path = args.policy.resolve()
    gate_path = args.gate.resolve()
    expected_plan_file_sha256 = _require_sha256(
        args.expected_plan_file_sha256,
        label="expected_plan_file_sha256",
    )
    expected_receipt_file_sha256 = _require_sha256(
        args.expected_receipt_file_sha256,
        label="expected_receipt_file_sha256",
    )
    if _file_sha256(plan_path) != expected_plan_file_sha256:
        raise ValueError("plan file SHA256 mismatch")
    if _file_sha256(receipt_path) != expected_receipt_file_sha256:
        raise ValueError("receipt file SHA256 mismatch")
    plan = _load_json(plan_path)
    expected_plan_hash = _require_sha256(
        args.expected_plan_hash, label="expected_plan_hash"
    )
    if plan.get("plan_hash") != expected_plan_hash:
        raise ValueError("plan hash mismatch")
    logical_receipt_path = (
        args.logical_receipt_path
        if args.logical_receipt_path is not None
        else receipt_path
    )
    errors = validate_approval_bundle(
        plan=plan,
        plan_path=plan_path,
        plan_file_sha256=expected_plan_file_sha256,
        receipt=_load_json(receipt_path),
        receipt_path=logical_receipt_path,
        receipt_file_sha256=expected_receipt_file_sha256,
        policy=_load_json(policy_path),
        gate=_load_json(gate_path),
    )
    return (0 if not errors else 2), {
        "schema": "trading_mvp_slow_liquidity_recollect_control_plane_validation_v1",
        "status": "VALID" if not errors else "INVALID",
        "plan_path": str(plan_path),
        "plan_file_sha256": expected_plan_file_sha256,
        "plan_hash": expected_plan_hash,
        "receipt_path": str(receipt_path),
        "logical_receipt_path": str(logical_receipt_path),
        "receipt_file_sha256": expected_receipt_file_sha256,
        "policy_path": str(policy_path),
        "policy_file_sha256": _file_sha256(policy_path),
        "gate_path": str(gate_path),
        "gate_file_sha256": _file_sha256(gate_path),
        "errors": errors,
    }


def _validate_quality_command(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    plan_path = args.plan.resolve()
    receipt_path = args.receipt.resolve()
    policy_path = args.policy.resolve()
    gate_path = args.gate.resolve()
    launch_record_path = args.launch_record.resolve()
    manifest_path = args.manifest.resolve()
    output_path = args.output_jsonl.resolve()
    expected_plan_file_sha256 = _require_sha256(
        args.expected_plan_file_sha256, label="expected_plan_file_sha256"
    )
    expected_receipt_file_sha256 = _require_sha256(
        args.expected_receipt_file_sha256, label="expected_receipt_file_sha256"
    )
    expected_manifest_file_sha256 = _require_sha256(
        args.expected_manifest_file_sha256, label="expected_manifest_file_sha256"
    )
    expected_output_file_sha256 = _require_sha256(
        args.expected_output_file_sha256, label="expected_output_file_sha256"
    )
    for path, expected, label in (
        (plan_path, expected_plan_file_sha256, "plan"),
        (receipt_path, expected_receipt_file_sha256, "receipt"),
        (manifest_path, expected_manifest_file_sha256, "manifest"),
        (output_path, expected_output_file_sha256, "output"),
    ):
        if _file_sha256(path) != expected:
            raise ValueError(f"{label} file SHA256 mismatch")
    plan = _load_json(plan_path)
    expected_plan_hash = _require_sha256(
        args.expected_plan_hash, label="expected_plan_hash"
    )
    if plan.get("plan_hash") != expected_plan_hash:
        raise ValueError("plan hash mismatch")
    logical_receipt_path = (
        args.logical_receipt_path
        if args.logical_receipt_path is not None
        else receipt_path
    )
    errors = validate_postcollect_quality_context(
        plan=plan,
        plan_path=plan_path,
        plan_file_sha256=expected_plan_file_sha256,
        receipt=_load_json(receipt_path),
        receipt_path=logical_receipt_path,
        receipt_file_sha256=expected_receipt_file_sha256,
        policy=_load_json(policy_path),
        gate=_load_json(gate_path),
        launch_record=_load_json(launch_record_path),
        launch_record_path=launch_record_path,
        manifest=_load_json(manifest_path),
        manifest_path=manifest_path,
        manifest_file_sha256=expected_manifest_file_sha256,
        output_path=output_path,
        output_file_sha256=expected_output_file_sha256,
    )
    return (0 if not errors else 2), {
        "schema": "trading_mvp_slow_liquidity_recollect_quality_context_v1",
        "status": "VALID" if not errors else "INVALID",
        "plan_path": str(plan_path),
        "plan_file_sha256": expected_plan_file_sha256,
        "plan_hash": expected_plan_hash,
        "receipt_path": str(receipt_path),
        "receipt_file_sha256": expected_receipt_file_sha256,
        "policy_path": str(policy_path),
        "policy_file_sha256": _file_sha256(policy_path),
        "gate_path": str(gate_path),
        "gate_file_sha256": _file_sha256(gate_path),
        "launch_record_path": str(launch_record_path),
        "launch_record_file_sha256": _file_sha256(launch_record_path),
        "manifest_path": str(manifest_path),
        "manifest_file_sha256": expected_manifest_file_sha256,
        "output_path": str(output_path),
        "output_file_sha256": expected_output_file_sha256,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render and validate the exact slow-liquidity recollect approval "
            "control plane without network access."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--plan", type=Path, required=True)
    render.add_argument("--expected-plan-file-sha256", required=True)
    render.add_argument("--expected-plan-hash", required=True)
    render.add_argument("--policy", type=Path, required=True)
    render.add_argument("--gate", type=Path, required=True)
    render.add_argument("--user-approval-text-file", type=Path, required=True)
    render.add_argument("--receipt-output", type=Path, required=True)
    render.add_argument("--policy-output", type=Path, required=True)
    render.add_argument("--gate-output", type=Path, required=True)
    render.add_argument("--approved-at-utc", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--expected-plan-file-sha256", required=True)
    validate.add_argument("--expected-plan-hash", required=True)
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--logical-receipt-path", type=Path)
    validate.add_argument("--expected-receipt-file-sha256", required=True)
    validate.add_argument("--policy", type=Path, required=True)
    validate.add_argument("--gate", type=Path, required=True)

    quality = subparsers.add_parser("validate-quality")
    quality.add_argument("--plan", type=Path, required=True)
    quality.add_argument("--expected-plan-file-sha256", required=True)
    quality.add_argument("--expected-plan-hash", required=True)
    quality.add_argument("--receipt", type=Path, required=True)
    quality.add_argument("--logical-receipt-path", type=Path)
    quality.add_argument("--expected-receipt-file-sha256", required=True)
    quality.add_argument("--policy", type=Path, required=True)
    quality.add_argument("--gate", type=Path, required=True)
    quality.add_argument("--launch-record", type=Path, required=True)
    quality.add_argument("--manifest", type=Path, required=True)
    quality.add_argument("--expected-manifest-file-sha256", required=True)
    quality.add_argument("--output-jsonl", type=Path, required=True)
    quality.add_argument("--expected-output-file-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "render":
            exit_code, result = _render_command(args)
        elif args.command == "validate":
            exit_code, result = _validate_command(args)
        else:
            exit_code, result = _validate_quality_command(args)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        exit_code = 2
        result = {
            "schema": "trading_mvp_slow_liquidity_recollect_control_plane_error_v1",
            "status": "INVALID",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
