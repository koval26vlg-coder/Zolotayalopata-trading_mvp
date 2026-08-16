from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import (
    COLLISION_FAIL_CLOSED_BASES,
    PROPOSAL_ID,
)
from slow_liquidity_spot_v2_official_currency_json import (
    DISCOVERY_PLAN_PATH as PARENT_CURRENCY_JSON_PLAN_PATH,
    OUTPUT_ROOT as PARENT_CURRENCY_JSON_OUTPUT_ROOT,
    PLAN_ID as PARENT_CURRENCY_JSON_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    BINDINGS_FILE_SHA256,
    BINDINGS_PLAN_HASH,
    canonical_hash,
)
from slow_liquidity_spot_v2_request_plan import (
    BINDINGS_PATH,
    PLAN_ID as BINDINGS_PLAN_ID,
    SPOT_V2_PROPOSAL_FILE_SHA256,
    SPOT_V2_PROPOSAL_HASH,
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_spot_v2_identity_gap_planonly_v1"
PLAN_ID = "slow_liquidity_spot_v2_identity_gap_20260815"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT / "docs/plans/slow-liquidity-spot-v2-identity-gap-planonly-20260815.json"
)
PARENT_CURRENCY_JSON_PLAN_HASH = (
    "b6db2d430d42728681594701e00ddeb95f302f5728e99f198daccadc930fc9fc"
)
PARENT_CURRENCY_JSON_PLAN_FILE_SHA256 = (
    "7e0820f23dd34cf8a70084193e97505650191bc2e9ed9ee3e0a4d713282d5f48"
)
PARENT_CURRENCY_JSON_MANIFEST_PATH = PARENT_CURRENCY_JSON_OUTPUT_ROOT / "manifest.json"
PARENT_CURRENCY_JSON_MANIFEST_SHA256 = (
    "34d579d26f9fc8275c8473d0d394010fb63ea18006795b5dd7983f9c634cccba"
)
PARENT_CURRENCY_JSON_RECORDS_PATH = (
    PARENT_CURRENCY_JSON_OUTPUT_ROOT / "gate-currency-records.json"
)
PARENT_CURRENCY_JSON_RECORDS_SHA256 = (
    "2068e1979c5b3e335a97a2b7287ea961fcc079b630015931902c48a6e3d65807"
)
PARENT_CURRENCY_JSON_RECORDS_FILE_SHA256 = (
    "9a9eb1768f720a8cfe277f7046a5fd31452ef25368c5fa90603b6029f7f43c37"
)
PARENT_LAUNCH_PATH = (
    REPO_ROOT
    / "docs/agent-log/run-gates"
    / "slow_liquidity_spot_v2_official_currency_json_20260815.launch.json"
)
PARENT_LAUNCH_FILE_SHA256 = (
    "cd8295d4c7924afc2b05532555ecca986c7b5432f6d3dc111d952667decbe66b"
)
UNIQUE_GATE_EVM_BASES = ("STETH", "WEETH", "OKB", "MNT")
NOT_UNIQUE_EVM_BASES = ("CC", "USDD", "BDX")
UNRESOLVED = (
    "CC:NOT_UNIQUE_EVM_ADDR",
    "RAIN:AMBIGUOUS_KNOWN_TICKER_COLLISION",
    "USDD:NOT_UNIQUE_EVM_ADDR",
    "BDX:NOT_UNIQUE_EVM_ADDR",
    "EDGE:AMBIGUOUS_KNOWN_TICKER_COLLISION",
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
    "Принимаю PlanOnly slow_liquidity_spot_v2_identity_gap_20260815 по "
    "plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: "
    "18-item official-page request plan недостижим, identity execution закрыт. "
    "Не retry currency JSON, не r5 sitemap/search/Bing, не v7. "
    "EDGE и RAIN fail-closed. Rescope universe или evidence class только "
    "отдельной новой фразой. Без evaluator, OOS, returns/PnL, grid/retune, "
    "paper/live, private API, реальных денег, плеча или маржи."
)


class SpotV2IdentityGapError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2IdentityGapError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_expected_approval_text(plan_hash: str, plan_file_sha256: str) -> str:
    return EXPECTED_APPROVAL_TEXT.replace("<PLAN_HASH>", plan_hash).replace(
        "<PLAN_FILE_SHA256>", plan_file_sha256
    )


def build_spot_v2_identity_gap_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_CURRENCY_JSON_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_CURRENCY_JSON_PLAN_PATH)
            == PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
            "parent currency json plan file hash mismatch",
        )
    if PARENT_CURRENCY_JSON_MANIFEST_PATH.is_file():
        _require(
            _sha256_file(PARENT_CURRENCY_JSON_MANIFEST_PATH)
            == PARENT_CURRENCY_JSON_MANIFEST_SHA256,
            "parent currency json manifest hash mismatch",
        )
    if PARENT_CURRENCY_JSON_RECORDS_PATH.is_file():
        _require(
            _sha256_file(PARENT_CURRENCY_JSON_RECORDS_PATH)
            == PARENT_CURRENCY_JSON_RECORDS_FILE_SHA256,
            "parent currency json records file hash mismatch",
        )
    if PARENT_LAUNCH_PATH.is_file():
        _require(
            _sha256_file(PARENT_LAUNCH_PATH) == PARENT_LAUNCH_FILE_SHA256,
            "parent currency json launch hash mismatch",
        )
    if SPOT_V2_RUNTIME_PATH.is_file():
        _require(
            _sha256_file(SPOT_V2_RUNTIME_PATH) == SPOT_V2_RUNTIME_FILE_SHA256,
            "frozen spot v2 runtime hash mismatch",
        )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "IDENTITY_UNIVERSE_UNREACHABLE_AWAIT_RESCOPE_OR_CLOSE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_verdict_allowed": False,
        "network_authorized": False,
        "execution_authorized": False,
        "html_request_plan_available": False,
        "official_page_request_plan_item_count": 0,
        "eighteen_item_official_page_plan_unreachable": True,
        "minimum_eight_two_venue_bases_unreachable": True,
        "parent_retry_forbidden": True,
        "page_locator_r5_forbidden": True,
        "consumer_runtime": PROPOSAL_ID,
        "market": "SPOT_USDT",
        "evidence_class": "IDENTITY_GAP_RECORD",
        "unique_gate_evm_bases": list(UNIQUE_GATE_EVM_BASES),
        "unique_gate_evm_base_count": len(UNIQUE_GATE_EVM_BASES),
        "two_venue_verified_base_count": 0,
        "fail_closed_bases": list(COLLISION_FAIL_CLOSED_BASES),
        "not_unique_evm_bases": list(NOT_UNIQUE_EVM_BASES),
        "unresolved": list(UNRESOLVED),
        "collision_ambiguity_disposition": "REJECT_EXCLUDE_FAIL_CLOSED",
        "goal": (
            "Record that the 9-base two-venue HTML identity universe is "
            "unreachable after r1-r4 page locators and the Gate currency JSON "
            "run. This is not a retry and not another page locator."
        ),
        "parent_currency_json": {
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
            "status": "SPOT_V2_OFFICIAL_CURRENCY_JSON_INCOMPLETE",
            "retry_of_parent_forbidden": True,
        },
        "mexc_public_contract_json": {
            "documented_unsigned_endpoint": False,
            "capital_config_getall_requires_api_key": True,
            "invented_undocumented_endpoint_forbidden": True,
        },
        "frozen_html_consumer": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "silently_edited": False,
            "required_pair_count": 18,
            "minimum_verified_bases_after_exclusions": 8,
            "mexc_path_prefix": "/support/articles/",
            "gate_path_prefix": "/announcements/article/",
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
        },
        "closed_locators": [
            "official_page_discovery_r1_full_catalog_metadata",
            "official_page_discovery_r2_bing_rss",
            "official_page_discovery_r3_support_sitemap_and_html_search",
            "official_page_discovery_r4_news_title_slug",
            "official_public_rest_currency_json",
        ],
        "unauthorized_next_actions": [
            "RETRY_CURRENCY_JSON",
            "PAGE_LOCATOR_R5",
            "BING_OR_SITEMAP_SEARCH",
            "SILENT_HTML_CONSUMER_EDIT",
            "SILENT_UNIVERSE_RESCOPE",
            "IDENTITY_EXECUTION",
        ],
        "checkpoint_options_not_authorized": [
            "CLOSE_IDENTITY_AS_UNREACHABLE",
            "RESCOPE_UNIVERSE_OR_EVIDENCE_CLASS",
            "KEEP_HTML_18_IDENTITY_CLOSED",
        ],
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
            "text_normalization": (
                "normalize CRLF/CR to LF, then trim outer whitespace; "
                "all internal text must match exactly"
            ),
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_verdict_allowed": False,
            "rescope_authorized": False,
            "exact_user_approval_required": True,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_spot_v2_identity_gap_plan(plan)
    return plan


def validate_spot_v2_identity_gap_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "identity gap schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "identity gap plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "IDENTITY_UNIVERSE_UNREACHABLE_AWAIT_RESCOPE_OR_CLOSE",
        "status mismatch",
    )
    _require(plan.get("identity_verdict_allowed") is False, "identity verdict already allowed")
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("html_request_plan_available") is False, "html request plan claimed")
    _require(plan.get("official_page_request_plan_item_count") == 0, "html items claimed")
    _require(plan.get("eighteen_item_official_page_plan_unreachable") is True, "18-item reachable")
    _require(
        plan.get("minimum_eight_two_venue_bases_unreachable") is True,
        "8 two-venue bases reachable",
    )
    _require(plan.get("parent_retry_forbidden") is True, "retry not forbidden")
    _require(plan.get("page_locator_r5_forbidden") is True, "r5 not forbidden")
    _require(plan.get("unique_gate_evm_base_count") == 4, "unique gate count")
    _require(plan.get("two_venue_verified_base_count") == 0, "two-venue count")
    _require(plan.get("unique_gate_evm_base_count") < 8, "unique count meets minimum")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_currency_json") or {}
    _require(parent.get("retry_of_parent_forbidden") is True, "parent retry not forbidden")
    _require(
        parent.get("plan_hash") == PARENT_CURRENCY_JSON_PLAN_HASH,
        "parent currency json hash mismatch",
    )
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
        "parent currency json file hash mismatch",
    )
    _require(
        parent.get("records_sha256") == PARENT_CURRENCY_JSON_RECORDS_SHA256,
        "parent records hash mismatch",
    )
    mexc = plan.get("mexc_public_contract_json") or {}
    _require(mexc.get("documented_unsigned_endpoint") is False, "mexc unsigned flag")
    auth = plan.get("authorization_now") or {}
    _require(auth.get("actual_network_run_allowed") is False, "network allowed")
    _require(auth.get("rescope_authorized") is False, "rescope already authorized")
    _require(plan.get("unique_gate_evm_bases") == list(UNIQUE_GATE_EVM_BASES), "unique bases")
    _require("RAIN" in list(plan.get("fail_closed_bases") or []), "RAIN fail-closed")
    _require("EDGE" in list(plan.get("fail_closed_bases") or []), "EDGE fail-closed")


def write_spot_v2_identity_gap_plan(generated_at_utc: str) -> Path:
    plan = build_spot_v2_identity_gap_plan(generated_at_utc)
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
    path = write_spot_v2_identity_gap_plan(generated)
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
                "identity_verdict": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
