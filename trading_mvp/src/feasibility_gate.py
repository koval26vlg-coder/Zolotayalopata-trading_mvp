from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "fast_first_feasibility_gate_v1"
ESTIMATOR_VERSION = "feasibility_gate_v1_wilson_lower_bound"
CANONICAL_MIN_TOTAL_EVENTS = 20
CANONICAL_MIN_PER_VENUE_EVENTS = 10
CANONICAL_MIN_UNIQUE_DATES = 10
CANONICAL_MIN_DUAL_VENUE_COVERAGE = 0.80
CANONICAL_MIN_CAPACITY_QUOTE = 500.0
Z_90_ONE_SIDED = 1.2815515655446004


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON object {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {target}")
    return payload


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def estimator_version_hash() -> str:
    payload = {
        "estimator_version": ESTIMATOR_VERSION,
        "z_90_one_sided": Z_90_ONE_SIDED,
        "canonical_min_total_events": CANONICAL_MIN_TOTAL_EVENTS,
        "canonical_min_per_venue_events": CANONICAL_MIN_PER_VENUE_EVENTS,
        "canonical_min_unique_dates": CANONICAL_MIN_UNIQUE_DATES,
        "canonical_min_dual_venue_coverage": CANONICAL_MIN_DUAL_VENUE_COVERAGE,
        "canonical_min_capacity_quote": CANONICAL_MIN_CAPACITY_QUOTE,
    }
    return sha256_json(payload)


def plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return sha256_json(payload)


def validate_frozen_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a JSON object")
    if plan.get("mode") != "PlanOnly":
        raise ValueError("Feasibility gate requires a frozen PlanOnly artifact")
    if plan.get("research_only") is not True:
        raise ValueError("Feasibility gate requires research_only=true")
    if plan.get("frozen_parameters_no_grid") is not True:
        raise ValueError("Feasibility gate requires frozen_parameters_no_grid=true")
    for flag in (
        "evaluation_allowed",
        "strategy_accepted",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
    ):
        if plan.get(flag) is not False:
            raise ValueError(f"{flag} must be false before feasibility/OOS")
    if plan.get("oos_metrics") or plan.get("observed_performance"):
        raise ValueError("PlanOnly artifact already contains OOS/observed performance")
    audit = plan.get("data_access_audit")
    if isinstance(audit, dict):
        forbidden_audit_flags = (
            "oos_returns_read",
            "pnl_computed",
            "signal_scores_computed",
            "performance_metrics_computed",
        )
        for flag in forbidden_audit_flags:
            if audit.get(flag) is not False and audit.get(flag) is not None:
                raise ValueError(f"{flag} must be false before feasibility")
    expected = str(plan.get("plan_hash") or "").lower()
    if expected:
        if len(expected) != 64:
            raise ValueError("plan_hash must be a SHA-256 hex string")
        observed = plan_hash(plan)
        if observed != expected:
            raise ValueError("Plan hash mismatch; frozen config was modified")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number


def _wilson_lower_bound(successes: int, trials: int, z: float = Z_90_ONE_SIDED) -> float:
    if trials <= 0:
        return 0.0
    successes = max(0, min(int(successes), int(trials)))
    phat = successes / trials
    z2 = z * z
    denominator = 1.0 + z2 / trials
    centre = phat + z2 / (2.0 * trials)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * trials)) / trials)
    return max(0.0, (centre - margin) / denominator)


def _acceptance_gates(plan: dict[str, Any]) -> dict[str, Any]:
    gates = ((plan.get("validation") or {}).get("acceptance_gates") or {}) if isinstance(plan.get("validation"), dict) else {}
    min_total = max(
        CANONICAL_MIN_TOTAL_EVENTS,
        _as_int(gates.get("minimum_oos_portfolio_events_total"), 0),
        _as_int(gates.get("min_oos_portfolio_events_total"), 0),
        _as_int(gates.get("min_oos_settlements"), 0),
    )
    min_per_venue = max(
        CANONICAL_MIN_PER_VENUE_EVENTS,
        _as_int(gates.get("minimum_oos_portfolio_events_per_venue"), 0),
        _as_int(gates.get("min_oos_portfolio_events_per_venue"), 0),
    )
    min_unique_dates = max(
        CANONICAL_MIN_UNIQUE_DATES,
        _as_int(gates.get("minimum_unique_oos_signal_dates"), 0),
        _as_int(gates.get("min_unique_oos_signal_dates"), 0),
    )
    min_capacity = max(
        CANONICAL_MIN_CAPACITY_QUOTE,
        _as_float(gates.get("minimum_capacity_proxy_quote_per_selected_leg"), 0.0),
        _as_float(gates.get("min_capacity_usd_per_leg"), 0.0),
    )
    return {
        "minimum_oos_portfolio_events_total": min_total,
        "minimum_oos_portfolio_events_per_venue": min_per_venue,
        "minimum_unique_oos_signal_dates": min_unique_dates,
        "minimum_dual_venue_coverage": max(
            CANONICAL_MIN_DUAL_VENUE_COVERAGE,
            _as_float(gates.get("minimum_dual_venue_coverage"), 0.0),
            _as_float(gates.get("min_dual_leg_coverage"), 0.0),
        ),
        "minimum_capacity_proxy_quote_per_selected_leg": min_capacity,
    }


def _infer_venues(plan: dict[str, Any], feasibility_inputs: dict[str, Any]) -> list[str]:
    venues = feasibility_inputs.get("venues")
    if isinstance(venues, list) and venues:
        return [str(value) for value in venues]
    signal_venues = (plan.get("signal") or {}).get("venues") if isinstance(plan.get("signal"), dict) else None
    if isinstance(signal_venues, list) and signal_venues:
        return [str(value) for value in signal_venues]
    by_venue = (plan.get("data_availability") or {}).get("by_venue") if isinstance(plan.get("data_availability"), dict) else None
    if isinstance(by_venue, dict) and by_venue:
        return sorted(str(key) for key in by_venue)
    return ["mexc", "gateio"]


def _infer_oos_candidates(plan: dict[str, Any], feasibility_inputs: dict[str, Any]) -> int:
    for key in ("oos_candidate_events", "expected_oos_portfolio_events", "oos_candidate_settlements"):
        if key in feasibility_inputs:
            return max(0, _as_int(feasibility_inputs.get(key), 0))
    availability = plan.get("data_availability") if isinstance(plan.get("data_availability"), dict) else {}
    for key in ("candidate_oos_events", "candidate_weekend_entry_days", "candidate_signal_days"):
        if key in availability:
            return max(0, _as_int(availability.get(key), 0))
    split = ((plan.get("validation") or {}).get("chronological_split") or {}) if isinstance(plan.get("validation"), dict) else {}
    oos = split.get("oos") if isinstance(split, dict) else {}
    if isinstance(oos, dict):
        return max(0, _as_int(oos.get("calendar_days"), 0))
    return 0


def _infer_per_venue_candidates(
    plan: dict[str, Any],
    feasibility_inputs: dict[str, Any],
    venues: list[str],
    total_candidates: int,
) -> dict[str, int]:
    explicit = feasibility_inputs.get("per_venue_oos_candidate_events")
    if isinstance(explicit, dict):
        return {venue: max(0, _as_int(explicit.get(venue), 0)) for venue in venues}
    availability = plan.get("data_availability") if isinstance(plan.get("data_availability"), dict) else {}
    by_venue = availability.get("by_venue") if isinstance(availability, dict) else None
    if isinstance(by_venue, dict):
        inferred: dict[str, int] = {}
        for venue in venues:
            entry = by_venue.get(venue) if isinstance(by_venue.get(venue), dict) else {}
            inferred[venue] = max(
                0,
                _as_int(entry.get("candidate_oos_events"), 0)
                or _as_int(entry.get("candidate_weekend_entry_days"), 0)
                or min(total_candidates, _as_int(entry.get("markets"), 0)),
            )
        if any(inferred.values()):
            return inferred
    if not venues:
        return {}
    share = total_candidates // len(venues)
    remainder = total_candidates % len(venues)
    return {venue: share + (1 if index < remainder else 0) for index, venue in enumerate(venues)}


def _infer_train_counts(feasibility_inputs: dict[str, Any], total_candidates: int) -> tuple[int, int]:
    trials = max(0, _as_int(feasibility_inputs.get("train_candidate_events"), 0))
    valid = max(0, _as_int(feasibility_inputs.get("train_valid_events"), 0))
    if trials > 0:
        return min(valid, trials), trials
    fill_rate = _as_float(feasibility_inputs.get("train_event_fill_rate"), -1.0)
    if 0.0 <= fill_rate <= 1.0:
        synthetic_trials = max(1, _as_int(feasibility_inputs.get("synthetic_train_trials"), total_candidates or 1))
        return int(math.floor(fill_rate * synthetic_trials)), synthetic_trials
    if total_candidates > 0:
        return total_candidates, total_candidates
    return 0, 0


def evaluate_feasibility(plan_path: str | Path, *, output_path: str | Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    plan_target = Path(plan_path).expanduser().resolve()
    plan = read_json(plan_target)
    validate_frozen_plan(plan)
    has_explicit_feasibility_inputs = "feasibility_inputs" in plan
    feasibility_inputs = plan.get("feasibility_inputs")
    if feasibility_inputs is None:
        feasibility_inputs = {}
    if not isinstance(feasibility_inputs, dict):
        raise ValueError("feasibility_inputs must be an object when present")

    gates = _acceptance_gates(plan)
    venues = _infer_venues(plan, feasibility_inputs)
    total_candidates = _infer_oos_candidates(plan, feasibility_inputs)
    valid_train_events, train_candidate_events = _infer_train_counts(feasibility_inputs, total_candidates)
    lower_rate = _wilson_lower_bound(valid_train_events, train_candidate_events)
    lower_total = int(math.floor(total_candidates * lower_rate))
    per_venue_candidates = _infer_per_venue_candidates(plan, feasibility_inputs, venues, total_candidates)
    lower_per_venue = {
        venue: int(math.floor(count * lower_rate))
        for venue, count in sorted(per_venue_candidates.items())
    }
    unique_dates = max(
        0,
        _as_int(
            feasibility_inputs.get(
                "unique_oos_dates",
                feasibility_inputs.get("expected_unique_oos_dates", total_candidates),
            ),
            0,
        ),
    )
    lower_unique_dates = int(math.floor(unique_dates * lower_rate))
    dual_venue_coverage = _as_float(feasibility_inputs.get("dual_venue_coverage"), 1.0 if len(venues) >= 2 else 0.0)
    capacity = _as_float(
        feasibility_inputs.get(
            "capacity_proxy_quote_per_selected_leg",
            feasibility_inputs.get("capacity_usd_per_leg", gates["minimum_capacity_proxy_quote_per_selected_leg"]),
        ),
        0.0,
    )

    reasons: list[str] = []
    blocked_bad_input = False
    if not has_explicit_feasibility_inputs:
        blocked_bad_input = True
        reasons.append("missing_explicit_feasibility_inputs")
    elif train_candidate_events <= 0:
        blocked_bad_input = True
        reasons.append("missing_train_candidate_events")
    elif total_candidates <= 0:
        blocked_bad_input = True
        reasons.append("missing_oos_candidate_events")
    if lower_total < gates["minimum_oos_portfolio_events_total"]:
        reasons.append("lower_bound_oos_portfolio_events_total_below_minimum")
    for venue, value in sorted(lower_per_venue.items()):
        if value < gates["minimum_oos_portfolio_events_per_venue"]:
            reasons.append(f"lower_bound_oos_portfolio_events_below_minimum:{venue}")
    if lower_unique_dates < gates["minimum_unique_oos_signal_dates"]:
        reasons.append("lower_bound_unique_oos_dates_below_minimum")
    if dual_venue_coverage < gates["minimum_dual_venue_coverage"]:
        reasons.append("expected_dual_venue_coverage_below_minimum")
    if capacity < gates["minimum_capacity_proxy_quote_per_selected_leg"]:
        reasons.append("expected_capacity_below_minimum")

    if blocked_bad_input:
        verdict = "FEASIBILITY_BLOCKED_BAD_INPUT"
    else:
        verdict = "FEASIBLE_FOR_OOS" if not reasons else "INFEASIBLE_ON_CURRENT_DATA"
    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "mode": "FEASIBILITY_ONLY",
        "research_only": True,
        "plan_path": str(plan_target),
        "plan_sha256": sha256_file(plan_target),
        "plan_hash": str(plan.get("plan_hash") or ""),
        "hypothesis_id": str((plan.get("hypothesis") or {}).get("id") or ""),
        "input_merkle_sha256": str((plan.get("sealed_input") or {}).get("input_merkle_sha256") or ""),
        "estimator_version": ESTIMATOR_VERSION,
        "estimator_version_hash": estimator_version_hash(),
        "oos_metrics_read": False,
        "pnl_or_returns_read": False,
        "grid_search": False,
        "retune": False,
        "execution_probe_started": False,
        "paper_forward_started": False,
        "live_orders": False,
        "api_keys": False,
        "acceptance_gates": gates,
        "inputs": {
            "venues": venues,
            "train_valid_events": valid_train_events,
            "train_candidate_events": train_candidate_events,
            "oos_candidate_events": total_candidates,
            "per_venue_oos_candidate_events": per_venue_candidates,
            "unique_oos_dates": unique_dates,
            "dual_venue_coverage": dual_venue_coverage,
            "capacity_proxy_quote_per_selected_leg": capacity,
        },
        "forecast": {
            "train_fill_rate": (valid_train_events / train_candidate_events) if train_candidate_events else 0.0,
            "wilson_90_lower_fill_rate": lower_rate,
            "expected_oos_event_count": total_candidates,
            "conservative_90_lower_oos_event_count": lower_total,
            "expected_per_venue_event_counts": per_venue_candidates,
            "conservative_90_lower_per_venue_event_counts": lower_per_venue,
            "expected_unique_oos_dates": unique_dates,
            "conservative_90_lower_unique_oos_dates": lower_unique_dates,
        },
        "verdict": verdict,
        "rejection_reasons": reasons,
        "next_allowed_action": (
            "run_visible_owned_no_grid_oos"
            if verdict == "FEASIBLE_FOR_OOS"
            else (
                "fix_planonly_feasibility_inputs_before_oos"
                if verdict == "FEASIBILITY_BLOCKED_BAD_INPUT"
                else "bank_hypothesis_with_data_requirements_do_not_run_oos"
            )
        ),
        "elapsed_sec": round(time.monotonic() - started, 6),
    }
    artifact["deterministic_result_hash"] = sha256_json(
        {
            key: value
            for key, value in artifact.items()
            if key not in {"created_at_utc", "elapsed_sec", "plan_sha256"}
        }
    )
    if output_path:
        write_json_atomic(output_path, artifact)
        artifact["artifact_path"] = str(Path(output_path).expanduser().resolve())
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fast-First feasibility gate v1")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("evaluate", help="Evaluate feasibility before OOS without reading OOS PnL")
    run.add_argument("--plan", required=True)
    run.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "evaluate":
        result = evaluate_feasibility(args.plan, output_path=args.output)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
