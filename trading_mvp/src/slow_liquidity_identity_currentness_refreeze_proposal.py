from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "trading_mvp_slow_liquidity_identity_currentness_refreeze_proposal_v7"
PROPOSAL_ID = "slow_liquidity_identity_currentness_refreeze_20260813_v7"
STATUS = "BLOCKED_CURRENTNESS_FEASIBILITY_UNPROVEN"
HASH_METHOD = "sha256_canonical_json_excluding_proposal_hash"
PARENT_RUN_ID = "slow_liquidity_identity_request_plan_discovery_20260813_v2"
PARENT_PLAN_FILE_SHA256 = (
    "501f42f7f418fcc07522f8df8a59db38db106cd3d2ae86cc598ffb19af34afe4"
)
PARENT_PLAN_HASH = (
    "6246471964815d139e6900298a2a78e80e830df40f0c06b39078487c254183cc"
)
PARENT_RUNTIME_FILE_SHA256 = (
    "0e2dfa6be70c289a877f9660d2ef58adca4c05276d38bfc8d99c4b8e703b250d"
)
PARENT_RUNTIME_HASH = (
    "f2cedc562660b25da6d0eac1845deb2e4ef17ba38782867ed49792f13fb392e1"
)
BASES = (
    "STETH",
    "WEETH",
    "CC",
    "OKB",
    "RAIN",
    "MNT",
    "USDD",
    "BDX",
    "EDGE",
)
VENUES = ("mexc", "gateio")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_FILE_BYTES = 5_000_000

MODULE_PATH = Path(__file__).resolve()
REPO_ROOT = MODULE_PATH.parents[2]
TESTS_PATH = (
    REPO_ROOT
    / "trading_mvp/tests/"
    "test_slow_liquidity_identity_currentness_refreeze_proposal.py"
)
GUARD_PATH = REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1"
DISCOVERY_VALIDATOR_PATH = (
    REPO_ROOT / "trading_mvp/src/slow_liquidity_identity_request_plan_discovery.py"
)
IDENTITY_VALIDATOR_PATH = (
    REPO_ROOT / "trading_mvp/src/slow_liquidity_official_identity_verification.py"
)
IDENTITY_PROPOSAL_VALIDATOR_PATH = (
    REPO_ROOT / "trading_mvp/src/slow_liquidity_official_identity_proposal.py"
)
DISCOVERY_VALIDATOR_SHA256 = (
    "bae92d9c0d0f2a1ad4b63e49b335ae44aa96aa98bd1d67f140c706111ba2024e"
)
IDENTITY_VALIDATOR_SHA256 = (
    "61961d13450235d531942f175d7dea5746ec9ab57818f2f0bf53cf311f487ec2"
)
IDENTITY_PROPOSAL_VALIDATOR_SHA256 = (
    "e0cdfb36bda5afe482efaa799a4af040366083d0715659c3a0b51cb78418c0e3"
)
PARENT_BUNDLE = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-identity-request-plan-discovery-20260813-v2"
)
PARENT_PLAN_PATH = PARENT_BUNDLE / "plan.json"
PARENT_RUNTIME_PATH = PARENT_BUNDLE / "runtime-manifest.json"
TOPOLOGY_RUN_ID = "slow_liquidity_official_currentness_topology_discovery_20260813_v1"
TOPOLOGY_URLS = (
    "https://www.mexc.com/robots.txt",
    "https://www.mexc.com/sitemap.xml",
    "https://www.mexc.com/support/articles/",
    "https://www.gate.com/robots.txt",
    "https://www.gate.com/sitemap.xml",
    "https://www.gate.com/announcements",
)
TOPOLOGY_RUNTIME_MODULE = (
    REPO_ROOT / "trading_mvp/src/slow_liquidity_official_currentness_topology.py"
)
TOPOLOGY_RUNTIME_TESTS = (
    REPO_ROOT / "trading_mvp/tests/test_slow_liquidity_official_currentness_topology.py"
)
TOPOLOGY_VISIBLE_LAUNCHER = (
    REPO_ROOT
    / "tools/start_exact_approved_slow_liquidity_official_currentness_topology_"
    "visible.ps1"
)


class ProposalError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_proposal_hash(proposal: Mapping[str, Any]) -> str:
    normalized = copy.deepcopy(dict(proposal))
    normalized.pop("proposal_hash", None)
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def _json_file_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProposalError(message)


def _require_hash(value: Any, label: str) -> str:
    _require(
        type(value) is str and HASH_PATTERN.fullmatch(value) is not None,
        f"{label} is invalid",
    )
    return value


def _validate_timestamp(value: Any, label: str) -> str:
    _require(type(value) is str and value.endswith("Z"), f"{label} must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProposalError(f"{label} is invalid") from exc
    _require(parsed.utcoffset() is not None, f"{label} must be timezone-aware")
    return value


def _sha256_file(path: Path) -> str:
    _require(path.is_file(), f"required file is missing: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProposalError(f"cannot read required file: {path}") from exc
    return digest.hexdigest()


def _read_bounded_bytes(path: Path, label: str) -> bytes:
    try:
        with path.open("rb") as handle:
            _assert_open_handle_path(handle, path)
            before = os.fstat(handle.fileno())
            raw = handle.read(MAX_JSON_FILE_BYTES + 1)
            after = os.fstat(handle.fileno())
            _assert_open_handle_path(handle, path)
    except OSError as exc:
        raise ProposalError(f"cannot read {label}") from exc
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"{label} changed while reading",
    )
    _require(len(raw) <= MAX_JSON_FILE_BYTES, f"{label} exceeds size limit")
    return raw


def _parse_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalError(f"{label} is not valid JSON") from exc
    _require(type(payload) is dict, f"{label} must be a plain JSON object")
    return payload


def _read_json(path: Path, label: str) -> tuple[str, dict[str, Any]]:
    raw = _read_bounded_bytes(path, label)
    payload = _parse_json_object(raw, label)
    return hashlib.sha256(raw).hexdigest(), payload


def _read_exact_json(
    path: Path,
    label: str,
    expected_sha256: str,
) -> tuple[str, dict[str, Any]]:
    raw = _read_bounded_bytes(path, label)
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    _require(observed_sha256 == expected_sha256, f"{label} file hash changed")
    return observed_sha256, _parse_json_object(raw, label)


def _local_path(
    path: str | Path,
    label: str,
    *,
    repo_root: Path | None = None,
) -> Path:
    raw = os.fspath(path)
    _require(type(raw) is str and raw != "", f"{label} is missing")
    _require("\x00" not in raw, f"{label} contains a null byte")
    windows_form = raw.replace("/", "\\")
    _require(
        not windows_form.startswith(("\\\\", "\\?\\", "\\.\\")),
        f"{label} remote or device path is forbidden",
    )
    candidate = Path(os.path.abspath(os.path.expanduser(raw)))
    if os.name == "nt":
        import ctypes

        drive, _ = os.path.splitdrive(str(candidate))
        _require(drive != "", f"{label} has no local drive")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
        _require(drive_type != 4, f"{label} remote drive is forbidden")
        _require(drive_type not in (0, 1), f"{label} drive type is invalid")
    is_junction = getattr(os.path, "isjunction", lambda _value: False)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        _require(
            not os.path.islink(current) and not is_junction(current),
            f"{label} reparse path is forbidden",
        )
    if repo_root is not None:
        try:
            candidate.relative_to(repo_root)
        except ValueError as exc:
            raise ProposalError(f"{label} must remain inside the repository") from exc
    return candidate


def _file_binding(path: Path) -> dict[str, str]:
    return {"path": str(path), "file_sha256": _sha256_file(path)}


def _assert_open_handle_path(handle: Any, expected_path: Path) -> None:
    expected = os.path.normcase(os.path.abspath(os.fspath(expected_path)))
    if os.name != "nt":
        observed = os.path.normcase(os.path.realpath(os.fspath(handle.name)))
        _require(observed == expected, "open file handle escaped the expected path")
        return

    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    get_final_path.restype = ctypes.c_uint32
    native_handle = msvcrt.get_osfhandle(handle.fileno())
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)
    length = get_final_path(native_handle, buffer, size, 0)
    _require(0 < length < size, "cannot resolve open file handle")
    observed = buffer.value
    _require(
        not observed.startswith("\\\\?\\UNC\\"),
        "open file handle resolved to a remote path",
    )
    if observed.startswith("\\\\?\\"):
        observed = observed[4:]
    _require(
        os.path.normcase(os.path.abspath(observed)) == expected,
        "open file handle escaped the expected path",
    )


def _target_identity_requirements() -> dict[str, Any]:
    return {
        "proof_unit": "EXACT_VENUE_INSTRUMENT_AND_CANONICAL_IDENTIFIER",
        "all_18_pairs_required": True,
        "active_metadata_snapshot_same_run_required": True,
        "metadata_snapshot_observed_at_utc_required": True,
        "metadata_http_date_header_required": True,
        "metadata_http_age_header_max_sec": 60,
        "metadata_http_date_max_clock_skew_sec": 300,
        "local_or_intermediate_cache_reuse_allowed": False,
        "metadata_response_sha256_required": True,
        "direct_metadata_to_official_page_link_required": True,
        "direct_linkage_evidence_fields_required": [
            "venue",
            "instrument_id",
            "metadata_source_url",
            "metadata_response_sha256",
            "metadata_observed_at_utc",
            "metadata_http_date_utc",
            "metadata_http_age_sec",
            "metadata_record_locator_type",
            "metadata_record_locator_value",
            "metadata_record_sha256",
            "official_page_url",
            "linkage_source_field",
            "linkage_method",
        ],
        "allowed_linkage_methods": [
            "DIRECT_OFFICIAL_METADATA_FIELD",
            "EXHAUSTIVE_OFFICIAL_EVENT_INDEX_ENTRY",
        ],
        "official_effective_timestamp_required": True,
        "exact_instrument_and_identifier_same_fragment_required": True,
        "canonical_chain_namespace_required": "CAIP_2",
        "canonical_asset_identifier_required": "CAIP_19_OR_EXACT_NATIVE_ASSET_ID",
        "asset_relation_required": True,
        "allowed_asset_relations": ["NATIVE"],
        "wrapped_or_bridged_equivalence_allowed": False,
        "complete_official_identity_event_lineage_required": True,
        "official_event_index_must_be_exhaustive_and_allowlisted": True,
        "official_index_endpoint_and_pagination_contract_required": True,
        "official_index_history_start_and_termination_proof_required": True,
        "official_identity_event_types_must_be_enumerated": True,
        "latest_effective_identity_event_must_match_identifier": True,
        "superseded_listing_or_identifier_must_not_be_accepted": True,
        "bing_result_is_currentness_evidence": False,
        "search_title_is_identity_evidence": False,
        "search_snippet_is_identity_evidence": False,
        "single_official_page_is_complete_lineage_evidence": False,
        "navigation_may_replace_direct_linkage": False,
        "missing_direct_metadata_page_link_disposition": "UNRESOLVED_FAIL_CLOSED",
        "non_exhaustive_official_index_disposition": "UNRESOLVED_FAIL_CLOSED",
        "missing_effective_timestamp_disposition": "UNRESOLVED_FAIL_CLOSED",
        "later_migration_or_relisting_ambiguity_disposition": (
            "UNRESOLVED_FAIL_CLOSED"
        ),
        "identifier_conflict_disposition": "REJECT_FAIL_CLOSED",
        "request_cap_prevents_complete_proof_disposition": "UNRESOLVED_FAIL_CLOSED",
        "raw_response_persistence_allowed_under_parent_contract": False,
        "independent_later_replay_possible_under_parent_contract": False,
        "sanitized_fragment_hash_alone_is_inclusion_proof": False,
        "reproducible_provenance_contract_change_required": True,
        "synthetic_fixture_may_claim_real_completion": False,
        "real_complete_status_enabled_now": False,
    }


def _parent_limits() -> dict[str, int]:
    return {
        "maximum_total_http_requests": 38,
        "maximum_attempts_per_url": 1,
        "maximum_response_bytes_per_request": 1_000_000,
        "max_runtime_sec": 600,
        "hard_output_cap_bytes": 20_000_000,
    }


def _feasibility_assessment() -> dict[str, Any]:
    metadata_requests = len(VENUES)
    navigation_requests = len(BASES) * len(VENUES)
    official_page_requests = len(BASES) * len(VENUES)
    required_baseline = (
        metadata_requests + navigation_requests + official_page_requests
    )
    cap = _parent_limits()["maximum_total_http_requests"]
    remaining = cap - required_baseline
    _require(remaining == 0, "parent request budget calculation changed")
    return {
        "parent_request_cap": cap,
        "baseline_metadata_requests": metadata_requests,
        "baseline_navigation_requests": navigation_requests,
        "baseline_official_page_requests": official_page_requests,
        "baseline_required_requests": required_baseline,
        "remaining_requests_for_lineage_or_topology": remaining,
        "minimum_additional_official_index_requests_lower_bound": len(VENUES),
        "complete_currentness_feasible_under_parent_cap": False,
        "direct_linkage_evidence_schema_complete": False,
        "official_event_index_contract_complete": False,
        "temporal_freshness_contract_complete": False,
        "chain_and_asset_relation_contract_complete": False,
        "independently_replayable_provenance_complete": False,
        "implementation_approval_safe_now": False,
        "execution_approval_safe_now": False,
        "reason_codes": [
            "REQUEST_CAP_FULLY_CONSUMED_BY_BASELINE_38_OF_38",
            "OFFICIAL_EVENT_INDEX_TOPOLOGY_UNKNOWN",
            "DIRECT_METADATA_PAGE_LINK_SCHEMA_UNPROVEN",
            "CACHE_AND_RESPONSE_AGE_RULES_NOT_IMPLEMENTED",
            "CHAIN_NAMESPACE_AND_ASSET_RELATION_UNPROVEN",
            "NO_REPLAYABLE_PROVENANCE_WITHOUT_RAW_OR_EXTERNAL_SNAPSHOT",
        ],
    }


def _topology_transport_requirements() -> dict[str, Any]:
    return {
        "https_only": True,
        "get_only": True,
        "request_body_allowed": False,
        "private_or_auth_headers_allowed": False,
        "redirects_allowed": False,
        "environment_proxies_allowed": False,
        "retries_allowed": False,
        "streaming_body_limit_required": True,
        "content_length_precheck_required": True,
        "deadline_checks_before_request_and_each_chunk_required": True,
        "global_deadline_check_after_response_required": True,
        "response_url_must_equal_requested_url": True,
        "dns_or_redirect_host_expansion_allowed": False,
        "raw_payload_persistence_allowed": False,
        "search_payload_persistence_allowed": False,
        "free_form_error_text_persistence_allowed": False,
    }


def _topology_discovery_candidate() -> dict[str, Any]:
    return {
        "run_id": TOPOLOGY_RUN_ID,
        "purpose": (
            "Discover only the official index, pagination and termination topology "
            "needed to decide whether exhaustive identity-event lineage is feasible."
        ),
        "exact_seed_urls": list(TOPOLOGY_URLS),
        "official_hosts": ["www.mexc.com", "www.gate.com"],
        "identity_evidence_created": False,
        "request_plan_created": False,
        "currentness_verdict_created": False,
        "navigation_or_discovered_content_is_identity_evidence": False,
        "maximum_total_http_requests": len(TOPOLOGY_URLS),
        "maximum_attempts_per_url": 1,
        "maximum_response_bytes_per_request": 1_000_000,
        "max_runtime_sec": 300,
        "hard_output_cap_bytes": 10_000_000,
        "transport_requirements": _topology_transport_requirements(),
        "canonical_runtime_module_path": str(TOPOLOGY_RUNTIME_MODULE),
        "canonical_tests_path": str(TOPOLOGY_RUNTIME_TESTS),
        "future_visible_launcher_path": str(TOPOLOGY_VISIBLE_LAUNCHER),
        "network_adapter_implemented": False,
        "execution_manifest_validator_implemented": False,
        "visible_launcher_implemented": False,
        "output_writer_implemented": False,
        "offline_code_bound_refreeze_required": True,
        "separate_exact_execution_approval_required_after_refreeze": True,
    }


def _topology_output_contract() -> dict[str, Any]:
    return {
        "sanitized_topology_only": True,
        "allowlisted_fields": [
            "source_url",
            "response_sha256",
            "response_bytes",
            "content_type",
            "same_host_candidate_index_urls",
            "same_host_candidate_pagination_templates",
            "candidate_termination_markers",
            "disposition",
        ],
        "raw_payload_persistence_allowed": False,
        "free_form_text_persistence_allowed": False,
        "article_body_persistence_allowed": False,
        "identity_identifier_persistence_allowed": False,
        "prices_or_funding_rates_persistence_allowed": False,
        "maximum_discovered_urls": 256,
        "maximum_url_bytes": 2048,
        "topology_success_does_not_prove_exhaustiveness": True,
        "topology_success_does_not_authorize_identity_runtime": True,
    }


def _next_checkpoint() -> dict[str, Any]:
    return {
        "required_action": (
            "REQUEST_EXACT_HASH_BOUND_TOPOLOGY_DISCOVERY_OFFLINE_"
            "IMPLEMENTATION_APPROVAL"
        ),
        "approval_must_bind": [
            "proposal_path",
            "proposal_file_sha256",
            "proposal_hash",
            "parent_plan_file_sha256",
            "parent_plan_hash",
            "parent_runtime_file_sha256",
            "parent_runtime_hash",
            "topology_run_id",
            "exact_seed_urls",
            "maximum_total_http_requests",
            "max_runtime_sec",
            "hard_output_cap_bytes",
        ],
        "offline_approval_scope_only": [
            "topology_runtime_implementation",
            "synthetic_tests",
            "immutable_code_bound_runtime_refreeze",
            "preflight_only",
        ],
        "offline_approval_does_not_authorize": [
            "network",
            "official_source_content_read",
            "approval_receipt",
            "visible_launcher",
            "writer_claim",
            "topology_output",
            "request_plan_output",
            "identity_output",
            "collector_or_evaluator",
            "oos_or_returns_or_pnl",
            "grid_or_retune",
            "paper_or_live",
            "private_api_or_real_capital",
            "leverage_or_margin",
        ],
        "separate_topology_execution_approval_required_after_refreeze": True,
        "identity_implementation_approval_allowed_now": False,
        "identity_execution_approval_allowed_now": False,
    }


def _authorization_now() -> dict[str, bool]:
    return {
        "proposal_freeze_allowed": True,
        "offline_runtime_implementation_allowed": False,
        "synthetic_tests_allowed": False,
        "runtime_refreeze_allowed": False,
        "execution_manifest_creation_allowed": False,
        "approval_receipt_creation_allowed": False,
        "visible_launcher_creation_allowed": False,
        "network_run_allowed": False,
        "official_source_content_read_allowed": False,
        "global_writer_claim_allowed": False,
        "request_plan_output_allowed": False,
        "identity_output_allowed": False,
        "candidate_planonly_allowed": False,
        "collector_or_evaluator_allowed": False,
        "oos_or_returns_or_pnl_allowed": False,
        "grid_or_retune_allowed": False,
        "execution_probe_allowed": False,
        "paper_or_live_allowed": False,
        "private_api_or_real_capital_allowed": False,
        "leverage_or_margin_allowed": False,
    }


def _safety() -> dict[str, bool]:
    return {
        "network_accessed": False,
        "official_source_content_read": False,
        "execution_manifest_read": False,
        "approval_receipt_created": False,
        "visible_launcher_created": False,
        "global_writer_claim_created": False,
        "request_plan_output_created": False,
        "identity_output_created": False,
        "collector_or_evaluator_run": False,
        "oos_or_returns_or_pnl_read": False,
        "grid_or_retune": False,
        "execution_probe": False,
        "paper_or_live": False,
        "private_api_or_real_capital": False,
        "leverage_or_margin": False,
    }


def _load_parent(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan_path = _local_path(
        root / PARENT_PLAN_PATH.relative_to(REPO_ROOT),
        "parent discovery plan path",
        repo_root=root,
    )
    runtime_path = _local_path(
        root / PARENT_RUNTIME_PATH.relative_to(REPO_ROOT),
        "parent discovery runtime path",
        repo_root=root,
    )
    plan_file_sha256, plan = _read_exact_json(
        plan_path,
        "parent discovery plan",
        PARENT_PLAN_FILE_SHA256,
    )
    runtime_file_sha256, runtime = _read_exact_json(
        runtime_path,
        "parent discovery runtime manifest",
        PARENT_RUNTIME_FILE_SHA256,
    )
    _require(
        plan_file_sha256 == PARENT_PLAN_FILE_SHA256,
        "parent discovery plan file hash changed",
    )
    _require(plan.get("plan_hash") == PARENT_PLAN_HASH, "parent plan hash changed")
    _require(
        runtime_file_sha256 == PARENT_RUNTIME_FILE_SHA256,
        "parent discovery runtime file hash changed",
    )
    _require(
        runtime.get("manifest_hash") == PARENT_RUNTIME_HASH,
        "parent discovery runtime hash changed",
    )
    _require(plan.get("run_id") == PARENT_RUN_ID, "parent plan run_id changed")
    _require(runtime.get("run_id") == PARENT_RUN_ID, "parent runtime run_id changed")
    _require(
        runtime["discovery_plan"]["file_sha256"] == PARENT_PLAN_FILE_SHA256,
        "parent runtime no longer binds the exact plan file",
    )
    _require(
        runtime["discovery_plan"]["plan_hash"] == PARENT_PLAN_HASH,
        "parent runtime no longer binds the exact plan hash",
    )
    _require(
        plan["currentness_contract"]["metadata_to_official_page_linkage_implemented"]
        is False,
        "parent currentness gap unexpectedly changed",
    )
    _require(
        plan["currentness_contract"]["actual_current_request_plan_status_enabled"]
        is False,
        "parent unexpectedly enables real completion",
    )
    _require(
        runtime["execution_authorization"]["approved"] is False,
        "parent execution approval unexpectedly opened",
    )
    seed_items = plan.get("seed_items")
    _require(isinstance(seed_items, list), "parent seed items are missing")
    observed_pairs = {
        (item.get("venue"), item.get("base_ticker"))
        for item in seed_items
        if isinstance(item, Mapping)
    }
    expected_pairs = {(venue, base) for venue in VENUES for base in BASES}
    _require(
        len(seed_items) == len(expected_pairs) and observed_pairs == expected_pairs,
        "parent venue/base universe changed",
    )
    _require(
        plan["limits"]["maximum_total_http_requests"] == 38,
        "parent request cap changed",
    )
    return plan, runtime


def build_proposal(
    repo_root: str | Path,
    generated_at_utc: str,
) -> dict[str, Any]:
    _validate_timestamp(generated_at_utc, "proposal timestamp")
    root = _local_path(repo_root, "repository root")
    _require(root == REPO_ROOT, "repository root mismatch")
    _require(root.is_dir(), "repository root is missing")
    _load_parent(root)

    code_bindings = {
        "proposal_generator_path": str(MODULE_PATH),
        "proposal_generator_sha256": _sha256_file(MODULE_PATH),
        "synthetic_tests_path": str(TESTS_PATH),
        "synthetic_tests_sha256": _sha256_file(TESTS_PATH),
        "guard_checker_path": str(GUARD_PATH),
        "guard_checker_sha256": _sha256_file(GUARD_PATH),
        "parent_discovery_validator_path": str(DISCOVERY_VALIDATOR_PATH),
        "parent_discovery_validator_sha256": DISCOVERY_VALIDATOR_SHA256,
        "parent_identity_validator_path": str(IDENTITY_VALIDATOR_PATH),
        "parent_identity_validator_sha256": IDENTITY_VALIDATOR_SHA256,
        "parent_identity_proposal_validator_path": str(
            IDENTITY_PROPOSAL_VALIDATOR_PATH
        ),
        "parent_identity_proposal_validator_sha256": (
            IDENTITY_PROPOSAL_VALIDATOR_SHA256
        ),
    }
    proposal: dict[str, Any] = {
        "schema": SCHEMA,
        "proposal_id": PROPOSAL_ID,
        "mode": "PlanOnlyReviewProposal",
        "status": STATUS,
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "objective": (
            "Record why exact currentness is not yet feasible under the frozen 38-"
            "request parent contract and define only a bounded official-source "
            "topology discovery candidate."
        ),
        "parent_discovery": {
            "run_id": PARENT_RUN_ID,
            "plan_path": str(PARENT_PLAN_PATH),
            "plan_file_sha256": PARENT_PLAN_FILE_SHA256,
            "plan_hash": PARENT_PLAN_HASH,
            "runtime_path": str(PARENT_RUNTIME_PATH),
            "runtime_file_sha256": PARENT_RUNTIME_FILE_SHA256,
            "runtime_hash": PARENT_RUNTIME_HASH,
            "parent_remains_immutable": True,
            "parent_execution_authorized": False,
            "parent_real_complete_status_enabled": False,
            "parent_validation_mode": (
                "PINNED_ARTIFACT_FILE_AND_CANONICAL_HASH_NO_TRANSITIVE_IMPORT"
            ),
            "parent_validator_code_executed": False,
        },
        "code_bindings": code_bindings,
        "scope": {
            "venues": list(VENUES),
            "market": "USDT_SETTLED_LINEAR_PERPETUAL",
            "bases": list(BASES),
            "required_pair_count": len(BASES) * len(VENUES),
            "all_pairs_required": True,
            "category_exclusions_allowed": False,
            "symbol_blacklist_allowed": False,
            "hypothesis_or_universe_change_allowed": False,
        },
        "feasibility_assessment": _feasibility_assessment(),
        "target_identity_requirements": _target_identity_requirements(),
        "topology_discovery_candidate": _topology_discovery_candidate(),
        "topology_output_contract": _topology_output_contract(),
        "authorization_now": _authorization_now(),
        "preflight_contract": {
            "status": "BLOCKED_NO_CODE_BOUND_TOPOLOGY_RUNTIME",
            "proposal_validation_only": True,
            "execution_manifest_must_not_be_read": True,
            "network_must_not_be_accessed": True,
            "output_must_not_be_created": True,
            "global_writer_must_not_be_claimed": True,
            "blocked_cli_exit_code": 3,
        },
        "next_checkpoint": _next_checkpoint(),
        "safety": _safety(),
        "proposal_hash_method": HASH_METHOD,
    }
    proposal["proposal_hash"] = canonical_proposal_hash(proposal)
    validate_proposal(proposal, root)
    return proposal


def validate_proposal(
    proposal: Mapping[str, Any],
    repo_root: str | Path,
) -> None:
    _require(type(proposal) is dict, "proposal must be a plain object")
    expected_fields = {
        "schema",
        "proposal_id",
        "mode",
        "status",
        "generated_at_utc",
        "research_only",
        "objective",
        "parent_discovery",
        "code_bindings",
        "scope",
        "feasibility_assessment",
        "target_identity_requirements",
        "topology_discovery_candidate",
        "topology_output_contract",
        "authorization_now",
        "preflight_contract",
        "next_checkpoint",
        "safety",
        "proposal_hash_method",
        "proposal_hash",
    }
    _require(set(proposal) == expected_fields, "proposal field set changed")
    _require(proposal.get("schema") == SCHEMA, "proposal schema mismatch")
    _require(proposal.get("proposal_id") == PROPOSAL_ID, "proposal id mismatch")
    _require(proposal.get("mode") == "PlanOnlyReviewProposal", "proposal mode changed")
    _require(proposal.get("status") == STATUS, "proposal status changed")
    _require(proposal.get("research_only") is True, "research-only flag changed")
    _validate_timestamp(proposal.get("generated_at_utc"), "proposal timestamp")
    _require(
        proposal.get("proposal_hash_method") == HASH_METHOD,
        "proposal hash method changed",
    )
    observed_hash = _require_hash(proposal.get("proposal_hash"), "proposal hash")
    _require(
        observed_hash == canonical_proposal_hash(proposal),
        "proposal hash mismatch",
    )

    root = _local_path(repo_root, "repository root")
    _require(root == REPO_ROOT, "repository root mismatch")
    _load_parent(root)
    parent = proposal.get("parent_discovery")
    _require(isinstance(parent, Mapping), "parent discovery binding is missing")
    expected_parent = {
        "run_id": PARENT_RUN_ID,
        "plan_path": str(PARENT_PLAN_PATH),
        "plan_file_sha256": PARENT_PLAN_FILE_SHA256,
        "plan_hash": PARENT_PLAN_HASH,
        "runtime_path": str(PARENT_RUNTIME_PATH),
        "runtime_file_sha256": PARENT_RUNTIME_FILE_SHA256,
        "runtime_hash": PARENT_RUNTIME_HASH,
        "parent_remains_immutable": True,
        "parent_execution_authorized": False,
        "parent_real_complete_status_enabled": False,
        "parent_validation_mode": (
            "PINNED_ARTIFACT_FILE_AND_CANONICAL_HASH_NO_TRANSITIVE_IMPORT"
        ),
        "parent_validator_code_executed": False,
    }
    _require(dict(parent) == expected_parent, "parent discovery binding changed")

    bindings = proposal.get("code_bindings")
    _require(isinstance(bindings, Mapping), "code bindings are missing")
    exact_code_paths = {
        "proposal_generator": MODULE_PATH,
        "synthetic_tests": TESTS_PATH,
        "guard_checker": GUARD_PATH,
        "parent_discovery_validator": DISCOVERY_VALIDATOR_PATH,
        "parent_identity_validator": IDENTITY_VALIDATOR_PATH,
        "parent_identity_proposal_validator": IDENTITY_PROPOSAL_VALIDATOR_PATH,
    }
    _require(
        set(bindings)
        == {
            "proposal_generator_path",
            "proposal_generator_sha256",
            "synthetic_tests_path",
            "synthetic_tests_sha256",
            "guard_checker_path",
            "guard_checker_sha256",
            "parent_discovery_validator_path",
            "parent_discovery_validator_sha256",
            "parent_identity_validator_path",
            "parent_identity_validator_sha256",
            "parent_identity_proposal_validator_path",
            "parent_identity_proposal_validator_sha256",
        },
        "code binding field set changed",
    )
    for prefix, expected_path in exact_code_paths.items():
        observed_path = _local_path(
            str(bindings.get(f"{prefix}_path", "")),
            f"{prefix} path",
            repo_root=root,
        )
        _require(observed_path == expected_path, f"{prefix} path changed")
        bound_hash = _require_hash(
            bindings.get(f"{prefix}_sha256"), f"{prefix} file hash"
        )
        _require(
            bound_hash == _sha256_file(observed_path),
            f"{prefix} file hash changed",
        )

    expected_scope = {
        "venues": list(VENUES),
        "market": "USDT_SETTLED_LINEAR_PERPETUAL",
        "bases": list(BASES),
        "required_pair_count": len(BASES) * len(VENUES),
        "all_pairs_required": True,
        "category_exclusions_allowed": False,
        "symbol_blacklist_allowed": False,
        "hypothesis_or_universe_change_allowed": False,
    }
    _require(proposal.get("scope") == expected_scope, "proposal scope changed")
    _require(
        proposal.get("feasibility_assessment") == _feasibility_assessment(),
        "feasibility assessment changed",
    )
    feasibility = proposal["feasibility_assessment"]
    baseline_total = (
        feasibility["baseline_metadata_requests"]
        + feasibility["baseline_navigation_requests"]
        + feasibility["baseline_official_page_requests"]
    )
    _require(
        baseline_total == feasibility["baseline_required_requests"],
        "baseline request arithmetic mismatch",
    )
    _require(
        baseline_total == feasibility["parent_request_cap"]
        and feasibility["remaining_requests_for_lineage_or_topology"] == 0,
        "proposal hides available or overspent request budget",
    )
    _require(
        feasibility["complete_currentness_feasible_under_parent_cap"] is False
        and feasibility["implementation_approval_safe_now"] is False
        and feasibility["execution_approval_safe_now"] is False,
        "infeasible identity path was promoted",
    )
    _require(
        proposal.get("target_identity_requirements")
        == _target_identity_requirements(),
        "target identity requirements changed",
    )
    _require(
        proposal.get("topology_discovery_candidate")
        == _topology_discovery_candidate(),
        "topology discovery candidate changed",
    )
    _require(
        proposal.get("topology_output_contract") == _topology_output_contract(),
        "topology output contract changed",
    )
    _require(
        proposal.get("authorization_now") == _authorization_now(),
        "current authorization changed",
    )
    expected_preflight = {
        "status": "BLOCKED_NO_CODE_BOUND_TOPOLOGY_RUNTIME",
        "proposal_validation_only": True,
        "execution_manifest_must_not_be_read": True,
        "network_must_not_be_accessed": True,
        "output_must_not_be_created": True,
        "global_writer_must_not_be_claimed": True,
        "blocked_cli_exit_code": 3,
    }
    _require(
        proposal.get("preflight_contract") == expected_preflight,
        "preflight contract changed",
    )
    _require(proposal.get("safety") == _safety(), "safety contract changed")
    _require(
        proposal.get("next_checkpoint") == _next_checkpoint(),
        "next checkpoint changed",
    )


def write_proposal(
    path: str | Path,
    proposal: Mapping[str, Any],
) -> Path:
    output = _local_path(path, "proposal output path")
    expected = _json_file_bytes(proposal)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as handle:
            _assert_open_handle_path(handle, output)
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            with output.open("rb") as handle:
                _assert_open_handle_path(handle, output)
                before = os.fstat(handle.fileno())
                current = handle.read()
                after = os.fstat(handle.fileno())
                _assert_open_handle_path(handle, output)
        except OSError as exc:
            raise ProposalError(f"cannot read immutable artifact: {output}") from exc
        _require(
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            f"immutable artifact changed while reading: {output}",
        )
        _require(current == expected, f"immutable artifact mismatch: {output}")
    return output


def preflight_future_execution(
    *,
    proposal_path: str | Path,
    execution_manifest_path: str | Path,
    output_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "BLOCKED_NO_CODE_BOUND_TOPOLOGY_RUNTIME",
        "reason": "topology runtime is not implemented or authorized",
        "proposal_path": os.fspath(proposal_path),
        "execution_manifest_path": os.fspath(execution_manifest_path),
        "output_path": os.fspath(output_path),
        "network_accessed": False,
        "execution_manifest_read": False,
        "output_created": False,
        "global_writer_claimed": False,
    }
    try:
        root = _local_path(repo_root, "repository root")
        proposal_file = _local_path(proposal_path, "proposal path")
        execution_file = _local_path(
            execution_manifest_path, "execution manifest path"
        )
        output = _local_path(output_path, "output path")
        result["proposal_path"] = str(proposal_file)
        result["execution_manifest_path"] = str(execution_file)
        result["output_path"] = str(output)
        _, proposal = _read_json(proposal_file, "currentness proposal")
        validate_proposal(proposal, root)
    except ProposalError as exc:
        result["reason"] = str(exc)
        return result
    result["reason"] = (
        "proposal is valid, but execution manifest was not read; exact offline "
        "topology implementation approval is required before any runtime refreeze"
    )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", required=True)
    build.add_argument("--generated-at-utc", required=True)
    build.add_argument("--output", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--repo-root", required=True)
    validate.add_argument("--proposal", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--repo-root", required=True)
    preflight.add_argument("--proposal", required=True)
    preflight.add_argument("--execution-manifest", required=True)
    preflight.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    exit_code = 0
    if args.command == "build":
        proposal = build_proposal(args.repo_root, args.generated_at_utc)
        output = write_proposal(args.output, proposal)
        payload = {
            "status": "FROZEN_PLANONLY_NO_EXECUTION",
            "proposal_path": str(output),
            "proposal_file_sha256": _sha256_file(output),
            "proposal_hash": proposal["proposal_hash"],
        }
    elif args.command == "validate":
        path = _local_path(args.proposal, "proposal path")
        file_sha256, proposal = _read_json(path, "currentness proposal")
        validate_proposal(proposal, args.repo_root)
        payload = {
            "status": "VALID_PLANONLY_NO_EXECUTION",
            "proposal_path": str(path),
            "proposal_file_sha256": file_sha256,
            "proposal_hash": proposal["proposal_hash"],
        }
    else:
        payload = preflight_future_execution(
            proposal_path=args.proposal,
            execution_manifest_path=args.execution_manifest,
            output_path=args.output,
            repo_root=args.repo_root,
        )
        exit_code = 3
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASES",
    "PARENT_PLAN_FILE_SHA256",
    "PARENT_PLAN_HASH",
    "PARENT_RUNTIME_FILE_SHA256",
    "PARENT_RUNTIME_HASH",
    "ProposalError",
    "build_proposal",
    "canonical_proposal_hash",
    "preflight_future_execution",
    "validate_proposal",
    "write_proposal",
]
