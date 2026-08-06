from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from feasibility_gate import sha256_file
from pit_membership_drift_evaluator import (
    _certification_descriptor,
    _load_cycle_groups,
    _load_quality_ledger,
    _profit_factor,
    _serialise_result,
    _verify_certification_artifacts,
    detect_activation_events_by_daily_segments,
    simulate_event,
    validate_evaluation_input_plan,
)
from pit_membership_drift_execution_probe import (
    EVALUATION_OUTPUT_SCHEMA,
    _artifact_result_hash as execution_result_hash,
    validate_execution_probe_plan,
)


PLAN_SCHEMA = "pit_membership_drift_paper_forward_plan_v1"
PLAN_DECISION = "PIT_PAPER_FORWARD_PLAN_READY_REQUIRES_EXPLICIT_APPROVAL"
APPROVAL_SCHEMA = "pit_membership_drift_paper_forward_approval_v1"
STATE_SCHEMA = "pit_membership_drift_paper_forward_state_v1"


def build_paper_forward_plan(
    execution_evaluation_path: str | Path,
    output_path: str | Path,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    execution_target = Path(execution_evaluation_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"paper-forward plan already exists: {target}")
    execution, execution_plan = _validate_paper_ready_execution(execution_target)

    source = execution_plan["source"]
    full_plan_target = Path(str(source["full_plan_path"])).expanduser().resolve()
    full_validation = validate_evaluation_input_plan(full_plan_target, str(source["full_plan_hash"]))
    if full_validation["plan_stage"] != "full_evaluation":
        raise ValueError("paper-forward source must be a full historical evaluation plan")
    full_plan = _read_json(full_plan_target)
    sealed = full_plan["sealed_input"]
    descriptors = list(sealed["selected_certifications"])
    if len(descriptors) != 120:
        raise ValueError("paper-forward requires exactly 120 sealed historical dates")
    historical_dates = [str(item["scheduled_date"]) for item in descriptors]
    last_historical_date = date.fromisoformat(historical_dates[-1])
    paper_start_date = (last_historical_date + timedelta(days=1)).isoformat()

    ledger_target = Path(str(sealed["quality_ledger"]["path"])).expanduser().resolve()
    ledger_bytes = ledger_target.read_bytes()
    if ledger_bytes and not ledger_bytes.endswith(b"\n"):
        raise ValueError("quality ledger prefix must end with a newline before paper accrual")
    entries = _load_quality_ledger(ledger_target)
    if ledger_target.read_bytes() != ledger_bytes:
        raise ValueError("quality ledger changed during paper-forward plan creation")
    matching_entries = [
        entry
        for entry in entries
        if entry.get("hypothesis_id") == sealed["hypothesis_id"]
        and entry.get("data_type") == sealed["data_type"]
        and entry.get("hypothesis_contract_sha256") == sealed["hypothesis_contract_sha256"]
    ]
    if any(
        date.fromisoformat(str(entry["scheduled_date"])) >= date.fromisoformat(paper_start_date)
        for entry in matching_entries
    ):
        raise ValueError("paper-forward PlanOnly must be frozen before any paper-date accrual")
    matching_accepted = [
        entry for entry in matching_entries if entry.get("technical_quality_accepted") is True
    ]
    accepted_dates = sorted(str(entry["scheduled_date"]) for entry in matching_accepted)
    if accepted_dates != historical_dates:
        raise ValueError("paper-forward PlanOnly must be frozen before any paper-date accrual")

    module_path = Path(__file__).resolve()
    membership_evaluator_path = module_path.with_name("pit_membership_drift_evaluator.py")
    sealed_paper = {
        "hypothesis_id": str(sealed["hypothesis_id"]),
        "data_type": str(sealed["data_type"]),
        "hypothesis_contract_sha256": str(sealed["hypothesis_contract_sha256"]),
        "cost_profile_sha256": str(execution_plan["source"]["cost_profile_sha256"]),
        "source": {
            "execution_evaluation_path": str(execution_target),
            "execution_evaluation_file_sha256": sha256_file(execution_target),
            "execution_evaluation_result_hash": str(execution["deterministic_result_hash"]),
            "execution_plan_path": str(Path(str(execution["plan_path"])).expanduser().resolve()),
            "execution_plan_file_sha256": str(execution["plan_file_sha256"]),
            "execution_plan_hash": str(execution["plan_hash"]),
            "historical_evaluation_result_hash": str(execution["source_evaluation_result_hash"]),
            "full_plan_path": str(full_plan_target),
            "full_plan_file_sha256": sha256_file(full_plan_target),
            "full_plan_hash": str(full_validation["plan_hash"]),
            "input_merkle_root": str(full_validation["input_merkle_root"]),
        },
        "paper_ledger": {
            "path": str(ledger_target),
            "append_only_prefix_byte_length": len(ledger_bytes),
            "append_only_prefix_sha256": _sha256_bytes(ledger_bytes),
            "append_only_prefix_line_count": len(entries),
            "historical_accepted_dates": len(historical_dates),
            "paper_start_date": paper_start_date,
        },
        "warmup_certifications": descriptors[-2:],
        "hypothesis_contract": sealed["hypothesis_contract"],
        "paper_state_model": {
            "source_of_truth": "append_only_quality_certifications_and_hash_bound_segment_artifacts",
            "state_recovery": "recompute_all_positions_from_sealed_warmup_and_paper_dates_then_atomic_replace",
            "event_boundary": "event_date_must_be_on_or_after_paper_start_date",
            "position_completion": "normal_robustness_and_stress_scenarios_all_have_executable_exit",
            "maximum_segment_duration_sec": 1200,
            "manual_pnl_observations_allowed": False,
            "paper_positions_may_span_consecutive_quality_dates": True,
        },
        "acceptance_gates": {
            "minimum_completed_portfolio_observations": 15,
            "minimum_net_expectancy_quote_exclusive": 0.0,
            "minimum_profit_factor": 1.2,
            "minimum_stress_reconciliation_net_quote": 0.0,
            "maximum_incidents": 1,
            "incident_definition": "rejected technical certification or explicit kill_switch_breach after paper boundary",
        },
        "runtime_tools": {
            "paper_forward_evaluator": {
                "path": str(module_path),
                "sha256": sha256_file(module_path),
            },
            "membership_drift_evaluator": {
                "path": str(membership_evaluator_path),
                "sha256": sha256_file(membership_evaluator_path),
            },
        },
    }
    plan_hash = _canonical_hash(sealed_paper)
    approval_phrase = (
        "подтверждаю PIT membership-drift paper-forward "
        f"plan_hash={plan_hash} короткими видимыми сегментами до 20 минут"
    )
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "decision": PLAN_DECISION,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "research_only": True,
        "plan_hash": plan_hash,
        **sealed_paper,
        "approval_phrase": approval_phrase,
        "requires_explicit_user_approval_for_paper_forward": True,
        "paper_forward_started": False,
        "would_start": False,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "next_allowed_action": "request_explicit_user_approval_for_hash_bound_paper_forward",
        "next_allowed_command": approval_phrase,
        "output_path": str(target),
    }
    _write_json_immutable(target, plan)
    return plan


def validate_paper_forward_plan(
    plan_path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan = _read_json(target)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError(f"expected {PLAN_SCHEMA} PlanOnly artifact")
    if plan.get("decision") != PLAN_DECISION or plan.get("research_only") is not True:
        raise ValueError("paper-forward PlanOnly decision is invalid")
    sealed = _sealed_plan_payload(plan)
    observed_hash = _canonical_hash(sealed)
    if plan.get("plan_hash") != observed_hash:
        raise ValueError("paper-forward plan hash mismatch")
    if expected_plan_hash is not None and observed_hash != expected_plan_hash:
        raise ValueError("paper-forward plan does not match expected plan hash")
    expected_phrase = (
        "подтверждаю PIT membership-drift paper-forward "
        f"plan_hash={observed_hash} короткими видимыми сегментами до 20 минут"
    )
    if plan.get("approval_phrase") != expected_phrase or plan.get("next_allowed_command") != expected_phrase:
        raise ValueError("paper-forward approval phrase mismatch")
    if plan.get("requires_explicit_user_approval_for_paper_forward") is not True:
        raise ValueError("paper-forward PlanOnly must require explicit approval")
    for field in (
        "paper_forward_started",
        "would_start",
        "network_access",
        "grid_search",
        "retune",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        if plan.get(field) is not False:
            raise ValueError(f"paper-forward PlanOnly safety flag must be false: {field}")

    # Reject provenance tampering before any downstream validator parses the ledger.
    ledger_info = plan["paper_ledger"]
    ledger_target = Path(str(ledger_info["path"])).expanduser().resolve()
    _validate_append_only_prefix(ledger_target, ledger_info)

    gates = plan.get("acceptance_gates") or {}
    expected_gates = {
        "minimum_completed_portfolio_observations": 15,
        "minimum_net_expectancy_quote_exclusive": 0.0,
        "minimum_profit_factor": 1.2,
        "minimum_stress_reconciliation_net_quote": 0.0,
        "maximum_incidents": 1,
    }
    for key, value in expected_gates.items():
        if gates.get(key) != value:
            raise ValueError(f"paper-forward frozen gate mismatch: {key}")
    state_model = plan.get("paper_state_model") or {}
    if state_model.get("maximum_segment_duration_sec") != 1200:
        raise ValueError("paper-forward segment duration gate mismatch")
    if state_model.get("manual_pnl_observations_allowed") is not False:
        raise ValueError("paper-forward must reject manual PnL observations")

    source = plan["source"]
    execution_target = _verify_file(
        source.get("execution_evaluation_path"),
        source.get("execution_evaluation_file_sha256"),
        "execution evaluation",
    )
    execution, execution_plan = _validate_paper_ready_execution(execution_target)
    if execution.get("deterministic_result_hash") != source.get("execution_evaluation_result_hash"):
        raise ValueError("paper-forward execution result binding mismatch")
    if execution.get("plan_hash") != source.get("execution_plan_hash"):
        raise ValueError("paper-forward execution plan binding mismatch")
    if execution.get("source_evaluation_result_hash") != source.get("historical_evaluation_result_hash"):
        raise ValueError("paper-forward historical result binding mismatch")
    if execution_plan["source"]["cost_profile_sha256"] != plan.get("cost_profile_sha256"):
        raise ValueError("paper-forward cost profile binding mismatch")

    full_plan_target = _verify_file(
        source.get("full_plan_path"),
        source.get("full_plan_file_sha256"),
        "full historical plan",
    )
    full_validation = validate_evaluation_input_plan(full_plan_target, str(source.get("full_plan_hash") or ""))
    if full_validation["input_merkle_root"] != source.get("input_merkle_root"):
        raise ValueError("paper-forward input Merkle binding mismatch")
    full_plan = _read_json(full_plan_target)
    sealed = full_plan["sealed_input"]
    if sealed["hypothesis_contract"] != plan.get("hypothesis_contract"):
        raise ValueError("paper-forward hypothesis contract mismatch")
    if sealed["selected_certifications"][-2:] != plan.get("warmup_certifications"):
        raise ValueError("paper-forward warmup certification mismatch")
    if len(sealed["selected_certifications"]) != 120:
        raise ValueError("paper-forward historical date count mismatch")

    for name, runtime in (plan.get("runtime_tools") or {}).items():
        _verify_file(runtime.get("path"), runtime.get("sha256"), f"runtime tool {name}")
    return {
        "plan_path": str(target),
        "plan_file_sha256": sha256_file(target),
        "plan_hash": observed_hash,
        "hypothesis_id": str(plan["hypothesis_id"]),
        "historical_dates": len(sealed["selected_certifications"]),
        "paper_start_date": str(ledger_info["paper_start_date"]),
        "ledger_path": str(ledger_target),
    }


def create_paper_forward_approval(
    plan_path: str | Path,
    output_path: str | Path,
    *,
    confirmed_plan_hash: str,
    confirmed_paper_forward: bool,
    approved_at_utc: str | None = None,
) -> dict[str, Any]:
    if confirmed_paper_forward is not True:
        raise ValueError("paper-forward approval requires an explicit confirmed_paper_forward flag")
    validation = validate_paper_forward_plan(plan_path, confirmed_plan_hash)
    if confirmed_plan_hash != validation["plan_hash"]:
        raise ValueError("paper-forward approval plan hash mismatch")
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"paper-forward approval already exists: {target}")
    body: dict[str, Any] = {
        "schema": APPROVAL_SCHEMA,
        "approved_at_utc": approved_at_utc or _utc_now(),
        "plan_path": validation["plan_path"],
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": validation["plan_hash"],
        "hypothesis_id": validation["hypothesis_id"],
        "authorized_action": "paper_forward_accrual_and_offline_state_evaluation",
        "paper_forward_authorized": True,
        "public_data_only": True,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
    }
    approval = {**body, "approval_id": _canonical_hash(body)}
    _write_json_immutable(target, approval)
    return approval


def evaluate_paper_forward_state(
    plan_path: str | Path,
    approval_path: str | Path,
    output_path: str | Path,
    *,
    expected_plan_hash: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    validation = validate_paper_forward_plan(plan_target, expected_plan_hash)
    plan = _read_json(plan_target)
    approval_target = Path(approval_path).expanduser().resolve()
    approval = _validate_approval(approval_target, validation)
    state_target = Path(output_path).expanduser().resolve()
    ledger_target = Path(validation["ledger_path"])
    ledger_bytes = ledger_target.read_bytes()
    ledger_sha256 = _sha256_bytes(ledger_bytes)

    if state_target.exists():
        previous = _read_json(state_target)
        _validate_existing_state(previous, validation, approval, ledger_bytes)
        if previous.get("source_ledger_sha256") == ledger_sha256:
            return {**previous, "cache_hit": True}
        if previous.get("status") in {"PAPER_REJECTED", "LIVE_REVIEW_ELIGIBLE"}:
            raise ValueError(
                f"paper-forward state is terminal and cannot consume later ledger data: {previous['status']}"
            )

    entries = _load_quality_ledger(ledger_target)
    if ledger_target.read_bytes() != ledger_bytes:
        raise ValueError("paper-forward quality ledger changed during evaluation")
    paper_start = date.fromisoformat(validation["paper_start_date"])
    contract_hash = str(plan["hypothesis_contract_sha256"])
    matching_entries = [
        entry
        for entry in entries
        if entry.get("hypothesis_id") == validation["hypothesis_id"]
        and entry.get("data_type") == plan["data_type"]
        and entry.get("hypothesis_contract_sha256") == contract_hash
    ]
    paper_entries = [
        entry
        for entry in matching_entries
        if date.fromisoformat(str(entry["scheduled_date"])) >= paper_start
    ]
    accepted_by_date: dict[str, dict[str, Any]] = {}
    accepted_order: list[str] = []
    incident_ids: set[str] = set()
    for entry in paper_entries:
        scheduled_date = str(entry["scheduled_date"])
        if entry.get("technical_quality_accepted") is True:
            if scheduled_date in accepted_by_date:
                raise ValueError(f"duplicate accepted paper certification date: {scheduled_date}")
            accepted_by_date[scheduled_date] = entry
            accepted_order.append(scheduled_date)
        else:
            incident_ids.add(str(entry["certification_id"]))
        if entry.get("kill_switch_breach") is True:
            incident_ids.add(f"kill-switch:{entry['certification_id']}")
    if accepted_order != sorted(accepted_order):
        raise ValueError("paper certifications must be appended in chronological order")

    descriptors = [_certification_descriptor(accepted_by_date[value]) for value in accepted_order]
    for descriptor in descriptors:
        _verify_certification_artifacts(descriptor)
    all_descriptors = list(plan["warmup_certifications"]) + descriptors
    selected_dates = [str(item["scheduled_date"]) for item in all_descriptors]
    groups, _ = _load_cycle_groups(
        {"sealed_input": {"selected_certifications": all_descriptors}},
        selected_dates,
    )
    contract = plan["hypothesis_contract"]
    candidate_events, cycles = detect_activation_events_by_daily_segments(contract, groups)
    candidate_events = [event for event in candidate_events if date.fromisoformat(event.event_date) >= paper_start]
    observations: list[dict[str, Any]] = []
    pending_events = 0
    for event in candidate_events:
        normal = simulate_event(contract, event, cycles, scenario="normal")
        robustness = simulate_event(contract, event, cycles, scenario="robustness")
        stress = simulate_event(contract, event, cycles, scenario="stress")
        if normal is None or robustness is None or stress is None:
            pending_events += 1
            continue
        observations.append(
            {
                "observation_id": f"{event.base}|{event.activation_venue}|{event.event_date}",
                "normal": _serialise_result(normal),
                "robustness": _serialise_result(robustness),
                "stress": _serialise_result(stress),
            }
        )
    observations.sort(
        key=lambda item: (
            item["normal"]["exit_timestamp"],
            item["observation_id"],
        )
    )
    normal_values = [float(item["normal"]["net_price_pnl_quote"]) for item in observations]
    stress_values = [float(item["stress"]["net_price_pnl_quote"]) for item in observations]
    completed = len(observations)
    total_net = sum(normal_values)
    expectancy = total_net / completed if completed else 0.0
    profit_factor = _profit_factor(normal_values)
    stress_net = sum(stress_values)
    incident_count = len(incident_ids)
    metrics = {
        "paper_quality_dates": len(descriptors),
        "candidate_events": len(candidate_events),
        "pending_or_incomplete_events": pending_events,
        "completed_portfolio_observations": completed,
        "net_pnl_quote": total_net,
        "net_expectancy_quote": expectancy,
        "profit_factor": profit_factor,
        "positive_observation_rate": (
            sum(value > 0.0 for value in normal_values) / completed if completed else 0.0
        ),
        "stress_reconciliation_net_quote": stress_net,
        "incident_count": incident_count,
        "data_quality_or_kill_switch_incident_ids": sorted(incident_ids),
    }
    gates = plan["acceptance_gates"]
    rejection_reasons: list[str] = []
    if incident_count > int(gates["maximum_incidents"]):
        rejection_reasons.append("incident_limit_exceeded")
    if completed >= int(gates["minimum_completed_portfolio_observations"]):
        if expectancy <= float(gates["minimum_net_expectancy_quote_exclusive"]):
            rejection_reasons.append("paper_net_expectancy_not_positive")
        if profit_factor < float(gates["minimum_profit_factor"]):
            rejection_reasons.append("paper_profit_factor_below_gate")
        if stress_net < float(gates["minimum_stress_reconciliation_net_quote"]):
            rejection_reasons.append("paper_stress_reconciliation_negative")

    if rejection_reasons:
        status = "PAPER_REJECTED"
    elif completed >= int(gates["minimum_completed_portfolio_observations"]):
        status = "LIVE_REVIEW_ELIGIBLE"
    else:
        status = "PAPER_COLLECTING"
    state: dict[str, Any] = {
        "schema": STATE_SCHEMA,
        "mode": "deterministic_atomic_paper_forward_state",
        "generated_at_utc": generated_at_utc or _utc_now(),
        "research_only": True,
        "plan_path": validation["plan_path"],
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": validation["plan_hash"],
        "approval_path": str(approval_target),
        "approval_file_sha256": sha256_file(approval_target),
        "approval_id": approval["approval_id"],
        "source_ledger_path": str(ledger_target),
        "source_ledger_byte_length": len(ledger_bytes),
        "source_ledger_sha256": ledger_sha256,
        "paper_start_date": validation["paper_start_date"],
        "selected_paper_certification_ids": [str(item["certification_id"]) for item in accepted_by_date.values()],
        "metrics": metrics,
        "observations": observations,
        "status": status,
        "rejection_reasons": rejection_reasons,
        "requires_explicit_user_live_review": status == "LIVE_REVIEW_ELIGIBLE",
        "next_allowed_action": (
            "request_explicit_user_live_review_without_starting_live"
            if status == "LIVE_REVIEW_ELIGIBLE"
            else "continue_approved_bounded_paper_segments"
            if status == "PAPER_COLLECTING"
            else "close_hypothesis_without_retune"
        ),
        "next_allowed_command": (
            "REQUEST_EXPLICIT_USER_LIVE_REVIEW"
            if status == "LIVE_REVIEW_ELIGIBLE"
            else "WAIT_FOR_NEXT_APPROVED_PAPER_SEGMENT"
            if status == "PAPER_COLLECTING"
            else "NO_COMMAND_TERMINAL_HYPOTHESIS_CLOSED"
        ),
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
    }
    state["deterministic_result_hash"] = _state_result_hash(state)
    _write_json_atomic(state_target, state)
    return {**state, "cache_hit": False}


def _validate_paper_ready_execution(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    execution = _read_json(path)
    if execution.get("schema") != EVALUATION_OUTPUT_SCHEMA:
        raise ValueError("paper-forward requires a PIT execution-probe evaluation")
    if execution.get("deterministic_result_hash") != execution_result_hash(execution):
        raise ValueError("execution evaluation deterministic result hash mismatch")
    if execution.get("verdict") != "PAPER_READY":
        raise ValueError("paper-forward requires PAPER_READY execution verdict")
    if execution.get("paper_forward_allowed") is not True:
        raise ValueError("execution evaluation did not open paper-forward")
    if execution.get("requires_explicit_user_approval_for_paper_forward") is not True:
        raise ValueError("execution evaluation lacks explicit paper approval boundary")
    for field in ("live_orders", "api_keys", "leverage_or_margin", "grid_search", "retune", "network_access"):
        if execution.get(field) is not False:
            raise ValueError(f"execution evaluation safety flag must be false: {field}")
    plan_target = _verify_file(
        execution.get("plan_path"), execution.get("plan_file_sha256"), "execution plan"
    )
    validation = validate_execution_probe_plan(plan_target, str(execution.get("plan_hash") or ""))
    if validation["plan_file_sha256"] != execution.get("plan_file_sha256"):
        raise ValueError("execution evaluation plan file binding mismatch")
    _verify_file(execution.get("manifest_path"), execution.get("manifest_file_sha256"), "execution manifest")
    _verify_file(execution.get("sample_path"), execution.get("sample_file_sha256"), "execution samples")
    return execution, _read_json(plan_target)


def _validate_approval(
    approval_path: Path,
    plan_validation: dict[str, Any],
) -> dict[str, Any]:
    if not approval_path.is_file():
        raise ValueError(f"paper-forward approval is missing: {approval_path}")
    approval = _read_json(approval_path)
    if approval.get("schema") != APPROVAL_SCHEMA:
        raise ValueError("paper-forward approval schema mismatch")
    body = {key: value for key, value in approval.items() if key != "approval_id"}
    if approval.get("approval_id") != _canonical_hash(body):
        raise ValueError("paper-forward approval id mismatch")
    if approval.get("plan_path") != plan_validation["plan_path"]:
        raise ValueError("paper-forward approval plan path mismatch")
    if approval.get("plan_file_sha256") != plan_validation["plan_file_sha256"]:
        raise ValueError("paper-forward approval plan file mismatch")
    if approval.get("plan_hash") != plan_validation["plan_hash"]:
        raise ValueError("paper-forward approval plan hash mismatch")
    if approval.get("paper_forward_authorized") is not True:
        raise ValueError("paper-forward approval did not authorize paper accrual")
    for field in ("live_orders", "api_keys", "leverage_or_margin", "grid_search", "retune"):
        if approval.get(field) is not False:
            raise ValueError(f"paper-forward approval safety flag must be false: {field}")
    return approval


def _validate_existing_state(
    state: dict[str, Any],
    plan_validation: dict[str, Any],
    approval: dict[str, Any],
    current_ledger_bytes: bytes,
) -> None:
    if state.get("schema") != STATE_SCHEMA:
        raise ValueError("existing paper-forward state schema mismatch")
    if state.get("deterministic_result_hash") != _state_result_hash(state):
        raise ValueError("existing paper-forward state deterministic result hash mismatch")
    if state.get("plan_hash") != plan_validation["plan_hash"]:
        raise ValueError("existing paper-forward state belongs to another plan")
    if state.get("approval_id") != approval.get("approval_id"):
        raise ValueError("existing paper-forward state belongs to another approval")
    prior_length = int(state.get("source_ledger_byte_length") or 0)
    if len(current_ledger_bytes) < prior_length:
        raise ValueError("paper-forward ledger shrank after prior state")
    if _sha256_bytes(current_ledger_bytes[:prior_length]) != state.get("source_ledger_sha256"):
        raise ValueError("paper-forward ledger changed before the prior append boundary")


def _validate_append_only_prefix(path: Path, ledger_info: dict[str, Any]) -> None:
    if not path.is_file():
        raise ValueError(f"paper quality ledger is missing: {path}")
    data = path.read_bytes()
    length = int(ledger_info.get("append_only_prefix_byte_length") or 0)
    if len(data) < length:
        raise ValueError("paper quality ledger is shorter than sealed append-only prefix")
    if _sha256_bytes(data[:length]) != ledger_info.get("append_only_prefix_sha256"):
        raise ValueError("paper quality ledger append-only prefix mismatch")


def _sealed_plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        key: plan[key]
        for key in (
            "hypothesis_id",
            "data_type",
            "hypothesis_contract_sha256",
            "cost_profile_sha256",
            "source",
            "paper_ledger",
            "warmup_certifications",
            "hypothesis_contract",
            "paper_state_model",
            "acceptance_gates",
            "runtime_tools",
        )
    }


def _state_result_hash(payload: dict[str, Any]) -> str:
    ignored = {"generated_at_utc", "deterministic_result_hash", "cache_hit"}
    return _canonical_hash({key: value for key, value in payload.items() if key not in ignored})


def _verify_file(path_value: Any, expected_hash: Any, label: str) -> Path:
    path = Path(str(path_value or "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} file is missing: {path}")
    observed = sha256_file(path)
    if observed != str(expected_hash or ""):
        raise ValueError(f"{label} hash mismatch: expected={expected_hash}, observed={observed}")
    return path


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON artifact {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(target, payload)


def _write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PIT membership-drift paper-forward contract")
    subparsers = parser.add_subparsers(dest="action", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--execution-evaluation", required=True)
    plan.add_argument("--output", required=True)
    approve = subparsers.add_parser("approve")
    approve.add_argument("--plan", required=True)
    approve.add_argument("--output", required=True)
    approve.add_argument("--expected-plan-hash", required=True)
    approve.add_argument("--confirmed-paper-forward", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--approval", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument("--expected-plan-hash")
    validate = subparsers.add_parser("validate-plan")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.action == "plan":
        result = build_paper_forward_plan(args.execution_evaluation, args.output)
        print(f"{result['decision']} plan={Path(args.output).resolve()} hash={result['plan_hash']}")
        return 0
    if args.action == "approve":
        result = create_paper_forward_approval(
            args.plan,
            args.output,
            confirmed_plan_hash=args.expected_plan_hash,
            confirmed_paper_forward=args.confirmed_paper_forward,
        )
        print(f"PAPER_FORWARD_APPROVED approval={Path(args.output).resolve()} id={result['approval_id']}")
        return 0
    if args.action == "evaluate":
        result = evaluate_paper_forward_state(
            args.plan,
            args.approval,
            args.output,
            expected_plan_hash=args.expected_plan_hash,
        )
        print(
            f"{result['status']} observations={result['metrics']['completed_portfolio_observations']} "
            f"state={Path(args.output).resolve()}"
        )
        return 0
    if args.action == "validate-plan":
        result = validate_paper_forward_plan(args.plan, args.expected_plan_hash)
        print(f"VALID plan={result['plan_path']} hash={result['plan_hash']}")
        return 0
    raise AssertionError(f"unhandled action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
