from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_membership_momentum_v2_oos as v2_oos
import gate_membership_momentum_v2_train as v2_train
from gate_membership_momentum import DAY_SEC


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_v2_execution_probe_plan_v2"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_EXECUTION_PROBE_PLAN_READY"
WINDOW_COUNT = 3
WINDOW_DURATION_SEC = 1_200
WINDOW_START_SEPARATION_SEC = 14_400
WINDOW_PREP_BUFFER_SEC = 900
SAMPLE_INTERVAL_SEC = 5
MINIMUM_VALID_SNAPSHOTS_PER_ASSET_PER_WINDOW = 180
MINIMUM_COVERAGE_PER_ASSET = 0.80
MAXIMUM_TIMESTAMP_SKEW_MS = 2_000.0
MAXIMUM_QUOTE_AGE_MS = 2_000.0
MINIMUM_CAPACITY_QUOTE_PER_ASSET = 500.0
MAXIMUM_P95_IMPACT_BPS = 10.0


def execution_probe_plan_hash(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_contract")
    if isinstance(frozen, Mapping):
        return v3_history_plan.sha256_json(frozen)
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "plan_hash"}
        }
    )


def _validate_oos_accept(
    *,
    oos_plan_path: str | Path,
    expected_oos_plan_hash: str,
    oos_result_path: str | Path,
    expected_oos_result_hash: str,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    plan_path = Path(oos_plan_path).expanduser().resolve()
    plan_hash = v2_train._validate_hash(expected_oos_plan_hash, label="OOS plan hash")
    plan = v2_oos.authorize_oos_evaluation(plan_path, plan_hash)

    result_path = Path(oos_result_path).expanduser().resolve()
    result = v2_train._read_json_object(result_path)
    result_hash = v2_train._validate_hash(
        expected_oos_result_hash,
        label="OOS result hash",
    )
    stored_result_hash = str(result.get("deterministic_result_hash") or "")
    if (
        result.get("schema") != v2_oos.RESULT_SCHEMA
        or result.get("stage") != "chronological_oos"
        or result.get("final") is not True
        or result.get("decision") != v2_oos.HISTORICAL_ACCEPT_DECISION
        or result.get("capacity_status") != "REQUIRES_EXECUTION_PROBE"
        or result.get("maximum_historical_verdict") != "ACCEPT_FOR_EXECUTION_PROBE"
        or result.get("next_allowed_command")
        != "create_hash_bound_gate_membership_momentum_v2_execution_probe_planonly"
        or result.get("paper_forward_allowed") is not False
        or result.get("live_orders") is not False
        or result.get("private_api_keys") is not False
        or result.get("leverage_or_margin") is not False
        or str(result.get("plan_hash") or "") != plan_hash
        or stored_result_hash != result_hash
        or stored_result_hash != v2_train._deterministic_result_hash(result)
        or result.get("rebalance_schedule_contract")
        != plan.get("rebalance_schedule_contract")
        or result.get("capacity_contract") != plan.get("capacity_contract")
    ):
        raise ValueError("execution probe requires a hash-valid momentum-v2 historical ACCEPT")
    audit = result.get("data_access_audit")
    if (
        not isinstance(audit, Mapping)
        or audit.get("network_access") is not False
        or audit.get("grid_search") is not False
        or audit.get("retune") is not False
    ):
        raise ValueError("momentum-v2 OOS result violates the frozen data-access contract")
    return plan, plan_path, result, result_path


def _utc_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _execution_windows(target_entry_day: int) -> list[dict[str, Any]]:
    first_start_ts = int(target_entry_day) * DAY_SEC + WINDOW_PREP_BUFFER_SEC
    return [
        {
            "index": index,
            "start_ts": first_start_ts + index * WINDOW_START_SEPARATION_SEC,
            "start_utc": _utc_iso(
                first_start_ts + index * WINDOW_START_SEPARATION_SEC
            ),
            "end_ts": (
                first_start_ts
                + index * WINDOW_START_SEPARATION_SEC
                + WINDOW_DURATION_SEC
            ),
            "end_utc": _utc_iso(
                first_start_ts
                + index * WINDOW_START_SEPARATION_SEC
                + WINDOW_DURATION_SEC
            ),
        }
        for index in range(WINDOW_COUNT)
    ]


def build_execution_probe_plan(
    *,
    oos_plan_path: str | Path,
    expected_oos_plan_hash: str,
    oos_result_path: str | Path,
    expected_oos_result_hash: str,
    output_path: str | Path | None,
    run_id: str,
    not_before_day: int,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    lower_bound_day = int(not_before_day)
    if lower_bound_day < 0:
        raise ValueError("not_before_day must be non-negative")

    oos_plan, resolved_plan_path, oos_result, resolved_result_path = _validate_oos_accept(
        oos_plan_path=oos_plan_path,
        expected_oos_plan_hash=expected_oos_plan_hash,
        oos_result_path=oos_result_path,
        expected_oos_result_hash=expected_oos_result_hash,
    )
    schedule = oos_plan.get("rebalance_schedule_contract")
    oos_input = oos_plan.get("oos_input")
    if not isinstance(schedule, Mapping) or not isinstance(oos_input, Mapping):
        raise ValueError("momentum-v2 OOS plan schedule/input contract is missing")
    oos_range = oos_input.get("range")
    if not isinstance(oos_range, Mapping):
        raise ValueError("momentum-v2 OOS range is missing")
    oos_end_sec = int(oos_range.get("end_sec") or 0)
    if oos_end_sec <= 0 or oos_end_sec % DAY_SEC:
        raise ValueError("momentum-v2 OOS end must be UTC day aligned")
    anchor_day = int(schedule.get("anchor_day") or -1)
    cadence_days = int(schedule.get("cadence_days") or 0)
    if schedule.get("semantics") != v2_train.REBALANCE_SCHEDULE_SEMANTICS:
        raise ValueError("momentum-v2 execution probe requires the global train anchor")
    target_signal_day = v2_train._first_scheduled_day_at_or_after(
        anchor_day=anchor_day,
        lower_bound_day=max(oos_end_sec // DAY_SEC, lower_bound_day),
        cadence_days=cadence_days,
    )
    target_entry_day = target_signal_day + 1
    windows = _execution_windows(target_entry_day)

    module_paths = {
        "module": Path(__file__).resolve(),
        "oos_module": Path(v2_oos.__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
        "history_plan_module": Path(v3_history_plan.__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    contract: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "gate_membership_momentum_v2_execution_probe_planonly",
        "stage": "execution_capacity_probe_planonly",
        "decision": PLAN_DECISION,
        "hypothesis_id": oos_plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "public_api_only": True,
        "grid_search": False,
        "retune": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "historical_authorization": {
            "oos_plan_path": str(resolved_plan_path),
            "oos_plan_sha256": v3_history_plan.sha256_file(resolved_plan_path),
            "oos_plan_hash": str(oos_plan["plan_hash"]),
            "oos_result_path": str(resolved_result_path),
            "oos_result_sha256": v3_history_plan.sha256_file(resolved_result_path),
            "oos_result_hash": str(oos_result["deterministic_result_hash"]),
            "decision": v2_oos.HISTORICAL_ACCEPT_DECISION,
        },
        "strategy": oos_plan["strategy"],
        "cost_contract": oos_plan["cost_contract"],
        "rebalance_schedule_contract": dict(schedule),
        "target_event_contract": {
            "semantics": v2_train.REBALANCE_SCHEDULE_SEMANTICS,
            "anchor_day": anchor_day,
            "cadence_days": cadence_days,
            "oos_end_day": oos_end_sec // DAY_SEC,
            "not_before_day": lower_bound_day,
            "target_signal_day": target_signal_day,
            "target_signal_close_ts": (target_signal_day + 1) * DAY_SEC,
            "target_entry_day": target_entry_day,
            "target_entry_ts": target_entry_day * DAY_SEC,
        },
        "selection_contract": {
            "selection_source": "point_in_time_gate_universe_at_target_signal",
            "selection_timing": "after_target_signal_closed_daily_bar_before_first_snapshot",
            "selection_price": "target_signal_closed_daily_close",
            "strategy": oos_plan["strategy"],
            "canonical_asset_id_required": True,
            "binance_spot_exclusion_required": True,
            "lifecycle_valid_at_target_signal_required": True,
            "oos_event_frequency_used": False,
            "oos_event_asset_names_used": False,
            "manual_shortlist": False,
            "selection_artifact_required": True,
            "selection_artifact_frozen_before_first_snapshot": True,
            "minimum_scored_markets": int(oos_plan["strategy"]["minimum_scored_markets"]),
            "minimum_assets_per_side": int(oos_plan["strategy"]["min_per_side"]),
            "bucket_rule": str(oos_plan["strategy"]["bucket_rule"]),
        },
        "execution_contract": {
            "target_entry_ts": target_entry_day * DAY_SEC,
            "windows": windows,
            "window_count": WINDOW_COUNT,
            "duration_sec": WINDOW_DURATION_SEC,
            "interval_sec": SAMPLE_INTERVAL_SEC,
            "selected_buckets": ["long", "short"],
            "book_walk_sides": ["buy", "sell"],
            "notional_quote_per_asset": MINIMUM_CAPACITY_QUOTE_PER_ASSET,
            "minimum_valid_snapshots_per_asset_per_window": (
                MINIMUM_VALID_SNAPSHOTS_PER_ASSET_PER_WINDOW
            ),
            "minimum_coverage_per_asset": MINIMUM_COVERAGE_PER_ASSET,
            "maximum_timestamp_skew_ms": MAXIMUM_TIMESTAMP_SKEW_MS,
            "maximum_quote_age_ms": MAXIMUM_QUOTE_AGE_MS,
            "minimum_capacity_quote_per_asset": MINIMUM_CAPACITY_QUOTE_PER_ASSET,
            "maximum_p95_impact_bps": MAXIMUM_P95_IMPACT_BPS,
            "critical_schema_reconnect_or_stale_quote_errors_allowed": 0,
        },
        "code_provenance": code_provenance,
        "maximum_authority": "EXECUTION_PROBE_PLANONLY",
        "next_allowed_command": "fast-edge-membership-momentum-v2-execution-selection",
        "blocked_actions": [
            "oos_frequency_shortlist",
            "manual_shortlist",
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
        "limitations": [
            "Historical OHLCV does not prove fill, impact, or executable capacity.",
            "The portfolio must be selected causally after the target signal daily close.",
            "This PlanOnly grants no paper-forward or live authority.",
        ],
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "oos_plan_hash": contract["historical_authorization"]["oos_plan_hash"],
            "oos_plan_sha256": contract["historical_authorization"]["oos_plan_sha256"],
            "oos_result_hash": contract["historical_authorization"]["oos_result_hash"],
            "oos_result_sha256": contract["historical_authorization"]["oos_result_sha256"],
            "not_before_day": lower_bound_day,
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(contract)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": plan_hash,
        "frozen_contract": contract,
    }
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def validate_execution_probe_plan(
    path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    plan = v2_train._read_json_object(resolved)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected momentum-v2 execution-probe PlanOnly artifact")
    if not isinstance(frozen, Mapping):
        raise ValueError("momentum-v2 execution-probe frozen contract is missing")
    computed_hash = v3_history_plan.sha256_json(frozen)
    if (
        str(plan.get("plan_hash") or "") != computed_hash
        or (expected_plan_hash is not None and str(expected_plan_hash) != computed_hash)
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 execution-probe plan hash mismatch")

    authorization = plan.get("historical_authorization")
    if not isinstance(authorization, Mapping):
        raise ValueError("momentum-v2 historical authorization is missing")
    oos_plan, oos_plan_path, _oos_result, oos_result_path = _validate_oos_accept(
        oos_plan_path=str(authorization.get("oos_plan_path") or ""),
        expected_oos_plan_hash=str(authorization.get("oos_plan_hash") or ""),
        oos_result_path=str(authorization.get("oos_result_path") or ""),
        expected_oos_result_hash=str(authorization.get("oos_result_hash") or ""),
    )
    if (
        authorization.get("oos_plan_sha256") != v3_history_plan.sha256_file(oos_plan_path)
        or authorization.get("oos_result_sha256")
        != v3_history_plan.sha256_file(oos_result_path)
    ):
        raise ValueError("momentum-v2 historical authorization file hash mismatch")
    schedule = oos_plan["rebalance_schedule_contract"]
    target = plan.get("target_event_contract")
    execution = plan.get("execution_contract")
    selection = plan.get("selection_contract")
    if not all(isinstance(value, Mapping) for value in (target, execution, selection)):
        raise ValueError("momentum-v2 execution-probe contracts are missing")
    oos_end_day = int(oos_plan["oos_input"]["range"]["end_sec"]) // DAY_SEC
    expected_signal_day = v2_train._first_scheduled_day_at_or_after(
        anchor_day=int(schedule["anchor_day"]),
        lower_bound_day=max(oos_end_day, int(target["not_before_day"])),
        cadence_days=int(schedule["cadence_days"]),
    )
    expected_target = {
        "semantics": v2_train.REBALANCE_SCHEDULE_SEMANTICS,
        "anchor_day": int(schedule["anchor_day"]),
        "cadence_days": int(schedule["cadence_days"]),
        "oos_end_day": oos_end_day,
        "not_before_day": int(target["not_before_day"]),
        "target_signal_day": expected_signal_day,
        "target_signal_close_ts": (expected_signal_day + 1) * DAY_SEC,
        "target_entry_day": expected_signal_day + 1,
        "target_entry_ts": (expected_signal_day + 1) * DAY_SEC,
    }
    if dict(target) != expected_target:
        raise ValueError("momentum-v2 execution-probe target event is not globally anchored")
    expected_execution = {
        "target_entry_ts": (expected_signal_day + 1) * DAY_SEC,
        "windows": _execution_windows(expected_signal_day + 1),
        "window_count": WINDOW_COUNT,
        "duration_sec": WINDOW_DURATION_SEC,
        "interval_sec": SAMPLE_INTERVAL_SEC,
        "selected_buckets": ["long", "short"],
        "book_walk_sides": ["buy", "sell"],
        "notional_quote_per_asset": MINIMUM_CAPACITY_QUOTE_PER_ASSET,
        "minimum_valid_snapshots_per_asset_per_window": (
            MINIMUM_VALID_SNAPSHOTS_PER_ASSET_PER_WINDOW
        ),
        "minimum_coverage_per_asset": MINIMUM_COVERAGE_PER_ASSET,
        "maximum_timestamp_skew_ms": MAXIMUM_TIMESTAMP_SKEW_MS,
        "maximum_quote_age_ms": MAXIMUM_QUOTE_AGE_MS,
        "minimum_capacity_quote_per_asset": MINIMUM_CAPACITY_QUOTE_PER_ASSET,
        "maximum_p95_impact_bps": MAXIMUM_P95_IMPACT_BPS,
        "critical_schema_reconnect_or_stale_quote_errors_allowed": 0,
    }
    if dict(execution) != expected_execution:
        raise ValueError("momentum-v2 execution-probe execution contract mismatch")
    expected_selection = {
        "selection_source": "point_in_time_gate_universe_at_target_signal",
        "selection_timing": "after_target_signal_closed_daily_bar_before_first_snapshot",
        "selection_price": "target_signal_closed_daily_close",
        "strategy": oos_plan["strategy"],
        "canonical_asset_id_required": True,
        "binance_spot_exclusion_required": True,
        "lifecycle_valid_at_target_signal_required": True,
        "oos_event_frequency_used": False,
        "oos_event_asset_names_used": False,
        "manual_shortlist": False,
        "selection_artifact_required": True,
        "selection_artifact_frozen_before_first_snapshot": True,
        "minimum_scored_markets": int(oos_plan["strategy"]["minimum_scored_markets"]),
        "minimum_assets_per_side": int(oos_plan["strategy"]["min_per_side"]),
        "bucket_rule": str(oos_plan["strategy"]["bucket_rule"]),
    }
    if (
        dict(selection) != expected_selection
        or "candidates" in plan
        or "events" in plan
    ):
        raise ValueError("momentum-v2 execution-probe selection contract is not causal")
    if (
        plan.get("network_access") is not False
        or plan.get("grid_search") is not False
        or plan.get("retune") is not False
        or plan.get("paper_forward_allowed") is not False
        or plan.get("live_orders") is not False
        or plan.get("private_api_keys") is not False
        or plan.get("leverage_or_margin") is not False
        or plan.get("next_allowed_command")
        != "fast-edge-membership-momentum-v2-execution-selection"
    ):
        raise ValueError("momentum-v2 execution-probe safety contract was loosened")
    code = plan.get("code_provenance")
    expected_paths = {
        "module": Path(__file__).resolve(),
        "oos_module": Path(v2_oos.__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
        "history_plan_module": Path(v3_history_plan.__file__).resolve(),
    }
    if not isinstance(code, Mapping):
        raise ValueError("momentum-v2 execution-probe code provenance is missing")
    for name, expected_path in expected_paths.items():
        actual_path = Path(str(code.get(f"{name}_path") or "")).expanduser().resolve()
        if (
            actual_path != expected_path
            or not actual_path.is_file()
            or code.get(f"{name}_sha256") != v3_history_plan.sha256_file(actual_path)
        ):
            raise ValueError(f"momentum-v2 execution-probe module hash mismatch: {name}")
    expected_input_merkle = v3_history_plan.sha256_json(
        {
            "oos_plan_hash": authorization["oos_plan_hash"],
            "oos_plan_sha256": authorization["oos_plan_sha256"],
            "oos_result_hash": authorization["oos_result_hash"],
            "oos_result_sha256": authorization["oos_result_sha256"],
            "not_before_day": int(target["not_before_day"]),
            **{
                key: value
                for key, value in code.items()
                if key.endswith("_sha256")
            },
        }
    )
    if plan.get("input_merkle_sha256") != expected_input_merkle:
        raise ValueError("momentum-v2 execution-probe input merkle mismatch")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate membership momentum-v2 execution-probe PlanOnly"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--oos-plan", required=True)
    plan_parser.add_argument("--expected-oos-plan-hash", required=True)
    plan_parser.add_argument("--oos-result", required=True)
    plan_parser.add_argument("--expected-oos-result-hash", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--not-before-day", required=True, type=int)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash")
    args = parser.parse_args()

    if args.command == "plan":
        payload = build_execution_probe_plan(
            oos_plan_path=args.oos_plan,
            expected_oos_plan_hash=args.expected_oos_plan_hash,
            oos_result_path=args.oos_result,
            expected_oos_result_hash=args.expected_oos_result_hash,
            output_path=args.output,
            run_id=args.run_id,
            not_before_day=args.not_before_day,
        )
    else:
        plan = validate_execution_probe_plan(args.plan, args.expected_plan_hash)
        payload = {
            "schema": "trading_mvp_gate_membership_momentum_v2_execution_probe_validation_v1",
            "valid": True,
            "plan_path": str(Path(args.plan).expanduser().resolve()),
            "plan_hash": plan["plan_hash"],
            "decision": plan["decision"],
            "next_allowed_command": plan["next_allowed_command"],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
