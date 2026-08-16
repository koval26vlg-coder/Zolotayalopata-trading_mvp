from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from listing_calendar import GATE_CURRENCY_PAIRS_URL, MEXC_EXCHANGE_INFO_URL
from slow_liquidity_calendar_first_official_identity import GATE_CURRENCY_URL_PREFIX
from slow_liquidity_listing_announcement_discovery import GATE_INDEX_URL, MEXC_INDEX_URL
from slow_liquidity_listing_momentum_scope import (
    EXPECTED_AGE_BUCKETS,
    EXPECTED_TWO_VENUE_COUNT,
    PARENT_SELECTED_BASES_SHA256,
    SCOPE_PLAN_PATH as PARENT_SCOPE_PLAN_PATH,
    PLAN_ID as PARENT_SCOPE_PLAN_ID,
)
from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_momentum_official_date_planonly_v1"
PLAN_ID = "slow_liquidity_listing_momentum_official_date_unavailable_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATE_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-listing-momentum-official-date-unavailable-planonly-20260816.json"
)
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
PARENT_SCOPE_RECEIPT_STATUS = "ACCEPTED_LISTING_MOMENTUM_SCOPE_NOT_V6_POSTPROCESS"
PARENT_LISTING_FIRST_CLOSE_STATUS = "LISTING_FIRST_CLOSED_AS_UNREACHABLE"
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
EXPECTED_APPROVAL_TEXT = (
    "Принимаю PlanOnly "
    "slow_liquidity_listing_momentum_official_date_unavailable_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: "
    "documented official announcement/listing date method нет, "
    "firstOpenTime/buy_start/sell_start не official announcement, "
    "HTML indexes/article уже исчерпаны, не invent URL, не OHLCV, "
    "не replay v6, не reopen closed 9, не reopen listing-first, "
    "не reuse spot v2 consumer, не v7. Без evaluator, OOS, returns/PnL, "
    "grid/retune, paper/live, private API, реальных денег, плеча или маржи."
)


class ListingMomentumOfficialDateError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingMomentumOfficialDateError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def build_listing_momentum_official_date_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_SCOPE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_SCOPE_PLAN_PATH) == PARENT_SCOPE_PLAN_FILE_SHA256,
            "parent scope plan file hash mismatch",
        )
    if PARENT_SCOPE_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_SCOPE_RECEIPT_PATH.read_text(encoding="utf-8"))
        _require(
            _sha256_file(PARENT_SCOPE_RECEIPT_PATH)
            == PARENT_SCOPE_RECEIPT_FILE_SHA256,
            "parent scope receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_SCOPE_RECEIPT_HASH,
            "parent scope receipt hash mismatch",
        )
        _require(
            receipt.get("status") == PARENT_SCOPE_RECEIPT_STATUS,
            "listing momentum scope not accepted",
        )
        _require(receipt.get("network_authorized") is False, "parent opened network")
        _require(
            receipt.get("ohlcv_collect_authorized") is False,
            "parent opened ohlcv",
        )
        _require(
            receipt.get("v6_postprocess_authorized") is False,
            "parent authorized v6 postprocess",
        )
        _require(
            receipt.get("first_days_sample_count") == 0,
            "parent first-days sample changed",
        )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "NO_DOCUMENTED_OFFICIAL_ANNOUNCEMENT_DATE_METHOD_AWAIT_ACCEPTANCE",
        "prepared_checkpoint": "RECORD_OFFICIAL_DATE_METHOD_UNAVAILABLE",
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
        "spot_v2_runtime_reuse": False,
        "listing_first_name_discovery_reopened": False,
        "closed_nine_reopened": False,
        "listing_event_closed_branch_reopened": False,
        "close_listing_momentum_authorized": False,
        "parent_retry_forbidden": True,
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_base_count": EXPECTED_TWO_VENUE_COUNT,
        "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
        "invented_ticker_count": 0,
        "invented_announcement_api_url_count": 0,
        "evidence_class": "OFFICIAL_ANNOUNCEMENT_DATE_METHOD_UNAVAILABLE",
        "identity_before_ohlcv_collect": True,
        "two_venue_official_identity_complete": False,
        "documented_unsigned_announcement_json_endpoint": False,
        "public_trading_start_fields_are_official_announcement": False,
        "first_days_sample_count": EXPECTED_AGE_BUCKETS["0_3d"],
        "official_announcement_row_count": 0,
        "goal": (
            "Record that Listing Momentum first-days cannot start: no "
            "documented official announcement/listing-date method exists "
            "in-repo. Public trading-start fields already in the frozen "
            "calendar are not official announcements and yield an empty "
            "first-days sample. Do not invent an announcement URL."
        ),
        "parent_listing_momentum_scope": {
            "plan_id": PARENT_SCOPE_PLAN_ID,
            "plan_path": str(PARENT_SCOPE_PLAN_PATH),
            "plan_hash": PARENT_SCOPE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_SCOPE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_SCOPE_RECEIPT_PATH),
            "receipt_hash": PARENT_SCOPE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_SCOPE_RECEIPT_FILE_SHA256,
            "status": PARENT_SCOPE_RECEIPT_STATUS,
        },
        "already_consumed_public_trading_start_fields": {
            "source_class": "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
            "mexc": {
                "url": MEXC_EXCHANGE_INFO_URL,
                "field": "firstOpenTime",
                "role": "CURRENT_SNAPSHOT_TRADING_START_NOT_ANNOUNCEMENT",
            },
            "gateio": {
                "url": GATE_CURRENCY_PAIRS_URL,
                "fields": ["buy_start", "sell_start"],
                "role": "CURRENT_SNAPSHOT_TRADING_START_NOT_ANNOUNCEMENT",
            },
            "calendar_announcement_at_utc_populated": False,
            "usable_as_official_announcement_date": False,
            "first_days_sample_count": EXPECTED_AGE_BUCKETS["0_3d"],
        },
        "exhausted_official_announcement_html": {
            "listing_first_name_discovery": PARENT_LISTING_FIRST_CLOSE_STATUS,
            "indexes": [
                {"venue": "mexc", "index_url": MEXC_INDEX_URL},
                {"venue": "gateio", "index_url": GATE_INDEX_URL},
            ],
            "article_url": (
                "https://www.mexc.com/announcements/article/"
                "first-in-market-17827791537583"
            ),
            "article_title_is_ticker": False,
            "selected_bases": [],
            "extracted_publish_timestamp": False,
            "retry_authorized": False,
        },
        "gate_unsigned_currency_json": {
            "url_prefix": GATE_CURRENCY_URL_PREFIX,
            "role": "IDENTITY_EVIDENCE_NOT_LISTING_DATE",
            "listing_or_announcement_timestamp_field": False,
        },
        "frozen_html_consumer_not_reused": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "reused": False,
        },
        "still_forbidden": [
            "INVENT_ANNOUNCEMENT_API_URL",
            "INVENT_OFFICIAL_ANNOUNCEMENT_DATES",
            "TREAT_CALENDAR_LISTED_AT_AS_OFFICIAL_ANNOUNCEMENT",
            "REOPEN_LISTING_FIRST_NAME_DISCOVERY",
            "RETRY_DISCOVERY_OR_ARTICLE",
            "REOPEN_CLOSED_NINE",
            "REUSE_SPOT_V2_HTML_CONSUMER",
            "OHLCV_COLLECT",
            "IDENTITY_VERDICT",
            "V6_POSTPROCESS_AS_LISTING_MOMENTUM",
            "BING_OR_SITEMAP",
            "REPLAY_OR_GRID",
            "EVALUATOR_OR_OOS",
            "PAPER_OR_LIVE",
            "20260815-V7",
        ],
        "checkpoint_options_not_authorized": [
            "CLOSE_LISTING_MOMENTUM_FIRST_DAYS_AS_INCOMPLETE",
            "USER_SUPPLIED_GROUNDED_OFFICIAL_ANNOUNCEMENT_DATE_METHOD",
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
            "close_listing_momentum_allowed": False,
            "invent_announcement_url_allowed": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_listing_momentum_official_date_plan(plan)
    return plan


def validate_listing_momentum_official_date_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "official date schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "official date plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status")
        == "NO_DOCUMENTED_OFFICIAL_ANNOUNCEMENT_DATE_METHOD_AWAIT_ACCEPTANCE",
        "status mismatch",
    )
    _require(
        plan.get("prepared_checkpoint")
        == "RECORD_OFFICIAL_DATE_METHOD_UNAVAILABLE",
        "checkpoint mismatch",
    )
    _require(plan.get("selected_base_count") == EXPECTED_TWO_VENUE_COUNT, "selected")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(
        plan.get("invented_announcement_api_url_count") == 0,
        "invented announcement url count",
    )
    _require(
        plan.get("documented_unsigned_announcement_json_endpoint") is False,
        "announcement json claimed documented",
    )
    _require(
        plan.get("public_trading_start_fields_are_official_announcement") is False,
        "trading-start treated as official announcement",
    )
    _require(plan.get("first_days_sample_count") == 0, "first-days sample")
    _require(plan.get("official_announcement_row_count") == 0, "official rows")
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
        plan.get("close_listing_momentum_authorized") is False,
        "close already authorized",
    )
    consumed = plan.get("already_consumed_public_trading_start_fields") or {}
    _require(
        consumed.get("usable_as_official_announcement_date") is False,
        "calendar listed_at treated official",
    )
    _require(
        consumed.get("mexc", {}).get("url") == MEXC_EXCHANGE_INFO_URL,
        "mexc trading-start url",
    )
    _require(
        consumed.get("gateio", {}).get("url") == GATE_CURRENCY_PAIRS_URL,
        "gate trading-start url",
    )
    html = plan.get("exhausted_official_announcement_html") or {}
    _require(html.get("retry_authorized") is False, "html retry authorized")
    _require(html.get("selected_bases") == [], "html selected bases invented")
    _require(html.get("extracted_publish_timestamp") is False, "article date claimed")
    gate_json = plan.get("gate_unsigned_currency_json") or {}
    _require(
        gate_json.get("listing_or_announcement_timestamp_field") is False,
        "gate currency json date claimed",
    )
    _require(gate_json.get("url_prefix") == GATE_CURRENCY_URL_PREFIX, "gate prefix")
    parent = plan.get("parent_listing_momentum_scope") or {}
    _require(parent.get("plan_hash") == PARENT_SCOPE_PLAN_HASH, "parent scope hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_SCOPE_PLAN_FILE_SHA256,
        "parent scope file hash",
    )
    _require(
        parent.get("receipt_hash") == PARENT_SCOPE_RECEIPT_HASH,
        "parent scope receipt",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    _require(
        auth.get("close_listing_momentum_allowed") is False,
        "close listing momentum allowed",
    )
    _require(
        auth.get("invent_announcement_url_allowed") is False,
        "invent url allowed",
    )
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    _require("keyword=" not in dumped, "ticker keyword search leaked")


def write_listing_momentum_official_date_plan(generated_at_utc: str) -> Path:
    plan = build_listing_momentum_official_date_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if DATE_PLAN_PATH.exists():
        _require(
            DATE_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {DATE_PLAN_PATH}",
        )
        return DATE_PLAN_PATH
    DATE_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATE_PLAN_PATH.write_text(payload, encoding="utf-8")
    return DATE_PLAN_PATH


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
    path = write_listing_momentum_official_date_plan(generated)
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
                "documented_unsigned_announcement_json_endpoint": False,
                "first_days_sample_count": 0,
                "network_authorized": False,
                "ohlcv_collect_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
