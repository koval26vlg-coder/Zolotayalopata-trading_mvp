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
from urllib.parse import urljoin, urlsplit

from slow_liquidity_official_identity_proposal import EXPECTED_BASES
from slow_liquidity_official_identity_verification import (
    FetchedResponse,
    IdentityVerificationError,
)
from slow_liquidity_listing_first_universe import (
    DISCOVERY_PLAN_PATH as PARENT_UNIVERSE_PLAN_PATH,
    PLAN_ID as PARENT_UNIVERSE_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    canonical_hash,
    fetch_public_discovery_response,
    normalize_approval_text,
)


SCHEMA = "trading_mvp_slow_liquidity_listing_announcement_discovery_planonly_v1"
PLAN_ID = "slow_liquidity_listing_announcement_discovery_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-listing-announcement-discovery-planonly-20260816.json"
)
PARENT_UNIVERSE_PLAN_HASH = (
    "748b0777e3f628483fcf00212dc130a8608ca85684d5aca57c286cebe6341771"
)
PARENT_UNIVERSE_PLAN_FILE_SHA256 = (
    "375ab9eb16f8d67b1d1b3ac51fc6237ceb0da9b6a8e4acddc5a40db375c7ecfc"
)
PARENT_UNIVERSE_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-15-slow-liquidity-listing-first-universe-approval.json"
)
PARENT_UNIVERSE_RECEIPT_HASH = (
    "95fe56f9b378d5165ea20aada5fbfa98220ee29948610e87d11ec5fffa6201f9"
)
PARENT_UNIVERSE_RECEIPT_FILE_SHA256 = (
    "4c3bf08a7f3f95bc6c3bfab9d3ac57573aa4c41cdf4da6913fedbbd74285eeda"
)
MEXC_INDEX_URL = "https://www.mexc.com/announcements"
GATE_INDEX_URL = "https://www.gate.com/announcements"
ARTICLE_PREFIX = "/announcements/article/"
HREF_RE = re.compile(r"""href\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
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
    r"\slow-liquidity-listing-announcement-discovery"
    r"\slow_liquidity_listing_announcement_discovery_20260816"
)
EXPECTED_APPROVAL_TEXT = (
    "Разрешаю один видимый public read-only запуск "
    "slow_liquidity_listing_announcement_discovery_20260816 через "
    "tools\\start_exact_approved_slow_liquidity_listing_announcement_"
    "discovery_visible.ps1 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: official listing announcement "
    "indexes only, exclude closed 9, no invented tickers, identity before "
    "OHLCV collect. Не Bing, не sitemap, не retry r1-r4, не reuse spot v2 "
    "consumer. Не v7. STOPPED_INCOMPLETE не повторять. Без evaluator, OOS, "
    "returns/PnL, grid/retune, paper/live, private API, реальных денег, "
    "плеча или маржи."
)


class ListingAnnouncementDiscoveryError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ListingAnnouncementDiscoveryError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def build_listing_announcement_discovery_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_UNIVERSE_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_UNIVERSE_PLAN_PATH) == PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "parent universe plan file hash mismatch",
        )
    if PARENT_UNIVERSE_RECEIPT_PATH.is_file():
        _require(
            _sha256_file(PARENT_UNIVERSE_RECEIPT_PATH)
            == PARENT_UNIVERSE_RECEIPT_FILE_SHA256,
            "parent universe receipt file hash mismatch",
        )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_DISCOVERY_APPROVAL",
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
        "invented_ticker_count": 0,
        "excluded_bases": list(EXPECTED_BASES),
        "identity_before_ohlcv_collect": True,
        "article_path_prefix": ARTICLE_PREFIX,
        "goal": (
            "Read official MEXC and Gate announcement indexes and collect "
            "article URLs. Do not invent tickers, reuse the closed 9 bases, "
            "or open identity/OHLCV/replay."
        ),
        "parent_listing_first_universe": {
            "plan_id": PARENT_UNIVERSE_PLAN_ID,
            "plan_path": str(PARENT_UNIVERSE_PLAN_PATH),
            "plan_hash": PARENT_UNIVERSE_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_UNIVERSE_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_UNIVERSE_RECEIPT_PATH),
            "receipt_hash": PARENT_UNIVERSE_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_UNIVERSE_RECEIPT_FILE_SHA256,
            "status": "ACCEPTED_LISTING_FIRST_UNIVERSE_NO_NETWORK",
        },
        "seed_items": [
            {
                "venue": "mexc",
                "index_url": MEXC_INDEX_URL,
                "article_host": "www.mexc.com",
            },
            {
                "venue": "gateio",
                "index_url": GATE_INDEX_URL,
                "article_host": "www.gate.com",
            },
        ],
        "limits": {
            "maximum_total_http_requests": 2,
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
    validate_listing_announcement_discovery_plan(plan)
    return plan


def validate_listing_announcement_discovery_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "listing discovery schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "listing discovery plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(plan.get("selected_bases") == [], "tickers were invented")
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
    _require(isinstance(seeds, list) and len(seeds) == 2, "seed count")
    _require(seeds[0]["index_url"] == MEXC_INDEX_URL, "mexc index")
    _require(seeds[1]["index_url"] == GATE_INDEX_URL, "gate index")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    _require("keyword=" not in dumped, "ticker keyword search leaked")
    parent = plan.get("parent_listing_first_universe") or {}
    _require(parent.get("plan_hash") == PARENT_UNIVERSE_PLAN_HASH, "parent universe hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_UNIVERSE_PLAN_FILE_SHA256,
        "parent universe file hash",
    )


def write_listing_announcement_discovery_plan(generated_at_utc: str) -> Path:
    plan = build_listing_announcement_discovery_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if DISCOVERY_PLAN_PATH.exists():
        _require(
            DISCOVERY_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {DISCOVERY_PLAN_PATH}",
        )
        return DISCOVERY_PLAN_PATH
    DISCOVERY_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_PLAN_PATH.write_text(payload, encoding="utf-8")
    return DISCOVERY_PLAN_PATH


def _mentions_closed_base(url: str) -> bool:
    lowered = url.lower()
    for base in EXPECTED_BASES:
        token = base.lower()
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
            return True
    return False


def _article_urls(index_url: str, host: str, body: bytes) -> tuple[str, ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ListingAnnouncementDiscoveryError("index is not UTF-8") from exc
    found: list[str] = []
    seen: set[str] = set()
    for match in HREF_RE.finditer(text):
        raw = match.group(1).strip()
        absolute = urljoin(index_url, raw)
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or parsed.hostname != host:
            continue
        if ARTICLE_PREFIX not in parsed.path:
            continue
        if parsed.query or parsed.fragment:
            continue
        if "futures" in parsed.path.lower():
            continue
        if _mentions_closed_base(absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
    return tuple(found)


@dataclass(frozen=True)
class ListingAnnouncementDiscoveryResult:
    status: str
    candidates: tuple[dict[str, Any], ...]
    request_count: int
    identity_verdict: bool
    network_accessed: bool


def collect_listing_announcement_candidates(
    plan: Mapping[str, Any],
    *,
    user_approval_text: str,
    fetch: Callable[[str], FetchedResponse] = fetch_public_discovery_response,
    monotonic: Callable[[], float] = time.monotonic,
) -> ListingAnnouncementDiscoveryResult:
    validate_listing_announcement_discovery_plan(plan)
    allowed = {EXPECTED_APPROVAL_TEXT}
    if DISCOVERY_PLAN_PATH.is_file():
        frozen = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        allowed.add(
            fill_expected_approval_text(
                str(frozen["plan_hash"]),
                _sha256_file(DISCOVERY_PLAN_PATH),
            )
        )
    _require(
        normalize_approval_text(user_approval_text) in allowed,
        "approval text mismatch",
    )
    started = monotonic()
    request_count = 0
    candidates: list[dict[str, Any]] = []
    for item in plan["seed_items"]:
        _require(monotonic() - started <= 180, "runtime cap exceeded")
        _require(request_count < 2, "HTTP request cap exceeded")
        url = str(item["index_url"])
        request_count += 1
        try:
            response = fetch(url)
        except IdentityVerificationError as exc:
            raise ListingAnnouncementDiscoveryError(str(exc)) from exc
        _require(isinstance(response, FetchedResponse), "invalid fetch response")
        _require(response.requested_url == url, "fetcher request URL mismatch")
        _require(response.final_url == url, "HTTP redirect is forbidden")
        _require(response.status == 200, f"HTTP {response.status} for {url}")
        _require(len(response.body) <= 1_000_000, "response exceeds cap")
        for article in _article_urls(url, str(item["article_host"]), response.body):
            candidates.append(
                {
                    "venue": item["venue"],
                    "official_source_url": article,
                    "source_index_url": url,
                    "evidence_class": "OFFICIAL_LISTING_ANNOUNCEMENT_INDEX",
                    "identity_verdict": False,
                }
            )
    return ListingAnnouncementDiscoveryResult(
        status="LISTING_ANNOUNCEMENT_DISCOVERY_INCOMPLETE",
        candidates=tuple(candidates),
        request_count=request_count,
        identity_verdict=False,
        network_accessed=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--run-approved-visible-discovery", action="store_true")
    parser.add_argument("--user-approval-text", default="")
    args = parser.parse_args(argv)
    if args.write_plan:
        generated = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        path = write_listing_announcement_discovery_plan(generated)
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
    if not args.run_approved_visible_discovery:
        raise SystemExit("no authorized action requested")
    plan = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
    approval = args.user_approval_text or fill_expected_approval_text(
        str(plan["plan_hash"]),
        _sha256_file(DISCOVERY_PLAN_PATH),
    )
    result = collect_listing_announcement_candidates(plan, user_approval_text=approval)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    candidates_path = OUTPUT_ROOT / "listing-announcement-candidates.json"
    manifest_path = OUTPUT_ROOT / "manifest.json"
    _require(not candidates_path.exists(), "listing discovery output already exists")
    candidates = list(result.candidates)
    manifest = {
        "schema": "trading_mvp_slow_liquidity_listing_announcement_discovery_output_v1",
        "status": result.status,
        "plan_id": PLAN_ID,
        "plan_hash": plan["plan_hash"],
        "identity_verdict": False,
        "request_count": result.request_count,
        "candidate_count": len(candidates),
        "selected_bases": [],
        "retry_authorized": False,
    }
    candidates_path.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result.status, "candidate_count": len(candidates)}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
