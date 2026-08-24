"""Immutable PlanOnly validation for the pre-market perpetual branch."""

from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
from typing import Any, Mapping


PLAN_SCHEMA = "trading_mvp_premarket_perp_listing_impulse_planonly_v2"
REQUIRED_VENUES = {"bybit", "okx", "gate"}
REQUIRED_EXIT_OFFSETS = [0, 5, 15, 60]
REQUIRED_ENTRY_COHORTS = ["first_tradable", "last_1_4h"]
ADAPTIVE_CADENCE = {
    "policy_version": "adaptive_event_proximity_v2",
    "scheduler_wake_interval_sec": 300,
    "search_interval_sec": 21600,
    "soon_interval_sec": 10800,
    "confirmed_interval_sec": 3600,
    "scheduled_interval_sec": 300,
    "soon_horizon_sec": 259200,
    "scheduled_horizon_sec": 86400,
    "exact_timestamp_required_for_scheduled": True,
    "proxy_cannot_escalate_to_confirmed": True,
    "collector_runs_only_when_due": True,
    "terminal_event_returns_to_search": True,
    # An anchor whose own event has passed is not an upcoming event. Without this the
    # CONFIRMED branch had no time check at all and held the hourly cadence forever.
    "event_spent_after_sec": 259200,
    "spent_anchor_returns_to_search": True,
}


def canonical_plan_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "plan_hash"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_plan(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path)
    reasons: list[str] = []
    if not plan_path.exists():
        return {"status": "PLAN_INVALID", "ok": False, "reasons": ["plan_file_missing"], "path": str(plan_path)}
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "PLAN_INVALID", "ok": False, "reasons": [f"plan_json_invalid:{exc}"], "path": str(plan_path)}
    if payload.get("schema") != PLAN_SCHEMA:
        reasons.append("schema_mismatch")
    if payload.get("mode") != "PlanOnly" or payload.get("research_only") is not True:
        reasons.append("plan_mode_or_research_only_invalid")
    if payload.get("public_data_only") is not True or payload.get("private_api") is not False:
        reasons.append("public_data_contract_invalid")
    if payload.get("live_orders") is not False or payload.get("real_capital") is not False:
        reasons.append("live_execution_contract_invalid")
    if payload.get("leverage_or_margin") is not False:
        reasons.append("leverage_or_margin_contract_invalid")
    if set(payload.get("venues") or []) != REQUIRED_VENUES:
        reasons.append("venue_contract_invalid")
    lifecycle = payload.get("lifecycle_statuses") or []
    required_lifecycle = {"scheduled", "call_auction", "continuous", "spot_listing_pending", "transitioned", "cancelled", "delisted", "expired"}
    if set(lifecycle) != required_lifecycle:
        reasons.append("lifecycle_contract_invalid")
    if payload.get("entry_cohorts") != REQUIRED_ENTRY_COHORTS:
        reasons.append("entry_cohort_contract_invalid")
    if payload.get("exit_offsets_sec") != REQUIRED_EXIT_OFFSETS:
        reasons.append("exit_contract_invalid")
    risk = payload.get("risk_contract") or {}
    if float(risk.get("paper_notional_quote", 0)) != 25.0 or risk.get("primary_leverage") != 1:
        reasons.append("paper_risk_contract_invalid")
    if risk.get("stress_leverage") != [2, 5]:
        reasons.append("stress_risk_contract_invalid")
    if payload.get("primary_exit_policy") != "event_relative_only_no_hindsight":
        reasons.append("exit_policy_invalid")
    if payload.get("adaptive_cadence") != ADAPTIVE_CADENCE:
        reasons.append("adaptive_cadence_contract_invalid")
    collection = payload.get("collection_contract") or {}
    if collection.get("discovery_cadence_sec") != 6 * 60 * 60 or collection.get("scheduler_wake_interval_sec") != 5 * 60:
        reasons.append("collection_adaptive_interval_invalid")
    recovery = payload.get("recovery_contract") or {}
    if recovery.get("interval_sec") != 6 * 60 * 60 or recovery.get("scheduler_wake_interval_sec") != 5 * 60:
        reasons.append("recovery_adaptive_interval_invalid")
    guard = payload.get("guard_contract") or {}
    if (
        guard.get("visible_terminal_required") is not True
        or guard.get("inline_worker_no_terminal_allowed") is not False
    ):
        reasons.append("visible_worker_contract_invalid")
    acceptance = payload.get("acceptance_gates") or {}
    for key, expected in {
        "minimum_complete_events": 30,
        "minimum_normal_fill_rate": 0.8,
        "minimum_stress_fill_rate": 0.7,
        "minimum_profit_factor": 1.2,
        "maximum_drawdown_fraction": 0.1,
        "maximum_positive_event_share": 0.25,
    }.items():
        if acceptance.get(key) != expected:
            reasons.append(f"acceptance_gate_{key}_invalid")
    stored_hash = str(payload.get("plan_hash") or "")
    actual_hash = canonical_plan_hash(payload)
    if stored_hash != actual_hash:
        reasons.append("plan_hash_mismatch")
    implementation = payload.get("implementation") or []
    missing_bindings: list[str] = []
    for binding in implementation:
        binding_path = Path(str(binding.get("path") or ""))
        if not binding_path.exists():
            missing_bindings.append(str(binding_path))
            continue
        expected_sha = str(binding.get("sha256") or "")
        if expected_sha and file_sha256(binding_path) != expected_sha:
            reasons.append(f"implementation_hash_mismatch:{binding_path.name}")
    if missing_bindings:
        reasons.append("implementation_file_missing")
    return {
        "status": "PLAN_OK" if not reasons else "PLAN_INVALID",
        "ok": not reasons,
        "reasons": reasons,
        "plan_id": payload.get("plan_id"),
        "plan_hash": stored_hash,
        "actual_plan_hash": actual_hash,
        "plan_file_sha256": file_sha256(plan_path),
        "venues": payload.get("venues"),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate the immutable pre-market PlanOnly")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_plan(args.plan)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
