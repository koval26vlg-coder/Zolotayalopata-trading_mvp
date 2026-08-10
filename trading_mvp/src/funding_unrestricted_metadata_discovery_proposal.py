from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
POLICY_SCHEMA = "trading_mvp_funding_asset_universe_policy_v1"
AUDIT_SCHEMA = "trading_mvp_funding_unrestricted_cache_feasibility_v1"
PROPOSAL_SCHEMA = (
    "trading_mvp_funding_unrestricted_metadata_discovery_proposal_v1"
)
AUDIT_DECISION = "CURRENT_CACHE_FIXED_HOLD_STRESS_INSUFFICIENT"
PROPOSAL_STATUS = "AWAIT_EXACT_HASH_BOUND_APPROVAL"

AUDIT_CORE_KEYS = (
    "pair_summary_sha256",
    "dataset_path",
    "manifest_sha256",
    "cost_contract_proposal_sha256",
    "cost_contract_proposal_hash",
    "universe_policy_sha256",
    "universe_policy_hash",
    "pair_summary_analysis_as_of_utc",
    "pre_oos_cutoff_utc",
    "cached_assets_analyzed",
    "oos_horizon_days",
    "minimum_assets_required",
    "normal_cycle_cost_bps",
    "stress_cycle_cost_bps",
    "stress_favorable_funding_haircut",
    "normal_positive_at_oos_horizon",
    "stress_positive_at_oos_horizon",
    "minimum_horizon_days_for_required_assets",
    "candidate_upper_bounds",
    "decision",
    "fixed_hold_planonly_allowed_from_current_cache",
    "complete_unrestricted_universe_or_longer_oos_required",
    "blocking_reasons",
)


class ProposalInputError(ValueError):
    pass


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalInputError(f"{label} could not be loaded: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProposalInputError(f"{label} must be a JSON object")
    return payload


def _verify_file_hash(path: Path, expected_sha256: str, label: str) -> str:
    expected = str(expected_sha256 or "").lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise ProposalInputError(f"{label} expected SHA-256 is invalid")
    if not path.is_file():
        raise ProposalInputError(f"{label} is missing: {path}")
    observed = _sha256_file(path)
    if observed != expected:
        raise ProposalInputError(
            f"{label} SHA-256 mismatch: expected {expected}, observed {observed}"
        )
    return observed


def _verify_embedded_hash(
    payload: dict[str, Any],
    *,
    field: str,
    label: str,
) -> str:
    expected = str(payload.get(field) or "").lower()
    if not SHA256_PATTERN.fullmatch(expected):
        raise ProposalInputError(f"{label} {field} is missing or invalid")
    canonical = dict(payload)
    canonical.pop(field, None)
    observed = _canonical_hash(canonical)
    if observed != expected:
        raise ProposalInputError(
            f"{label} {field} mismatch: expected {expected}, observed {observed}"
        )
    return observed


def _normalized_utc(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    candidate = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ProposalInputError("generated_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProposalInputError("generated_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("schema") != POLICY_SCHEMA:
        raise ProposalInputError(f"universe policy schema must be {POLICY_SCHEMA}")
    if policy.get("status") != "ACTIVE_FOR_NEW_FUNDING_PLANONLY_CONTRACTS":
        raise ProposalInputError("universe policy is not active for new funding plans")
    if policy.get("scope") != "FUNDING_STRATEGIES_ONLY":
        raise ProposalInputError("universe policy scope must be FUNDING_STRATEGIES_ONLY")

    universe = policy.get("asset_universe")
    if not isinstance(universe, dict):
        raise ProposalInputError("universe policy asset_universe is missing")
    if universe.get("mode") != "ALL_ASSETS_WITHOUT_CATEGORY_EXCLUSIONS":
        raise ProposalInputError("universe policy does not allow every asset")
    if universe.get("whitelist_required") is not False:
        raise ProposalInputError("universe policy whitelist must be disabled")
    if universe.get("blacklisted_symbols") != []:
        raise ProposalInputError("universe policy symbol blacklist must be empty")
    if universe.get("blacklisted_categories") != []:
        raise ProposalInputError("universe policy category blacklist must be empty")
    if universe.get("binance_listing_status_filter") != "NONE":
        raise ProposalInputError("universe policy Binance status filter must be NONE")
    category_filters = universe.get("category_filters")
    if not isinstance(category_filters, dict) or not category_filters:
        raise ProposalInputError("universe policy category filters are missing")
    for name, enabled in category_filters.items():
        if enabled is not False:
            raise ProposalInputError(f"universe policy category filter is enabled: {name}")

    if policy.get("current_venue_scope") != ["mexc", "gateio"]:
        raise ProposalInputError("universe policy venue scope must be mexc and gateio")
    identity = policy.get("candidate_eligibility_gates")
    if not isinstance(identity, dict):
        raise ProposalInputError("universe policy identity gates are missing")
    if identity.get("official_identity") != "EXACT_SAME_UNDERLYING_VERIFIED_PER_VENUE":
        raise ProposalInputError("universe policy official identity gate changed")
    if identity.get("ticker_text_alone_is_identity_evidence") is not False:
        raise ProposalInputError("ticker text alone may not be identity evidence")

    authorization = policy.get("authorization")
    if not isinstance(authorization, dict):
        raise ProposalInputError("universe policy authorization is missing")
    if authorization.get("candidate_discovery_on_pre_oos_data") is not True:
        raise ProposalInputError("candidate discovery is not allowed by universe policy")
    if authorization.get("official_identity_metadata_verification") is not True:
        raise ProposalInputError("official identity metadata verification is not allowed")
    if authorization.get("oos_market_value_read") is not False:
        raise ProposalInputError("universe policy must keep OOS values closed")
    if authorization.get("evaluator_or_collector_launch") is not False:
        raise ProposalInputError("universe policy must keep evaluator and collector closed")


def _validate_audit(
    audit: dict[str, Any],
    *,
    policy_file_sha256: str,
    policy_hash: str,
) -> str:
    if audit.get("schema") != AUDIT_SCHEMA:
        raise ProposalInputError(f"cache audit schema must be {AUDIT_SCHEMA}")
    if audit.get("audit_passed") is not True:
        raise ProposalInputError("cache audit did not pass")

    core = {key: audit.get(key) for key in AUDIT_CORE_KEYS}
    expected = str(audit.get("deterministic_result_hash") or "").lower()
    observed = _canonical_hash(core)
    if not SHA256_PATTERN.fullmatch(expected) or observed != expected:
        raise ProposalInputError(
            "cache audit deterministic_result_hash mismatch: "
            f"expected {expected or '<missing>'}, observed {observed}"
        )
    if audit.get("decision") != AUDIT_DECISION:
        raise ProposalInputError("cache audit is not the frozen insufficient-cache result")
    if audit.get("fixed_hold_planonly_allowed_from_current_cache") is not False:
        raise ProposalInputError("cache audit unexpectedly allows a fixed-hold PlanOnly")
    if audit.get("complete_unrestricted_universe_or_longer_oos_required") is not True:
        raise ProposalInputError("cache audit does not require a complete universe")
    if audit.get("universe_policy_sha256") != policy_file_sha256:
        raise ProposalInputError("cache audit universe policy file binding changed")
    if audit.get("universe_policy_hash") != policy_hash:
        raise ProposalInputError("cache audit universe policy hash binding changed")

    access = audit.get("data_access_audit")
    if not isinstance(access, dict):
        raise ProposalInputError("cache audit data access record is missing")
    forbidden_true = (
        "raw_market_rows_read",
        "oos_values_read",
        "returns_or_pnl_computed",
        "network_market_data_accessed",
        "collector_run",
        "evaluator_run",
        "grid_or_retune_run",
    )
    for field in forbidden_true:
        if access.get(field) is not False:
            raise ProposalInputError(f"cache audit forbidden data access is not false: {field}")
    return observed


def build_proposal(
    *,
    universe_policy_path: str | Path,
    expected_universe_policy_sha256: str,
    cache_audit_path: str | Path,
    expected_cache_audit_sha256: str,
    generated_at_utc: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd()).resolve()
    policy_path = Path(universe_policy_path).resolve()
    audit_path = Path(cache_audit_path).resolve()
    policy_file_sha256 = _verify_file_hash(
        policy_path,
        expected_universe_policy_sha256,
        "universe policy",
    )
    audit_file_sha256 = _verify_file_hash(
        audit_path,
        expected_cache_audit_sha256,
        "cache audit",
    )
    policy = _load_json(policy_path, "universe policy")
    audit = _load_json(audit_path, "cache audit")
    policy_hash = _verify_embedded_hash(
        policy,
        field="policy_hash",
        label="universe policy",
    )
    _validate_policy(policy)
    audit_result_hash = _validate_audit(
        audit,
        policy_file_sha256=policy_file_sha256,
        policy_hash=policy_hash,
    )

    proposal: dict[str, Any] = {
        "schema": PROPOSAL_SCHEMA,
        "proposal_id": "funding_unrestricted_active_perp_metadata_discovery_20260810_v1",
        "mode": "PlanOnlyMetadataDiscoveryProposal",
        "status": PROPOSAL_STATUS,
        "generated_at_utc": _normalized_utc(generated_at_utc),
        "research_only": True,
        "objective": (
            "Discover every currently active USDT-settled perpetual contract on "
            "MEXC and Gate without coin, category, top-N or Binance-status exclusions."
        ),
        "source_bindings": {
            "universe_policy": {
                "path": _display_path(policy_path, root),
                "file_sha256": policy_file_sha256,
                "policy_hash": policy_hash,
            },
            "current_cache_feasibility_audit": {
                "path": _display_path(audit_path, root),
                "file_sha256": audit_file_sha256,
                "deterministic_result_hash": audit_result_hash,
                "decision": audit["decision"],
                "cached_assets_analyzed": audit["cached_assets_analyzed"],
                "fixed_hold_planonly_allowed_from_current_cache": False,
            },
        },
        "branch_boundary": {
            "current_top_200_cache_is_complete_unrestricted_universe": False,
            "current_cache_may_support_full_universe_claim": False,
            "existing_closed_funding_branches_reopened": False,
            "holding_period_or_signal_retuned": False,
            "metadata_discovery_is_hypothesis_neutral": True,
            "oos_values_used_for_discovery_design": False,
        },
        "discovery_contract": {
            "instrument_scope": {
                "venues": ["mexc", "gateio"],
                "market": "USDT_SETTLED_LINEAR_PERPETUAL",
                "required_status": "ACTIVE_TRADING",
                "all_active_contracts_per_venue": True,
                "all_shared_ticker_candidates": True,
                "maximum_candidates": None,
            },
            "exclusion_contract": {
                "top_n_filter_allowed": False,
                "volume_rank_filter_allowed": False,
                "binance_status_filter_allowed": False,
                "asset_category_filter_allowed": False,
                "market_cap_filter_allowed": False,
                "listing_age_filter_allowed": False,
                "symbol_blacklist_allowed": False,
            },
            "endpoint_allowlist": [
                {
                    "venue": "mexc",
                    "base_url": "https://contract.mexc.com",
                    "path": "/api/v1/contract/detail",
                    "method": "GET",
                    "query_parameters_allowed": [],
                    "persisted_field_allowlist": [
                        "symbol",
                        "baseCoin",
                        "baseCoinName",
                        "quoteCoin",
                        "quoteCoinName",
                        "settleCoin",
                        "state",
                        "apiAllowed",
                    ],
                },
                {
                    "venue": "gateio",
                    "base_url": "https://api.gateio.ws",
                    "path": "/api/v4/futures/usdt/contracts",
                    "method": "GET",
                    "query_parameters_allowed": [],
                    "persisted_field_allowlist": [
                        "name",
                        "status",
                        "type",
                        "in_delisting",
                    ],
                },
            ],
            "request_limits": {
                "maximum_total_http_requests": 4,
                "maximum_attempts_per_endpoint": 2,
                "request_body_allowed": False,
                "private_or_auth_headers_allowed": False,
            },
            "response_handling": {
                "raw_response_persistence_allowed": False,
                "persist_allowlisted_contract_metadata_only": True,
                "incidental_prices_or_funding_fields_must_be_discarded": True,
                "market_values_may_affect_selection": False,
                "response_body_sha256_recorded": True,
            },
        },
        "identity_contract": {
            "ticker_intersection_allowed_for_discovery": True,
            "ticker_match_disposition": (
                "PROVISIONAL_CANDIDATE_ONLY_NOT_IDENTITY_EVIDENCE"
            ),
            "same_underlying_status_after_discovery": "UNRESOLVED_UNLESS_SEPARATELY_PROVEN",
            "official_same_underlying_evidence_required_before_strategy_planonly": True,
            "unresolved_or_conflicting_identity_disposition": "EXCLUDE_FAIL_CLOSED",
        },
        "output_contract": {
            "immutable": True,
            "overwrite_allowed": False,
            "root": (
                "E:\\ZolotyayLopata-data\\exports\\trading-mvp\\"
                "funding-unrestricted-metadata-discovery"
            ),
            "required_files": [
                "mexc-active-contracts.json",
                "gateio-active-contracts.json",
                "provisional-shared-ticker-candidates.json",
                "manifest.json",
            ],
            "raw_api_payload_files_allowed": False,
            "manifest_must_bind": [
                "proposal_hash",
                "source_policy_file_sha256",
                "source_policy_hash",
                "endpoint_urls",
                "response_body_sha256",
                "projected_output_sha256",
                "contract_counts",
                "provisional_shared_ticker_count",
                "runtime_start_and_finish_utc",
            ],
        },
        "runtime_contract": {
            "top_level_visible_launcher": (
                "tools\\start_funding_unrestricted_metadata_discovery_visible.ps1"
            ),
            "visible_terminal_required": True,
            "preflight_only_supported": True,
            "single_use": True,
            "max_runtime_sec": 300,
            "hard_output_cap_bytes": 50_000_000,
            "active_run_gate_must_not_be_running": True,
            "global_market_data_writer_must_be_absent": True,
            "global_writer_claim_required": True,
            "network_scope": "PUBLIC_CONTRACT_METADATA_ENDPOINTS_ONLY",
        },
        "implementation_after_exact_approval": {
            "runtime_module": (
                "trading_mvp\\src\\funding_unrestricted_metadata_discovery.py"
            ),
            "synthetic_tests": (
                "trading_mvp\\tests\\test_funding_unrestricted_metadata_discovery.py"
            ),
            "visible_launcher": (
                "tools\\start_funding_unrestricted_metadata_discovery_visible.ps1"
            ),
            "one_visible_metadata_run_allowed": True,
            "collector_or_evaluator_implementation_in_scope": False,
        },
        "authorization": {
            "proposal_freeze_allowed": True,
            "offline_implementation_allowed": False,
            "synthetic_tests_allowed": False,
            "actual_network_run_allowed": False,
            "market_data_collector_allowed": False,
            "funding_rates_or_prices_persisted_allowed": False,
            "oos_market_value_read_allowed": False,
            "evaluator_allowed": False,
            "returns_or_pnl_allowed": False,
            "grid_or_retune_allowed": False,
            "execution_probe_allowed": False,
            "paper_or_live_allowed": False,
            "private_api_keys_allowed": False,
            "real_capital_allowed": False,
            "leverage_or_margin_allowed": False,
            "exact_user_approval_required": True,
        },
        "next_checkpoint": {
            "after_successful_discovery": (
                "Freeze the exact identity-verified candidate set and its data requirements."
            ),
            "separate_exact_candidate_planonly_required": True,
            "separate_strategy_or_collector_launch_approval_required": True,
            "automatic_funding_collection_after_discovery": False,
            "automatic_oos_or_evaluator_after_discovery": False,
        },
        "independent_review": {
            "swarm_dry_run_completed": True,
            "independent_verdict_available": False,
            "status": "SWARM_LIMITED_NO_ACTUAL_REVIEW",
            "local_deterministic_boundary_tests_authoritative": True,
        },
        "proposal_hash_method": "sha256_canonical_json_excluding_proposal_hash",
    }
    proposal["proposal_hash"] = _canonical_hash(proposal)
    return proposal


def _write_json_immutable(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ProposalInputError(f"immutable proposal output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a fail-closed proposal for unrestricted MEXC/Gate contract "
            "metadata discovery without making network requests."
        )
    )
    parser.add_argument("--universe-policy", required=True)
    parser.add_argument("--expected-universe-policy-sha256", required=True)
    parser.add_argument("--cache-audit", required=True)
    parser.add_argument("--expected-cache-audit-sha256", required=True)
    parser.add_argument("--generated-at-utc")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.out).resolve()
    try:
        if output.exists():
            raise ProposalInputError(f"immutable proposal output already exists: {output}")
        proposal = build_proposal(
            universe_policy_path=args.universe_policy,
            expected_universe_policy_sha256=args.expected_universe_policy_sha256,
            cache_audit_path=args.cache_audit,
            expected_cache_audit_sha256=args.expected_cache_audit_sha256,
            generated_at_utc=args.generated_at_utc,
        )
        _write_json_immutable(output, proposal)
    except ProposalInputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": proposal["status"],
                "proposal_hash": proposal["proposal_hash"],
                "network_run_allowed": proposal["authorization"][
                    "actual_network_run_allowed"
                ],
                "out": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
