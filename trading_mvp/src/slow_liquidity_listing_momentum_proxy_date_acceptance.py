from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from listing_event_normalizer import parse_ts
from slow_liquidity_calendar_first_universe import (
    CALENDAR_FILE_SHA256,
    CALENDAR_PATH,
    materialize_two_venue_bases,
)
from slow_liquidity_listing_momentum_first_days_close import (
    CLOSE_PLAN_PATH as PARENT_CLOSE_PLAN_PATH,
    PLAN_ID as PARENT_CLOSE_PLAN_ID,
)
from slow_liquidity_listing_momentum_scope import (
    EXPECTED_AGE_BUCKETS,
    EXPECTED_CALENDAR_USDT_ROWS,
    EXPECTED_TWO_VENUE_COUNT,
    EXPECTED_TWO_VENUE_EVENT_ROWS,
    FIRST_DAYS_SEC,
    PARENT_SELECTED_BASES_SHA256,
    census_listing_momentum_calendar,
)
from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_spot_v2_official_page_discovery import (
    canonical_hash,
    canonical_json_bytes,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_proxy_date_acceptance_planonly_v1"
PLAN_ID = "slow_liquidity_listing_momentum_proxy_date_acceptance_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-proxy-date-acceptance-planonly-20260816.json"
)
MATERIALIZATION_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_proxy_date_materialization_20260816.json"
)
RECEIPT_SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_proxy_date_acceptance_receipt_v1"
RECEIPT_STATUS = "PROXY_LISTING_DATE_SOURCE_ACCEPTED"
PARENT_SCOPE_PLAN_HASH = (
    "4c89ce8e9a6d1065da4f6987ebee04ae8357481a4596084239796f78197a848b"
)
PARENT_SCOPE_PLAN_FILE_SHA256 = (
    "a31cc2850f4ba38443ac328f4014c62407e24fab0b106918ce9ecfa01c64b178"
)
PARENT_SCOPE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-momentum-scope-approval.json"
)
PARENT_SCOPE_RECEIPT_HASH = (
    "9e11996cd01adde63f603b56afc2030825476120b55e3aea61a879f4e6772be9"
)
PARENT_SCOPE_RECEIPT_FILE_SHA256 = (
    "ed65d308d64e671969ff66eeb52f618d1b7ed9f9f3fa41f343c51b71d9a8c771"
)
PARENT_CLOSE_PLAN_HASH = (
    "fbb7c535941c672ee65a11d1bbb868626263a5d59c84a028bcc793a05385c5ae"
)
PARENT_CLOSE_PLAN_FILE_SHA256 = (
    "f54399987d98ef76e7917e88eef327dc2ba8d2af87b4f9a5bcb53fe7576d861b"
)
PARENT_CLOSE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-momentum-first-days-close-approval.json"
)
PARENT_CLOSE_RECEIPT_HASH = (
    "4be62cb7281420eb49678fb96f05c3ab32367b8d39c6a9a6bf676669bf7ea7db"
)
PARENT_CLOSE_RECEIPT_FILE_SHA256 = (
    "07cc19f86d57a87e6f15d7499606ad9d832d7f3cf553676eb8fbab5e6087e2cf"
)
PARENT_CLOSE_RECEIPT_STATUS = "LISTING_MOMENTUM_FIRST_DAYS_CLOSED_AS_INCOMPLETE"
PROXY_SOURCE_CLASS = "PROXY_TRADING_START_NOT_OFFICIAL_ANNOUNCEMENT"
AGREEMENT_BUCKETS = (
    "both_venues_le_1h",
    "both_venues_le_24h",
    "both_venues_gt_24h",
    "one_venue_only",
    "missing",
)
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
EXPECTED_USER_DECISION_TEXT = "принять proxy-источник даты листинга"
EXPECTED_APPROVAL_TEXT = (
    "Принимаю PlanOnly "
    "slow_liquidity_listing_momentum_proxy_date_acceptance_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: принять "
    "proxy-источник даты листинга (класс PROXY_TRADING_START_NOT_OFFICIAL_"
    "ANNOUNCEMENT: замороженный calendar listed_ts firstOpenTime / "
    "min_nonzero_buy_start_sell_start, корроборация earliest available 1h "
    "open time при сборе), limitations в acceptance contract, retrospective "
    "event windows для 407 имён, не official announcement, не identity "
    "verdict, не invent URL, не reopen closed 9, не reuse spot v2 consumer, "
    "не v7. Сбор first-days OHLCV — отдельный PlanOnly + видимый запуск. "
    "Без evaluator, OOS, returns/PnL, grid/retune, paper/live, private API, "
    "реальных денег, плеча или маржи."
)


class ListingMomentumProxyDateAcceptanceError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingMomentumProxyDateAcceptanceError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _agreement_bucket(mexc_ts: float | None, gate_ts: float | None) -> str:
    if mexc_ts is None and gate_ts is None:
        return "missing"
    if mexc_ts is None or gate_ts is None:
        return "one_venue_only"
    delta_sec = abs(mexc_ts - gate_ts)
    if delta_sec <= 3600.0:
        return "both_venues_le_1h"
    if delta_sec <= 86400.0:
        return "both_venues_le_24h"
    return "both_venues_gt_24h"


def census_proxy_listing_dates(path: Path) -> dict[str, Any]:
    two_venue = set(materialize_two_venue_bases(path))
    per_venue_ts: dict[str, dict[str, float]] = {base: {} for base in two_venue}
    timestamp_source_counts: dict[str, int] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            venue = str(row.get("exchange") or "").strip().lower()
            if venue == "gate":
                venue = "gateio"
            if venue not in EXPECTED_VENUES:
                continue
            if str(row.get("quote") or "").strip().upper() != "USDT":
                continue
            base = str(row.get("base") or "").strip().upper()
            if base not in two_venue:
                continue
            if str(row.get("is_delisted") or "").strip().lower() == "true":
                continue
            event_ts = parse_ts(row.get("listed_ts"))
            if event_ts is None:
                event_ts = parse_ts(row.get("first_trade_ts_utc"))
            source = str(row.get("listing_timestamp_source") or "").strip()
            if event_ts is not None:
                previous = per_venue_ts[base].get(venue)
                if previous is None or event_ts < previous:
                    per_venue_ts[base][venue] = event_ts
                if source:
                    timestamp_source_counts[source] = (
                        timestamp_source_counts.get(source, 0) + 1
                    )
    agreement_counts = {key: 0 for key in AGREEMENT_BUCKETS}
    records: list[dict[str, Any]] = []
    for base in sorted(two_venue):
        mexc_ts = per_venue_ts[base].get("mexc")
        gate_ts = per_venue_ts[base].get("gateio")
        available = [ts for ts in (mexc_ts, gate_ts) if ts is not None]
        proxy_ts = min(available) if available else None
        bucket = _agreement_bucket(mexc_ts, gate_ts)
        agreement_counts[bucket] += 1
        records.append(
            {
                "base": base,
                "mexc_listed_ts": mexc_ts,
                "gateio_listed_ts": gate_ts,
                "proxy_event_ts": proxy_ts,
                "agreement_bucket": bucket,
                "window_start_ts": proxy_ts,
                "window_end_ts": (
                    proxy_ts + FIRST_DAYS_SEC if proxy_ts is not None else None
                ),
            }
        )
    return {
        "two_venue_base_count": len(two_venue),
        "timestamp_source_counts": dict(sorted(timestamp_source_counts.items())),
        "agreement_buckets": agreement_counts,
        "proxy_event_available_count": sum(
            1 for record in records if record["proxy_event_ts"] is not None
        ),
        "records": records,
    }


def _bind_existing_file(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file():
        return
    _require(_sha256_file(path) == expected_sha256, f"{label} file hash mismatch")


def build_proxy_date_acceptance_plan(generated_at_utc: str) -> dict[str, Any]:
    _bind_existing_file(
        PARENT_CLOSE_PLAN_PATH,
        PARENT_CLOSE_PLAN_FILE_SHA256,
        "parent first-days close plan",
    )
    if PARENT_CLOSE_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_CLOSE_RECEIPT_PATH.read_text(encoding="utf-8"))
        _bind_existing_file(
            PARENT_CLOSE_RECEIPT_PATH,
            PARENT_CLOSE_RECEIPT_FILE_SHA256,
            "parent first-days close receipt",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_CLOSE_RECEIPT_HASH,
            "parent first-days close receipt hash mismatch",
        )
        _require(
            receipt.get("status") == PARENT_CLOSE_RECEIPT_STATUS,
            "listing momentum first-days not closed incomplete",
        )
        _require(receipt.get("network_authorized") is False, "parent opened network")
        _require(
            receipt.get("identity_verdict") is False,
            "parent issued identity verdict",
        )
    _bind_existing_file(
        PARENT_SCOPE_RECEIPT_PATH,
        PARENT_SCOPE_RECEIPT_FILE_SHA256,
        "parent scope receipt",
    )
    if PARENT_SCOPE_RECEIPT_PATH.is_file():
        scope_receipt = json.loads(
            PARENT_SCOPE_RECEIPT_PATH.read_text(encoding="utf-8")
        )
        _require(
            scope_receipt.get("receipt_hash") == PARENT_SCOPE_RECEIPT_HASH,
            "parent scope receipt hash mismatch",
        )
        _require(
            scope_receipt.get("status")
            == "ACCEPTED_LISTING_MOMENTUM_SCOPE_NOT_V6_POSTPROCESS",
            "listing momentum scope not accepted",
        )
    _require(CALENDAR_PATH.is_file(), "frozen listing calendar missing")
    _require(
        _sha256_file(CALENDAR_PATH) == CALENDAR_FILE_SHA256,
        "frozen listing calendar hash mismatch",
    )
    calendar_census = census_listing_momentum_calendar(CALENDAR_PATH)
    _require(
        calendar_census["two_venue_base_count"] == EXPECTED_TWO_VENUE_COUNT,
        "two-venue count changed",
    )
    _require(
        calendar_census["calendar_usdt_rows"] == EXPECTED_CALENDAR_USDT_ROWS,
        "calendar row count changed",
    )
    _require(
        calendar_census["two_venue_event_rows"] == EXPECTED_TWO_VENUE_EVENT_ROWS,
        "two-venue event row count changed",
    )
    _require(
        calendar_census["age_buckets_as_of"] == EXPECTED_AGE_BUCKETS,
        "age buckets changed",
    )
    proxy_census = census_proxy_listing_dates(CALENDAR_PATH)
    _require(
        proxy_census["two_venue_base_count"] == EXPECTED_TWO_VENUE_COUNT,
        "proxy census base count changed",
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_PROXY_LISTING_DATE_ACCEPTANCE_RECEIPT",
        "prepared_checkpoint": "ACCEPT_PROXY_LISTING_DATE_SOURCE_USER_CONTRACT_DECISION",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_verdict_allowed": False,
        "identity_execution_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "ohlcv_collect_authorized": False,
        "proxy_date_materialization_authorized": False,
        "proxy_treated_as_official_announcement": False,
        "spot_v2_runtime_reuse": False,
        "listing_first_name_discovery_reopened": False,
        "closed_nine_reopened": False,
        "listing_event_closed_branch_reopened": False,
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_base_count": EXPECTED_TWO_VENUE_COUNT,
        "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
        "invented_ticker_count": 0,
        "proxy_listing_date_source": {
            "source_class": PROXY_SOURCE_CLASS,
            "primary": {
                "artifact": "frozen listing calendar",
                "file_sha256": CALENDAR_FILE_SHA256,
                "mexc_field": "listed_ts (firstOpenTime)",
                "gateio_field": "listed_ts (min_nonzero_buy_start_sell_start)",
                "fallback_field": "first_trade_ts_utc",
            },
            "corroboration_at_collect": (
                "earliest available 1h kline open time per venue; flags "
                "history_truncated when earliest bar is materially after "
                "proxy_event_ts and proxy_ts_after_first_bar when earlier"
            ),
            "selection_rule": "min non-null listed_ts across both venues",
            "usable_as_official_announcement_date": False,
        },
        "proxy_first_days_semantics": {
            "live_first_days_sample_as_of_now": 0,
            "redefined_sample": "retrospective first-days event windows",
            "window_sec": FIRST_DAYS_SEC,
            "retrospective_window_available_count": proxy_census[
                "proxy_event_available_count"
            ],
        },
        "acceptance_contract_change": {
            "contract_field": "listing_date_evidence_class",
            "previous": "OFFICIAL_ANNOUNCEMENT_DATE_REQUIRED",
            "accepted_via_user_decision": PROXY_SOURCE_CLASS,
            "user_decision_text_expected": EXPECTED_USER_DECISION_TEXT,
            "two_venue_official_identity_complete": False,
            "ticker_pairing_class": "SAME_TICKER_STRING_TWO_VENUE_ASSUMPTION",
            "announcement_lead_time_available": False,
        },
        "limitations": [
            "SURVIVORSHIP_BIAS_CURRENT_SNAPSHOT: universe from current public "
            "API snapshot; assets delisted before the snapshot are absent",
            "TRADING_START_NOT_ANNOUNCEMENT: proxy t0 is first trade time; no "
            "announcement lead time exists in this evidence class",
            "HISTORY_DEPTH_TRUNCATION: exchange 1h history may not reach back "
            "to proxy_event_ts; affected windows must be flagged, not silently "
            "used",
            "SAME_TICKER_STRING_PAIRING: two-venue identity remains formally "
            "incomplete; pairing uses identical base ticker strings",
            "PRIOR_LISTING_EVENT_BRANCH_REJECTED: proxy-dated evidence alone "
            "cannot overturn the prior listing_event rejection without "
            "materially different data or method",
        ],
        "acceptance_gate_implication": (
            "Any ACCEPT on proxy-dated evidence is capped at evidence class "
            "PROXY_DATE; terminal ACCEPT additionally requires a forward or "
            "announcement-grounded sample"
        ),
        "parent_first_days_close": {
            "plan_id": PARENT_CLOSE_PLAN_ID,
            "plan_path": str(PARENT_CLOSE_PLAN_PATH),
            "plan_hash": PARENT_CLOSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_CLOSE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_CLOSE_RECEIPT_PATH),
            "receipt_hash": PARENT_CLOSE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_CLOSE_RECEIPT_FILE_SHA256,
            "status": PARENT_CLOSE_RECEIPT_STATUS,
        },
        "parent_listing_momentum_scope": {
            "plan_hash": PARENT_SCOPE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_SCOPE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_SCOPE_RECEIPT_PATH),
            "receipt_hash": PARENT_SCOPE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_SCOPE_RECEIPT_FILE_SHA256,
        },
        "frozen_calendar": {
            "path": str(CALENDAR_PATH),
            "file_sha256": CALENDAR_FILE_SHA256,
            "source_class": "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
        },
        "calendar_census": calendar_census,
        "proxy_date_census": {
            key: value for key, value in proxy_census.items() if key != "records"
        },
        "collector_prerequisites": [
            "SEPARATE_HASH_BOUND_COLLECTOR_PLANONLY",
            "VISIBLE_LAUNCHER",
            "SYNTHETIC_AND_REGRESSION_TESTS",
            "PAGE_AND_RATE_LIMIT_CAPS",
            "NO_PRIVATE_API",
        ],
        "still_forbidden": [
            "TREAT_PROXY_DATE_AS_OFFICIAL_ANNOUNCEMENT",
            "CLAIM_ANNOUNCEMENT_LEAD_TIME",
            "INVENT_ANNOUNCEMENT_API_URL",
            "REOPEN_CLOSED_NINE",
            "REOPEN_LISTING_FIRST_NAME_DISCOVERY",
            "REUSE_SPOT_V2_HTML_CONSUMER",
            "IDENTITY_VERDICT",
            "V6_POSTPROCESS_AS_LISTING_MOMENTUM",
            "BING_OR_SITEMAP",
            "REPLAY_OR_GRID",
            "EVALUATOR_OR_OOS",
            "PAPER_OR_LIVE",
            "20260815-V7",
        ],
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
            "user_decision_binding": (
                "per standing policy the already-given user contract decision "
                "binds this plan via receipt without a second approval phrase"
            ),
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "proxy_date_materialization_allowed": False,
            "proxy_first_days_collector_plan_preparation_allowed": False,
            "actual_network_run_allowed": False,
            "ohlcv_collect_allowed": False,
            "replay_allowed": False,
            "evaluator_or_oos_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_proxy_date_acceptance_plan(plan)
    return plan


def validate_proxy_date_acceptance_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "proxy date schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "proxy date plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_PROXY_LISTING_DATE_ACCEPTANCE_RECEIPT",
        "status mismatch",
    )
    _require(
        plan.get("prepared_checkpoint")
        == "ACCEPT_PROXY_LISTING_DATE_SOURCE_USER_CONTRACT_DECISION",
        "checkpoint mismatch",
    )
    _require(plan.get("selected_base_count") == EXPECTED_TWO_VENUE_COUNT, "selected")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(
        plan.get("proxy_treated_as_official_announcement") is False,
        "proxy treated as official announcement",
    )
    source = plan.get("proxy_listing_date_source") or {}
    _require(
        source.get("source_class") == PROXY_SOURCE_CLASS,
        "proxy source class mismatch",
    )
    _require(
        source.get("usable_as_official_announcement_date") is False,
        "proxy usable as official date",
    )
    semantics = plan.get("proxy_first_days_semantics") or {}
    _require(
        semantics.get("live_first_days_sample_as_of_now") == 0,
        "live first-days sample is not empty",
    )
    _require(
        semantics.get("redefined_sample") == "retrospective first-days event windows",
        "redefined sample mismatch",
    )
    _require(
        semantics.get("retrospective_window_available_count")
        == EXPECTED_TWO_VENUE_COUNT,
        "retrospective windows not covering the full universe",
    )
    _require(
        len(plan.get("limitations") or []) >= 5,
        "acceptance-contract limitations missing",
    )
    contract = plan.get("acceptance_contract_change") or {}
    _require(
        contract.get("two_venue_official_identity_complete") is False,
        "identity claimed complete",
    )
    _require(
        contract.get("announcement_lead_time_available") is False,
        "announcement lead time claimed",
    )
    _require(
        plan.get("network_authorized") is False,
        "network already authorized",
    )
    _require(
        plan.get("ohlcv_collect_authorized") is False,
        "ohlcv already authorized",
    )
    _require(
        plan.get("proxy_date_materialization_authorized") is False,
        "materialization already authorized",
    )
    _require(plan.get("replay_allowed") is False, "replay already allowed")
    _require(
        plan.get("identity_verdict_allowed") is False,
        "identity verdict already allowed",
    )
    _require(
        plan.get("closed_nine_reopened") is False,
        "closed 9 reopened",
    )
    _require(
        plan.get("spot_v2_runtime_reuse") is False,
        "spot v2 consumer reused",
    )
    census = plan.get("calendar_census") or {}
    _require(
        census.get("age_buckets_as_of") == EXPECTED_AGE_BUCKETS,
        "age buckets",
    )
    _require(census.get("first_days_sample_count") == 0, "first-days sample")
    parent = plan.get("parent_first_days_close") or {}
    _require(parent.get("plan_hash") == PARENT_CLOSE_PLAN_HASH, "parent close hash")
    _require(
        parent.get("receipt_hash") == PARENT_CLOSE_RECEIPT_HASH,
        "parent close receipt",
    )
    scope = plan.get("parent_listing_momentum_scope") or {}
    _require(scope.get("plan_hash") == PARENT_SCOPE_PLAN_HASH, "parent scope hash")
    _require(
        scope.get("receipt_hash") == PARENT_SCOPE_RECEIPT_HASH,
        "parent scope receipt",
    )
    auth = plan.get("authorization_now") or {}
    _require(
        auth.get("actual_network_run_allowed") is False,
        "network allowed",
    )
    _require(
        auth.get("proxy_date_materialization_allowed") is False,
        "materialization allowed",
    )
    _require(
        auth.get("replay_allowed") is False,
        "replay allowed",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")


def write_proxy_date_acceptance_plan(generated_at_utc: str) -> Path:
    plan = build_proxy_date_acceptance_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if PROXY_PLAN_PATH.exists():
        _require(
            PROXY_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {PROXY_PLAN_PATH}",
        )
        return PROXY_PLAN_PATH
    PROXY_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROXY_PLAN_PATH.write_text(payload, encoding="utf-8")
    return PROXY_PLAN_PATH


def validate_acceptance_receipt(
    receipt: Mapping[str, Any], plan: Mapping[str, Any]
) -> None:
    _require(receipt.get("schema") == RECEIPT_SCHEMA, "receipt schema mismatch")
    _require(receipt.get("status") == RECEIPT_STATUS, "receipt status mismatch")
    _require(
        receipt.get("plan_hash") == plan.get("plan_hash"),
        "receipt binds a different plan hash",
    )
    _require(
        receipt.get("plan_file_sha256") == _sha256_file(PROXY_PLAN_PATH),
        "receipt binds a different plan file",
    )
    _require(
        receipt.get("user_decision_text") == EXPECTED_USER_DECISION_TEXT,
        "user decision text mismatch",
    )
    scope = receipt.get("authorized_scope") or {}
    _require(scope.get("proxy_date_materialization") is True, "materialization")
    _require(
        scope.get("proxy_first_days_collector_plan_preparation") is True,
        "collector plan preparation",
    )
    _require(scope.get("actual_network_run") is False, "network opened")
    _require(scope.get("ohlcv_collect") is False, "ohlcv opened")
    _require(scope.get("treat_proxy_as_official") is False, "proxy as official")
    _require(scope.get("identity_verdict") is False, "identity verdict")
    _require(scope.get("replay") is False, "replay")
    _require(scope.get("evaluator_or_oos") is False, "evaluator or oos")
    _require(scope.get("grid_or_retune") is False, "grid or retune")
    _require(scope.get("paper_or_live") is False, "paper or live")
    _require(scope.get("private_api") is False, "private api")
    _require(receipt.get("limitations_acknowledged") is True, "limitations")
    _require(
        receipt.get("receipt_hash") == _receipt_canonical_hash(receipt),
        "receipt hash mismatch",
    )


def _receipt_canonical_hash(receipt: Mapping[str, Any]) -> str:
    normalized = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def build_materialization_payload(
    receipt: Mapping[str, Any]
) -> dict[str, Any]:
    plan = json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))
    validate_acceptance_receipt(receipt, plan)
    proxy_census = census_proxy_listing_dates(CALENDAR_PATH)
    records = proxy_census["records"]
    payload: dict[str, Any] = {
        "schema": "trading_mvp_slow_liquidity_listing_momentum_proxy_date_materialization_v1",
        "source_class": PROXY_SOURCE_CLASS,
        "authorized_by_receipt": {
            "status": receipt.get("status"),
            "receipt_hash": receipt.get("receipt_hash"),
            "plan_hash": plan.get("plan_hash"),
        },
        "frozen_calendar": {
            "path": str(CALENDAR_PATH),
            "file_sha256": CALENDAR_FILE_SHA256,
        },
        "window_sec": FIRST_DAYS_SEC,
        "as_of_note": (
            "proxy dates are trading-start timestamps from the frozen current "
            "snapshot; not official announcement dates"
        ),
        "summary": {
            "two_venue_base_count": proxy_census["two_venue_base_count"],
            "proxy_event_available_count": proxy_census[
                "proxy_event_available_count"
            ],
            "agreement_buckets": proxy_census["agreement_buckets"],
            "timestamp_source_counts": proxy_census["timestamp_source_counts"],
        },
        "records": records,
        "materialization_hash_method": HASH_METHOD,
    }
    payload["materialization_hash"] = canonical_hash(payload)
    return payload


def write_materialization(receipt_path: Path, output_path: Path) -> Path:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload = build_materialization_payload(receipt)
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output_path.exists():
        _require(
            output_path.read_text(encoding="utf-8") == content,
            f"immutable artifact mismatch: {output_path}",
        )
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--accepted-receipt", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    if not args.write_plan and not args.materialize:
        raise SystemExit("no authorized action requested")
    if args.write_plan:
        generated = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        path = write_proxy_date_acceptance_plan(generated)
        plan = json.loads(path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "status": "PLAN_WRITTEN",
                    "path": str(path),
                    "plan_hash": plan["plan_hash"],
                    "plan_file_sha256": _sha256_file(path),
                    "exact_approval_text": fill_expected_approval_text(
                        plan["plan_hash"],
                        _sha256_file(path),
                    ),
                    "retrospective_window_available_count": plan[
                        "proxy_first_days_semantics"
                    ]["retrospective_window_available_count"],
                    "proxy_date_materialization_authorized": False,
                    "network_authorized": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.materialize:
        _require(
            bool(args.accepted_receipt),
            "materialization requires the accepted receipt path",
        )
        receipt_path = Path(args.accepted_receipt)
        output_path = Path(args.output) if args.output else MATERIALIZATION_PATH
        path = write_materialization(receipt_path, output_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "status": "MATERIALIZATION_WRITTEN",
                    "path": str(path),
                    "materialization_hash": payload["materialization_hash"],
                    "proxy_event_available_count": payload["summary"][
                        "proxy_event_available_count"
                    ],
                    "agreement_buckets": payload["summary"]["agreement_buckets"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
