from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import slow_liquidity_listing_momentum_forward_monitor as monitor
from slow_liquidity_calendar_first_universe import (
    CALENDAR_FILE_SHA256,
    CALENDAR_PATH,
)
from slow_liquidity_listing_momentum_proxy_date_acceptance import (
    PLAN_ID as PARENT_PLAN_ID,
    PROXY_PLAN_PATH,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = monitor.SCHEMA
PLAN_ID = monitor.PLAN_ID
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
FORWARD_PLAN_PATH = monitor.FORWARD_PLAN_PATH
PREVIOUS_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260821-v3.json"
)
PREVIOUS_PLAN_HASH = "2b41fd407a758e68340c0bba000f48fa87b1fc1e4a7e1c41b0e21a439bfc4dc0"
PREVIOUS_PLAN_FILE_SHA256 = (
    "b4e6b085c40e10c91cc235f186e46f52e56fc6f6d913b79f0b707172d4bc99f4"
)
LAUNCHER_PATH = monitor.EXPECTED_IMPLEMENTATION_PATHS["visible_launcher"]
PROXY_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-momentum-proxy-date-acceptance-approval.json"
)
BATCH1_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log"
    / "listing-strategy-control-plane-batch1-readiness-20260821.json"
)
BATCH1_RECEIPT_FILE_SHA256 = (
    "b310912a5c1d4e5b4bca16d8e343bb77aecca837a4ad32d4917a899fd08eeb56"
)
BOUND_FILES = tuple(
    (role, path)
    for role, path in monitor.EXPECTED_IMPLEMENTATION_PATHS.items()
    if role != "visible_launcher"
)
CADENCE_RECOMMENDATION = "adaptive: search 6h, candidate 3h, official confirmation 1h, exact official time within 24h 5m; scheduler wake 5m and no-op when not due"
ADAPTIVE_CADENCE = {
    "policy_version": "adaptive_event_proximity_v1",
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
}


class ForwardMonitorPlanError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ForwardMonitorPlanError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_forward_monitor_plan(generated_at_utc: str) -> dict[str, Any]:
    _require(PREVIOUS_PLAN_PATH.is_file(), "previous immutable plan missing")
    _require(
        _sha256_file(PREVIOUS_PLAN_PATH) == PREVIOUS_PLAN_FILE_SHA256,
        "previous immutable plan file sha256 mismatch",
    )
    previous_plan = json.loads(PREVIOUS_PLAN_PATH.read_text(encoding="utf-8"))
    _require(
        previous_plan.get("plan_hash") == PREVIOUS_PLAN_HASH,
        "previous immutable plan hash mismatch",
    )
    _require(
        previous_plan.get("plan_hash") == canonical_hash(previous_plan),
        "previous immutable plan is not internally consistent",
    )
    proxy_plan = json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))
    _require(
        proxy_plan.get("plan_id") == PARENT_PLAN_ID,
        "parent proxy plan mismatch",
    )
    _require(
        proxy_plan.get("plan_hash") == canonical_hash(proxy_plan),
        "parent proxy plan hash mismatch",
    )
    receipt = json.loads(PROXY_RECEIPT_PATH.read_text(encoding="utf-8"))
    _require(
        receipt.get("status") == "PROXY_LISTING_DATE_SOURCE_ACCEPTED",
        "proxy acceptance receipt not accepted",
    )
    _require(
        CALENDAR_PATH.is_file()
        and _sha256_file(CALENDAR_PATH) == CALENDAR_FILE_SHA256,
        "baseline calendar hash mismatch",
    )
    previous_rows = {
        str(item.get("role") or ""): item
        for item in (previous_plan.get("implementation") or {}).get("files") or []
    }
    files = [
        {
            "role": role,
            "path": str(path),
            "sha256": _sha256_file(path),
            "provenance": {
                "kind": "technical_rebind_from_superseded_plan_row",
                "superseded_sha256": previous_rows[role]["sha256"],
                "superseded_plan_hash": PREVIOUS_PLAN_HASH,
                "superseded_plan_file_sha256": PREVIOUS_PLAN_FILE_SHA256,
                "batch1_readiness_receipt_sha256": BATCH1_RECEIPT_FILE_SHA256,
            },
        }
        for role, path in BOUND_FILES
    ]
    files.append(
        {
            "role": "visible_launcher",
            "path": str(LAUNCHER_PATH),
            "sha256": _sha256_file(LAUNCHER_PATH),
            "provenance": {
                "kind": "technical_rebind_from_superseded_plan_row",
                "superseded_sha256": previous_rows["visible_launcher"]["sha256"],
                "superseded_plan_hash": PREVIOUS_PLAN_HASH,
                "superseded_plan_file_sha256": PREVIOUS_PLAN_FILE_SHA256,
                "batch1_readiness_receipt_sha256": BATCH1_RECEIPT_FILE_SHA256,
            },
        }
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "strategy_branch": "slow_liquidity_listing_momentum_forward",
        "mode": "PlanOnly",
        "status": "AWAIT_GUARD_GREEN_VISIBLE_TICKS",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "replay_allowed": False,
        "evaluator_or_oos_allowed": False,
        "objective": (
            "Accrue a survivorship-clean forward sample of first-days "
            "windows for NEW MEXC/Gate USDT listings detected by diffing "
            "public current snapshots against the frozen baseline "
            "calendar. Repeatable bounded visible ticks; deterministic "
            "state rebuild. Descriptive accrual only - no acceptance."
        ),
        "adaptive_cadence": ADAPTIVE_CADENCE,
        "source_bindings": {
            "technical_rebind": {
                "kind": "listing_strategy_control_plane_batch2_p1_mutex_hash_rebind",
                "supersedes_plan_id": previous_plan["plan_id"],
                "supersedes_plan_hash": PREVIOUS_PLAN_HASH,
                "supersedes_plan_file_sha256": PREVIOUS_PLAN_FILE_SHA256,
                "supersedes_plan_path": str(PREVIOUS_PLAN_PATH),
                "research_scope_changed": False,
                "reason": (
                    "Rebind the current-run transaction mutex fix and current "
                    "launcher identities without changing venue, universe, "
                    "signal, cost, risk, cadence or acceptance contracts."
                ),
            },
            "control_plane_readiness_receipt": {
                "path": str(BATCH1_RECEIPT_PATH),
                "file_sha256": BATCH1_RECEIPT_FILE_SHA256,
                "status": "READY_FOR_PLANONLY_REBIND_NOT_ACTIVATED",
            },
            "proxy_acceptance_plan": {
                "plan_id": PARENT_PLAN_ID,
                "plan_hash": proxy_plan["plan_hash"],
                "plan_file_sha256": _sha256_file(PROXY_PLAN_PATH),
            },
            "proxy_acceptance_receipt": {
                "receipt_hash": receipt["receipt_hash"],
                "receipt_file_sha256": _sha256_file(PROXY_RECEIPT_PATH),
                "status": receipt["status"],
            },
            "baseline_calendar": {
                "path": str(CALENDAR_PATH),
                "file_sha256": CALENDAR_FILE_SHA256,
                "baseline_as_of_ts": monitor.BASELINE_AS_OF_TS,
            },
            "retrospective_context": {
                "collect_plan_hash": "c48349500731708b7afa33f7c88c32c75ea2731bf285f7f9d434782b87621134",
                "census_hash": "682a88dfccc8ecc16c18d70646ed7658f4ff62043a8c05f2d96cbad245c9fca5",
                "retrospective_closed_descriptive_only": True,
                "survivorship_bias_dominant": True,
            },
        },
        "implementation": {"files": files},
        "tick": {
            "run_kind": "repeatable_bounded_visible_tick",
            "cadence_recommendation": CADENCE_RECOMMENDATION,
            "max_runtime_sec": monitor.MAX_RUNTIME_SEC,
            "baseline_snapshot_requests_per_tick": monitor.BASELINE_SNAPSHOT_REQUESTS,
            "max_new_listings_per_tick": monitor.MAX_NEW_LISTINGS_PER_TICK,
            "effective_page_sizes": dict(monitor.EFFECTIVE_PAGE_SIZES),
            "window_sec": monitor.WINDOW_SEC,
            "probe_window_before_proxy_sec": monitor.PROBE_BEFORE_SEC,
            "granularity": monitor.GRANULARITY,
            "tick_output_root": str(monitor.TICKS_DIR),
            "claim_path": str(monitor.CLAIM_PATH),
            "state_path": str(monitor.FORWARD_STATE_PATH),
            "new_listing_semantics": {
                "window_complete": "listed_ts >= baseline_as_of AND window ended before tick",
                "window_in_progress": "listed_ts >= baseline_as_of AND window not ended",
                "backfill_or_relist_skip": "listed_ts < baseline_as_of: recorded, not collected",
            },
        },
        "guard_contract": {
            "active_gate_must_not_be_running": True,
            "global_writer_claim_must_be_absent": True,
            "visible_terminal_launch_required": True,
            "one_tick_at_a_time": True,
            "tick_directory_must_be_new": True,
            "no_background_daemon": True,
        },
        "authorized_after_guards": [
            "run repeatable visible public read-only forward ticks",
            "write per-tick manifests and forward state rebuild",
            "read forward accrual status",
        ],
        "acceptance_policy": {
            "evidence_class": "PROXY_DATE_FORWARD_ACCRUAL",
            "acceptance_decision": "NONE_ACCRUAL_ONLY",
            "forward_sample_target_note": (
                "acceptance evaluation requires a separate evaluator plan "
                "when enough complete forward windows accrue"
            ),
        },
        "forbidden": [
            "background daemon or hidden scheduled runs",
            "second concurrent market-data writer",
            "evaluator or OOS on forward data without a separate plan",
            "returns or PnL acceptance conclusions from accrual state",
            "treat proxy dates as official announcements",
            "identity verdict",
            "grid or retune",
            "execution probe",
            "paper or live trading",
            "private API keys",
            "real capital",
            "leverage or margin",
        ],
        "commands": {
            "plan_check": (
                "python trading_mvp/src/slow_liquidity_listing_momentum_forward_monitor.py --plan-check"
            ),
            "status": (
                "python trading_mvp/src/slow_liquidity_listing_momentum_forward_monitor.py --status"
            ),
            "visible_tick": (
                "pwsh -NoProfile -ExecutionPolicy Bypass -File "
                f'"{LAUNCHER_PATH}"'
            ),
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_forward_monitor_plan(plan)
    return plan


def validate_forward_monitor_plan(plan: dict[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_GUARD_GREEN_VISIBLE_TICKS",
        "status mismatch",
    )
    _require(plan.get("research_only") is True, "research_only")
    _require(plan.get("public_data_only") is True, "public_data_only")
    _require(plan.get("private_api") is False, "private api")
    _require(plan.get("replay_allowed") is False, "replay allowed")
    _require(
        plan.get("evaluator_or_oos_allowed") is False, "evaluator allowed"
    )
    tick = plan.get("tick") or {}
    _require(
        tick.get("max_runtime_sec") == 600, "tick max runtime bound"
    )
    _require(
        tick.get("max_new_listings_per_tick") == 50, "tick new-listing cap"
    )
    guard = plan.get("guard_contract") or {}
    _require(guard.get("no_background_daemon") is True, "daemon guard")
    _require(
        guard.get("visible_terminal_launch_required") is True,
        "visible launch guard",
    )
    acceptance = plan.get("acceptance_policy") or {}
    _require(
        acceptance.get("acceptance_decision") == "NONE_ACCRUAL_ONLY",
        "acceptance decision leaked into monitor plan",
    )
    _require(
        plan.get("source_bindings", {})
        .get("baseline_calendar", {})
        .get("baseline_as_of_ts")
        == monitor.BASELINE_AS_OF_TS,
        "baseline as-of mismatch",
    )
    rebind = (plan.get("source_bindings") or {}).get("technical_rebind") or {}
    _require(
        rebind.get("supersedes_plan_hash") == PREVIOUS_PLAN_HASH,
        "technical rebind previous plan hash mismatch",
    )
    _require(
        rebind.get("supersedes_plan_file_sha256")
        == PREVIOUS_PLAN_FILE_SHA256,
        "technical rebind previous plan file mismatch",
    )
    _require(
        rebind.get("research_scope_changed") is False,
        "technical rebind changed research scope",
    )
    implementation = plan.get("implementation") or {}
    bound_files = implementation.get("files") or []
    by_role = {str(item.get("role") or ""): item for item in bound_files}
    _require(
        set(by_role) == set(monitor.EXPECTED_IMPLEMENTATION_PATHS),
        "implementation role set mismatch",
    )
    previous_payload = json.loads(PREVIOUS_PLAN_PATH.read_text(encoding="utf-8"))
    previous_by_role = {
        str(item.get("role") or ""): item
        for item in (previous_payload.get("implementation") or {}).get("files") or []
    }
    for role, path in monitor.EXPECTED_IMPLEMENTATION_PATHS.items():
        item = by_role[role]
        _require(
            Path(str(item.get("path") or "")).resolve() == path.resolve(),
            f"implementation path mismatch: {role}",
        )
        _require(
            item.get("sha256") == _sha256_file(path),
            f"implementation sha256 mismatch: {role}",
        )
        provenance = item.get("provenance") or {}
        _require(
            provenance.get("superseded_sha256") == previous_by_role[role]["sha256"],
            f"implementation provenance mismatch: {role}",
        )
    receipt = (plan.get("source_bindings") or {}).get(
        "control_plane_readiness_receipt"
    ) or {}
    _require(BATCH1_RECEIPT_PATH.is_file(), "Batch 1 readiness receipt missing")
    _require(
        _sha256_file(BATCH1_RECEIPT_PATH) == BATCH1_RECEIPT_FILE_SHA256,
        "Batch 1 readiness receipt sha256 mismatch",
    )
    _require(
        receipt.get("path") == str(BATCH1_RECEIPT_PATH)
        and receipt.get("file_sha256") == BATCH1_RECEIPT_FILE_SHA256
        and receipt.get("status") == "READY_FOR_PLANONLY_REBIND_NOT_ACTIVATED",
        "Batch 1 readiness receipt binding mismatch",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")


def write_forward_monitor_plan(generated_at_utc: str) -> Path:
    plan = build_forward_monitor_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if FORWARD_PLAN_PATH.exists():
        _require(
            FORWARD_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {FORWARD_PLAN_PATH}",
        )
        return FORWARD_PLAN_PATH
    FORWARD_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    FORWARD_PLAN_PATH.write_text(payload, encoding="utf-8")
    return FORWARD_PLAN_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    args = parser.parse_args(argv)
    if not args.write_plan:
        raise SystemExit("no authorized action requested")
    generated = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    path = write_forward_monitor_plan(generated)
    plan = json.loads(path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": "PLAN_WRITTEN",
                "path": str(path),
                "plan_hash": plan["plan_hash"],
                "plan_file_sha256": _sha256_file(path),
                "max_runtime_sec_per_tick": plan["tick"]["max_runtime_sec"],
                "baseline_as_of_ts": plan["source_bindings"]["baseline_calendar"][
                    "baseline_as_of_ts"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
