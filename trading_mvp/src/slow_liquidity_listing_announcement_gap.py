from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES
from slow_liquidity_listing_announcement_article import (
    ARTICLE_PLAN_PATH as PARENT_ARTICLE_PLAN_PATH,
    ARTICLE_URL,
    OUTPUT_ROOT as PARENT_ARTICLE_OUTPUT_ROOT,
    PLAN_ID as PARENT_ARTICLE_PLAN_ID,
)
from slow_liquidity_listing_announcement_discovery import (
    DISCOVERY_PLAN_PATH as PARENT_DISCOVERY_PLAN_PATH,
    PARENT_UNIVERSE_PLAN_FILE_SHA256,
    PARENT_UNIVERSE_PLAN_HASH,
    PLAN_ID as PARENT_DISCOVERY_PLAN_ID,
)
from slow_liquidity_listing_first_universe import (
    DISCOVERY_PLAN_PATH as PARENT_UNIVERSE_PLAN_PATH,
    PLAN_ID as PARENT_UNIVERSE_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_announcement_gap_planonly_v1"
PLAN_ID = "slow_liquidity_listing_announcement_gap_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
GAP_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-listing-announcement-gap-planonly-20260816.json"
)
PARENT_ARTICLE_PLAN_HASH = (
    "3b28ddd81b2feaa90ab2e4e35acf1a9292b8933084a82ab4d08b9842048f5f93"
)
PARENT_ARTICLE_PLAN_FILE_SHA256 = (
    "f44db661f812bf302e1cd249af78edb043a997e3cfccb21f681da4817ba93d4c"
)
PARENT_ARTICLE_RECORD_PATH = PARENT_ARTICLE_OUTPUT_ROOT / "article-record.json"
PARENT_ARTICLE_RECORD_SHA256 = (
    "76ea655e4079a296e1f84f4884fd5b8e725bf17bc742efa8afd0a503bb70aee9"
)
PARENT_ARTICLE_MANIFEST_PATH = PARENT_ARTICLE_OUTPUT_ROOT / "manifest.json"
PARENT_ARTICLE_MANIFEST_SHA256 = (
    "763b0f18d3d44342889f6192df9f2e56edaa9e8680712c864e6e950df9db03d5"
)
PARENT_ARTICLE_LAUNCH_PATH = (
    REPO_ROOT
    / "docs/agent-log/run-gates"
    / "slow_liquidity_listing_announcement_article_20260816.launch.json"
)
PARENT_ARTICLE_LAUNCH_FILE_SHA256 = (
    "cde7f463ab8c1dffe3577cca3b014d62de96059b7623c244b8f29a3a57f428a2"
)
PARENT_DISCOVERY_PLAN_HASH = (
    "1a7e4505e611b505e23c98cd89be015dc04d14b2da7cf3df12085a21db9ec8db"
)
PARENT_DISCOVERY_PLAN_FILE_SHA256 = (
    "4ed3124faf5abb26db95963aad316cccd98006945ae0bd5f1bd32ef07325bfa8"
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
    "Принимаю PlanOnly slow_liquidity_listing_announcement_gap_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: "
    "listing-first indexes/article не дали selected_bases, first-in-market "
    "и title не ticker, не invent tickers, не identity, не OHLCV, не reuse "
    "spot v2 consumer. Не retry discovery/article/r1-r4, не v7. Rescope "
    "listing index или новый universe только отдельной новой фразой. Без "
    "evaluator, OOS, returns/PnL, grid/retune, paper/live, private API, "
    "реальных денег, плеча или маржи."
)


class ListingAnnouncementGapError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingAnnouncementGapError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _load_frozen_article_record() -> dict[str, Any]:
    _require(PARENT_ARTICLE_RECORD_PATH.is_file(), "frozen article record missing")
    _require(
        _sha256_file(PARENT_ARTICLE_RECORD_PATH) == PARENT_ARTICLE_RECORD_SHA256,
        "frozen article record hash mismatch",
    )
    record = json.loads(PARENT_ARTICLE_RECORD_PATH.read_text(encoding="utf-8"))
    _require(record.get("official_source_url") == ARTICLE_URL, "article url mismatch")
    _require(record.get("extracted_bases") == [], "article extracted bases")
    _require(record.get("selected_bases") == [], "article selected bases")
    _require(record.get("listing_slug_match") is False, "article slug match")
    _require(record.get("identity_verdict") is False, "article identity verdict")
    return record


def build_listing_announcement_gap_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_ARTICLE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_ARTICLE_PLAN_PATH) == PARENT_ARTICLE_PLAN_FILE_SHA256,
            "parent article plan file hash mismatch",
        )
    if PARENT_ARTICLE_MANIFEST_PATH.is_file():
        _require(
            _sha256_file(PARENT_ARTICLE_MANIFEST_PATH) == PARENT_ARTICLE_MANIFEST_SHA256,
            "parent article manifest hash mismatch",
        )
    if PARENT_ARTICLE_LAUNCH_PATH.is_file():
        _require(
            _sha256_file(PARENT_ARTICLE_LAUNCH_PATH) == PARENT_ARTICLE_LAUNCH_FILE_SHA256,
            "parent article launch hash mismatch",
        )
    if PARENT_DISCOVERY_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_DISCOVERY_PLAN_PATH) == PARENT_DISCOVERY_PLAN_FILE_SHA256,
            "parent discovery plan file hash mismatch",
        )
    if PARENT_UNIVERSE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_UNIVERSE_PLAN_PATH) == PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "parent universe plan file hash mismatch",
        )
    record = _load_frozen_article_record()
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "LISTING_ANNOUNCEMENT_PATH_INCOMPLETE_AWAIT_RESCOPE_OR_CLOSE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_execution_authorized": False,
        "ohlcv_collect_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "spot_v2_runtime_reuse": False,
        "parent_retry_forbidden": True,
        "market": "SPOT_USDT",
        "evidence_class": "LISTING_ANNOUNCEMENT_GAP_RECORD",
        "selected_bases": [],
        "extracted_bases": [],
        "invented_ticker_count": 0,
        "excluded_bases": list(EXPECTED_BASES),
        "identity_before_ohlcv_collect": True,
        "listing_slug_match": False,
        "candidate_count": 1,
        "official_source_url": ARTICLE_URL,
        "observed_title": str(record.get("title") or ""),
        "observed_title_is_not_ticker": True,
        "goal": (
            "Record that official announcement indexes and the one frozen "
            "article did not yield selected_bases. Do not invent tickers, "
            "reuse the spot v2 consumer, or open identity/OHLCV."
        ),
        "parent_listing_first_universe": {
            "plan_id": PARENT_UNIVERSE_PLAN_ID,
            "plan_path": str(PARENT_UNIVERSE_PLAN_PATH),
            "plan_hash": PARENT_UNIVERSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "status": "ACCEPTED_LISTING_FIRST_UNIVERSE_NO_NETWORK",
        },
        "parent_listing_announcement_discovery": {
            "plan_id": PARENT_DISCOVERY_PLAN_ID,
            "plan_path": str(PARENT_DISCOVERY_PLAN_PATH),
            "plan_hash": PARENT_DISCOVERY_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_DISCOVERY_PLAN_FILE_SHA256,
            "status": "LISTING_ANNOUNCEMENT_DISCOVERY_INCOMPLETE",
            "retry_of_parent_forbidden": True,
        },
        "parent_listing_announcement_article": {
            "plan_id": PARENT_ARTICLE_PLAN_ID,
            "plan_path": str(PARENT_ARTICLE_PLAN_PATH),
            "plan_hash": PARENT_ARTICLE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_ARTICLE_PLAN_FILE_SHA256,
            "record_path": str(PARENT_ARTICLE_RECORD_PATH),
            "record_sha256": PARENT_ARTICLE_RECORD_SHA256,
            "manifest_path": str(PARENT_ARTICLE_MANIFEST_PATH),
            "manifest_sha256": PARENT_ARTICLE_MANIFEST_SHA256,
            "launch_path": str(PARENT_ARTICLE_LAUNCH_PATH),
            "launch_file_sha256": PARENT_ARTICLE_LAUNCH_FILE_SHA256,
            "status": "LISTING_ANNOUNCEMENT_ARTICLE_INCOMPLETE",
            "retry_of_parent_forbidden": True,
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
            "20260815-V7",
        ],
        "checkpoint_options_not_authorized": [
            "CLOSE_LISTING_FIRST_AS_UNREACHABLE",
            "NEW_LISTING_INDEX_METHOD",
            "NEW_UNIVERSE",
        ],
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_execution_allowed": False,
            "ohlcv_collect_allowed": False,
            "rescope_authorized": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_listing_announcement_gap_plan(plan)
    return plan


def validate_listing_announcement_gap_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "listing gap schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "listing gap plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status")
        == "LISTING_ANNOUNCEMENT_PATH_INCOMPLETE_AWAIT_RESCOPE_OR_CLOSE",
        "status mismatch",
    )
    _require(plan.get("selected_bases") == [], "tickers were invented")
    _require(plan.get("extracted_bases") == [], "extracted tickers in plan")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(plan.get("excluded_bases") == list(EXPECTED_BASES), "excluded bases")
    _require(plan.get("listing_slug_match") is False, "listing slug claimed")
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("replay_allowed") is False, "replay already allowed")
    _require(plan.get("spot_v2_runtime_reuse") is False, "spot v2 runtime reused")
    _require(
        plan.get("identity_execution_authorized") is False,
        "identity execution already authorized",
    )
    _require(
        plan.get("ohlcv_collect_authorized") is False,
        "ohlcv collect already authorized",
    )
    _require(plan.get("parent_retry_forbidden") is True, "retry not forbidden")
    _require(plan.get("official_source_url") == ARTICLE_URL, "article url")
    _require(plan.get("observed_title_is_not_ticker") is True, "title treated as ticker")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    _require("keyword=" not in dumped, "ticker keyword search leaked")
    parent = plan.get("parent_listing_announcement_article") or {}
    _require(parent.get("plan_hash") == PARENT_ARTICLE_PLAN_HASH, "parent article hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_ARTICLE_PLAN_FILE_SHA256,
        "parent article file hash",
    )
    _require(
        parent.get("record_sha256") == PARENT_ARTICLE_RECORD_SHA256,
        "parent article record hash",
    )
    _require(parent.get("retry_of_parent_forbidden") is True, "article retry")
    discovery = plan.get("parent_listing_announcement_discovery") or {}
    _require(
        discovery.get("plan_hash") == PARENT_DISCOVERY_PLAN_HASH,
        "parent discovery hash",
    )
    universe = plan.get("parent_listing_first_universe") or {}
    _require(universe.get("plan_hash") == PARENT_UNIVERSE_PLAN_HASH, "parent universe hash")
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("identity_execution_allowed") is False, "identity allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    _require(auth.get("rescope_authorized") is False, "rescope already authorized")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")
    _require(consumer.get("file_sha256") == SPOT_V2_RUNTIME_FILE_SHA256, "consumer hash")


def write_listing_announcement_gap_plan(generated_at_utc: str) -> Path:
    plan = build_listing_announcement_gap_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if GAP_PLAN_PATH.exists():
        _require(
            GAP_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {GAP_PLAN_PATH}",
        )
        return GAP_PLAN_PATH
    GAP_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GAP_PLAN_PATH.write_text(payload, encoding="utf-8")
    return GAP_PLAN_PATH


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
    path = write_listing_announcement_gap_plan(generated)
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
                "network_authorized": False,
                "selected_bases": [],
                "identity_verdict": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
