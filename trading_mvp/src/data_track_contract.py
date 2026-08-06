from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from feasibility_gate import (
    CANONICAL_MIN_CAPACITY_QUOTE,
    CANONICAL_MIN_DUAL_VENUE_COVERAGE,
    CANONICAL_MIN_PER_VENUE_EVENTS,
    CANONICAL_MIN_TOTAL_EVENTS,
    CANONICAL_MIN_UNIQUE_DATES,
    estimator_version_hash,
    plan_hash,
    read_json,
    sha256_file,
    validate_frozen_plan,
)


PLAN_SCHEMA = "fast_first_data_track_contract_plan_v1"
DEFAULT_VENUES = ("mexc", "gateio")
MAX_PLAN_RUNTIME_SEC = 1_200


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _load_hypothesis(bank_path: str | Path, hypothesis_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    bank_target = Path(bank_path).expanduser().resolve()
    bank = read_json(bank_target)
    hypotheses = bank.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("Hypothesis bank must contain a hypotheses list")
    for entry in hypotheses:
        if isinstance(entry, dict) and str(entry.get("id") or "") == hypothesis_id:
            return bank, entry
    raise ValueError(f"Hypothesis id not found in bank: {hypothesis_id}")


def _parse_venue_counts(raw: str | None, venues: tuple[str, ...], total: int) -> dict[str, int]:
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid per-venue JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Per-venue candidate events must be a JSON object")
        result = {venue: int(payload.get(venue, 0)) for venue in venues}
        if any(value < 0 for value in result.values()):
            raise ValueError("Per-venue candidate events must be non-negative")
        return result
    share = total // len(venues)
    remainder = total % len(venues)
    return {venue: share + (1 if index < remainder else 0) for index, venue in enumerate(venues)}


def _runtime(max_runtime_sec: int) -> int:
    value = int(max_runtime_sec)
    if not 1 <= value <= MAX_PLAN_RUNTIME_SEC:
        raise ValueError(f"MaxRuntimeSec must be in [1, {MAX_PLAN_RUNTIME_SEC}] for PlanOnly data-track contracts")
    return value


def _validate_counts(
    train_candidate_events: int,
    train_valid_events: int,
    oos_candidate_events: int,
    unique_oos_dates: int,
    dual_venue_coverage: float,
    capacity_proxy_quote_per_selected_leg: float,
) -> None:
    if train_candidate_events <= 0:
        raise ValueError("train_candidate_events must be > 0")
    if not 0 <= train_valid_events <= train_candidate_events:
        raise ValueError("train_valid_events must be in [0, train_candidate_events]")
    if oos_candidate_events <= 0:
        raise ValueError("oos_candidate_events must be > 0")
    if unique_oos_dates <= 0:
        raise ValueError("unique_oos_dates must be > 0")
    if not 0.0 <= dual_venue_coverage <= 1.0:
        raise ValueError("dual_venue_coverage must be in [0, 1]")
    if capacity_proxy_quote_per_selected_leg < 0.0:
        raise ValueError("capacity_proxy_quote_per_selected_leg must be non-negative")


def build_data_track_contract(
    *,
    hypothesis_bank_path: str | Path,
    hypothesis_id: str,
    data_type: str,
    dataset_id: str,
    input_merkle_sha256: str,
    output_path: str | Path,
    goal_path: str | Path | None = None,
    track_id: str = "",
    dataset_root: str = "",
    train_candidate_events: int,
    train_valid_events: int,
    oos_candidate_events: int,
    per_venue_oos_candidate_events_json: str | None = None,
    unique_oos_dates: int,
    dual_venue_coverage: float,
    capacity_proxy_quote_per_selected_leg: float,
    max_runtime_sec: int = MAX_PLAN_RUNTIME_SEC,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    runtime = _runtime(max_runtime_sec)
    _validate_counts(
        train_candidate_events,
        train_valid_events,
        oos_candidate_events,
        unique_oos_dates,
        dual_venue_coverage,
        capacity_proxy_quote_per_selected_leg,
    )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(input_merkle_sha256)):
        raise ValueError("input_merkle_sha256 must be a SHA-256 hex string")
    bank, hypothesis = _load_hypothesis(hypothesis_bank_path, hypothesis_id)
    required_data_type = str(hypothesis.get("required_data_type") or "")
    if required_data_type and required_data_type != data_type:
        raise ValueError(f"Hypothesis {hypothesis_id} requires data_type={required_data_type}, got {data_type}")

    venues = DEFAULT_VENUES
    per_venue_counts = _parse_venue_counts(per_venue_oos_candidate_events_json, venues, int(oos_candidate_events))
    if sum(per_venue_counts.values()) < int(oos_candidate_events):
        raise ValueError("Sum of per-venue OOS candidate events must cover total OOS candidate events")

    bank_target = Path(hypothesis_bank_path).expanduser().resolve()
    goal_info: dict[str, Any] | None = None
    if goal_path:
        goal_target = Path(goal_path).expanduser().resolve()
        goal_info = {"path": str(goal_target), "sha256": sha256_file(goal_target)}

    created = created_at_utc or utc_now()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "created_at_utc": created,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "evaluation_allowed": False,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "retune": False,
        "oos_metrics": {},
        "observed_performance": {},
        "track": {
            "id": track_id or f"{data_type.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "data_type": data_type,
            "dataset_id": dataset_id,
            "dataset_root": dataset_root,
            "closed_prior_track": str(bank.get("closed_track") or ""),
            "new_data_required": True,
            "actual_collection_started": False,
        },
        "hypothesis": {
            "id": hypothesis_id,
            "status": "PLANONLY_CONTRACT_FROZEN",
            "required_data_type": data_type,
            "thesis": str(hypothesis.get("thesis") or ""),
            "minimum_data": hypothesis.get("minimum_data") or {},
            "forbidden": hypothesis.get("forbidden") or [],
        },
        "hypothesis_bank": {
            "path": str(bank_target),
            "sha256": sha256_file(bank_target),
            "version": str(bank.get("version") or ""),
        },
        "goal_document": goal_info,
        "sealed_input": {
            "dataset_id": dataset_id,
            "dataset_root": dataset_root,
            "input_merkle_sha256": str(input_merkle_sha256).lower(),
            "input_hash_method": "provided_by_track_data_contract_no_market_returns_read",
            "data_type": data_type,
            "oos_returns_embargoed": True,
        },
        "validation": {
            "acceptance_gates": {
                "minimum_oos_portfolio_events_total": CANONICAL_MIN_TOTAL_EVENTS,
                "minimum_oos_portfolio_events_per_venue": CANONICAL_MIN_PER_VENUE_EVENTS,
                "minimum_unique_oos_signal_dates": CANONICAL_MIN_UNIQUE_DATES,
                "minimum_dual_venue_coverage": CANONICAL_MIN_DUAL_VENUE_COVERAGE,
                "minimum_capacity_proxy_quote_per_selected_leg": CANONICAL_MIN_CAPACITY_QUOTE,
            },
            "feasibility_estimator": {
                "version": "feasibility_gate_v1_wilson_lower_bound",
                "version_hash": estimator_version_hash(),
                "must_run_before_oos": True,
            },
            "verdicts": [
                "FEASIBILITY_BLOCKED_BAD_INPUT",
                "INFEASIBLE_ON_CURRENT_DATA",
                "FEASIBLE_FOR_OOS",
                "INSUFFICIENT_DATA",
                "REJECT",
                "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
            ],
        },
        "feasibility_inputs": {
            "venues": list(venues),
            "train_candidate_events": int(train_candidate_events),
            "train_valid_events": int(train_valid_events),
            "oos_candidate_events": int(oos_candidate_events),
            "per_venue_oos_candidate_events": per_venue_counts,
            "unique_oos_dates": int(unique_oos_dates),
            "dual_venue_coverage": float(dual_venue_coverage),
            "capacity_proxy_quote_per_selected_leg": float(capacity_proxy_quote_per_selected_leg),
        },
        "data_access_audit": {
            "planonly_scope": "metadata_counts_hashes_and_user_supplied_feasibility_inputs_only",
            "oos_returns_read": False,
            "pnl_computed": False,
            "signal_scores_computed": False,
            "performance_metrics_computed": False,
            "market_data_collected": False,
            "network_access": False,
        },
        "runtime_policy": {
            "max_runtime_sec": runtime,
            "visible_terminal_required_for_collection": True,
            "actual_collect_requires_explicit_user_approval": True,
            "night_schedule_requires_explicit_user_approval": True,
        },
        "prohibited": [
            "grid search",
            "retune",
            "OOS before feasibility",
            "forward-return browsing before hypothesis freeze",
            "collector start from this command",
            "execution probe",
            "paper-forward",
            "live orders",
            "API keys",
            "leverage",
            "margin",
        ],
        "next_allowed_action": "run_fast_edge_feasibility_before_any_oos",
    }
    plan["plan_hash"] = plan_hash(plan)
    validate_frozen_plan(plan)

    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"Refusing to overwrite immutable data-track PlanOnly artifact: {target}")
    write_json_atomic(target, plan)
    persisted = read_json(target)
    validate_frozen_plan(persisted)
    return {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "output_path": str(target),
        "output_sha256": sha256_file(target),
        "plan_hash": persisted["plan_hash"],
        "hypothesis_id": hypothesis_id,
        "data_type": data_type,
        "input_merkle_sha256": str(input_merkle_sha256).lower(),
        "feasibility_inputs_present": "feasibility_inputs" in persisted,
        "evaluation_allowed": False,
        "next_allowed_action": "run_fast_edge_feasibility_before_any_oos",
        "elapsed_sec": round(time.monotonic() - started, 6),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Fast-First data-track PlanOnly contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Freeze a data-track PlanOnly contract with explicit feasibility inputs")
    build.add_argument("--hypothesis-bank", required=True)
    build.add_argument("--hypothesis-id", required=True)
    build.add_argument("--data-type", required=True)
    build.add_argument("--dataset-id", required=True)
    build.add_argument("--input-merkle-sha256", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--goal")
    build.add_argument("--track-id", default="")
    build.add_argument("--dataset-root", default="")
    build.add_argument("--train-candidate-events", type=int, required=True)
    build.add_argument("--train-valid-events", type=int, required=True)
    build.add_argument("--oos-candidate-events", type=int, required=True)
    build.add_argument("--per-venue-oos-candidate-events-json")
    build.add_argument("--unique-oos-dates", type=int, required=True)
    build.add_argument("--dual-venue-coverage", type=float, required=True)
    build.add_argument("--capacity-proxy-quote-per-selected-leg", type=float, required=True)
    build.add_argument("--max-runtime-sec", type=int, default=MAX_PLAN_RUNTIME_SEC)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        result = build_data_track_contract(
            hypothesis_bank_path=args.hypothesis_bank,
            hypothesis_id=args.hypothesis_id,
            data_type=args.data_type,
            dataset_id=args.dataset_id,
            input_merkle_sha256=args.input_merkle_sha256,
            output_path=args.output,
            goal_path=args.goal,
            track_id=args.track_id,
            dataset_root=args.dataset_root,
            train_candidate_events=args.train_candidate_events,
            train_valid_events=args.train_valid_events,
            oos_candidate_events=args.oos_candidate_events,
            per_venue_oos_candidate_events_json=args.per_venue_oos_candidate_events_json,
            unique_oos_dates=args.unique_oos_dates,
            dual_venue_coverage=args.dual_venue_coverage,
            capacity_proxy_quote_per_selected_leg=args.capacity_proxy_quote_per_selected_leg,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
