from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from slow_liquidity_official_identity_proposal import (
    COLLISION_FAIL_CLOSED_BASES,
    EXPECTED_BASES,
    EXPECTED_VENUES,
    PROPOSAL_ID,
    collected_spot_instrument,
)
from slow_liquidity_official_identity_verification import (
    FetchedResponse,
    IdentityVerificationError,
    _strict_json_loads,
    _validate_official_source_url,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    BINDINGS_FILE_SHA256,
    BINDINGS_PLAN_HASH,
    EVIDENCE_HOSTS,
    SpotV2OfficialPageDiscoveryError,
    _canonical_identifier_from_official_page,
    _exact_token,
    _official_host,
    _request_plan_item,
    canonical_hash,
    canonical_json_bytes,
    fetch_public_discovery_response,
    normalize_approval_text,
)
from slow_liquidity_spot_v2_official_page_discovery_r2 import (
    _collected_instrument_is_listed,
    _metadata_url,
)
from slow_liquidity_spot_v2_official_page_discovery_r3 import (
    _discovery_official_url,
)
from slow_liquidity_spot_v2_request_plan import (
    BINDINGS_PATH,
    PLAN_ID as BINDINGS_PLAN_ID,
    SPOT_V2_PROPOSAL_FILE_SHA256,
    SPOT_V2_PROPOSAL_HASH,
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
    build_spot_v2_request_plan_bindings,
    validate_spot_v2_request_plan_bindings,
)


SCHEMA = "trading_mvp_slow_liquidity_spot_v2_official_page_discovery_planonly_r4"
PLAN_ID = "slow_liquidity_spot_v2_official_page_discovery_20260815_r4"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-official-page-discovery-planonly-20260815-r4.json"
)
PARENT_R3_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-official-page-discovery-planonly-20260815-r3.json"
)
PARENT_R3_PLAN_ID = "slow_liquidity_spot_v2_official_page_discovery_20260815_r3"
PARENT_R3_PLAN_HASH = (
    "fa527d7fcb2e01b56c1bf33f5d897e8c8ef69758b9f00963c0c1181da7658631"
)
PARENT_R3_PLAN_FILE_SHA256 = (
    "d14caf3556fa6707e8969263f878159a4a927e0e130577f0250bacec42b914f8"
)
PARENT_R3_MANIFEST_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-page-discovery"
    r"\slow_liquidity_spot_v2_official_page_discovery_20260815_r3\manifest.json"
)
PARENT_R3_MANIFEST_SHA256 = (
    "2ef958ed23720be8688e38f7c48fb7a29c8ced6e06fa84ce37318b7837ce83bd"
)
TOPOLOGY_V4_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-official-currentness-topology"
    r"\slow_liquidity_official_currentness_topology_discovery_20260814_v4\topology.json"
)
TOPOLOGY_V4_FILE_SHA256 = (
    "e0bd139724034dee1b37d2173814a70a8029d3f6a10d5e4059982bda2fa5aeaa"
)
TOPOLOGY_V4_RESULT_HASH = (
    "3e2ca0be86d57dcd3182d515ca0185e92f10748ca08e2926f6c34aac9d7343c7"
)
MEXC_NEWS_SITEMAP_INDEX = "https://www.mexc.com/news/sitemap-index.xml"
GATE_GOOGLE_NEWS_SITEMAP = (
    "https://www.gate.com/sitemaps/sitemap-google-news-recent-en-001.xml"
)
GATE_ANNOUNCEMENT_SITEMAP = (
    "https://www.gate.com/sitemaps/sitemap-announcement-001.xml"
)
SEED_FIELDS = {
    "venue",
    "base_ticker",
    "instrument_id",
    "collision_fail_closed",
    "metadata_url",
    "expected_official_host",
    "allowed_official_path_prefix",
}
OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-page-discovery"
    r"\slow_liquidity_spot_v2_official_page_discovery_20260815_r4"
)
APPROVAL_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/"
    "2026-08-15-slow-liquidity-spot-v2-official-page-discovery-r4-approval.json"
)
MAX_SITEMAP_CHILDREN = 8
EXPECTED_APPROVAL_TEXT = (
    "Разрешаю один видимый public read-only запуск "
    "slow_liquidity_spot_v2_official_page_discovery_20260815_r4 через "
    "tools\\start_exact_approved_slow_liquidity_spot_v2_official_page_"
    "discovery_r4_visible.ps1 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: MEXC и Gate SPOT_USDT, "
    "18 пар, per-symbol metadata, official news sitemap title/slug, "
    "не Bing, не support HTML search, не повтор r1/r2/r3, "
    "MEXC BASEUSDT / Gate BASE_USDT, EDGE и RAIN fail-closed. "
    "Официальные страницы — не identity verdict. Не v7 и не MEXC perp "
    "underscore ticker. STOPPED_INCOMPLETE не повторять. Без evaluator, OOS, "
    "returns/PnL, grid/retune, execution probe, paper/live, private API, "
    "реальных денег, плеча или маржи."
)


class SpotV2OfficialPageDiscoveryR4Error(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2OfficialPageDiscoveryR4Error(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _seed_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for base in EXPECTED_BASES:
        for venue in EXPECTED_VENUES:
            instrument_id = collected_spot_instrument(venue, base)
            host, prefix = _official_host(venue)
            items.append(
                {
                    "venue": venue,
                    "base_ticker": base,
                    "instrument_id": instrument_id,
                    "collision_fail_closed": base in COLLISION_FAIL_CLOSED_BASES,
                    "metadata_url": _metadata_url(venue, instrument_id),
                    "expected_official_host": host,
                    "allowed_official_path_prefix": prefix,
                }
            )
    return items


def build_spot_v2_official_page_discovery_plan_r4(
    generated_at_utc: str,
) -> dict[str, Any]:
    if BINDINGS_PATH.is_file():
        bindings = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
        validate_spot_v2_request_plan_bindings(bindings)
        _require(bindings.get("plan_hash") == BINDINGS_PLAN_HASH, "bindings hash mismatch")
        _require(
            _sha256_file(BINDINGS_PATH) == BINDINGS_FILE_SHA256,
            "bindings file hash mismatch",
        )
    else:
        bindings = build_spot_v2_request_plan_bindings(generated_at_utc)
    if PARENT_R3_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_R3_PLAN_PATH) == PARENT_R3_PLAN_FILE_SHA256,
            "parent r3 plan file hash mismatch",
        )
    if TOPOLOGY_V4_PATH.is_file():
        _require(
            _sha256_file(TOPOLOGY_V4_PATH) == TOPOLOGY_V4_FILE_SHA256,
            "topology v4 file hash mismatch",
        )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_DISCOVERY_APPROVAL",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "network_authorized": False,
        "execution_authorized": False,
        "consumer_runtime": PROPOSAL_ID,
        "market": "SPOT_USDT",
        "required_pair_count": 18,
        "collision_fail_closed_bases": list(COLLISION_FAIL_CLOSED_BASES),
        "collision_ambiguity_disposition": "REJECT_EXCLUDE_FAIL_CLOSED",
        "goal": (
            "Discover official pages by matching ticker tokens in official "
            "news/announcement sitemap titles and slugs. Not Bing, not support "
            "HTML search, not a retry of r3."
        ),
        "parent_discovery": {
            "plan_id": PARENT_R3_PLAN_ID,
            "plan_path": str(PARENT_R3_PLAN_PATH),
            "plan_hash": PARENT_R3_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_R3_PLAN_FILE_SHA256,
            "manifest_path": str(PARENT_R3_MANIFEST_PATH),
            "manifest_sha256": PARENT_R3_MANIFEST_SHA256,
            "status": "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE",
            "retry_of_parent_forbidden": True,
            "reason": (
                "r3 listed all 18 instruments. Support sitemap locs and venue "
                "HTML keyword search produced zero allowlisted article URLs."
            ),
        },
        "topology_locator": {
            "path": str(TOPOLOGY_V4_PATH),
            "file_sha256": TOPOLOGY_V4_FILE_SHA256,
            "result_hash": TOPOLOGY_V4_RESULT_HASH,
            "identity_evidence": False,
        },
        "source_bindings": {
            "instrument_bindings": {
                "path": str(BINDINGS_PATH),
                "plan_id": BINDINGS_PLAN_ID,
                "file_sha256": BINDINGS_FILE_SHA256,
                "plan_hash": BINDINGS_PLAN_HASH,
            },
            "spot_v2_proposal": {
                "proposal_hash": SPOT_V2_PROPOSAL_HASH,
                "file_sha256": SPOT_V2_PROPOSAL_FILE_SHA256,
            },
            "spot_v2_runtime": {
                "path": str(SPOT_V2_RUNTIME_PATH),
                "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
                "manifest_hash": SPOT_V2_RUNTIME_HASH,
            },
        },
        "compatibility_contract": {
            "consumer_runtime": PROPOSAL_ID,
            "required_pair_count": 18,
            "perp_template_forbidden": True,
            "v7_runtime_forbidden": True,
            "bing_navigation_forbidden": True,
            "support_html_keyword_search_forbidden": True,
            "full_catalog_metadata_forbidden": True,
            "request_plan_items_must_pass_spot_v2_consumer": True,
        },
        "navigation_contract": {
            "provider": "OFFICIAL_NEWS_SITEMAP_TITLE_AND_SLUG",
            "role": "NAVIGATION_ONLY_NOT_IDENTITY_EVIDENCE",
            "bing_navigation_allowed": False,
            "redirect_following_allowed": False,
            "search_result_persistence_allowed": False,
            "mexc_news_sitemap_index": MEXC_NEWS_SITEMAP_INDEX,
            "gate_google_news_sitemap": GATE_GOOGLE_NEWS_SITEMAP,
            "gate_announcement_sitemap": GATE_ANNOUNCEMENT_SITEMAP,
            "match_fields": ["loc_slug", "news_title", "image_title"],
            "maximum_sitemap_children": MAX_SITEMAP_CHILDREN,
        },
        "official_source_contract": {
            "metadata_mode": "PER_SYMBOL",
            "mexc_announcement_prefix_is_discovery_only_until_identity_amendment": True,
        },
        "limits": {
            "maximum_total_http_requests": 56,
            "maximum_attempts_per_url": 2,
            "maximum_response_bytes_per_request": 1_000_000,
            "max_runtime_sec": 600,
            "hard_output_cap_bytes": 20_000_000,
        },
        "seed_items": _seed_items(),
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
            "text_normalization": (
                "normalize CRLF/CR to LF, then trim outer whitespace; "
                "all internal text must match exactly"
            ),
        },
        "authorized_scope_after_exact_approval": {
            "one_visible_public_read_only_official_page_discovery": True,
            "official_source_content_read": True,
            "request_plan_output": True,
            "identity_verdict": False,
            "parent_retry": False,
            "evaluator_or_oos": False,
            "paper_or_live": False,
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_verdict_allowed": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    del bindings
    plan["plan_hash"] = canonical_hash(plan)
    validate_spot_v2_official_page_discovery_plan_r4(plan)
    return plan


def validate_spot_v2_official_page_discovery_plan_r4(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "r4 schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "r4 plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "r4 mode mismatch")
    _require(
        plan.get("status") == "AWAIT_EXACT_HASH_BOUND_DISCOVERY_APPROVAL",
        "r4 status mismatch",
    )
    _require(plan.get("identity_evidence") is False, "r4 claimed identity evidence")
    _require(plan.get("network_authorized") is False, "r4 authorized network")
    _require(plan.get("plan_hash") == canonical_hash(plan), "r4 plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    _require("www.bing.com" not in dumped, "Bing leaked into r4 plan")
    _require("announcements?keyword=" not in dumped, "r3 HTML search leaked")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_discovery") or {}
    _require(parent.get("retry_of_parent_forbidden") is True, "r3 retry not forbidden")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_R3_PLAN_FILE_SHA256,
        "parent r3 hash mismatch",
    )
    nav = plan.get("navigation_contract") or {}
    _require(
        nav.get("provider") == "OFFICIAL_NEWS_SITEMAP_TITLE_AND_SLUG",
        "r4 navigation provider mismatch",
    )
    _require(nav.get("mexc_news_sitemap_index") == MEXC_NEWS_SITEMAP_INDEX, "mexc news sitemap")
    _require(
        nav.get("gate_google_news_sitemap") == GATE_GOOGLE_NEWS_SITEMAP,
        "gate news sitemap",
    )
    seeds = plan.get("seed_items")
    _require(isinstance(seeds, list) and len(seeds) == 18, "r4 seed count")
    for item in seeds:
        _require(set(item) == SEED_FIELDS, "r4 seed fields changed")
        _require("search_url" not in item, "r4 seed still has HTML search")


def write_spot_v2_official_page_discovery_plan_r4(generated_at_utc: str) -> Path:
    plan = build_spot_v2_official_page_discovery_plan_r4(generated_at_utc)
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


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1].lower()


def _sitemap_entries(body: bytes) -> tuple[str, tuple[dict[str, Any], ...]]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise SpotV2OfficialPageDiscoveryR4Error("sitemap XML DTD/entity is forbidden")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SpotV2OfficialPageDiscoveryR4Error("sitemap is not valid XML") from exc
    kind = _local_tag(root.tag)
    if kind == "sitemapindex":
        children: list[str] = []
        for node in root.findall(".//{*}sitemap/{*}loc"):
            value = (node.text or "").strip()
            if value:
                children.append(value)
        return "index", tuple({"url": value, "titles": ()} for value in children)
    if kind != "urlset":
        raise SpotV2OfficialPageDiscoveryR4Error("sitemap root is invalid")
    entries: list[dict[str, Any]] = []
    for url_node in root.findall(".//{*}url"):
        loc = ""
        titles: list[str] = []
        for child in url_node.iter():
            name = _local_tag(child.tag)
            text = (child.text or "").strip()
            if not text:
                continue
            if name == "loc" and not loc:
                loc = text
            elif name in {"title", "news:title"} or name == "title":
                titles.append(text)
        if loc:
            entries.append({"url": loc, "titles": tuple(titles)})
    return "urlset", tuple(entries)


def _entry_matches(
    venue: str, base: str, instrument: str, entry: Mapping[str, Any]
) -> str | None:
    url = _discovery_official_url(venue, str(entry.get("url") or ""))
    if not url:
        return None
    haystacks = [url, *list(entry.get("titles") or ())]
    if any(_exact_token(base, text) or _exact_token(instrument, text) for text in haystacks):
        return url
    return None


@dataclass(frozen=True)
class SpotV2DiscoveryR4Result:
    status: str
    request_plan: tuple[dict[str, Any], ...]
    unresolved_pairs: tuple[str, ...]
    pending_allowlist: tuple[str, ...]
    metadata_diagnostics: tuple[dict[str, str], ...]
    locator_diagnostics: dict[str, int]
    request_count: int
    identity_verdict: bool
    network_accessed: bool


def discover_spot_v2_official_pages_r4(
    plan: Mapping[str, Any],
    *,
    user_approval_text: str,
    fetch: Callable[[str], FetchedResponse] = fetch_public_discovery_response,
    monotonic: Callable[[], float] = time.monotonic,
) -> SpotV2DiscoveryR4Result:
    validate_spot_v2_official_page_discovery_plan_r4(plan)
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
    requests_by_url: dict[str, int] = {}

    def fetch_counted(url: str) -> bytes:
        nonlocal request_count
        _require(monotonic() - started <= 600, "discovery runtime cap exceeded")
        _require(request_count < 56, "discovery HTTP request cap exceeded")
        requests_by_url[url] = requests_by_url.get(url, 0) + 1
        _require(requests_by_url[url] <= 2, "attempt cap per URL exceeded")
        request_count += 1
        try:
            response = fetch(url)
        except IdentityVerificationError as exc:
            raise SpotV2OfficialPageDiscoveryR4Error(str(exc)) from exc
        _require(isinstance(response, FetchedResponse), "invalid fetch response")
        _require(response.requested_url == url, "fetcher request URL mismatch")
        _require(response.final_url == url, "HTTP redirect is forbidden")
        _require(response.status == 200, f"HTTP {response.status} for {url}")
        _require(len(response.body) <= 1_000_000, "response exceeds cap")
        return response.body

    entries: list[dict[str, Any]] = []
    locator = {
        "sitemap_requests": 0,
        "loc_count": 0,
        "title_present_count": 0,
        "title_match_count": 0,
        "slug_match_count": 0,
    }
    roots = (
        plan["navigation_contract"]["mexc_news_sitemap_index"],
        plan["navigation_contract"]["gate_google_news_sitemap"],
        plan["navigation_contract"]["gate_announcement_sitemap"],
    )
    pending_children: list[str] = []
    for root_url in roots:
        try:
            kind, parsed = _sitemap_entries(fetch_counted(root_url))
            locator["sitemap_requests"] += 1
        except (SpotV2OfficialPageDiscoveryR4Error, UnicodeDecodeError, ValueError):
            locator["sitemap_requests"] += 1
            continue
        if kind == "index":
            host = urllib.parse.urlsplit(root_url).hostname
            for item in parsed:
                child = str(item["url"])
                child_host = urllib.parse.urlsplit(child).hostname
                if child.endswith(".xml") and child_host == host:
                    pending_children.append(child)
        else:
            entries.extend(parsed)
    for child in pending_children[:MAX_SITEMAP_CHILDREN]:
        try:
            kind, parsed = _sitemap_entries(fetch_counted(child))
            locator["sitemap_requests"] += 1
        except (SpotV2OfficialPageDiscoveryR4Error, UnicodeDecodeError, ValueError):
            locator["sitemap_requests"] += 1
            continue
        if kind == "urlset":
            entries.extend(parsed)
    locator["loc_count"] = len(entries)
    locator["title_present_count"] = sum(1 for item in entries if item.get("titles"))

    request_plan: list[dict[str, Any]] = []
    unresolved: list[str] = []
    pending: list[str] = []
    diagnostics: list[dict[str, str]] = []

    for item in plan["seed_items"]:
        venue = str(item["venue"])
        base = str(item["base_ticker"])
        instrument = str(item["instrument_id"])
        pair = f"{venue}:{base}"
        collision = bool(item["collision_fail_closed"])
        try:
            payload = _strict_json_loads(
                fetch_counted(str(item["metadata_url"])).decode("utf-8")
            )
            listed = _collected_instrument_is_listed(venue, instrument, payload)
        except (SpotV2OfficialPageDiscoveryR4Error, UnicodeDecodeError, ValueError):
            diagnostics.append(
                {"venue": venue, "instrument_id": instrument, "status": "METADATA_UNREADABLE"}
            )
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:METADATA_UNREADABLE"
            )
            continue
        diagnostics.append(
            {
                "venue": venue,
                "instrument_id": instrument,
                "status": "LISTED" if listed else "NOT_LISTED",
            }
        )
        if not listed:
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:ACTIVE_SPOT_METADATA_MISSING"
            )
            continue
        hits: list[str] = []
        for entry in entries:
            matched = _entry_matches(venue, base, instrument, entry)
            if not matched:
                continue
            if entry.get("titles"):
                locator["title_match_count"] += 1
            else:
                locator["slug_match_count"] += 1
            hits.append(matched)
        candidates = tuple(sorted(set(hits)))
        if len(candidates) != 1:
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else (
                    f"{pair}:EXACT_OFFICIAL_URL_NOT_FOUND"
                    if not candidates
                    else f"{pair}:AMBIGUOUS_OFFICIAL_URL"
                )
            )
            continue
        try:
            official_body = fetch_counted(candidates[0])
            identifier = _canonical_identifier_from_official_page(
                base, instrument, official_body
            )
            try:
                _validate_official_source_url(venue, candidates[0])
            except IdentityVerificationError:
                pending.append(
                    f"{pair}:MEXC_ANNOUNCEMENT_PREFIX_NOT_IN_FROZEN_CONSUMER"
                    if venue == "mexc"
                    else f"{pair}:OFFICIAL_URL_NOT_IN_FROZEN_CONSUMER"
                )
            else:
                request_plan.append(
                    _request_plan_item(
                        venue=venue,
                        base=base,
                        official_url=candidates[0],
                        identifier=identifier,
                    )
                )
        except (
            SpotV2OfficialPageDiscoveryR4Error,
            SpotV2OfficialPageDiscoveryError,
            IdentityVerificationError,
        ):
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:CANONICAL_IDENTIFIER_NOT_UNIQUE"
            )
        print(
            f"SPOT_V2_R4_PROGRESS pair={pair} resolved={len(request_plan)} "
            f"pending={len(pending)} unresolved={len(unresolved)} "
            f"requests={request_count}",
            flush=True,
        )

    complete = len(request_plan) == 18 and not unresolved and not pending
    return SpotV2DiscoveryR4Result(
        status=(
            "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE"
            if complete
            else "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE"
        ),
        request_plan=tuple(request_plan),
        unresolved_pairs=tuple(unresolved),
        pending_allowlist=tuple(pending),
        metadata_diagnostics=tuple(diagnostics),
        locator_diagnostics=locator,
        request_count=request_count,
        identity_verdict=False,
        network_accessed=True,
    )


def write_discovery_bundle_r4(
    result: SpotV2DiscoveryR4Result,
    *,
    user_approval_text: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    _require(DISCOVERY_PLAN_PATH.is_file(), "r4 plan file is missing")
    plan = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
    expected = fill_expected_approval_text(
        str(plan["plan_hash"]),
        _sha256_file(DISCOVERY_PLAN_PATH),
    )
    _require(
        normalize_approval_text(user_approval_text) == expected,
        "approval text mismatch",
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    request_plan_path = OUTPUT_ROOT / "request-plan.json"
    manifest_path = OUTPUT_ROOT / "manifest.json"
    _require(not request_plan_path.exists(), "r4 discovery output already exists")
    request_plan = list(result.request_plan)
    request_plan_hash = hashlib.sha256(canonical_json_bytes(request_plan)).hexdigest()
    manifest = {
        "schema": "trading_mvp_slow_liquidity_spot_v2_official_page_discovery_output_r4",
        "status": result.status,
        "generated_at_utc": generated_at_utc,
        "plan_id": PLAN_ID,
        "plan_hash": plan["plan_hash"],
        "identity_verdict": False,
        "identity_evidence": False,
        "network_accessed": result.network_accessed,
        "request_count": result.request_count,
        "request_plan_count": len(request_plan),
        "unresolved_pairs": list(result.unresolved_pairs),
        "pending_allowlist": list(result.pending_allowlist),
        "metadata_diagnostics": list(result.metadata_diagnostics),
        "locator_diagnostics": result.locator_diagnostics,
        "request_plan_sha256": request_plan_hash,
        "retry_authorized": False,
        "parent_retry": False,
        "v7_used": False,
        "bing_used": False,
        "support_html_search_used": False,
        "full_catalog_metadata_used": False,
    }
    request_plan_path.write_text(
        json.dumps(request_plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if not APPROVAL_RECEIPT_PATH.exists():
        receipt = {
            "schema": "trading_mvp_slow_liquidity_spot_v2_discovery_r4_approval_receipt_v1",
            "status": "APPROVED_SINGLE_USE_VISIBLE_DISCOVERY",
            "user_approval_text": expected,
            "plan_id": PLAN_ID,
            "plan_hash": plan["plan_hash"],
            "plan_file_sha256": _sha256_file(DISCOVERY_PLAN_PATH),
            "identity_verdict": False,
            "retry_authorized": False,
            "parent_retry": False,
        }
        APPROVAL_RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        APPROVAL_RECEIPT_PATH.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {
        "status": result.status,
        "request_plan_path": str(request_plan_path),
        "manifest_path": str(manifest_path),
        "request_plan_sha256": request_plan_hash,
        "request_plan_count": len(request_plan),
        "locator_diagnostics": result.locator_diagnostics,
        "unresolved_pairs": list(result.unresolved_pairs),
        "request_count": result.request_count,
        "identity_verdict": False,
        "network_accessed": True,
    }


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
        path = write_spot_v2_official_page_discovery_plan_r4(generated)
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
    print("SPOT_V2_R4_DISCOVERY_START", flush=True)
    result = discover_spot_v2_official_pages_r4(plan, user_approval_text=approval)
    generated = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    written = write_discovery_bundle_r4(
        result,
        user_approval_text=approval,
        generated_at_utc=generated,
    )
    print(json.dumps(written, ensure_ascii=False), flush=True)
    print("SPOT_V2_R4_DISCOVERY_DONE", written["status"], flush=True)
    return 0 if result.status.endswith("COMPLETE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
