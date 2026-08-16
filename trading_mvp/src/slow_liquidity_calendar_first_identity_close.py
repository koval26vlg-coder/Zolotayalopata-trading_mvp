from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_calendar_first_identity_gap import (
    EXPECTED_SELECTED_COUNT,
    EXPECTED_UNIQUE_GATE_COUNT,
    EXPECTED_UNRESOLVED_COUNT,
    GAP_PLAN_PATH as PARENT_GAP_PLAN_PATH,
    PARENT_CURRENCY_JSON_RECORDS_SHA256,
    PARENT_SELECTED_BASES_SHA256,
    PLAN_ID as PARENT_GAP_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_calendar_first_identity_close_planonly_v1"
PLAN_ID = "slow_liquidity_calendar_first_identity_close_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSE_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-calendar-first-identity-close-planonly-20260816.json"
)
PARENT_GAP_PLAN_HASH = (
    "3593627c4be1f6a84ecf45d20adff6af9aea0945a986728d1bcd99d608b32f6d"
)
PARENT_GAP_PLAN_FILE_SHA256 = (
    "80e02872e313a632c85f6b1dc11a9cc9bf6af56a8d3e5ddfbe8b7643070bcd3d"
)
PARENT_GAP_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-calendar-first-identity-gap-approval.json"
)
PARENT_GAP_RECEIPT_HASH = (
    "8b91ad1e1ce967be6cf2b4b5e9008e3bea4c1bd47d1c6ad618d9c1e634270fda"
)
PARENT_GAP_RECEIPT_FILE_SHA256 = (
    "2aad825a6a0c0e00ffdf5d2906a5bd6285c4dc774c032900f840393463993fe1"
)
PARENT_GAP_RECEIPT_STATUS = "ACCEPTED_CALENDAR_FIRST_IDENTITY_GAP_NO_NETWORK"
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
EXPECTED_APPROVAL_TEXT = (
    "CLOSE_CALENDAR_FIRST_TWO_VENUE_IDENTITY_AS_INCOMPLETE — принимаю "
    "PlanOnly slow_liquidity_calendar_first_identity_close_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: закрыть "
    "two-venue official identity как incomplete, Gate JSON 407/244/163, "
    "MEXC unsigned JSON нет, не invent URL, не identity verdict, не OHLCV, "
    "не retry currency JSON, не reopen listing-first, не reuse spot v2 "
    "consumer, не replay, не v7. Без evaluator, OOS, returns/PnL, "
    "grid/retune, paper/live, private API, реальных денег, плеча или маржи."
)


class CalendarFirstIdentityCloseError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CalendarFirstIdentityCloseError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def build_calendar_first_identity_close_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_GAP_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_GAP_PLAN_PATH) == PARENT_GAP_PLAN_FILE_SHA256,
            "parent gap plan file hash mismatch",
        )
    if PARENT_GAP_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_GAP_RECEIPT_PATH.read_text(encoding="utf-8"))
        _require(
            _sha256_file(PARENT_GAP_RECEIPT_PATH) == PARENT_GAP_RECEIPT_FILE_SHA256,
            "parent gap receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_GAP_RECEIPT_HASH,
            "parent gap receipt hash mismatch",
        )
        _require(
            receipt.get("status") == PARENT_GAP_RECEIPT_STATUS,
            "parent gap not accepted",
        )
        _require(receipt.get("network_authorized") is False, "parent opened network")
        _require(receipt.get("identity_verdict") is False, "parent issued verdict")
        _require(
            receipt.get("ohlcv_collect_authorized") is False,
            "parent opened ohlcv",
        )
        _require(
            receipt.get("parent_retry_authorized") is False,
            "parent authorized retry",
        )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE",
        "prepared_checkpoint": "CLOSE_TWO_VENUE_OFFICIAL_IDENTITY_AS_INCOMPLETE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_verdict_allowed": False,
        "identity_execution_authorized": False,
        "ohlcv_collect_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "spot_v2_runtime_reuse": False,
        "listing_first_name_discovery_reopened": False,
        "parent_retry_forbidden": True,
        "close_two_venue_identity_authorized": False,
        "documented_second_venue_method_unavailable": True,
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_base_count": EXPECTED_SELECTED_COUNT,
        "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
        "unique_gate_evm_base_count": EXPECTED_UNIQUE_GATE_COUNT,
        "unresolved_count": EXPECTED_UNRESOLVED_COUNT,
        "two_venue_verified_base_count": 0,
        "records_sha256": PARENT_CURRENCY_JSON_RECORDS_SHA256,
        "invented_ticker_count": 0,
        "evidence_class": "TWO_VENUE_OFFICIAL_IDENTITY_CLOSE_PACKET",
        "identity_before_ohlcv_collect": True,
        "two_venue_official_identity_complete": False,
        "goal": (
            "Prepare close of two-venue official identity as incomplete: "
            "Gate unsigned currency JSON ran 407/244/163, and no documented "
            "unsigned MEXC contract JSON exists in-repo. This is not an "
            "identity verdict and not OHLCV collect."
        ),
        "parent_calendar_first_identity_gap": {
            "plan_id": PARENT_GAP_PLAN_ID,
            "plan_path": str(PARENT_GAP_PLAN_PATH),
            "plan_hash": PARENT_GAP_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_GAP_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_GAP_RECEIPT_PATH),
            "receipt_hash": PARENT_GAP_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_GAP_RECEIPT_FILE_SHA256,
            "status": PARENT_GAP_RECEIPT_STATUS,
        },
        "mexc_public_contract_json": {
            "documented_unsigned_endpoint": False,
            "capital_config_getall_requires_api_key": True,
            "invented_undocumented_endpoint_forbidden": True,
        },
        "frozen_html_consumer_not_reused": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "reused": False,
        },
        "still_forbidden": [
            "RETRY_CURRENCY_JSON",
            "INVENT_OFFICIAL_PAGE_URLS",
            "INVENT_MEXC_UNSIGNED_JSON",
            "REOPEN_LISTING_FIRST_NAME_DISCOVERY",
            "REUSE_SPOT_V2_HTML_CONSUMER",
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
            "retry_parent_allowed": False,
            "close_two_venue_identity_allowed": False,
            "replay_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_calendar_first_identity_close_plan(plan)
    return plan


def validate_calendar_first_identity_close_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "calendar identity close schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "calendar identity close plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE",
        "status mismatch",
    )
    _require(
        plan.get("prepared_checkpoint")
        == "CLOSE_TWO_VENUE_OFFICIAL_IDENTITY_AS_INCOMPLETE",
        "checkpoint mismatch",
    )
    _require(plan.get("selected_base_count") == EXPECTED_SELECTED_COUNT, "selected count")
    _require(
        plan.get("unique_gate_evm_base_count") == EXPECTED_UNIQUE_GATE_COUNT,
        "unique count",
    )
    _require(plan.get("unresolved_count") == EXPECTED_UNRESOLVED_COUNT, "unresolved")
    _require(plan.get("two_venue_verified_base_count") == 0, "two-venue claimed")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(
        plan.get("selected_bases_sha256") == PARENT_SELECTED_BASES_SHA256,
        "selected bases hash",
    )
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("spot_v2_runtime_reuse") is False, "spot v2 runtime reused")
    _require(
        plan.get("identity_verdict_allowed") is False,
        "identity verdict already allowed",
    )
    _require(
        plan.get("ohlcv_collect_authorized") is False,
        "ohlcv collect already authorized",
    )
    _require(plan.get("parent_retry_forbidden") is True, "retry not forbidden")
    _require(
        plan.get("listing_first_name_discovery_reopened") is False,
        "listing-first reopened",
    )
    _require(
        plan.get("close_two_venue_identity_authorized") is False,
        "close already authorized",
    )
    _require(
        plan.get("documented_second_venue_method_unavailable") is True,
        "second-venue method claimed available",
    )
    _require(
        plan.get("two_venue_official_identity_complete") is False,
        "two-venue identity claimed complete",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    mexc = plan.get("mexc_public_contract_json") or {}
    _require(mexc.get("documented_unsigned_endpoint") is False, "mexc unsigned claimed")
    parent = plan.get("parent_calendar_first_identity_gap") or {}
    _require(parent.get("plan_hash") == PARENT_GAP_PLAN_HASH, "parent gap hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_GAP_PLAN_FILE_SHA256,
        "parent gap file hash",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    _require(auth.get("close_two_venue_identity_allowed") is False, "close allowed")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")


def write_calendar_first_identity_close_plan(generated_at_utc: str) -> Path:
    plan = build_calendar_first_identity_close_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if CLOSE_PLAN_PATH.exists():
        _require(
            CLOSE_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {CLOSE_PLAN_PATH}",
        )
        return CLOSE_PLAN_PATH
    CLOSE_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLOSE_PLAN_PATH.write_text(payload, encoding="utf-8")
    return CLOSE_PLAN_PATH


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
    path = write_calendar_first_identity_close_plan(generated)
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
                "close_two_venue_identity_authorized": False,
                "documented_second_venue_method_unavailable": True,
                "network_authorized": False,
                "identity_verdict_allowed": False,
                "ohlcv_collect_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
