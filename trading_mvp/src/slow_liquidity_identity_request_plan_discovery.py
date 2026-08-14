from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from .slow_liquidity_official_identity_verification import (
    FetchedResponse,
    IdentityVerificationError,
    OFFICIAL_METADATA_ENDPOINTS,
    _active_gateio_instruments,
    _active_mexc_instruments,
    _strict_json_loads,
    _validate_official_source_url,
    _validate_request_plan_item,
    validate_runtime_manifest as validate_identity_runtime_manifest,
)


DISCOVERY_PLAN_SCHEMA = (
    "trading_mvp_slow_liquidity_identity_request_plan_discovery_plan_v1"
)
DISCOVERY_PLAN_STATUS = "PLANONLY_OFFLINE_AWAIT_EXACT_EXECUTION_APPROVAL"
RUNTIME_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_identity_request_plan_discovery_runtime_manifest_v1"
)
RUNTIME_MANIFEST_STATUS = (
    "FROZEN_OFFLINE_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL"
)
EXECUTION_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_identity_request_plan_discovery_execution_manifest_v1"
)
EXECUTION_MANIFEST_STATUS = "FROZEN_WITH_EXACT_DISCOVERY_EXECUTION_APPROVAL"
RUN_ID = "slow_liquidity_identity_request_plan_discovery_20260813_v2"
MODULE_PATH = Path(__file__).resolve()
REPO_ROOT = MODULE_PATH.parents[2]
SYNTHETIC_TESTS_PATH = (
    REPO_ROOT
    / "trading_mvp/tests/test_slow_liquidity_identity_request_plan_discovery.py"
)
GUARD_CHECKER_PATH = REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1"
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
NAVIGATION_HOST = "www.bing.com"
NAVIGATION_PATH = "/search"
MAX_TOTAL_HTTP_REQUESTS = 38
MAX_ATTEMPTS_PER_URL = 1
MAX_RESPONSE_BYTES = 1_000_000
MAX_RUNTIME_SEC = 600
HARD_OUTPUT_CAP_BYTES = 20_000_000
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EVM_IDENTIFIER_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f])0[xX][0-9a-fA-F]{40}(?![0-9A-Fa-f])"
)
CONTRACT_ADDRESS_PATTERN = re.compile(
    r"contract[\s_.:-]*address", re.IGNORECASE
)
VISIBLE_CONTEXT_RADIUS = 256
SEED_ITEM_FIELDS = {
    "venue",
    "base_ticker",
    "instrument_id",
    "search_url",
    "navigation_query",
    "expected_official_host",
    "allowed_official_path_prefix",
}
OFFLINE_AUTHORIZATION_SCOPE = {
    "offline_runtime_implementation": True,
    "synthetic_tests": True,
    "planonly_manifest_creation": True,
    "runtime_manifest_creation": True,
    "preflight_only": True,
    "actual_network_run": False,
    "official_source_content_read": False,
    "identity_output": False,
    "global_writer_claim": False,
    "candidate_planonly_creation": False,
    "collector_or_evaluator": False,
    "oos_or_returns_or_pnl": False,
    "grid_or_retune": False,
    "paper_or_live": False,
    "private_api_or_real_capital": False,
    "leverage_or_margin": False,
}


class RequestPlanDiscoveryError(ValueError):
    pass


class _VisibleTextExtractor(HTMLParser):
    _HIDDEN_TAGS = {"script", "style", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag.lower() in self._HIDDEN_TAGS:
            self._hidden_depth += 1

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del tag, attrs

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._HIDDEN_TAGS and self._hidden_depth > 0:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(self._parts)


@dataclass(frozen=True)
class RequestPlanDiscoveryResult:
    status: str
    request_plan: tuple[dict[str, Any], ...]
    unresolved_pairs: tuple[str, ...]
    metadata_response_hashes: tuple[str, ...]
    navigation_response_hashes: tuple[str, ...]
    official_response_hashes: tuple[str, ...]
    request_count: int


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash_without(payload: Mapping[str, Any], field: str) -> str:
    normalized = copy.deepcopy(dict(payload))
    normalized.pop(field, None)
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def _json_file_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _sha256_file(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    _require(resolved.is_file(), f"required file is missing: {resolved}")
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RequestPlanDiscoveryError(f"cannot read required file: {resolved}") from exc
    return digest.hexdigest()


def _read_json_snapshot(
    path: str | Path, label: str
) -> tuple[Path, str, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    _require(resolved.is_file(), f"{label} is missing")
    try:
        raw = resolved.read_bytes()
        payload = _strict_json_loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RequestPlanDiscoveryError(f"{label} is not valid JSON") from exc
    _require(isinstance(payload, dict), f"{label} must be a JSON object")
    return resolved, hashlib.sha256(raw).hexdigest(), payload


def _file_binding(path: str | Path) -> dict[str, str]:
    resolved = Path(path).expanduser().resolve()
    return {"path": str(resolved), "file_sha256": _sha256_file(resolved)}


def _write_immutable_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    output = Path(path).expanduser().resolve()
    expected = _json_file_bytes(payload)
    if output.exists():
        try:
            current = output.read_bytes()
        except OSError as exc:
            raise RequestPlanDiscoveryError(
                f"cannot read immutable artifact: {output}"
            ) from exc
        _require(current == expected, f"immutable artifact mismatch: {output}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RequestPlanDiscoveryError(f"immutable artifact race: {output}") from exc
    return output


def _local_lexical_path(
    path: str | Path,
    label: str,
    *,
    require_repo_path: bool,
) -> Path:
    raw = os.fspath(path)
    _require(type(raw) is str and raw != "", f"{label} is missing")
    _require("\x00" not in raw, f"{label} contains a null byte")
    windows_form = raw.replace("/", "\\")
    _require(
        not windows_form.startswith(("\\\\", "\\?\\", "\\.\\")),
        f"{label} remote path is forbidden",
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
    if not require_repo_path:
        return candidate
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise RequestPlanDiscoveryError(f"{label} must be inside the local repo") from exc
    return candidate


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RequestPlanDiscoveryError(message)


def _require_hash(value: Any, label: str) -> str:
    _require(type(value) is str and HASH_PATTERN.fullmatch(value) is not None, f"{label} is invalid")
    return value


def _validate_timestamp(value: Any, label: str) -> str:
    _require(type(value) is str and value.endswith("Z"), f"{label} must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RequestPlanDiscoveryError(f"{label} is invalid") from exc
    _require(parsed.utcoffset() is not None, f"{label} must be timezone-aware")
    return value


def _official_contract(venue: str) -> tuple[str, str]:
    return (
        ("www.mexc.com", "/support/articles/")
        if venue == "mexc"
        else ("www.gate.com", "/announcements/article/")
    )


def _navigation_query(venue: str, base: str) -> str:
    host, prefix = _official_contract(venue)
    return (
        f'site:{host}{prefix} "{base}" "{base}_USDT" '
        '"Contract Address"'
    )


def _navigation_url(query: str) -> str:
    return "https://www.bing.com/search?" + urllib.parse.urlencode(
        (("format", "rss"), ("q", query))
    )


def _seed_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for base in BASES:
        for venue in VENUES:
            host, prefix = _official_contract(venue)
            query = _navigation_query(venue, base)
            items.append(
                {
                    "venue": venue,
                    "base_ticker": base,
                    "instrument_id": f"{base}_USDT",
                    "search_url": _navigation_url(query),
                    "navigation_query": query,
                    "expected_official_host": host,
                    "allowed_official_path_prefix": prefix,
                }
            )
    return items


def build_discovery_plan(*, generated_at_utc: str) -> dict[str, Any]:
    _validate_timestamp(generated_at_utc, "discovery plan timestamp")
    plan: dict[str, Any] = {
        "schema": DISCOVERY_PLAN_SCHEMA,
        "status": DISCOVERY_PLAN_STATUS,
        "mode": "PlanOnly",
        "generated_at_utc": generated_at_utc,
        "run_id": RUN_ID,
        "research_only": True,
        "goal": "Build an exact official-source request plan for identity verification",
        "compatibility_contract": {
            "consumer_runtime": "slow_liquidity_official_identity_verification_v1",
            "required_pair_count": len(BASES) * len(VENUES),
            "venues": list(VENUES),
            "bases": list(BASES),
            "instrument_template": "{BASE}_USDT",
            "request_plan_items_must_pass_consumer_validator": True,
        },
        "navigation_contract": {
            "provider": "BING_RSS",
            "scheme": "https",
            "host": NAVIGATION_HOST,
            "path": NAVIGATION_PATH,
            "role": "NAVIGATION_ONLY_NOT_IDENTITY_EVIDENCE",
            "search_result_title_is_identity_evidence": False,
            "search_result_snippet_is_identity_evidence": False,
            "search_result_persistence_allowed": False,
            "redirect_following_allowed": False,
        },
        "official_source_contract": {
            "metadata_endpoints": copy.deepcopy(OFFICIAL_METADATA_ENDPOINTS),
            "evidence_hosts": {
                venue: {
                    "host": _official_contract(venue)[0],
                    "allowed_path_prefix": _official_contract(venue)[1],
                }
                for venue in VENUES
            },
            "only_allowlisted_official_page_content_is_identity_evidence": True,
            "ticker_or_name_match_alone_is_identity_evidence": False,
            "exact_active_perpetual_metadata_required": True,
            "exact_unique_canonical_identifier_required": True,
        },
        "currentness_contract": {
            "active_perpetual_metadata_snapshot_required": True,
            "single_navigation_result_is_currentness_evidence": False,
            "metadata_to_official_page_linkage_required": True,
            "metadata_to_official_page_linkage_implemented": False,
            "synthetic_fixture_may_claim_real_completion": False,
            "actual_current_request_plan_status_enabled": False,
        },
        "seed_items": _seed_items(),
        "limits": {
            "maximum_total_http_requests": MAX_TOTAL_HTTP_REQUESTS,
            "maximum_attempts_per_url": MAX_ATTEMPTS_PER_URL,
            "maximum_response_bytes_per_request": MAX_RESPONSE_BYTES,
            "max_runtime_sec": MAX_RUNTIME_SEC,
            "hard_output_cap_bytes": HARD_OUTPUT_CAP_BYTES,
        },
        "output_contract": {
            "required_files": ["request-plan.json", "manifest.json"],
            "immutable_exclusive_create": True,
            "raw_payload_persistence_allowed": False,
            "search_snippet_persistence_allowed": False,
            "prices_or_funding_rates_persistence_allowed": False,
            "identity_verdict_created": False,
            "candidate_planonly_created": False,
        },
        "execution_authorization": {
            "approved": False,
            "actual_network_run_allowed": False,
            "output_creation_allowed": False,
            "global_writer_claim_allowed": False,
            "separate_exact_code_bound_execution_approval_required": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "safety": {
            "network_accessed": False,
            "output_created": False,
            "collector_or_evaluator_run": False,
            "oos_or_returns_or_pnl_read": False,
            "grid_or_retune": False,
            "paper_or_live": False,
            "private_api_or_real_capital": False,
            "leverage_or_margin": False,
        },
        "plan_hash_method": "sha256_canonical_json_excluding_plan_hash",
    }
    plan["plan_hash"] = canonical_hash_without(plan, "plan_hash")
    return plan


def _validate_navigation_url(item: Mapping[str, Any]) -> None:
    value = item.get("search_url")
    _require(type(value) is str and value != "", "navigation URL is missing")
    parsed = urllib.parse.urlsplit(value)
    _require(parsed.scheme == "https", "navigation scheme is invalid")
    _require(
        parsed.hostname == NAVIGATION_HOST and parsed.netloc == NAVIGATION_HOST,
        "navigation host is not allowlisted",
    )
    _require(parsed.path == NAVIGATION_PATH, "navigation path is invalid")
    _require(parsed.fragment == "", "navigation fragment is forbidden")
    _require(
        parsed.username is None and parsed.password is None and parsed.port is None,
        "navigation authority is invalid",
    )
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    _require(set(query) == {"format", "q"}, "navigation query field set changed")
    _require(query["format"] == ["rss"], "navigation format is not RSS")
    _require(query["q"] == [item.get("navigation_query")], "navigation query mismatch")


def validate_discovery_plan(plan: Mapping[str, Any]) -> None:
    _require(type(plan) is dict, "discovery plan must be a plain object")
    expected_fields = {
        "schema",
        "status",
        "mode",
        "generated_at_utc",
        "run_id",
        "research_only",
        "goal",
        "compatibility_contract",
        "navigation_contract",
        "official_source_contract",
        "currentness_contract",
        "seed_items",
        "limits",
        "output_contract",
        "execution_authorization",
        "safety",
        "plan_hash_method",
        "plan_hash",
    }
    _require(set(plan) == expected_fields, "discovery plan field set changed")
    _require(plan.get("schema") == DISCOVERY_PLAN_SCHEMA, "discovery plan schema mismatch")
    _require(plan.get("status") == DISCOVERY_PLAN_STATUS, "discovery plan status mismatch")
    _validate_timestamp(plan.get("generated_at_utc"), "discovery plan timestamp")
    expected = build_discovery_plan(generated_at_utc=str(plan["generated_at_utc"]))
    items = plan.get("seed_items")
    _require(isinstance(items, list) and len(items) == 18, "seed item count mismatch")
    for index, item in enumerate(items):
        _require(isinstance(item, Mapping), "seed item is invalid")
        _require(set(item) == SEED_ITEM_FIELDS, "seed item field set changed")
        _validate_navigation_url(item)
        expected_item = expected["seed_items"][index]
        _require(dict(item) == expected_item, "seed item contract mismatch")
    _require(dict(plan) == expected, "discovery plan contract mismatch")
    _require_hash(plan.get("plan_hash"), "discovery plan hash")
    _require(
        plan["plan_hash"] == canonical_hash_without(plan, "plan_hash"),
        "discovery plan hash mismatch",
    )


def build_runtime_manifest(
    *,
    discovery_plan_path: str | Path,
    parent_identity_runtime_manifest_path: str | Path,
    runtime_module_path: str | Path,
    synthetic_tests_path: str | Path,
    guard_checker_path: str | Path,
    generated_at_utc: str,
    user_authorization_text: str,
    response_annotation_index: int,
    _plan_snapshot: tuple[Path, str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _validate_timestamp(generated_at_utc, "runtime manifest timestamp")
    _require(
        user_authorization_text == "разрешаю",
        "offline authorization text mismatch",
    )
    _require(
        response_annotation_index == 1,
        "offline authorization annotation mismatch",
    )
    if _plan_snapshot is None:
        local_plan_path = _local_lexical_path(
            discovery_plan_path,
            "discovery PlanOnly path",
            require_repo_path=False,
        )
        plan_path, plan_file_sha256, plan = _read_json_snapshot(
            local_plan_path, "discovery PlanOnly"
        )
    else:
        plan_path, plan_file_sha256, plan = _plan_snapshot
        expected_plan_path = Path(
            os.path.abspath(os.path.expanduser(os.fspath(discovery_plan_path)))
        )
        _require(plan_path == expected_plan_path, "staged discovery plan path mismatch")
        _require_hash(plan_file_sha256, "staged discovery plan file hash")
    validate_discovery_plan(plan)
    local_parent_path = _local_lexical_path(
        parent_identity_runtime_manifest_path,
        "parent official identity runtime path",
        require_repo_path=True,
    )
    parent_path, parent_file_sha256, parent = _read_json_snapshot(
        local_parent_path,
        "parent official identity runtime manifest",
    )
    try:
        validate_identity_runtime_manifest(parent)
    except IdentityVerificationError as exc:
        raise RequestPlanDiscoveryError(
            "parent official identity runtime manifest is invalid"
        ) from exc
    parent_authorization = parent.get("execution_authorization")
    _require(
        isinstance(parent_authorization, Mapping),
        "parent identity execution authorization is missing",
    )
    for key in (
        "actual_network_run_allowed",
        "official_source_content_read_allowed",
        "identity_output_allowed",
        "global_writer_claim_allowed",
    ):
        _require(
            parent_authorization.get(key) is False,
            f"parent identity execution permission is open: {key}",
        )

    module_candidate = _local_lexical_path(
        runtime_module_path, "runtime module path", require_repo_path=True
    )
    tests_candidate = _local_lexical_path(
        synthetic_tests_path, "synthetic tests path", require_repo_path=True
    )
    guard_candidate = _local_lexical_path(
        guard_checker_path, "guard checker path", require_repo_path=True
    )
    _require(module_candidate == MODULE_PATH, "runtime module path mismatch")
    _require(
        tests_candidate == SYNTHETIC_TESTS_PATH,
        "synthetic tests path mismatch",
    )
    _require(guard_candidate == GUARD_CHECKER_PATH, "guard checker path mismatch")
    module_binding = _file_binding(module_candidate)
    tests_binding = _file_binding(tests_candidate)
    guard_binding = _file_binding(guard_candidate)
    manifest: dict[str, Any] = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "status": RUNTIME_MANIFEST_STATUS,
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "run_id": RUN_ID,
        "discovery_plan": {
            "path": str(plan_path),
            "file_sha256": plan_file_sha256,
            "plan_hash": plan["plan_hash"],
        },
        "parent_official_identity_runtime": {
            "path": str(parent_path),
            "file_sha256": parent_file_sha256,
            "manifest_hash": parent["manifest_hash"],
        },
        "runtime": {
            "module_path": module_binding["path"],
            "module_sha256": module_binding["file_sha256"],
            "synthetic_tests_path": tests_binding["path"],
            "synthetic_tests_sha256": tests_binding["file_sha256"],
            "guard_checker_path": guard_binding["path"],
            "guard_checker_sha256": guard_binding["file_sha256"],
            "synthetic_fixture_parser_only": True,
            "network_discovery_callable_exposed": False,
            "network_adapter_implemented": False,
            "execution_manifest_validator_implemented": False,
            "visible_launcher_implemented": False,
            "loaded_module_identity_verification_implemented": False,
        },
        "offline_authorization": {
            "mode": "DIRECT_USER_RESPONSE_ANNOTATION_OFFLINE_ONLY",
            "response_annotation_index": response_annotation_index,
            "user_authorization_text": user_authorization_text,
            "authorized_scope": copy.deepcopy(OFFLINE_AUTHORIZATION_SCOPE),
        },
        "compatibility_contract": copy.deepcopy(plan["compatibility_contract"]),
        "navigation_contract": copy.deepcopy(plan["navigation_contract"]),
        "official_source_contract": copy.deepcopy(
            plan["official_source_contract"]
        ),
        "currentness_contract": copy.deepcopy(plan["currentness_contract"]),
        "limits": copy.deepcopy(plan["limits"]),
        "output_contract": copy.deepcopy(plan["output_contract"]),
        "execution_authorization": {
            "approved": False,
            "execution_approval_receipt": None,
            "actual_network_run_allowed": False,
            "official_source_content_read_allowed": False,
            "output_creation_allowed": False,
            "identity_output_allowed": False,
            "global_writer_claim_allowed": False,
            "execution_manifest_supported": False,
            "network_adapter_available": False,
            "visible_launcher_available": False,
            "runtime_can_mint_execution_approval": False,
            "external_runtime_manifest_file_sha256_required_for_execution": True,
            "external_runtime_manifest_hash_required_for_execution": True,
            "separate_exact_code_bound_refreeze_and_execution_approval_required": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "preflight_contract": {
            "status": "BLOCKED_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL",
            "must_not_create_output": True,
            "must_not_access_network": True,
            "must_not_claim_global_writer": True,
            "direct_runtime_invocation_forbidden": True,
            "actual_execution_path_present": False,
            "new_code_bound_runtime_refreeze_required_before_execution_approval": True,
        },
        "safety": {
            "network_accessed": False,
            "official_source_content_read": False,
            "output_created": False,
            "identity_output_created": False,
            "global_writer_claim_created": False,
            "collector_or_evaluator_run": False,
            "oos_or_returns_or_pnl_read": False,
            "grid_or_retune": False,
            "paper_or_live": False,
            "private_api_or_real_capital": False,
            "leverage_or_margin": False,
        },
        "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
    }
    manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")
    return manifest


def validate_runtime_manifest(
    manifest: Mapping[str, Any],
    *,
    _plan_snapshot: tuple[Path, str, dict[str, Any]] | None = None,
    _require_repo_plan: bool = False,
) -> None:
    expected_fields = {
        "schema",
        "status",
        "generated_at_utc",
        "research_only",
        "run_id",
        "discovery_plan",
        "parent_official_identity_runtime",
        "runtime",
        "offline_authorization",
        "compatibility_contract",
        "navigation_contract",
        "official_source_contract",
        "currentness_contract",
        "limits",
        "output_contract",
        "execution_authorization",
        "preflight_contract",
        "safety",
        "manifest_hash_method",
        "manifest_hash",
    }
    _require(set(manifest) == expected_fields, "runtime manifest field set changed")
    _require(
        manifest.get("schema") == RUNTIME_MANIFEST_SCHEMA,
        "runtime manifest schema mismatch",
    )
    _require(
        manifest.get("status") == RUNTIME_MANIFEST_STATUS,
        "runtime manifest status mismatch",
    )
    _validate_timestamp(manifest.get("generated_at_utc"), "runtime manifest timestamp")
    _require(manifest.get("research_only") is True, "runtime is not research-only")
    _require(manifest.get("run_id") == RUN_ID, "runtime run_id mismatch")
    _require(
        manifest.get("manifest_hash_method")
        == "sha256_canonical_json_excluding_manifest_hash",
        "runtime manifest hash method mismatch",
    )
    observed_hash = _require_hash(manifest.get("manifest_hash"), "runtime manifest hash")
    _require(
        observed_hash == canonical_hash_without(manifest, "manifest_hash"),
        "runtime manifest hash mismatch",
    )

    plan_binding = manifest.get("discovery_plan")
    _require(isinstance(plan_binding, Mapping), "runtime discovery plan binding is missing")
    _require(
        set(plan_binding) == {"path", "file_sha256", "plan_hash"},
        "runtime discovery plan binding changed",
    )
    bound_plan_path = _local_lexical_path(
        str(plan_binding.get("path", "")),
        "runtime discovery PlanOnly path",
        require_repo_path=_require_repo_plan,
    )
    if _plan_snapshot is None:
        plan_path, plan_file_sha256, plan = _read_json_snapshot(
            bound_plan_path, "runtime discovery PlanOnly"
        )
    else:
        plan_path, plan_file_sha256, plan = _plan_snapshot
    _require(
        plan_file_sha256
        == _require_hash(plan_binding.get("file_sha256"), "discovery plan file hash"),
        "runtime discovery plan file hash mismatch",
    )
    validate_discovery_plan(plan)
    _require(
        plan.get("plan_hash") == plan_binding.get("plan_hash"),
        "runtime discovery plan canonical hash mismatch",
    )
    _require(plan_path == bound_plan_path, "runtime discovery plan path mismatch")

    parent_binding = manifest.get("parent_official_identity_runtime")
    _require(
        isinstance(parent_binding, Mapping),
        "parent identity runtime binding is missing",
    )
    _require(
        set(parent_binding) == {"path", "file_sha256", "manifest_hash"},
        "parent identity runtime binding changed",
    )
    parent_path = _local_lexical_path(
        str(parent_binding.get("path", "")),
        "parent official identity runtime path",
        require_repo_path=True,
    )
    _, parent_file_sha256, parent = _read_json_snapshot(
        parent_path,
        "parent official identity runtime manifest",
    )
    _require(
        parent_file_sha256
        == _require_hash(parent_binding.get("file_sha256"), "parent runtime file hash"),
        "parent identity runtime file hash mismatch",
    )
    try:
        validate_identity_runtime_manifest(parent)
    except IdentityVerificationError as exc:
        raise RequestPlanDiscoveryError(
            "parent official identity runtime manifest is invalid"
        ) from exc
    _require(
        parent.get("manifest_hash") == parent_binding.get("manifest_hash"),
        "parent identity runtime canonical hash mismatch",
    )

    runtime = manifest.get("runtime")
    _require(isinstance(runtime, Mapping), "runtime file bindings are missing")
    _require(
        set(runtime)
        == {
            "module_path",
            "module_sha256",
            "synthetic_tests_path",
            "synthetic_tests_sha256",
            "guard_checker_path",
            "guard_checker_sha256",
            "synthetic_fixture_parser_only",
            "network_discovery_callable_exposed",
            "network_adapter_implemented",
            "execution_manifest_validator_implemented",
            "visible_launcher_implemented",
            "loaded_module_identity_verification_implemented",
        },
        "runtime file binding set changed",
    )
    _require(
        runtime.get("synthetic_fixture_parser_only") is True,
        "runtime is not restricted to synthetic fixtures",
    )
    _require(
        runtime.get("network_discovery_callable_exposed") is False,
        "network discovery callable is exposed",
    )
    exact_runtime_paths = {
        "module": MODULE_PATH,
        "synthetic_tests": SYNTHETIC_TESTS_PATH,
        "guard_checker": GUARD_CHECKER_PATH,
    }
    for prefix, exact_path in exact_runtime_paths.items():
        observed_path = _local_lexical_path(
            str(runtime.get(f"{prefix}_path", "")),
            f"{prefix} path",
            require_repo_path=True,
        )
        _require(observed_path == exact_path, f"{prefix} path mismatch")
        expected = _require_hash(runtime.get(f"{prefix}_sha256"), f"{prefix} hash")
        _require(
            _sha256_file(observed_path) == expected,
            f"{prefix} file hash mismatch",
        )
    for key in (
        "network_adapter_implemented",
        "execution_manifest_validator_implemented",
        "visible_launcher_implemented",
        "loaded_module_identity_verification_implemented",
    ):
        _require(runtime.get(key) is False, f"offline runtime capability enabled: {key}")

    offline = manifest.get("offline_authorization")
    _require(isinstance(offline, Mapping), "offline authorization is missing")
    _require(
        set(offline)
        == {
            "mode",
            "response_annotation_index",
            "user_authorization_text",
            "authorized_scope",
        },
        "offline authorization field set changed",
    )
    _require(
        offline.get("mode") == "DIRECT_USER_RESPONSE_ANNOTATION_OFFLINE_ONLY",
        "offline authorization mode mismatch",
    )
    _require(offline.get("response_annotation_index") == 1, "offline annotation mismatch")
    _require(offline.get("user_authorization_text") == "разрешаю", "offline text mismatch")
    _require(
        offline.get("authorized_scope") == OFFLINE_AUTHORIZATION_SCOPE,
        "offline authorization scope changed",
    )

    for contract_name in (
        "compatibility_contract",
        "navigation_contract",
        "official_source_contract",
        "currentness_contract",
        "limits",
        "output_contract",
    ):
        _require(
            manifest.get(contract_name) == plan.get(contract_name),
            f"runtime {contract_name} differs from PlanOnly",
        )

    authorization = manifest.get("execution_authorization")
    _require(isinstance(authorization, Mapping), "execution authorization is missing")
    _require(
        set(authorization)
        == {
            "approved",
            "execution_approval_receipt",
            "actual_network_run_allowed",
            "official_source_content_read_allowed",
            "output_creation_allowed",
            "identity_output_allowed",
            "global_writer_claim_allowed",
            "execution_manifest_supported",
            "network_adapter_available",
            "visible_launcher_available",
            "runtime_can_mint_execution_approval",
            "external_runtime_manifest_file_sha256_required_for_execution",
            "external_runtime_manifest_hash_required_for_execution",
            "separate_exact_code_bound_refreeze_and_execution_approval_required",
            "stopped_incomplete_retry_authorized",
        },
        "execution authorization field set changed",
    )
    _require(authorization.get("approved") is False, "execution approval is open")
    _require(
        authorization.get("execution_approval_receipt") is None,
        "execution approval receipt is unexpectedly bound",
    )
    for key in (
        "actual_network_run_allowed",
        "official_source_content_read_allowed",
        "output_creation_allowed",
        "identity_output_allowed",
        "global_writer_claim_allowed",
        "execution_manifest_supported",
        "network_adapter_available",
        "visible_launcher_available",
        "runtime_can_mint_execution_approval",
        "stopped_incomplete_retry_authorized",
    ):
        _require(authorization.get(key) is False, f"network or execution permission enabled: {key}")
    for key in (
        "external_runtime_manifest_file_sha256_required_for_execution",
        "external_runtime_manifest_hash_required_for_execution",
    ):
        _require(
            authorization.get(key) is True,
            f"external execution binding requirement removed: {key}",
        )
    _require(
        authorization.get(
            "separate_exact_code_bound_refreeze_and_execution_approval_required"
        )
        is True,
        "separate execution refreeze requirement removed",
    )

    preflight = manifest.get("preflight_contract")
    _require(isinstance(preflight, Mapping), "preflight contract is missing")
    _require(
        preflight
        == {
            "status": "BLOCKED_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL",
            "must_not_create_output": True,
            "must_not_access_network": True,
            "must_not_claim_global_writer": True,
            "direct_runtime_invocation_forbidden": True,
            "actual_execution_path_present": False,
            "new_code_bound_runtime_refreeze_required_before_execution_approval": True,
        },
        "preflight contract changed",
    )
    safety = manifest.get("safety")
    _require(
        safety
        == {
            "network_accessed": False,
            "official_source_content_read": False,
            "output_created": False,
            "identity_output_created": False,
            "global_writer_claim_created": False,
            "collector_or_evaluator_run": False,
            "oos_or_returns_or_pnl_read": False,
            "grid_or_retune": False,
            "paper_or_live": False,
            "private_api_or_real_capital": False,
            "leverage_or_margin": False,
        },
        "runtime safety block changed",
    )


def freeze_offline_bundle(
    *,
    discovery_plan_path: str | Path,
    runtime_manifest_path: str | Path,
    parent_identity_runtime_manifest_path: str | Path,
    runtime_module_path: str | Path,
    synthetic_tests_path: str | Path,
    guard_checker_path: str | Path,
    plan_generated_at_utc: str,
    manifest_generated_at_utc: str,
    user_authorization_text: str,
    response_annotation_index: int,
) -> dict[str, Any]:
    plan = build_discovery_plan(generated_at_utc=plan_generated_at_utc)
    plan_path = _local_lexical_path(
        discovery_plan_path,
        "offline discovery PlanOnly output path",
        require_repo_path=False,
    )
    manifest_path = _local_lexical_path(
        runtime_manifest_path,
        "offline discovery runtime output path",
        require_repo_path=False,
    )
    _require(plan_path.parent == manifest_path.parent, "offline bundle paths differ")
    _require(plan_path != manifest_path, "offline bundle file paths collide")
    bundle_path = plan_path.parent
    plan_file_sha256 = hashlib.sha256(_json_file_bytes(plan)).hexdigest()
    plan_snapshot = (plan_path, plan_file_sha256, plan)
    manifest = build_runtime_manifest(
        discovery_plan_path=plan_path,
        parent_identity_runtime_manifest_path=parent_identity_runtime_manifest_path,
        runtime_module_path=runtime_module_path,
        synthetic_tests_path=synthetic_tests_path,
        guard_checker_path=guard_checker_path,
        generated_at_utc=manifest_generated_at_utc,
        user_authorization_text=user_authorization_text,
        response_annotation_index=response_annotation_index,
        _plan_snapshot=plan_snapshot,
    )
    validate_runtime_manifest(manifest, _plan_snapshot=plan_snapshot)
    expected_names = sorted((plan_path.name, manifest_path.name))
    if bundle_path.exists():
        _require(bundle_path.is_dir(), "offline bundle path is not a directory")
        _require(
            sorted(path.name for path in bundle_path.iterdir()) == expected_names,
            "offline bundle file set changed",
        )
        _write_immutable_json(plan_path, plan)
        _write_immutable_json(manifest_path, manifest)
    else:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{bundle_path.name}.tmp-",
                dir=str(bundle_path.parent),
            )
        )
        committed = False
        try:
            _write_immutable_json(temporary / plan_path.name, plan)
            _write_immutable_json(temporary / manifest_path.name, manifest)
            _require(
                sorted(path.name for path in temporary.iterdir()) == expected_names,
                "staged offline bundle file set changed",
            )
            temporary.rename(bundle_path)
            committed = True
        except FileExistsError as exc:
            raise RequestPlanDiscoveryError("offline bundle publish race") from exc
        finally:
            if not committed:
                shutil.rmtree(temporary, ignore_errors=True)
    validate_runtime_manifest(manifest)
    return {
        "status": RUNTIME_MANIFEST_STATUS,
        "discovery_plan_path": str(plan_path),
        "discovery_plan_file_sha256": _sha256_file(plan_path),
        "discovery_plan_hash": plan["plan_hash"],
        "runtime_manifest_path": str(manifest_path),
        "runtime_manifest_file_sha256": _sha256_file(manifest_path),
        "runtime_manifest_hash": manifest["manifest_hash"],
        "actual_network_run_allowed": False,
        "output_creation_allowed": False,
        "global_writer_claim_allowed": False,
    }


def _validated_response(response: FetchedResponse, expected_url: str) -> bytes:
    _require(type(response) is FetchedResponse, "fixture response type changed")
    _require(response.requested_url == expected_url, "requested URL mismatch")
    _require(response.final_url == expected_url, "HTTP redirect is forbidden")
    _require(response.status == 200, "HTTP response status is not 200")
    _require(type(response.body) is bytes, "HTTP response body must be bytes")
    _require(0 < len(response.body) <= MAX_RESPONSE_BYTES, "HTTP response body exceeds cap")
    return response.body


def _exact_token(value: str, text: str) -> bool:
    return (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", text)
        is not None
    )


def _rss_official_candidates(venue: str, base: str, body: bytes) -> tuple[str, ...]:
    _require(b"<!DOCTYPE" not in body.upper(), "navigation XML DTD is forbidden")
    _require(b"<!ENTITY" not in body.upper(), "navigation XML entity is forbidden")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RequestPlanDiscoveryError("navigation response is not valid RSS XML") from exc
    candidates: list[str] = []
    instrument = f"{base}_USDT"
    for node in root.findall(".//item"):
        title = node.findtext("title") or ""
        link = (node.findtext("link") or "").strip()
        if not _exact_token(base, title) or not _exact_token(instrument, title):
            continue
        try:
            _validate_official_source_url(venue, link)
        except IdentityVerificationError:
            continue
        candidates.append(link)
    return tuple(sorted(set(candidates)))


def _canonical_identifier_from_official_page(base: str, body: bytes) -> str:
    try:
        source = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestPlanDiscoveryError("official response is not valid UTF-8") from exc
    extractor = _VisibleTextExtractor()
    extractor.feed(source)
    extractor.close()
    text = extractor.text()
    text = re.sub(r"\s+", " ", text)
    labels = list(CONTRACT_ADDRESS_PATTERN.finditer(text))
    _require(labels, "official page has no canonical identifier label")
    identifiers: set[str] = set()
    for label in labels:
        start = max(0, label.start() - VISIBLE_CONTEXT_RADIUS)
        end = min(len(text), label.end() + VISIBLE_CONTEXT_RADIUS)
        context = text[start:end]
        if not _exact_token(base, context):
            continue
        if not _exact_token(f"{base}_USDT", context):
            continue
        identifiers.update(EVM_IDENTIFIER_PATTERN.findall(context))
    _require(
        len({value.lower() for value in identifiers}) == 1,
        "official page has no unique canonical identifier bound to the exact instrument",
    )
    return sorted(identifiers, key=str.lower)[0]


def _request_plan_item(
    *, venue: str, base: str, official_url: str, identifier: str
) -> dict[str, str]:
    assertion = json.dumps(
        {
            "base_ticker": base,
            "canonical_asset_identifier_label": "contract_address",
            "canonical_asset_identifier_value": identifier,
            "instrument_id": f"{base}_USDT",
            "venue": venue,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    item = {
        "venue": venue,
        "official_source_url": official_url,
        "instrument_id": f"{base}_USDT",
        "base_ticker": base,
        "canonical_asset_identifier_namespace": "EVM_CONTRACT",
        "canonical_asset_identifier_value": identifier,
        "canonical_asset_identifier_label": "contract_address",
        "evidence_locator_type": "CANONICAL_REQUIRED_EXACT_UTF8_TOKENS_V1",
        "evidence_locator_value": assertion,
        "sanitized_evidence_fragment": assertion,
    }
    try:
        _validate_request_plan_item(item)
    except IdentityVerificationError as exc:
        raise RequestPlanDiscoveryError("discovered request plan is incompatible") from exc
    return item


def discover_request_plan(
    plan: Mapping[str, Any],
    *,
    fetch: Any,
) -> RequestPlanDiscoveryResult:
    del plan, fetch
    raise RequestPlanDiscoveryError(
        "network discovery execution is not authorized in the offline phase"
    )


def _discover_request_plan_from_fixture_responses(
    plan: Mapping[str, Any],
    *,
    responses: Mapping[str, FetchedResponse],
) -> RequestPlanDiscoveryResult:
    validate_discovery_plan(plan)
    _require(type(responses) is dict, "synthetic responses must be a plain object")
    request_count = 0
    requests_by_url: dict[str, int] = {}
    hashes: dict[str, list[str]] = {
        "metadata": [],
        "navigation": [],
        "official": [],
    }

    def fixture_response(url: str, category: str) -> bytes:
        nonlocal request_count
        _require(
            request_count < MAX_TOTAL_HTTP_REQUESTS,
            "synthetic fixture response cap exceeded",
        )
        requests_by_url[url] = requests_by_url.get(url, 0) + 1
        _require(
            requests_by_url[url] <= MAX_ATTEMPTS_PER_URL,
            "synthetic fixture duplicate URL exceeds frozen cap",
        )
        request_count += 1
        _require(url in responses, "synthetic fixture response is missing")
        body = _validated_response(responses[url], url)
        hashes[category].append(hashlib.sha256(body).hexdigest())
        return body

    active: dict[str, tuple[str, ...]] = {}
    for venue in VENUES:
        body = fixture_response(OFFICIAL_METADATA_ENDPOINTS[venue], "metadata")
        try:
            payload = _strict_json_loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RequestPlanDiscoveryError(
                f"{venue} metadata response is not valid JSON"
            ) from exc
        try:
            active[venue] = (
                _active_mexc_instruments(payload)
                if venue == "mexc"
                else _active_gateio_instruments(payload)
            )
        except IdentityVerificationError as exc:
            raise RequestPlanDiscoveryError(
                f"{venue} metadata response violates the exact contract"
            ) from exc

    request_plan: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for item in plan["seed_items"]:
        venue = str(item["venue"])
        base = str(item["base_ticker"])
        instrument = str(item["instrument_id"])
        pair = f"{venue}:{base}"
        if instrument not in active[venue]:
            unresolved.append(f"{pair}:ACTIVE_PERPETUAL_METADATA_MISSING")
            continue
        try:
            rss = fixture_response(str(item["search_url"]), "navigation")
            candidates = _rss_official_candidates(venue, base, rss)
        except RequestPlanDiscoveryError:
            unresolved.append(f"{pair}:NAVIGATION_RESPONSE_INVALID")
            continue
        if len(candidates) != 1:
            reason = (
                "EXACT_OFFICIAL_URL_NOT_FOUND"
                if not candidates
                else "AMBIGUOUS_OFFICIAL_URL"
            )
            unresolved.append(f"{pair}:{reason}")
            continue
        official_url = candidates[0]
        try:
            official_body = fixture_response(official_url, "official")
            identifier = _canonical_identifier_from_official_page(base, official_body)
            request_plan.append(
                _request_plan_item(
                    venue=venue,
                    base=base,
                    official_url=official_url,
                    identifier=identifier,
                )
            )
        except RequestPlanDiscoveryError:
            unresolved.append(f"{pair}:CANONICAL_IDENTIFIER_NOT_UNIQUE")

    complete = len(request_plan) == len(BASES) * len(VENUES) and not unresolved
    return RequestPlanDiscoveryResult(
        status=(
            "SYNTHETIC_FIXTURE_REQUEST_PLAN_COMPATIBLE"
            if complete
            else "SYNTHETIC_FIXTURE_INCOMPLETE"
        ),
        request_plan=tuple(request_plan),
        unresolved_pairs=tuple(unresolved),
        metadata_response_hashes=tuple(sorted(set(hashes["metadata"]))),
        navigation_response_hashes=tuple(sorted(set(hashes["navigation"]))),
        official_response_hashes=tuple(sorted(set(hashes["official"]))),
        request_count=request_count,
    )


def write_discovery_output(
    output_path: str | Path,
    *,
    plan: Mapping[str, Any],
    result: RequestPlanDiscoveryResult,
    runtime_manifest_binding: Mapping[str, Any],
    generated_at_utc: str,
) -> dict[str, Any]:
    del output_path, plan, result, runtime_manifest_binding, generated_at_utc
    raise RequestPlanDiscoveryError(
        "identity output creation is not authorized in the offline phase"
    )


def preflight_execution(
    *,
    runtime_manifest_path: str | Path,
    execution_manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    result = {
        "status": "BLOCKED_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL",
        "reason": "exact discovery execution approval is missing",
        "run_id": RUN_ID,
        "runtime_manifest_path": os.fspath(runtime_manifest_path),
        "execution_manifest_path": os.fspath(execution_manifest_path),
        "output_path": os.fspath(output_path),
        "network_accessed": False,
        "output_created": False,
    }
    try:
        runtime_path = _local_lexical_path(
            runtime_manifest_path,
            "runtime manifest path",
            require_repo_path=True,
        )
        execution_path = _local_lexical_path(
            execution_manifest_path,
            "execution manifest path",
            require_repo_path=False,
        )
        output = _local_lexical_path(
            output_path,
            "output path",
            require_repo_path=False,
        )
    except RequestPlanDiscoveryError as exc:
        result["reason"] = str(exc)
        return result
    result["runtime_manifest_path"] = str(runtime_path)
    result["execution_manifest_path"] = str(execution_path)
    result["output_path"] = str(output)
    if not runtime_path.is_file():
        result["reason"] = "runtime manifest is missing"
        return result
    try:
        _, _, runtime_manifest = _read_json_snapshot(
            runtime_path, "discovery runtime manifest"
        )
        validate_runtime_manifest(runtime_manifest, _require_repo_plan=True)
    except RequestPlanDiscoveryError:
        result["reason"] = "runtime manifest is invalid"
        return result
    result["reason"] = (
        "execution path is not implemented; execution manifest was not read; "
        "new code-bound refreeze is required"
    )
    return result


__all__ = [
    "BASES",
    "DISCOVERY_PLAN_SCHEMA",
    "FetchedResponse",
    "RequestPlanDiscoveryError",
    "RequestPlanDiscoveryResult",
    "RUNTIME_MANIFEST_SCHEMA",
    "build_discovery_plan",
    "build_runtime_manifest",
    "canonical_hash_without",
    "discover_request_plan",
    "freeze_offline_bundle",
    "preflight_execution",
    "validate_discovery_plan",
    "validate_runtime_manifest",
    "write_discovery_output",
]
