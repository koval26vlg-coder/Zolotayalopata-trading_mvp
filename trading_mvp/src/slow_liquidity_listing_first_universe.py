from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_official_identity_proposal import (
    EXPECTED_BASES,
    EXPECTED_VENUES,
)
from slow_liquidity_spot_v2_identity_closed import (
    DISCOVERY_PLAN_PATH as PARENT_CLOSED_PLAN_PATH,
    PLAN_ID as PARENT_CLOSED_PLAN_ID,
)
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash


SCHEMA = "trading_mvp_slow_liquidity_listing_first_universe_planonly_v1"
PLAN_ID = "slow_liquidity_listing_first_universe_20260815"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_PLAN_PATH = (
    REPO_ROOT / "docs/plans/slow-liquidity-listing-first-universe-planonly-20260815.json"
)
PARENT_CLOSED_PLAN_HASH = (
    "328dbf53f2bb2191e07d8b048d313dd4a9a7dee8fc67930cb5e106a892929d28"
)
PARENT_CLOSED_PLAN_FILE_SHA256 = (
    "d3205e3e2d5d5b2cb962cc04c53501bd1d4affd07ad3bdb8a4985106f463fe40"
)
PARENT_CLOSED_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-15-slow-liquidity-spot-v2-identity-closed-unreachable-approval.json"
)
PARENT_CLOSED_RECEIPT_HASH = (
    "2807af970511f3a2f1c7e8f99be09ca426a58e1ef8e5b0c0f15180819ed06beb"
)
PARENT_CLOSED_RECEIPT_FILE_SHA256 = (
    "b16860ff38e24a14ee158c7889cbaa6b2d43bdde82638b907c4427c0cfb2d4f7"
)
MEXC_LISTING_PREFIX = "/announcements/article/"
GATE_LISTING_PREFIX = "/announcements/article/"
PREFIX_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/analysis/funding-forward"
    / "funding_forward_identity_evidence_20260810_v1.json"
)
FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS = (
    "www.bing.com",
    "sitemap.xml",
    "sitemap-index",
    "/sitemaps/",
    "sitemap-google-news",
    "sitemap-announcement",
)
USER_UNIVERSE_TEXT = "новый universe"


class SpotV2ListingFirstUniverseError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotV2ListingFirstUniverseError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_listing_first_universe_plan(generated_at_utc: str) -> dict[str, Any]:
    if PARENT_CLOSED_PLAN_PATH.is_file():
        _require(
            _sha256_file(PARENT_CLOSED_PLAN_PATH) == PARENT_CLOSED_PLAN_FILE_SHA256,
            "parent closed plan file hash mismatch",
        )
    if PARENT_CLOSED_RECEIPT_PATH.is_file():
        _require(
            _sha256_file(PARENT_CLOSED_RECEIPT_PATH) == PARENT_CLOSED_RECEIPT_FILE_SHA256,
            "parent closed receipt file hash mismatch",
        )
    prefix_evidence_sha = (
        _sha256_file(PREFIX_EVIDENCE_PATH) if PREFIX_EVIDENCE_PATH.is_file() else ""
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_EXACT_HASH_BOUND_UNIVERSE_ACCEPTANCE",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "universe_selection": "OFFICIAL_LISTING_ANNOUNCEMENT_FIRST",
        "market": "SPOT_USDT",
        "venues": list(EXPECTED_VENUES),
        "excluded_bases": list(EXPECTED_BASES),
        "selected_bases": [],
        "invented_ticker_count": 0,
        "identity_before_ohlcv_collect": True,
        "spot_v2_runtime_reuse": False,
        "identity_execution_authorized": False,
        "network_authorized": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "user_universe_text": USER_UNIVERSE_TEXT,
        "official_listing_path_prefixes": {
            "mexc": MEXC_LISTING_PREFIX,
            "gateio": GATE_LISTING_PREFIX,
        },
        "prefix_evidence": {
            "path": str(PREFIX_EVIDENCE_PATH),
            "file_sha256": prefix_evidence_sha,
            "role": "PATH_PREFIX_ONLY_NOT_SELECTED_UNIVERSE",
            "selected_asset": False,
        },
        "goal": (
            "Define a new two-venue spot universe selected from official "
            "listing announcements, excluding the closed 9 bases. Tickers "
            "are not invented here. Identity comes before OHLCV collect."
        ),
        "parent_identity_closed": {
            "plan_id": PARENT_CLOSED_PLAN_ID,
            "plan_path": str(PARENT_CLOSED_PLAN_PATH),
            "plan_hash": PARENT_CLOSED_PLAN_HASH,
            "parent_plan_file_sha256": PARENT_CLOSED_PLAN_FILE_SHA256,
            "receipt_path": str(PARENT_CLOSED_RECEIPT_PATH),
            "receipt_hash": PARENT_CLOSED_RECEIPT_HASH,
            "receipt_file_sha256": PARENT_CLOSED_RECEIPT_FILE_SHA256,
            "status": "IDENTITY_CLOSED_AS_UNREACHABLE",
        },
        "still_forbidden": [
            "REUSE_CLOSED_NINE_BASES",
            "INVENT_TICKERS",
            "REUSE_SPOT_V2_HTML_CONSUMER",
            "IDENTITY_EXECUTION",
            "OHLCV_COLLECT",
            "REPLAY_OR_GRID",
            "EVALUATOR_OR_OOS",
            "PAPER_OR_LIVE",
            "20260815-V7",
        ],
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
    validate_listing_first_universe_plan(plan)
    return plan


def validate_listing_first_universe_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "listing-first schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "listing-first plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("universe_selection") == "OFFICIAL_LISTING_ANNOUNCEMENT_FIRST",
        "universe selection mismatch",
    )
    selected = list(plan.get("selected_bases") or [])
    closed = set(EXPECTED_BASES)
    overlap = [base for base in selected if base in closed]
    _require(not overlap, f"closed base selected: {overlap}")
    _require(plan.get("selected_bases") == [], "tickers were invented")
    _require(plan.get("invented_ticker_count") == 0, "invented ticker count")
    _require(plan.get("excluded_bases") == list(EXPECTED_BASES), "excluded bases mismatch")
    _require(plan.get("identity_before_ohlcv_collect") is True, "identity-first required")
    _require(plan.get("network_authorized") is False, "network already authorized")
    _require(plan.get("replay_allowed") is False, "replay already allowed")
    _require(plan.get("spot_v2_runtime_reuse") is False, "spot v2 runtime reused")
    _require(
        plan.get("identity_execution_authorized") is False,
        "identity execution already authorized",
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")
    dumped = json.dumps(plan, ensure_ascii=False)
    dumped_lower = dumped.lower()
    for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
        _require(marker not in dumped_lower, f"live page locator leaked: {marker}")
    _require("20260815-v7" not in dumped, "v7 leaked")
    _require("{BASE}_USDT" not in dumped, "perp template leaked")
    prefixes = plan.get("official_listing_path_prefixes") or {}
    _require(prefixes.get("mexc") == MEXC_LISTING_PREFIX, "mexc listing prefix")
    _require(prefixes.get("gateio") == GATE_LISTING_PREFIX, "gate listing prefix")
    parent = plan.get("parent_identity_closed") or {}
    _require(parent.get("plan_hash") == PARENT_CLOSED_PLAN_HASH, "parent closed hash")
    _require(
        parent.get("parent_plan_file_sha256") == PARENT_CLOSED_PLAN_FILE_SHA256,
        "parent closed file hash",
    )


def write_listing_first_universe_plan(generated_at_utc: str) -> Path:
    plan = build_listing_first_universe_plan(generated_at_utc)
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
    return (
        "Принимаю PlanOnly slow_liquidity_listing_first_universe_20260815 по "
        f"plan_hash={plan_hash} и plan_file_sha256={plan_file_sha256}: "
        "новый universe — official listing announcements first, "
        "исключить закрытые 9 bases, тикеры не выдумывать, "
        "identity до OHLCV collect. Не reuse spot v2 consumer, не replay, "
        "не v7. Без evaluator, OOS, returns/PnL, grid/retune, paper/live, "
        "private API, реальных денег, плеча или маржи."
    )


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
    path = write_listing_first_universe_plan(generated)
    plan = json.loads(path.read_text(encoding="utf-8"))
    file_sha = _sha256_file(path)
    print(
        json.dumps(
            {
                "status": "PLAN_WRITTEN",
                "path": str(path),
                "plan_hash": plan["plan_hash"],
                "plan_file_sha256": file_sha,
                "exact_approval_text": fill_expected_approval_text(
                    plan["plan_hash"], file_sha
                ),
                "selected_bases": plan["selected_bases"],
                "network_authorized": False,
                "replay_allowed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
