from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import (
    COLLISION_FAIL_CLOSED_BASES,
    EXPECTED_BASES,
    EXPECTED_VENUES,
    PROPOSAL_ID,
)
from slow_liquidity_spot_v2_identity_gap import (
    DISCOVERY_PLAN_PATH as PARENT_GAP_PLAN_PATH,
    PLAN_ID as PARENT_GAP_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash
from slow_liquidity_spot_v2_request_plan import (
    SPOT_V2_RUNTIME_FILE_SHA256,
    SPOT_V2_RUNTIME_HASH,
    SPOT_V2_RUNTIME_PATH,
)


SCHEMA = "trading_mvp_slow_liquidity_spot_v2_identity_closed_planonly_v1"
PLAN_ID = "slow_liquidity_spot_v2_identity_closed_unreachable_20260815"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-spot-v2-identity-closed-unreachable-20260815.json"
)
PARENT_GAP_PLAN_HASH = (
    "df92867aa836c6a03092d49895207ffac5260674bdcbf2b1d17a3912d0b58973"
)
PARENT_GAP_PLAN_FILE_SHA256 = (
    "bdea19b374e845064513fa1261265a2922666c456ad2cb9ffaef1d02cc5c3279"
)
PARENT_GAP_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-15-slow-liquidity-spot-v2-identity-gap-approval.json"
)
PARENT_GAP_RECEIPT_HASH = (
    "c1147f7ac6703e4ee3f6f8dd03b49825de63e8c70397effee0a00f0a63f00ff8"
)
PARENT_GAP_RECEIPT_FILE_SHA256 = (
    "6ec97dbb77afdf75d59677d9ad29d20d69da86758981c3bc6f1c37aec26e2140"
)
CLOSED_PAIR_COUNT = len(EXPECTED_BASES) * len(EXPECTED_VENUES)
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
USER_CLOSE_TEXT = (
    "CLOSE_IDENTITY_AS_UNREACHABLE — закрыть identity для этих 9 two-venue bases"
)


class SpotV2IdentityClosedError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2IdentityClosedError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_spot_v2_identity_closed_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_GAP_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_GAP_PLAN_PATH) == PARENT_GAP_PLAN_FILE_SHA256,
            "parent gap plan file hash mismatch",
        )
    if PARENT_GAP_RECEIPT_PATH.is_file():
        _require(
            _sha256_file(PARENT_GAP_RECEIPT_PATH) == PARENT_GAP_RECEIPT_FILE_SHA256,
            "parent gap receipt file hash mismatch",
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
        "status": "IDENTITY_CLOSED_AS_UNREACHABLE",
        "selected_checkpoint": "CLOSE_IDENTITY_AS_UNREACHABLE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "identity_evidence": False,
        "identity_verdict_allowed": False,
        "identity_execution_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "rescope_authorized": False,
        "ohlcv_dataset_retained": True,
        "frozen_html_consumer_unchanged": True,
        "consumer_runtime": PROPOSAL_ID,
        "market": "SPOT_USDT",
        "closed_bases": list(EXPECTED_BASES),
        "closed_venues": list(EXPECTED_VENUES),
        "closed_pair_count": CLOSED_PAIR_COUNT,
        "fail_closed_bases": list(COLLISION_FAIL_CLOSED_BASES),
        "collision_ambiguity_disposition": "REJECT_EXCLUDE_FAIL_CLOSED",
        "user_close_text": USER_CLOSE_TEXT,
        "goal": (
            "Close official-identity execution for the 9 collected two-venue "
            "spot bases because the 18-item official-page request plan is "
            "unreachable. Do not retry locators, rescope, or open replay."
        ),
        "parent_identity_gap": {
            "plan_id": PARENT_GAP_PLAN_ID,
            "plan_path": str(PARENT_GAP_PLAN_PATH),
            "plan_hash": PARENT_GAP_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_GAP_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_GAP_RECEIPT_PATH),
            "receipt_hash": PARENT_GAP_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_GAP_RECEIPT_FILE_SHA256,
            "status": "ACCEPTED_IDENTITY_GAP_NO_RESCOPE",
        },
        "frozen_html_consumer": {
            "path": str(SPOT_V2_RUNTIME_PATH),
            "file_sha256": SPOT_V2_RUNTIME_FILE_SHA256,
            "manifest_hash": SPOT_V2_RUNTIME_HASH,
            "silently_edited": False,
        },
        "still_forbidden": [
            "RETRY_CURRENCY_JSON",
            "PAGE_LOCATOR_R5",
            "BING_OR_SITEMAP_SEARCH",
            "SILENT_HTML_CONSUMER_EDIT",
            "SILENT_UNIVERSE_RESCOPE",
            "IDENTITY_EXECUTION",
            "EVALUATOR_OR_OOS",
            "REPLAY_OR_GRID",
            "PAPER_OR_LIVE",
        ],
        "authorization_now": {
            "plan_freeze_allowed": True,
            "actual_network_run_allowed": False,
            "identity_verdict_allowed": False,
            "identity_execution_allowed": False,
            "replay_allowed": False,
            "rescope_authorized": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_spot_v2_identity_closed_plan(plan)
    return plan


def validate_spot_v2_identity_closed_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "identity closed schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "identity closed plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(plan.get("status") == "IDENTITY_CLOSED_AS_UNREACHABLE", "status mismatch")
    _require(
        plan.get("selected_checkpoint") == "CLOSE_IDENTITY_AS_UNREACHABLE",
        "checkpoint mismatch",
    )
    _require(plan.get("identity_verdict_allowed") is False, "identity verdict already allowed")
    _require(
        plan.get("identity_execution_authorized") is False,
        "identity execution already authorized",
    )
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("replay_allowed") is False, "replay already allowed")
    _require(plan.get("rescope_authorized") is False, "rescope already authorized")
    _require(plan.get("ohlcv_dataset_retained") is True, "ohlcv not retained")
    _require(plan.get("frozen_html_consumer_unchanged") is True, "html consumer marked changed")
    _require(plan.get("closed_bases") == list(EXPECTED_BASES), "closed bases mismatch")
    _require(plan.get("closed_venues") == list(EXPECTED_VENUES), "closed venues mismatch")
    _require(plan.get("closed_pair_count") == CLOSED_PAIR_COUNT, "closed pair count")
    _require(plan.get("closed_pair_count") == 18, "expected 18 closed pairs")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    parent = plan.get("parent_identity_gap") or {}
    _require(parent.get("plan_hash") == PARENT_GAP_PLAN_HASH, "parent gap hash mismatch")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_GAP_PLAN_FILE_SHA256,
        "parent gap file hash mismatch",
    )
    _require("RAIN" in list(plan.get("fail_closed_bases") or []), "RAIN fail-closed")
    _require("EDGE" in list(plan.get("fail_closed_bases") or []), "EDGE fail-closed")
    auth = plan.get("authorization_now") or {}
    _require(auth.get("replay_allowed") is False, "auth replay allowed")
    _require(auth.get("identity_execution_allowed") is False, "auth identity execution")


def write_spot_v2_identity_closed_plan(generated_at_utc: str) -> Path:
    plan = build_spot_v2_identity_closed_plan(generated_at_utc)
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
    path = write_spot_v2_identity_closed_plan(generated)
    plan = json.loads(path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": "PLAN_WRITTEN",
                "path": str(path),
                "plan_hash": plan["plan_hash"],
                "plan_file_sha256": _sha256_file(path),
                "selected_checkpoint": plan["selected_checkpoint"],
                "network_authorized": False,
                "replay_allowed": False,
                "identity_execution_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
