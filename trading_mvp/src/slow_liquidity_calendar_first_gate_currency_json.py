from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_official_identity_verification import (
    FetchedResponse,
    IdentityVerificationError,
    _strict_json_loads,
)
from slow_liquidity_calendar_first_official_identity import (
    EXPECTED_SELECTED_COUNT,
    GATE_CURRENCY_URL_PREFIX,
    GATE_DOCS_URL,
    IDENTITY_PLAN_PATH as PARENT_IDENTITY_PLAN_PATH,
    PARENT_SELECTED_BASES_SHA256,
    PLAN_ID as PARENT_IDENTITY_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    canonical_hash,
    canonical_json_bytes,
    normalize_approval_text,
)
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_calendar_first_gate_currency_json_planonly_v1"
PLAN_ID = "slow_liquidity_calendar_first_gate_currency_json_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENCY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-calendar-first-gate-currency-json-planonly-20260816.json"
)
PARENT_IDENTITY_PLAN_HASH = (
    "39d92e6c20c6f8e179bb94180b8c854dd35fed6fccd9a9132d33e75ec6525625"
)
PARENT_IDENTITY_PLAN_FILE_SHA256 = (
    "e0d4c1471e3c4b578d2ddca54c7da4130d725d40eafa3db7199819e79189bc61"
)
PARENT_IDENTITY_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-calendar-first-official-identity-approval.json"
)
PARENT_IDENTITY_RECEIPT_HASH = (
    "c806716203f142526c6d4894d5ea1595ff936e547fd6847edf3a0ef1223471f2"
)
PARENT_IDENTITY_RECEIPT_FILE_SHA256 = (
    "7ac0eed65d4097ffee1b0ae06c2a9da605b2b1b5dfcfe3e094d3bb1278250882"
)
PARENT_IDENTITY_RECEIPT_STATUS = "ACCEPTED_CALENDAR_FIRST_OFFICIAL_IDENTITY_NO_NETWORK"
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
SEED_FIELDS = {"base_ticker", "currency_url"}
EVM_ADDR = re.compile(r"^0[xX][0-9a-fA-F]{40}$")
ALLOWED_FETCH_HOST = "api.gateio.ws"
OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp"
    r"\slow-liquidity-calendar-first-gate-currency-json"
    r"\slow_liquidity_calendar_first_gate_currency_json_20260816"
)
APPROVAL_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-calendar-first-gate-currency-json-approval.json"
)
EXPECTED_APPROVAL_TEXT = (
    "Разрешаю один видимый public read-only запуск "
    "slow_liquidity_calendar_first_gate_currency_json_20260816 через "
    "tools\\start_exact_approved_slow_liquidity_calendar_first_gate_"
    "currency_json_visible.ps1 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: official identity для accepted "
    "calendar-first 407 — только Gate GET /spot/currencies/BASE без ключа, "
    "MEXC unsigned JSON нет, не HTML pages, не invent URL, не identity "
    "verdict, не OHLCV. Не reopen listing-first, не reuse spot v2 consumer, "
    "не replay, не v7. STOPPED_INCOMPLETE не повторять. Без evaluator, OOS, "
    "returns/PnL, grid/retune, paper/live, private API, реальных денег, "
    "плеча или маржи."
)


class CalendarFirstGateCurrencyJsonError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CalendarFirstGateCurrencyJsonError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _load_parent_selected_bases() -> list[str]:
    _require(PARENT_IDENTITY_PLAN_PATH.is_file(), "parent identity plan missing")
    _require(
        _sha256_file(PARENT_IDENTITY_PLAN_PATH) == PARENT_IDENTITY_PLAN_FILE_SHA256,
        "parent identity plan file hash mismatch",
    )
    parent = json.loads(PARENT_IDENTITY_PLAN_PATH.read_text(encoding="utf-8"))
    _require(parent.get("plan_hash") == PARENT_IDENTITY_PLAN_HASH, "parent identity hash")
    selected = list(parent.get("selected_bases") or [])
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "parent selected count")
    _require(
        hashlib.sha256(canonical_json_bytes(selected)).hexdigest()
        == PARENT_SELECTED_BASES_SHA256,
        "parent selected bases hash mismatch",
    )
    return selected


def _seed_items(selected: list[str]) -> list[dict[str, str]]:
    return [
        {
            "base_ticker": base,
            "currency_url": f"{GATE_CURRENCY_URL_PREFIX}{base}",
        }
        for base in selected
    ]


def build_calendar_first_gate_currency_json_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_IDENTITY_RECEIPT_PATH.is_file():
        receipt = json.loads(PARENT_IDENTITY_RECEIPT_PATH.read_text(encoding="utf-8"))
        _require(
            _sha256_file(PARENT_IDENTITY_RECEIPT_PATH)
            == PARENT_IDENTITY_RECEIPT_FILE_SHA256,
            "parent identity receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_IDENTITY_RECEIPT_HASH,
            "parent identity receipt hash mismatch",
        )
        _require(
            receipt.get("status") == PARENT_IDENTITY_RECEIPT_STATUS,
            "parent identity not accepted",
        )
        _require(receipt.get("network_authorized") is False, "parent already opened network")
        _require(
            receipt.get("identity_execution_authorized") is False,
            "parent already opened identity execution",
        )
        _require(
            receipt.get("ohlcv_collect_authorized") is False,
            "parent already opened ohlcv",
        )
        _require(receipt.get("identity_verdict") is False, "parent already issued verdict")
    selected = _load_parent_selected_bases()
    seeds = _seed_items(selected)
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_CURRENCY_JSON_APPROVAL",
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
        "not_html_official_page_request_plan": True,
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_bases": selected,
        "selected_base_count": len(selected),
        "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
        "invented_ticker_count": 0,
        "evidence_class": "OFFICIAL_PUBLIC_REST_CURRENCY_JSON",
        "identity_before_ohlcv_collect": True,
        "two_venue_official_identity_complete": False,
        "goal": (
            "Collect official unsigned Gate currency JSON for the accepted "
            "calendar-first 407 names. MEXC unsigned contract JSON is not "
            "documented. This is not an identity verdict and not OHLCV collect."
        ),
        "parent_calendar_first_official_identity": {
            "plan_id": PARENT_IDENTITY_PLAN_ID,
            "plan_path": str(PARENT_IDENTITY_PLAN_PATH),
            "plan_hash": PARENT_IDENTITY_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_IDENTITY_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_IDENTITY_RECEIPT_PATH),
            "receipt_hash": PARENT_IDENTITY_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_IDENTITY_RECEIPT_FILE_SHA256,
            "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
            "status": PARENT_IDENTITY_RECEIPT_STATUS,
        },
        "mexc_public_contract_json": {
            "documented_unsigned_endpoint": False,
            "capital_config_getall_requires_api_key": True,
            "invented_undocumented_endpoint_forbidden": True,
        },
        "official_json_contract": {
            "provider": "GATE_APIV4_SPOT_CURRENCY",
            "method": "GET",
            "auth_required": False,
            "url_prefix": GATE_CURRENCY_URL_PREFIX,
            "docs": GATE_DOCS_URL,
            "token_address_field": "chains[].addr",
            "chain_name_field": "chains[].name",
            "redirect_following_allowed": False,
            "raw_response_persistence_allowed": False,
        },
        "limits": {
            "maximum_total_http_requests": EXPECTED_SELECTED_COUNT,
            "maximum_attempts_per_url": 1,
            "maximum_response_bytes_per_request": 1_000_000,
            "max_runtime_sec": 900,
            "hard_output_cap_bytes": 20_000_000,
        },
        "seed_items": seeds,
        "frozen_html_consumer_not_reused": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "reused": False,
        },
        "still_forbidden": [
            "INVENT_OFFICIAL_PAGE_URLS",
            "REOPEN_LISTING_FIRST_NAME_DISCOVERY",
            "REUSE_SPOT_V2_HTML_CONSUMER",
            "OHLCV_COLLECT",
            "IDENTITY_VERDICT",
            "RETRY_R1_R4",
            "BING_OR_SITEMAP",
            "REPLAY_OR_GRID",
            "EVALUATOR_OR_OOS",
            "PAPER_OR_LIVE",
            "20260815-V7",
        ],
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
            "text_normalization": (
                "normalize CRLF/CR to LF, then trim outer whitespace; "
                "all internal text must match exactly"
            ),
        },
        "authorized_scope_after_exact_approval": {
            "one_visible_public_read_only_gate_currency_json": True,
            "html_official_page_discovery": False,
            "identity_verdict": False,
            "ohlcv_collect": False,
            "invent_url": False,
            "reopen_listing_first_name_discovery": False,
            "spot_v2_runtime_reuse": False,
            "evaluator_or_oos": False,
            "paper_or_live": False,
            "private_api": False,
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_execution_allowed": False,
            "identity_verdict_allowed": False,
            "ohlcv_collect_allowed": False,
            "replay_allowed": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_calendar_first_gate_currency_json_plan(plan)
    return plan


def validate_calendar_first_gate_currency_json_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "calendar currency json schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "calendar currency json plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    selected = list(plan.get("selected_bases") or [])
    closed = set(EXPECTED_BASES)
    overlap = [base for base in selected if base in closed]
    _require(not overlap, f"closed base selected: {overlap}")
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "selected count")
    _require(plan.get("selected_base_count") == EXPECTED_SELECTED_COUNT, "count field")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(
        plan.get("selected_bases_sha256") == PARENT_SELECTED_BASES_SHA256,
        "selected bases hash",
    )
    _require(
        hashlib.sha256(canonical_json_bytes(selected)).hexdigest()
        == PARENT_SELECTED_BASES_SHA256,
        "selected bases content hash",
    )
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("spot_v2_runtime_reuse") is False, "spot v2 runtime reused")
    _require(
        plan.get("identity_execution_authorized") is False,
        "identity execution already authorized",
    )
    _require(
        plan.get("identity_verdict_allowed") is False,
        "identity verdict already allowed",
    )
    _require(
        plan.get("ohlcv_collect_authorized") is False,
        "ohlcv collect already authorized",
    )
    _require(
        plan.get("listing_first_name_discovery_reopened") is False,
        "listing-first reopened",
    )
    _require(plan.get("not_html_official_page_request_plan") is True, "html plan claimed")
    _require(
        plan.get("two_venue_official_identity_complete") is False,
        "two-venue identity claimed complete",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    mexc = plan.get("mexc_public_contract_json") or {}
    _require(mexc.get("documented_unsigned_endpoint") is False, "mexc unsigned claimed")
    contract = plan.get("official_json_contract") or {}
    _require(contract.get("url_prefix") == GATE_CURRENCY_URL_PREFIX, "gate prefix")
    _require(contract.get("auth_required") is False, "gate auth required")
    limits = plan.get("limits") or {}
    _require(limits.get("maximum_total_http_requests") == EXPECTED_SELECTED_COUNT, "http cap")
    _require(limits.get("maximum_attempts_per_url") == 1, "attempt cap")
    _require(limits.get("max_runtime_sec") == 900, "runtime cap")
    seeds = plan.get("seed_items")
    _require(isinstance(seeds, list) and len(seeds) == EXPECTED_SELECTED_COUNT, "seed count")
    for item, base in zip(seeds, selected, strict=True):
        _require(set(item) == SEED_FIELDS, "seed fields changed")
        _require(item.get("base_ticker") == base, "seed base mismatch")
        _require(
            item.get("currency_url") == f"{GATE_CURRENCY_URL_PREFIX}{base}",
            "currency url is not prefix+base",
        )
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_calendar_first_official_identity") or {}
    _require(parent.get("plan_hash") == PARENT_IDENTITY_PLAN_HASH, "parent identity hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_IDENTITY_PLAN_FILE_SHA256,
        "parent identity file hash",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")


def write_calendar_first_gate_currency_json_plan(generated_at_utc: str) -> Path:
    plan = build_calendar_first_gate_currency_json_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if CURRENCY_PLAN_PATH.exists():
        _require(
            CURRENCY_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {CURRENCY_PLAN_PATH}",
        )
        return CURRENCY_PLAN_PATH
    CURRENCY_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURRENCY_PLAN_PATH.write_text(payload, encoding="utf-8")
    return CURRENCY_PLAN_PATH


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        raise CalendarFirstGateCurrencyJsonError("HTTP redirect is forbidden")


def fetch_gate_currency_json(url: str, timeout_sec: float = 20.0) -> FetchedResponse:
    parsed = urllib.parse.urlsplit(url)
    _require(parsed.scheme == "https", "only HTTPS is allowed")
    _require(
        (parsed.hostname or "").lower() == ALLOWED_FETCH_HOST,
        "fetch host is not allowlisted",
    )
    _require(url.startswith(GATE_CURRENCY_URL_PREFIX), "currency url prefix")
    _require(not parsed.query and not parsed.fragment, "query/fragment forbidden")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "trading-mvp-calendar-first-gate-currency-json/1.0",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            body = response.read(1_000_001)
            final_url = response.geturl()
            status = int(response.status)
    except CalendarFirstGateCurrencyJsonError:
        raise
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise CalendarFirstGateCurrencyJsonError("HTTP redirect is forbidden") from exc
        raise CalendarFirstGateCurrencyJsonError(f"HTTP {exc.code} for {url}") from exc
    except Exception as exc:
        raise CalendarFirstGateCurrencyJsonError(f"fetch failed for {url}") from exc
    return FetchedResponse(url, final_url, status, body)


def _unique_evm_addr(payload: Mapping[str, Any]) -> str | None:
    chains = payload.get("chains")
    if not isinstance(chains, list):
        return None
    found: set[str] = set()
    for row in chains:
        if not isinstance(row, dict):
            continue
        addr = str(row.get("addr") or "").strip()
        if EVM_ADDR.fullmatch(addr):
            found.add(addr.lower())
    if len(found) == 1:
        return next(iter(found))
    return None


@dataclass(frozen=True)
class CalendarFirstGateCurrencyJsonResult:
    status: str
    gate_records: tuple[dict[str, Any], ...]
    unresolved: tuple[str, ...]
    request_count: int
    identity_verdict: bool
    network_accessed: bool


def collect_calendar_first_gate_currency_json(
    plan: Mapping[str, Any],
    *,
    user_approval_text: str,
    fetch: Callable[[str], FetchedResponse] = fetch_gate_currency_json,
    monotonic: Callable[[], float] = time.monotonic,
) -> CalendarFirstGateCurrencyJsonResult:
    validate_calendar_first_gate_currency_json_plan(plan)
    allowed = {EXPECTED_APPROVAL_TEXT}
    if CURRENCY_PLAN_PATH.is_file():
        frozen = json.loads(CURRENCY_PLAN_PATH.read_text(encoding="utf-8"))
        allowed.add(
            fill_expected_approval_text(
                str(frozen["plan_hash"]),
                _sha256_file(CURRENCY_PLAN_PATH),
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
        _require(monotonic() - started <= 900, "runtime cap exceeded")
        _require(request_count < EXPECTED_SELECTED_COUNT, "HTTP request cap exceeded")
        requests_by_url[url] = requests_by_url.get(url, 0) + 1
        _require(requests_by_url[url] <= 1, "attempt cap per URL exceeded")
        request_count += 1
        try:
            response = fetch(url)
        except IdentityVerificationError as exc:
            raise CalendarFirstGateCurrencyJsonError(str(exc)) from exc
        _require(isinstance(response, FetchedResponse), "invalid fetch response")
        _require(response.requested_url == url, "fetcher request URL mismatch")
        _require(response.final_url == url, "HTTP redirect is forbidden")
        _require(response.status == 200, f"HTTP {response.status} for {url}")
        _require(len(response.body) <= 1_000_000, "response exceeds cap")
        return response.body

    records: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for item in plan["seed_items"]:
        base = str(item["base_ticker"])
        try:
            payload = _strict_json_loads(fetch_counted(str(item["currency_url"])).decode("utf-8"))
            if not isinstance(payload, dict):
                raise CalendarFirstGateCurrencyJsonError("currency payload is not an object")
            addr = _unique_evm_addr(payload)
        except (CalendarFirstGateCurrencyJsonError, UnicodeDecodeError, ValueError):
            unresolved.append(f"{base}:CURRENCY_JSON_UNREADABLE")
            continue
        if not addr:
            unresolved.append(f"{base}:NOT_UNIQUE_EVM_ADDR")
            continue
        records.append(
            {
                "venue": "gateio",
                "base_ticker": base,
                "official_source_url": item["currency_url"],
                "canonical_asset_identifier_namespace": "EVM_CONTRACT",
                "canonical_asset_identifier_value": addr,
                "canonical_asset_identifier_label": "contract_address",
                "evidence_class": "OFFICIAL_PUBLIC_REST_CURRENCY_JSON",
                "mexc_record": False,
                "identity_verdict": False,
            }
        )
        print(
            f"CALENDAR_FIRST_CURRENCY_JSON_PROGRESS base={base} "
            f"records={len(records)} unresolved={len(unresolved)} "
            f"requests={request_count}",
            flush=True,
        )

    return CalendarFirstGateCurrencyJsonResult(
        status="CALENDAR_FIRST_GATE_CURRENCY_JSON_INCOMPLETE",
        gate_records=tuple(records),
        unresolved=tuple(unresolved),
        request_count=request_count,
        identity_verdict=False,
        network_accessed=True,
    )


def write_currency_json_bundle(
    result: CalendarFirstGateCurrencyJsonResult,
    *,
    user_approval_text: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    _require(CURRENCY_PLAN_PATH.is_file(), "currency json plan file is missing")
    plan = json.loads(CURRENCY_PLAN_PATH.read_text(encoding="utf-8"))
    expected = fill_expected_approval_text(
        str(plan["plan_hash"]),
        _sha256_file(CURRENCY_PLAN_PATH),
    )
    _require(
        normalize_approval_text(user_approval_text) == expected,
        "approval text mismatch",
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    records_path = OUTPUT_ROOT / "gate-currency-records.json"
    manifest_path = OUTPUT_ROOT / "manifest.json"
    _require(not records_path.exists(), "currency json output already exists")
    records = list(result.gate_records)
    records_hash = hashlib.sha256(canonical_json_bytes(records)).hexdigest()
    manifest = {
        "schema": "trading_mvp_slow_liquidity_calendar_first_gate_currency_json_output_v1",
        "status": result.status,
        "generated_at_utc": generated_at_utc,
        "plan_id": PLAN_ID,
        "plan_hash": plan["plan_hash"],
        "identity_verdict": False,
        "html_request_plan": False,
        "network_accessed": True,
        "request_count": result.request_count,
        "gate_record_count": len(records),
        "unresolved": list(result.unresolved),
        "records_sha256": records_hash,
        "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
        "retry_authorized": False,
        "parent_retry": False,
        "v7_used": False,
        "bing_used": False,
        "page_locator_used": False,
        "mexc_json_used": False,
        "spot_v2_runtime_reuse": False,
        "ohlcv_collect": False,
        "two_venue_official_identity_complete": False,
    }
    records_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if not APPROVAL_RECEIPT_PATH.exists():
        receipt = {
            "schema": "trading_mvp_slow_liquidity_calendar_first_gate_currency_json_approval_receipt_v1",
            "status": "APPROVED_SINGLE_USE_VISIBLE_CURRENCY_JSON",
            "user_approval_text": expected,
            "plan_id": PLAN_ID,
            "plan_hash": plan["plan_hash"],
            "plan_file_sha256": _sha256_file(CURRENCY_PLAN_PATH),
            "identity_verdict": False,
            "ohlcv_collect_authorized": False,
            "retry_authorized": False,
        }
        APPROVAL_RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        APPROVAL_RECEIPT_PATH.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {
        "status": result.status,
        "records_path": str(records_path),
        "manifest_path": str(manifest_path),
        "gate_record_count": len(records),
        "unresolved": list(result.unresolved),
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
        path = write_calendar_first_gate_currency_json_plan(generated)
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
                    "network_authorized": False,
                    "identity_verdict_allowed": False,
                    "ohlcv_collect_authorized": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not args.run_approved_visible_discovery:
        raise SystemExit("no authorized action requested")
    plan = json.loads(CURRENCY_PLAN_PATH.read_text(encoding="utf-8"))
    approval = args.user_approval_text or fill_expected_approval_text(
        str(plan["plan_hash"]),
        _sha256_file(CURRENCY_PLAN_PATH),
    )
    print("CALENDAR_FIRST_CURRENCY_JSON_START", flush=True)
    result = collect_calendar_first_gate_currency_json(plan, user_approval_text=approval)
    generated = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    written = write_currency_json_bundle(
        result,
        user_approval_text=approval,
        generated_at_utc=generated,
    )
    print(json.dumps(written, ensure_ascii=False), flush=True)
    print("CALENDAR_FIRST_CURRENCY_JSON_DONE", written["status"], flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
