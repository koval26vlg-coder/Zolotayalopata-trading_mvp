from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES
from slow_liquidity_listing_announcement_discovery import (
    PARENT_UNIVERSE_PLAN_FILE_SHA256,
    PARENT_UNIVERSE_PLAN_HASH,
)
from slow_liquidity_listing_first_universe import (
    DISCOVERY_PLAN_PATH as PARENT_UNIVERSE_PLAN_PATH,
    PLAN_ID as PARENT_UNIVERSE_PLAN_ID,
)
from slow_liquidity_listing_index_method import (
    METHOD_PLAN_PATH as PARENT_METHOD_PLAN_PATH,
    PLAN_ID as PARENT_METHOD_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_first_close_planonly_v1"
PLAN_ID = "slow_liquidity_listing_first_close_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSE_PLAN_PATH = (
    REPO_ROOT / "docs/plans/slow-liquidity-listing-first-close-planonly-20260816.json"
)
PARENT_METHOD_PLAN_HASH = (
    "ab38823d404fa546608ed8c42db2b716194fbccacefa16e514bc917c83700d55"
)
PARENT_METHOD_PLAN_FILE_SHA256 = (
    "e825860938d9eaf96c9b7432375debc95787f775fac3c18431424fa30becc896"
)
PARENT_METHOD_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-index-method-unavailable-approval.json"
)
PARENT_METHOD_RECEIPT_HASH = (
    "d246caa0effec75143474734ee60526b951d10ed60bcafbe8b47fb2fe2f81d55"
)
PARENT_METHOD_RECEIPT_FILE_SHA256 = (
    "7c277a39e25955865c5b706f4e5ed4ea28365294c08353c3270d0b4fd37303de"
)
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
EXPECTED_APPROVAL_TEXT = (
    "CLOSE_LISTING_FIRST_AS_UNREACHABLE — принимаю PlanOnly "
    "slow_liquidity_listing_first_close_20260816 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: закрыть listing-first name "
    "discovery как unreachable, selected_bases=[], не invent tickers, не "
    "identity, не OHLCV, не reuse spot v2 consumer, не новый universe, не "
    "retry discovery/article/r1-r4, не v7. Без evaluator, OOS, returns/PnL, "
    "grid/retune, paper/live, private API, реальных денег, плеча или маржи."
)


class ListingFirstCloseError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingFirstCloseError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def build_listing_first_close_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_METHOD_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_METHOD_PLAN_PATH) == PARENT_METHOD_PLAN_FILE_SHA256,
            "parent method plan file hash mismatch",
        )
    if PARENT_METHOD_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_METHOD_RECEIPT_PATH.read_text(encoding="utf-8"))
        _require(
            _sha256_file(PARENT_METHOD_RECEIPT_PATH)
            == PARENT_METHOD_RECEIPT_FILE_SHA256,
            "parent method receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_METHOD_RECEIPT_HASH,
            "parent method receipt hash mismatch",
        )
        _require(
            receipt.get("status")
            == "ACCEPTED_LISTING_INDEX_METHOD_UNAVAILABLE_NO_RESCOPE",
            "parent method not accepted",
        )
        _require(
            receipt.get("close_listing_first_authorized") is False,
            "parent method already closed listing-first",
        )
    if PARENT_UNIVERSE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_UNIVERSE_PLAN_PATH) == PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "parent universe plan file hash mismatch",
        )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE",
        "prepared_checkpoint": "CLOSE_LISTING_FIRST_AS_UNREACHABLE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "listing_first_name_discovery_unreachable": True,
        "selected_bases": [],
        "invented_ticker_count": 0,
        "excluded_bases": list(EXPECTED_BASES),
        "identity_before_ohlcv_collect": True,
        "identity_execution_authorized": False,
        "ohlcv_collect_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "spot_v2_runtime_reuse": False,
        "new_universe_authorized": False,
        "close_listing_first_authorized": False,
        "parent_retry_forbidden": True,
        "market": "SPOT_USDT",
        "evidence_class": "LISTING_FIRST_CLOSE_PACKET",
        "goal": (
            "Prepare close of listing-first name discovery because official "
            "indexes and the one article did not yield selected_bases, and "
            "no second grounded listing-index URL exists. Do not accept "
            "close, invent tickers, or open a new universe here."
        ),
        "parent_listing_first_universe": {
            "plan_id": PARENT_UNIVERSE_PLAN_ID,
            "plan_path": str(PARENT_UNIVERSE_PLAN_PATH),
            "plan_hash": PARENT_UNIVERSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "status": "ACCEPTED_LISTING_FIRST_UNIVERSE_NO_NETWORK",
            "close_authorized": False,
        },
        "parent_listing_index_method": {
            "plan_id": PARENT_METHOD_PLAN_ID,
            "plan_path": str(PARENT_METHOD_PLAN_PATH),
            "plan_hash": PARENT_METHOD_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_METHOD_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_METHOD_RECEIPT_PATH),
            "receipt_hash": PARENT_METHOD_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_METHOD_RECEIPT_FILE_SHA256,
            "status": "ACCEPTED_LISTING_INDEX_METHOD_UNAVAILABLE_NO_RESCOPE",
        },
        "frozen_html_consumer_not_reused": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "reused": False,
        },
        "unauthorized_next_actions": [
            "INVENT_TICKER",
            "IDENTITY_EXECUTION",
            "OHLCV_COLLECT",
            "REUSE_SPOT_V2_CONSUMER",
            "RETRY_DISCOVERY",
            "RETRY_ARTICLE",
            "RETRY_R1_R4",
            "NEW_UNIVERSE",
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
            "close_listing_first_allowed": False,
            "new_universe_allowed": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_listing_first_close_plan(plan)
    return plan


def validate_listing_first_close_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "listing-first close schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "listing-first close plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE",
        "status mismatch",
    )
    _require(
        plan.get("prepared_checkpoint") == "CLOSE_LISTING_FIRST_AS_UNREACHABLE",
        "checkpoint mismatch",
    )
    _require(plan.get("selected_bases") == [], "tickers were invented")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(plan.get("excluded_bases") == list(EXPECTED_BASES), "excluded bases")
    _require(
        plan.get("listing_first_name_discovery_unreachable") is True,
        "name discovery still reachable",
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
    _require(plan.get("new_universe_authorized") is False, "new universe already authorized")
    _require(
        plan.get("close_listing_first_authorized") is False,
        "close already authorized",
    )
    _require(plan.get("parent_retry_forbidden") is True, "retry not forbidden")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    _require("keyword=" not in dumped, "ticker keyword search leaked")
    parent = plan.get("parent_listing_index_method") or {}
    _require(parent.get("plan_hash") == PARENT_METHOD_PLAN_HASH, "parent method hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_METHOD_PLAN_FILE_SHA256,
        "parent method file hash",
    )
    universe = plan.get("parent_listing_first_universe") or {}
    _require(universe.get("plan_hash") == PARENT_UNIVERSE_PLAN_HASH, "parent universe hash")
    _require(universe.get("close_authorized") is False, "universe already closed")
    auth = plan.get("authorization_now") or {}
    _require(auth.get("close_listing_first_allowed") is False, "close allowed now")
    _require(auth.get("new_universe_allowed") is False, "universe allowed now")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")


def write_listing_first_close_plan(generated_at_utc: str) -> Path:
    plan = build_listing_first_close_plan(generated_at_utc)
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
    path = write_listing_first_close_plan(generated)
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
                "close_listing_first_authorized": False,
                "new_universe_authorized": False,
                "selected_bases": [],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
