from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import EXPECTED_BASES, EXPECTED_VENUES
from slow_liquidity_calendar_first_gate_currency_json import (
    CURRENCY_PLAN_PATH as PARENT_CURRENCY_JSON_PLAN_PATH,
    OUTPUT_ROOT as PARENT_CURRENCY_JSON_OUTPUT_ROOT,
    PARENT_SELECTED_BASES_SHA256,
    PLAN_ID as PARENT_CURRENCY_JSON_PLAN_ID,
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


SCHEMA = "trading_mvp_slow_liquidity_calendar_first_identity_gap_planonly_v1"
PLAN_ID = "slow_liquidity_calendar_first_identity_gap_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
GAP_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-calendar-first-identity-gap-planonly-20260816.json"
)
PARENT_CURRENCY_JSON_PLAN_HASH = (
    "388d81d40e866eb7ccfd93cc439c27a9c220e3f5167eb62cc92d6bbc1983f756"
)
PARENT_CURRENCY_JSON_PLAN_FILE_SHA256 = (
    "25ab519895f262f6482a5b4c1b107f1517c83eadfdda235f4d8fac0f3414e1fd"
)
PARENT_CURRENCY_JSON_MANIFEST_PATH = PARENT_CURRENCY_JSON_OUTPUT_ROOT / "manifest.json"
PARENT_CURRENCY_JSON_MANIFEST_SHA256 = (
    "c59bd647dc7b3a56a0a1f0642c2588f185b613cde8df50b36a751d43dde19b1c"
)
PARENT_CURRENCY_JSON_RECORDS_PATH = (
    PARENT_CURRENCY_JSON_OUTPUT_ROOT / "gate-currency-records.json"
)
PARENT_CURRENCY_JSON_RECORDS_SHA256 = (
    "e073a9b3d2aba7b29b3b90a0004431d33cc97ce63d8b37694fb7689ade407430"
)
PARENT_CURRENCY_JSON_RECORDS_FILE_SHA256 = (
    "0182cfe2ff2e59857a71f5cdffddbc10375aa7089918a29508d4e01cda5bee85"
)
PARENT_LAUNCH_PATH = (
    REPO_ROOT
    / "docs/agent-log/run-gates"
    / "slow_liquidity_calendar_first_gate_currency_json_20260816.launch.json"
)
PARENT_LAUNCH_FILE_SHA256 = (
    "2a421d97299c7c92ccc79bdced43b78c896ec2ce8440637267c67009e2a9f306"
)
EXPECTED_SELECTED_COUNT = 407
EXPECTED_UNIQUE_GATE_COUNT = 244
EXPECTED_UNRESOLVED_COUNT = 163
EXPECTED_NOT_UNIQUE_COUNT = 162
EXPECTED_UNREADABLE_COUNT = 1
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
    "slow_liquidity_calendar_first_identity_gap_20260816 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: Gate JSON "
    "407/244/163, two-venue official identity incomplete, MEXC unsigned JSON "
    "нет. Не identity verdict, не OHLCV, не retry currency JSON, не invent "
    "URL, не reopen listing-first, не reuse spot v2 consumer, не replay, не "
    "v7. Без evaluator, OOS, returns/PnL, grid/retune, paper/live, private "
    "API, реальных денег, плеча или маржи."
)


class CalendarFirstIdentityGapError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise CalendarFirstIdentityGapError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def _load_parent_selected_bases() -> list[str]:
    _require(PARENT_CURRENCY_JSON_PLAN_PATH.is_file(), "parent currency json plan missing")
    _require(
        _sha256_file(PARENT_CURRENCY_JSON_PLAN_PATH)
        == PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
        "parent currency json plan file hash mismatch",
    )
    parent = json.loads(PARENT_CURRENCY_JSON_PLAN_PATH.read_text(encoding="utf-8"))
    _require(
        parent.get("plan_hash") == PARENT_CURRENCY_JSON_PLAN_HASH,
        "parent currency json hash mismatch",
    )
    selected = list(parent.get("selected_bases") or [])
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "parent selected count")
    _require(
        hashlib.sha256(canonical_json_bytes(selected)).hexdigest()
        == PARENT_SELECTED_BASES_SHA256,
        "parent selected bases hash mismatch",
    )
    return selected


def _load_parent_records_and_unresolved() -> tuple[list[str], list[str]]:
    _require(PARENT_CURRENCY_JSON_RECORDS_PATH.is_file(), "parent records missing")
    _require(
        _sha256_file(PARENT_CURRENCY_JSON_RECORDS_PATH)
        == PARENT_CURRENCY_JSON_RECORDS_FILE_SHA256,
        "parent records file hash mismatch",
    )
    records = json.loads(PARENT_CURRENCY_JSON_RECORDS_PATH.read_text(encoding="utf-8"))
    _require(isinstance(records, list), "parent records not a list")
    _require(
        hashlib.sha256(canonical_json_bytes(records)).hexdigest()
        == PARENT_CURRENCY_JSON_RECORDS_SHA256,
        "parent records content hash mismatch",
    )
    unique = [str(row.get("base_ticker") or "") for row in records]
    _require(all(unique), "blank unique base")
    _require(len(unique) == EXPECTED_UNIQUE_GATE_COUNT, "unique gate count")
    unresolved: list[str] = []
    if PARENT_CURRENCY_JSON_MANIFEST_PATH.is_file():
        _require(
            _sha256_file(PARENT_CURRENCY_JSON_MANIFEST_PATH)
            == PARENT_CURRENCY_JSON_MANIFEST_SHA256,
            "parent manifest file hash mismatch",
        )
        manifest = json.loads(
            PARENT_CURRENCY_JSON_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        _require(
            manifest.get("status") == "CALENDAR_FIRST_GATE_CURRENCY_JSON_INCOMPLETE",
            "parent manifest status",
        )
        _require(manifest.get("identity_verdict") is False, "parent claimed verdict")
        _require(manifest.get("retry_authorized") is False, "parent retry authorized")
        _require(manifest.get("request_count") == EXPECTED_SELECTED_COUNT, "parent requests")
        unresolved = list(manifest.get("unresolved") or [])
    _require(len(unresolved) == EXPECTED_UNRESOLVED_COUNT, "unresolved count")
    return unique, unresolved


def build_calendar_first_identity_gap_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_LAUNCH_PATH.is_file():
        _require(
            _sha256_file(PARENT_LAUNCH_PATH) == PARENT_LAUNCH_FILE_SHA256,
            "parent launch file hash mismatch",
        )
        launch = json.loads(PARENT_LAUNCH_PATH.read_text(encoding="utf-8"))
        _require(launch.get("status") == "COMPLETE", "parent launch not complete")
        _require(launch.get("retry_authorized") is False, "parent launch retry")
        _require(launch.get("identity_verdict") is False, "parent launch verdict")
    selected = _load_parent_selected_bases()
    unique, unresolved = _load_parent_records_and_unresolved()
    not_unique = [row for row in unresolved if row.endswith(":NOT_UNIQUE_EVM_ADDR")]
    unreadable = [row for row in unresolved if row.endswith(":CURRENCY_JSON_UNREADABLE")]
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "TWO_VENUE_OFFICIAL_IDENTITY_INCOMPLETE_AWAIT_GAP_ACCEPTANCE",
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
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_bases": selected,
        "selected_base_count": len(selected),
        "selected_bases_sha256": PARENT_SELECTED_BASES_SHA256,
        "unique_gate_evm_bases": unique,
        "unique_gate_evm_base_count": len(unique),
        "unresolved": unresolved,
        "unresolved_count": len(unresolved),
        "not_unique_evm_count": len(not_unique),
        "unreadable_count": len(unreadable),
        "two_venue_verified_base_count": 0,
        "invented_ticker_count": 0,
        "evidence_class": "IDENTITY_GAP_RECORD",
        "identity_before_ohlcv_collect": True,
        "two_venue_official_identity_complete": False,
        "goal": (
            "Record that calendar-first official identity is still incomplete "
            "after the visible Gate currency JSON run: 244 unique Gate EVM "
            "addresses, 163 unresolved, and no documented unsigned MEXC JSON. "
            "This is not an identity verdict and not OHLCV collect."
        ),
        "parent_calendar_first_gate_currency_json": {
            "plan_id": PARENT_CURRENCY_JSON_PLAN_ID,
            "plan_path": str(PARENT_CURRENCY_JSON_PLAN_PATH),
            "plan_hash": PARENT_CURRENCY_JSON_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
            "manifest_path": str(PARENT_CURRENCY_JSON_MANIFEST_PATH),
            "manifest_sha256": PARENT_CURRENCY_JSON_MANIFEST_SHA256,
            "records_path": str(PARENT_CURRENCY_JSON_RECORDS_PATH),
            "records_sha256": PARENT_CURRENCY_JSON_RECORDS_SHA256,
            "records_file_sha256": PARENT_CURRENCY_JSON_RECORDS_FILE_SHA256,
            "launch_path": str(PARENT_LAUNCH_PATH),
            "launch_file_sha256": PARENT_LAUNCH_FILE_SHA256,
            "status": "CALENDAR_FIRST_GATE_CURRENCY_JSON_INCOMPLETE",
            "launch_status": "COMPLETE",
            "retry_of_parent_forbidden": True,
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
            "replay_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_calendar_first_identity_gap_plan(plan)
    return plan


def validate_calendar_first_identity_gap_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "calendar identity gap schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "calendar identity gap plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status")
        == "TWO_VENUE_OFFICIAL_IDENTITY_INCOMPLETE_AWAIT_GAP_ACCEPTANCE",
        "status mismatch",
    )
    selected = list(plan.get("selected_bases") or [])
    unique = list(plan.get("unique_gate_evm_bases") or [])
    unresolved = list(plan.get("unresolved") or [])
    closed = set(EXPECTED_BASES)
    _require(not [base for base in unique if base in closed], "closed unique base")
    _require(len(selected) == EXPECTED_SELECTED_COUNT, "selected count")
    _require(plan.get("selected_base_count") == EXPECTED_SELECTED_COUNT, "count field")
    _require(len(unique) == EXPECTED_UNIQUE_GATE_COUNT, "unique count")
    _require(plan.get("unique_gate_evm_base_count") == EXPECTED_UNIQUE_GATE_COUNT, "unique field")
    _require(len(unresolved) == EXPECTED_UNRESOLVED_COUNT, "unresolved count")
    _require(plan.get("unresolved_count") == EXPECTED_UNRESOLVED_COUNT, "unresolved field")
    _require(plan.get("not_unique_evm_count") == EXPECTED_NOT_UNIQUE_COUNT, "not unique")
    _require(plan.get("unreadable_count") == EXPECTED_UNREADABLE_COUNT, "unreadable")
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
        plan.get("two_venue_official_identity_complete") is False,
        "two-venue identity claimed complete",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    mexc = plan.get("mexc_public_contract_json") or {}
    _require(mexc.get("documented_unsigned_endpoint") is False, "mexc unsigned claimed")
    parent = plan.get("parent_calendar_first_gate_currency_json") or {}
    _require(parent.get("plan_hash") == PARENT_CURRENCY_JSON_PLAN_HASH, "parent hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
        "parent file hash",
    )
    _require(
        parent.get("records_sha256") == PARENT_CURRENCY_JSON_RECORDS_SHA256,
        "parent records hash",
    )
    _require(parent.get("retry_of_parent_forbidden") is True, "parent retry allowed")
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("ohlcv_collect_allowed") is False, "ohlcv allowed")
    _require(auth.get("retry_parent_allowed") is False, "retry allowed")
    consumer = plan.get("frozen_html_consumer_not_reused") or {}
    _require(consumer.get("reused") is False, "spot v2 consumer reused")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")


def write_calendar_first_identity_gap_plan(generated_at_utc: str) -> Path:
    plan = build_calendar_first_identity_gap_plan(generated_at_utc)
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
    path = write_calendar_first_identity_gap_plan(generated)
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
                "unique_gate_evm_base_count": plan["unique_gate_evm_base_count"],
                "unresolved_count": plan["unresolved_count"],
                "two_venue_verified_base_count": 0,
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
