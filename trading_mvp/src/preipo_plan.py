"""Immutable PlanOnly validation for the isolated pre-IPO perpetual branch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


PLAN_SCHEMA = "trading_mvp_preipo_perpetual_event_planonly_v2"
# Promoted 2026-08-25: bitmex and kraken have adapters and public unauthenticated
# instruments endpoints. A failing venue is isolated to its own outcome
# (RETRY_NEXT_INTERVAL) and cannot break collection from the others, which is what makes
# promotion safe to do before either venue has ever answered.
REQUIRED_VENUES = {"okx", "gate", "bitmex", "kraken"}
# Candidates are venues we have established carry pre-IPO perpetuals on a public,
# unauthenticated instruments endpoint - verified from their documentation on
# 2026-08-25 - but from which nothing is collected yet. Writing an adapter says we can
# collect; being in `venues` says we do. Promotion needs an authorised capture run.
# Still candidates: no adapter, because their instrument response shape could not be
# confirmed from documentation. Crypto.com publishes symbol/base_ccy/quote_ccy and the
# decimals but no listing timestamp was found, and Coinbase International's instrument
# fields could not be read at all. Writing a normaliser against guessed field names
# would silently mis-map data, which is worse than not collecting.
REQUIRED_CANDIDATE_VENUES = {"bybit", "cryptocom", "coinbase_intx"}

# Coinbase International's own documentation states that a pre-IPO perpetual's index
# price "may comprise internal reference prices from trading activity and/or third-party
# market prices, though certain contracts may use only internal reference prices". Where
# the index is purely internal, a listing impulse measured on that venue may be the
# venue's own order book reflecting itself rather than information arriving. This does
# not invalidate the collection, but it bounds what a positive result could mean, and a
# bound that is not written down is a bound that gets forgotten.
INDEX_PRICE_CAVEAT = (
    "pre-IPO perpetual index prices may be internal-only; a measured impulse may be "
    "venue-internal reflexivity rather than information"
)
REQUIRED_LIFECYCLE = {
    "scheduled",
    "preipo_continuous",
    "s1_disclosed",
    "rebase",
    "ipo_pending",
    "ipo_open",
    "converted",
    "postponed",
    "cancelled",
    "delisted",
    "expired",
}
REQUIRED_ENTRY_COHORTS = ["first_tradable", "last_1_4h"]
REQUIRED_SIDES = ["long", "short"]
REQUIRED_EXITS = ["ipo_open", "ipo_open_plus_5s", "ipo_open_plus_15s", "ipo_open_plus_60s", "conversion"]
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
    for key in ("public_data_only",):
        if payload.get(key) is not True:
            reasons.append(f"{key}_invalid")
    for key in ("private_api", "live_orders", "real_capital", "leverage_or_margin", "crypto_listing_mix_allowed"):
        if payload.get(key) is not False:
            reasons.append(f"{key}_invalid")
    if payload.get("asset_class") != "preipo_equity":
        reasons.append("asset_class_invalid")
    if set(payload.get("venues") or []) != REQUIRED_VENUES:
        reasons.append("venue_contract_invalid")
    if str((payload.get("venue_caveats") or {}).get("index_price") or "") != INDEX_PRICE_CAVEAT:
        reasons.append("index_price_caveat_missing")
    if not REQUIRED_CANDIDATE_VENUES.issubset(set(payload.get("candidate_venues") or [])):
        reasons.append("candidate_venue_contract_invalid")
    if "official pre-IPO contract" not in str(payload.get("bybit_extension_condition") or ""):
        reasons.append("bybit_extension_condition_invalid")
    if payload.get("sides") != REQUIRED_SIDES:
        reasons.append("side_contract_invalid")
    if payload.get("entry_cohorts") != REQUIRED_ENTRY_COHORTS:
        reasons.append("entry_cohort_contract_invalid")
    if payload.get("event_relative_exits") != REQUIRED_EXITS:
        reasons.append("exit_contract_invalid")
    if set(payload.get("lifecycle_statuses") or []) != REQUIRED_LIFECYCLE:
        reasons.append("lifecycle_contract_invalid")
    if payload.get("proxy_acceptance_allowed") is not False:
        reasons.append("proxy_acceptance_invalid")
    if payload.get("official_timestamp_policy") != "exact_first_trade_t0_required_for_acceptance_proxy_separate":
        reasons.append("official_timestamp_policy_invalid")
    if payload.get("adaptive_cadence") != ADAPTIVE_CADENCE:
        reasons.append("adaptive_cadence_contract_invalid")

    automation = payload.get("automation") or {}
    if automation.get("schedule_interval_sec") != 6 * 60 * 60:
        reasons.append("automation_schedule_interval_invalid")
    if automation.get("discovery_interval_sec") != 6 * 60 * 60 or automation.get("scheduler_wake_interval_sec") != 5 * 60:
        reasons.append("automation_adaptive_interval_invalid")
    if automation.get("capture_duration_sec") != 5 * 60:
        reasons.append("automation_capture_duration_invalid")

    risk = payload.get("risk_contract") or {}
    if float(risk.get("paper_notional_quote", 0)) != 25.0:
        reasons.append("paper_notional_invalid")
    if risk.get("primary_leverage_equivalent") != 1:
        reasons.append("primary_leverage_invalid")
    if risk.get("stress_leverage_equivalent") != [2, 5]:
        reasons.append("stress_leverage_invalid")
    if risk.get("real_leverage_or_margin") is not False:
        reasons.append("risk_real_leverage_invalid")
    rebase = payload.get("rebase_policy") or {}
    if rebase.get("value_neutral") is not True or rebase.get("pnl_credit") is not False:
        reasons.append("rebase_policy_invalid")

    acceptance = payload.get("acceptance_gates") or {}
    for key, expected in {
        "minimum_complete_events": 30,
        "minimum_official_events": 30,
        "interim_descriptive_events": 10,
        "interim_authorizes": False,
        "minimum_normal_fill_rate": 0.8,
        "minimum_stress_fill_rate": 0.7,
        "minimum_profit_factor": 1.2,
        "maximum_drawdown_fraction": 0.1,
        "maximum_positive_event_share": 0.25,
    }.items():
        if acceptance.get(key) != expected:
            reasons.append(f"acceptance_gate_{key}_invalid")
    if acceptance.get("below_minimum_status") != "INSUFFICIENT_DATA_NOT_REJECTED":
        reasons.append("acceptance_insufficient_status_invalid")
    interim = acceptance.get("interim_descriptive_events")
    minimum = acceptance.get("minimum_complete_events")
    if acceptance.get("interim_authorizes") is not False:
        reasons.append("acceptance_interim_tier_must_not_authorize")
    if not isinstance(interim, int) or not isinstance(minimum, int) or interim >= minimum:
        # Collapsing the tiers would turn the early descriptive read into the acceptance
        # decision itself, which is exactly what the two tiers exist to prevent.
        reasons.append("acceptance_interim_tier_not_below_minimum")


    recovery = payload.get("recovery_contract") or {}
    if recovery.get("interval_sec") != 6 * 60 * 60 or recovery.get("scheduler_wake_interval_sec") != 5 * 60:
        reasons.append("recovery_interval_invalid")
    guard = payload.get("guard_contract") or {}
    if (
        guard.get("visible_terminal_required") is not True
        or guard.get("inline_worker_no_terminal_allowed") is not False
    ):
        reasons.append("visible_worker_contract_invalid")

    implementation = payload.get("implementation") or []
    missing_bindings: list[str] = []
    for binding in implementation:
        binding_path = Path(str(binding.get("path") or ""))
        if not binding_path.exists():
            missing_bindings.append(str(binding_path))
            continue
        expected_sha = str(binding.get("sha256") or "")
        if len(expected_sha) != 64 or file_sha256(binding_path) != expected_sha:
            reasons.append(f"implementation_hash_mismatch:{binding_path.name}")
    if missing_bindings:
        reasons.append("implementation_file_missing")

    stored_hash = str(payload.get("plan_hash") or "")
    actual_hash = canonical_plan_hash(payload)
    if stored_hash != actual_hash:
        reasons.append("plan_hash_mismatch")

    return {
        "status": "PLAN_OK" if not reasons else "PLAN_INVALID",
        "ok": not reasons,
        "reasons": reasons,
        "plan_id": payload.get("plan_id"),
        "plan_hash": stored_hash,
        "actual_plan_hash": actual_hash,
        "plan_file_sha256": file_sha256(plan_path),
        "venues": payload.get("venues"),
        "candidate_venues": payload.get("candidate_venues"),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate the immutable pre-IPO PlanOnly")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_plan(args.plan)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
