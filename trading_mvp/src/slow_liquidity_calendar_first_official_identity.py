from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_calendar_name_materialization import (
    MATERIALIZATION_PLAN_PATH as PARENT_MATERIALIZATION_PLAN_PATH,
    PLAN_ID as PARENT_MATERIALIZATION_PLAN_ID,
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


SCHEMA = "trading_mvp_slow_liquidity_calendar_first_official_identity_planonly_v1"
PLAN_ID = "slow_liquidity_calendar_first_official_identity_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-calendar-first-official-identity-planonly-20260816.json"
)
PARENT_MATERIALIZATION_PLAN_HASH = (
    "cb18a5207955f39303360d41ea4b050f1c0fba701b33869c8d478c55262f717b"
)
PARENT_MATERIALIZATION_PLAN_FILE_SHA256 = (
    "218f03872479633af8e2fcef3b3ca089567665b141f1e23c4e7a569c33dc6146"
)
PARENT_MATERIALIZATION_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-calendar-name-materialization-approval.json"
)
PARENT_MATERIALIZATION_RECEIPT_HASH = (
    "c68152870f6d46e62c9b7ee4a6f1c2beb4086c76bfd809a0e5ce945b4a242e1a"
)
PARENT_MATERIALIZATION_RECEIPT_FILE_SHA256 = (
    "1dae00601cdeb8ee2ede12ad65254047dca8ba51d472cbe64c1616aea815d004"
)
PARENT_SELECTED_BASES_SHA256 = (
    "3b5c44955f309041867763e89731f074e0a9721e0d184537d253b48fbde56322"
)
EXPECTED_SELECTED_COUNT = 407
GATE_CURRENCY_URL_PREFIX = "https://api.gateio.ws/api/v4/spot/currencies/"
GATE_DOCS_URL = "https://www.gate.com/docs/developers/apiv4/en/"
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
    "slow_liquidity_calendar_first_official_identity_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: official "
    "identity для accepted calendar-first 407 — только Gate GET "
    "/spot/currencies/BASE без ключа, MEXC unsigned JSON нет, не HTML "
    "pages, не invent URL, не identity verdict, не OHLCV. Не reopen "
    "listing-first, не reuse spot v2 consumer, не replay, не v7. Без "
    "evaluator, OOS, returns/PnL, grid/retune, paper/live, private API, "
    "реальных денег, плеча или маржи."
)


class CalendarFirstOfficialIdentityError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CalendarFirstOfficialIdentityError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _load_parent_selected_bases() -> list[str]:
    _require(PARENT_MATERIALIZATION_PLAN_PATH.is_file(), "parent materialization missing")
    _require(
        _sha256_file(PARENT_MATERIALIZATION_PLAN_PATH)
        == PARENT_MATERIALIZATION_PLAN_FILE_SHA256,
        "parent materialization plan file hash mismatch",
    )
    parent = json.loads(PARENT_MATERIALIZATION_PLAN_PATH.read_text(encoding="utf-8"))
    selected = list(parent.get("selected_bases") or [])
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "parent selected count")
    _require(
        hashlib.sha256(canonical_json_bytes(selected)).hexdigest()
        == PARENT_SELECTED_BASES_SHA256,
        "parent selected bases hash mismatch",
    )
    return selected


def build_calendar_first_official_identity_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_MATERIALIZATION_RECEIPT_PATH.is_file():
        receipt = json.loads(
            PARENT_MATERIALIZATION_RECEIPT_PATH.read_text(encoding="utf-8")
        )
        _require(
            _sha256_file(PARENT_MATERIALIZATION_RECEIPT_PATH)
            == PARENT_MATERIALIZATION_RECEIPT_FILE_SHA256,
            "parent materialization receipt file hash mismatch",
        )
        _require(
            receipt.get("receipt_hash") == PARENT_MATERIALIZATION_RECEIPT_HASH,
            "parent materialization receipt hash mismatch",
        )
        _require(
            receipt.get("status") == "ACCEPTED_CALENDAR_NAME_MATERIALIZATION_NO_IDENTITY",
            "parent names not accepted",
        )
        _require(
            receipt.get("identity_execution_authorized") is False,
            "parent already opened identity",
        )
        _require(
            receipt.get("ohlcv_collect_authorized") is False,
            "parent already opened ohlcv",
        )
    selected = _load_parent_selected_bases()
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_IDENTITY_ACCEPTANCE",
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
            "Prepare official identity for the accepted calendar-first 407 "
            "names using only documented unsigned Gate currency JSON. "
            "MEXC unsigned contract JSON is not documented. This is not an "
            "identity verdict and not OHLCV collect."
        ),
        "parent_calendar_name_materialization": {
            "plan_id": PARENT_MATERIALIZATION_PLAN_ID,
            "plan_path": str(PARENT_MATERIALIZATION_PLAN_PATH),
            "plan_hash": PARENT_MATERIALIZATION_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_MATERIALIZATION_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_MATERIALIZATION_RECEIPT_PATH),
            "receipt_hash": PARENT_MATERIALIZATION_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_MATERIALIZATION_RECEIPT_FILE_SHA256,
            "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
            "status": "ACCEPTED_CALENDAR_NAME_MATERIALIZATION_NO_IDENTITY",
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
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_execution_allowed": False,
            "identity_verdict_allowed": False,
            "ohlcv_collect_allowed": False,
            "replay_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_calendar_first_official_identity_plan(plan)
    return plan


def validate_calendar_first_official_identity_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "calendar identity schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "calendar identity plan id mismatch")
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
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_calendar_name_materialization") or {}
    _require(
        parent.get("plan_hash") == PARENT_MATERIALIZATION_PLAN_HASH,
        "parent materialization hash",
    )
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_MATERIALIZATION_PLAN_FILE_SHA256,
        "parent materialization file hash",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")


def write_calendar_first_official_identity_plan(generated_at_utc: str) -> Path:
    plan = build_calendar_first_official_identity_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if IDENTITY_PLAN_PATH.exists():
        _require(
            IDENTITY_PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {IDENTITY_PLAN_PATH}",
        )
        return IDENTITY_PLAN_PATH
    IDENTITY_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_PLAN_PATH.write_text(payload, encoding="utf-8")
    return IDENTITY_PLAN_PATH


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
    path = write_calendar_first_official_identity_plan(generated)
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


if __name__ == "__main__":
    raise SystemExit(main())
