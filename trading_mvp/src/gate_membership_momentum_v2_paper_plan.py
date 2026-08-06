from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import gate_historical_membership_v3_history_plan as v3_history_plan
import gate_membership_momentum_v2_execution_probe as probe
import gate_membership_momentum_v2_execution_probe_runtime as runtime
import gate_membership_momentum_v2_execution_selection as selection
import gate_membership_momentum_v2_oos as v2_oos
import gate_membership_momentum_v2_train as v2_train


PLAN_SCHEMA = "trading_mvp_gate_membership_momentum_v2_paper_plan_v1"
PLAN_DECISION = "GATE_MEMBERSHIP_MOMENTUM_V2_PAPER_PLAN_READY_REQUIRES_EXPLICIT_APPROVAL"
MINIMUM_INDEPENDENT_EVENTS = 15
MAXIMUM_PAPER_SEGMENT_SEC = 1_200


def paper_plan_hash(payload: Mapping[str, Any]) -> str:
    frozen = payload.get("frozen_contract")
    if isinstance(frozen, Mapping):
        return v3_history_plan.sha256_json(frozen)
    return v3_history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "plan_hash", "approval_phrase"}
        }
    )


def approval_phrase(plan_hash: str) -> str:
    digest = v2_train._validate_hash(plan_hash, label="paper plan hash")
    return (
        "Подтверждаю visible Gate membership-momentum-v2 paper-forward "
        f"plan_hash={digest}, короткими public-data сегментами <=20 минут, "
        "без live/private API keys/leverage/margin."
    )


def _validate_execution_report(
    path: str | Path,
    expected_result_hash: str,
) -> tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    report = v2_train._read_json_object(resolved)
    expected = v2_train._validate_hash(
        expected_result_hash,
        label="execution report result hash",
    )
    if (
        report.get("schema") != runtime.REPORT_SCHEMA
        or report.get("final") is not True
        or report.get("verdict") != runtime.PAPER_FORWARD_READY_DECISION
        or report.get("historical_oos_decision") != v2_oos.HISTORICAL_ACCEPT_DECISION
        or report.get("next_allowed_command")
        != "fast-edge-membership-momentum-v2-paper-plan"
        or report.get("maximum_authority") != "PAPER_FORWARD_PLANONLY"
    ):
        raise ValueError("paper PlanOnly requires a final PAPER_FORWARD_READY execution report")
    stored = str(report.get("deterministic_result_hash") or "")
    if stored != runtime._artifact_hash(report) or stored != expected:
        raise ValueError("execution report deterministic hash mismatch")
    if any(
        report.get(field) is not False
        for field in (
            "network_access",
            "grid_search",
            "retune",
            "live_orders",
            "private_api_keys",
            "leverage_or_margin",
        )
    ):
        raise ValueError("execution report safety contract was loosened")

    probe_auth = report.get("probe_plan")
    selection_auth = report.get("selection")
    if not isinstance(probe_auth, Mapping) or not isinstance(selection_auth, Mapping):
        raise ValueError("execution report source authorizations are missing")
    probe_path = Path(str(probe_auth.get("path") or "")).expanduser().resolve()
    selection_path = Path(str(selection_auth.get("path") or "")).expanduser().resolve()
    probe_plan = probe.validate_execution_probe_plan(
        probe_path,
        str(probe_auth.get("plan_hash") or ""),
    )
    selected = selection.validate_selection_artifact(
        selection_path,
        str(selection_auth.get("artifact_hash") or ""),
    )
    if (
        probe_auth.get("file_sha256") != v3_history_plan.sha256_file(probe_path)
        or selection_auth.get("file_sha256") != v3_history_plan.sha256_file(selection_path)
    ):
        raise ValueError("execution report source file hash mismatch")
    selection_probe = selected.get("probe_plan_authorization")
    if not isinstance(selection_probe, Mapping) or (
        Path(str(selection_probe.get("path") or "")).expanduser().resolve() != probe_path
        or selection_probe.get("plan_hash") != probe_plan["plan_hash"]
    ):
        raise ValueError("execution report selection belongs to another probe plan")

    window_rows = report.get("windows")
    if not isinstance(window_rows, list) or len(window_rows) != probe.WINDOW_COUNT:
        raise ValueError("execution report must contain all three probe windows")
    windows_by_index: dict[int, tuple[dict[str, Any], dict[str, Any], Path]] = {}
    for raw in window_rows:
        if not isinstance(raw, Mapping):
            raise ValueError("execution report window is not an object")
        index = int(raw.get("index", -1))
        if index in windows_by_index:
            raise ValueError("execution report contains a duplicate window")
        manifest_path = Path(str(raw.get("manifest_path") or "")).expanduser().resolve()
        manifest, metrics, verified_path = runtime._validate_manifest(
            manifest_path,
            expected_probe_hash=probe_plan["plan_hash"],
            expected_selection_hash=selected["artifact_hash"],
        )
        if (
            raw.get("manifest_file_sha256")
            != v3_history_plan.sha256_file(verified_path)
            or raw.get("manifest_result_hash") != manifest["deterministic_result_hash"]
            or raw.get("metrics") != metrics
        ):
            raise ValueError("execution report window provenance mismatch")
        windows_by_index[index] = (manifest, metrics, verified_path)
    if sorted(windows_by_index) != list(range(probe.WINDOW_COUNT)):
        raise ValueError("execution report window indexes are incomplete")

    selected_assets = sorted(
        str(row["canonical_asset_id"]) for row in selected["selected_positions"]
    )
    eligible_sets = [
        set(windows_by_index[index][1]["eligible_assets"])
        for index in range(probe.WINDOW_COUNT)
    ]
    execution_eligible = sorted(set.intersection(*eligible_sets))
    critical_errors = sum(
        int(windows_by_index[index][0].get("critical_error_count") or 0)
        for index in range(probe.WINDOW_COUNT)
    )
    if (
        report.get("selected_assets") != selected_assets
        or report.get("execution_eligible_assets") != execution_eligible
        or report.get("all_selected_assets_eligible") is not True
        or execution_eligible != selected_assets
        or int(report.get("critical_error_count") or 0) != critical_errors
        or critical_errors != 0
        or report.get("rejection_reasons") != []
    ):
        raise ValueError("execution report PAPER_FORWARD_READY evidence is inconsistent")
    expected_merkle = v3_history_plan.sha256_json(
        {
            "probe_plan_hash": probe_plan["plan_hash"],
            "selection_hash": selected["artifact_hash"],
            "window_result_hashes": [
                windows_by_index[index][0]["deterministic_result_hash"]
                for index in range(probe.WINDOW_COUNT)
            ],
        }
    )
    if report.get("input_merkle_sha256") != expected_merkle:
        raise ValueError("execution report input Merkle mismatch")
    return report, resolved, probe_plan, selected


def _paper_contract(probe_plan: Mapping[str, Any]) -> dict[str, Any]:
    strategy = probe_plan["strategy"]
    schedule = probe_plan["rebalance_schedule_contract"]
    target = probe_plan["target_event_contract"]
    execution = probe_plan["execution_contract"]
    cadence = int(schedule["cadence_days"])
    first_signal_day = int(target["target_signal_day"]) + cadence
    return {
        "minimum_independent_events": MINIMUM_INDEPENDENT_EVENTS,
        "global_anchor_day": int(schedule["anchor_day"]),
        "event_cadence_days": cadence,
        "first_paper_signal_day": first_signal_day,
        "hold_days": int(strategy["hold_days"]),
        "lookback_days": int(strategy["lookback_days"]),
        "notional_quote_per_asset": float(execution["notional_quote_per_asset"]),
        "selection_artifact_required": True,
        "selection_timing": "after_closed_signal_bar_before_entry_execution_window",
        "selection_must_use_same_hash_bound_strategy": True,
        "manual_shortlist_allowed": False,
        "entry_execution_evidence_required": True,
        "exit_execution_evidence_required": True,
        "execution_windows_per_boundary": int(execution["window_count"]),
        "execution_window_duration_sec": int(execution["duration_sec"]),
        "maximum_segment_duration_sec": MAXIMUM_PAPER_SEGMENT_SEC,
        "minimum_valid_snapshots_per_asset_per_window": int(
            execution["minimum_valid_snapshots_per_asset_per_window"]
        ),
        "minimum_coverage_per_asset": float(execution["minimum_coverage_per_asset"]),
        "maximum_timestamp_skew_ms": float(execution["maximum_timestamp_skew_ms"]),
        "maximum_quote_age_ms": float(execution["maximum_quote_age_ms"]),
        "minimum_capacity_quote_per_asset": float(
            execution["minimum_capacity_quote_per_asset"]
        ),
        "maximum_p95_impact_bps": float(execution["maximum_p95_impact_bps"]),
        "funding_settlement_evidence_required": True,
        "manual_pnl_allowed": False,
        "position_state_required": True,
        "append_only_event_ledger_required": True,
        "deterministic_reconciliation_required": True,
        "kill_switch_on_data_quality_or_execution_breach": True,
        "acceptance_gates": {
            "minimum_independent_events": MINIMUM_INDEPENDENT_EVENTS,
            "paper_total_net_pnl_quote_gt": 0.0,
            "paper_total_net_expectancy_quote_gt": 0.0,
            "profit_factor_gte": 1.2,
            "stress_net_pnl_quote_gte": 0.0,
            "reconciliation_violations": 0,
            "kill_switch_violations": 0,
            "maximum_single_event_positive_pnl_share": 0.25,
        },
    }


def build_paper_plan(
    *,
    execution_report_path: str | Path,
    expected_execution_report_hash: str,
    output_path: str | Path | None,
    run_id: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    report, resolved_report, probe_plan, selected = _validate_execution_report(
        execution_report_path,
        expected_execution_report_hash,
    )
    module_paths = {
        "module": Path(__file__).resolve(),
        "execution_runtime_module": Path(runtime.__file__).resolve(),
        "execution_probe_module": Path(probe.__file__).resolve(),
        "selection_module": Path(selection.__file__).resolve(),
        "oos_module": Path(v2_oos.__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
    }
    code_provenance = {
        f"{name}_path": str(path) for name, path in module_paths.items()
    } | {
        f"{name}_sha256": v3_history_plan.sha256_file(path)
        for name, path in module_paths.items()
    }
    report_file_hash = v3_history_plan.sha256_file(resolved_report)
    contract: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "mode": "PlanOnly",
        "stage": "paper_forward_planonly",
        "decision": PLAN_DECISION,
        "hypothesis_id": probe_plan["hypothesis_id"],
        "research_only": True,
        "network_access": False,
        "public_data_only": True,
        "grid_search": False,
        "retune": False,
        "paper_forward_started": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "requires_explicit_user_approval_for_paper_forward": True,
        "execution_report_authorization": {
            "path": str(resolved_report),
            "file_sha256": report_file_hash,
            "result_hash": report["deterministic_result_hash"],
            "verdict": runtime.PAPER_FORWARD_READY_DECISION,
            "probe_plan_hash": probe_plan["plan_hash"],
            "selection_hash": selected["artifact_hash"],
        },
        "strategy": probe_plan["strategy"],
        "cost_contract": probe_plan["cost_contract"],
        "rebalance_schedule_contract": probe_plan["rebalance_schedule_contract"],
        "paper_contract": _paper_contract(probe_plan),
        "code_provenance": code_provenance,
        "maximum_authority": "PAPER_FORWARD_PLANONLY",
        "next_allowed_action": "request_explicit_hash_bound_paper_forward_approval",
        "blocked_actions": [
            "paper_forward_without_exact_plan_hash_approval",
            "manual_pnl",
            "manual_shortlist",
            "grid_search",
            "retune",
            "live_orders",
            "private_api_keys",
            "leverage",
            "margin",
        ],
        "limitations": [
            "This PlanOnly does not start paper-forward collection or positions.",
            "Each paper event requires new causal selection plus entry and exit execution evidence.",
            "LIVE_REVIEW_ELIGIBLE still requires fifteen independent reconciled paper events.",
        ],
    }
    contract["input_merkle_sha256"] = v3_history_plan.sha256_json(
        {
            "execution_report_result_hash": report["deterministic_result_hash"],
            "execution_report_file_sha256": report_file_hash,
            "probe_plan_hash": probe_plan["plan_hash"],
            "selection_hash": selected["artifact_hash"],
            **{
                key: value
                for key, value in code_provenance.items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = v3_history_plan.sha256_json(contract)
    phrase = approval_phrase(plan_hash)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc,
        "plan_hash": plan_hash,
        "approval_phrase": phrase,
        "next_allowed_command": phrase,
        "frozen_contract": contract,
    }
    if payload["generated_at_utc"] is None:
        from datetime import datetime, timezone

        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    if output_path is not None:
        v2_train._write_json_immutable(output_path, payload)
    return payload


def validate_paper_plan(
    path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    plan = v2_train._read_json_object(resolved)
    frozen = plan.get("frozen_contract")
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("mode") != "PlanOnly"
        or plan.get("decision") != PLAN_DECISION
        or not isinstance(frozen, Mapping)
    ):
        raise ValueError("unexpected momentum-v2 paper PlanOnly artifact")
    computed_hash = v3_history_plan.sha256_json(frozen)
    if (
        plan.get("plan_hash") != computed_hash
        or (expected_plan_hash is not None and str(expected_plan_hash) != computed_hash)
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("momentum-v2 paper PlanOnly hash mismatch")
    phrase = approval_phrase(computed_hash)
    if plan.get("approval_phrase") != phrase or plan.get("next_allowed_command") != phrase:
        raise ValueError("momentum-v2 paper approval boundary mismatch")
    if plan.get("requires_explicit_user_approval_for_paper_forward") is not True:
        raise ValueError("momentum-v2 paper-forward must require explicit approval")
    if any(
        plan.get(field) is not False
        for field in (
            "network_access",
            "grid_search",
            "retune",
            "paper_forward_started",
            "live_orders",
            "private_api_keys",
            "leverage_or_margin",
        )
    ):
        raise ValueError("momentum-v2 paper PlanOnly safety contract was loosened")

    authorization = plan.get("execution_report_authorization")
    if not isinstance(authorization, Mapping):
        raise ValueError("momentum-v2 paper execution authorization is missing")
    report, report_path, probe_plan, selected = _validate_execution_report(
        str(authorization.get("path") or ""),
        str(authorization.get("result_hash") or ""),
    )
    expected_authorization = {
        "path": str(report_path),
        "file_sha256": v3_history_plan.sha256_file(report_path),
        "result_hash": report["deterministic_result_hash"],
        "verdict": runtime.PAPER_FORWARD_READY_DECISION,
        "probe_plan_hash": probe_plan["plan_hash"],
        "selection_hash": selected["artifact_hash"],
    }
    if dict(authorization) != expected_authorization:
        raise ValueError("momentum-v2 paper execution authorization mismatch")
    paper_contract = plan.get("paper_contract")
    if not isinstance(paper_contract, Mapping):
        raise ValueError("momentum-v2 paper contract is missing")
    if int(paper_contract.get("minimum_independent_events") or 0) != MINIMUM_INDEPENDENT_EVENTS:
        raise ValueError("momentum-v2 paper minimum independent events gate mismatch")
    if dict(paper_contract) != _paper_contract(probe_plan):
        raise ValueError("momentum-v2 paper contract mismatch")
    if (
        plan.get("strategy") != probe_plan["strategy"]
        or plan.get("cost_contract") != probe_plan["cost_contract"]
        or plan.get("rebalance_schedule_contract")
        != probe_plan["rebalance_schedule_contract"]
    ):
        raise ValueError("momentum-v2 paper strategy/economics/schedule mismatch")

    code = plan.get("code_provenance")
    expected_paths = {
        "module": Path(__file__).resolve(),
        "execution_runtime_module": Path(runtime.__file__).resolve(),
        "execution_probe_module": Path(probe.__file__).resolve(),
        "selection_module": Path(selection.__file__).resolve(),
        "oos_module": Path(v2_oos.__file__).resolve(),
        "train_module": Path(v2_train.__file__).resolve(),
    }
    if not isinstance(code, Mapping):
        raise ValueError("momentum-v2 paper code provenance is missing")
    for name, expected_path in expected_paths.items():
        if (
            Path(str(code.get(f"{name}_path") or "")).expanduser().resolve()
            != expected_path
            or code.get(f"{name}_sha256") != v3_history_plan.sha256_file(expected_path)
        ):
            raise ValueError(f"momentum-v2 paper code provenance mismatch: {name}")
    expected_merkle = v3_history_plan.sha256_json(
        {
            "execution_report_result_hash": report["deterministic_result_hash"],
            "execution_report_file_sha256": v3_history_plan.sha256_file(report_path),
            "probe_plan_hash": probe_plan["plan_hash"],
            "selection_hash": selected["artifact_hash"],
            **{
                key: value for key, value in code.items() if key.endswith("_sha256")
            },
        }
    )
    if plan.get("input_merkle_sha256") != expected_merkle:
        raise ValueError("momentum-v2 paper input Merkle mismatch")
    return plan


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate membership-momentum-v2 paper-forward PlanOnly"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--execution-report", required=True)
    plan.add_argument("--expected-execution-report-hash", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--run-id", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        result = build_paper_plan(
            execution_report_path=args.execution_report,
            expected_execution_report_hash=args.expected_execution_report_hash,
            output_path=args.output,
            run_id=args.run_id,
        )
    else:
        plan = validate_paper_plan(args.plan, args.expected_plan_hash)
        result = {
            "schema": "trading_mvp_gate_membership_momentum_v2_paper_plan_validation_v1",
            "valid": True,
            "plan_path": str(Path(args.plan).expanduser().resolve()),
            "plan_hash": plan["plan_hash"],
            "decision": plan["decision"],
            "next_allowed_command": plan["next_allowed_command"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
