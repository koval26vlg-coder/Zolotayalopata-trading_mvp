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
    / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260817-v2.json"
)
PREVIOUS_V2_PLAN_HASH = "d98d402fb08065bef58859522b938ec064b2bc4a223f269aa0218cce502e5afb"
PREVIOUS_V2_PLAN_FILE_SHA256 = "33da4a8bc9ece1f43055dbb833afa49f068328f4c192bdcad690a7421968c0ee"


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
    implementation_paths = {
        "expansion_adapter": REPO_ROOT / "trading_mvp/src/listing_momentum_exchange_expansion.py",
        "expansion_monitor": REPO_ROOT / "trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py",
        "preflight_launcher": REPO_ROOT / "tools/start_listing_momentum_exchange_expansion_preflight_visible.ps1",
        "expansion_plan_generator": Path(__file__).resolve(),
    }
    implementation = [
        {"role": role, "path": str(path), "sha256": _sha256_file(path)}
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
        "source_bindings": {
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
            "cadence_recommendation": "manual 'продолжай' или scheduler; не чаще 1 тика в 3 часа",
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
