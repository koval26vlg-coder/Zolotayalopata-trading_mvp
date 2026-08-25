"""Immutable PlanOnly validation for the isolated pre-IPO perpetual branch."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PLAN_SCHEMA = "trading_mvp_preipo_perpetual_event_planonly_v2"
PLAN_ID = "preipo_perpetual_event_20260826_v11"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN_PATH = (
    REPO_ROOT / "docs/plans/preipo-perpetual-event-planonly-20260826-v11.json"
)
SUPERSEDED_PLAN_PATH = (
    REPO_ROOT / "docs/plans/preipo-perpetual-event-planonly-20260825-v10.json"
)
SUPERSEDED_PLAN = {
    "plan_id": "preipo_perpetual_event_20260825_v10",
    "plan_hash": "bdfb567da778f4f7f6ac7c6b1625fcd7d5013ab42734e15e3037ad3679db0f13",
    "plan_file_sha256": "56d450dba620044fa1662c82d3d1d8381fbfc26a4ed72a6de7aa0ee5e4604d9f",
    "plan_path": "docs/plans/preipo-perpetual-event-planonly-20260825-v10.json",
}
TECHNICAL_REBIND_CHANGED_DIMENSIONS = [
    "implementation_exact_byte_sha256",
    "launcher_default_plan",
    "plan_identity",
    "trusted_git_executable_resolution",
]
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
REQUIRED_CANDIDATE_VENUES = {
    "binance",
    "bybit",
    "cryptocom",
    "coinbase_intx",
}

PUBLIC_SOURCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "bitmex": {
        "instrument_metadata": {
            "host": "www.bitmex.com",
            "path": "/api/v1/instrument/active",
            "timestamp_field": "listing",
            "timestamp_kind": "premarket_contract_launch_ts",
        },
        "official_event_family": {
            "host": "www.bitmex.com",
            "path_prefix": "/blog/",
            "published_semantics": ["contract_launch", "contract_specification"],
        },
        "auto_proves_official_first_trade": False,
        "fail_closed_reason": (
            "BitMEX instrument listing and blog futures-listing dates describe the "
            "derivative contract, not the underlying equity's first executed trade."
        ),
    },
    "gate": {
        "instrument_metadata": {
            "host": "api.gateio.ws",
            "path": "/api/v4/futures/usdt/contracts",
            "timestamp_field": "launch_time",
            "timestamp_kind": "premarket_contract_launch_ts",
        },
        "official_event_family": {
            "host": "www.gate.com",
            "perpetual_announcement_path_prefix": "/announcements/article/",
            "reference_article_id": "50673",
            "published_semantics": ["contract_launch", "conversion_notice"],
        },
        "excluded_product_families": [
            "mirror_note",
            "spot_preipo_asset_certificate",
        ],
        "auto_proves_official_first_trade": False,
        "fail_closed_reason": (
            "Gate pre-IPO perpetual announcements are distinct from Mirror Note and "
            "spot pre-IPO certificates; none is equity first-trade proof by default."
        ),
    },
    "kraken": {
        "instrument_metadata": {
            "host": "futures.kraken.com",
            "path": "/derivatives/api/v3/instruments",
            "timestamp_field": "openingDate",
            "timestamp_kind": "premarket_contract_launch_ts",
        },
        "official_event_family": {
            "host": "support.kraken.com",
            "path_prefix": "/articles/pre-ipo-perpetual-futures-faq",
            "published_semantics": [
                "conversion_notice",
                "rebase_notice",
                "contract_first_trading",
            ],
        },
        "auto_proves_official_first_trade": False,
        "fail_closed_reason": (
            "Kraken conversion/rebase notices and a contract First Trading field do "
            "not by themselves prove the underlying equity's first executed trade."
        ),
    },
    "okx": {
        "instrument_metadata": {
            "host": "www.okx.com",
            "path": "/api/v5/public/instruments",
            "timestamp_field": "listTime",
            "timestamp_kind": "premarket_contract_launch_ts",
        },
        "official_event_family": {
            "host": "www.okx.com",
            "path_prefix": "/help/",
            "published_semantics": ["conversion_window", "rebase_notice"],
        },
        "auto_proves_official_first_trade": False,
        "fail_closed_reason": (
            "An OKX conversion window depends on the stock's actual first trade but "
            "remains separate from an explicitly sourced equity first-trade timestamp."
        ),
    },
}

OFFICIAL_FIRST_TRADE_SOURCE_CONTRACT: dict[str, Any] = {
    "timestamp_kind": "official_first_trade_ts",
    "meaning": "underlying_equity_first_executed_trade",
    "resolver": "preipo_perp_event.parse_announcement",
    "required_source_class": "official",
    "allowed_source_families": {
        "bitmex": "bitmex_official_equity_first_trade_notice",
        "gate": "gate_preipo_perpetual_official_first_trade_notice",
        "kraken": "kraken_official_equity_first_trade_notice",
        "okx": "okx_official_equity_first_trade_notice",
    },
    "required_fields": [
        "venue",
        "contract_id",
        "underlying_symbol",
        "quote",
        "source_url",
        "announcement_ts",
        "official_first_trade_ts",
    ],
    "required_binding_arguments": ["source_family"],
    "contract_provenance_fields": [
        "official_first_trade_ts",
        "official_first_trade_announcement_ts",
        "official_first_trade_source_class",
        "official_first_trade_source_url",
        "official_first_trade_source_family",
    ],
    "source_url_must_match_venue_official_host": True,
    "disallowed_substitutions": [
        "premarket_contract_launch_ts",
        "contract_first_trading_ts",
        "first_trade_ts",
        "ipo_open_ts",
        "ipo_start_ts",
        "first_trading_ts",
        "conversion_window_ts",
        "transition_ts",
        "rebase_ts",
        "expected_ipo_date",
        "first_observed_trade_ts",
    ],
    "unresolved_policy": "descriptive_only",
    "proxy_acceptance_allowed": False,
}

_COMMON_CANDIDATE_PROMOTION_CONDITIONS = [
    "official_preipo_perpetual_product_evidence",
    "public_unauthenticated_instrument_and_lifecycle_api",
    "public_market_data_adapter",
    "equity_timestamp_taxonomy",
    "preipo_equity_asset_class_separation",
    "adapter_fixtures_and_failure_tests",
    "https_allow_list_and_provenance_audit",
]

CANDIDATE_PROMOTION_CONDITIONS: dict[str, dict[str, Any]] = {
    "binance": {
        "status": "candidate_only",
        "automatic_promotion_allowed": False,
        "promotion_requires_all": [
            *_COMMON_CANDIDATE_PROMOTION_CONDITIONS,
            "official_binance_preipo_listing_source",
        ],
    },
    "bybit": {
        "status": "candidate_only",
        "automatic_promotion_allowed": False,
        "promotion_requires_all": [
            *_COMMON_CANDIDATE_PROMOTION_CONDITIONS,
            "official_bybit_contract_and_timestamp_method",
        ],
    },
    "coinbase_intx": {
        "status": "candidate_only",
        "automatic_promotion_allowed": False,
        "promotion_requires_all": [
            *_COMMON_CANDIDATE_PROMOTION_CONDITIONS,
            "documented_index_methodology_and_internal_index_caveat",
        ],
    },
    "cryptocom": {
        "status": "candidate_only",
        "automatic_promotion_allowed": False,
        "promotion_requires_all": [
            *_COMMON_CANDIDATE_PROMOTION_CONDITIONS,
            "documented_contract_listing_and_lifecycle_timestamps",
        ],
    },
}

PREIPO_TEMPORAL_ANCHOR_CONTRACT: dict[str, Any] = {
    "module": "trading_mvp/src/preipo_temporal_anchor.py",
    "primary_t0_kind": "official_first_trade_ts",
    "kinds": [
        "official_first_trade_ts",
        "conversion_window_ts",
        "transition_ts",
        "premarket_contract_launch_ts",
    ],
    "official_anchor_kinds": ["official_first_trade_ts"],
    "required_exact_provenance": [
        "active_venue",
        "positive_finite_official_first_trade_ts",
        "positive_finite_announcement_ts",
        "official_source_class",
        "venue_official_source_url",
    ],
    "proxy_anchor_kinds": [
        "conversion_window_ts",
        "transition_ts",
        "premarket_contract_launch_ts",
    ],
    "rule": (
        "Only an official source that explicitly publishes the underlying equity's "
        "first executed trade may certify the primary t0; contract launch, contract "
        "First Trading, conversion, transition, rebase and expected dates remain proxy."
    ),
    "source_class_is_not_timestamp_class": (
        "Contract metadata provenance never certifies a timestamp; official-first-trade "
        "provenance is attached to that field, a positive announcement timestamp, the "
        "active venue and its venue-official source URL."
    ),
    "anchor_selection": (
        "Use official_first_trade_ts first, otherwise the best still-future descriptive "
        "proxy; select the earliest future row and retire spent rows by cadence policy."
    ),
    "confirmation_scope": (
        "official_confirmed and exact_timestamp belong only to the selected "
        "official_first_trade_ts anchor, never any other row or field."
    ),
    "measured": (
        "2026-08-25: active venue metadata and published conversion/rebase notices do "
        "not automatically prove an underlying equity first-trade t0. Bybit is "
        "candidate-only and cannot feed this runtime until all promotion conditions pass."
    ),
}

VENUE_VERIFICATION: dict[str, Any] = {
    "verified_at_utc": "2026-08-25",
    "method": "official vendor documentation; no venue endpoint called in this rebind",
    "venues": {
        "bitmex": {
            "status": "active",
            "adapter": True,
            "public_instruments_endpoint": "/api/v1/instrument/active",
            "timestamp_field": "listing",
            "timestamp_kind": "premarket_contract_launch_ts",
            "authentication_required": False,
        },
        "gate": {
            "status": "active",
            "adapter": True,
            "public_instruments_endpoint": "/api/v4/futures/usdt/contracts",
            "timestamp_field": "launch_time",
            "timestamp_kind": "premarket_contract_launch_ts",
            "authentication_required": False,
        },
        "kraken": {
            "status": "active",
            "adapter": True,
            "public_instruments_endpoint": "/derivatives/api/v3/instruments",
            "timestamp_field": "openingDate",
            "timestamp_kind": "premarket_contract_launch_ts",
            "authentication_required": False,
        },
        "okx": {
            "status": "active",
            "adapter": True,
            "public_instruments_endpoint": "/api/v5/public/instruments",
            "timestamp_field": "listTime",
            "timestamp_kind": "premarket_contract_launch_ts",
            "authentication_required": False,
        },
        "binance": {
            "status": "candidate_only",
            "adapter": False,
            "public_instruments_endpoint": None,
            "official_product_evidence": "Binance Academy pre-IPO product documentation",
            "promotion_contract": "candidate_promotion_conditions.binance",
        },
        "bybit": {
            "status": "candidate_only",
            "adapter": False,
            "public_instruments_endpoint": None,
            "promotion_contract": "candidate_promotion_conditions.bybit",
        },
        "coinbase_intx": {
            "status": "candidate_only",
            "adapter": False,
            "public_instruments_endpoint": "public market-data API family not yet bound",
            "promotion_contract": "candidate_promotion_conditions.coinbase_intx",
        },
        "cryptocom": {
            "status": "candidate_only",
            "adapter": False,
            "public_instruments_endpoint": "public/get-instruments",
            "promotion_contract": "candidate_promotion_conditions.cryptocom",
        },
    },
}

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

EXPECTED_IMPLEMENTATION_PATHS = {
    "preipo_event_lifecycle_and_causal_paper_replay": (
        REPO_ROOT / "trading_mvp/src/preipo_perp_event.py"
    ).resolve(),
    "preipo_public_venue_adapters": (
        REPO_ROOT / "trading_mvp/src/preipo_adapters.py"
    ).resolve(),
    "preipo_append_only_raw_event_store": (
        REPO_ROOT / "trading_mvp/src/preipo_raw_event_store.py"
    ).resolve(),
    "preipo_retry_state_and_tick_worker": (
        REPO_ROOT / "trading_mvp/src/preipo_automation.py"
    ).resolve(),
    "preipo_plan_validator": Path(__file__).resolve(),
    "preipo_visible_orchestrator": (
        REPO_ROOT / "tools/start_preipo_perpetual_event_automation_visible.ps1"
    ).resolve(),
    "cadence_policy": (REPO_ROOT / "trading_mvp/src/adaptive_cadence.py").resolve(),
    "shared_temporal_anchor_selection": (
        REPO_ROOT / "trading_mvp/src/premarket_temporal_anchor.py"
    ).resolve(),
    "preipo_temporal_anchor_taxonomy": (
        REPO_ROOT / "trading_mvp/src/preipo_temporal_anchor.py"
    ).resolve(),
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


def _git_blob_sha256(path: str | Path, revision: str = "HEAD") -> str:
    if os.name == "nt":
        git = r"C:\Program Files\Git\cmd\git.exe"
    elif os.name == "posix":
        git = "/usr/bin/git"
    else:
        raise RuntimeError("git_platform_unsupported")
    if not Path(git).is_file():
        raise RuntimeError("git_executable_missing")
    try:
        relative = Path(path).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError("predecessor_path_outside_repository") from exc
    try:
        result = subprocess.run(
            [git, "show", f"{revision}:{relative}"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("predecessor_git_blob_timeout") from exc
    except OSError as exc:
        raise RuntimeError("predecessor_git_blob_unavailable") from exc
    if result.returncode != 0:
        raise RuntimeError("predecessor_git_blob_unavailable")
    return hashlib.sha256(result.stdout).hexdigest()


def _parse_generated_at_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp_must_be_utc")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_must_be_timezone_aware")
    return parsed.astimezone(timezone.utc)


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
    if payload.get("plan_id") != PLAN_ID:
        reasons.append("plan_id_mismatch")
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
    if set(payload.get("candidate_venues") or []) != REQUIRED_CANDIDATE_VENUES:
        reasons.append("candidate_venue_contract_invalid")
    if payload.get("candidate_promotion_conditions") != CANDIDATE_PROMOTION_CONDITIONS:
        reasons.append("candidate_promotion_conditions_invalid")
    if payload.get("venue_verification") != VENUE_VERIFICATION:
        reasons.append("venue_verification_invalid")
    if set(payload.get("venues") or []) & set(payload.get("candidate_venues") or []):
        reasons.append("venue_candidate_overlap")
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
    if payload.get("temporal_anchor_contract") != PREIPO_TEMPORAL_ANCHOR_CONTRACT:
        reasons.append("preipo_temporal_anchor_contract_invalid")

    data = payload.get("data_contract") or {}
    if data.get("public_source_contracts") != PUBLIC_SOURCE_CONTRACTS:
        reasons.append("public_source_contracts_invalid")
    if (
        data.get("official_first_trade_source_contract")
        != OFFICIAL_FIRST_TRADE_SOURCE_CONTRACT
    ):
        reasons.append("official_first_trade_source_contract_invalid")

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

    if (
        payload.get("supersedes_plan_id") != SUPERSEDED_PLAN["plan_id"]
        or payload.get("supersedes_plan_hash") != SUPERSEDED_PLAN["plan_hash"]
        or payload.get("supersedes_plan_file_sha256")
        != SUPERSEDED_PLAN["plan_file_sha256"]
        or payload.get("supersedes_plan_path") != SUPERSEDED_PLAN["plan_path"]
    ):
        reasons.append("supersedes_binding_invalid")
    if file_sha256(SUPERSEDED_PLAN_PATH) != SUPERSEDED_PLAN["plan_file_sha256"]:
        reasons.append("superseded_plan_worktree_sha256_mismatch")
    try:
        if (
            _git_blob_sha256(SUPERSEDED_PLAN_PATH)
            != SUPERSEDED_PLAN["plan_file_sha256"]
        ):
            reasons.append("superseded_plan_git_blob_sha256_mismatch")
    except (OSError, RuntimeError, ValueError):
        reasons.append("superseded_plan_git_blob_unavailable")
    try:
        superseded_payload = json.loads(
            SUPERSEDED_PLAN_PATH.read_text(encoding="utf-8")
        )
        if _parse_generated_at_utc(
            payload.get("generated_at_utc")
        ) <= _parse_generated_at_utc(superseded_payload.get("generated_at_utc")):
            reasons.append("generated_at_utc_not_after_superseded_plan")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        reasons.append("generated_at_utc_lineage_invalid")

    rebind = ((payload.get("source_bindings") or {}).get("technical_rebind") or {})
    if (
        rebind.get("kind") != "preipo_trusted_git_path_cwe426_rebind_v11"
        or rebind.get("research_scope_changed") is not False
        or set(rebind.get("baseline_active_venues") or []) != REQUIRED_VENUES
        or set(rebind.get("baseline_candidate_venues") or [])
        != REQUIRED_CANDIDATE_VENUES
        or set(rebind.get("current_active_venues") or []) != REQUIRED_VENUES
        or set(rebind.get("current_candidate_venues") or [])
        != REQUIRED_CANDIDATE_VENUES
        or rebind.get("changed_dimensions") != TECHNICAL_REBIND_CHANGED_DIMENSIONS
    ):
        reasons.append("technical_exact_byte_rebind_binding_invalid")

    implementation = payload.get("implementation") or []
    if not isinstance(implementation, list):
        implementation = []
        reasons.append("implementation_not_list")
    by_role = {
        str(binding.get("role") or ""): binding
        for binding in implementation
        if isinstance(binding, Mapping)
    }
    if set(by_role) != set(EXPECTED_IMPLEMENTATION_PATHS) or len(by_role) != len(implementation):
        reasons.append("implementation_roles_invalid")
    for role, expected_path in EXPECTED_IMPLEMENTATION_PATHS.items():
        binding = by_role.get(role)
        if binding is None:
            continue
        binding_path = Path(str(binding.get("path") or "")).resolve()
        if binding_path != expected_path:
            reasons.append(f"implementation_path_mismatch:{role}")
            continue
        if not binding_path.is_file():
            reasons.append(f"implementation_file_missing:{role}")
            continue
        expected_sha = str(binding.get("sha256") or "")
        if len(expected_sha) != 64 or file_sha256(binding_path) != expected_sha:
            reasons.append(f"implementation_hash_mismatch:{role}")

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


def build_rebound_plan(source_path: str | Path, generated_at_utc: str) -> dict[str, Any]:
    source = Path(source_path)
    if source.resolve() != SUPERSEDED_PLAN_PATH.resolve():
        raise ValueError("source_plan_must_be_immutable_v10")
    if file_sha256(source) != SUPERSEDED_PLAN["plan_file_sha256"]:
        raise ValueError("source_plan_file_sha256_mismatch")
    if _git_blob_sha256(source) != SUPERSEDED_PLAN["plan_file_sha256"]:
        raise ValueError("source_plan_git_blob_sha256_mismatch")
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    if (
        source_payload.get("plan_id") != SUPERSEDED_PLAN["plan_id"]
        or source_payload.get("plan_hash") != SUPERSEDED_PLAN["plan_hash"]
        or canonical_plan_hash(source_payload) != SUPERSEDED_PLAN["plan_hash"]
    ):
        raise ValueError("source_plan_identity_mismatch")

    payload = copy.deepcopy(source_payload)
    payload["plan_id"] = PLAN_ID
    payload["generated_at_utc"] = generated_at_utc
    payload["implementation"] = [
        {
            "role": role,
            "path": str(path),
            "sha256": file_sha256(path),
            "change": {
                "kind": "preipo_trusted_git_path_cwe426_rebind_v11",
                "superseded_plan_hash": SUPERSEDED_PLAN["plan_hash"],
                "superseded_plan_file_sha256": SUPERSEDED_PLAN["plan_file_sha256"],
                "research_scope_changed": False,
                "reason": (
                    "Bind the CWE-426 fix that permits only the fixed platform Git "
                    "executable with a 15-second fail-closed timeout; research scope "
                    "and strategy semantics remain unchanged."
                ),
            },
        }
        for role, path in EXPECTED_IMPLEMENTATION_PATHS.items()
    ]
    payload["supersedes_plan_id"] = SUPERSEDED_PLAN["plan_id"]
    payload["supersedes_plan_hash"] = SUPERSEDED_PLAN["plan_hash"]
    payload["supersedes_plan_file_sha256"] = SUPERSEDED_PLAN["plan_file_sha256"]
    payload["supersedes_plan_path"] = SUPERSEDED_PLAN["plan_path"]
    payload.setdefault("source_bindings", {})["technical_rebind"] = {
        "kind": "preipo_trusted_git_path_cwe426_rebind_v11",
        "supersedes_plan_id": SUPERSEDED_PLAN["plan_id"],
        "supersedes_plan_hash": SUPERSEDED_PLAN["plan_hash"],
        "supersedes_plan_file_sha256": SUPERSEDED_PLAN["plan_file_sha256"],
        "supersedes_plan_path": SUPERSEDED_PLAN["plan_path"],
        "research_scope_changed": False,
        "baseline_active_venues": sorted(REQUIRED_VENUES),
        "baseline_candidate_venues": sorted(REQUIRED_CANDIDATE_VENUES),
        "current_active_venues": sorted(REQUIRED_VENUES),
        "current_candidate_venues": sorted(REQUIRED_CANDIDATE_VENUES),
        "changed_dimensions": TECHNICAL_REBIND_CHANGED_DIMENSIONS,
        "reason": (
            "Replace PATH-resolved Git with the fixed platform executable, enforce a "
            "15-second fail-closed timeout, refresh exact raw file bindings and move "
            "the launcher default; all research contracts are unchanged."
        ),
    }
    payload["commands"] = {
        "plan_check": (
            "python trading_mvp/src/preipo_plan.py --plan "
            "docs/plans/preipo-perpetual-event-planonly-20260826-v11.json --json"
        ),
        "automation": (
            "pwsh -NoProfile -ExecutionPolicy Bypass -File "
            "tools/start_preipo_perpetual_event_automation_visible.ps1 -ScheduledTick -Json"
        ),
        "status": (
            "pwsh -NoProfile -ExecutionPolicy Bypass -File "
            "tools/start_preipo_perpetual_event_automation_visible.ps1 -Status -Json"
        ),
    }
    payload["plan_hash"] = canonical_plan_hash(payload)
    return payload


def write_rebound_plan(source_path: str | Path, generated_at_utc: str) -> Path:
    if DEFAULT_PLAN_PATH.exists():
        raise FileExistsError(f"refusing to overwrite immutable plan: {DEFAULT_PLAN_PATH}")
    payload = build_rebound_plan(source_path, generated_at_utc)
    DEFAULT_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PLAN_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    result = validate_plan(DEFAULT_PLAN_PATH)
    if not result["ok"]:
        raise ValueError(f"generated_plan_invalid:{result['reasons']}")
    return DEFAULT_PLAN_PATH


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate the immutable pre-IPO PlanOnly")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN_PATH))
    parser.add_argument("--write-rebind", action="store_true")
    parser.add_argument("--source-plan", default=str(SUPERSEDED_PLAN_PATH))
    parser.add_argument("--generated-at-utc", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.write_rebind:
        if not args.generated_at_utc:
            raise SystemExit("--generated-at-utc is required with --write-rebind")
        path = write_rebound_plan(args.source_plan, args.generated_at_utc)
        result = validate_plan(path)
        print(json.dumps({**result, "path": str(path)}, ensure_ascii=False, sort_keys=True))
        return 0
    result = validate_plan(args.plan)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
