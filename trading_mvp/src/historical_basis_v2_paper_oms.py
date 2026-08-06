from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import basis_paper_oms as core
from historical_basis_code_snapshot import require_plan_runtime_code_snapshot
from historical_basis_v2 import sha256_file, sha256_json, validate_historical_basis_v2_plan
from historical_basis_v2_execution_probe import (
    REPORT_SCHEMA as PROBE_REPORT_SCHEMA,
    _validate_probe_manifest,
    artifact_hash as probe_artifact_hash,
    validate_execution_probe_plan,
)
from paper_execution_guard import evaluate_depth_execution_guard


HYPOTHESIS_ID = "cross_venue_perp_basis_convergence_1h_v2"
PAPER_PLAN_SCHEMA = "trading_mvp_historical_basis_v2_paper_plan_v1"
STATE_SCHEMA = "trading_mvp_historical_basis_v2_paper_oms_state_v1"
LEDGER_EVENT_SCHEMA = "trading_mvp_historical_basis_v2_paper_oms_event_v1"
MINIMUM_INDEPENDENT_PAPER_EVENTS = 15


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _deterministic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        ignored = {
            "generated_at_utc",
            "module_path",
            "path",
            "runtime_sec",
        }
        return {
            str(key): _deterministic_value(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            if str(key) not in ignored
        }
    if isinstance(value, (list, tuple)):
        return [_deterministic_value(item) for item in value]
    return value


def paper_plan_hash(payload: Mapping[str, Any]) -> str:
    root = {key: value for key, value in payload.items() if key != "paper_plan_hash"}
    return sha256_json(_deterministic_value(root))


def _validate_probe_report(
    report_path: str | Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path, dict[str, Any], Path]:
    report_target = Path(report_path).expanduser().resolve()
    report = _read_json(report_target)
    if report.get("schema") != PROBE_REPORT_SCHEMA:
        raise ValueError(f"expected execution probe report schema {PROBE_REPORT_SCHEMA}")
    if report.get("deterministic_result_hash") != probe_artifact_hash(report):
        raise ValueError("execution probe report deterministic hash mismatch")
    if report.get("verdict") != "PAPER_FORWARD_READY":
        raise ValueError("paper PlanOnly requires PAPER_FORWARD_READY")
    safety = report.get("safety") or {}
    for key in ("live_orders", "private_api_keys", "leverage_or_margin", "grid_search", "retune"):
        if safety.get(key) is not False:
            raise ValueError(f"unsafe execution probe report flag: {key}")

    probe_reference = report.get("probe_plan") or {}
    probe_plan_target = Path(str(probe_reference.get("path") or "")).expanduser().resolve()
    if not probe_plan_target.is_file():
        raise ValueError("execution probe plan is missing")
    if sha256_file(probe_plan_target) != probe_reference.get("file_sha256"):
        raise ValueError("execution probe plan file hash mismatch")
    probe_plan = validate_execution_probe_plan(
        probe_plan_target,
        str(probe_reference.get("probe_plan_hash") or ""),
    )
    windows = report.get("windows") or []
    if len(windows) != 3:
        raise ValueError("execution probe report must contain exactly three windows")
    for expected_index, window in enumerate(windows):
        if int(window.get("index", -1)) != expected_index:
            raise ValueError("execution probe report window sequence mismatch")
        manifest_target = Path(str(window.get("manifest_path") or "")).expanduser().resolve()
        if not manifest_target.is_file():
            raise ValueError("execution probe report manifest is missing")
        if sha256_file(manifest_target) != window.get("manifest_file_sha256"):
            raise ValueError("execution probe report manifest file hash mismatch")
        manifest, metrics = _validate_probe_manifest(manifest_target, plan=probe_plan)
        if manifest.get("deterministic_result_hash") != window.get("manifest_result_hash"):
            raise ValueError("execution probe report manifest result hash mismatch")
        if metrics != window.get("metrics"):
            raise ValueError("execution probe report window metrics mismatch")

    historical_reference = probe_plan.get("historical_plan") or {}
    historical_plan_target = Path(str(historical_reference.get("path") or "")).expanduser().resolve()
    if not historical_plan_target.is_file():
        raise ValueError("historical plan is missing")
    if sha256_file(historical_plan_target) != historical_reference.get("file_sha256"):
        raise ValueError("historical plan file hash mismatch")
    historical_plan = _read_json(historical_plan_target)
    validation = validate_historical_basis_v2_plan(
        historical_plan_target,
        str(probe_plan.get("historical_plan_hash") or ""),
    )
    if validation["plan_hash"] != probe_plan.get("historical_plan_hash"):
        raise ValueError("historical plan hash mismatch")
    require_plan_runtime_code_snapshot(historical_plan, runtime_code_path=__file__)
    report_evaluation = report.get("historical_evaluation") or {}
    probe_evaluation = probe_plan.get("historical_evaluation") or {}
    for key in ("path", "file_sha256", "deterministic_result_hash"):
        if report_evaluation.get(key) != probe_evaluation.get(key):
            raise ValueError("execution probe report evaluation provenance mismatch")

    eligible = {str(base).strip().upper() for base in report.get("execution_eligible_bases") or []}
    qualifying = {
        str(base).strip().upper()
        for base in report.get("qualifying_execution_eligible_bases") or []
    }
    if not qualifying or not qualifying.issubset(eligible):
        raise ValueError("execution probe report has no qualifying eligible bases")
    return report, report_target, probe_plan, probe_plan_target, historical_plan, historical_plan_target


def build_historical_basis_v2_paper_plan(
    probe_report_path: str | Path,
    output_path: str | Path,
    *,
    minimum_independent_paper_events: int = MINIMUM_INDEPENDENT_PAPER_EVENTS,
) -> dict[str, Any]:
    if int(minimum_independent_paper_events) != MINIMUM_INDEPENDENT_PAPER_EVENTS:
        raise ValueError("minimum independent paper events is frozen at 15")
    report, report_target, probe_plan, probe_plan_target, historical_plan, historical_plan_target = (
        _validate_probe_report(probe_report_path)
    )
    qualifying = {
        str(base).strip().upper()
        for base in report["qualifying_execution_eligible_bases"]
    }
    candidates = [
        deepcopy(row)
        for row in historical_plan["universe"]["candidates"]
        if str(row.get("base") or "").strip().upper() in qualifying
    ]
    if {str(row["base"]).upper() for row in candidates} != qualifying:
        raise ValueError("paper universe cannot be reconciled with the historical plan")

    plan: dict[str, Any] = {
        "schema": PAPER_PLAN_SCHEMA,
        "mode": "PlanOnly",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hypothesis_id": HYPOTHESIS_ID,
        "execution_probe_report": {
            "path": str(report_target),
            "file_sha256": sha256_file(report_target),
            "deterministic_result_hash": report["deterministic_result_hash"],
        },
        "execution_probe_plan": {
            "path": str(probe_plan_target),
            "file_sha256": sha256_file(probe_plan_target),
            "probe_plan_hash": probe_plan["probe_plan_hash"],
        },
        "historical_plan": {
            "path": str(historical_plan_target),
            "file_sha256": sha256_file(historical_plan_target),
            "plan_hash": historical_plan["plan_hash"],
        },
        "code_provenance": deepcopy(historical_plan["code_provenance"]),
        "universe": {"candidate_count": len(candidates), "candidates": candidates},
        "strategy": deepcopy(historical_plan["strategy"]),
        "economics": deepcopy(historical_plan["economics"]),
        "execution_guard": {
            "required_for_position_transition": True,
            "notional_quote_per_leg": float(probe_plan["notional_quote_per_leg"]),
            "maximum_timestamp_skew_ms": float(probe_plan["maximum_timestamp_skew_ms"]),
            "maximum_quote_age_ms": float(probe_plan["interval_sec"]) * 1_000.0,
            "minimum_capacity_quote_per_leg": float(
                probe_plan["minimum_capacity_quote_per_leg"]
            ),
            "maximum_impact_bps": float(probe_plan["maximum_p95_impact_bps"]),
            "price_source": "synchronized_public_depth_vwap",
        },
        "minimum_independent_paper_events": MINIMUM_INDEPENDENT_PAPER_EVENTS,
        "acceptance_gates": {
            "minimum_independent_paper_events": MINIMUM_INDEPENDENT_PAPER_EVENTS,
            "paper_net_pnl_quote_strictly_positive": True,
            "reconciliation_violations": 0,
            "kill_switch_violations": 0,
            "data_quality_violations": 0,
        },
        "safety": {
            "paper_only": True,
            "public_data_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
            "grid_search": False,
            "retune": False,
        },
        "maximum_authority": "LIVE_REVIEW_ELIGIBLE",
        "next_allowed_command": "fast-edge-basis-v2-paper-init",
    }
    plan["paper_plan_hash"] = paper_plan_hash(plan)
    _write_json_immutable(output_path, plan)
    return plan


def validate_historical_basis_v2_paper_plan(
    path: str | Path,
    expected_paper_plan_hash: str | None = None,
) -> dict[str, Any]:
    plan_target = Path(path).expanduser().resolve()
    plan = _read_json(plan_target)
    if plan.get("schema") != PAPER_PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError(f"expected {PAPER_PLAN_SCHEMA} PlanOnly")
    if plan.get("paper_plan_hash") != paper_plan_hash(plan):
        raise ValueError("paper plan deterministic hash mismatch")
    if expected_paper_plan_hash and plan.get("paper_plan_hash") != expected_paper_plan_hash:
        raise ValueError("paper plan does not match expected hash")
    if int(plan.get("minimum_independent_paper_events") or 0) != MINIMUM_INDEPENDENT_PAPER_EVENTS:
        raise ValueError("paper plan minimum event count changed")
    safety = plan.get("safety") or {}
    for key in ("live_orders", "private_api_keys", "leverage_or_margin", "grid_search", "retune"):
        if safety.get(key) is not False:
            raise ValueError(f"paper plan safety contract was loosened: {key}")

    report_reference = plan.get("execution_probe_report") or {}
    report_target = Path(str(report_reference.get("path") or "")).expanduser().resolve()
    if not report_target.is_file() or sha256_file(report_target) != report_reference.get("file_sha256"):
        raise ValueError("execution probe report file provenance mismatch")
    report, _report_target, probe_plan, probe_plan_target, historical_plan, historical_plan_target = (
        _validate_probe_report(report_target)
    )
    if report_reference.get("deterministic_result_hash") != report.get("deterministic_result_hash"):
        raise ValueError("execution probe report hash provenance mismatch")
    if (plan.get("execution_probe_plan") or {}).get("file_sha256") != sha256_file(probe_plan_target):
        raise ValueError("execution probe plan provenance mismatch")
    if (plan.get("execution_probe_plan") or {}).get("probe_plan_hash") != probe_plan.get(
        "probe_plan_hash"
    ):
        raise ValueError("execution probe plan hash provenance mismatch")
    historical_reference = plan.get("historical_plan") or {}
    if historical_reference.get("file_sha256") != sha256_file(historical_plan_target):
        raise ValueError("historical plan provenance mismatch")
    if historical_reference.get("plan_hash") != historical_plan.get("plan_hash"):
        raise ValueError("historical plan hash provenance mismatch")
    if plan.get("code_provenance") != historical_plan.get("code_provenance"):
        raise ValueError("paper plan code provenance mismatch")
    if plan.get("strategy") != historical_plan.get("strategy"):
        raise ValueError("paper plan strategy differs from frozen historical strategy")
    if plan.get("economics") != historical_plan.get("economics"):
        raise ValueError("paper plan economics differs from frozen historical economics")
    expected_execution_guard = {
        "required_for_position_transition": True,
        "notional_quote_per_leg": float(probe_plan["notional_quote_per_leg"]),
        "maximum_timestamp_skew_ms": float(probe_plan["maximum_timestamp_skew_ms"]),
        "maximum_quote_age_ms": float(probe_plan["interval_sec"]) * 1_000.0,
        "minimum_capacity_quote_per_leg": float(probe_plan["minimum_capacity_quote_per_leg"]),
        "maximum_impact_bps": float(probe_plan["maximum_p95_impact_bps"]),
        "price_source": "synchronized_public_depth_vwap",
    }
    if plan.get("execution_guard") != expected_execution_guard:
        raise ValueError("paper plan execution guard differs from frozen execution probe")

    qualifying = {
        str(base).strip().upper()
        for base in report["qualifying_execution_eligible_bases"]
    }
    expected_candidates = [
        row
        for row in historical_plan["universe"]["candidates"]
        if str(row.get("base") or "").strip().upper() in qualifying
    ]
    if (plan.get("universe") or {}).get("candidates") != expected_candidates:
        raise ValueError("paper plan universe differs from execution-qualified universe")
    if int((plan.get("universe") or {}).get("candidate_count") or 0) != len(expected_candidates):
        raise ValueError("paper plan candidate count mismatch")
    return plan


def _validate_ready_chain(
    paper_plan_path: str | Path,
    probe_report_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_target = Path(paper_plan_path).expanduser().resolve()
    plan = validate_historical_basis_v2_paper_plan(plan_target)
    report_target = Path(probe_report_path).expanduser().resolve()
    report_reference = plan["execution_probe_report"]
    if report_target != Path(report_reference["path"]).expanduser().resolve():
        raise ValueError("paper OMS report path differs from frozen paper plan")
    if sha256_file(report_target) != report_reference["file_sha256"]:
        raise ValueError("paper OMS report file provenance mismatch")
    report = _read_json(report_target)
    return plan, report, {
        "plan_path": str(plan_target),
        "plan_file_sha256": sha256_file(plan_target),
        "plan_hash": plan["paper_plan_hash"],
        "report_path": str(report_target),
        "report_file_sha256": sha256_file(report_target),
        "report_semantic_hash": report["deterministic_result_hash"],
    }


def _contract() -> core.BasisPaperOmsContract:
    return core.BasisPaperOmsContract(
        state_schema=STATE_SCHEMA,
        ledger_event_schema=LEDGER_EVENT_SCHEMA,
        hypothesis_id=HYPOTHESIS_ID,
        ready_chain_validator=_validate_ready_chain,
        execution_guard=evaluate_depth_execution_guard,
    )


def initialize_historical_basis_v2_paper_oms(
    paper_plan_path: str | Path,
    probe_report_path: str | Path,
    *,
    ledger_path: str | Path,
    state_path: str | Path,
    daily_loss_limit_quote: float = 50.0,
) -> dict[str, Any]:
    return core.initialize_basis_paper_oms(
        paper_plan_path,
        probe_report_path,
        ledger_path=ledger_path,
        state_path=state_path,
        daily_loss_limit_quote=daily_loss_limit_quote,
        contract=_contract(),
    )


def apply_historical_basis_v2_paper_observation(
    paper_plan_path: str | Path,
    probe_report_path: str | Path,
    *,
    ledger_path: str | Path,
    state_path: str | Path,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    return core.apply_basis_paper_observation(
        paper_plan_path,
        probe_report_path,
        ledger_path=ledger_path,
        state_path=state_path,
        observation=dict(observation),
        contract=_contract(),
    )


def verify_historical_basis_v2_paper_ledger(path: str | Path) -> dict[str, Any]:
    return core.verify_basis_paper_ledger(path, contract=_contract())


def reconcile_historical_basis_v2_paper_state(
    state_path: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    return core.reconcile_basis_paper_state(
        state_path,
        ledger_path,
        contract=_contract(),
    )


def historical_basis_v2_paper_status(
    paper_plan_path: str | Path,
    *,
    ledger_path: str | Path,
    state_path: str | Path,
) -> dict[str, Any]:
    plan = validate_historical_basis_v2_paper_plan(paper_plan_path)
    contract = _contract()
    with core.paper_oms_single_writer_lock(
        ledger_path=ledger_path,
        state_path=state_path,
        operation="historical_basis_v2_paper_status",
    ):
        events = core._read_ledger_events(ledger_path, contract=contract)
        state = core._load_state(Path(state_path).expanduser().resolve(), contract=contract)
        reconciliation = reconcile_historical_basis_v2_paper_state(state_path, ledger_path)
        if state.get("plan_hash") != plan.get("paper_plan_hash"):
            raise ValueError("paper state belongs to another paper plan")
        if events[0].get("plan_hash") != plan.get("paper_plan_hash"):
            raise ValueError("paper ledger belongs to another paper plan")
        if state.get("report_semantic_hash") != plan["execution_probe_report"][
            "deterministic_result_hash"
        ]:
            raise ValueError("paper state report provenance mismatch")
        closed = [
            (event.get("details") or {}).get("closed_position")
            for event in events
            if event.get("event_type") == "POSITION_CLOSED"
        ]
        closed = [row for row in closed if isinstance(row, dict)]
        independent_ids = {
            str(row.get("position_id") or "")
            for row in closed
            if row.get("position_id")
        }
        net_pnl = sum(float(row.get("net_pnl_quote") or 0.0) for row in closed)
        minimum_events = int(plan["minimum_independent_paper_events"])
        violations = []
        if not reconciliation["matched"]:
            violations.append("reconciliation_mismatch")
        if state.get("status") == "HALTED" or state.get("kill_switch_reason"):
            violations.append("kill_switch_active")
        eligible = len(independent_ids) >= minimum_events and net_pnl > 0.0 and not violations
        return {
            "schema": "trading_mvp_historical_basis_v2_paper_status_v1",
            "paper_plan_hash": plan["paper_plan_hash"],
            "independent_paper_event_count": len(independent_ids),
            "minimum_independent_paper_events": minimum_events,
            "paper_net_pnl_quote": net_pnl,
            "open_position_count": len(state.get("positions") or {}),
            "blocked_execution_count": int(state.get("blocked_execution_count") or 0),
            "executed_transition_count": int(state.get("executed_transition_count") or 0),
            "last_execution_block_reason": state.get("last_execution_block_reason"),
            "reconciliation": reconciliation,
            "violations": violations,
            "verdict": "LIVE_REVIEW_ELIGIBLE" if eligible else "PAPER_FORWARD_ACTIVE",
            "maximum_authority": "LIVE_REVIEW_ELIGIBLE",
            "next_allowed_command": (
                "request-separate-live-review"
                if eligible
                else "fast-edge-basis-v2-paper-observe"
            ),
            "safety": deepcopy(plan["safety"]),
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper-only OMS for historical basis v2")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--probe-report", required=True)
    plan_parser.add_argument("--output", required=True)
    validate_parser = subparsers.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash")
    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--plan", required=True)
    init_parser.add_argument("--probe-report", required=True)
    init_parser.add_argument("--ledger", required=True)
    init_parser.add_argument("--state", required=True)
    init_parser.add_argument("--daily-loss-limit-quote", type=float, default=50.0)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--plan", required=True)
    observe_parser.add_argument("--probe-report", required=True)
    observe_parser.add_argument("--ledger", required=True)
    observe_parser.add_argument("--state", required=True)
    observe_parser.add_argument("--observation", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--plan", required=True)
    status_parser.add_argument("--ledger", required=True)
    status_parser.add_argument("--state", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        result = build_historical_basis_v2_paper_plan(args.probe_report, args.output)
    elif args.command == "validate-plan":
        result = validate_historical_basis_v2_paper_plan(args.plan, args.expected_plan_hash)
    elif args.command == "init":
        result = initialize_historical_basis_v2_paper_oms(
            args.plan,
            args.probe_report,
            ledger_path=args.ledger,
            state_path=args.state,
            daily_loss_limit_quote=args.daily_loss_limit_quote,
        )
    elif args.command == "observe":
        result = apply_historical_basis_v2_paper_observation(
            args.plan,
            args.probe_report,
            ledger_path=args.ledger,
            state_path=args.state,
            observation=_read_json(args.observation),
        )
    else:
        result = historical_basis_v2_paper_status(
            args.plan,
            ledger_path=args.ledger,
            state_path=args.state,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
