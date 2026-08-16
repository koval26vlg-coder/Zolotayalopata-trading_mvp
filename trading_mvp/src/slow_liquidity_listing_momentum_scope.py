from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from listing_event_normalizer import parse_ts
from slow_liquidity_calendar_first_identity_close import (
    CLOSE_PLAN_PATH as PARENT_CLOSE_PLAN_PATH,
    PLAN_ID as PARENT_CLOSE_PLAN_ID,
)
from slow_liquidity_calendar_first_universe import (
    CALENDAR_FILE_SHA256,
    CALENDAR_PATH,
    CALENDAR_SUMMARY_FILE_SHA256,
    CALENDAR_SUMMARY_PATH,
    materialize_two_venue_bases,
)
from slow_liquidity_official_identity_proposal import (
    EXPECTED_BASES,
    EXPECTED_VENUES,
    QUALITY_DECISION,
    SOURCE_PLAN_HASH,
    SOURCE_RUN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_scope_planonly_v1"
PLAN_ID = "slow_liquidity_listing_momentum_scope_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPE_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-scope-planonly-20260816.json"
)
PARENT_CLOSE_PLAN_HASH = (
    "55b764789af94652e59471ecf8a8916680d7159744e05456274265f4a6ec0407"
)
PARENT_CLOSE_PLAN_FILE_SHA256 = (
    "2485ddca3712b8af35455ab13cfa6e28fbe989858c6d8ec69010fe60a0994066"
)
PARENT_CLOSE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-calendar-first-identity-close-approval.json"
)
PARENT_CLOSE_RECEIPT_HASH = (
    "7aa6f8ce33433d4a0d5e8305f14ce0387a6919ec129510630fdadbb5986eb382"
)
PARENT_CLOSE_RECEIPT_FILE_SHA256 = (
    "9a46f489ba3d9accc3cecfd8a210edfa78eb37f7488c586f7f0a52753a309f88"
)
PARENT_CLOSE_RECEIPT_STATUS = "TWO_VENUE_OFFICIAL_IDENTITY_CLOSED_AS_INCOMPLETE"
PARENT_SELECTED_BASES_SHA256 = (
    "3b5c44955f309041867763e89731f074e0a9721e0d184537d253b48fbde56322"
)
V6_PLAN_HASH = SOURCE_PLAN_HASH
V6_PLAN_FILE_SHA256 = (
    "d649f61fb7adbd333ff5b979be8a9bcc3e0373beed6bcbe04c29583e34b03e94"
)
V6_QUALITY_PATH = Path(
    "E:/ZolotyayLopata-data/exports/trading-mvp/analysis/"
    "slow_liquidity_history_recollect_quality_20260813_"
    "pagecap_provenance_slotintegrity_v6.json"
)
V6_QUALITY_FILE_SHA256 = (
    "9f240efe9a300f4e1a57c6c8438eab63c9169bdf4bb9ff47f6cc50175e7e6a9e"
)
V6_OUTPUT_SHA256 = (
    "96ea0272f95b0f47edb897b328ad1ee7ab2ef30489e9822f70301970cc228be9"
)
V6_MANIFEST_SHA256 = (
    "b4a45a66030cfdef957268053814372d40659a6c0202c8268ec9cb284731ef37"
)
V6_OK_ROWS = 30021
V6_HISTORY_DAYS = 56
V6_CLEAN_BASE_COUNT = 9
LISTING_EVENT_MEXC_GATE_QUALITY_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "listing_event_history_data_quality_20260709_002932.json"
)
LISTING_EVENT_MEXC_GATE_QUALITY_FILE_SHA256 = (
    "c8894a96937cba16172b7965edb58572014b507216f3821908340cd01e0db26a"
)
LISTING_EVENT_MEXC_GATE_QUALITY_DECISION = (
    "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN"
)
LISTING_EVENT_BITGET_QUALITY_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "listing_event_history_data_quality_20260709_093747.json"
)
LISTING_EVENT_BITGET_QUALITY_FILE_SHA256 = (
    "2183a9f3dc64ee45bf687e8ea730f457a5147eb1255f72079e948e5e9099667e"
)
LISTING_EVENT_REPLAY_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/backtests"
    / "listing_event_replay_planonly_20260709_095909.json"
)
LISTING_EVENT_REPLAY_FILE_SHA256 = (
    "c52ea4f6f8c13b49e2266ceaf7785f7139a3700c57d0a795366ce512390a1fe5"
)
LISTING_EVENT_REPLAY_DECISION = "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE"
AS_OF_UTC = "2026-08-16T00:00:00Z"
FIRST_DAYS_SEC = 3 * 86400
EXPECTED_TWO_VENUE_COUNT = 407
EXPECTED_CALENDAR_USDT_ROWS = 1239
EXPECTED_TWO_VENUE_EVENT_ROWS = 814
EXPECTED_AGE_BUCKETS = {
    "missing_ts": 0,
    "future_or_after_as_of": 0,
    "0_3d": 0,
    "4_7d": 0,
    "8_30d": 0,
    "31_90d": 1,
    "gt_90d": 406,
}
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
EXPECTED_APPROVAL_TEXT = (
    "Принимаю PlanOnly slow_liquidity_listing_momentum_scope_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: Listing "
    "Momentum — event-window first days after listing/announcement, не "
    "postprocess v6 30021. v6 = closed 9 / 56d 1h4h, identity incomplete, "
    "replay false. Calendar = public API snapshot, не official announcement. "
    "Не OHLCV, не replay v6, не reopen closed 9, не reopen listing-first, "
    "не reuse spot v2 consumer, не v7. Без evaluator, OOS, returns/PnL, "
    "grid/retune, paper/live, private API, реальных денег, плеча или маржи."
)


class ListingMomentumScopeError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingMomentumScopeError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _as_of_ts() -> float:
    return datetime.fromisoformat(AS_OF_UTC.replace("Z", "+00:00")).timestamp()


def _age_bucket(age_days: float) -> str:
    if age_days < 0:
        return "future_or_after_as_of"
    if age_days <= 3:
        return "0_3d"
    if age_days <= 7:
        return "4_7d"
    if age_days <= 30:
        return "8_30d"
    if age_days <= 90:
        return "31_90d"
    return "gt_90d"


def census_listing_momentum_calendar(path: Path) -> dict[str, Any]:
    two_venue = set(materialize_two_venue_bases(path))
    rows: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
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
            if not base:
                continue
            delisted = str(row.get("is_delisted") or "").strip().lower() == "true"
            event_ts = parse_ts(
                row.get("listed_ts")
                or row.get("listed_at_utc")
                or row.get("first_trade_ts_utc")
            )
            source_type = str(row.get("source_type") or "")
            source_counts[source_type] += 1
            rows.append(
                {
                    "venue": venue,
                    "base": base,
                    "delisted": delisted,
                    "event_ts": event_ts,
                    "source_type": source_type,
                }
            )
    earliest: dict[str, float] = {}
    two_venue_event_rows = 0
    for row in rows:
        if row["base"] not in two_venue or row["delisted"]:
            continue
        two_venue_event_rows += 1
        if row["event_ts"] is None:
            continue
        previous = earliest.get(row["base"])
        earliest[row["base"]] = (
            row["event_ts"]
            if previous is None
            else min(previous, float(row["event_ts"]))
        )
    as_of = _as_of_ts()
    buckets = {key: 0 for key in EXPECTED_AGE_BUCKETS}
    for base in two_venue:
        event_ts = earliest.get(base)
        if event_ts is None:
            buckets["missing_ts"] += 1
            continue
        buckets[_age_bucket((as_of - event_ts) / 86400.0)] += 1
    closed_in_calendar = sorted(
        {
            row["base"]
            for row in rows
            if row["base"] in set(EXPECTED_BASES)
        }
    )
    official_announcement_rows = sum(
        1
        for row in rows
        if "announcement" in str(row["source_type"]).lower()
        or "official" in str(row["source_type"]).lower()
    )
    return {
        "as_of_utc": AS_OF_UTC,
        "first_days_sec": FIRST_DAYS_SEC,
        "calendar_usdt_rows": len(rows),
        "calendar_delisted_rows": sum(1 for row in rows if row["delisted"]),
        "two_venue_base_count": len(two_venue),
        "two_venue_event_rows": two_venue_event_rows,
        "two_venue_with_timestamp_count": len(earliest),
        "source_type_counts": dict(sorted(source_counts.items())),
        "official_announcement_row_count": official_announcement_rows,
        "age_buckets_as_of": buckets,
        "first_days_sample_count": buckets["0_3d"],
        "closed_nine_present_in_calendar_count": len(closed_in_calendar),
        "calendar_source_class": "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
    }


def _bind_existing_file(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file():
        return
    _require(_sha256_file(path) == expected_sha256, f"{label} file hash mismatch")


def build_listing_momentum_scope_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_CLOSE_PLAN_PATH.is_file():
        _bind_existing_file(
            PARENT_CLOSE_PLAN_PATH,
            PARENT_CLOSE_PLAN_FILE_SHA256,
            "parent close plan",
        )
    if PARENT_CLOSE_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_CLOSE_RECEIPT_PATH.read_text(encoding="utf-8"))
        _bind_existing_file(
            PARENT_CLOSE_RECEIPT_PATH,
            PARENT_CLOSE_RECEIPT_FILE_SHA256,
            "parent close receipt",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_CLOSE_RECEIPT_HASH,
            "parent close receipt hash mismatch",
        )
        _require(
            receipt.get("status") == PARENT_CLOSE_RECEIPT_STATUS,
            "two-venue identity not closed incomplete",
        )
        _require(receipt.get("network_authorized") is False, "parent opened network")
        _require(receipt.get("identity_verdict") is False, "parent issued verdict")
        _require(
            receipt.get("ohlcv_collect_authorized") is False,
            "parent opened ohlcv",
        )
    _require(CALENDAR_PATH.is_file(), "frozen listing calendar missing")
    _require(
        _sha256_file(CALENDAR_PATH) == CALENDAR_FILE_SHA256,
        "frozen listing calendar hash mismatch",
    )
    if CALENDAR_SUMMARY_PATH.is_file():
        _bind_existing_file(
            CALENDAR_SUMMARY_PATH,
            CALENDAR_SUMMARY_FILE_SHA256,
            "calendar summary",
        )
    _bind_existing_file(V6_QUALITY_PATH, V6_QUALITY_FILE_SHA256, "v6 quality")
    if V6_QUALITY_PATH.is_file():
        quality = json.loads(V6_QUALITY_PATH.read_text(encoding="utf-8"))
        _require(quality.get("accepted") is True, "v6 quality not accepted")
        _require(quality.get("replay_allowed") is False, "v6 replay already allowed")
        _require(
            quality.get("normalizer_allowed") is False,
            "v6 normalizer already allowed",
        )
        _require(
            quality.get("fixed_signal_plan_allowed") is False,
            "v6 fixed-signal already allowed",
        )
        _require(quality.get("decision") == QUALITY_DECISION, "v6 quality decision")
        _require(
            int((quality.get("metrics") or {}).get("ok_rows") or 0) == V6_OK_ROWS,
            "v6 ok_rows mismatch",
        )
        _require(
            list((quality.get("clean_markets") or {}).get("two_exchange_bases") or [])
            == list(EXPECTED_BASES)
            or set((quality.get("clean_markets") or {}).get("two_exchange_bases") or [])
            == set(EXPECTED_BASES),
            "v6 bases are not the closed 9",
        )
    _bind_existing_file(
        LISTING_EVENT_MEXC_GATE_QUALITY_PATH,
        LISTING_EVENT_MEXC_GATE_QUALITY_FILE_SHA256,
        "listing-event mexc/gate quality",
    )
    _bind_existing_file(
        LISTING_EVENT_BITGET_QUALITY_PATH,
        LISTING_EVENT_BITGET_QUALITY_FILE_SHA256,
        "listing-event bitget quality",
    )
    _bind_existing_file(
        LISTING_EVENT_REPLAY_PATH,
        LISTING_EVENT_REPLAY_FILE_SHA256,
        "listing-event replay",
    )
    census = census_listing_momentum_calendar(CALENDAR_PATH)
    _require(
        census["two_venue_base_count"] == EXPECTED_TWO_VENUE_COUNT,
        "two-venue count changed",
    )
    _require(
        census["calendar_usdt_rows"] == EXPECTED_CALENDAR_USDT_ROWS,
        "calendar row count changed",
    )
    _require(
        census["two_venue_event_rows"] == EXPECTED_TWO_VENUE_EVENT_ROWS,
        "two-venue event row count changed",
    )
    _require(
        census["age_buckets_as_of"] == EXPECTED_AGE_BUCKETS,
        "age buckets changed",
    )
    _require(census["first_days_sample_count"] == 0, "first-days sample is not empty")
    _require(
        census["official_announcement_row_count"] == 0,
        "calendar unexpectedly contains official announcements",
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_SCOPE_ACCEPTANCE",
        "prepared_checkpoint": "REMAP_LISTING_MOMENTUM_NOT_V6_POSTPROCESS",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_verdict_allowed": False,
        "identity_execution_authorized": False,
        "ohlcv_collect_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "v6_postprocess_authorized": False,
        "v6_normalizer_authorized": False,
        "v6_fixed_signal_authorized": False,
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
        "evidence_class": "LISTING_MOMENTUM_SCOPE_REMAP_PACKET",
        "identity_before_ohlcv_collect": True,
        "two_venue_official_identity_complete": False,
        "listing_momentum_dataset_class": "NOT_V6_TRAILING_HISTORY",
        "dashboard_claim": {
            "label": "Slow Liquidity / Listing Momentum",
            "claimed_state": "ACTIVE / READY_FOR_POSTPROCESS",
            "claimed_dataset": "v6 30021 rows from 2026-08-13 awaiting final postprocess",
            "matches_listing_momentum": False,
        },
        "goal": (
            "Remap track 2 Listing Momentum away from v6 trailing 56-day "
            "history of the closed 9. Listing Momentum is first-days "
            "event-window drift/volume after listing or announcement. This "
            "packet does not authorize OHLCV, replay, or an identity verdict."
        ),
        "v6_trailing_history": {
            "run_id": SOURCE_RUN_ID,
            "plan_hash": V6_PLAN_HASH,
            "plan_file_sha256": V6_PLAN_FILE_SHA256,
            "quality_path": str(V6_QUALITY_PATH),
            "quality_file_sha256": V6_QUALITY_FILE_SHA256,
            "quality_decision": QUALITY_DECISION,
            "output_sha256": V6_OUTPUT_SHA256,
            "manifest_sha256": V6_MANIFEST_SHA256,
            "ok_rows": V6_OK_ROWS,
            "history_days": V6_HISTORY_DAYS,
            "clean_1h4h_two_venue_base_count": V6_CLEAN_BASE_COUNT,
            "bases": list(EXPECTED_BASES),
            "window_aligned_to_listing_or_announcement": False,
            "technical_quality_accepted": True,
            "replay_allowed": False,
            "normalizer_allowed": False,
            "fixed_signal_plan_allowed": False,
            "usable_as_listing_momentum": False,
        },
        "prior_listing_event_branch": {
            "hypothesis_id": "listing_event_drift_reversal",
            "mexc_gate_quality_path": str(LISTING_EVENT_MEXC_GATE_QUALITY_PATH),
            "mexc_gate_quality_file_sha256": LISTING_EVENT_MEXC_GATE_QUALITY_FILE_SHA256,
            "mexc_gate_quality_decision": LISTING_EVENT_MEXC_GATE_QUALITY_DECISION,
            "bitget_quality_path": str(LISTING_EVENT_BITGET_QUALITY_PATH),
            "bitget_quality_file_sha256": LISTING_EVENT_BITGET_QUALITY_FILE_SHA256,
            "replay_path": str(LISTING_EVENT_REPLAY_PATH),
            "replay_file_sha256": LISTING_EVENT_REPLAY_FILE_SHA256,
            "replay_decision": LISTING_EVENT_REPLAY_DECISION,
            "closed_on_prior_data": True,
            "retune_authorized": False,
        },
        "parent_calendar_first_identity_close": {
            "plan_id": PARENT_CLOSE_PLAN_ID,
            "plan_path": str(PARENT_CLOSE_PLAN_PATH),
            "plan_hash": PARENT_CLOSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_CLOSE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_CLOSE_RECEIPT_PATH),
            "receipt_hash": PARENT_CLOSE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_CLOSE_RECEIPT_FILE_SHA256,
            "status": PARENT_CLOSE_RECEIPT_STATUS,
        },
        "frozen_calendar": {
            "path": str(CALENDAR_PATH),
            "file_sha256": CALENDAR_FILE_SHA256,
            "summary_path": str(CALENDAR_SUMMARY_PATH),
            "summary_file_sha256": CALENDAR_SUMMARY_FILE_SHA256,
            "source_class": "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
        },
        "calendar_census": census,
        "listing_momentum_blockers": [
            "V6_IS_TRAILING_56D_HISTORY_OF_CLOSED_NINE",
            "TWO_VENUE_OFFICIAL_IDENTITY_CLOSED_AS_INCOMPLETE",
            "IDENTITY_BEFORE_OHLCV",
            "CALENDAR_IS_PUBLIC_API_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
            "FIRST_DAYS_SAMPLE_EMPTY_ON_FROZEN_CALENDAR",
            "PRIOR_LISTING_EVENT_BRANCH_CLOSED_NO_ROBUST_EDGE",
        ],
        "frozen_html_consumer_not_reused": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "reused": False,
        },
        "still_forbidden": [
            "V6_POSTPROCESS_AS_LISTING_MOMENTUM",
            "REOPEN_CLOSED_NINE",
            "REOPEN_LISTING_EVENT_ON_PRIOR_DATA",
            "REOPEN_LISTING_FIRST_NAME_DISCOVERY",
            "REUSE_SPOT_V2_HTML_CONSUMER",
            "INVENT_TICKERS",
            "INVENT_OFFICIAL_ANNOUNCEMENT_DATES",
            "OHLCV_COLLECT",
            "IDENTITY_VERDICT",
            "BING_OR_SITEMAP",
            "REPLAY_OR_GRID",
            "EVALUATOR_OR_OOS",
            "PAPER_OR_LIVE",
            "20260815-V7",
        ],
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_execution_allowed": False,
            "identity_verdict_allowed": False,
            "ohlcv_collect_allowed": False,
            "v6_postprocess_allowed": False,
            "replay_allowed": False,
            "scope_accept_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_listing_momentum_scope_plan(plan)
    return plan


def validate_listing_momentum_scope_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "listing momentum scope schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "listing momentum scope plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_EXACT_HASH_BOUND_SCOPE_ACCEPTANCE",
        "status mismatch",
    )
    _require(
        plan.get("prepared_checkpoint") == "REMAP_LISTING_MOMENTUM_NOT_V6_POSTPROCESS",
        "checkpoint mismatch",
    )
    _require(plan.get("selected_base_count") == EXPECTED_TWO_VENUE_COUNT, "selected")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(
        plan.get("selected_bases_sha256") == PARENT_SELECTED_BASES_SHA256,
        "selected bases hash",
    )
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("ohlcv_collect_authorized") is False, "ohlcv already authorized")
    _require(plan.get("replay_allowed") is False, "replay already allowed")
    _require(
        plan.get("v6_postprocess_authorized") is False,
        "v6 postprocess already authorized",
    )
    _require(
        plan.get("listing_first_name_discovery_reopened") is False,
        "listing-first reopened",
    )
    _require(plan.get("closed_nine_reopened") is False, "closed 9 reopened")
    _require(
        plan.get("listing_event_closed_branch_reopened") is False,
        "listing-event branch reopened",
    )
    _require(
        plan.get("listing_momentum_dataset_class") == "NOT_V6_TRAILING_HISTORY",
        "dataset class",
    )
    _require(
        plan.get("dashboard_claim", {}).get("matches_listing_momentum") is False,
        "dashboard claim treated as listing momentum",
    )
    v6 = plan.get("v6_trailing_history") or {}
    _require(v6.get("ok_rows") == V6_OK_ROWS, "v6 rows")
    _require(v6.get("history_days") == V6_HISTORY_DAYS, "v6 days")
    _require(v6.get("usable_as_listing_momentum") is False, "v6 usable")
    _require(v6.get("replay_allowed") is False, "v6 replay")
    _require(
        v6.get("window_aligned_to_listing_or_announcement") is False,
        "v6 window claimed listing-aligned",
    )
    prior = plan.get("prior_listing_event_branch") or {}
    _require(
        prior.get("replay_decision") == LISTING_EVENT_REPLAY_DECISION,
        "listing-event replay decision",
    )
    _require(prior.get("closed_on_prior_data") is True, "listing-event not closed")
    _require(prior.get("retune_authorized") is False, "listing-event retune")
    census = plan.get("calendar_census") or {}
    _require(census.get("first_days_sample_count") == 0, "first-days sample")
    _require(census.get("official_announcement_row_count") == 0, "official rows")
    _require(census.get("age_buckets_as_of") == EXPECTED_AGE_BUCKETS, "age buckets")
    _require(
        census.get("calendar_source_class")
        == "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
        "calendar source class",
    )
    parent = plan.get("parent_calendar_first_identity_close") or {}
    _require(parent.get("plan_hash") == PARENT_CLOSE_PLAN_HASH, "parent close hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_CLOSE_PLAN_FILE_SHA256,
        "parent close file hash",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    _require(auth.get("v6_postprocess_allowed") is False, "v6 postprocess allowed")
    _require(auth.get("scope_accept_allowed") is False, "scope accept allowed")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")


def write_listing_momentum_scope_plan(generated_at_utc: str) -> Path:
    plan = build_listing_momentum_scope_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if SCOPE_PLAN_PATH.exists():
        _require(
            SCOPE_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {SCOPE_PLAN_PATH}",
        )
        return SCOPE_PLAN_PATH
    SCOPE_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_PLAN_PATH.write_text(payload, encoding="utf-8")
    return SCOPE_PLAN_PATH


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
    path = write_listing_momentum_scope_plan(generated)
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
                "v6_postprocess_authorized": False,
                "first_days_sample_count": plan["calendar_census"][
                    "first_days_sample_count"
                ],
                "network_authorized": False,
                "ohlcv_collect_authorized": False,
                "replay_allowed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
