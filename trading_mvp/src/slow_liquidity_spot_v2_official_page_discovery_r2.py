from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
import urllib.parse
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
)
from slow_liquidity_spot_v2_official_page_discovery import (
    BINDINGS_FILE_SHA256,
    BINDINGS_PLAN_HASH,
    EVIDENCE_HOSTS,
    SpotV2OfficialPageDiscoveryError,
    _canonical_identifier_from_official_page,
    _navigation_official_candidates,
    _navigation_query,
    _navigation_url,
    _official_host,
    _request_plan_item,
    canonical_hash,
    canonical_json_bytes,
    fetch_public_discovery_response,
    normalize_approval_text,
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


SCHEMA = "trading_mvp_slow_liquidity_spot_v2_official_page_discovery_planonly_r2"
PLAN_ID = "slow_liquidity_spot_v2_official_page_discovery_20260815_r2"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-official-page-discovery-planonly-20260815-r2.json"
)
PARENT_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-official-page-discovery-planonly-20260815.json"
)
PARENT_PLAN_ID = "slow_liquidity_spot_v2_official_page_discovery_20260815"
PARENT_PLAN_HASH = "becfd2d04871b435614f8a0785ac9e6f90c79cc3537b9868745508bc73e45d20"
PARENT_PLAN_FILE_SHA256 = (
    "10d6cc6407915c49969711afc013e5865d3179b03a2166fb647c88abfd3b4360"
)
PARENT_MANIFEST_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-page-discovery"
    r"\slow_liquidity_spot_v2_official_page_discovery_20260815\manifest.json"
)
PARENT_MANIFEST_SHA256 = (
    "3d43f66bf7a8d2059193ef3e53664feb59cb226422cb38202f8d644f497500cd"
)
CATALOG_EVIDENCE_DIR = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\analysis\fee_evidence_20260702"
)
MEXC_CATALOG_BYTES = 1_732_301
GATE_CATALOG_BYTES = 1_080_843
SEED_FIELDS = {
    "venue",
    "base_ticker",
    "instrument_id",
    "collision_fail_closed",
    "metadata_url",
    "search_url",
    "navigation_query",
    "expected_official_host",
    "allowed_official_path_prefix",
}
OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-page-discovery"
    r"\slow_liquidity_spot_v2_official_page_discovery_20260815_r2"
)
APPROVAL_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/"
    "2026-08-15-slow-liquidity-spot-v2-official-page-discovery-r2-approval.json"
)
EXPECTED_APPROVAL_TEXT = (
    "Разрешаю один видимый public read-only запуск "
    "slow_liquidity_spot_v2_official_page_discovery_20260815_r2 через "
    "tools\\start_exact_approved_slow_liquidity_spot_v2_official_page_"
    "discovery_r2_visible.ps1 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: MEXC и Gate SPOT_USDT, "
    "18 пар из frozen instrument bindings, per-symbol metadata, "
    "MEXC BASEUSDT / Gate BASE_USDT, EDGE и RAIN fail-closed. "
    "Не повтор r1. Bing navigation только для поиска страниц. "
    "Официальные страницы — не identity verdict. Не v7 и не MEXC perp "
    "underscore ticker. STOPPED_INCOMPLETE не повторять. Без evaluator, OOS, "
    "returns/PnL, grid/retune, execution probe, paper/live, private API, "
    "реальных денег, плеча или маржи."
)


class SpotV2OfficialPageDiscoveryR2Error(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2OfficialPageDiscoveryR2Error(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata_url(venue: str, instrument_id: str) -> str:
    if venue == "mexc":
        return "https://api.mexc.com/api/v3/exchangeInfo?" + urllib.parse.urlencode(
            {"symbol": instrument_id}
        )
    if venue == "gateio":
        return f"https://api.gateio.ws/api/v4/spot/currency_pairs/{instrument_id}"
    raise SpotV2OfficialPageDiscoveryR2Error("unsupported metadata venue")


def _seed_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for base in EXPECTED_BASES:
        for venue in EXPECTED_VENUES:
            instrument_id = collected_spot_instrument(venue, base)
            host, prefix = _official_host(venue)
            query = _navigation_query(venue, base, instrument_id)
            items.append(
                {
                    "venue": venue,
                    "base_ticker": base,
                    "instrument_id": instrument_id,
                    "collision_fail_closed": base in COLLISION_FAIL_CLOSED_BASES,
                    "metadata_url": _metadata_url(venue, instrument_id),
                    "search_url": _navigation_url(query),
                    "navigation_query": query,
                    "expected_official_host": host,
                    "allowed_official_path_prefix": prefix,
                }
            )
    return items


def _approval_phrase_template() -> str:
    return EXPECTED_APPROVAL_TEXT


def _catalog_size_evidence() -> dict[str, Any]:
    mexc_path = CATALOG_EVIDENCE_DIR / "mexc_spot_exchangeinfo.json"
    gate_path = CATALOG_EVIDENCE_DIR / "gate_spot_currency_pairs.json"
    mexc_bytes = mexc_path.stat().st_size if mexc_path.is_file() else MEXC_CATALOG_BYTES
    gate_bytes = gate_path.stat().st_size if gate_path.is_file() else GATE_CATALOG_BYTES
    _require(mexc_bytes == MEXC_CATALOG_BYTES, "mexc catalog evidence size drifted")
    _require(gate_bytes == GATE_CATALOG_BYTES, "gate catalog evidence size drifted")
    return {
        "source_dir": str(CATALOG_EVIDENCE_DIR),
        "source_date": "2026-07-02",
        "network_read_for_this_plan": False,
        "mexc_spot_exchangeinfo_bytes": mexc_bytes,
        "gate_spot_currency_pairs_bytes": gate_bytes,
        "parent_response_cap_bytes": 1_000_000,
        "both_catalogs_exceed_parent_cap": True,
    }


def build_spot_v2_official_page_discovery_plan_r2(
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
    if PARENT_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_PLAN_PATH) == PARENT_PLAN_FILE_SHA256,
            "parent discovery plan file hash mismatch",
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
            "Discover official public pages for the frozen 18 collected spot "
            "instruments using per-symbol metadata. This is not an identity verdict "
            "and not a retry of the r1 catalog-cap incomplete run."
        ),
        "parent_discovery": {
            "plan_id": PARENT_PLAN_ID,
            "plan_path": str(PARENT_PLAN_PATH),
            "plan_hash": PARENT_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_PLAN_FILE_SHA256,
            "manifest_path": str(PARENT_MANIFEST_PATH),
            "manifest_sha256": PARENT_MANIFEST_SHA256,
            "status": "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE",
            "retry_of_parent_forbidden": True,
            "reason": (
                "Parent used full catalog metadata endpoints that exceed the "
                "frozen 1MB response cap."
            ),
        },
        "catalog_size_evidence": _catalog_size_evidence(),
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
            "instrument_rule": "collected_spot_instrument(venue, base)",
            "perp_template_forbidden": True,
            "v7_runtime_forbidden": True,
            "full_catalog_metadata_forbidden": True,
            "request_plan_items_must_pass_spot_v2_consumer": True,
        },
        "navigation_contract": {
            "provider": "BING_RSS",
            "scheme": "https",
            "host": "www.bing.com",
            "path": "/search",
            "role": "NAVIGATION_ONLY_NOT_IDENTITY_EVIDENCE",
            "search_result_title_is_identity_evidence": False,
            "search_result_snippet_is_identity_evidence": False,
            "search_result_persistence_allowed": False,
            "redirect_following_allowed": False,
        },
        "official_source_contract": {
            "metadata_mode": "PER_SYMBOL",
            "metadata_url_templates": {
                "mexc": "https://api.mexc.com/api/v3/exchangeInfo?symbol=<INSTRUMENT>",
                "gateio": "https://api.gateio.ws/api/v4/spot/currency_pairs/<INSTRUMENT>",
            },
            "evidence_hosts": {
                venue: {
                    "host": host,
                    "allowed_path_prefix": prefix,
                }
                for venue, (host, prefix) in EVIDENCE_HOSTS.items()
            },
            "collected_instrument_presence_not_retail_flag": True,
            "only_allowlisted_official_page_content_is_identity_evidence": True,
            "ticker_or_name_match_alone_is_identity_evidence": False,
            "exact_unique_canonical_identifier_required": True,
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
            "exact_user_text_template": _approval_phrase_template(),
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
            "returns_or_pnl": False,
            "grid_or_retune": False,
            "execution_probe": False,
            "paper_or_live": False,
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "official_source_content_read_allowed": False,
            "identity_verdict_allowed": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    del bindings
    plan["plan_hash"] = canonical_hash(plan)
    validate_spot_v2_official_page_discovery_plan_r2(plan)
    return plan


def validate_spot_v2_official_page_discovery_plan_r2(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "discovery r2 plan schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "discovery r2 plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "discovery r2 plan mode mismatch")
    _require(
        plan.get("status") == "AWAIT_EXACT_HASH_BOUND_DISCOVERY_APPROVAL",
        "discovery r2 plan status mismatch",
    )
    _require(plan.get("identity_evidence") is False, "r2 plan claimed identity evidence")
    _require(plan.get("network_authorized") is False, "r2 plan authorized network")
    _require(plan.get("execution_authorized") is False, "r2 plan authorized execution")
    _require(plan.get("market") == "SPOT_USDT", "r2 plan market mismatch")
    _require(plan.get("plan_hash") == canonical_hash(plan), "r2 plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    _require("20260815-v7" not in dumped, "v7 runtime leaked into r2 plan")
    _require("{BASE}_USDT" not in dumped, "perp instrument template leaked")
    _require("contract.mexc.com" not in dumped, "perp metadata endpoint leaked")
    _require(
        "https://api.mexc.com/api/v3/exchangeInfo\"" not in dumped,
        "full MEXC catalog endpoint leaked",
    )
    _require(
        "https://api.gateio.ws/api/v4/spot/currency_pairs\"" not in dumped,
        "full Gate catalog endpoint leaked",
    )
    parent = plan.get("parent_discovery") or {}
    _require(parent.get("retry_of_parent_forbidden") is True, "parent retry not forbidden")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_PLAN_FILE_SHA256,
        "parent plan file hash mismatch",
    )
    evidence = plan.get("catalog_size_evidence") or {}
    _require(
        int(evidence.get("mexc_spot_exchangeinfo_bytes") or 0) > 1_000_000,
        "mexc catalog evidence is not above cap",
    )
    _require(
        int(evidence.get("gate_spot_currency_pairs_bytes") or 0) > 1_000_000,
        "gate catalog evidence is not above cap",
    )
    limits = plan.get("limits") or {}
    _require(limits.get("maximum_total_http_requests") == 56, "r2 HTTP cap mismatch")
    _require(
        limits.get("maximum_response_bytes_per_request") == 1_000_000,
        "r2 response cap mismatch",
    )
    seeds = plan.get("seed_items")
    _require(isinstance(seeds, list) and len(seeds) == 18, "r2 seed item count mismatch")
    seen: set[tuple[str, str]] = set()
    for item in seeds:
        _require(isinstance(item, dict), "r2 seed item is invalid")
        _require(set(item) == SEED_FIELDS, "r2 seed item field set changed")
        venue = str(item.get("venue"))
        base = str(item.get("base_ticker"))
        expected = collected_spot_instrument(venue, base)
        _require(item.get("instrument_id") == expected, "collected spot instrument mismatch")
        _require(
            item.get("metadata_url") == _metadata_url(venue, expected),
            "per-symbol metadata URL mismatch",
        )
        pair = (venue, base)
        _require(pair not in seen, "duplicate r2 seed pair")
        seen.add(pair)
    _require(
        seen == {(venue, base) for venue in EXPECTED_VENUES for base in EXPECTED_BASES},
        "r2 seed universe mismatch",
    )


def write_spot_v2_official_page_discovery_plan_r2(generated_at_utc: str) -> Path:
    plan = build_spot_v2_official_page_discovery_plan_r2(generated_at_utc)
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


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


@dataclass(frozen=True)
class SpotV2DiscoveryR2Result:
    status: str
    request_plan: tuple[dict[str, Any], ...]
    unresolved_pairs: tuple[str, ...]
    metadata_diagnostics: tuple[dict[str, str], ...]
    request_count: int
    identity_verdict: bool
    network_accessed: bool


def _collected_instrument_is_listed(
    venue: str, instrument: str, payload: Any
) -> bool:
    if venue == "mexc":
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            return False
        for row in payload["symbols"]:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol") or "").upper() != instrument:
                continue
            if str(row.get("quoteAsset") or "").upper() != "USDT":
                continue
            if str(row.get("status") or "").upper() not in {"1", "ENABLED", "TRADING"}:
                continue
            return True
        return False
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("id") or row.get("name") or "").upper()
        if name != instrument:
            continue
        if str(row.get("quote") or "").upper() != "USDT":
            continue
        if str(row.get("trade_status") or "").lower() != "tradable":
            continue
        return True
    return False


def discover_spot_v2_official_pages_r2(
    plan: Mapping[str, Any],
    *,
    user_approval_text: str,
    fetch: Callable[[str], FetchedResponse] = fetch_public_discovery_response,
    monotonic: Callable[[], float] = time.monotonic,
) -> SpotV2DiscoveryR2Result:
    validate_spot_v2_official_page_discovery_plan_r2(plan)
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
            raise SpotV2OfficialPageDiscoveryR2Error(str(exc)) from exc
        _require(isinstance(response, FetchedResponse), "invalid fetch response")
        _require(response.requested_url == url, "fetcher request URL mismatch")
        _require(response.final_url == url, "HTTP redirect is forbidden")
        _require(response.status == 200, f"HTTP {response.status} for {url}")
        _require(len(response.body) <= 1_000_000, "METADATA_RESPONSE_CAP_EXCEEDED")
        return response.body

    request_plan: list[dict[str, Any]] = []
    unresolved: list[str] = []
    diagnostics: list[dict[str, str]] = []

    for item in plan["seed_items"]:
        venue = str(item["venue"])
        base = str(item["base_ticker"])
        instrument = str(item["instrument_id"])
        pair = f"{venue}:{base}"
        collision = bool(item["collision_fail_closed"])
        listed = False
        try:
            payload = _strict_json_loads(fetch_counted(str(item["metadata_url"])).decode("utf-8"))
            listed = _collected_instrument_is_listed(venue, instrument, payload)
            diagnostics.append(
                {
                    "venue": venue,
                    "instrument_id": instrument,
                    "status": "LISTED" if listed else "NOT_LISTED",
                }
            )
        except SpotV2OfficialPageDiscoveryR2Error as exc:
            reason = str(exc)
            if "METADATA_RESPONSE_CAP_EXCEEDED" in reason:
                code = "METADATA_RESPONSE_CAP_EXCEEDED"
            elif "HTTP" in reason:
                code = "METADATA_HTTP_ERROR"
            else:
                code = "METADATA_UNREADABLE"
            diagnostics.append(
                {
                    "venue": venue,
                    "instrument_id": instrument,
                    "status": code,
                }
            )
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION" if collision else f"{pair}:{code}"
            )
            print(
                f"SPOT_V2_R2_PROGRESS pair={pair} listed=0 "
                f"resolved={len(request_plan)} unresolved={len(unresolved)} "
                f"requests={request_count}",
                flush=True,
            )
            continue
        except (UnicodeDecodeError, ValueError):
            diagnostics.append(
                {
                    "venue": venue,
                    "instrument_id": instrument,
                    "status": "METADATA_UNREADABLE",
                }
            )
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:METADATA_UNREADABLE"
            )
            continue
        if not listed:
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:ACTIVE_SPOT_METADATA_MISSING"
            )
            print(
                f"SPOT_V2_R2_PROGRESS pair={pair} listed=0 "
                f"resolved={len(request_plan)} unresolved={len(unresolved)} "
                f"requests={request_count}",
                flush=True,
            )
            continue
        try:
            navigation = fetch_counted(str(item["search_url"]))
            candidates = _navigation_official_candidates(
                venue, base, instrument, navigation
            )
        except (
            SpotV2OfficialPageDiscoveryR2Error,
            SpotV2OfficialPageDiscoveryError,
            UnicodeDecodeError,
            ValueError,
        ):
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:NAVIGATION_RESPONSE_INVALID"
            )
            continue
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
            request_plan.append(
                _request_plan_item(
                    venue=venue,
                    base=base,
                    official_url=candidates[0],
                    identifier=identifier,
                )
            )
        except (
            SpotV2OfficialPageDiscoveryR2Error,
            SpotV2OfficialPageDiscoveryError,
            IdentityVerificationError,
        ):
            unresolved.append(
                f"{pair}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{pair}:CANONICAL_IDENTIFIER_NOT_UNIQUE"
            )
        print(
            f"SPOT_V2_R2_PROGRESS pair={pair} listed=1 "
            f"resolved={len(request_plan)} unresolved={len(unresolved)} "
            f"requests={request_count}",
            flush=True,
        )

    complete = len(request_plan) == 18 and not unresolved
    return SpotV2DiscoveryR2Result(
        status=(
            "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE"
            if complete
            else "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE"
        ),
        request_plan=tuple(request_plan),
        unresolved_pairs=tuple(unresolved),
        metadata_diagnostics=tuple(diagnostics),
        request_count=request_count,
        identity_verdict=False,
        network_accessed=True,
    )


def write_discovery_bundle_r2(
    result: SpotV2DiscoveryR2Result,
    *,
    user_approval_text: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    _require(DISCOVERY_PLAN_PATH.is_file(), "r2 plan file is missing")
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
    _require(not request_plan_path.exists(), "r2 discovery output already exists")
    request_plan = list(result.request_plan)
    request_plan_hash = hashlib.sha256(canonical_json_bytes(request_plan)).hexdigest()
    manifest = {
        "schema": "trading_mvp_slow_liquidity_spot_v2_official_page_discovery_output_r2",
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
        "metadata_diagnostics": list(result.metadata_diagnostics),
        "request_plan_sha256": request_plan_hash,
        "retry_authorized": False,
        "parent_retry": False,
        "v7_used": False,
        "perp_template_used": False,
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
            "schema": "trading_mvp_slow_liquidity_spot_v2_discovery_r2_approval_receipt_v1",
            "status": "APPROVED_SINGLE_USE_VISIBLE_DISCOVERY",
            "user_approval_text": expected,
            "plan_id": PLAN_ID,
            "plan_hash": plan["plan_hash"],
            "plan_file_sha256": _sha256_file(DISCOVERY_PLAN_PATH),
            "output_manifest_path": str(manifest_path),
            "request_plan_path": str(request_plan_path),
            "request_plan_sha256": request_plan_hash,
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
        path = write_spot_v2_official_page_discovery_plan_r2(generated)
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
    print("SPOT_V2_R2_DISCOVERY_START", flush=True)
    try:
        result = discover_spot_v2_official_pages_r2(
            plan,
            user_approval_text=approval,
        )
    except SpotV2OfficialPageDiscoveryR2Error:
        result = SpotV2DiscoveryR2Result(
            status="SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE",
            request_plan=(),
            unresolved_pairs=("RUN:DISCOVERY_CONTRACT_REJECTED",),
            metadata_diagnostics=(),
            request_count=0,
            identity_verdict=False,
            network_accessed=True,
        )
    generated = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    written = write_discovery_bundle_r2(
        result,
        user_approval_text=approval,
        generated_at_utc=generated,
    )
    print(json.dumps(written, ensure_ascii=False), flush=True)
    print("SPOT_V2_R2_DISCOVERY_DONE", written["status"], flush=True)
    return 0 if result.status.endswith("COMPLETE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
