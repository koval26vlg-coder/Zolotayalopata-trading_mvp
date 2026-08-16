from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_calendar_first_universe import (
    CALENDAR_FILE_SHA256,
    CALENDAR_PATH,
    UNIVERSE_PLAN_PATH as PARENT_UNIVERSE_PLAN_PATH,
    PLAN_ID as PARENT_UNIVERSE_PLAN_ID,
    materialize_two_venue_bases,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    canonical_hash,
    canonical_json_bytes,
)
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_calendar_name_materialization_planonly_v1"
PLAN_ID = "slow_liquidity_calendar_name_materialization_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
MATERIALIZATION_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-calendar-name-materialization-planonly-20260816.json"
)
PARENT_UNIVERSE_PLAN_HASH = (
    "6608a2b2f13de4f33db89d13813cd9563b191f20a04fbd18604d37d8e4816c77"
)
PARENT_UNIVERSE_PLAN_FILE_SHA256 = (
    "b848557a9fafdf65415625aff6ce641afb594f9eea57d71ae2643331108eed2a"
)
PARENT_UNIVERSE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-calendar-first-universe-approval.json"
)
PARENT_UNIVERSE_RECEIPT_HASH = (
    "5c016b871438ddb8eadf1b63d769ecab57f327812a4149e4d90652721964c7ea"
)
PARENT_UNIVERSE_RECEIPT_FILE_SHA256 = (
    "2d61165bae6e823ee9b71c675061660ed4f741daa4adb0d2c2fde097bcab4fef"
)
EXPECTED_SELECTED_COUNT = 407
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
    "slow_liquidity_calendar_name_materialization_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: "
    "материализовать имена по accepted calendar-first method, список из "
    "frozen local calendar, не invent, exclude closed 9. Не identity, не "
    "OHLCV, не reopen listing-first, не reuse spot v2 consumer, не replay, "
    "не v7. Без evaluator, OOS, returns/PnL, grid/retune, paper/live, "
    "private API, реальных денег, плеча или маржи."
)


class CalendarNameMaterializationError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CalendarNameMaterializationError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def build_calendar_name_materialization_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_UNIVERSE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_UNIVERSE_PLAN_PATH) == PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "parent universe plan file hash mismatch",
        )
    if PARENT_UNIVERSE_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_UNIVERSE_RECEIPT_PATH.read_text(encoding="utf-8"))
        _require(
            _sha256_file(PARENT_UNIVERSE_RECEIPT_PATH)
            == PARENT_UNIVERSE_RECEIPT_FILE_SHA256,
            "parent universe receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_UNIVERSE_RECEIPT_HASH,
            "parent universe receipt hash mismatch",
        )
        _require(
            receipt.get("status") == "ACCEPTED_CALENDAR_FIRST_UNIVERSE_NO_NETWORK",
            "parent universe not accepted",
        )
        _require(receipt.get("selected_bases") == [], "parent already listed names")
    _require(CALENDAR_PATH.is_file(), "frozen listing calendar missing")
    _require(
        _sha256_file(CALENDAR_PATH) == CALENDAR_FILE_SHA256,
        "frozen listing calendar hash mismatch",
    )
    selected = list(materialize_two_venue_bases(CALENDAR_PATH))
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "selected count")
    selected_sha256 = hashlib.sha256(canonical_json_bytes(selected)).hexdigest()
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_NAME_MATERIALIZATION_ACCEPTANCE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "universe_selection": "FROZEN_LOCAL_TWO_VENUE_LISTING_CALENDAR",
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_bases": selected,
        "selected_base_count": len(selected),
        "selected_bases_sha256": selected_sha256,
        "invented_ticker_count": 0,
        "names_materialized": True,
        "identity_before_ohlcv_collect": True,
        "listing_first_name_discovery_reopened": False,
        "spot_v2_runtime_reuse": False,
        "identity_execution_authorized": False,
        "ohlcv_collect_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "calendar_path": str(CALENDAR_PATH),
        "calendar_file_sha256": CALENDAR_FILE_SHA256,
        "source_class": "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
        "goal": (
            "Materialize selected_bases from the accepted frozen local "
            "two-venue listing calendar method. This is a calendar extract, "
            "not an invented ticker list. Do not open identity or OHLCV."
        ),
        "parent_calendar_first_universe": {
            "plan_id": PARENT_UNIVERSE_PLAN_ID,
            "plan_path": str(PARENT_UNIVERSE_PLAN_PATH),
            "plan_hash": PARENT_UNIVERSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_UNIVERSE_RECEIPT_PATH),
            "receipt_hash": PARENT_UNIVERSE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_UNIVERSE_RECEIPT_FILE_SHA256,
            "status": "ACCEPTED_CALENDAR_FIRST_UNIVERSE_NO_NETWORK",
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
            "replay_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_calendar_name_materialization_plan(plan)
    return plan


def validate_calendar_name_materialization_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "name materialization schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "name materialization plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    selected = list(plan.get("selected_bases") or [])
    closed = set(EXPECTED_BASES)
    overlap = [base for base in selected if base in closed]
    _require(not overlap, f"closed base selected: {overlap}")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "selected count")
    _require(plan.get("selected_base_count") == EXPECTED_SELECTED_COUNT, "count field")
    _require(selected == sorted(selected), "selected bases unsorted")
    _require(
        plan.get("selected_bases_sha256") == hashlib.sha256(canonical_json_bytes(selected)).hexdigest(),
        "selected bases hash",
    )
    _require(plan.get("names_materialized") is True, "names not marked materialized")
    _require(plan.get("excluded_bases") == list(EXPECTED_BASES), "excluded bases")
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
    if CALENDAR_PATH.is_file() and _sha256_file(CALENDAR_PATH) == CALENDAR_FILE_SHA256:
        expected = list(materialize_two_venue_bases(CALENDAR_PATH))
        _require(selected == expected, "selected bases drifted from calendar")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_calendar_first_universe") or {}
    _require(parent.get("plan_hash") == PARENT_UNIVERSE_PLAN_HASH, "parent universe hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_UNIVERSE_PLAN_FILE_SHA256,
        "parent universe file hash",
    )
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")


def write_calendar_name_materialization_plan(generated_at_utc: str) -> Path:
    plan = build_calendar_name_materialization_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if MATERIALIZATION_PLAN_PATH.exists():
        _require(
            MATERIALIZATION_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {MATERIALIZATION_PLAN_PATH}",
        )
        return MATERIALIZATION_PLAN_PATH
    MATERIALIZATION_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATERIALIZATION_PLAN_PATH.write_text(payload, encoding="utf-8")
    return MATERIALIZATION_PLAN_PATH


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
    path = write_calendar_name_materialization_plan(generated)
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
                "selected_base_count": plan["selected_base_count"],
                "selected_bases_sha256": plan["selected_bases_sha256"],
                "invented_ticker_count": 0,
                "identity_execution_authorized": False,
                "ohlcv_collect_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
