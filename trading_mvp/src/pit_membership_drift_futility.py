from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable

import pit_membership_drift_evaluator as evaluator
from hypothesis_contract import validate_hypothesis_contract


PLAN_SCHEMA = "pit_membership_drift_futility_plan_v1"
RESULT_SCHEMA = "pit_membership_drift_futility_result_v1"
CHECKPOINT_DAYS = 10
UPPER_BOUND_CONFIDENCE = 0.90


def _poisson_log_cdf(count: int, mean: float) -> float:
    if count < 0:
        return float("-inf")
    if mean < 0 or not math.isfinite(mean):
        raise ValueError("Poisson mean must be finite and nonnegative")
    if mean == 0:
        return 0.0
    log_mean = math.log(mean)
    terms = [index * log_mean - mean - math.lgamma(index + 1.0) for index in range(count + 1)]
    maximum = max(terms)
    return maximum + math.log(sum(math.exp(value - maximum) for value in terms))


def poisson_upper_mean(count: int, *, confidence: float = UPPER_BOUND_CONFIDENCE) -> float:
    """Return the exact one-sided Poisson upper bound for an observed count."""

    if isinstance(count, bool) or int(count) != count or count < 0:
        raise ValueError("count must be a nonnegative integer")
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be between 0.5 and 1")
    observed = int(count)
    log_alpha = math.log1p(-confidence)
    low = 0.0
    high = max(1.0, float(observed + 1))
    while _poisson_log_cdf(observed, high) > log_alpha:
        high *= 2.0
        if not math.isfinite(high):
            raise RuntimeError("failed to bracket Poisson upper bound")
    for _ in range(96):
        midpoint = (low + high) / 2.0
        if _poisson_log_cdf(observed, midpoint) > log_alpha:
            low = midpoint
        else:
            high = midpoint
    return high


def _wilson_upper_bound(
    successes: int,
    trials: int,
    *,
    confidence: float = UPPER_BOUND_CONFIDENCE,
) -> float:
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("Wilson counts are invalid")
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be between 0.5 and 1")
    if trials == 0:
        return 1.0
    z = NormalDist().inv_cdf(confidence)
    z2 = z * z
    phat = successes / trials
    denominator = 1.0 + z2 / trials
    centre = phat + z2 / (2.0 * trials)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * trials)) / trials)
    return min(1.0, (centre + margin) / denominator)


def _venue_projection(
    *,
    checkpoint_days: int,
    oos_days: int,
    candidate_events: int,
    valid_events: int,
    confidence: float,
) -> dict[str, Any]:
    candidate_upper_mean = poisson_upper_mean(candidate_events, confidence=confidence)
    candidate_upper_oos_raw = candidate_upper_mean * oos_days / checkpoint_days
    fill_upper = _wilson_upper_bound(valid_events, candidate_events, confidence=confidence)
    executable_upper_oos_raw = candidate_upper_oos_raw * fill_upper
    return {
        "observed_candidate_events": candidate_events,
        "observed_valid_events": valid_events,
        "candidate_event_upper_mean_checkpoint": candidate_upper_mean,
        "candidate_event_upper_oos": int(math.ceil(candidate_upper_oos_raw)),
        "valid_fill_rate_upper": fill_upper,
        "executable_event_upper_oos": int(math.ceil(executable_upper_oos_raw)),
    }


def project_futility_bounds(
    *,
    checkpoint_days: int,
    oos_days: int,
    candidate_events: int,
    valid_events: int,
    candidate_events_by_venue: dict[str, int],
    valid_events_by_venue: dict[str, int],
    valid_event_dates: int,
    minimum_total_events: int,
    minimum_events_per_venue: int,
    minimum_unique_dates: int,
    venues: tuple[str, ...],
    confidence: float = UPPER_BOUND_CONFIDENCE,
) -> dict[str, Any]:
    if checkpoint_days <= 0 or oos_days <= 0:
        raise ValueError("checkpoint_days and oos_days must be positive")
    if valid_event_dates < 0 or valid_event_dates > checkpoint_days:
        raise ValueError("valid_event_dates must be within the checkpoint window")
    combined = _venue_projection(
        checkpoint_days=checkpoint_days,
        oos_days=oos_days,
        candidate_events=candidate_events,
        valid_events=valid_events,
        confidence=confidence,
    )
    per_venue: dict[str, dict[str, Any]] = {}
    for venue in venues:
        per_venue[venue] = _venue_projection(
            checkpoint_days=checkpoint_days,
            oos_days=oos_days,
            candidate_events=int(candidate_events_by_venue.get(venue, 0)),
            valid_events=int(valid_events_by_venue.get(venue, 0)),
            confidence=confidence,
        )
    event_date_rate_upper = _wilson_upper_bound(
        valid_event_dates,
        checkpoint_days,
        confidence=confidence,
    )
    unique_dates_upper = min(oos_days, int(math.ceil(event_date_rate_upper * oos_days)))
    reasons: list[str] = []
    if combined["executable_event_upper_oos"] < minimum_total_events:
        reasons.append("optimistic_oos_event_upper_below_minimum")
    for venue in venues:
        if per_venue[venue]["executable_event_upper_oos"] < minimum_events_per_venue:
            reasons.append(f"optimistic_oos_event_upper_below_minimum:{venue}")
    if unique_dates_upper < minimum_unique_dates:
        reasons.append("optimistic_unique_oos_date_upper_below_minimum")
    return {
        "method": "poisson_candidate_ucb_times_wilson_fill_ucb",
        "confidence": confidence,
        "checkpoint_days": checkpoint_days,
        "oos_days": oos_days,
        "combined": combined,
        "by_activation_venue": per_venue,
        "observed_valid_event_dates": valid_event_dates,
        "valid_event_date_rate_upper": event_date_rate_upper,
        "unique_oos_date_upper": unique_dates_upper,
        "minimum_total_events": minimum_total_events,
        "minimum_events_per_venue": minimum_events_per_venue,
        "minimum_unique_dates": minimum_unique_dates,
        "verdict": (
            "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN"
            if reasons
            else "CONTINUE_TO_20_DATE_TRAIN_GATE"
        ),
        "reasons": reasons,
        "acceptance_use_forbidden": True,
    }


def _matching_accepted_by_date(
    *,
    ledger_path: Path,
    hypothesis_id: str,
    data_type: str,
    contract_hash: str,
) -> dict[str, dict[str, Any]]:
    accepted_by_date: dict[str, dict[str, Any]] = {}
    for entry in evaluator._load_quality_ledger(ledger_path):
        if entry.get("hypothesis_id") != hypothesis_id or entry.get("data_type") != data_type:
            continue
        if entry.get("hypothesis_contract_sha256") != contract_hash:
            raise ValueError("quality certification hypothesis contract hash mismatch")
        if not bool(entry.get("technical_quality_accepted")):
            continue
        scheduled_date = str(entry.get("scheduled_date") or "")
        try:
            date.fromisoformat(scheduled_date)
        except ValueError as exc:
            raise ValueError(f"invalid scheduled_date in quality ledger: {scheduled_date}") from exc
        if scheduled_date in accepted_by_date:
            raise ValueError(f"duplicate accepted certification date: {scheduled_date}")
        accepted_by_date[scheduled_date] = entry
    return accepted_by_date


def _runtime_tool(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": evaluator.sha256_file(path)}


def _powershell_literal(value: str | Path | int) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _next_command(plan_path: Path, plan_hash: str) -> str:
    wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
    output = plan_path.with_name(f"{plan_path.stem}.futility-result.json")
    return " ".join(
        (
            "&",
            _powershell_literal(wrapper),
            "-Action",
            "fast-edge-pit-futility-evaluate",
            "-PlanPath",
            _powershell_literal(plan_path),
            "-ExpectedPlanHash",
            _powershell_literal(plan_hash),
            "-OutputPath",
            _powershell_literal(output),
            "-MaxRuntimeSec",
            "1800",
        )
    )


def build_futility_plan(
    *,
    quality_ledger_path: str | Path,
    hypothesis_bank_path: str | Path,
    hypothesis_id: str,
    output_path: str | Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    ledger_target = Path(quality_ledger_path).expanduser().resolve()
    bank_target = Path(hypothesis_bank_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite immutable futility plan: {target}")
    bank, hypothesis = evaluator._load_hypothesis(bank_target, hypothesis_id)
    contract = hypothesis.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("banked hypothesis must contain a frozen contract")
    contract_validation = validate_hypothesis_contract(
        contract,
        expected_id=hypothesis_id,
        expected_data_type=str(hypothesis.get("required_data_type") or ""),
    )
    accepted_by_date = _matching_accepted_by_date(
        ledger_path=ledger_target,
        hypothesis_id=hypothesis_id,
        data_type=contract_validation["required_data_type"],
        contract_hash=contract_validation["contract_hash"],
    )
    ordered_dates = sorted(accepted_by_date)
    if len(ordered_dates) < CHECKPOINT_DAYS:
        raise ValueError(
            f"insufficient futility quality dates: observed={len(ordered_dates)}, "
            f"required={CHECKPOINT_DAYS}"
        )
    selected_dates = ordered_dates[:CHECKPOINT_DAYS]
    descriptors = [
        evaluator._certification_descriptor(accepted_by_date[value]) for value in selected_dates
    ]
    for descriptor in descriptors:
        evaluator._verify_certification_artifacts(descriptor)
    input_merkle_root = evaluator._json_hash(descriptors)
    checker_path = Path(__file__).resolve()
    evaluator_path = Path(evaluator.__file__).resolve()
    contract_path = evaluator_path.with_name("hypothesis_contract.py")
    gates = contract["validation_protocol"]
    policy = {
        "checkpoint_quality_dates": CHECKPOINT_DAYS,
        "upper_bound_confidence": UPPER_BOUND_CONFIDENCE,
        "candidate_rate_model": "exact_one_sided_poisson_upper_bound",
        "fill_rate_model": "one_sided_wilson_upper_bound",
        "decision_rule": "close_only_if_optimistic_upper_bound_misses_any_frozen_sample_gate",
        "minimum_total_events": int(gates["minimum_oos_portfolio_events_total"]),
        "minimum_events_per_venue": int(gates["minimum_oos_portfolio_events_per_venue"]),
        "minimum_unique_dates": int(gates["minimum_unique_oos_signal_dates"]),
        "acceptance_use_forbidden": True,
    }
    sealed_input = {
        "schema": PLAN_SCHEMA,
        "hypothesis_id": hypothesis_id,
        "data_type": contract_validation["required_data_type"],
        "hypothesis_contract": contract,
        "hypothesis_contract_sha256": contract_validation["contract_hash"],
        "hypothesis_bank": {
            "path": str(bank_target),
            "sha256": evaluator.sha256_file(bank_target),
            "version": str(bank.get("version") or ""),
        },
        "quality_ledger": {
            "path": str(ledger_target),
            "file_sha256_at_plan": evaluator.sha256_file(ledger_target),
            "selected_entries_sha256": input_merkle_root,
        },
        "runtime_tools": {
            "futility_checker": _runtime_tool(checker_path),
            "membership_drift_evaluator": _runtime_tool(evaluator_path),
            "hypothesis_contract_validator": _runtime_tool(contract_path),
        },
        "source_control": evaluator._repository_metadata(),
        "runtime_versions": evaluator._runtime_versions(),
        "selected_certifications": descriptors,
        "input_artifact_hashes": evaluator._input_artifact_hashes(descriptors),
        "input_merkle_root": input_merkle_root,
        "selected_dates": selected_dates,
        "futility_policy": policy,
        "oos_days": int(contract["sample_plan"]["oos_closed_days"]),
    }
    plan_hash = evaluator._json_hash(sealed_input)
    plan = {
        "schema": PLAN_SCHEMA,
        "created_at_utc": created_at_utc or evaluator._utc_now(),
        "mode": "PlanOnly",
        "research_only": True,
        "plan_artifact_path": str(target),
        "plan_hash": plan_hash,
        "sealed_input_hash": plan_hash,
        "sealed_input": sealed_input,
        "input_merkle_root": input_merkle_root,
        "forward_market_rows_read": False,
        "returns_read": False,
        "pnl_computed": False,
        "oos_metrics_computed": False,
        "grid_search": False,
        "retune": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "next_allowed_action": "run_embargo_safe_10_date_futility_evaluation",
        "next_allowed_command": _next_command(target, plan_hash),
    }
    evaluator._write_json_immutable(target, plan)
    validation = validate_futility_plan(target, plan_hash)
    return {
        "schema": PLAN_SCHEMA,
        "decision": "READY_FOR_10_DATE_FUTILITY_EVALUATION",
        "plan_path": str(target),
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": plan_hash,
        "input_merkle_root": input_merkle_root,
        "selected_dates": validation["selected_dates"],
        "forward_market_rows_read": False,
        "returns_read": False,
        "pnl_computed": False,
        "next_allowed_command": plan["next_allowed_command"],
    }


def validate_futility_plan(
    plan_path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan = evaluator._read_json(target)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError(f"expected {PLAN_SCHEMA} PlanOnly artifact")
    sealed = plan.get("sealed_input")
    if not isinstance(sealed, dict) or sealed.get("schema") != PLAN_SCHEMA:
        raise ValueError("futility plan sealed_input is invalid")
    observed_hash = evaluator._json_hash(sealed)
    if plan.get("plan_hash") != observed_hash or plan.get("sealed_input_hash") != observed_hash:
        raise ValueError("futility plan hash mismatch")
    if expected_plan_hash and observed_hash != expected_plan_hash:
        raise ValueError(
            f"futility plan hash differs from expected: expected={expected_plan_hash}, "
            f"observed={observed_hash}"
        )
    tools = sealed.get("runtime_tools")
    if not isinstance(tools, dict):
        raise ValueError("futility runtime tools are missing")
    for name in ("futility_checker", "membership_drift_evaluator", "hypothesis_contract_validator"):
        tool = tools.get(name)
        if not isinstance(tool, dict):
            raise ValueError(f"futility runtime tool is missing: {name}")
        evaluator._verify_file(tool.get("path"), tool.get("sha256"), f"runtime tool {name}")
    bank_info = sealed.get("hypothesis_bank") or {}
    bank_path = evaluator._verify_file(
        bank_info.get("path"),
        bank_info.get("sha256"),
        "hypothesis bank",
    )
    hypothesis_id = str(sealed.get("hypothesis_id") or "")
    _, hypothesis = evaluator._load_hypothesis(bank_path, hypothesis_id)
    contract = hypothesis.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("sealed hypothesis contract is missing")
    contract_validation = validate_hypothesis_contract(
        contract,
        expected_id=hypothesis_id,
        expected_data_type=str(sealed.get("data_type") or ""),
    )
    if contract != sealed.get("hypothesis_contract"):
        raise ValueError("sealed hypothesis contract differs from the bank")
    if contract_validation["contract_hash"] != sealed.get("hypothesis_contract_sha256"):
        raise ValueError("sealed hypothesis contract hash mismatch")
    ledger_info = sealed.get("quality_ledger") or {}
    ledger_path = Path(str(ledger_info.get("path") or "")).expanduser().resolve()
    accepted_by_date = _matching_accepted_by_date(
        ledger_path=ledger_path,
        hypothesis_id=hypothesis_id,
        data_type=contract_validation["required_data_type"],
        contract_hash=contract_validation["contract_hash"],
    )
    expected_dates = sorted(accepted_by_date)[:CHECKPOINT_DAYS]
    selected_dates = list(sealed.get("selected_dates") or [])
    if len(expected_dates) < CHECKPOINT_DAYS or selected_dates != expected_dates:
        raise ValueError("futility plan does not seal the earliest ten accepted dates")
    descriptors = sealed.get("selected_certifications")
    if not isinstance(descriptors, list) or len(descriptors) != CHECKPOINT_DAYS:
        raise ValueError("futility plan must seal exactly ten certifications")
    expected_descriptors = [
        evaluator._certification_descriptor(accepted_by_date[value]) for value in expected_dates
    ]
    if descriptors != expected_descriptors:
        raise ValueError("futility selected certification descriptors mismatch")
    for descriptor in descriptors:
        evaluator._verify_certification_artifacts(descriptor)
    input_merkle_root = evaluator._json_hash(descriptors)
    if input_merkle_root != sealed.get("input_merkle_root"):
        raise ValueError("futility input merkle mismatch")
    if input_merkle_root != ledger_info.get("selected_entries_sha256"):
        raise ValueError("futility quality ledger selection hash mismatch")
    if sealed.get("input_artifact_hashes") != evaluator._input_artifact_hashes(descriptors):
        raise ValueError("futility input artifact hashes mismatch")
    policy = sealed.get("futility_policy")
    if not isinstance(policy, dict):
        raise ValueError("futility policy is missing")
    if int(policy.get("checkpoint_quality_dates") or 0) != CHECKPOINT_DAYS:
        raise ValueError("futility checkpoint date count mismatch")
    if float(policy.get("upper_bound_confidence") or 0.0) != UPPER_BOUND_CONFIDENCE:
        raise ValueError("futility confidence mismatch")
    return {
        "schema": PLAN_SCHEMA,
        "plan_path": str(target),
        "plan_file_sha256": evaluator.sha256_file(target),
        "plan_hash": observed_hash,
        "input_merkle_root": input_merkle_root,
        "selected_dates": len(selected_dates),
        "selected_date_values": selected_dates,
    }


def _evaluate_once(plan: dict[str, Any]) -> dict[str, Any]:
    sealed = plan["sealed_input"]
    contract = sealed["hypothesis_contract"]
    selected_dates = list(sealed["selected_dates"])
    groups, cycles = evaluator._load_cycle_groups(plan, selected_dates)
    events, cycles = evaluator.detect_activation_events_by_daily_segments(contract, groups)
    valid_events = []
    capacities: list[float] = []
    for event in events:
        rows = evaluator._entry_rows(contract, event, cycles, scenario="normal")
        if rows is None:
            continue
        valid_events.append(event)
        long_row, short_row = (rows[0], rows[1]) if rows[0].mid < rows[1].mid else (rows[1], rows[0])
        capacities.append(evaluator._entry_capacity_quote(long_row, short_row))
    venues = tuple(str(value) for value in contract["universe"]["venues"])
    candidate_by_venue = {
        venue: sum(event.activation_venue == venue for event in events) for venue in venues
    }
    valid_by_venue = {
        venue: sum(event.activation_venue == venue for event in valid_events) for venue in venues
    }
    gates = contract["validation_protocol"]
    projection = project_futility_bounds(
        checkpoint_days=len(selected_dates),
        oos_days=int(sealed["oos_days"]),
        candidate_events=len(events),
        valid_events=len(valid_events),
        candidate_events_by_venue=candidate_by_venue,
        valid_events_by_venue=valid_by_venue,
        valid_event_dates=len({event.event_date for event in valid_events}),
        minimum_total_events=int(gates["minimum_oos_portfolio_events_total"]),
        minimum_events_per_venue=int(gates["minimum_oos_portfolio_events_per_venue"]),
        minimum_unique_dates=int(gates["minimum_unique_oos_signal_dates"]),
        venues=venues,
        confidence=UPPER_BOUND_CONFIDENCE,
    )
    return {
        "checkpoint_dates_read": len(selected_dates),
        "checkpoint_date_values": selected_dates,
        "candidate_events": len(events),
        "valid_events": len(valid_events),
        "candidate_events_by_activation_venue": candidate_by_venue,
        "valid_events_by_activation_venue": valid_by_venue,
        "valid_event_dates": len({event.event_date for event in valid_events}),
        "dual_venue_coverage": evaluator._dual_venue_coverage(contract, cycles),
        "minimum_observed_executable_capacity_quote_per_leg": min(capacities) if capacities else 0.0,
        "projection": projection,
        "verdict": projection["verdict"],
        "rejection_reasons": projection["reasons"],
    }


def evaluate_futility_plan(
    plan_path: str | Path,
    *,
    expected_plan_hash: str,
    output_path: str | Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    validation = validate_futility_plan(plan_path, expected_plan_hash)
    plan_target = Path(plan_path).expanduser().resolve()
    plan = evaluator._read_json(plan_target)
    sealed = plan["sealed_input"]
    repeats = int(sealed["hypothesis_contract"]["validation_protocol"]["deterministic_repeats"])
    evaluated = [_evaluate_once(plan) for _ in range(repeats)]
    repeat_hashes = [evaluator._json_hash(value) for value in evaluated]
    if len(set(repeat_hashes)) != 1:
        raise RuntimeError(f"deterministic futility repeats diverged: {repeat_hashes}")
    core = evaluated[0]
    verdict = str(core["verdict"])
    artifact: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "created_at_utc": created_at_utc or evaluator._utc_now(),
        "mode": "embargo_safe_10_date_futility",
        "research_only": True,
        "hypothesis_id": sealed["hypothesis_id"],
        "plan_path": str(plan_target),
        "plan_hash": validation["plan_hash"],
        "plan_file_sha256": validation["plan_file_sha256"],
        "input_merkle_root": validation["input_merkle_root"],
        "hypothesis_contract_sha256": sealed["hypothesis_contract_sha256"],
        "runtime_tools": sealed["runtime_tools"],
        "futility_policy": sealed["futility_policy"],
        "deterministic_repeats": repeats,
        "deterministic_repeat_hashes": repeat_hashes,
        "deterministic_repeats_match": True,
        **core,
        "forward_market_rows_read": True,
        "signal_eligibility_computed": True,
        "returns_read": False,
        "pnl_computed": False,
        "oos_metrics_computed": False,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "next_allowed_action": (
            "bank_hypothesis_without_oos_or_retune"
            if verdict == "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN"
            else "continue_quality_certified_train_accrual_until_20_dates"
        ),
        "next_allowed_command": (
            "NO_COMMAND_TERMINAL_FUTILITY_REJECTED"
            if verdict == "FUTILE_CLOSE_BRANCH_BEFORE_TRAIN"
            else "WAIT_FOR_NEXT_APPROVED_QUALITY_CERTIFIED_PIT_DATE"
        ),
        "elapsed_sec": round(time.monotonic() - started, 6),
    }
    artifact["deterministic_result_hash"] = evaluator._result_hash(artifact)
    evaluator._write_json_immutable(output_path, artifact)
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Embargo-safe PIT membership-drift futility gate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Seal the earliest ten quality-certified dates")
    plan.add_argument("--quality-ledger", required=True)
    plan.add_argument("--hypothesis-bank", required=True)
    plan.add_argument("--hypothesis-id", required=True)
    plan.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate-plan", help="Validate a sealed futility plan")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash", required=True)
    evaluate = subparsers.add_parser("evaluate", help="Evaluate event-frequency futility without PnL")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--expected-plan-hash", required=True)
    evaluate.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        result = build_futility_plan(
            quality_ledger_path=args.quality_ledger,
            hypothesis_bank_path=args.hypothesis_bank,
            hypothesis_id=args.hypothesis_id,
            output_path=args.output,
        )
    elif args.command == "validate-plan":
        result = validate_futility_plan(args.plan, args.expected_plan_hash)
    elif args.command == "evaluate":
        result = evaluate_futility_plan(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
        )
    else:
        raise ValueError(f"unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
