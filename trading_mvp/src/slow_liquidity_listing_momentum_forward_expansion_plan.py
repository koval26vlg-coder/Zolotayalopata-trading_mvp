from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import slow_liquidity_listing_momentum_forward_expansion_monitor as monitor
from listing_momentum_exchange_expansion import (
    DEFAULT_PREFLIGHT_PATH,
    SUPPORTED_VENUES,
    canonical_hash as preflight_hash,
    load_preflight,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = monitor.SCHEMA
PLAN_ID = monitor.PLAN_ID
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
FORWARD_PLAN_PATH = monitor.PLAN_PATH
PREVIOUS_V2_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260824-v5.json"
)
PREVIOUS_V2_PLAN_HASH = "8face1d1ad40043782dafdbdfe7a9bc162248c701bcc9eedb2c4a4a15f5fd8eb"
PREVIOUS_V2_PLAN_FILE_SHA256 = "b801918d9dbb63c8d3635dc0a38b885dad8b0125e234dfbd1ad9a49fe604bcd6"
PREVIOUS_EXPANSION_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-forward-expansion-planonly-20260821-v2.json"
)
PREVIOUS_EXPANSION_PLAN_HASH = "3e3d7ffe8a58bf70263b349644663054893d77e6b7a02c4e5b4fca04208a0b0c"
PREVIOUS_EXPANSION_PLAN_FILE_SHA256 = "0becc5ef47cfe03d5f2fcea94ef30a24668354fc238c3864db3f8b011ed40128"
BATCH1_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log"
    / "listing-strategy-control-plane-batch1-readiness-20260821.json"
)
BATCH1_RECEIPT_FILE_SHA256 = "b310912a5c1d4e5b4bca16d8e343bb77aecca837a4ad32d4917a899fd08eeb56"
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


class ExpansionPlanError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ExpansionPlanError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _baseline_ts(generated_at_utc: str) -> int:
    return int(datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00")).timestamp())


def _validate_parent_v2() -> dict[str, Any]:
    _require(PREVIOUS_V2_PLAN_PATH.is_file(), "current v2 plan missing")
    file_sha = _sha256_file(PREVIOUS_V2_PLAN_PATH)
    _require(file_sha == PREVIOUS_V2_PLAN_FILE_SHA256, "current v2 plan file sha mismatch")
    payload = json.loads(PREVIOUS_V2_PLAN_PATH.read_text(encoding="utf-8"))
    _require(payload.get("plan_hash") == PREVIOUS_V2_PLAN_HASH, "current v2 plan hash mismatch")
    _require(payload.get("plan_hash") == canonical_hash(payload), "current v2 plan is not internally consistent")
    return {
        "path": str(PREVIOUS_V2_PLAN_PATH),
        "file_sha256": file_sha,
        "plan_id": payload.get("plan_id"),
        "plan_hash": payload.get("plan_hash"),
        "parallel_immutable": True,
        "venues": ["mexc", "gateio"],
    }


def build_plan(generated_at_utc: str) -> dict[str, Any]:
    preflight = load_preflight(DEFAULT_PREFLIGHT_PATH)
    _require(preflight.get("status") == "PASS", "preflight is not PASS")
    _require(tuple(preflight.get("contract", {}).get("supported_venues") or []) == SUPPORTED_VENUES, "preflight venue set mismatch")
    _require(all(item.get("status") == "PASS" for item in preflight.get("venues") or []), "not all expansion venues passed preflight")
    _require(preflight.get("receipt_hash") == preflight_hash(preflight), "preflight receipt hash mismatch")
    parent_v2 = _validate_parent_v2()
    _require(PREVIOUS_EXPANSION_PLAN_PATH.is_file(), "previous expansion plan missing")
    _require(
        _sha256_file(PREVIOUS_EXPANSION_PLAN_PATH)
        == PREVIOUS_EXPANSION_PLAN_FILE_SHA256,
        "previous expansion plan file sha mismatch",
    )
    previous_expansion = json.loads(
        PREVIOUS_EXPANSION_PLAN_PATH.read_text(encoding="utf-8")
    )
    _require(
        previous_expansion.get("plan_hash") == PREVIOUS_EXPANSION_PLAN_HASH
        and previous_expansion.get("plan_hash") == canonical_hash(previous_expansion),
        "previous expansion plan hash mismatch",
    )
    _require(BATCH1_RECEIPT_PATH.is_file(), "Batch 1 readiness receipt missing")
    _require(
        _sha256_file(BATCH1_RECEIPT_PATH) == BATCH1_RECEIPT_FILE_SHA256,
        "Batch 1 readiness receipt sha mismatch",
    )
    implementation_paths = {
        "expansion_adapter": REPO_ROOT / "trading_mvp/src/listing_momentum_exchange_expansion.py",
        "expansion_monitor": REPO_ROOT / "trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py",
        "preflight_launcher": REPO_ROOT / "tools/start_listing_momentum_exchange_expansion_preflight_visible.ps1",
        "visible_tick_launcher": REPO_ROOT / "tools/start_listing_momentum_forward_expansion_tick_visible.ps1",
        "automation_launcher": REPO_ROOT / "tools/start_listing_momentum_forward_automation_visible.ps1",
        "expansion_plan_generator": Path(__file__).resolve(),
    }
    previous_rows = {
        str(item.get("role") or ""): item
        for item in (previous_expansion.get("implementation") or {}).get("files") or []
    }
    implementation = [
        {
            "role": role,
            "path": str(path),
            "sha256": _sha256_file(path),
            "provenance": {
                "kind": "technical_rebind_from_superseded_plan_row",
                "superseded_sha256": previous_rows[role]["sha256"],
                "superseded_plan_hash": PREVIOUS_EXPANSION_PLAN_HASH,
                "superseded_plan_file_sha256": PREVIOUS_EXPANSION_PLAN_FILE_SHA256,
                "batch1_readiness_receipt_sha256": BATCH1_RECEIPT_FILE_SHA256,
            },
        }
        for role, path in implementation_paths.items()
    ]
    baseline_ts = _baseline_ts(preflight["generated_at_utc"])
    venue_contracts: dict[str, Any] = {}
    for item in preflight["venues"]:
        venue_contracts[item["exchange"]] = {
            "snapshot_url": item["snapshot"]["url"],
            "ohlcv_url": item["ohlcv"]["url"],
            "snapshot_rows": item["snapshot"]["rows"],
            "active_rows": item["snapshot"]["active_rows"],
            "timestamp_coverage": item["snapshot"]["timestamp_coverage"],
            "sample_symbol": item["snapshot"]["sample_symbol"],
            "parsed_candles": item["ohlcv"]["parsed_candles"],
            "timestamp_contract": item["timestamp_contract"],
            "symbol_format": item["snapshot"]["symbol_format"],
        }
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "strategy_branch": "slow_liquidity_listing_momentum_forward_expansion",
        "mode": "PlanOnly",
        "status": "READY_FOR_VISIBLE_EXPANSION_TICKS",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "replay_allowed": False,
        "evaluator_or_oos_allowed": False,
        "venues": list(SUPPORTED_VENUES),
        "objective": (
            "Accrue a separate descriptive first-days forward sample for "
            "new USDT spot symbols detected on Binance, Bybit, OKX and "
            "Bitget. Use official snapshot timestamps where available and "
            "an explicit detection-time proxy where the public spot schema "
            "does not expose a trustworthy listing timestamp. Do not mix "
            "this namespace with the immutable MEXC/Gate v2 sample."
        ),
        "adaptive_cadence": ADAPTIVE_CADENCE,
        "source_bindings": {
            "technical_rebind": {
                "kind": "listing_strategy_control_plane_batch2_p1_mutex_hash_rebind",
                "supersedes_plan_id": previous_expansion.get("plan_id"),
                "supersedes_plan_hash": PREVIOUS_EXPANSION_PLAN_HASH,
                "supersedes_plan_file_sha256": PREVIOUS_EXPANSION_PLAN_FILE_SHA256,
                "supersedes_plan_path": str(PREVIOUS_EXPANSION_PLAN_PATH),
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
            "preflight": {
                "path": str(DEFAULT_PREFLIGHT_PATH),
                "file_sha256": _sha256_file(DEFAULT_PREFLIGHT_PATH),
                "receipt_hash": preflight["receipt_hash"],
                "generated_at_utc": preflight["generated_at_utc"],
                "baseline_as_of_ts": baseline_ts,
                "request_count": preflight["contract"]["request_count"],
                "max_requests": preflight["contract"]["max_requests"],
                "raw_payload_persisted": False,
            },
            "parent_v2": parent_v2,
            "venue_contracts": venue_contracts,
        },
        "implementation": {"files": implementation},
        "tick": {
            "run_kind": "repeatable_bounded_visible_tick",
            "cadence_recommendation": "adaptive: search 6h, candidate 3h, official confirmation 1h, exact official time within 24h 5m; scheduler wake 5m and no-op when not due",
            "max_runtime_sec": monitor.MAX_RUNTIME_SEC,
            "max_new_listings_per_tick": monitor.MAX_NEW_LISTINGS_PER_TICK,
            "effective_page_sizes": dict(monitor.EFFECTIVE_PAGE_SIZES),
            "window_sec": monitor.WINDOW_SEC,
            "probe_window_before_proxy_sec": monitor.PROBE_BEFORE_SEC,
            "granularity": monitor.GRANULARITY,
            "tick_output_root": str(monitor.TICKS_DIR),
            "claim_path": str(monitor.CLAIM_PATH),
            "state_path": str(monitor.STATE_PATH),
            "separate_namespace_from_v2": True,
        },
        "guard_contract": {
            "active_gate_must_not_be_running": True,
            "global_writer_claim_must_be_absent": True,
            "visible_terminal_launch_required": True,
            "one_tick_at_a_time": True,
            "tick_directory_must_be_new": True,
            "no_background_daemon": True,
            "v2_namespace_must_remain_untouched": True,
        },
        "authorized_after_guards": [
            "run repeatable visible public read-only expansion ticks",
            "write per-tick expansion manifests and state rebuild",
            "read expansion accrual status",
        ],
        "acceptance_policy": {
            "evidence_class": "PROXY_DATE_FORWARD_ACCRUAL_EXPANSION",
            "acceptance_decision": "NONE_ACCRUAL_ONLY",
            "timestamp_caveat": "Binance and Bybit current spot snapshots have no reliable listing timestamp; detection-time proxy is explicit and not an official announcement date.",
            "bitget_caveat": "Bitget openTime is retained as a deprecated snapshot timestamp and must remain separately flagged.",
            "forward_sample_target_note": "A separate evaluator plan is required after enough complete windows accrue.",
        },
        "forbidden": [
            "background daemon or hidden scheduled runs",
            "second concurrent market-data writer",
            "mixing expansion rows into MEXC/Gate v2 state",
            "evaluator or OOS without a separate plan",
            "returns or PnL acceptance conclusions from accrual state",
            "treating detection-time proxy as an official listing announcement",
            "grid or retune",
            "paper or live trading",
            "private API keys",
            "real capital",
            "leverage or margin",
        ],
        "commands": {
            "plan_check": "python trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py --plan-check",
            "status": "python trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py --status",
            "visible_tick": "python trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py --tick --confirmed-visible-tick",
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_plan(plan)
    return plan


def validate_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(plan.get("status") == "READY_FOR_VISIBLE_EXPANSION_TICKS", "status mismatch")
    _require(plan.get("research_only") is True, "research_only")
    _require(plan.get("public_data_only") is True, "public_data_only")
    _require(plan.get("private_api") is False, "private api")
    _require(plan.get("replay_allowed") is False, "replay allowed")
    _require(plan.get("evaluator_or_oos_allowed") is False, "evaluator allowed")
    _require(tuple(plan.get("venues") or []) == SUPPORTED_VENUES, "venue set")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash")
    _require(plan.get("tick", {}).get("max_runtime_sec") == monitor.MAX_RUNTIME_SEC, "runtime bound")
    _require(plan.get("tick", {}).get("max_new_listings_per_tick") == monitor.MAX_NEW_LISTINGS_PER_TICK, "tick cap")
    _require(plan.get("source_bindings", {}).get("parent_v2", {}).get("parallel_immutable") is True, "v2 parallel binding")
    _require(plan.get("guard_contract", {}).get("v2_namespace_must_remain_untouched") is True, "v2 isolation guard")
    _require(plan.get("acceptance_policy", {}).get("acceptance_decision") == "NONE_ACCRUAL_ONLY", "acceptance policy")
    rebind = (plan.get("source_bindings") or {}).get("technical_rebind") or {}
    _require(
        rebind.get("supersedes_plan_hash") == PREVIOUS_EXPANSION_PLAN_HASH
        and rebind.get("supersedes_plan_file_sha256")
        == PREVIOUS_EXPANSION_PLAN_FILE_SHA256
        and rebind.get("research_scope_changed") is False,
        "technical rebind provenance",
    )
    receipt = (plan.get("source_bindings") or {}).get(
        "control_plane_readiness_receipt"
    ) or {}
    _require(
        BATCH1_RECEIPT_PATH.is_file()
        and _sha256_file(BATCH1_RECEIPT_PATH) == BATCH1_RECEIPT_FILE_SHA256,
        "Batch 1 readiness receipt",
    )
    _require(
        receipt.get("path") == str(BATCH1_RECEIPT_PATH)
        and receipt.get("file_sha256") == BATCH1_RECEIPT_FILE_SHA256
        and receipt.get("status") == "READY_FOR_PLANONLY_REBIND_NOT_ACTIVATED",
        "Batch 1 readiness receipt binding",
    )
    expected_paths = {
        "expansion_adapter": REPO_ROOT / "trading_mvp/src/listing_momentum_exchange_expansion.py",
        "expansion_monitor": REPO_ROOT / "trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py",
        "preflight_launcher": REPO_ROOT / "tools/start_listing_momentum_exchange_expansion_preflight_visible.ps1",
        "visible_tick_launcher": REPO_ROOT / "tools/start_listing_momentum_forward_expansion_tick_visible.ps1",
        "automation_launcher": REPO_ROOT / "tools/start_listing_momentum_forward_automation_visible.ps1",
        "expansion_plan_generator": Path(__file__).resolve(),
    }
    current_rows = {
        str(item.get("role") or ""): item
        for item in (plan.get("implementation") or {}).get("files") or []
    }
    previous_payload = json.loads(
        PREVIOUS_EXPANSION_PLAN_PATH.read_text(encoding="utf-8")
    )
    previous_rows = {
        str(item.get("role") or ""): item
        for item in (previous_payload.get("implementation") or {}).get("files") or []
    }
    _require(set(current_rows) == set(expected_paths), "implementation role set")
    for role, path in expected_paths.items():
        row = current_rows[role]
        _require(Path(str(row.get("path") or "")).resolve() == path.resolve(), f"implementation path: {role}")
        _require(row.get("sha256") == _sha256_file(path), f"implementation sha256: {role}")
        _require(
            (row.get("provenance") or {}).get("superseded_sha256")
            == previous_rows[role]["sha256"],
            f"implementation provenance: {role}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Listing Momentum exchange expansion PlanOnly")
    parser.add_argument("--output", default=str(FORWARD_PLAN_PATH))
    parser.add_argument("--generated-at-utc", default=_iso_now())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    output_path = Path(args.output)
    if args.check:
        plan = json.loads(output_path.read_text(encoding="utf-8"))
        validate_plan(plan)
    else:
        plan = build_plan(args.generated_at_utc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PLAN_OK",
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "output_path": str(output_path),
                "venues": list(SUPPORTED_VENUES),
                "preflight_receipt_hash": plan["source_bindings"]["preflight"]["receipt_hash"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
