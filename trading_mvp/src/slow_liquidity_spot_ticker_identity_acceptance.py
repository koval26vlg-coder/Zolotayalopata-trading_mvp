from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from slow_liquidity_listing_momentum_scope import (
    V6_QUALITY_FILE_SHA256,
    V6_QUALITY_PATH,
)
from slow_liquidity_official_identity_proposal import (
    COLLISION_FAIL_CLOSED_BASES,
    EXPECTED_BASES,
    EXPECTED_VENUES,
)
from slow_liquidity_spot_v2_official_page_discovery import (
    canonical_hash,
    canonical_json_bytes,
)


SCHEMA = "trading_mvp_slow_liquidity_spot_ticker_identity_acceptance_planonly_v1"
PLAN_ID = "slow_liquidity_spot_ticker_identity_acceptance_20260816"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"
IDENTITY_CLASS = "SPOT_TICKER_MATCH_BOTH_VENUES_COLLECTED"
REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs/plans"
    / "slow-liquidity-spot-ticker-identity-acceptance-planonly-20260816.json"
)
RECEIPT_SCHEMA = "trading_mvp_slow_liquidity_spot_ticker_identity_acceptance_receipt_v1"
RECEIPT_STATUS = "SPOT_TICKER_IDENTITY_ACCEPTED"
RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-spot-ticker-identity-acceptance-approval.json"
)
VERDICT_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_spot_ticker_identity_verdict_20260816.json"
)
QUALITY_REBIND_PATH = (
    REPO_ROOT
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_history_recollect_quality_v6_identity_accepted_rebind.json"
)
REBOUND_QUALITY_DECISION = (
    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_IDENTITY_ACCEPTED_"
    "READY_FOR_FIXED_SIGNAL_PLANONLY"
)
EXPECTED_USER_DECISION_TEXT = (
    "Принять спот-тикер identity (аналог proxy-дат) — разблокирует "
    "fixed-signal → replay исходной slow-liquidity гипотезы на готовых данных;"
)
EXPECTED_APPROVAL_TEXT = (
    "Принимаю PlanOnly slow_liquidity_spot_ticker_identity_acceptance_20260816 "
    "по plan_hash=<PLAN_HASH> и plan_file_sha256=<PLAN_FILE_SHA256>: принять "
    "спот-тикер identity (аналог proxy-дат) — identity = совпадающий спот-"
    "тикер на обоих venue, свидетельство = собранные v6 clean two-venue 1h4h "
    "данные; EDGE и RAIN fail-closed исключены; разблокирует fixed-signal → "
    "replay исходной slow-liquidity гипотезы на готовых данных; не canonical "
    "asset claim, не official identity, не private API, не grid/retune, не "
    "paper/live, не реальные деньги, плечо или маржа."
)


class SpotTickerIdentityAcceptanceError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise SpotTickerIdentityAcceptanceError(message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_v6_quality() -> dict[str, Any]:
    _require(V6_QUALITY_PATH.is_file(), "v6 quality artifact missing")
    _require(
        _sha256_file(V6_QUALITY_PATH) == V6_QUALITY_FILE_SHA256,
        "v6 quality hash mismatch",
    )
    quality = json.loads(V6_QUALITY_PATH.read_text(encoding="utf-8"))
    _require(quality.get("accepted") is True, "v6 quality not accepted")
    clean = quality.get("clean_markets") or {}
    bases = sorted(str(base) for base in clean.get("two_exchange_bases") or [])
    full = sorted(
        str(base) for base in clean.get("two_exchange_full_coverage_1h4h_bases") or []
    )
    _require(bases == sorted(EXPECTED_BASES), "v6 two-exchange bases changed")
    _require(full == sorted(EXPECTED_BASES), "v6 full-coverage bases changed")
    return quality


def compute_identity_verdict(quality: Mapping[str, Any]) -> dict[str, Any]:
    clean = quality.get("clean_markets") or {}
    bases = sorted(str(base) for base in clean.get("two_exchange_bases") or [])
    full = set(str(base) for base in clean.get("two_exchange_full_coverage_1h4h_bases") or [])
    collision = set(COLLISION_FAIL_CLOSED_BASES)
    accepted = sorted(base for base in bases if base in full and base not in collision)
    excluded = sorted(
        (
            {"base": base, "reason": "COLLISION_FAIL_CLOSED_TICKER"}
            for base in bases
            if base in collision
        ),
        key=lambda entry: entry["base"],
    )
    _require(len(accepted) + len(excluded) == len(bases), "verdict partition mismatch")
    _require(len(accepted) == 7, "expected 7 identity-accepted bases")
    return {
        "identity_class": IDENTITY_CLASS,
        "rule": (
            "same base ticker string collected as clean 1h4h spot USDT history "
            "on both MEXC and Gate in the exact v6 recollect"
        ),
        "evidence_source": {
            "kind": "v6 exact recollect clean two-venue full-coverage 1h4h bases",
            "quality_path": str(V6_QUALITY_PATH),
            "quality_file_sha256": V6_QUALITY_FILE_SHA256,
        },
        "accepted_bases": accepted,
        "accepted_base_count": len(accepted),
        "excluded_bases": excluded,
        "excluded_base_count": len(excluded),
        "venues": list(EXPECTED_VENUES),
        "market": "SPOT_USDT",
    }


def build_identity_acceptance_plan(generated_at_utc: str) -> dict[str, Any]:
    quality = load_v6_quality()
    verdict = compute_identity_verdict(quality)
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "AWAIT_SPOT_TICKER_IDENTITY_ACCEPTANCE_RECEIPT",
        "prepared_checkpoint": "ACCEPT_SPOT_TICKER_IDENTITY_USER_CONTRACT_DECISION",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "network_authorized": False,
        "private_api": False,
        "execution_authorized": False,
        "replay_allowed": False,
        "identity_verdict_authorized": False,
        "quality_decision_rebind_authorized": False,
        "official_identity_claim": False,
        "user_decision_text_expected": EXPECTED_USER_DECISION_TEXT,
        "goal": (
            "Accept spot-ticker identity for the closed v6 nine so the "
            "original slow-liquidity hypothesis can proceed to fixed-signal "
            "and replay on the already-collected data. This is a user "
            "contract decision analogous to the proxy listing-date "
            "acceptance; it is NOT a canonical-asset or official identity "
            "claim."
        ),
        "identity_contract": {
            "identity_class": IDENTITY_CLASS,
            "rule": verdict["rule"],
            "evidence": verdict["evidence_source"],
            "fail_closed_bases": list(COLLISION_FAIL_CLOSED_BASES),
            "accepted_bases": verdict["accepted_bases"],
            "excluded_bases": verdict["excluded_bases"],
        },
        "unblocks": {
            "identity_verdict_materialization": True,
            "v6_quality_decision_rebind": True,
            "fixed_signal_planonly": True,
            "feature_normalizer_and_replay_via_existing_plans": True,
        },
        "limitations": [
            "SAME_TICKER_STRING_PAIRING: identity is ticker-string equality "
            "witnessed by simultaneous clean two-venue trading, not a "
            "canonical-asset verification",
            "COLLISION_FAIL_CLOSED: EDGE and RAIN are excluded from the "
            "identity verdict and from downstream primary statistics",
            "SCOPE_V6_ONLY: this acceptance binds the exact v6 recollect "
            "universe (9 bases) and does not authorize identity claims for "
            "any other universe",
            "NO_OFFICIAL_IDENTITY_CLAIM: the official two-venue identity "
            "branch remains closed as incomplete; this acceptance supersedes "
            "its blocking effect only",
        ],
        "still_forbidden": [
            "CANONICAL_ASSET_OR_OFFICIAL_IDENTITY_CLAIM",
            "REPLAY_OR_GRID_WITHOUT_SEPARATE_PLANS",
            "EVALUATOR_OR_OOS_WITHOUT_SEPARATE_PLANS",
            "PRIVATE_API",
            "PAPER_OR_LIVE",
            "REAL_CAPITAL_LEVERAGE_MARGIN",
        ],
        "v6_quality_binding": {
            "path": str(V6_QUALITY_PATH),
            "file_sha256": V6_QUALITY_FILE_SHA256,
            "decision_before": quality.get("decision"),
            "decision_after_rebind": REBOUND_QUALITY_DECISION,
        },
        "approval_request": {
            "exact_user_text_template": EXPECTED_APPROVAL_TEXT,
            "user_decision_binding": (
                "per standing policy the already-given user contract decision "
                "binds this plan via receipt without a second approval phrase"
            ),
        },
        "authorization_now": {
            "plan_freeze_allowed": True,
            "identity_verdict_allowed": False,
            "quality_decision_rebind_allowed": False,
            "replay_allowed": False,
        },
        "plan_hash_method": HASH_METHOD,
    }
    plan["plan_hash"] = canonical_hash(plan)
    validate_identity_acceptance_plan(plan)
    return plan


def validate_identity_acceptance_plan(plan: Mapping[str, Any]) -> None:
    _require(plan.get("schema") == SCHEMA, "schema mismatch")
    _require(plan.get("plan_id") == PLAN_ID, "plan id mismatch")
    _require(plan.get("mode") == "PlanOnly", "mode mismatch")
    _require(
        plan.get("status") == "AWAIT_SPOT_TICKER_IDENTITY_ACCEPTANCE_RECEIPT",
        "status mismatch",
    )
    _require(plan.get("official_identity_claim") is False, "official identity claim")
    contract = plan.get("identity_contract") or {}
    _require(
        contract.get("identity_class") == IDENTITY_CLASS, "identity class"
    )
    _require(
        sorted(contract.get("fail_closed_bases") or [])
        == sorted(COLLISION_FAIL_CLOSED_BASES),
        "fail-closed bases",
    )
    _require(
        len(contract.get("accepted_bases") or []) == 7, "accepted bases count"
    )
    _require(
        set(contract.get("accepted_bases") or []).isdisjoint(
            set(COLLISION_FAIL_CLOSED_BASES)
        ),
        "accepted bases must exclude fail-closed",
    )
    _require(plan.get("network_authorized") is False, "network authorized")
    _require(plan.get("replay_allowed") is False, "replay authorized")
    _require(
        plan.get("identity_verdict_authorized") is False,
        "verdict authorized without receipt",
    )
    auth = plan.get("authorization_now") or {}
    _require(auth.get("identity_verdict_allowed") is False, "verdict allowed")
    _require(
        auth.get("quality_decision_rebind_allowed") is False, "rebind allowed"
    )
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash mismatch")


def write_identity_acceptance_plan(generated_at_utc: str) -> Path:
    plan = build_identity_acceptance_plan(generated_at_utc)
    payload = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if PLAN_PATH.exists():
        _require(
            PLAN_PATH.read_text(encoding="utf-8") == payload,
            f"immutable artifact mismatch: {PLAN_PATH}",
        )
        return PLAN_PATH
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(payload, encoding="utf-8")
    return PLAN_PATH


def validate_acceptance_receipt(
    receipt: Mapping[str, Any], plan: Mapping[str, Any]
) -> None:
    _require(receipt.get("schema") == RECEIPT_SCHEMA, "receipt schema mismatch")
    _require(receipt.get("status") == RECEIPT_STATUS, "receipt status mismatch")
    _require(
        receipt.get("plan_hash") == plan.get("plan_hash"),
        "receipt binds a different plan hash",
    )
    _require(
        receipt.get("plan_file_sha256") == _sha256_file(PLAN_PATH),
        "receipt binds a different plan file",
    )
    _require(
        receipt.get("user_decision_text") == EXPECTED_USER_DECISION_TEXT,
        "user decision text mismatch",
    )
    scope = receipt.get("authorized_scope") or {}
    _require(scope.get("identity_verdict_materialization") is True, "verdict")
    _require(scope.get("v6_quality_decision_rebind") is True, "rebind")
    _require(
        scope.get("fixed_signal_planonly") is True, "fixed signal"
    )
    _require(scope.get("actual_network_run") is False, "network opened")
    _require(scope.get("canonical_or_official_identity_claim") is False, "claim")
    _require(scope.get("replay_direct") is False, "replay direct")
    _require(scope.get("evaluator_or_oos") is False, "evaluator")
    _require(scope.get("grid_or_retune") is False, "grid")
    _require(scope.get("paper_or_live") is False, "paper or live")
    _require(scope.get("private_api") is False, "private api")
    _require(
        receipt.get("limitations_acknowledged") is True, "limitations"
    )
    _require(
        receipt.get("receipt_hash") == _receipt_canonical_hash(receipt),
        "receipt hash mismatch",
    )


def _receipt_canonical_hash(receipt: Mapping[str, Any]) -> str:
    content = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    return hashlib.sha256(canonical_json_bytes(content)).hexdigest()


def build_verdict_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    validate_acceptance_receipt(receipt, plan)
    quality = load_v6_quality()
    verdict = compute_identity_verdict(quality)
    payload: dict[str, Any] = {
        "schema": "trading_mvp_slow_liquidity_spot_ticker_identity_verdict_v1",
        "authorized_by_receipt": {
            "status": receipt.get("status"),
            "receipt_hash": receipt.get("receipt_hash"),
            "plan_hash": plan.get("plan_hash"),
        },
        **verdict,
        "supersedes_blocking_of": {
            "decision_before": quality.get("decision"),
            "decision_after": REBOUND_QUALITY_DECISION,
        },
    }
    payload["verdict_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "verdict_hash"}
    )
    _require(
        len(payload["accepted_bases"]) == 7 and len(payload["excluded_bases"]) == 2,
        "verdict counts",
    )
    return payload


def build_quality_rebind_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    verdict = build_verdict_payload(receipt)
    quality = load_v6_quality()
    rebind: dict[str, Any] = {
        "schema": "trading_mvp_slow_liquidity_history_recollect_quality_rebind_v1",
        "source_quality_path": str(V6_QUALITY_PATH),
        "source_quality_file_sha256": V6_QUALITY_FILE_SHA256,
        "accepted": True,
        "decision": REBOUND_QUALITY_DECISION,
        "identity_acceptance": {
            "plan_hash": verdict["authorized_by_receipt"]["plan_hash"],
            "receipt_hash": verdict["authorized_by_receipt"]["receipt_hash"],
            "identity_class": verdict["identity_class"],
            "verdict_path": str(VERDICT_PATH),
            "verdict_hash": verdict["verdict_hash"],
            "accepted_bases": verdict["accepted_bases"],
            "excluded_bases": verdict["excluded_bases"],
        },
        "identity_verification_required": False,
        "identity_verification_authorized": True,
        "fixed_signal_plan_allowed": True,
        "normalizer_allowed": True,
        "replay_allowed": False,
        "evaluator_or_oos_authorized": False,
        "grid_allowed": False,
        "clean_markets": quality.get("clean_markets"),
        "warnings": quality.get("warnings"),
        "metrics": quality.get("metrics"),
        "counts": quality.get("counts"),
        "input_jsonl": quality.get("input_jsonl"),
        "manifest_path": quality.get("manifest_path"),
        "note": (
            "Deterministic rebind of the exact v6 quality packet after the "
            "user-accepted spot-ticker identity contract; original quality "
            "artifact is untouched and hash-bound above"
        ),
    }
    rebind["rebind_hash"] = canonical_hash(
        {key: value for key, value in rebind.items() if key != "rebind_hash"}
    )
    return rebind


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> Path:
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        _require(
            path.read_text(encoding="utf-8") == content,
            f"immutable artifact mismatch: {path}",
        )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-plan", action="store_true")
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--accepted-receipt", default="")
    args = parser.parse_args(argv)
    if not args.write_plan and not args.materialize:
        raise SystemExit("no authorized action requested")
    if args.write_plan:
        generated = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        path = write_identity_acceptance_plan(generated)
        plan = json.loads(path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "status": "PLAN_WRITTEN",
                    "path": str(path),
                    "plan_hash": plan["plan_hash"],
                    "plan_file_sha256": _sha256_file(path),
                    "accepted_bases": plan["identity_contract"]["accepted_bases"],
                    "fail_closed_bases": plan["identity_contract"]["fail_closed_bases"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    _require(bool(args.accepted_receipt), "materialize requires accepted receipt path")
    receipt = json.loads(Path(args.accepted_receipt).read_text(encoding="utf-8"))
    verdict = build_verdict_payload(receipt)
    _write_immutable(VERDICT_PATH, verdict)
    rebind = build_quality_rebind_payload(receipt)
    _write_immutable(QUALITY_REBIND_PATH, rebind)
    print(
        json.dumps(
            {
                "status": "MATERIALIZED",
                "verdict_path": str(VERDICT_PATH),
                "verdict_hash": verdict["verdict_hash"],
                "accepted_bases": verdict["accepted_bases"],
                "excluded_bases": [entry["base"] for entry in verdict["excluded_bases"]],
                "quality_rebind_path": str(QUALITY_REBIND_PATH),
                "rebind_decision": rebind["decision"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
