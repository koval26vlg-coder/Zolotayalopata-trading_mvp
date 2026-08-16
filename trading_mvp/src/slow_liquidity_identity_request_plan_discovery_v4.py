from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import slow_liquidity_identity_request_plan_discovery as discovery_v2
from . import slow_liquidity_official_currentness_topology_v4 as topology_v4
from . import slow_liquidity_official_identity_verification as identity_runtime
from .slow_liquidity_official_identity_verification import (
    FetchedResponse,
    OFFICIAL_METADATA_ENDPOINTS,
)


RUN_ID = "slow_liquidity_identity_request_plan_discovery_20260816_v4"
RUNTIME_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_identity_request_plan_discovery_runtime_manifest_v4"
)
RUNTIME_MANIFEST_STATUS = "FROZEN_OFFLINE_V4_STANDING_PUBLIC_RESEARCH"
EXECUTION_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_identity_request_plan_discovery_execution_manifest_v4"
)
EXECUTION_APPROVED_STATUS = (
    "FROZEN_V4_WITH_EXACT_REQUEST_PLAN_DISCOVERY_EXECUTION_APPROVAL"
)
EXECUTION_RECEIPT_SCHEMA = (
    "trading_mvp_slow_liquidity_identity_request_plan_discovery_"
    "execution_approval_receipt_v4"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT_DISCOVERY_PLAN_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-identity-request-plan-discovery-20260813-v2/plan.json"
)
PARENT_DISCOVERY_RUNTIME_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-identity-request-plan-discovery-20260813-v2/"
    "runtime-manifest.json"
)
TOPOLOGY_RUNTIME_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-currentness-topology-runtime-"
    "manifest-20260814-v4.json"
)
TOPOLOGY_OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-official-"
    r"currentness-topology\slow_liquidity_official_currentness_topology_"
    r"discovery_20260814_v4"
)
TOPOLOGY_OUTPUT_MANIFEST_PATH = TOPOLOGY_OUTPUT_ROOT / "manifest.json"
TOPOLOGY_OUTPUT_PATH = TOPOLOGY_OUTPUT_ROOT / "topology.json"
IDENTITY_RUNTIME_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-identity-runtime-manifest-20260815-v7.json"
)
IDENTITY_RUNTIME_MODULE_PATH = Path(identity_runtime.__file__).resolve()
RUNTIME_MODULE_PATH = Path(__file__).resolve()
SYNTHETIC_TESTS_PATH = (
    REPO_ROOT
    / "trading_mvp/tests/test_slow_liquidity_identity_request_plan_discovery_v4.py"
)
VISIBLE_LAUNCHER_PATH = (
    REPO_ROOT
    / "tools/start_exact_approved_slow_liquidity_identity_request_plan_"
    "discovery_v4_visible.ps1"
)
RUNTIME_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-identity-request-plan-discovery-runtime-"
    "manifest-20260816-v4-r6.json"
)
EXECUTION_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-identity-request-plan-discovery-execution-"
    "manifest-20260816-v4.json"
)
TOPOLOGY_EXECUTION_MANIFEST_PATH = (
    REPO_ROOT
    / "docs/plans/slow-liquidity-official-currentness-topology-execution-"
    "manifest-20260814-v4.json"
)
TOPOLOGY_LAUNCH_RECORD_PATH = (
    REPO_ROOT
    / "docs/agent-log/run-gates/slow_liquidity_official_currentness_topology_"
    "discovery_20260814_v4.launch.json"
)
APPROVAL_RECEIPT_PATH = (
    REPO_ROOT
    / "docs/agent-log/approvals/2026-08-16-slow-liquidity-identity-request-"
    "plan-discovery-v4-execution-approval.json"
)
LAUNCH_RECORD_PATH = (
    REPO_ROOT
    / "docs/agent-log/run-gates/"
    f"{RUN_ID}.launch.json"
)
LAUNCHER_CAPABILITY_PATH = (
    REPO_ROOT
    / "docs/agent-log/run-gates/"
    f"{RUN_ID}.capability.json"
)
PARENT_DISCOVERY_MODULE_PATH = discovery_v2.MODULE_PATH
GUARD_CHECKER_PATH = REPO_ROOT / "tools/check_trading_mvp_autopilot.ps1"
AUTOPILOT_GUARD_MODULE_PATH = REPO_ROOT / "trading_mvp/src/autopilot_guard.py"
READINESS_MODULE_PATH = (
    REPO_ROOT / "trading_mvp/src/one_week_edge_sprint_readiness.py"
)
OUTPUT_PATH = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\slow-liquidity-identity-"
    r"request-plan\slow_liquidity_identity_request_plan_discovery_20260816_v4"
)

BASES = discovery_v2.BASES
VENUES = discovery_v2.VENUES
MAX_TOTAL_HTTP_REQUESTS = discovery_v2.MAX_TOTAL_HTTP_REQUESTS
MAX_ATTEMPTS_PER_URL = discovery_v2.MAX_ATTEMPTS_PER_URL
MAX_RESPONSE_BYTES = discovery_v2.MAX_RESPONSE_BYTES
MAX_RUNTIME_SEC = discovery_v2.MAX_RUNTIME_SEC
HARD_OUTPUT_CAP_BYTES = discovery_v2.HARD_OUTPUT_CAP_BYTES
MAX_TOTAL_RESPONSE_BYTES = 20_000_000
STREAM_CHUNK_BYTES = 64 * 1024
OVERSIZE_POLICIES = {
    "metadata": "fail_run_required_body",
    "navigation": "fail_run_required_body",
    "official": "fail_run_required_body",
    "optional_topology": "record_only",
}

PARENT_DISCOVERY_PLAN_FILE_SHA256 = (
    "501f42f7f418fcc07522f8df8a59db38db106cd3d2ae86cc598ffb19af34afe4"
)
PARENT_DISCOVERY_PLAN_HASH = (
    "6246471964815d139e6900298a2a78e80e830df40f0c06b39078487c254183cc"
)
PARENT_DISCOVERY_RUNTIME_FILE_SHA256 = (
    "0e2dfa6be70c289a877f9660d2ef58adca4c05276d38bfc8d99c4b8e703b250d"
)
PARENT_DISCOVERY_RUNTIME_HASH = (
    "f2cedc562660b25da6d0eac1845deb2e4ef17ba38782867ed49792f13fb392e1"
)
PARENT_DISCOVERY_MODULE_FILE_SHA256 = (
    "bae92d9c0d0f2a1ad4b63e49b335ae44aa96aa98bd1d67f140c706111ba2024e"
)
TOPOLOGY_RUNTIME_FILE_SHA256 = (
    "ddea956647b0110d079a191a0653dd66bd27e675df9d0b01b1e3e3f6b825aba6"
)
TOPOLOGY_RUNTIME_HASH = (
    "9ab770ba4e3a857d5a2dee8ba74260a8d7d717080afb411abab009a3ccf508c0"
)
TOPOLOGY_EXECUTION_FILE_SHA256 = (
    "cd2387b4ac6f1bdd91091e94c1d52f2509cfe56e4aadfb83a706bcf6efd3e817"
)
TOPOLOGY_EXECUTION_HASH = (
    "66333bb0410d45b84de5cf9250e07e53d905cb98e3c5a6689b336d1e18a75091"
)
TOPOLOGY_LAUNCH_RECORD_FILE_SHA256 = (
    "2af92b5b07b9c98fb8dc7ba17d46d6ebe69205cd426a8c0a0208b39ee02575de"
)
TOPOLOGY_OUTPUT_MANIFEST_FILE_SHA256 = (
    "e632634b8619e092b6873a7f847da2d2fcb188e74fb07afb67128632d76d2b82"
)
TOPOLOGY_OUTPUT_MANIFEST_HASH = (
    "760fd335ef3a4eecc3286526d2192e769476d73daab8f960305ec2b04e03aa94"
)
TOPOLOGY_OUTPUT_FILE_SHA256 = (
    "e0bd139724034dee1b37d2173814a70a8029d3f6a10d5e4059982bda2fa5aeaa"
)
TOPOLOGY_OUTPUT_HASH = (
    "3e2ca0be86d57dcd3182d515ca0185e92f10748ca08e2926f6c34aac9d7343c7"
)
IDENTITY_RUNTIME_FILE_SHA256 = (
    "254fb38dae1457b0a87e47adb3aefac4a77e6d3224dc792c6aa5076cbf81555f"
)
IDENTITY_RUNTIME_HASH = (
    "00d991885d49116651a5bb69345e694acf9df05fb0c4be7bf30b6c15e333137d"
)
OFFLINE_AUTHORIZATION_TEXT = (
    "Standing policy разрешает same-scope public request-plan discovery после "
    "offline-refreeze v4, synthetic tests, immutable manifest, policy/readiness "
    "rebind и свежих технических guards. Без private API, реальных средств, "
    "второго writer, redirects, proxies или retries."
)
BLOCKED_EXIT_CODE = 3


class RequestPlanDiscoveryV4Error(ValueError):
    def __init__(
        self,
        message: str,
        *,
        response_audit: Mapping[str, Any] | None = None,
        total_response_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.response_audit = copy.deepcopy(dict(response_audit)) if response_audit else None
        self.total_response_bytes = total_response_bytes


class ResponseCapExceeded(RequestPlanDiscoveryV4Error):
    pass


class TotalResponseCapExceeded(RequestPlanDiscoveryV4Error):
    pass


@dataclass(frozen=True, slots=True)
class ResponseAudit:
    requested_url: str
    final_url: str
    status: int
    resource_kind: str
    declared_length: int | None
    bytes_read: int
    complete: bool
    truncated: bool
    reason: str | None
    body_sha256: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status": self.status,
            "resource_kind": self.resource_kind,
            "declared_length": self.declared_length,
            "bytes_read": self.bytes_read,
            "complete": self.complete,
            "truncated": self.truncated,
            "reason": self.reason,
            "body_sha256": self.body_sha256,
        }


@dataclass(frozen=True, slots=True)
class StreamedResponse:
    requested_url: str
    final_url: str
    status: int
    body: bytes | None
    audit: ResponseAudit


@dataclass(frozen=True, slots=True)
class RequestPlanDiscoveryV4Result:
    status: str
    request_plan: tuple[dict[str, Any], ...]
    unresolved_pairs: tuple[str, ...]
    metadata_response_hashes: tuple[str, ...]
    navigation_response_hashes: tuple[str, ...]
    official_response_hashes: tuple[str, ...]
    request_count: int
    response_audits: tuple[dict[str, Any], ...]
    total_response_bytes: int


@dataclass(frozen=True, slots=True)
class RequestPlanDiscoveryV4ExecutionCapability:
    run_id: str
    runtime_manifest_hash: str
    execution_manifest_hash: str
    output_path: str
    not_before_local: str
    latest_launch_local: str
    hard_deadline_local: str


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RequestPlanDiscoveryV4Error("payload is not canonical JSON") from exc


def canonical_hash_without(payload: Mapping[str, Any], field: str) -> str:
    normalized = copy.deepcopy(dict(payload))
    normalized.pop(field, None)
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RequestPlanDiscoveryV4Error(message)


def _require_hash(value: Any, label: str) -> str:
    normalized = str(value or "").lower()
    _require(re.fullmatch(r"[0-9a-f]{64}", normalized) is not None, f"{label} is invalid")
    return normalized


def _validate_timestamp(value: Any, label: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RequestPlanDiscoveryV4Error(f"{label} is invalid") from exc
    _require(parsed.tzinfo is not None, f"{label} has no timezone")
    return text


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestPlanDiscoveryV4Error(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: str | Path, label: str) -> tuple[bytes, dict[str, Any]]:
    candidate = Path(path).expanduser().resolve()
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise RequestPlanDiscoveryV4Error(f"{label} is unavailable") from exc
    _require(0 < len(raw) <= 25_000_000, f"{label} exceeds the local read cap")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                RequestPlanDiscoveryV4Error(f"invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestPlanDiscoveryV4Error(f"{label} is invalid JSON") from exc
    _require(isinstance(payload, dict), f"{label} is not a JSON object")
    return raw, payload


def _sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise RequestPlanDiscoveryV4Error(f"required file is unavailable: {path}") from exc


def _file_binding(path: str | Path) -> dict[str, str]:
    candidate = Path(path).expanduser().resolve()
    return {"path": str(candidate), "file_sha256": _sha256_file(candidate)}


def _exact_file(
    path: str | Path,
    expected_sha256: str,
    label: str,
) -> tuple[bytes, dict[str, Any]]:
    raw, payload = _read_json(path, label)
    _require(
        _sha256_bytes(raw) == expected_sha256,
        f"{label} file hash mismatch",
    )
    return raw, payload


def _validate_frozen_parent_runtime(manifest: Mapping[str, Any]) -> None:
    """Validate the immutable v2 envelope without revalidating stale transitive code."""
    _require(
        manifest.get("schema")
        == "trading_mvp_slow_liquidity_identity_request_plan_discovery_runtime_manifest_v1",
        "parent discovery runtime schema mismatch",
    )
    _require(
        manifest.get("status")
        == "FROZEN_OFFLINE_AWAIT_EXACT_DISCOVERY_EXECUTION_APPROVAL",
        "parent discovery runtime status mismatch",
    )
    _require(
        manifest.get("manifest_hash_method")
        == "sha256_canonical_json_excluding_manifest_hash",
        "parent discovery runtime hash method mismatch",
    )
    _require(
        manifest.get("manifest_hash") == PARENT_DISCOVERY_RUNTIME_HASH
        and canonical_hash_without(manifest, "manifest_hash")
        == PARENT_DISCOVERY_RUNTIME_HASH,
        "parent discovery runtime hash mismatch",
    )
    plan_binding = manifest.get("discovery_plan") or {}
    _require(
        plan_binding.get("file_sha256") == PARENT_DISCOVERY_PLAN_FILE_SHA256
        and plan_binding.get("plan_hash") == PARENT_DISCOVERY_PLAN_HASH,
        "parent discovery runtime PlanOnly binding mismatch",
    )
    runtime = manifest.get("runtime") or {}
    _require(
        runtime.get("module_sha256") == PARENT_DISCOVERY_MODULE_FILE_SHA256,
        "parent discovery runtime parser binding mismatch",
    )
    authorization = manifest.get("execution_authorization") or {}
    for field in (
        "approved",
        "actual_network_run_allowed",
        "official_source_content_read_allowed",
        "output_creation_allowed",
        "identity_output_allowed",
        "global_writer_claim_allowed",
    ):
        _require(
            authorization.get(field) is False,
            f"parent discovery runtime illegally enables {field}",
        )
    _require(
        authorization.get("execution_approval_receipt") is None,
        "parent discovery runtime contains an execution receipt",
    )


def _validate_frozen_identity_runtime(manifest: Mapping[str, Any]) -> None:
    _require(
        manifest.get("schema")
        == "trading_mvp_slow_liquidity_official_identity_runtime_manifest_v1",
        "identity v7 runtime schema mismatch",
    )
    _require(
        manifest.get("status")
        == "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
        "identity v7 runtime status mismatch",
    )
    _require(manifest.get("runtime_revision") == "v7", "identity runtime is not v7")
    _require(
        manifest.get("manifest_hash_method")
        == "sha256_canonical_json_excluding_manifest_hash",
        "identity v7 runtime hash method mismatch",
    )
    _require(
        manifest.get("manifest_hash") == IDENTITY_RUNTIME_HASH
        and canonical_hash_without(manifest, "manifest_hash") == IDENTITY_RUNTIME_HASH,
        "identity v7 runtime hash mismatch",
    )
    runtime = manifest.get("runtime") or {}
    _require(
        Path(str(runtime.get("module_path") or "")).resolve()
        == IDENTITY_RUNTIME_MODULE_PATH,
        "identity v7 runtime module path mismatch",
    )
    _require(
        isinstance(runtime.get("module_sha256"), str)
        and len(str(runtime.get("module_sha256"))) == 64,
        "identity v7 runtime module hash missing",
    )
    authorization = manifest.get("execution_authorization") or {}
    for field in (
        "approved",
        "actual_network_run_allowed",
        "official_source_content_read_allowed",
        "identity_output_allowed",
        "global_writer_claim_allowed",
        "runtime_can_mint_execution_approval",
        "launcher_can_mint_execution_approval",
    ):
        _require(
            authorization.get(field) is False,
            f"identity v7 runtime illegally enables {field}",
        )
    _require(
        authorization.get("execution_approval_receipt") is None,
        "identity v7 runtime contains an execution receipt",
    )


def _validate_lineage() -> dict[str, Any]:
    plan_raw, plan = _exact_file(
        PARENT_DISCOVERY_PLAN_PATH,
        PARENT_DISCOVERY_PLAN_FILE_SHA256,
        "parent request-plan discovery PlanOnly",
    )
    try:
        discovery_v2.validate_discovery_plan(plan)
    except discovery_v2.RequestPlanDiscoveryError as exc:
        raise RequestPlanDiscoveryV4Error("parent discovery PlanOnly is invalid") from exc
    _require(plan.get("plan_hash") == PARENT_DISCOVERY_PLAN_HASH, "parent plan hash mismatch")

    runtime_raw, parent_runtime = _exact_file(
        PARENT_DISCOVERY_RUNTIME_MANIFEST_PATH,
        PARENT_DISCOVERY_RUNTIME_FILE_SHA256,
        "parent request-plan discovery runtime",
    )
    _validate_frozen_parent_runtime(parent_runtime)
    _require(
        _sha256_file(PARENT_DISCOVERY_MODULE_PATH)
        == PARENT_DISCOVERY_MODULE_FILE_SHA256,
        "parent discovery parser module hash mismatch",
    )

    topology_runtime_raw, topology_runtime_manifest = _exact_file(
        TOPOLOGY_RUNTIME_MANIFEST_PATH,
        TOPOLOGY_RUNTIME_FILE_SHA256,
        "topology v4 runtime manifest",
    )
    try:
        topology_v4.validate_runtime_manifest(
            topology_runtime_manifest,
            repo_root=REPO_ROOT,
        )
    except topology_v4.TopologyDiscoveryError as exc:
        raise RequestPlanDiscoveryV4Error("topology v4 runtime is invalid") from exc
    _require(
        topology_runtime_manifest.get("manifest_hash") == TOPOLOGY_RUNTIME_HASH,
        "topology v4 runtime hash mismatch",
    )

    topology_execution_raw, topology_execution_manifest = _exact_file(
        TOPOLOGY_EXECUTION_MANIFEST_PATH,
        TOPOLOGY_EXECUTION_FILE_SHA256,
        "topology v4 execution manifest",
    )
    _require(
        topology_execution_manifest.get("manifest_hash") == TOPOLOGY_EXECUTION_HASH,
        "topology v4 execution hash mismatch",
    )
    try:
        topology_v4.validate_execution_manifest(
            topology_execution_manifest,
            runtime_manifest=topology_runtime_manifest,
            repo_root=REPO_ROOT,
        )
    except topology_v4.TopologyDiscoveryError as exc:
        raise RequestPlanDiscoveryV4Error("topology v4 execution is invalid") from exc

    launch_raw, launch = _exact_file(
        TOPOLOGY_LAUNCH_RECORD_PATH,
        TOPOLOGY_LAUNCH_RECORD_FILE_SHA256,
        "topology v4 terminal launch record",
    )
    _require(launch.get("status") == "COMPLETE", "topology v4 launch is not COMPLETE")
    _require(launch.get("run_id") == topology_v4.RUN_ID, "topology v4 launch run mismatch")
    _require(launch.get("retry_authorized") is False, "topology v4 launch retry changed")
    _require(launch.get("topology_output_created") is True, "topology v4 output was not created")

    output_manifest_raw, output_manifest = _exact_file(
        TOPOLOGY_OUTPUT_MANIFEST_PATH,
        TOPOLOGY_OUTPUT_MANIFEST_FILE_SHA256,
        "topology v4 output manifest",
    )
    _require(
        output_manifest.get("manifest_hash") == TOPOLOGY_OUTPUT_MANIFEST_HASH
        and canonical_hash_without(output_manifest, "manifest_hash")
        == TOPOLOGY_OUTPUT_MANIFEST_HASH,
        "topology v4 output manifest hash mismatch",
    )
    _require(
        output_manifest.get("status")
        == "COMPLETE_SANITIZED_TOPOLOGY_NOT_IDENTITY_EVIDENCE",
        "topology v4 output is not a completed sanitized topology",
    )
    for field in (
        "identity_evidence_created",
        "request_plan_created",
        "currentness_verdict_created",
        "raw_payload_persisted",
    ):
        _require(output_manifest.get(field) is False, f"topology output changed: {field}")

    topology_raw, topology = _exact_file(
        TOPOLOGY_OUTPUT_PATH,
        TOPOLOGY_OUTPUT_FILE_SHA256,
        "topology v4 sanitized output",
    )
    _require(
        topology.get("result_hash") == TOPOLOGY_OUTPUT_HASH
        and canonical_hash_without(topology, "result_hash") == TOPOLOGY_OUTPUT_HASH,
        "topology v4 result hash mismatch",
    )
    _require(topology.get("request_count") == 6, "topology v4 request count changed")
    _require(topology.get("raw_payload_persisted") is False, "topology raw payload appeared")
    _require(topology.get("identity_evidence_created") is False, "topology became identity evidence")

    identity_raw, identity = _exact_file(
        IDENTITY_RUNTIME_MANIFEST_PATH,
        IDENTITY_RUNTIME_FILE_SHA256,
        "identity runtime v7",
    )
    _validate_frozen_identity_runtime(identity)
    authorization = identity.get("execution_authorization") or {}
    _require(authorization.get("approved") is False, "identity v7 execution is open")

    return {
        "parent_discovery_plan": {
            "path": str(PARENT_DISCOVERY_PLAN_PATH),
            "file_sha256": _sha256_bytes(plan_raw),
            "plan_hash": plan["plan_hash"],
        },
        "parent_discovery_runtime": {
            "path": str(PARENT_DISCOVERY_RUNTIME_MANIFEST_PATH),
            "file_sha256": _sha256_bytes(runtime_raw),
            "manifest_hash": parent_runtime["manifest_hash"],
            "execution_authorized": False,
        },
        "parent_discovery_parser": {
            "path": str(PARENT_DISCOVERY_MODULE_PATH),
            "file_sha256": PARENT_DISCOVERY_MODULE_FILE_SHA256,
        },
        "topology_v4_runtime": {
            "path": str(TOPOLOGY_RUNTIME_MANIFEST_PATH),
            "file_sha256": _sha256_bytes(topology_runtime_raw),
            "manifest_hash": topology_runtime_manifest["manifest_hash"],
        },
        "topology_v4_execution": {
            "path": str(TOPOLOGY_EXECUTION_MANIFEST_PATH),
            "file_sha256": _sha256_bytes(topology_execution_raw),
            "manifest_hash": topology_execution_manifest["manifest_hash"],
        },
        "topology_v4_launch": {
            "path": str(TOPOLOGY_LAUNCH_RECORD_PATH),
            "file_sha256": _sha256_bytes(launch_raw),
            "status": "COMPLETE",
            "retry_authorized": False,
        },
        "topology_v4_output": {
            "status": output_manifest["status"],
            "manifest_path": str(TOPOLOGY_OUTPUT_MANIFEST_PATH),
            "manifest_file_sha256": _sha256_bytes(output_manifest_raw),
            "manifest_hash": output_manifest["manifest_hash"],
            "topology_path": str(TOPOLOGY_OUTPUT_PATH),
            "topology_file_sha256": _sha256_bytes(topology_raw),
            "topology_result_hash": topology["result_hash"],
            "identity_evidence_created": False,
            "request_plan_created": False,
        },
        "identity_runtime_v7": {
            "path": str(IDENTITY_RUNTIME_MANIFEST_PATH),
            "file_sha256": _sha256_bytes(identity_raw),
            "manifest_hash": identity["manifest_hash"],
            "execution_authorized": False,
        },
    }


def _authorized_scope(*, execution: bool) -> dict[str, bool]:
    return {
        "one_visible_public_read_only_request_plan_discovery_run": execution,
        "official_source_content_read": execution,
        "request_plan_output": execution,
        "global_writer_claim": execution,
        "approval_receipt_creation": False,
        "identity_output": False,
        "collector_or_evaluator": False,
        "oos_or_returns_or_pnl": False,
        "grid_or_retune": False,
        "execution_probe": False,
        "paper_or_live": False,
        "private_api_or_real_capital": False,
        "leverage_or_margin": False,
    }


def _limits() -> dict[str, int]:
    return {
        "maximum_total_http_requests": MAX_TOTAL_HTTP_REQUESTS,
        "maximum_attempts_per_url": MAX_ATTEMPTS_PER_URL,
        "maximum_response_bytes_per_request": MAX_RESPONSE_BYTES,
        "maximum_total_response_bytes": MAX_TOTAL_RESPONSE_BYTES,
        "stream_chunk_bytes": STREAM_CHUNK_BYTES,
        "max_runtime_sec": MAX_RUNTIME_SEC,
        "hard_output_cap_bytes": HARD_OUTPUT_CAP_BYTES,
    }


def build_runtime_manifest(*, generated_at_utc: str) -> dict[str, Any]:
    _validate_timestamp(generated_at_utc, "runtime manifest timestamp")
    lineage = _validate_lineage()
    runtime_files = {
        "module": _file_binding(RUNTIME_MODULE_PATH),
        "synthetic_tests": _file_binding(SYNTHETIC_TESTS_PATH),
        "visible_launcher": _file_binding(VISIBLE_LAUNCHER_PATH),
        "identity_runtime_module": {
            "path": str(IDENTITY_RUNTIME_MODULE_PATH),
            "file_sha256": str(
                ((_read_json(IDENTITY_RUNTIME_MANIFEST_PATH, "identity v7 runtime")[1].get("runtime") or {}).get("module_sha256") or "")
            ),
        },
        "guard_checker": _file_binding(GUARD_CHECKER_PATH),
        "autopilot_guard_module": _file_binding(AUTOPILOT_GUARD_MODULE_PATH),
        "readiness_module": _file_binding(READINESS_MODULE_PATH),
    }
    manifest: dict[str, Any] = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "status": RUNTIME_MANIFEST_STATUS,
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "run_id": RUN_ID,
        "lineage": lineage,
        "runtime": {
            **runtime_files,
            "network_adapter_implemented": True,
            "execution_manifest_validator_implemented": True,
            "request_plan_writer_implemented": True,
            "visible_launcher_implemented": True,
            "preflight_only_enabled": True,
            "runtime_can_mint_execution_approval": False,
            "launcher_can_mint_execution_approval": False,
        },
        "offline_authorization": {
            "mode": "DIRECT_EXACT_USER_APPROVAL_OFFLINE_ONLY_NOT_A_RECEIPT",
            "user_authorization_text": OFFLINE_AUTHORIZATION_TEXT,
            "approval_receipt_created": False,
            "authorized_scope": {
                "runtime_implementation": True,
                "synthetic_tests": True,
                "immutable_manifest": True,
                "visible_launcher_implementation": True,
                "preflight_only": True,
                "policy_readiness_rebind": True,
            },
            "not_authorized": {
                "network": True,
                "approval_receipt": True,
                "writer_claim": True,
                "request_plan_output": True,
                "identity_output": True,
                "visible_launcher_execution": True,
            },
        },
        "compatibility_contract": {
            "consumer_runtime": "slow_liquidity_official_identity_verification_v7",
            "required_pair_count": len(BASES) * len(VENUES),
            "venues": list(VENUES),
            "bases": list(BASES),
            "instrument_template": "{BASE}_USDT",
            "request_plan_items_must_pass_consumer_validator": True,
        },
        "navigation_contract": copy.deepcopy(
            _load_exact_parent_plan(
                json.loads(PARENT_DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
            )["navigation_contract"]
        ),
        "topology_consumption_contract": {
            "completed_sanitized_topology_v4_required": True,
            "topology_is_lineage_and_route_provenance": True,
            "topology_is_not_identity_evidence": True,
            "topology_does_not_authorize_network": True,
            "topology_does_not_prove_exhaustiveness": True,
        },
        "limits": _limits(),
        "response_streaming_contract": {
            "enabled": True,
            "headers_read_before_body": True,
            "body_read_mode": "bounded_stream",
            "raw_payload_persisted": False,
            "audit_fields": [
                "complete",
                "truncated",
                "declared_length",
                "bytes_read",
                "reason",
            ],
            "oversize_policies": copy.deepcopy(OVERSIZE_POLICIES),
        },
        "output_contract": {
            "output_path": str(OUTPUT_PATH),
            "required_files": ["request-plan.json", "manifest.json"],
            "immutable_exclusive_create": True,
            "raw_payload_persistence_allowed": False,
            "search_payload_persistence_allowed": False,
            "free_form_evidence_persistence_allowed": False,
            "identity_output_created": False,
            "identity_verdict_created": False,
        },
        "execution_authorization": {
            "approved": False,
            "execution_approval_receipt": None,
            "execution_manifest": None,
            "network_run_allowed": False,
            "official_source_content_read_allowed": False,
            "request_plan_output_allowed": False,
            "global_writer_claim_allowed": False,
            "visible_launcher_execution_allowed": False,
            "standing_same_scope_public_research_allowed": True,
            "standing_required_guard_decision": (
                "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4"
            ),
            "runtime_can_mint_execution_approval": False,
            "launcher_can_mint_execution_approval": False,
            "separate_exact_code_bound_execution_approval_required": False,
            "future_required_guard_decision": (
                "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4"
            ),
            "future_execution_manifest_path": str(EXECUTION_MANIFEST_PATH),
            "future_approval_receipt_path": str(APPROVAL_RECEIPT_PATH),
            "single_use": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "preflight_contract": {
            "status": "READY_FOR_STANDING_PUBLIC_RESEARCH_EXECUTION",
            "blocked_cli_exit_code": BLOCKED_EXIT_CODE,
            "runtime_manifest_must_be_validated": True,
            "execution_manifest_must_not_be_read": True,
            "network_must_not_be_accessed": True,
            "global_writer_must_not_be_claimed": True,
            "output_must_not_be_created": True,
            "visible_launcher_must_not_execute": True,
        },
        "safety": {
            "network_accessed_while_freezing": False,
            "official_source_content_read_while_freezing": False,
            "approval_receipt_created": False,
            "execution_manifest_created": False,
            "global_writer_claim_created": False,
            "request_plan_output_created": False,
            "identity_output_created": False,
            "visible_launcher_executed": False,
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


def validate_runtime_manifest(manifest: Mapping[str, Any]) -> None:
    _require(isinstance(manifest, Mapping), "runtime manifest is missing")
    _require(manifest.get("schema") == RUNTIME_MANIFEST_SCHEMA, "runtime manifest schema mismatch")
    _require(manifest.get("status") == RUNTIME_MANIFEST_STATUS, "runtime manifest status mismatch")
    _require(
        manifest.get("manifest_hash_method")
        == "sha256_canonical_json_excluding_manifest_hash",
        "runtime manifest hash method mismatch",
    )
    observed = _require_hash(manifest.get("manifest_hash"), "runtime manifest hash")
    _require(
        canonical_hash_without(manifest, "manifest_hash") == observed,
        "runtime manifest hash mismatch",
    )
    expected = build_runtime_manifest(
        generated_at_utc=_validate_timestamp(
            manifest.get("generated_at_utc"),
            "runtime manifest timestamp",
        )
    )
    _require(dict(manifest) == expected, "runtime manifest differs from exact offline freeze")


def build_standing_execution_capability(
    runtime_manifest: Mapping[str, Any],
) -> RequestPlanDiscoveryV4ExecutionCapability:
    """Build a technical capability from standing policy, not a user receipt."""
    validate_runtime_manifest(runtime_manifest)
    authorization = runtime_manifest.get("execution_authorization") or {}
    _require(
        authorization.get("standing_same_scope_public_research_allowed") is True,
        "standing public research is not enabled by the runtime contract",
    )
    _require(
        authorization.get("separate_exact_code_bound_execution_approval_required")
        is False,
        "runtime still requires a separate execution approval",
    )
    return RequestPlanDiscoveryV4ExecutionCapability(
        run_id=RUN_ID,
        runtime_manifest_hash=str(runtime_manifest["manifest_hash"]),
        execution_manifest_hash=str(runtime_manifest["manifest_hash"]),
        output_path=str(OUTPUT_PATH),
        not_before_local="1970-01-01T00:00:00+00:00",
        latest_launch_local="9999-12-31T23:59:59+00:00",
        hard_deadline_local="9999-12-31T23:59:59+00:00",
    )


def write_runtime_manifest(
    path: str | Path,
    manifest: Mapping[str, Any],
) -> Path:
    validate_runtime_manifest(manifest)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(dict(manifest))
    try:
        with target.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RequestPlanDiscoveryV4Error("runtime manifest already exists") from exc
    return target


def _load_exact_parent_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    try:
        raw = PARENT_DISCOVERY_PLAN_PATH.read_bytes()
        frozen = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestPlanDiscoveryV4Error("exact parent plan is unavailable") from exc
    if _sha256_bytes(raw) != PARENT_DISCOVERY_PLAN_FILE_SHA256:
        raise RequestPlanDiscoveryV4Error("exact parent plan file hash mismatch")
    if frozen.get("plan_hash") != PARENT_DISCOVERY_PLAN_HASH:
        raise RequestPlanDiscoveryV4Error("exact parent plan canonical hash mismatch")
    if dict(plan) != frozen:
        raise RequestPlanDiscoveryV4Error("exact parent plan binding mismatch")
    try:
        discovery_v2.validate_discovery_plan(frozen)
    except discovery_v2.RequestPlanDiscoveryError as exc:
        raise RequestPlanDiscoveryV4Error("exact parent plan is invalid") from exc
    return frozen


def _complete_fixture_response(response: FetchedResponse, resource_kind: str) -> StreamedResponse:
    body = response.body
    if type(body) is not bytes:
        raise RequestPlanDiscoveryV4Error("fixture response body must be bytes")
    audit = ResponseAudit(
        requested_url=response.requested_url,
        final_url=response.final_url,
        status=int(response.status),
        resource_kind=resource_kind,
        declared_length=len(body),
        bytes_read=len(body),
        complete=True,
        truncated=False,
        reason=None,
        body_sha256=_sha256_bytes(body),
    )
    return StreamedResponse(
        requested_url=response.requested_url,
        final_url=response.final_url,
        status=int(response.status),
        body=body,
        audit=audit,
    )


def _coerce_response(response: Any, resource_kind: str) -> StreamedResponse:
    if type(response) is FetchedResponse:
        return _complete_fixture_response(response, resource_kind)
    if type(response) is not StreamedResponse:
        raise RequestPlanDiscoveryV4Error("fetch response type changed")
    if response.audit.resource_kind != resource_kind:
        raise RequestPlanDiscoveryV4Error("response resource kind mismatch")
    return response


def _validated_response(
    response: StreamedResponse,
    expected_url: str,
    resource_kind: str,
) -> bytes:
    response = _coerce_response(response, resource_kind)
    audit = response.audit
    if response.requested_url != expected_url or audit.requested_url != expected_url:
        raise RequestPlanDiscoveryV4Error("requested URL mismatch")
    if response.final_url != expected_url or audit.final_url != expected_url:
        raise RequestPlanDiscoveryV4Error(
            "HTTP redirect is forbidden",
            response_audit=audit.as_dict(),
        )
    if response.status != 200 or audit.status != 200:
        raise RequestPlanDiscoveryV4Error("HTTP response status is not 200")
    if not 0 <= audit.bytes_read <= MAX_RESPONSE_BYTES:
        raise RequestPlanDiscoveryV4Error("response audit bytes_read exceeds cap")
    if audit.truncated:
        if OVERSIZE_POLICIES[resource_kind] == "record_only":
            return b""
        raise ResponseCapExceeded(
            "HTTP response body exceeds cap",
            response_audit=audit.as_dict(),
        )
    if not audit.complete:
        raise RequestPlanDiscoveryV4Error(
            "HTTP response body is incomplete",
            response_audit=audit.as_dict(),
        )
    if type(response.body) is not bytes:
        raise RequestPlanDiscoveryV4Error("HTTP response body must be bytes")
    if not 0 < len(response.body) <= MAX_RESPONSE_BYTES:
        raise RequestPlanDiscoveryV4Error("HTTP response body is empty or exceeds cap")
    if audit.bytes_read != len(response.body):
        raise RequestPlanDiscoveryV4Error("response audit bytes_read mismatch")
    if audit.body_sha256 != _sha256_bytes(response.body):
        raise RequestPlanDiscoveryV4Error("response audit body hash mismatch")
    return response.body


def discover_request_plan(
    plan: Mapping[str, Any],
    *,
    fetch: Callable[[str, str], StreamedResponse | FetchedResponse],
    monotonic: Callable[[], float] = time.monotonic,
) -> RequestPlanDiscoveryV4Result:
    frozen = _load_exact_parent_plan(plan)
    started = monotonic()
    responses: dict[str, FetchedResponse] = {}
    attempts: dict[str, int] = {}
    response_audits: list[dict[str, Any]] = []
    request_count = 0
    total_response_bytes = 0

    def fetch_once(url: str, resource_kind: str) -> FetchedResponse:
        nonlocal request_count, total_response_bytes
        if monotonic() - started > MAX_RUNTIME_SEC:
            raise RequestPlanDiscoveryV4Error("request-plan discovery deadline exceeded")
        if request_count >= MAX_TOTAL_HTTP_REQUESTS:
            raise RequestPlanDiscoveryV4Error("request-plan discovery request cap exceeded")
        attempts[url] = attempts.get(url, 0) + 1
        if attempts[url] > MAX_ATTEMPTS_PER_URL:
            raise RequestPlanDiscoveryV4Error("attempt cap per URL exceeded")
        request_count += 1
        response = _coerce_response(fetch(url, resource_kind), resource_kind)
        audit = response.audit.as_dict()
        response_audits.append(audit)
        body = _validated_response(response, url, resource_kind)
        total_response_bytes += response.audit.bytes_read
        if total_response_bytes > MAX_TOTAL_RESPONSE_BYTES:
            raise TotalResponseCapExceeded(
                "total response body bytes exceed cap",
                response_audit=audit,
                total_response_bytes=total_response_bytes,
            )
        responses[url] = FetchedResponse(url, url, response.status, body)
        return responses[url]

    for venue in VENUES:
        fetch_once(OFFICIAL_METADATA_ENDPOINTS[venue], "metadata")
    for item in frozen["seed_items"]:
        search_url = str(item["search_url"])
        search_response = fetch_once(search_url, "navigation")
        try:
            candidates = discovery_v2._rss_official_candidates(  # noqa: SLF001
                str(item["venue"]),
                str(item["base_ticker"]),
                search_response.body,
            )
        except discovery_v2.RequestPlanDiscoveryError as exc:
            raise RequestPlanDiscoveryV4Error(
                "navigation response violates the exact contract"
            ) from exc
        if len(candidates) == 1:
            official_url = candidates[0]
            if official_url in responses:
                raise RequestPlanDiscoveryV4Error(
                    "official URL is reused across venue/base pairs"
                )
            fetch_once(official_url, "official")

    try:
        parsed = discovery_v2._discover_request_plan_from_fixture_responses(  # noqa: SLF001
            frozen,
            responses=responses,
        )
    except discovery_v2.RequestPlanDiscoveryError as exc:
        raise RequestPlanDiscoveryV4Error(
            "request-plan discovery result violates the exact contract"
        ) from exc
    complete = (
        len(parsed.request_plan) == len(BASES) * len(VENUES)
        and not parsed.unresolved_pairs
        and parsed.request_count == MAX_TOTAL_HTTP_REQUESTS
    )
    return RequestPlanDiscoveryV4Result(
        status=(
            "COMPLETE_EXACT_REQUEST_PLAN"
            if complete
            else "STOPPED_INCOMPLETE_EXACT_REQUEST_PLAN"
        ),
        request_plan=tuple(copy.deepcopy(item) for item in parsed.request_plan),
        unresolved_pairs=tuple(parsed.unresolved_pairs),
        metadata_response_hashes=tuple(parsed.metadata_response_hashes),
        navigation_response_hashes=tuple(parsed.navigation_response_hashes),
        official_response_hashes=tuple(parsed.official_response_hashes),
        request_count=request_count,
        response_audits=tuple(copy.deepcopy(response_audits)),
        total_response_bytes=total_response_bytes,
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def fetch_public_response(
    url: str,
    *,
    timeout_sec: float,
    resource_kind: str = "official",
) -> StreamedResponse:
    _require(0.0 < timeout_sec <= 30.0, "HTTP timeout is outside the exact cap")
    _require(resource_kind in OVERSIZE_POLICIES, "unknown response resource kind")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json, application/xml, text/xml, text/html, application/rss+xml;q=0.9, */*;q=0.1",
            "Accept-Encoding": "identity",
            "User-Agent": "trading-mvp-request-plan-discovery-v4/1.0",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            status = int(response.getcode())
            final_url = str(response.geturl())
            encoding = str(response.headers.get("Content-Encoding") or "identity").lower()
            _require(encoding in {"", "identity"}, "compressed response encoding is forbidden")
            declared_header = response.headers.get("Content-Length")
            declared: int | None = None
            if declared_header is not None:
                _require(
                    str(declared_header).strip().isdigit(),
                    "HTTP Content-Length is invalid",
                )
                declared = int(str(declared_header).strip())
            body_buffer = bytearray()
            read_limit = min(
                MAX_RESPONSE_BYTES,
                declared if declared is not None else MAX_RESPONSE_BYTES,
            )
            while len(body_buffer) < read_limit:
                chunk = response.read(
                    min(STREAM_CHUNK_BYTES, read_limit - len(body_buffer))
                )
                if not chunk:
                    break
                _require(type(chunk) is bytes, "HTTP response chunk must be bytes")
                body_buffer.extend(chunk)
            bytes_read = len(body_buffer)
            if declared is not None and declared > MAX_RESPONSE_BYTES:
                complete = False
                truncated = True
                reason = "per_response_cap"
            elif declared is not None and bytes_read < declared:
                complete = False
                truncated = False
                reason = "declared_length_mismatch"
            elif declared is not None and declared == MAX_RESPONSE_BYTES:
                complete = True
                truncated = False
                reason = None
            elif bytes_read == MAX_RESPONSE_BYTES:
                complete = False
                truncated = True
                reason = "per_response_cap_boundary_unknown"
            else:
                complete = bytes_read > 0
                truncated = False
                reason = None if complete else "empty_response"
            body = bytes(body_buffer) if complete else None
            audit = ResponseAudit(
                requested_url=url,
                final_url=final_url,
                status=status,
                resource_kind=resource_kind,
                declared_length=declared,
                bytes_read=bytes_read,
                complete=complete,
                truncated=truncated,
                reason=reason,
                body_sha256=_sha256_bytes(body) if body is not None else None,
            )
    except urllib.error.HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            raise RequestPlanDiscoveryV4Error("HTTP redirect is forbidden") from exc
        raise RequestPlanDiscoveryV4Error("HTTP response status is not 200") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RequestPlanDiscoveryV4Error("public read-only HTTP request failed") from exc
    _require(status == 200, "HTTP response status is not 200")
    _require(final_url == url, "HTTP redirect is forbidden")
    return StreamedResponse(url, final_url, status, body, audit)


def _validate_launch_window(value: Any) -> dict[str, str]:
    _require(isinstance(value, Mapping), "execution launch window is missing")
    _require(
        set(value) == {"not_before_local", "latest_launch_local", "hard_deadline_local"},
        "execution launch window field set changed",
    )
    result = {
        key: _validate_timestamp(value[key], f"execution launch window {key}")
        for key in ("not_before_local", "latest_launch_local", "hard_deadline_local")
    }
    parsed = {
        key: datetime.fromisoformat(text.replace("Z", "+00:00"))
        for key, text in result.items()
    }
    _require(
        parsed["not_before_local"] <= parsed["latest_launch_local"]
        < parsed["hard_deadline_local"],
        "execution launch window ordering is invalid",
    )
    _require(
        (
            parsed["hard_deadline_local"] - parsed["latest_launch_local"]
        ).total_seconds()
        >= MAX_RUNTIME_SEC,
        "execution hard deadline cannot contain the runtime cap",
    )
    return result


def _validate_execution_receipt(
    receipt: Mapping[str, Any],
    *,
    runtime_manifest: Mapping[str, Any],
) -> None:
    expected_fields = {
        "schema",
        "status",
        "run_id",
        "runtime_manifest",
        "visible_launcher",
        "output_path",
        "authorized_scope",
        "limits",
        "launch_window",
        "authoritative_guard_contract",
        "single_use",
        "stopped_incomplete_retry_authorized",
        "user_approval_text",
        "approved_at_utc",
        "receipt_hash_method",
        "receipt_hash",
    }
    _require(set(receipt) == expected_fields, "execution approval receipt field set changed")
    _require(receipt.get("schema") == EXECUTION_RECEIPT_SCHEMA, "execution approval receipt schema mismatch")
    _require(receipt.get("status") == "APPROVED", "execution approval receipt is not approved")
    _require(receipt.get("run_id") == RUN_ID, "execution approval receipt run mismatch")
    _require(receipt.get("receipt_hash_method") == "sha256_canonical_json_excluding_receipt_hash", "execution approval receipt hash method mismatch")
    receipt_hash = _require_hash(receipt.get("receipt_hash"), "execution approval receipt hash")
    _require(canonical_hash_without(receipt, "receipt_hash") == receipt_hash, "execution approval receipt hash mismatch")
    _validate_timestamp(receipt.get("approved_at_utc"), "execution approval timestamp")
    _require(type(receipt.get("user_approval_text")) is str and len(receipt["user_approval_text"].strip()) >= 40, "execution approval text is missing")
    runtime_binding = receipt.get("runtime_manifest")
    _require(
        runtime_binding
        == {
            "path": str(RUNTIME_MANIFEST_PATH),
            "file_sha256": _sha256_file(RUNTIME_MANIFEST_PATH),
            "manifest_hash": runtime_manifest["manifest_hash"],
        },
        "execution approval runtime binding mismatch",
    )
    launcher_binding = receipt.get("visible_launcher")
    _require(
        launcher_binding
        == {
            "path": str(VISIBLE_LAUNCHER_PATH),
            "file_sha256": _sha256_file(VISIBLE_LAUNCHER_PATH),
        },
        "execution approval launcher binding mismatch",
    )
    _require(receipt.get("output_path") == str(OUTPUT_PATH), "execution approval output mismatch")
    _require(receipt.get("authorized_scope") == _authorized_scope(execution=True), "execution approval scope mismatch")
    _require(receipt.get("limits") == _limits(), "execution approval limits mismatch")
    _validate_launch_window(receipt.get("launch_window"))
    _require(receipt.get("single_use") is True, "execution approval is not single-use")
    _require(receipt.get("stopped_incomplete_retry_authorized") is False, "STOPPED_INCOMPLETE retry was authorized")
    guard = receipt.get("authoritative_guard_contract")
    _require(isinstance(guard, Mapping), "execution approval guard contract is missing")
    _require(
        set(guard) == {"required_guard_decision", "required_policy_file_sha256"},
        "execution approval guard contract changed",
    )
    _require(
        guard.get("required_guard_decision")
        == "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4",
        "execution approval guard decision mismatch",
    )
    _require_hash(guard.get("required_policy_file_sha256"), "execution approval policy hash")


def validate_execution_manifest(
    execution_manifest: Mapping[str, Any],
    *,
    runtime_manifest: Mapping[str, Any],
    repo_root: str | Path = REPO_ROOT,
) -> RequestPlanDiscoveryV4ExecutionCapability:
    _require(Path(repo_root).resolve() == REPO_ROOT, "execution repository root mismatch")
    validate_runtime_manifest(runtime_manifest)
    expected_fields = {
        "schema",
        "status",
        "execution_authorized",
        "execution_approval",
        "runtime_manifest",
        "run_id",
        "authorized_scope",
        "limits",
        "launch_window",
        "output_path",
        "single_use",
        "stopped_incomplete_retry_authorized",
        "manifest_hash_method",
        "manifest_hash",
    }
    _require(set(execution_manifest) == expected_fields, "execution manifest field set changed")
    _require(execution_manifest.get("schema") == EXECUTION_MANIFEST_SCHEMA, "execution manifest schema mismatch")
    _require(execution_manifest.get("status") == EXECUTION_APPROVED_STATUS, "separate exact execution approval is missing")
    _require(execution_manifest.get("execution_authorized") is True, "execution is not authorized")
    _require(execution_manifest.get("run_id") == RUN_ID, "execution manifest run mismatch")
    _require(execution_manifest.get("manifest_hash_method") == "sha256_canonical_json_excluding_manifest_hash", "execution manifest hash method mismatch")
    execution_hash = _require_hash(execution_manifest.get("manifest_hash"), "execution manifest hash")
    _require(canonical_hash_without(execution_manifest, "manifest_hash") == execution_hash, "execution manifest hash mismatch")
    runtime_binding = execution_manifest.get("runtime_manifest")
    _require(
        runtime_binding
        == {
            "path": str(RUNTIME_MANIFEST_PATH),
            "file_sha256": _sha256_file(RUNTIME_MANIFEST_PATH),
            "manifest_hash": runtime_manifest["manifest_hash"],
        },
        "execution manifest runtime binding mismatch",
    )
    approval = execution_manifest.get("execution_approval")
    _require(isinstance(approval, Mapping), "execution approval binding is missing")
    _require(
        set(approval) == {"status", "path", "file_sha256", "receipt_hash"},
        "execution approval binding changed",
    )
    _require(approval.get("status") == "APPROVED", "execution approval binding is not approved")
    _require(Path(str(approval.get("path") or "")).resolve() == APPROVAL_RECEIPT_PATH, "execution approval receipt path mismatch")
    receipt_raw, receipt = _read_json(APPROVAL_RECEIPT_PATH, "execution approval receipt")
    _require(_sha256_bytes(receipt_raw) == _require_hash(approval.get("file_sha256"), "execution approval receipt file hash"), "execution approval receipt file hash mismatch")
    _validate_execution_receipt(receipt, runtime_manifest=runtime_manifest)
    _require(approval.get("receipt_hash") == receipt["receipt_hash"], "execution approval receipt canonical hash mismatch")
    _require(execution_manifest.get("authorized_scope") == _authorized_scope(execution=True), "execution manifest scope mismatch")
    _require(execution_manifest.get("limits") == _limits(), "execution manifest limits mismatch")
    window = _validate_launch_window(execution_manifest.get("launch_window"))
    _require(execution_manifest.get("launch_window") == receipt["launch_window"], "execution launch window receipt mismatch")
    _require(execution_manifest.get("output_path") == str(OUTPUT_PATH), "execution output path mismatch")
    _require(execution_manifest.get("single_use") is True, "execution is not single-use")
    _require(execution_manifest.get("stopped_incomplete_retry_authorized") is False, "STOPPED_INCOMPLETE retry enabled")
    return RequestPlanDiscoveryV4ExecutionCapability(
        run_id=RUN_ID,
        runtime_manifest_hash=str(runtime_manifest["manifest_hash"]),
        execution_manifest_hash=execution_hash,
        output_path=str(OUTPUT_PATH),
        not_before_local=window["not_before_local"],
        latest_launch_local=window["latest_launch_local"],
        hard_deadline_local=window["hard_deadline_local"],
    )


def collect_request_plan(
    *,
    capability: RequestPlanDiscoveryV4ExecutionCapability,
    fetch: Callable[[str, str], StreamedResponse | FetchedResponse] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> RequestPlanDiscoveryV4Result:
    _require(type(capability) is RequestPlanDiscoveryV4ExecutionCapability, "execution capability is required")
    _require(capability.run_id == RUN_ID, "execution capability run mismatch")
    started = monotonic()

    def bounded_fetch(url: str, resource_kind: str) -> StreamedResponse | FetchedResponse:
        remaining = MAX_RUNTIME_SEC - (monotonic() - started)
        _require(remaining > 0, "request-plan discovery deadline exceeded")
        if fetch is not None:
            return fetch(url, resource_kind)
        return fetch_public_response(
            url,
            timeout_sec=min(30.0, remaining),
            resource_kind=resource_kind,
        )

    plan = json.loads(PARENT_DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
    result = discover_request_plan(plan, fetch=bounded_fetch, monotonic=monotonic)
    _require(monotonic() - started <= MAX_RUNTIME_SEC, "request-plan discovery deadline exceeded")
    _require(result.status == "COMPLETE_EXACT_REQUEST_PLAN", "request-plan discovery stopped incomplete")
    return result


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RequestPlanDiscoveryV4Error(f"immutable output already exists: {path.name}") from exc


def write_request_plan_bundle(
    output_path: str | Path,
    result: RequestPlanDiscoveryV4Result,
    *,
    capability: RequestPlanDiscoveryV4ExecutionCapability,
) -> dict[str, Any]:
    _require(type(capability) is RequestPlanDiscoveryV4ExecutionCapability, "execution capability is required")
    _require(Path(output_path).resolve() == OUTPUT_PATH, "request-plan output path mismatch")
    _require(result.status == "COMPLETE_EXACT_REQUEST_PLAN", "incomplete request plan cannot be written")
    _require(len(result.request_plan) == len(BASES) * len(VENUES), "request plan pair count mismatch")
    request_plan = [copy.deepcopy(item) for item in result.request_plan]
    for item in request_plan:
        try:
            identity_runtime._validate_request_plan_item(item)  # noqa: SLF001
        except identity_runtime.IdentityVerificationError as exc:
            raise RequestPlanDiscoveryV4Error("request plan is not consumer-compatible") from exc
    request_payload = canonical_json_bytes(request_plan)
    manifest: dict[str, Any] = {
        "schema": "trading_mvp_slow_liquidity_identity_request_plan_discovery_output_manifest_v4",
        "status": "COMPLETE_EXACT_REQUEST_PLAN_NOT_IDENTITY_VERDICT",
        "run_id": RUN_ID,
        "runtime_manifest_hash": capability.runtime_manifest_hash,
        "execution_manifest_hash": capability.execution_manifest_hash,
        "request_plan_file": {
            "name": "request-plan.json",
            "file_sha256": _sha256_bytes(request_payload),
            "bytes": len(request_payload),
            "pair_count": len(request_plan),
        },
        "request_count": result.request_count,
        "response_audits": [copy.deepcopy(item) for item in result.response_audits],
        "total_response_bytes": result.total_response_bytes,
        "maximum_total_response_bytes": MAX_TOTAL_RESPONSE_BYTES,
        "response_streaming": {
            "chunk_bytes": STREAM_CHUNK_BYTES,
            "per_response_cap_bytes": MAX_RESPONSE_BYTES,
            "raw_payload_persisted": False,
            "oversize_policies": copy.deepcopy(OVERSIZE_POLICIES),
        },
        "raw_payload_persisted": False,
        "search_payload_persisted": False,
        "identity_output_created": False,
        "identity_verdict_created": False,
        "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
    }
    manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")
    manifest_payload = canonical_json_bytes(manifest)
    _require(len(request_payload) + len(manifest_payload) <= HARD_OUTPUT_CAP_BYTES, "request-plan output exceeds hard cap")
    root = Path(output_path).resolve()
    try:
        root.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise RequestPlanDiscoveryV4Error("immutable request-plan output already exists") from exc
    try:
        _write_exclusive(root / "request-plan.json", request_payload)
        _write_exclusive(root / "manifest.json", manifest_payload)
    except BaseException:
        for child in (root / "manifest.json", root / "request-plan.json"):
            child.unlink(missing_ok=True)
        root.rmdir()
        raise
    return manifest


def sanitized_failure_envelope(
    error: BaseException,
    *,
    network_stage_entered: bool,
) -> dict[str, Any]:
    message = str(error).lower()
    if "redirect" in message:
        reason = "HTTP_REDIRECT_FORBIDDEN"
    elif isinstance(error, TotalResponseCapExceeded):
        reason = "TOTAL_RESPONSE_CAP_EXCEEDED"
    elif "response body exceeds" in message or "output exceeds" in message:
        reason = "RESPONSE_CAP_EXCEEDED"
    elif "deadline" in message:
        reason = "REQUEST_PLAN_DISCOVERY_RUNTIME_DEADLINE_EXCEEDED"
    elif isinstance(error, RequestPlanDiscoveryV4Error):
        reason = "REQUEST_PLAN_DISCOVERY_RUNTIME_CONTRACT_REJECTED"
    else:
        reason = "REQUEST_PLAN_DISCOVERY_INTERNAL_RUNTIME_FAILURE"
    return {
        "schema": "trading_mvp_slow_liquidity_identity_request_plan_discovery_failure_v4",
        "status": "STOPPED_INCOMPLETE",
        "run_id": RUN_ID,
        "reason_code": reason,
        "network_accessed": bool(network_stage_entered),
        "network_access_state": (
            "ATTEMPTED_OR_ENTERED_NETWORK_STAGE"
            if network_stage_entered
            else "NOT_ENTERED_NETWORK_STAGE"
        ),
        "request_plan_output_created": False,
        "identity_output_created": False,
        "raw_payload_persisted": False,
        "response_audit": copy.deepcopy(getattr(error, "response_audit", None)),
        "total_response_bytes": getattr(error, "total_response_bytes", None),
        "retry_authorized": False,
    }


def preflight_execution(
    *,
    runtime_manifest_path: str | Path,
    execution_manifest_path: str | Path,
    output_path: str | Path,
    read_execution_manifest: bool = False,
) -> dict[str, Any]:
    runtime_path = Path(runtime_manifest_path).expanduser().resolve()
    execution_path = Path(execution_manifest_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    _require(runtime_path == RUNTIME_MANIFEST_PATH, "runtime manifest path mismatch")
    _require(execution_path == EXECUTION_MANIFEST_PATH, "execution manifest path mismatch")
    _require(output == OUTPUT_PATH, "output path mismatch")
    runtime_raw, runtime_manifest = _read_json(runtime_path, "request-plan discovery runtime manifest")
    validate_runtime_manifest(runtime_manifest)
    return {
        "status": "READY_FOR_STANDING_PUBLIC_RESEARCH_EXECUTION",
        "reason": "standing same-scope public research policy is used after technical guards",
        "run_id": RUN_ID,
        "runtime_manifest_path": str(runtime_path),
        "runtime_manifest_file_sha256": _sha256_bytes(runtime_raw),
        "runtime_manifest_hash": runtime_manifest["manifest_hash"],
        "execution_manifest_path": str(execution_path),
        "output_path": str(output),
        "network_accessed": False,
        "execution_manifest_read": bool(read_execution_manifest and False),
        "global_writer_claim_created": False,
        "request_plan_output_created": False,
        "retry_authorized": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze-runtime")
    freeze.add_argument("--generated-at-utc", required=True)
    freeze.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate-runtime")
    validate.add_argument("--runtime-manifest", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--runtime-manifest", required=True)
    preflight.add_argument("--execution-manifest", required=True)
    preflight.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "freeze-runtime":
        target = Path(args.output).resolve()
        _require(target == RUNTIME_MANIFEST_PATH, "runtime manifest output path mismatch")
        _require(not APPROVAL_RECEIPT_PATH.exists(), "approval receipt exists during offline refreeze")
        _require(not EXECUTION_MANIFEST_PATH.exists(), "execution manifest exists during offline refreeze")
        _require(not OUTPUT_PATH.exists(), "request-plan output exists during offline refreeze")
        manifest = build_runtime_manifest(generated_at_utc=args.generated_at_utc)
        write_runtime_manifest(target, manifest)
        payload = {
            "status": RUNTIME_MANIFEST_STATUS,
            "runtime_manifest_path": str(target),
            "runtime_manifest_file_sha256": _sha256_file(target),
            "runtime_manifest_hash": manifest["manifest_hash"],
            "network_accessed": False,
            "approval_receipt_created": False,
            "execution_manifest_created": False,
            "global_writer_claim_created": False,
            "request_plan_output_created": False,
            "visible_launcher_executed": False,
        }
        exit_code = 0
    elif args.command == "validate-runtime":
        raw, manifest = _read_json(args.runtime_manifest, "request-plan discovery runtime manifest")
        validate_runtime_manifest(manifest)
        payload = {
            "status": "VALID_CODE_BOUND_RUNTIME_EXECUTION_CLOSED",
            "runtime_manifest_path": str(Path(args.runtime_manifest).resolve()),
            "runtime_manifest_file_sha256": _sha256_bytes(raw),
            "runtime_manifest_hash": manifest["manifest_hash"],
        }
        exit_code = 0
    else:
        payload = preflight_execution(
            runtime_manifest_path=args.runtime_manifest,
            execution_manifest_path=args.execution_manifest,
            output_path=args.output,
            read_execution_manifest=False,
        )
        exit_code = 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APPROVAL_RECEIPT_PATH",
    "BASES",
    "EXECUTION_MANIFEST_PATH",
    "FetchedResponse",
    "IDENTITY_RUNTIME_MANIFEST_PATH",
    "LAUNCH_RECORD_PATH",
    "LAUNCHER_CAPABILITY_PATH",
    "MAX_RESPONSE_BYTES",
    "MAX_TOTAL_RESPONSE_BYTES",
    "OUTPUT_PATH",
    "OVERSIZE_POLICIES",
    "PARENT_DISCOVERY_PLAN_PATH",
    "PARENT_DISCOVERY_RUNTIME_MANIFEST_PATH",
    "RUN_ID",
    "RUNTIME_MANIFEST_PATH",
    "RUNTIME_MANIFEST_STATUS",
    "ResponseAudit",
    "ResponseCapExceeded",
    "StreamedResponse",
    "STREAM_CHUNK_BYTES",
    "TotalResponseCapExceeded",
    "RequestPlanDiscoveryV4Error",
    "RequestPlanDiscoveryV4ExecutionCapability",
    "RequestPlanDiscoveryV4Result",
    "TOPOLOGY_EXECUTION_MANIFEST_PATH",
    "TOPOLOGY_LAUNCH_RECORD_PATH",
    "TOPOLOGY_OUTPUT_MANIFEST_PATH",
    "TOPOLOGY_OUTPUT_PATH",
    "VISIBLE_LAUNCHER_PATH",
    "build_runtime_manifest",
    "build_standing_execution_capability",
    "canonical_hash_without",
    "collect_request_plan",
    "discover_request_plan",
    "fetch_public_response",
    "preflight_execution",
    "sanitized_failure_envelope",
    "validate_execution_manifest",
    "validate_runtime_manifest",
    "write_request_plan_bundle",
    "write_runtime_manifest",
]
