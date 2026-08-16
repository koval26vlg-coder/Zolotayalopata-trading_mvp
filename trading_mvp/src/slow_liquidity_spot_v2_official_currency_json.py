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

from slow_liquidity_official_identity_proposal import (
    COLLISION_FAIL_CLOSED_BASES,
    EXPECTED_BASES,
    PROPOSAL_ID,
)
from slow_liquidity_official_identity_verification import (
    FetchedResponse,
    IdentityVerificationError,
    _strict_json_loads,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    BINDINGS_FILE_SHA256,
    BINDINGS_PLAN_HASH,
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


SCHEMA = "trading_mvp_slow_liquidity_spot_v2_official_currency_json_planonly_v1"
PLAN_ID = "slow_liquidity_spot_v2_official_currency_json_20260815"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-official-currency-json-planonly-20260815.json"
)
PARENT_R4_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-official-page-discovery-planonly-20260815-r4.json"
)
PARENT_R4_PLAN_ID = "slow_liquidity_spot_v2_official_page_discovery_20260815_r4"
PARENT_R4_PLAN_HASH = (
    "2f8cb14b747e582c54b1749a5ff2f5955774b427d2792d31b3853af9c3cd5de9"
)
PARENT_R4_PLAN_FILE_SHA256 = (
    "05187e3be802a5f2d53d00866f342c1a3f4a0c9d29f70932831ec16973203cce"
)
PARENT_R4_MANIFEST_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-page-discovery"
    r"\slow_liquidity_spot_v2_official_page_discovery_20260815_r4\manifest.json"
)
PARENT_R4_MANIFEST_SHA256 = (
    "1e602cff2f97e34f169965b7c7f86459a547a1698a7e270c895a63a542fa825f"
)
GATE_CURRENCY_URL_PREFIX = "https://api.gateio.ws/api/v4/spot/currencies/"
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
EVM_ADDR = re.compile(r"^0[xX][0-9a-fA-F]{40}$")
SEED_FIELDS = {"base_ticker", "currency_url", "collision_fail_closed"}
OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-spot-v2-official-currency-json"
    r"\slow_liquidity_spot_v2_official_currency_json_20260815"
)
APPROVAL_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/"
    "2026-08-15-slow-liquidity-spot-v2-official-currency-json-approval.json"
)
EXPECTED_APPROVAL_TEXT = (
    "Разрешаю один видимый public read-only запуск "
    "slow_liquidity_spot_v2_official_currency_json_20260815 через "
    "tools\\start_exact_approved_slow_liquidity_spot_v2_official_currency_"
    "json_visible.ps1 по plan_hash=<PLAN_HASH> и "
    "plan_file_sha256=<PLAN_FILE_SHA256>: официальный Gate GET "
    "/spot/currencies/BASE без ключа, не страницы, не Bing, не sitemap, "
    "не повтор r1-r4. MEXC unsigned contract JSON в public spot docs нет. "
    "EDGE и RAIN fail-closed. Это не identity verdict и не HTML request plan. "
    "Не v7. STOPPED_INCOMPLETE не повторять. Без evaluator, OOS, returns/PnL, "
    "grid/retune, execution probe, paper/live, private API, реальных денег, "
    "плеча или маржи."
)


class SpotV2OfficialCurrencyJsonError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2OfficialCurrencyJsonError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _parent_r4_manifest_sha256() -> str:
    if PARENT_R4_MANIFEST_PATH.is_file():
        return _sha256_file(PARENT_R4_MANIFEST_PATH)
    return PARENT_R4_MANIFEST_SHA256


def _seed_items() -> list[dict[str, Any]]:
    return [
        {
            "base_ticker": base,
            "currency_url": f"{GATE_CURRENCY_URL_PREFIX}{base}",
            "collision_fail_closed": base in COLLISION_FAIL_CLOSED_BASES,
        }
        for base in EXPECTED_BASES
    ]


def build_spot_v2_official_currency_json_plan(generated_at_utc: str) -> dict[str, Any]:
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
    if PARENT_R4_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_R4_PLAN_PATH) == PARENT_R4_PLAN_FILE_SHA256,
            "parent r4 plan file hash mismatch",
        )
    manifest_sha = (
        _sha256_file(PARENT_R4_MANIFEST_PATH)
        if PARENT_R4_MANIFEST_PATH.is_file()
        else PARENT_R4_MANIFEST_SHA256
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_DISCOVERY_APPROVAL",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_verdict_allowed": False,
        "network_authorized": False,
        "execution_authorized": False,
        "consumer_runtime": PROPOSAL_ID,
        "market": "SPOT_USDT",
        "evidence_class": "OFFICIAL_PUBLIC_REST_CURRENCY_JSON",
        "not_html_official_page_request_plan": True,
        "collision_fail_closed_bases": list(COLLISION_FAIL_CLOSED_BASES),
        "collision_ambiguity_disposition": "REJECT_EXCLUDE_FAIL_CLOSED",
        "goal": (
            "Collect official public Gate currency JSON token addresses for the "
            "9 collected spot bases. This is not another page/sitemap/Bing run "
            "and not an identity verdict."
        ),
        "parent_discovery": {
            "plan_id": PARENT_R4_PLAN_ID,
            "plan_path": str(PARENT_R4_PLAN_PATH),
            "plan_hash": PARENT_R4_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_R4_PLAN_FILE_SHA256,
            "manifest_path": str(PARENT_R4_MANIFEST_PATH),
            "manifest_sha256": manifest_sha,
            "status": "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE",
            "retry_of_parent_forbidden": True,
            "reason": (
                "r4 news locators had 1839 locs and 1000 titles but zero ticker "
                "matches. Another HTML page locator is not useful."
            ),
        },
        "mexc_public_contract_json": {
            "documented_unsigned_endpoint": False,
            "capital_config_getall_requires_api_key": True,
            "invented_undocumented_endpoint_forbidden": True,
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
        "official_json_contract": {
            "provider": "GATE_APIV4_SPOT_CURRENCY",
            "method": "GET",
            "auth_required": False,
            "url_prefix": GATE_CURRENCY_URL_PREFIX,
            "docs": "https://www.gate.com/docs/developers/apiv4/en/",
            "token_address_field": "chains[].addr",
            "chain_name_field": "chains[].name",
            "redirect_following_allowed": False,
            "raw_response_persistence_allowed": False,
        },
        "limits": {
            "maximum_total_http_requests": 18,
            "maximum_attempts_per_url": 2,
            "maximum_response_bytes_per_request": 1_000_000,
            "max_runtime_sec": 300,
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
            "one_visible_public_read_only_gate_currency_json": True,
            "html_official_page_discovery": False,
            "identity_verdict": False,
            "parent_retry": False,
            "evaluator_or_oos": False,
            "paper_or_live": False,
            "private_api": False,
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
    validate_spot_v2_official_currency_json_plan(plan)
    return plan


def validate_spot_v2_official_currency_json_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "currency json schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "currency json plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("evidence_class") == "OFFICIAL_PUBLIC_REST_CURRENCY_JSON",
        "evidence class mismatch",
    )
    _require(plan.get("identity_verdict_allowed") is False, "identity verdict already allowed")
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_discovery") or {}
    _require(parent.get("retry_of_parent_forbidden") is True, "r4 retry not forbidden")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_R4_PLAN_FILE_SHA256,
        "parent r4 hash mismatch",
    )
    mexc = plan.get("mexc_public_contract_json") or {}
    _require(mexc.get("documented_unsigned_endpoint") is False, "mexc unsigned flag")
    seeds = plan.get("seed_items")
    _require(isinstance(seeds, list) and len(seeds) == 9, "seed count")
    for item in seeds:
        _require(set(item) == SEED_FIELDS, "seed fields changed")
        _require(
            str(item["currency_url"]).startswith(GATE_CURRENCY_URL_PREFIX),
            "currency url prefix",
        )


def write_spot_v2_official_currency_json_plan(generated_at_utc: str) -> Path:
    plan = build_spot_v2_official_currency_json_plan(generated_at_utc)
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
class SpotV2CurrencyJsonResult:
    status: str
    gate_records: tuple[dict[str, Any], ...]
    unresolved: tuple[str, ...]
    request_count: int
    identity_verdict: bool
    network_accessed: bool


def collect_spot_v2_official_currency_json(
    plan: Mapping[str, Any],
    *,
    user_approval_text: str,
    fetch: Callable[[str], FetchedResponse] = fetch_public_discovery_response,
    monotonic: Callable[[], float] = time.monotonic,
) -> SpotV2CurrencyJsonResult:
    validate_spot_v2_official_currency_json_plan(plan)
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
        _require(monotonic() - started <= 300, "runtime cap exceeded")
        _require(request_count < 18, "HTTP request cap exceeded")
        requests_by_url[url] = requests_by_url.get(url, 0) + 1
        _require(requests_by_url[url] <= 2, "attempt cap per URL exceeded")
        request_count += 1
        try:
            response = fetch(url)
        except IdentityVerificationError as exc:
            raise SpotV2OfficialCurrencyJsonError(str(exc)) from exc
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
        collision = bool(item["collision_fail_closed"])
        try:
            payload = _strict_json_loads(fetch_counted(str(item["currency_url"])).decode("utf-8"))
            if not isinstance(payload, dict):
                raise SpotV2OfficialCurrencyJsonError("currency payload is not an object")
            addr = _unique_evm_addr(payload)
        except (SpotV2OfficialCurrencyJsonError, UnicodeDecodeError, ValueError):
            unresolved.append(
                f"{base}:AMBIGUOUS_KNOWN_TICKER_COLLISION"
                if collision
                else f"{base}:CURRENCY_JSON_UNREADABLE"
            )
            continue
        if collision:
            unresolved.append(f"{base}:AMBIGUOUS_KNOWN_TICKER_COLLISION")
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
            }
        )
        print(
            f"SPOT_V2_CURRENCY_JSON_PROGRESS base={base} "
            f"records={len(records)} unresolved={len(unresolved)} "
            f"requests={request_count}",
            flush=True,
        )

    return SpotV2CurrencyJsonResult(
        status="SPOT_V2_OFFICIAL_CURRENCY_JSON_INCOMPLETE",
        gate_records=tuple(records),
        unresolved=tuple(unresolved),
        request_count=request_count,
        identity_verdict=False,
        network_accessed=True,
    )


def write_currency_json_bundle(
    result: SpotV2CurrencyJsonResult,
    *,
    user_approval_text: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    _require(DISCOVERY_PLAN_PATH.is_file(), "currency json plan file is missing")
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
    records_path = OUTPUT_ROOT / "gate-currency-records.json"
    manifest_path = OUTPUT_ROOT / "manifest.json"
    _require(not records_path.exists(), "currency json output already exists")
    records = list(result.gate_records)
    records_hash = hashlib.sha256(canonical_json_bytes(records)).hexdigest()
    manifest = {
        "schema": "trading_mvp_slow_liquidity_spot_v2_official_currency_json_output_v1",
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
        "retry_authorized": False,
        "parent_retry": False,
        "v7_used": False,
        "bing_used": False,
        "page_locator_used": False,
        "mexc_json_used": False,
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
            "schema": "trading_mvp_slow_liquidity_spot_v2_currency_json_approval_receipt_v1",
            "status": "APPROVED_SINGLE_USE_VISIBLE_CURRENCY_JSON",
            "user_approval_text": expected,
            "plan_id": PLAN_ID,
            "plan_hash": plan["plan_hash"],
            "plan_file_sha256": _sha256_file(DISCOVERY_PLAN_PATH),
            "identity_verdict": False,
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
        path = write_spot_v2_official_currency_json_plan(generated)
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
    print("SPOT_V2_CURRENCY_JSON_START", flush=True)
    result = collect_spot_v2_official_currency_json(plan, user_approval_text=approval)
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
    print("SPOT_V2_CURRENCY_JSON_DONE", written["status"], flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
