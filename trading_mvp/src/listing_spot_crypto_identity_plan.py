"""Declare the one probe that could make the crypto acceptance universe non-empty.

The crypto track has collected 33 windows and can accept none of them. Twenty-eight are
OKX tokenised equities, correctly excluded. The remaining five are Bitget bases nobody has
established an identity for - ALIGN, DGAI, PWT, SWARM, TMX - and until one of them is
positively established as a token, ``DECLARED_CRYPTO_TOKEN_BASES`` stays empty and every
further window inherits the same verdict. More collection does not move this; identity
does. So this plan describes the smallest thing that could: ask Bitget, about those five
bases, what networks it publishes for them.

Three properties are deliberate.

**The bases are read, not typed.** They are derived from the collected expansion state at
build time and the state file's own hash is recorded, so the plan is anchored to the
sample actually observed. A hand-written list would let the question drift from the data
without anything noticing.

**It cannot conclude anything.** The result feeds ``propose_crypto_identity``, whose
output is a proposal carrying no acceptance eligibility. Editing the declared registry
stays a human act under review, and this plan says so in a field rather than in a habit.

**It is one request per base and nothing else.** No pagination, no discovery, no
authenticated endpoint, no order placement. The bound is five requests because the
question is about five instruments; a probe that grew past its question would be a
collection nobody scoped.

Issuing this plan performs no request. Execution is a separate, separately authorised
step, which is why the status says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
import pathlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from listing_spot_crypto_identity import VENUE_EVIDENCE_HOSTS, unresolved_bases

SCHEMA = "trading_mvp_listing_spot_crypto_identity_probe_planonly_v1"
PLAN_ID = "listing_spot_crypto_identity_probe_20260827_v6"
PLAN_RELATIVE_PATH = "docs/plans/listing-spot-crypto-identity-probe-planonly-20260827-v6.json"
HASH_METHOD = "sha256_canonical_json_excluding_plan_hash"

REPO_ROOT = Path(__file__).resolve().parents[2]
# The sample the activated runtime collects into. It stopped being in this repository
# when the runtime was carved out, and the plan follows the sample rather than the other
# way round - a probe reading a state nobody writes to any more would ask a stale question
# with a straight face.
EXPANSION_RUNTIME_REPO = pathlib.Path(
    r"C:\Users\koval\Documents\ZolotyayLopata-listing-momentum-expansion"
)
EXPANSION_STATE_PATH = (
    EXPANSION_RUNTIME_REPO
    / "exports/trading-mvp/analysis"
    / "slow_liquidity_listing_momentum_forward_expansion_state_20260817.json"
)

# One venue, because one venue is where the unresolved instruments are. Widening this is
# an explicit edit and a new plan, not a parameter.
PROBE_VENUE = "bitget"

# Bitget publishes spot coin metadata, including per-chain deposit and withdrawal flags,
# on this endpoint. It is public and unauthenticated; the plan records it so that what was
# asked is fixed before anything is asked.
PROBE_ENDPOINT = "https://api.bitget.com/api/v2/spot/public/coins"

IMPLEMENTATION_ROLES = {
    "crypto_identity_proposer": "trading_mvp/src/listing_spot_crypto_identity.py",
    "spot_asset_classifier": "trading_mvp/src/listing_spot_asset_class.py",
    "equity_class_heuristic": "trading_mvp/src/listing_asset_class_heuristic.py",
    "probe_plan_generator": "trading_mvp/src/listing_spot_crypto_identity_plan.py",
    # The code that actually makes the requests. v1 bound only what interprets the
    # answer, which left the acting part unbound by the plan authorising the act.
    "probe_collector": "trading_mvp/src/listing_spot_crypto_identity_probe.py",
    # v6: the equity heuristic now reads the exchange symbol directory rather than the
    # 28 names declared by hand, so what the probe concludes depends on both the reader
    # and the snapshot it reads. Binding the reader without the snapshot would leave the
    # deciding input free to change underneath a plan that claims to fix the question.
    "equity_ticker_reference": "trading_mvp/src/listing_equity_ticker_reference.py",
    "equity_ticker_snapshot": "docs/reference/exchange-symbol-directory-20260827.json",
}

# The bound exists to stop a probe growing past its question. The question grew: the
# activated runtime found eighteen instruments nobody has an identity for, where the
# first run had five. Raised deliberately rather than removed - a bound that adjusts
# itself to whatever it finds is not a bound.
MAX_REQUESTS = 25
REQUEST_TIMEOUT_SEC = 20
MAX_RUNTIME_SEC = 120
MIN_INTERVAL_BETWEEN_REQUESTS_SEC = 1


class CryptoIdentityPlanError(ValueError):
    """The plan cannot be built or does not describe what it claims."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CryptoIdentityPlanError(message)


def canonical_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "plan_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_pairs(state_path: Path = EXPANSION_STATE_PATH) -> list[tuple[str, str]]:
    """Every venue/base the expansion sample actually contains."""
    _require(state_path.is_file(), f"expansion state missing: {state_path}")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    windows = payload.get("windows")
    _require(isinstance(windows, list) and bool(windows), "expansion state has no windows")
    pairs: list[tuple[str, str]] = []
    for window in windows:
        if not isinstance(window, Mapping):
            continue
        venue = str(window.get("exchange") or window.get("venue") or "").strip().lower()
        base = str(window.get("base") or "").strip().upper()
        if venue and base and (venue, base) not in pairs:
            pairs.append((venue, base))
    _require(bool(pairs), "expansion state names no venue/base pair")
    return pairs


def build_plan(
    *,
    generated_at_utc: str,
    repo_root: Path = REPO_ROOT,
    state_path: Path = EXPANSION_STATE_PATH,
) -> dict[str, Any]:
    pairs = observed_pairs(state_path)
    unresolved = [pair for pair in unresolved_bases(pairs) if pair[0] == PROBE_VENUE]
    _require(
        bool(unresolved),
        "no unresolved base on the probe venue; this plan would ask a question that is "
        "already answered",
    )
    bases = sorted(base for _, base in unresolved)
    _require(
        len(bases) <= MAX_REQUESTS,
        f"{len(bases)} unresolved bases exceeds the declared request bound {MAX_REQUESTS}",
    )
    hosts = sorted(VENUE_EVIDENCE_HOSTS[PROBE_VENUE])
    _require(
        PROBE_ENDPOINT.split("/")[2] in hosts,
        "the declared endpoint is not on a host the proposer will accept evidence from",
    )

    implementation = [
        {
            "role": role,
            "path": str(repo_root / relative),
            "sha256": _sha256_file(repo_root / relative),
        }
        for role, relative in sorted(IMPLEMENTATION_ROLES.items())
    ]

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": PLAN_ID,
        "mode": "PlanOnly",
        "status": "READY_FOR_ONE_BOUNDED_PUBLIC_PROBE_NOT_EXECUTED",
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "authenticated": False,
        "live_orders": False,
        "real_capital": False,
        "leverage_or_margin": False,
        "writes_market_data": False,
        "question": (
            "Does Bitget publish deposit and withdrawal on a named public network for "
            "these bases? A base that can be moved onto a public chain and back is a "
            "token in the sense this research asks about; one that cannot is an internal "
            "instrument."
        ),
        "sample_binding": {
            "state_path": str(state_path),
            "state_file_sha256": _sha256_file(state_path),
            "observed_pairs": len(pairs),
            "unresolved_on_probe_venue": len(bases),
        },
        "probe": {
            "venue": PROBE_VENUE,
            "endpoint": PROBE_ENDPOINT,
            "accepted_hosts": hosts,
            "bases": bases,
            "max_requests": MAX_REQUESTS,
            "request_timeout_sec": REQUEST_TIMEOUT_SEC,
            "max_runtime_sec": MAX_RUNTIME_SEC,
            "min_interval_between_requests_sec": MIN_INTERVAL_BETWEEN_REQUESTS_SEC,
            "pagination": False,
            "discovery": False,
        },
        "outcome_contract": {
            "produces": "crypto_identity_proposals",
            "may_edit_declared_registry": False,
            "may_accept_a_listing": False,
            "may_authorise_paper_forward": False,
            "may_authorise_live_trading": False,
            "acceptance_decision": "NONE_IDENTITY_EVIDENCE_ONLY",
            "human_review_required": True,
        },
        "implementation": {"files": implementation},
        "plan_hash_method": HASH_METHOD,
    }
    payload["plan_hash"] = canonical_hash(payload)
    return payload


def validate_plan(plan: Mapping[str, Any], *, repo_root: Path = REPO_ROOT) -> None:
    _require(plan.get("schema") == SCHEMA, "schema")
    _require(plan.get("plan_id") == PLAN_ID, "plan id")
    _require(plan.get("mode") == "PlanOnly", "mode")
    _require(plan.get("plan_hash") == canonical_hash(plan), "plan hash")
    for flag in ("private_api", "authenticated", "live_orders", "real_capital",
                 "leverage_or_margin", "writes_market_data"):
        _require(plan.get(flag) is False, f"{flag} must be False")
    for flag in ("research_only", "public_data_only"):
        _require(plan.get(flag) is True, f"{flag} must be True")
    outcome = plan.get("outcome_contract") or {}
    for flag in ("may_edit_declared_registry", "may_accept_a_listing",
                 "may_authorise_paper_forward", "may_authorise_live_trading"):
        _require(outcome.get(flag) is False, f"outcome_contract.{flag} must be False")
    _require(outcome.get("human_review_required") is True, "human review required")

    probe = plan.get("probe") or {}
    bases = probe.get("bases")
    _require(isinstance(bases, list) and bool(bases), "probe bases")
    _require(len(bases) <= MAX_REQUESTS, "probe bases exceed the request bound")
    _require(probe.get("pagination") is False and probe.get("discovery") is False,
             "the probe must stay one request per base")
    endpoint = str(probe.get("endpoint") or "")
    _require(endpoint.startswith("https://"), "probe endpoint must be https")
    _require(endpoint.split("/")[2] in (probe.get("accepted_hosts") or []),
             "probe endpoint host is not accepted by the proposer")

    rows = (plan.get("implementation") or {}).get("files") or []
    _require(bool(rows), "implementation bindings")
    for row in rows:
        path = Path(str(row.get("path")))
        _require(path.is_file(), f"implementation missing: {path}")
        _require(_sha256_file(path) == row.get("sha256"),
                 f"implementation sha256: {row.get('role')}")

    sample = plan.get("sample_binding") or {}
    state_path = Path(str(sample.get("state_path") or ""))
    _require(state_path.is_file(), "sample state missing")
    _require(_sha256_file(state_path) == sample.get("state_file_sha256"),
             "sample state sha256")


def write_plan(generated_at_utc: str, *, repo_root: Path = REPO_ROOT) -> Path:
    plan = build_plan(generated_at_utc=generated_at_utc, repo_root=repo_root)
    target = repo_root / PLAN_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if target.exists():
        _require(target.read_bytes() == raw, f"immutable plan already exists: {target}")
        return target
    with target.open("xb") as handle:
        handle.write(raw)
    _require(target.read_bytes() == raw, "immutable plan readback mismatch")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--write-plan", action="store_true")
    actions.add_argument("--plan-check", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args(argv)
    try:
        if args.plan_check:
            path = REPO_ROOT / PLAN_RELATIVE_PATH
            _require(path.is_file(), f"plan not issued: {path}")
            plan = json.loads(path.read_text(encoding="utf-8"))
            validate_plan(plan)
            print(json.dumps({"status": "PLAN_OK", "plan_id": plan["plan_id"],
                              "plan_hash": plan["plan_hash"], "execution_performed": False},
                             ensure_ascii=False))
            return 0
        stamp = args.generated_at_utc or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        path = write_plan(stamp)
        plan = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({"status": "PLAN_WRITTEN", "path": str(path),
                          "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
                          "bases": plan["probe"]["bases"], "execution_performed": False},
                         ensure_ascii=False))
        return 0
    except (CryptoIdentityPlanError, OSError, ValueError) as exc:
        print(json.dumps({"status": "PLAN_BLOCKED", "reason": str(exc),
                          "execution_performed": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
