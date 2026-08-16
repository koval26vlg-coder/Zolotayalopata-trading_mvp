from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_listing_first_close import (
    CLOSE_PLAN_PATH as PARENT_CLOSE_PLAN_PATH,
    PLAN_ID as PARENT_CLOSE_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_calendar_first_universe_planonly_v1"
PLAN_ID = "slow_liquidity_calendar_first_universe_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-calendar-first-universe-planonly-20260816.json"
)
PARENT_CLOSE_PLAN_HASH = (
    "c0830512db1fef2e012262bcd6f7ad624437062a11712b09f4718ac0b261fc0f"
)
PARENT_CLOSE_PLAN_FILE_SHA256 = (
    "d1ce9ceadfe4803de5719c666e3a55c5e998f535f9083e00e64426a34c13bba2"
)
PARENT_CLOSE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-first-close-approval.json"
)
PARENT_CLOSE_RECEIPT_HASH = (
    "b68971465243bcb070969f2773eb792a9722e9fa88d44278e1eb75d01aea582c"
)
PARENT_CLOSE_RECEIPT_FILE_SHA256 = (
    "8f388635d3eea8f531dbb6cfa8ba9a4351456686ec360233b0a33883bc81662b"
)
CALENDAR_PATH = (
    REPO_ROOT / "exports/trading-mvp/listings/non_binance_listing_events.csv"
)
CALENDAR_FILE_SHA256 = (
    "d01f86646eaebfd4df5a738a754f021bb3a7b0dcd192cfa104057eb29a3f4abb"
)
CALENDAR_SUMMARY_PATH = (
    REPO_ROOT / "exports/trading-mvp/listings/non_binance_listing_events.summary.json"
)
CALENDAR_SUMMARY_FILE_SHA256 = (
    "84a626e572b5cdee49e3e9ec01d4506b4d8f950eaa7eef72e689beba7b6f8a8d"
)
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
USER_UNIVERSE_TEXT = (
    "новый universe, и для него нужен метод отбора, не список тикеров."
)
EXPECTED_APPROVAL_TEXT = (
    "Принимаю PlanOnly slow_liquidity_calendar_first_universe_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: новый "
    "universe — frozen local two-venue listing calendar method, не список "
    "тикеров, exclude closed 9, identity до OHLCV collect. Не reopen "
    "listing-first name discovery, не invent tickers, не reuse spot v2 "
    "consumer, не replay, не v7. Без evaluator, OOS, returns/PnL, "
    "grid/retune, paper/live, private API, реальных денег, плеча или маржи."
)


class CalendarFirstUniverseError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CalendarFirstUniverseError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def materialize_two_venue_bases(path: Path) -> tuple[str, ...]:
    by_venue: dict[str, set[str]] = {venue: set() for venue in EXPECTED_VENUES}
    closed = set(EXPECTED_BASES)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            venue = str(row.get("exchange") or "").strip().lower()
            if venue == "gate":
                venue = "gateio"
            if venue not in by_venue:
                continue
            if str(row.get("quote") or "").strip().upper() != "USDT":
                continue
            if str(row.get("is_delisted") or "").strip().lower() == "true":
                continue
            base = str(row.get("base") or "").strip().upper()
            if not base or base in closed:
                continue
            by_venue[venue].add(base)
    return tuple(sorted(by_venue["mexc"] & by_venue["gateio"]))


def _two_venue_candidate_count(path: Path) -> int:
    return len(materialize_two_venue_bases(path))


def build_calendar_first_universe_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_CLOSE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_CLOSE_PLAN_PATH) == PARENT_CLOSE_PLAN_FILE_SHA256,
            "parent close plan file hash mismatch",
        )
    if PARENT_CLOSE_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_CLOSE_RECEIPT_PATH.read_text(encoding="utf-8"))
        _require(
            _sha256_file(PARENT_CLOSE_RECEIPT_PATH) == PARENT_CLOSE_RECEIPT_FILE_SHA256,
            "parent close receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_CLOSE_RECEIPT_HASH,
            "parent close receipt hash mismatch",
        )
        _require(
            receipt.get("status") == "LISTING_FIRST_CLOSED_AS_UNREACHABLE",
            "listing-first name discovery not closed",
        )
    _require(CALENDAR_PATH.is_file(), "frozen listing calendar missing")
    _require(
        _sha256_file(CALENDAR_PATH) == CALENDAR_FILE_SHA256,
        "frozen listing calendar hash mismatch",
    )
    if CALENDAR_SUMMARY_PATH.is_file():
        _require(
            _sha256_file(CALENDAR_SUMMARY_PATH) == CALENDAR_SUMMARY_FILE_SHA256,
            "frozen listing calendar summary hash mismatch",
        )
    two_venue_count = _two_venue_candidate_count(CALENDAR_PATH)
    _require(two_venue_count > 0, "two-venue calendar intersection empty")
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_UNIVERSE_ACCEPTANCE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "universe_selection": "FROZEN_LOCAL_TWO_VENUE_LISTING_CALENDAR",
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_bases": [],
        "invented_ticker_count": 0,
        "two_venue_candidate_count": two_venue_count,
        "identity_before_ohlcv_collect": True,
        "listing_first_name_discovery_reopened": False,
        "spot_v2_runtime_reuse": False,
        "identity_execution_authorized": False,
        "ohlcv_collect_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "user_universe_text": USER_UNIVERSE_TEXT,
        "selection_method": {
            "id": "two_venue_usdt_spot_from_frozen_local_listing_calendar",
            "calendar_path": str(CALENDAR_PATH),
            "calendar_file_sha256": CALENDAR_FILE_SHA256,
            "calendar_summary_path": str(CALENDAR_SUMMARY_PATH),
            "calendar_summary_file_sha256": CALENDAR_SUMMARY_FILE_SHA256,
            "source_class": "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
            "rules": [
                "venue in mexc and gateio",
                "quote USDT",
                "not delisted in frozen calendar",
                "exclude closed 9 bases",
                "keep selected_bases empty until a later apply phrase",
            ],
            "names_materialized": False,
        },
        "goal": (
            "Define a new two-venue spot universe by method: intersection "
            "of the frozen local listing calendar. Do not invent a ticker "
            "list, reopen listing-first name discovery, or open identity/"
            "OHLCV here."
        ),
        "parent_listing_first_close": {
            "plan_id": PARENT_CLOSE_PLAN_ID,
            "plan_path": str(PARENT_CLOSE_PLAN_PATH),
            "plan_hash": PARENT_CLOSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_CLOSE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_CLOSE_RECEIPT_PATH),
            "receipt_hash": PARENT_CLOSE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_CLOSE_RECEIPT_FILE_SHA256,
            "status": "LISTING_FIRST_CLOSED_AS_UNREACHABLE",
        },
        "frozen_html_consumer_not_reused": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "reused": False,
        },
        "still_forbidden": [
            "INVENT_TICKERS",
            "REOPEN_LISTING_FIRST_NAME_DISCOVERY",
            "REUSE_CLOSED_NINE_BASES",
            "REUSE_SPOT_V2_HTML_CONSUMER",
            "IDENTITY_EXECUTION",
            "OHLCV_COLLECT",
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
            "ohlcv_collect_allowed": False,
            "name_materialization_allowed": False,
            "replay_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_calendar_first_universe_plan(plan)
    return plan


def validate_calendar_first_universe_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "calendar-first schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "calendar-first plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("universe_selection") == "FROZEN_LOCAL_TWO_VENUE_LISTING_CALENDAR",
        "universe selection mismatch",
    )
    _require(plan.get("selected_bases") == [], "tickers were invented")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(plan.get("excluded_bases") == list(EXPECTED_BASES), "excluded bases")
    _require(int(plan.get("two_venue_candidate_count") or 0) > 0, "candidate count")
    _require(plan.get("identity_before_ohlcv_collect") is True, "identity-first required")
    _require(
        plan.get("listing_first_name_discovery_reopened") is False,
        "listing-first reopened",
    )
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("spot_v2_runtime_reuse") is False, "spot v2 runtime reused")
    _require(
        plan.get("identity_execution_authorized") is False,
        "identity execution already authorized",
    )
    _require(
        plan.get("ohlcv_collect_authorized") is False,
        "ohlcv collect already authorized",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    method = plan.get("selection_method") or {}
    _require(method.get("names_materialized") is False, "names already materialized")
    _require(
        method.get("calendar_file_sha256") == CALENDAR_FILE_SHA256,
        "calendar hash",
    )
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_listing_first_close") or {}
    _require(parent.get("plan_hash") == PARENT_CLOSE_PLAN_HASH, "parent close hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_CLOSE_PLAN_FILE_SHA256,
        "parent close file hash",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("name_materialization_allowed") is False, "names allowed now")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")


def write_calendar_first_universe_plan(generated_at_utc: str) -> Path:
    plan = build_calendar_first_universe_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if UNIVERSE_PLAN_PATH.exists():
        _require(
            UNIVERSE_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {UNIVERSE_PLAN_PATH}",
        )
        return UNIVERSE_PLAN_PATH
    UNIVERSE_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE_PLAN_PATH.write_text(payload, encoding="utf-8")
    return UNIVERSE_PLAN_PATH


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
    path = write_calendar_first_universe_plan(generated)
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
                "selected_bases": [],
                "two_venue_candidate_count": plan["two_venue_candidate_count"],
                "network_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
