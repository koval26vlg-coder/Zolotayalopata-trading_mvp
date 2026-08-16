from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from slow_liquidity_official_identity_proposal import EXPECTED_BASES
from slow_liquidity_official_identity_verification import (
    FetchedResponse,
    IdentityVerificationError,
)
from slow_liquidity_listing_announcement_discovery import (
    DISCOVERY_PLAN_PATH as PARENT_DISCOVERY_PLAN_PATH,
    PLAN_ID as PARENT_DISCOVERY_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    canonical_hash,
    fetch_public_discovery_response,
    normalize_approval_text,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_announcement_article_planonly_v1"
PLAN_ID = "slow_liquidity_listing_announcement_article_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTICLE_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-listing-announcement-article-planonly-20260816.json"
)
PARENT_DISCOVERY_PLAN_HASH = (
    "1a7e4505e611b505e23c98cd89be015dc04d14b2da7cf3df12085a21db9ec8db"
)
PARENT_DISCOVERY_PLAN_FILE_SHA256 = (
    "4ed3124faf5abb26db95963aad316cccd98006945ae0bd5f1bd32ef07325bfa8"
)
PARENT_DISCOVERY_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-announcement-discovery-approval.json"
)
PARENT_DISCOVERY_RECEIPT_FILE_SHA256 = (
    "9c8deea9aac0bc37eb99ac178b8daf575a8850181adbb51bd3925b63009ba251"
)
PARENT_CANDIDATES_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp"
    r"\slow-liquidity-listing-announcement-discovery"
    r"\slow_liquidity_listing_announcement_discovery_20260816"
    r"\listing-announcement-candidates.json"
)
PARENT_CANDIDATES_SHA256 = (
    "63782d79b5bbb259dda4832e3dd4692930aa30bbd336d9e435cc43f63078186d"
)
PARENT_MANIFEST_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp"
    r"\slow-liquidity-listing-announcement-discovery"
    r"\slow_liquidity_listing_announcement_discovery_20260816"
    r"\manifest.json"
)
PARENT_MANIFEST_SHA256 = (
    "47f1d91d8cb905d8c0f0b9a5b02132ddd7ab15a6b575219795008ebf60b2100b"
)
ARTICLE_URL = (
    "https://www.mexc.com/announcements/article/first-in-market-17827791537583"
)
ARTICLE_HOST = "www.mexc.com"
ARTICLE_PREFIX = "/announcements/article/"
LISTING_SLUG_MARKERS = ("initial-listing", "will-list")
WILL_LIST_BASE_RE = re.compile(
    r"will-list-[a-z0-9]+-([a-z0-9]{2,10})-",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp"
    r"\slow-liquidity-listing-announcement-article"
    r"\slow_liquidity_listing_announcement_article_20260816"
)
EXPECTED_APPROVAL_TEXT = (
    "Разрешаю один видимый public read-only запуск "
    "slow_liquidity_listing_announcement_article_20260816 через "
    "tools\\start_exact_approved_slow_liquidity_listing_announcement_"
    "article_visible.ps1 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: один official MEXC article URL "
    "из frozen discovery, exclude closed 9, no invented tickers, slug "
    "first-in-market не ticker, identity before OHLCV collect. Не Bing, "
    "не sitemap, не retry discovery/r1-r4, не reuse spot v2 consumer. Не "
    "v7. STOPPED_INCOMPLETE не повторять. Без evaluator, OOS, "
    "returns/PnL, grid/retune, paper/live, private API, реальных денег, "
    "плеча или маржи."
)


class ListingAnnouncementArticleError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingAnnouncementArticleError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def classify_listing_slug(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(marker in path for marker in LISTING_SLUG_MARKERS)


def extract_base_from_listing_slug(url: str) -> str | None:
    if not classify_listing_slug(url):
        return None
    match = WILL_LIST_BASE_RE.search(urlsplit(url).path)
    if match is None:
        return None
    base = match.group(1).upper()
    if base in EXPECTED_BASES:
        return None
    return base


def _load_frozen_candidate_url() -> str:
    _require(PARENT_CANDIDATES_PATH.is_file(), "frozen candidates missing")
    _require(
        _sha256_file(PARENT_CANDIDATES_PATH) == PARENT_CANDIDATES_SHA256,
        "frozen candidates hash mismatch",
    )
    if PARENT_MANIFEST_PATH.is_file():
        _require(
            _sha256_file(PARENT_MANIFEST_PATH) == PARENT_MANIFEST_SHA256,
            "frozen discovery manifest hash mismatch",
        )
    payload = json.loads(PARENT_CANDIDATES_PATH.read_text(encoding="utf-8"))
    _require(isinstance(payload, list) and len(payload) == 1, "candidate count")
    url = str(payload[0].get("official_source_url") or "")
    _require(url == ARTICLE_URL, "frozen candidate URL mismatch")
    return url


def build_listing_announcement_article_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_DISCOVERY_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_DISCOVERY_PLAN_PATH)
            == PARENT_DISCOVERY_PLAN_FILE_SHA256,
            "parent discovery plan file hash mismatch",
        )
    if PARENT_DISCOVERY_RECEIPT_PATH.is_file():
        _require(
            _sha256_file(PARENT_DISCOVERY_RECEIPT_PATH)
            == PARENT_DISCOVERY_RECEIPT_FILE_SHA256,
            "parent discovery receipt file hash mismatch",
        )
    url = _load_frozen_candidate_url()
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_ARTICLE_APPROVAL",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_execution_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "spot_v2_runtime_reuse": False,
        "market": "SPOT_USDT",
        "selected_bases": [],
        "extracted_bases": [],
        "invented_ticker_count": 0,
        "excluded_bases": list(EXPECTED_BASES),
        "identity_before_ohlcv_collect": True,
        "listing_slug_match": classify_listing_slug(url),
        "listing_slug_markers": list(LISTING_SLUG_MARKERS),
        "article_path_prefix": ARTICLE_PREFIX,
        "goal": (
            "Read the one frozen official MEXC announcement article URL. "
            "Do not invent tickers, treat first-in-market as a ticker, "
            "reuse the closed 9 bases, or open identity/OHLCV/replay."
        ),
        "parent_listing_announcement_discovery": {
            "plan_id": PARENT_DISCOVERY_PLAN_ID,
            "plan_path": str(PARENT_DISCOVERY_PLAN_PATH),
            "plan_hash": PARENT_DISCOVERY_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_DISCOVERY_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_DISCOVERY_RECEIPT_PATH),
            "receipt_file_sha256": PARENT_DISCOVERY_RECEIPT_FILE_SHA256,
            "candidates_path": str(PARENT_CANDIDATES_PATH),
            "candidates_sha256": PARENT_CANDIDATES_SHA256,
            "manifest_path": str(PARENT_MANIFEST_PATH),
            "manifest_sha256": PARENT_MANIFEST_SHA256,
            "status": "LISTING_ANNOUNCEMENT_DISCOVERY_INCOMPLETE",
        },
        "seed_items": [
            {
                "venue": "mexc",
                "official_source_url": url,
                "article_host": ARTICLE_HOST,
                "source_index_url": "https://www.mexc.com/announcements",
                "evidence_class": "OFFICIAL_LISTING_ANNOUNCEMENT_INDEX",
            }
        ],
        "limits": {
            "maximum_total_http_requests": 1,
            "maximum_attempts_per_url": 1,
            "maximum_response_bytes_per_request": 1_000_000,
            "max_runtime_sec": 180,
            "hard_output_cap_bytes": 5_000_000,
        },
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_execution_allowed": False,
            "replay_allowed": False,
            "ohlcv_collect_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_listing_announcement_article_plan(plan)
    return plan


def validate_listing_announcement_article_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "article plan schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "article plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(plan.get("selected_bases") == [], "tickers were invented")
    _require(plan.get("extracted_bases") == [], "extracted tickers in plan")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(plan.get("excluded_bases") == list(EXPECTED_BASES), "excluded bases")
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("replay_allowed") is False, "replay already allowed")
    _require(plan.get("spot_v2_runtime_reuse") is False, "spot v2 runtime reused")
    _require(
        plan.get("identity_execution_authorized") is False,
        "identity execution already authorized",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    seeds = plan.get("seed_items")
    _require(isinstance(seeds, list) and len(seeds) == 1, "seed count")
    url = str(seeds[0]["official_source_url"])
    _require(url == ARTICLE_URL, "article url")
    _require(seeds[0]["article_host"] == ARTICLE_HOST, "article host")
    _require(
        plan.get("listing_slug_match") is classify_listing_slug(url),
        "listing slug match",
    )
    _require(plan.get("listing_slug_match") is False, "first-in-market treated as listing")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    _require("keyword=" not in dumped, "ticker keyword search leaked")
    parent = plan.get("parent_listing_announcement_discovery") or {}
    _require(parent.get("plan_hash") == PARENT_DISCOVERY_PLAN_HASH, "parent hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_DISCOVERY_PLAN_FILE_SHA256,
        "parent file hash",
    )
    _require(
        parent.get("candidates_sha256") == PARENT_CANDIDATES_SHA256,
        "candidates hash",
    )


def write_listing_announcement_article_plan(generated_at_utc: str) -> Path:
    plan = build_listing_announcement_article_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if ARTICLE_PLAN_PATH.exists():
        _require(
            ARTICLE_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {ARTICLE_PLAN_PATH}",
        )
        return ARTICLE_PLAN_PATH
    ARTICLE_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTICLE_PLAN_PATH.write_text(payload, encoding="utf-8")
    return ARTICLE_PLAN_PATH


def _page_title(body: bytes) -> str:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ListingAnnouncementArticleError("article is not UTF-8") from exc
    match = TITLE_RE.search(text)
    if match is None:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


@dataclass(frozen=True)
class ListingAnnouncementArticleResult:
    status: str
    official_source_url: str
    title: str
    extracted_bases: tuple[str, ...]
    selected_bases: tuple[str, ...]
    request_count: int
    listing_slug_match: bool
    identity_verdict: bool
    network_accessed: bool


def fetch_listing_announcement_article(
    plan: Mapping[str, Any],
    *,
    user_approval_text: str,
    fetch: Callable[[str], FetchedResponse] = fetch_public_discovery_response,
    monotonic: Callable[[], float] = time.monotonic,
) -> ListingAnnouncementArticleResult:
    validate_listing_announcement_article_plan(plan)
    allowed = {EXPECTED_APPROVAL_TEXT}
    if ARTICLE_PLAN_PATH.is_file():
        frozen = json.loads(ARTICLE_PLAN_PATH.read_text(encoding="utf-8"))
        allowed.add(
            fill_expected_approval_text(
                str(frozen["plan_hash"]),
                _sha256_file(ARTICLE_PLAN_PATH),
            )
        )
    _require(
        normalize_approval_text(user_approval_text) in allowed,
        "approval text mismatch",
    )
    started = monotonic()
    item = plan["seed_items"][0]
    url = str(item["official_source_url"])
    _require(monotonic() - started <= 180, "runtime cap exceeded")
    try:
        response = fetch(url)
    except IdentityVerificationError as exc:
        raise ListingAnnouncementArticleError(str(exc)) from exc
    _require(isinstance(response, FetchedResponse), "invalid fetch response")
    _require(response.requested_url == url, "fetcher request URL mismatch")
    _require(response.final_url == url, "HTTP redirect is forbidden")
    _require(response.status == 200, f"HTTP {response.status} for {url}")
    _require(len(response.body) <= 1_000_000, "response exceeds cap")
    extracted = extract_base_from_listing_slug(url)
    extracted_bases = (extracted,) if extracted else ()
    return ListingAnnouncementArticleResult(
        status="LISTING_ANNOUNCEMENT_ARTICLE_INCOMPLETE",
        official_source_url=url,
        title=_page_title(response.body),
        extracted_bases=extracted_bases,
        selected_bases=(),
        request_count=1,
        listing_slug_match=classify_listing_slug(url),
        identity_verdict=False,
        network_accessed=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--run-approved-visible-article", action="store_true")
    parser.add_argument("--user-approval-text", default="")
    args = parser.parse_args(argv)
    if args.write_plan:
        generated = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        path = write_listing_announcement_article_plan(generated)
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
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not args.run_approved_visible_article:
        raise SystemExit("no authorized action requested")
    plan = json.loads(ARTICLE_PLAN_PATH.read_text(encoding="utf-8"))
    approval = args.user_approval_text or fill_expected_approval_text(
        str(plan["plan_hash"]),
        _sha256_file(ARTICLE_PLAN_PATH),
    )
    result = fetch_listing_announcement_article(plan, user_approval_text=approval)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    record_path = OUTPUT_ROOT / "article-record.json"
    manifest_path = OUTPUT_ROOT / "manifest.json"
    _require(not record_path.exists(), "article output already exists")
    record = {
        "venue": "mexc",
        "official_source_url": result.official_source_url,
        "title": result.title,
        "extracted_bases": list(result.extracted_bases),
        "selected_bases": list(result.selected_bases),
        "listing_slug_match": result.listing_slug_match,
        "evidence_class": "OFFICIAL_LISTING_ANNOUNCEMENT_ARTICLE",
        "identity_verdict": False,
    }
    manifest = {
        "schema": "trading_mvp_slow_liquidity_listing_announcement_article_output_v1",
        "status": result.status,
        "plan_id": PLAN_ID,
        "plan_hash": plan["plan_hash"],
        "identity_verdict": False,
        "request_count": result.request_count,
        "listing_slug_match": result.listing_slug_match,
        "extracted_bases": list(result.extracted_bases),
        "selected_bases": [],
        "retry_authorized": False,
    }
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "extracted_bases": list(result.extracted_bases),
                "title": result.title,
            }
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
