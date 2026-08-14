from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


LEGACY_READINESS_SCHEMA = "trading_mvp_one_week_edge_sprint_current_readiness_v1"
READINESS_SCHEMA = "trading_mvp_one_week_edge_sprint_current_readiness_v2"
POINTER_SCHEMA = "trading_mvp_one_week_edge_sprint_readiness_pointer_v1"
READINESS_HASH_METHOD = "sha256_canonical_json_excluding_readiness_hash"
EXPECTED_PRIMARY_BASIS_HYPOTHESIS = (
    "cross_venue_perp_basis_convergence_history_v1"
)
EXPECTED_PRIMARY_BASIS_VERDICT = "INSUFFICIENT_DATA"
EXPECTED_PRIMARY_BASIS_REASON = (
    "GATE_5M_PUBLIC_HISTORY_RETENTION_LT_FROZEN_220D"
)
EXPECTED_PRIMARY_BASIS_NEXT_COMMAND = "none_branch_closed_insufficient_data"
EXPECTED_PRIMARY_BASIS_FORBIDDEN_ACTIONS = (
    "historical_collect_220d_5m_gate_public",
    "train_evaluation",
    "oos_evaluation",
    "execution_probe",
    "paper_forward",
    "live_orders",
    "retune_frozen_contract",
)


@dataclass(frozen=True)
class PrimaryBasisTrustAnchor:
    sprint_plan_path: Path
    sprint_plan_file_sha256: str
    currentness_audit_path: Path
    currentness_audit_file_sha256: str
    terminal_report_path: Path
    terminal_report_file_sha256: str
    artifact_hash: str


_REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_PRIMARY_BASIS_TRUST_ANCHOR = PrimaryBasisTrustAnchor(
    sprint_plan_path=(
        _REPO_ROOT
        / "docs"
        / "plans"
        / "2026-07-15-trading-mvp-one-week-historical-edge-sprint.md"
    ).resolve(),
    sprint_plan_file_sha256=(
        "cbf88e1f634735360910ea3b8934c99cb98cfb38be7b9b9b50369c0fc29b8626"
    ),
    currentness_audit_path=(
        _REPO_ROOT
        / "docs"
        / "agent-log"
        / "readiness"
        / "cross-venue-basis-terminal-currentness-audit-20260802T1323+0300.json"
    ).resolve(),
    currentness_audit_file_sha256=(
        "8640b20c5a5e9257998646c66afa1b5f574c3295c56a117a9d0f6fc591be83d2"
    ),
    terminal_report_path=Path(
        "E:/ZolotyayLopata-data/exports/trading-mvp/historical-basis/reports/"
        "basis_sprint_retention_closure_20260715_115819.json"
    ).resolve(),
    terminal_report_file_sha256=(
        "55fe4c4e07d54e5ffd48aac04f49b4087cb0d6539bc387171dc19a7e02d6d19c"
    ),
    artifact_hash=(
        "802662634518419e53c0ddb86d2501a213d4ec32b8fa06d401da0f8a46195f42"
    ),
)
EXPECTED_QUALITY_DECISION = (
    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
    "AWAIT_OFFICIAL_IDENTITY_APPROVAL"
)
EXPECTED_PIT_HYPOTHESIS = "pit_universe_membership_drift_reversion_v1"
EXPECTED_PIT_DATA_TYPE = "PIT_UNIVERSE_V2_FORWARD"
EXPECTED_PIT_STAGE = "train_accrual"
EXPECTED_BASES = (
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
EXPECTED_VENUES = ("mexc", "gateio")
EXPECTED_GRANULARITIES = ("1h", "4h")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CURRENT_READINESS_STATUS = (
    "QUALITY_ACCEPTED_SEPARATE_APPROVALS_PENDING_"
    "NO_EXECUTION_AUTHORIZED"
)
IDENTITY_PHASE1_READINESS_STATUS = (
    "IDENTITY_RUNTIME_FROZEN_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
)
IDENTITY_PHASE2_READINESS_STATUS = (
    "IDENTITY_RUNTIME_FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
)
TOPOLOGY_EXECUTION_READINESS_STATUS = (
    "TOPOLOGY_RUNTIME_FROZEN_WITH_EXACT_EXECUTION_APPROVAL"
)
TOPOLOGY_V2_REFREEZE_READINESS_STATUS = (
    "TOPOLOGY_V2_RUNTIME_FROZEN_AWAIT_EXACT_EXECUTION_APPROVAL"
)
TOPOLOGY_V3_REFREEZE_READINESS_STATUS = (
    "TOPOLOGY_V3_RUNTIME_FROZEN_AWAIT_EXACT_EXECUTION_APPROVAL"
)
TOPOLOGY_V3_OFFLINE_REFREEZE_APPROVAL_READINESS_STATUS = (
    "TOPOLOGY_V2_LAUNCHER_REJECTED_AWAIT_V3_OFFLINE_REFREEZE_APPROVAL"
)
IDENTITY_PHASE1_STATUS = (
    "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
)
IDENTITY_PHASE2_STATUS = "FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
IDENTITY_PHASE2_CHECKPOINT_ID = "slow_liquidity_identity_execution_phase_2"
CURRENT_READINESS_STATUSES = (
    CURRENT_READINESS_STATUS,
    IDENTITY_PHASE1_READINESS_STATUS,
    IDENTITY_PHASE2_READINESS_STATUS,
    TOPOLOGY_EXECUTION_READINESS_STATUS,
    TOPOLOGY_V2_REFREEZE_READINESS_STATUS,
    TOPOLOGY_V3_REFREEZE_READINESS_STATUS,
    TOPOLOGY_V3_OFFLINE_REFREEZE_APPROVAL_READINESS_STATUS,
)
CURRENT_PERMISSION_FIELDS = (
    "global_writer_present",
    "identity_offline_implementation_authorized",
    "identity_verification_authorized",
    "pit_extension_activation_authorized",
    "dense_refreeze_implementation_authorized",
    "collector_launch_authorized",
    "evaluator_or_oos_authorized",
    "returns_or_pnl_authorized",
    "grid_or_retune_authorized",
    "execution_probe_authorized",
    "paper_or_live_authorized",
    "private_api_or_real_capital_authorized",
    "leverage_or_margin_authorized",
    "stopped_incomplete_retry_authorized",
)
CURRENT_CHECKPOINT_IDS = (
    "pit_extension_schedule_activation",
    "slow_liquidity_identity_offline_phase_1",
    "dense_three_hour_segmented_refreeze_phase_1",
)
IDENTITY_RUNTIME_CHECKPOINT_IDS = (
    "pit_extension_schedule_activation",
    IDENTITY_PHASE2_CHECKPOINT_ID,
    "dense_three_hour_segmented_refreeze_phase_1",
)


class ReadinessError(ValueError):
    pass


class CurrentSprintReadinessError(ReadinessError):
    def __init__(self, message: str, *, status: str = "INVALID") -> None:
        super().__init__(message)
        self.status = status


def _load_identity_runtime_validator() -> Any:
    module_name = (
        f"{__package__}.slow_liquidity_official_identity_verification"
        if __package__
        else "slow_liquidity_official_identity_verification"
    )
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ReadinessError("identity runtime validator is unavailable") from exc


def _load_topology_runtime_validator() -> Any:
    module_name = (
        f"{__package__}.slow_liquidity_official_currentness_topology"
        if __package__
        else "slow_liquidity_official_currentness_topology"
    )
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ReadinessError("topology runtime validator is unavailable") from exc


def _load_topology_v2_runtime_validator() -> Any:
    module_name = (
        f"{__package__}.slow_liquidity_official_currentness_topology_v2"
        if __package__
        else "slow_liquidity_official_currentness_topology_v2"
    )
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ReadinessError("topology v2 runtime validator is unavailable") from exc


def _load_topology_v3_runtime_validator() -> Any:
    module_name = (
        f"{__package__}.slow_liquidity_official_currentness_topology_v3"
        if __package__
        else "slow_liquidity_official_currentness_topology_v3"
    )
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ReadinessError("topology v3 runtime validator is unavailable") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash_without(value: Mapping[str, Any], field: str) -> str:
    normalized = copy.deepcopy(dict(value))
    normalized.pop(field, None)
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReadinessError(f"cannot read file: {path}") from exc
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8-sig")
        value = json.loads(
            content,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid {label} JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_reject_duplicate_keys,
                )
                if not isinstance(value, dict):
                    raise ReadinessError(
                        f"{label} row {line_number} must be a JSON object"
                    )
                rows.append(value)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ReadinessError):
            raise
        raise ReadinessError(f"invalid {label} JSONL: {path}") from exc
    return rows


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessError(message)


def _require_hash(value: Any, label: str) -> str:
    observed = str(value or "").lower()
    if HASH_PATTERN.fullmatch(observed) is None:
        raise ReadinessError(f"invalid {label} SHA-256")
    return observed


def _require_file_hash(path: Path, expected: Any, label: str) -> str:
    expected_hash = _require_hash(expected, label)
    if not path.is_file():
        raise ReadinessError(f"{label} is missing: {path}")
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise ReadinessError(
            f"{label} SHA-256 mismatch: expected={expected_hash} actual={actual_hash}"
        )
    return actual_hash


def _require_exact_path(actual: Any, expected: Path, label: str) -> None:
    try:
        observed = _resolve(str(actual or ""))
    except (OSError, ValueError) as exc:
        raise ReadinessError(f"invalid {label} path") from exc
    if observed != expected:
        raise ReadinessError(f"{label} path mismatch")


def _require_false(mapping: Mapping[str, Any], fields: Sequence[str], label: str) -> None:
    for field in fields:
        if mapping.get(field) is not False:
            raise ReadinessError(f"{label} illegally enables {field}")


def _reject_unsafe_true_flags(value: Any, label: str, *, path: str = "") -> None:
    unsafe_fragments = (
        "authoriz",
        "allow",
        "enable",
        "launch",
        "execution",
        "collector",
        "network",
        "market_rows_read",
        "oos_read",
        "returns_read",
        "pnl_read",
        "grid",
        "retune",
        "paper",
        "live",
        "private_api",
        "real_capital",
        "leverage",
        "margin",
        "retry",
        "reopen",
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            field_path = f"{path}.{key}" if path else str(key)
            normalized_key = str(key).lower()
            if item is True and any(
                fragment in normalized_key for fragment in unsafe_fragments
            ):
                raise ReadinessError(
                    f"{label} contains unsafe true flag: {field_path}"
                )
            _reject_unsafe_true_flags(item, label, path=field_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            field_path = f"{path}[{index}]"
            _reject_unsafe_true_flags(item, label, path=field_path)


def _file_ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "file_sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_identity_runtime_manifest(
    manifest_path: Path,
    *,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    identity_runtime = _load_identity_runtime_validator()

    manifest = _load_json(manifest_path, "identity runtime manifest")
    try:
        identity_runtime.validate_runtime_manifest(manifest)
    except identity_runtime.IdentityVerificationError as exc:
        raise ReadinessError(f"invalid identity runtime manifest: {exc}") from exc

    proposal = manifest.get("proposal")
    _require(isinstance(proposal, Mapping), "identity runtime proposal binding is missing")
    _require(
        _resolve(str(proposal.get("path") or ""))
        == _resolve(str(identity.get("path") or "")),
        "identity runtime proposal path mismatch",
    )
    _require(
        proposal.get("file_sha256") == identity.get("file_sha256")
        and proposal.get("proposal_hash") == identity.get("proposal_hash"),
        "identity runtime proposal hash binding mismatch",
    )
    runtime = manifest.get("runtime")
    _require(isinstance(runtime, Mapping), "identity runtime code bindings are missing")
    readiness_path = _resolve(str(runtime.get("readiness_module_path") or ""))
    _require(
        readiness_path == Path(__file__).resolve()
        and runtime.get("readiness_module_sha256") == _sha256(readiness_path),
        "identity runtime readiness code binding mismatch",
    )
    approval = manifest.get("offline_approval_receipt")
    _require(isinstance(approval, Mapping), "identity offline approval binding is missing")
    approval_path = _resolve(str(approval.get("path") or ""))
    _require(
        approval.get("file_sha256") == _sha256(approval_path),
        "identity offline approval file hash mismatch",
    )
    return {
        **_file_ref(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "status": manifest["status"],
        "offline_approval_receipt": {
            **_file_ref(approval_path),
            "receipt_hash": approval["receipt_hash"],
        },
    }


def _validate_identity_execution_manifest(
    manifest_path: Path,
    *,
    runtime_state: Mapping[str, Any],
) -> dict[str, Any]:
    identity_runtime = _load_identity_runtime_validator()

    runtime_path = _resolve(str(runtime_state.get("path") or ""))
    runtime_manifest = _load_json(runtime_path, "identity runtime manifest")
    execution = _load_json(manifest_path, "identity execution manifest")
    approval = execution.get("execution_approval")
    _require(isinstance(approval, Mapping), "identity execution approval binding is missing")
    approval_path = _resolve(str(approval.get("path") or ""))
    approval_receipt = _load_json(approval_path, "identity execution approval receipt")
    approval_sha256 = _sha256(approval_path)
    try:
        identity_runtime.validate_execution_manifest(
            execution,
            phase1_manifest=runtime_manifest,
            approval_receipt_snapshot=approval_receipt,
            approval_receipt_file_sha256=approval_sha256,
        )
    except identity_runtime.IdentityVerificationError as exc:
        raise ReadinessError(f"invalid identity execution manifest: {exc}") from exc

    runtime_binding = execution.get("phase1_runtime_manifest")
    _require(isinstance(runtime_binding, Mapping), "identity phase1 binding is missing")
    _require(
        _resolve(str(runtime_binding.get("path") or "")) == runtime_path
        and runtime_binding.get("file_sha256") == runtime_state.get("file_sha256")
        and runtime_binding.get("manifest_hash") == runtime_state.get("manifest_hash"),
        "identity execution runtime binding mismatch",
    )
    request_plan = execution.get("request_plan")
    _require(isinstance(request_plan, list), "identity execution request plan is missing")
    request_plan_sha256 = hashlib.sha256(_canonical_bytes(request_plan)).hexdigest()
    _require(
        approval_receipt.get("request_plan_sha256") == request_plan_sha256,
        "identity execution request plan hash mismatch",
    )
    return {
        "status": execution["status"],
        "execution_manifest": {
            **_file_ref(manifest_path),
            "manifest_hash": execution["manifest_hash"],
        },
        "runtime_manifest_file_sha256": runtime_state["file_sha256"],
        "runtime_manifest_hash": runtime_state["manifest_hash"],
        "execution_approval_receipt": {
            **_file_ref(approval_path),
            "receipt_hash": approval_receipt["receipt_hash"],
        },
        "execution_approval_receipt_file_sha256": approval_sha256,
        "execution_approval_receipt_hash": approval_receipt["receipt_hash"],
        "request_plan_sha256": request_plan_sha256,
        "output_path": execution["output_path"],
    }


def _current_error(message: str, *, status: str = "INVALID") -> None:
    raise CurrentSprintReadinessError(message, status=status)


def _current_require(
    condition: bool,
    message: str,
    *,
    status: str = "INVALID",
) -> None:
    if not condition:
        _current_error(message, status=status)


def _read_current_json(
    path: Path,
    label: str,
    *,
    missing_status: str = "INVALID",
) -> tuple[dict[str, Any], bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CurrentSprintReadinessError(
            f"{label} is missing or unreadable: {path}",
            status=missing_status,
        ) from exc
    try:
        value = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise CurrentSprintReadinessError(
            f"invalid {label} JSON: {path}",
            status="INVALID",
        ) from exc
    if not isinstance(value, dict):
        _current_error(f"{label} must be a JSON object")
    return value, raw, hashlib.sha256(raw).hexdigest()


def _read_current_file(
    path: Path,
    label: str,
    *,
    missing_status: str = "INVALID",
) -> tuple[bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CurrentSprintReadinessError(
            f"{label} is missing or unreadable: {path}",
            status=missing_status,
        ) from exc
    return raw, hashlib.sha256(raw).hexdigest()


def _current_ref(
    value: Any,
    label: str,
    *,
    expected_path: Path | None = None,
    dynamic: bool = False,
    parse_json: bool = False,
) -> tuple[Path, dict[str, Any] | None]:
    _current_require(isinstance(value, dict), f"{label} reference is missing")
    reference = value
    try:
        path = _resolve(str(reference.get("path") or ""))
    except (OSError, ValueError) as exc:
        raise CurrentSprintReadinessError(
            f"invalid {label} path",
            status="INVALID",
        ) from exc
    if expected_path is not None:
        _current_require(path == expected_path, f"{label} path mismatch")

    expected_hash = str(reference.get("file_sha256") or "").lower()
    _current_require(
        HASH_PATTERN.fullmatch(expected_hash) is not None,
        f"invalid {label} file SHA-256",
    )
    stale_status = "REFRESH_REQUIRED" if dynamic else "INVALID"
    if parse_json:
        payload, raw, observed_hash = _read_current_json(
            path,
            label,
            missing_status=stale_status,
        )
    else:
        raw, observed_hash = _read_current_file(
            path,
            label,
            missing_status=stale_status,
        )
        payload = None
    _current_require(
        observed_hash == expected_hash,
        f"{label} file hash mismatch",
        status=stale_status,
    )
    size_value = reference.get("size_bytes")
    if size_value is not None:
        try:
            expected_size = int(size_value)
        except (TypeError, ValueError) as exc:
            raise CurrentSprintReadinessError(
                f"invalid {label} size",
                status="INVALID",
            ) from exc
        _current_require(
            len(raw) == expected_size,
            f"{label} size mismatch",
            status=stale_status,
        )
    return path, payload


def _require_aware_timestamp(value: Any, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise CurrentSprintReadinessError(f"invalid {label}") from exc
    _current_require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        f"{label} must include a UTC offset",
    )


def _resolve_topology_execution_readiness(
    report: Mapping[str, Any],
    *,
    pointer_file: Path,
    pointer_sha: str,
    readiness_path: Path,
    report_sha: str,
    gate_file: Path,
    writer_claim_file: Path,
) -> dict[str, Any]:
    permissions = report.get("permissions")
    _current_require(isinstance(permissions, dict), "readiness permissions are missing")
    _current_require(
        set(permissions) == set(CURRENT_PERMISSION_FIELDS),
        "readiness permission allowlist mismatch",
    )
    for field in CURRENT_PERMISSION_FIELDS:
        _current_require(
            permissions.get(field) is False,
            f"topology readiness illegally enables {field}",
        )

    topology = report.get("official_currentness_topology")
    _current_require(isinstance(topology, Mapping), "topology readiness is missing")
    _current_require(
        topology.get("status") == "FROZEN_WITH_EXACT_TOPOLOGY_EXECUTION_APPROVAL",
        "topology execution status mismatch",
    )
    _current_require(topology.get("execution_authorized") is True, "topology execution is not authorized")
    _current_require(topology.get("single_use") is True, "topology execution is not single-use")
    _current_require(
        topology.get("stopped_incomplete_retry_authorized") is False,
        "topology retry is authorized",
    )

    proposal_path, proposal = _current_ref(
        topology.get("proposal"),
        "topology proposal",
        parse_json=True,
    )
    runtime_path, runtime_manifest = _current_ref(
        topology.get("runtime_manifest"),
        "topology runtime manifest",
        parse_json=True,
    )
    execution_path, execution_manifest = _current_ref(
        topology.get("execution_manifest"),
        "topology execution manifest",
        parse_json=True,
    )
    approval_path, approval_receipt = _current_ref(
        topology.get("execution_approval_receipt"),
        "topology execution approval receipt",
        parse_json=True,
    )
    _current_require(isinstance(proposal, dict), "topology proposal payload is missing")
    _current_require(isinstance(runtime_manifest, dict), "topology runtime payload is missing")
    _current_require(isinstance(execution_manifest, dict), "topology execution payload is missing")
    _current_require(isinstance(approval_receipt, dict), "topology approval payload is missing")
    proposal_hash = str((topology.get("proposal") or {}).get("proposal_hash") or "").lower()
    _current_require(
        HASH_PATTERN.fullmatch(proposal_hash) is not None
        and proposal.get("proposal_hash") == proposal_hash,
        "topology proposal hash binding mismatch",
    )
    _current_require(
        runtime_manifest.get("proposal")
        == {
            "path": str(proposal_path),
            "file_sha256": (topology.get("proposal") or {}).get("file_sha256"),
            "proposal_hash": proposal_hash,
        },
        "topology runtime proposal binding mismatch",
    )
    topology_runtime = _load_topology_runtime_validator()
    try:
        capability = topology_runtime.validate_execution_manifest(
            execution_manifest,
            runtime_manifest=runtime_manifest,
            repo_root=_REPO_ROOT,
            approval_receipt_snapshot=approval_receipt,
            approval_receipt_file_sha256=(
                topology.get("execution_approval_receipt") or {}
            ).get("file_sha256"),
        )
    except topology_runtime.TopologyDiscoveryError as exc:
        raise CurrentSprintReadinessError(
            f"topology execution validation failed: {exc}"
        ) from exc
    _current_require(
        capability.run_id == topology.get("run_id"),
        "topology run binding mismatch",
    )
    _current_require(
        capability.output_path == topology.get("output_path"),
        "topology output binding mismatch",
    )
    _current_require(
        (topology.get("runtime_manifest") or {}).get("manifest_hash")
        == runtime_manifest.get("manifest_hash"),
        "topology runtime canonical hash mismatch",
    )
    _current_require(
        (topology.get("execution_manifest") or {}).get("manifest_hash")
        == execution_manifest.get("manifest_hash"),
        "topology execution canonical hash mismatch",
    )
    _current_require(
        (topology.get("execution_approval_receipt") or {}).get("receipt_hash")
        == approval_receipt.get("receipt_hash"),
        "topology approval canonical hash mismatch",
    )

    slow = report.get("slow_liquidity")
    _current_require(isinstance(slow, Mapping), "slow liquidity readiness is missing")
    _, current_gate = _current_ref(
        slow.get("gate"),
        "active gate",
        expected_path=gate_file,
        dynamic=True,
        parse_json=True,
    )
    _current_require(isinstance(current_gate, dict), "active gate payload is missing")
    _current_require(
        current_gate.get("status") == "READY_FOR_POSTPROCESS",
        "active gate is not open",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("run_id") == slow.get("run_id"),
        "active gate run changed",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("next_goal_decision") == EXPECTED_QUALITY_DECISION,
        "active gate decision changed",
        status="REFRESH_REQUIRED",
    )
    if writer_claim_file.exists():
        _current_error(
            "global market-data writer claim appeared after readiness",
            status="REFRESH_REQUIRED",
        )

    checkpoints = report.get("approval_checkpoints")
    _current_require(isinstance(checkpoints, list), "approval checkpoints are missing")
    expected_ids = [
        "pit_extension_schedule_activation",
        "slow_liquidity_currentness_topology_execution",
        "dense_three_hour_segmented_refreeze_phase_1",
    ]
    _current_require(
        [str(item.get("id") or "") for item in checkpoints if isinstance(item, dict)]
        == expected_ids,
        "topology approval checkpoint allowlist mismatch",
    )
    topology_checkpoint = checkpoints[1]
    _current_require(
        topology_checkpoint.get("status") == "APPROVED_SINGLE_USE"
        and topology_checkpoint.get("runtime_manifest_file_sha256")
        == (topology.get("runtime_manifest") or {}).get("file_sha256")
        and topology_checkpoint.get("runtime_manifest_hash")
        == runtime_manifest.get("manifest_hash")
        and topology_checkpoint.get("execution_manifest_file_sha256")
        == (topology.get("execution_manifest") or {}).get("file_sha256")
        and topology_checkpoint.get("execution_manifest_hash")
        == execution_manifest.get("manifest_hash")
        and topology_checkpoint.get("execution_approval_receipt_file_sha256")
        == (topology.get("execution_approval_receipt") or {}).get("file_sha256")
        and topology_checkpoint.get("execution_approval_receipt_hash")
        == approval_receipt.get("receipt_hash"),
        "topology approval checkpoint binding mismatch",
    )
    _current_require(
        report.get("next_safe_action")
        == "run_exact_approved_slow_liquidity_official_currentness_topology_visible",
        "topology readiness next action changed",
    )
    return {
        "status": "READY",
        "pointer_path": str(pointer_file),
        "pointer_file_sha256": pointer_sha,
        "readiness_path": str(readiness_path),
        "readiness_file_sha256": report_sha,
        "readiness_hash": report["readiness_hash"],
        "generated_at_utc": report["generated_at_utc"],
        "source_status": report["status"],
        "execution_authorized": True,
        "next_safe_action": report["next_safe_action"],
        "approval_checkpoints": checkpoints,
        "primary_frozen_basis_terminal": report.get("primary_frozen_basis_terminal"),
        "official_currentness_topology": {
            "status": topology["status"],
            "run_id": topology["run_id"],
            "proposal_path": str(proposal_path),
            "runtime_manifest_path": str(runtime_path),
            "execution_manifest_path": str(execution_path),
            "execution_approval_receipt_path": str(approval_path),
            "output_path": topology["output_path"],
            "execution_authorized": True,
            "single_use": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "active_pit_pointer_path": str(
            _resolve(
                str(
                    ((report.get("pit_shadow_track") or {}).get("active_pointer") or {}).get(
                        "path"
                    )
                    or ""
                )
            )
        ),
    }


def _resolve_topology_v3_offline_refreeze_approval_readiness(
    report: Mapping[str, Any],
    *,
    pointer_file: Path,
    pointer_sha: str,
    readiness_path: Path,
    report_sha: str,
    gate_file: Path,
    writer_claim_file: Path,
) -> dict[str, Any]:
    permissions = report.get("permissions")
    _current_require(isinstance(permissions, dict), "readiness permissions are missing")
    _current_require(
        set(permissions) == set(CURRENT_PERMISSION_FIELDS),
        "readiness permission allowlist mismatch",
    )
    for field in CURRENT_PERMISSION_FIELDS:
        _current_require(
            permissions.get(field) is False,
            f"topology v3 proposal readiness illegally enables {field}",
        )

    topology = report.get("official_currentness_topology")
    _current_require(
        isinstance(topology, Mapping),
        "topology v3 proposal readiness is missing",
    )
    _current_require(
        topology.get("status")
        == "V2_LAUNCHER_INTEGRITY_REJECTED_AWAIT_V3_OFFLINE_REFREEZE_APPROVAL",
        "topology v3 proposal status mismatch",
    )
    for field in (
        "execution_authorized",
        "network_authorized",
        "v2_execution_manifest_present",
        "v2_execution_approval_receipt_present",
        "v2_launch_record_present",
        "writer_claim_present",
        "v2_output_present",
        "v3_runtime_present",
        "v3_tests_present",
        "v3_runtime_manifest_present",
        "v3_launcher_present",
        "v3_execution_manifest_present",
        "v3_execution_approval_receipt_present",
        "v3_launch_record_present",
        "v3_output_present",
    ):
        _current_require(
            topology.get(field) is False,
            f"topology v3 proposal {field} changed",
        )
    _current_require(
        topology.get("stopped_incomplete_retry_authorized") is False,
        "topology v3 proposal retry was enabled",
    )

    v2_proposal_path, v2_proposal = _current_ref(
        topology.get("proposal"),
        "topology v2 proposal",
        parse_json=True,
    )
    v2_runtime_path, v2_runtime_manifest = _current_ref(
        topology.get("runtime_manifest"),
        "topology v2 runtime manifest",
        parse_json=True,
    )
    v2_launcher_path, _ = _current_ref(
        topology.get("visible_launcher"),
        "topology v2 visible launcher",
        parse_json=False,
    )
    audit_path, audit = _current_ref(
        topology.get("integrity_audit"),
        "topology v2 launcher integrity audit",
        parse_json=True,
    )
    v3_proposal_path, v3_proposal = _current_ref(
        topology.get("v3_refreeze_proposal"),
        "topology v3 refreeze proposal",
        parse_json=True,
    )
    _current_require(isinstance(v2_proposal, dict), "topology v2 proposal is missing")
    _current_require(
        isinstance(v2_runtime_manifest, dict),
        "topology v2 runtime manifest is missing",
    )
    _current_require(isinstance(audit, dict), "topology v2 integrity audit is missing")
    _current_require(isinstance(v3_proposal, dict), "topology v3 proposal is missing")

    audit_hash = str((topology.get("integrity_audit") or {}).get("audit_hash") or "")
    _current_require(
        audit.get("status") == "CRITICAL_BLOCKED_BEFORE_NETWORK_V2_NOT_LAUNCHABLE"
        and audit.get("audit_hash_method")
        == "sha256_canonical_json_excluding_audit_hash"
        and audit.get("audit_hash") == audit_hash
        and canonical_hash_without(audit, "audit_hash") == audit_hash,
        "topology v2 integrity audit binding mismatch",
    )
    finding = audit.get("finding") or {}
    _current_require(
        finding.get("finding_id") == "V2_ACTIVE_RUN_GATE_JSON_MODE_MISSING"
        and finding.get("json_parse_succeeds") is False
        and finding.get("network_accessed") is False,
        "topology v2 integrity finding changed",
    )

    proposal_hash = str(
        (topology.get("v3_refreeze_proposal") or {}).get("proposal_hash") or ""
    )
    _current_require(
        v3_proposal.get("status") == "PLANONLY_AWAIT_EXACT_OFFLINE_REFREEZE_APPROVAL"
        and v3_proposal.get("proposal_hash_method")
        == "sha256_canonical_json_excluding_proposal_hash"
        and v3_proposal.get("proposal_hash") == proposal_hash
        and canonical_hash_without(v3_proposal, "proposal_hash") == proposal_hash,
        "topology v3 proposal hash binding mismatch",
    )
    _current_require(
        (v3_proposal.get("defect_audit") or {}).get("path") == str(audit_path)
        and (v3_proposal.get("defect_audit") or {}).get("file_sha256")
        == (topology.get("integrity_audit") or {}).get("file_sha256")
        and (v3_proposal.get("defect_audit") or {}).get("audit_hash") == audit_hash,
        "topology v3 proposal audit binding mismatch",
    )
    superseded = v3_proposal.get("superseded_v2") or {}
    _current_require(
        superseded.get("run_id") == topology.get("run_id")
        and superseded.get("proposal_path") == str(v2_proposal_path)
        and superseded.get("proposal_file_sha256")
        == (topology.get("proposal") or {}).get("file_sha256")
        and superseded.get("runtime_manifest_path") == str(v2_runtime_path)
        and superseded.get("runtime_manifest_file_sha256")
        == (topology.get("runtime_manifest") or {}).get("file_sha256")
        and superseded.get("launcher_path") == str(v2_launcher_path)
        and superseded.get("launcher_file_sha256")
        == (topology.get("visible_launcher") or {}).get("file_sha256")
        and superseded.get("execution_authorized") is False,
        "topology v3 proposal superseded-v2 binding mismatch",
    )
    requested_scope = v3_proposal.get("requested_offline_scope") or {}
    for field in (
        "network",
        "official_source_content_read",
        "approval_receipt",
        "execution_manifest",
        "writer_claim",
        "topology_output",
        "identity_evidence",
        "request_plan",
        "currentness_verdict",
        "visible_launcher_execution",
    ):
        _current_require(
            requested_scope.get(field) is False,
            f"topology v3 proposal illegally enables {field}",
        )
    _current_require(
        v3_proposal.get("approval_effect")
        == "OFFLINE_REFREEZE_ONLY_NETWORK_REMAINS_BLOCKED"
        and v3_proposal.get("separate_network_execution_approval_required") is True,
        "topology v3 approval boundary changed",
    )

    successor = v3_proposal.get("proposed_successor") or {}
    _current_require(
        successor.get("run_id") == topology.get("successor_run_id"),
        "topology v3 successor run mismatch",
    )
    for field in (
        "runtime_module_path",
        "runtime_manifest_path",
        "launcher_path",
        "synthetic_tests_path",
        "output_path",
    ):
        successor_path = _resolve(str(successor.get(field) or ""))
        _current_require(
            not successor_path.exists(),
            f"topology v3 {field} exists before offline approval",
        )

    slow = report.get("slow_liquidity")
    _current_require(isinstance(slow, Mapping), "slow liquidity readiness is missing")
    _, current_gate = _current_ref(
        slow.get("gate"),
        "active gate",
        expected_path=gate_file,
        dynamic=True,
        parse_json=True,
    )
    _current_require(isinstance(current_gate, dict), "active gate payload is missing")
    _current_require(
        current_gate.get("status") == "READY_FOR_POSTPROCESS",
        "active gate is not open",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("run_id") == slow.get("run_id"),
        "active gate run changed",
        status="REFRESH_REQUIRED",
    )
    if writer_claim_file.exists():
        _current_error(
            "global market-data writer claim appeared after readiness",
            status="REFRESH_REQUIRED",
        )

    checkpoints = report.get("approval_checkpoints")
    _current_require(isinstance(checkpoints, list), "approval checkpoints are missing")
    expected_ids = [
        "pit_extension_schedule_activation",
        "slow_liquidity_currentness_topology_v3_offline_refreeze",
        "dense_three_hour_segmented_refreeze_phase_1",
    ]
    _current_require(
        [str(item.get("id") or "") for item in checkpoints if isinstance(item, dict)]
        == expected_ids,
        "topology v3 approval checkpoint allowlist mismatch",
    )
    checkpoint = checkpoints[1]
    _current_require(
        checkpoint.get("status") == "AWAIT_EXACT_HASH_BOUND_OFFLINE_REFREEZE_APPROVAL"
        and checkpoint.get("proposal_file_sha256")
        == (topology.get("v3_refreeze_proposal") or {}).get("file_sha256")
        and checkpoint.get("proposal_hash") == proposal_hash
        and checkpoint.get("integrity_audit_file_sha256")
        == (topology.get("integrity_audit") or {}).get("file_sha256")
        and checkpoint.get("integrity_audit_hash") == audit_hash,
        "topology v3 approval checkpoint binding mismatch",
    )
    _current_require(
        report.get("next_safe_action")
        == (
            "await_exact_slow_liquidity_official_currentness_"
            "topology_v3_offline_refreeze_approval"
        ),
        "topology v3 readiness next action changed",
    )
    return {
        "status": "READY",
        "pointer_path": str(pointer_file),
        "pointer_file_sha256": pointer_sha,
        "readiness_path": str(readiness_path),
        "readiness_file_sha256": report_sha,
        "readiness_hash": report["readiness_hash"],
        "generated_at_utc": report["generated_at_utc"],
        "source_status": report["status"],
        "execution_authorized": False,
        "next_safe_action": report["next_safe_action"],
        "approval_checkpoints": checkpoints,
        "primary_frozen_basis_terminal": report.get("primary_frozen_basis_terminal"),
        "official_currentness_topology": {
            "status": topology["status"],
            "run_id": topology["run_id"],
            "successor_run_id": topology["successor_run_id"],
            "integrity_audit_path": str(audit_path),
            "v3_refreeze_proposal_path": str(v3_proposal_path),
            "execution_authorized": False,
            "network_authorized": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "active_pit_pointer_path": str(
            _resolve(
                str(
                    ((report.get("pit_shadow_track") or {}).get("active_pointer") or {}).get(
                        "path"
                    )
                    or ""
                )
            )
        ),
    }


def _resolve_topology_v2_refreeze_readiness(
    report: Mapping[str, Any],
    *,
    pointer_file: Path,
    pointer_sha: str,
    readiness_path: Path,
    report_sha: str,
    gate_file: Path,
    writer_claim_file: Path,
) -> dict[str, Any]:
    permissions = report.get("permissions")
    _current_require(isinstance(permissions, dict), "readiness permissions are missing")
    _current_require(
        set(permissions) == set(CURRENT_PERMISSION_FIELDS),
        "readiness permission allowlist mismatch",
    )
    for field in CURRENT_PERMISSION_FIELDS:
        _current_require(
            permissions.get(field) is False,
            f"topology v2 readiness illegally enables {field}",
        )

    topology = report.get("official_currentness_topology")
    _current_require(isinstance(topology, Mapping), "topology v2 readiness is missing")
    _current_require(
        topology.get("status")
        == "FROZEN_OFFLINE_V2_AWAIT_EXACT_NETWORK_EXECUTION_APPROVAL",
        "topology v2 status mismatch",
    )
    _current_require(
        topology.get("execution_authorized") is False,
        "topology v2 execution was enabled",
    )
    _current_require(
        topology.get("network_authorized") is False,
        "topology v2 network was enabled",
    )
    _current_require(
        topology.get("future_execution_single_use_required") is True,
        "topology v2 future execution is not single-use",
    )
    _current_require(
        topology.get("stopped_incomplete_retry_authorized") is False,
        "topology v2 retry was enabled",
    )
    for field in (
        "execution_manifest_present",
        "execution_approval_receipt_present",
        "launch_record_present",
        "writer_claim_present",
        "output_present",
    ):
        _current_require(topology.get(field) is False, f"topology v2 {field} changed")

    proposal_path, proposal = _current_ref(
        topology.get("proposal"),
        "topology v2 proposal",
        parse_json=True,
    )
    postmortem_path, postmortem = _current_ref(
        topology.get("parent_postmortem"),
        "topology v2 parent postmortem",
        parse_json=True,
    )
    runtime_path, runtime_manifest = _current_ref(
        topology.get("runtime_manifest"),
        "topology v2 runtime manifest",
        parse_json=True,
    )
    launcher_path, _ = _current_ref(
        topology.get("visible_launcher"),
        "topology v2 visible launcher",
        parse_json=False,
    )
    _current_require(isinstance(proposal, dict), "topology v2 proposal payload is missing")
    _current_require(isinstance(postmortem, dict), "topology v2 postmortem payload is missing")
    _current_require(
        isinstance(runtime_manifest, dict),
        "topology v2 runtime payload is missing",
    )
    proposal_hash = str((topology.get("proposal") or {}).get("proposal_hash") or "")
    _current_require(
        HASH_PATTERN.fullmatch(proposal_hash) is not None
        and proposal.get("proposal_hash") == proposal_hash,
        "topology v2 proposal hash binding mismatch",
    )
    _current_require(
        postmortem.get("audit_hash")
        == (topology.get("parent_postmortem") or {}).get("audit_hash"),
        "topology v2 postmortem hash binding mismatch",
    )
    topology_runtime = _load_topology_v2_runtime_validator()
    try:
        topology_runtime.validate_runtime_manifest(
            runtime_manifest,
            repo_root=_REPO_ROOT,
        )
    except topology_runtime.TopologyDiscoveryError as exc:
        raise CurrentSprintReadinessError(
            f"topology v2 runtime validation failed: {exc}"
        ) from exc
    _current_require(
        runtime_manifest.get("run_id") == topology.get("run_id"),
        "topology v2 run binding mismatch",
    )
    _current_require(
        runtime_manifest.get("proposal")
        == {
            "path": str(proposal_path),
            "file_sha256": (topology.get("proposal") or {}).get("file_sha256"),
            "proposal_hash": proposal_hash,
        },
        "topology v2 runtime proposal binding mismatch",
    )
    runtime_code = runtime_manifest.get("runtime") or {}
    _current_require(
        runtime_code.get("visible_launcher_path") == str(launcher_path)
        and runtime_code.get("visible_launcher_sha256")
        == (topology.get("visible_launcher") or {}).get("file_sha256"),
        "topology v2 launcher binding mismatch",
    )
    _current_require(
        (runtime_manifest.get("parent_terminal") or {}).get("postmortem_path")
        == str(postmortem_path),
        "topology v2 postmortem path mismatch",
    )
    output_path = _resolve(str(topology.get("output_path") or ""))
    _current_require(
        output_path == topology_runtime.OUTPUT_PATH,
        "topology v2 output path mismatch",
    )
    _current_require(not output_path.exists(), "topology v2 output exists before approval")

    slow = report.get("slow_liquidity")
    _current_require(isinstance(slow, Mapping), "slow liquidity readiness is missing")
    _, current_gate = _current_ref(
        slow.get("gate"),
        "active gate",
        expected_path=gate_file,
        dynamic=True,
        parse_json=True,
    )
    _current_require(isinstance(current_gate, dict), "active gate payload is missing")
    _current_require(
        current_gate.get("status") == "READY_FOR_POSTPROCESS",
        "active gate is not open",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("run_id") == slow.get("run_id"),
        "active gate run changed",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("next_goal_decision") == EXPECTED_QUALITY_DECISION,
        "active gate decision changed",
        status="REFRESH_REQUIRED",
    )
    if writer_claim_file.exists():
        _current_error(
            "global market-data writer claim appeared after readiness",
            status="REFRESH_REQUIRED",
        )

    checkpoints = report.get("approval_checkpoints")
    _current_require(isinstance(checkpoints, list), "approval checkpoints are missing")
    expected_ids = [
        "pit_extension_schedule_activation",
        "slow_liquidity_currentness_topology_v2_execution",
        "dense_three_hour_segmented_refreeze_phase_1",
    ]
    _current_require(
        [str(item.get("id") or "") for item in checkpoints if isinstance(item, dict)]
        == expected_ids,
        "topology v2 approval checkpoint allowlist mismatch",
    )
    topology_checkpoint = checkpoints[1]
    _current_require(
        topology_checkpoint.get("status")
        == "AWAIT_EXACT_CODE_BOUND_NETWORK_EXECUTION_APPROVAL"
        and topology_checkpoint.get("proposal_file_sha256")
        == (topology.get("proposal") or {}).get("file_sha256")
        and topology_checkpoint.get("proposal_hash") == proposal_hash
        and topology_checkpoint.get("runtime_manifest_file_sha256")
        == (topology.get("runtime_manifest") or {}).get("file_sha256")
        and topology_checkpoint.get("runtime_manifest_hash")
        == runtime_manifest.get("manifest_hash")
        and topology_checkpoint.get("visible_launcher_file_sha256")
        == (topology.get("visible_launcher") or {}).get("file_sha256"),
        "topology v2 approval checkpoint binding mismatch",
    )
    _current_require(
        report.get("next_safe_action")
        == "await_exact_slow_liquidity_official_currentness_topology_v2_execution_approval",
        "topology v2 readiness next action changed",
    )
    return {
        "status": "READY",
        "pointer_path": str(pointer_file),
        "pointer_file_sha256": pointer_sha,
        "readiness_path": str(readiness_path),
        "readiness_file_sha256": report_sha,
        "readiness_hash": report["readiness_hash"],
        "generated_at_utc": report["generated_at_utc"],
        "source_status": report["status"],
        "execution_authorized": False,
        "next_safe_action": report["next_safe_action"],
        "approval_checkpoints": checkpoints,
        "primary_frozen_basis_terminal": report.get("primary_frozen_basis_terminal"),
        "official_currentness_topology": {
            "status": topology["status"],
            "run_id": topology["run_id"],
            "proposal_path": str(proposal_path),
            "runtime_manifest_path": str(runtime_path),
            "visible_launcher_path": str(launcher_path),
            "output_path": str(output_path),
            "execution_authorized": False,
            "network_authorized": False,
            "future_execution_single_use_required": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "active_pit_pointer_path": str(
            _resolve(
                str(
                    ((report.get("pit_shadow_track") or {}).get("active_pointer") or {}).get(
                        "path"
                    )
                    or ""
                )
            )
        ),
    }


def _resolve_topology_v3_refreeze_readiness(
    report: Mapping[str, Any],
    *,
    pointer_file: Path,
    pointer_sha: str,
    readiness_path: Path,
    report_sha: str,
    gate_file: Path,
    writer_claim_file: Path,
) -> dict[str, Any]:
    permissions = report.get("permissions")
    _current_require(isinstance(permissions, dict), "readiness permissions are missing")
    _current_require(
        set(permissions) == set(CURRENT_PERMISSION_FIELDS),
        "readiness permission allowlist mismatch",
    )
    for field in CURRENT_PERMISSION_FIELDS:
        _current_require(
            permissions.get(field) is False,
            f"topology v3 readiness illegally enables {field}",
        )

    topology = report.get("official_currentness_topology")
    _current_require(isinstance(topology, Mapping), "topology v3 readiness is missing")
    _current_require(
        topology.get("status")
        == "FROZEN_OFFLINE_V3_AWAIT_EXACT_NETWORK_EXECUTION_APPROVAL",
        "topology v3 status mismatch",
    )
    _current_require(
        topology.get("execution_authorized") is False,
        "topology v3 execution was enabled",
    )
    _current_require(
        topology.get("network_authorized") is False,
        "topology v3 network was enabled",
    )
    _current_require(
        topology.get("future_execution_single_use_required") is True,
        "topology v3 future execution is not single-use",
    )
    _current_require(
        topology.get("stopped_incomplete_retry_authorized") is False,
        "topology v3 retry was enabled",
    )
    for field in (
        "execution_manifest_present",
        "execution_approval_receipt_present",
        "launch_record_present",
        "writer_claim_present",
        "output_present",
    ):
        _current_require(topology.get(field) is False, f"topology v3 {field} changed")

    proposal_path, proposal = _current_ref(
        topology.get("proposal"),
        "topology v3 proposal",
        parse_json=True,
    )
    audit_path, audit = _current_ref(
        topology.get("integrity_audit"),
        "topology v3 integrity audit",
        parse_json=True,
    )
    runtime_path, runtime_manifest = _current_ref(
        topology.get("runtime_manifest"),
        "topology v3 runtime manifest",
        parse_json=True,
    )
    launcher_path, _ = _current_ref(
        topology.get("visible_launcher"),
        "topology v3 visible launcher",
        parse_json=False,
    )
    _current_require(isinstance(proposal, dict), "topology v3 proposal payload is missing")
    _current_require(isinstance(audit, dict), "topology v3 integrity audit payload is missing")
    _current_require(
        isinstance(runtime_manifest, dict),
        "topology v3 runtime payload is missing",
    )
    proposal_hash = str((topology.get("proposal") or {}).get("proposal_hash") or "")
    audit_hash = str((topology.get("integrity_audit") or {}).get("audit_hash") or "")
    _current_require(
        HASH_PATTERN.fullmatch(proposal_hash) is not None
        and proposal.get("proposal_hash") == proposal_hash,
        "topology v3 proposal hash binding mismatch",
    )
    _current_require(
        HASH_PATTERN.fullmatch(audit_hash) is not None
        and audit.get("audit_hash") == audit_hash,
        "topology v3 integrity audit hash binding mismatch",
    )
    topology_runtime = _load_topology_v3_runtime_validator()
    try:
        topology_runtime.validate_runtime_manifest(
            runtime_manifest,
            repo_root=_REPO_ROOT,
        )
    except topology_runtime.TopologyDiscoveryError as exc:
        raise CurrentSprintReadinessError(
            f"topology v3 runtime validation failed: {exc}"
        ) from exc
    _current_require(
        runtime_manifest.get("run_id") == topology.get("run_id"),
        "topology v3 run binding mismatch",
    )
    _current_require(
        runtime_manifest.get("proposal")
        == {
            "path": str(proposal_path),
            "file_sha256": (topology.get("proposal") or {}).get("file_sha256"),
            "proposal_hash": proposal_hash,
        },
        "topology v3 runtime proposal binding mismatch",
    )
    _current_require(
        runtime_manifest.get("defect_audit")
        == {
            "path": str(audit_path),
            "file_sha256": (topology.get("integrity_audit") or {}).get("file_sha256"),
            "audit_hash": audit_hash,
            "finding_id": "V2_ACTIVE_RUN_GATE_JSON_MODE_MISSING",
        },
        "topology v3 runtime integrity audit binding mismatch",
    )
    runtime_code = runtime_manifest.get("runtime") or {}
    _current_require(
        runtime_code.get("visible_launcher_path") == str(launcher_path)
        and runtime_code.get("visible_launcher_sha256")
        == (topology.get("visible_launcher") or {}).get("file_sha256"),
        "topology v3 launcher binding mismatch",
    )
    output_path = _resolve(str(topology.get("output_path") or ""))
    _current_require(
        output_path == topology_runtime.OUTPUT_PATH,
        "topology v3 output path mismatch",
    )
    _current_require(not output_path.exists(), "topology v3 output exists before approval")

    slow = report.get("slow_liquidity")
    _current_require(isinstance(slow, Mapping), "slow liquidity readiness is missing")
    _, current_gate = _current_ref(
        slow.get("gate"),
        "active gate",
        expected_path=gate_file,
        dynamic=True,
        parse_json=True,
    )
    _current_require(isinstance(current_gate, dict), "active gate payload is missing")
    _current_require(
        current_gate.get("status") == "READY_FOR_POSTPROCESS",
        "active gate is not open",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("run_id") == slow.get("run_id"),
        "active gate run changed",
        status="REFRESH_REQUIRED",
    )
    _current_require(
        current_gate.get("next_goal_decision") == EXPECTED_QUALITY_DECISION,
        "active gate decision changed",
        status="REFRESH_REQUIRED",
    )
    if writer_claim_file.exists():
        _current_error(
            "global market-data writer claim appeared after readiness",
            status="REFRESH_REQUIRED",
        )

    checkpoints = report.get("approval_checkpoints")
    _current_require(isinstance(checkpoints, list), "approval checkpoints are missing")
    expected_ids = [
        "pit_extension_schedule_activation",
        "slow_liquidity_currentness_topology_v3_execution",
        "dense_three_hour_segmented_refreeze_phase_1",
    ]
    _current_require(
        [str(item.get("id") or "") for item in checkpoints if isinstance(item, dict)]
        == expected_ids,
        "topology v3 approval checkpoint allowlist mismatch",
    )
    topology_checkpoint = checkpoints[1]
    _current_require(
        topology_checkpoint.get("status")
        == "AWAIT_EXACT_CODE_BOUND_NETWORK_EXECUTION_APPROVAL"
        and topology_checkpoint.get("proposal_file_sha256")
        == (topology.get("proposal") or {}).get("file_sha256")
        and topology_checkpoint.get("proposal_hash") == proposal_hash
        and topology_checkpoint.get("integrity_audit_file_sha256")
        == (topology.get("integrity_audit") or {}).get("file_sha256")
        and topology_checkpoint.get("integrity_audit_hash") == audit_hash
        and topology_checkpoint.get("runtime_manifest_file_sha256")
        == (topology.get("runtime_manifest") or {}).get("file_sha256")
        and topology_checkpoint.get("runtime_manifest_hash")
        == runtime_manifest.get("manifest_hash")
        and topology_checkpoint.get("visible_launcher_file_sha256")
        == (topology.get("visible_launcher") or {}).get("file_sha256"),
        "topology v3 approval checkpoint binding mismatch",
    )
    _current_require(
        report.get("next_safe_action")
        == "await_exact_slow_liquidity_official_currentness_topology_v3_execution_approval",
        "topology v3 readiness next action changed",
    )
    return {
        "status": "READY",
        "pointer_path": str(pointer_file),
        "pointer_file_sha256": pointer_sha,
        "readiness_path": str(readiness_path),
        "readiness_file_sha256": report_sha,
        "readiness_hash": report["readiness_hash"],
        "generated_at_utc": report["generated_at_utc"],
        "source_status": report["status"],
        "execution_authorized": False,
        "next_safe_action": report["next_safe_action"],
        "approval_checkpoints": checkpoints,
        "primary_frozen_basis_terminal": report.get("primary_frozen_basis_terminal"),
        "official_currentness_topology": {
            "status": topology["status"],
            "run_id": topology["run_id"],
            "proposal_path": str(proposal_path),
            "integrity_audit_path": str(audit_path),
            "runtime_manifest_path": str(runtime_path),
            "visible_launcher_path": str(launcher_path),
            "output_path": str(output_path),
            "execution_authorized": False,
            "network_authorized": False,
            "future_execution_single_use_required": True,
            "stopped_incomplete_retry_authorized": False,
        },
        "active_pit_pointer_path": str(
            _resolve(
                str(
                    ((report.get("pit_shadow_track") or {}).get("active_pointer") or {}).get(
                        "path"
                    )
                    or ""
                )
            )
        ),
    }


def resolve_current_sprint_readiness(
    pointer_path: str | Path,
    *,
    gate_path: str | Path,
    pit_pointer_path: str | Path,
    writer_claim_path: str | Path,
) -> dict[str, Any]:
    pointer_file = _resolve(pointer_path)
    gate_file = _resolve(gate_path)
    pit_pointer_file = _resolve(pit_pointer_path)
    writer_claim_file = _resolve(writer_claim_path)
    pointer, _, pointer_sha = _read_current_json(
        pointer_file,
        "current sprint readiness pointer",
        missing_status="MISSING",
    )
    _current_require(pointer.get("schema") == POINTER_SCHEMA, "pointer schema mismatch")
    _current_require(pointer.get("status") == "ACTIVE", "pointer is not ACTIVE")
    _current_require(pointer.get("project") == "trading_mvp", "pointer project mismatch")
    _require_aware_timestamp(pointer.get("updated_at_utc"), "pointer timestamp")

    try:
        readiness_path = _resolve(str(pointer.get("readiness_path") or ""))
    except (OSError, ValueError) as exc:
        raise CurrentSprintReadinessError("invalid readiness path") from exc
    readiness_root = (pointer_file.parent / "readiness").resolve()
    _current_require(
        readiness_path != readiness_root and readiness_root in readiness_path.parents,
        "readiness path escapes the allowed directory",
    )
    pointer_file_hash = str(pointer.get("readiness_file_sha256") or "").lower()
    pointer_readiness_hash = str(pointer.get("readiness_hash") or "").lower()
    _current_require(
        HASH_PATTERN.fullmatch(pointer_file_hash) is not None,
        "invalid readiness file SHA-256",
    )
    _current_require(
        HASH_PATTERN.fullmatch(pointer_readiness_hash) is not None,
        "invalid readiness canonical hash",
    )
    report, _, report_sha = _read_current_json(
        readiness_path,
        "current sprint readiness",
        missing_status="MISSING",
    )
    _current_require(
        report_sha == pointer_file_hash,
        "readiness file hash mismatch",
    )
    if report.get("schema") == LEGACY_READINESS_SCHEMA:
        _current_error(
            "readiness schema is superseded and requires an offline refresh",
            status="REFRESH_REQUIRED",
        )
    _current_require(report.get("schema") == READINESS_SCHEMA, "readiness schema mismatch")
    source_status = str(report.get("status") or "")
    _current_require(
        source_status in CURRENT_READINESS_STATUSES,
        "readiness status mismatch",
    )
    identity_runtime_frozen = source_status in {
        IDENTITY_PHASE1_READINESS_STATUS,
        IDENTITY_PHASE2_READINESS_STATUS,
    }
    identity_execution_authorized = (
        source_status == IDENTITY_PHASE2_READINESS_STATUS
    )
    _current_require(report.get("project") == "trading_mvp", "readiness project mismatch")
    _current_require(
        report.get("goal") == "One-Week Historical Edge Sprint",
        "readiness goal mismatch",
    )
    _current_require(report.get("research_only") is True, "readiness is not research-only")
    _current_require(
        report.get("readiness_hash_method") == READINESS_HASH_METHOD,
        "readiness hash method mismatch",
    )
    _require_aware_timestamp(report.get("generated_at_utc"), "readiness timestamp")
    report_hash = str(report.get("readiness_hash") or "").lower()
    _current_require(report_hash == pointer_readiness_hash, "pointer readiness hash mismatch")
    _current_require(
        canonical_hash_without(report, "readiness_hash") == report_hash,
        "readiness canonical hash mismatch",
    )

    if source_status == TOPOLOGY_V3_REFREEZE_READINESS_STATUS:
        return _resolve_topology_v3_refreeze_readiness(
            report,
            pointer_file=pointer_file,
            pointer_sha=pointer_sha,
            readiness_path=readiness_path,
            report_sha=report_sha,
            gate_file=gate_file,
            writer_claim_file=writer_claim_file,
        )
    if source_status == TOPOLOGY_V3_OFFLINE_REFREEZE_APPROVAL_READINESS_STATUS:
        return _resolve_topology_v3_offline_refreeze_approval_readiness(
            report,
            pointer_file=pointer_file,
            pointer_sha=pointer_sha,
            readiness_path=readiness_path,
            report_sha=report_sha,
            gate_file=gate_file,
            writer_claim_file=writer_claim_file,
        )
    if source_status == TOPOLOGY_V2_REFREEZE_READINESS_STATUS:
        return _resolve_topology_v2_refreeze_readiness(
            report,
            pointer_file=pointer_file,
            pointer_sha=pointer_sha,
            readiness_path=readiness_path,
            report_sha=report_sha,
            gate_file=gate_file,
            writer_claim_file=writer_claim_file,
        )
    if source_status == TOPOLOGY_EXECUTION_READINESS_STATUS:
        return _resolve_topology_execution_readiness(
            report,
            pointer_file=pointer_file,
            pointer_sha=pointer_sha,
            readiness_path=readiness_path,
            report_sha=report_sha,
            gate_file=gate_file,
            writer_claim_file=writer_claim_file,
        )

    permissions = report.get("permissions")
    _current_require(isinstance(permissions, dict), "readiness permissions are missing")
    _current_require(
        set(permissions) == set(CURRENT_PERMISSION_FIELDS),
        "readiness permission allowlist mismatch",
    )
    for field in CURRENT_PERMISSION_FIELDS:
        expected = (
            identity_execution_authorized
            if field == "identity_verification_authorized"
            else False
        )
        error = f"readiness permission mismatch: {field}"
        if expected is False and permissions.get(field) is True:
            error = f"readiness illegally enables {field}"
        _current_require(
            permissions.get(field) is expected,
            error,
        )

    primary_basis = report.get("primary_frozen_basis_terminal")
    slow = report.get("slow_liquidity")
    identity = report.get("official_identity_phase_1")
    pit = report.get("pit_shadow_track")
    dense = report.get("dense_three_hour_refreeze_phase_1")
    _current_require(
        isinstance(primary_basis, dict),
        "primary frozen basis terminal readiness is missing",
    )
    _current_require(isinstance(slow, dict), "slow liquidity readiness is missing")
    _current_require(isinstance(identity, dict), "identity phase 1 readiness is missing")
    _current_require(isinstance(pit, dict), "PIT readiness is missing")
    _current_require(isinstance(dense, dict), "Dense phase 1 readiness is missing")

    sprint_plan_path, _ = _current_ref(
        primary_basis.get("sprint_plan"),
        "primary basis sprint plan",
    )
    primary_basis_audit_path, _ = _current_ref(
        primary_basis.get("currentness_audit"),
        "primary basis currentness audit",
        parse_json=True,
    )
    primary_basis_report_path, _ = _current_ref(
        primary_basis.get("terminal_report"),
        "primary basis terminal report",
        parse_json=True,
    )
    _current_require(
        primary_basis.get("status") == "TERMINAL_CLOSED_INSUFFICIENT_DATA",
        "primary basis terminal status mismatch",
    )
    _current_require(
        primary_basis.get("hypothesis_id") == EXPECTED_PRIMARY_BASIS_HYPOTHESIS,
        "primary basis hypothesis mismatch",
    )
    _current_require(
        primary_basis.get("verdict") == EXPECTED_PRIMARY_BASIS_VERDICT,
        "primary basis verdict mismatch",
    )
    _current_require(
        primary_basis.get("reason_code") == EXPECTED_PRIMARY_BASIS_REASON,
        "primary basis reason mismatch",
    )
    for field in (
        "edge_evaluated",
        "market_rows_read",
        "oos_read",
        "returns_read",
        "pnl_read",
        "repeat_same_contract_authorized",
        "retune_authorized",
        "collector_launch_authorized",
        "execution_authorized",
    ):
        _current_require(
            primary_basis.get(field) is False,
            f"primary basis terminal illegally enables {field}",
        )

    _, slow_plan = _current_ref(slow.get("plan"), "slow plan", parse_json=True)
    _current_ref(slow.get("approval_receipt"), "slow approval receipt", parse_json=True)
    _, slow_launch = _current_ref(
        slow.get("launch_record"),
        "slow launch record",
        parse_json=True,
    )
    _, slow_manifest = _current_ref(
        slow.get("manifest"),
        "slow manifest",
        parse_json=True,
    )
    _current_ref(slow.get("output"), "slow output")
    _, slow_quality = _current_ref(
        slow.get("technical_quality"),
        "slow technical quality",
        parse_json=True,
    )
    _, current_gate = _current_ref(
        slow.get("gate"),
        "active gate",
        expected_path=gate_file,
        dynamic=True,
        parse_json=True,
    )
    _current_require(isinstance(slow_plan, dict), "slow plan payload is missing")
    _current_require(isinstance(slow_launch, dict), "slow launch payload is missing")
    _current_require(isinstance(slow_manifest, dict), "slow manifest payload is missing")
    _current_require(isinstance(slow_quality, dict), "slow quality payload is missing")
    _current_require(isinstance(current_gate, dict), "active gate payload is missing")
    slow_run_id = str(slow.get("run_id") or "")
    slow_plan_hash = str((slow.get("plan") or {}).get("plan_hash") or "").lower()
    _current_require(bool(slow_run_id), "slow run id is missing")
    _current_require(
        HASH_PATTERN.fullmatch(slow_plan_hash) is not None,
        "invalid slow plan hash",
    )
    _current_require(slow_plan.get("plan_hash") == slow_plan_hash, "slow plan hash binding mismatch")
    _current_require(slow_launch.get("status") == "COMPLETE", "slow launch is not COMPLETE")
    _current_require(slow_manifest.get("run_id") == slow_run_id, "slow manifest run mismatch")
    _current_require(slow_manifest.get("final") is True, "slow manifest is not final")
    _current_require(int(slow_manifest.get("rows", -1)) > 0, "slow manifest has no rows")
    _current_require(int(slow_manifest.get("errors", -1)) == 0, "slow manifest has errors")
    _current_require(
        slow_quality.get("decision") == EXPECTED_QUALITY_DECISION,
        "slow quality decision mismatch",
    )
    _current_require(slow_quality.get("accepted") is True, "slow quality is not accepted")
    _current_require(current_gate.get("status") == "READY_FOR_POSTPROCESS", "active gate is not open", status="REFRESH_REQUIRED")
    _current_require(current_gate.get("run_id") == slow_run_id, "active gate run changed", status="REFRESH_REQUIRED")
    _current_require(
        current_gate.get("next_goal_decision") == EXPECTED_QUALITY_DECISION,
        "active gate decision changed",
        status="REFRESH_REQUIRED",
    )
    _current_require(slow.get("identity_verification_required") is True, "identity checkpoint is missing")
    _current_require(slow.get("identity_verification_authorized") is False, "identity verification is authorized")
    _current_require(slow.get("evaluator_or_oos_authorized") is False, "evaluator or OOS is authorized")

    _, identity_payload = _current_ref(identity, "identity proposal", parse_json=True)
    identity_hash = str(identity.get("proposal_hash") or "").lower()
    _current_require(
        HASH_PATTERN.fullmatch(identity_hash) is not None,
        "invalid identity proposal hash",
    )
    _current_require(isinstance(identity_payload, dict), "identity proposal payload is missing")
    _current_require(identity_payload.get("proposal_hash") == identity_hash, "identity proposal hash binding mismatch")
    identity_runtime_state: dict[str, Any] | None = None
    identity_execution_state: dict[str, Any] | None = None
    if identity_runtime_frozen:
        _current_require(
            identity.get("status") == IDENTITY_PHASE1_STATUS,
            "identity runtime status mismatch",
        )
        _current_require(
            identity.get("phase_1_approved") is True
            and identity.get("offline_implementation_completed") is True,
            "identity offline phase is not complete",
        )
        runtime_binding = identity.get("runtime_manifest")
        _current_require(
            isinstance(runtime_binding, Mapping),
            "identity runtime manifest binding is missing",
        )
        try:
            identity_runtime_state = _validate_identity_runtime_manifest(
                _resolve(str(runtime_binding.get("path") or "")),
                identity=identity,
            )
        except ReadinessError as exc:
            raise CurrentSprintReadinessError(
                f"identity runtime validation failed: {exc}"
            ) from exc
        _current_require(
            identity_runtime_state == runtime_binding,
            "identity runtime manifest binding changed",
        )
    else:
        _current_require(
            identity.get("status") == "AWAIT_EXACT_HASH_BOUND_APPROVAL",
            "identity status mismatch",
        )
        _current_require(
            identity.get("phase_1_approved") is False,
            "identity offline phase is unexpectedly approved",
        )
    _current_require(
        identity.get("network_execution_authorized") is False
        and identity.get("identity_output_authorized") is False,
        "identity phase 1 illegally authorizes execution",
    )
    if identity_execution_authorized:
        phase2_binding = report.get("official_identity_phase_2")
        _current_require(
            isinstance(phase2_binding, Mapping),
            "identity phase 2 binding is missing",
        )
        try:
            identity_execution_state = _validate_identity_execution_manifest(
                _resolve(
                    str(
                        (phase2_binding.get("execution_manifest") or {}).get(
                            "path"
                        )
                        or ""
                    )
                ),
                runtime_state=identity_runtime_state or {},
            )
        except ReadinessError as exc:
            raise CurrentSprintReadinessError(
                f"identity execution validation failed: {exc}"
            ) from exc
        _current_require(
            identity_execution_state == phase2_binding,
            "identity phase 2 binding changed",
        )
    else:
        _current_require(
            "official_identity_phase_2" not in report,
            "identity phase 2 appears without exact execution approval",
        )

    active_pointer_path, active_pointer = _current_ref(
        pit.get("active_pointer"),
        "active PIT pointer",
        expected_path=pit_pointer_file,
        dynamic=True,
        parse_json=True,
    )
    ledger_path, _ = _current_ref(
        pit.get("quality_ledger"),
        "PIT quality ledger",
        dynamic=True,
    )
    extension_path, extension_plan = _current_ref(
        pit.get("extension_plan"),
        "PIT extension plan",
        parse_json=True,
    )
    _current_require(isinstance(active_pointer, dict), "active PIT pointer payload is missing")
    _current_require(isinstance(extension_plan, dict), "PIT extension payload is missing")
    _current_require(active_pointer.get("status") == "ACTIVE", "active PIT pointer changed", status="REFRESH_REQUIRED")
    _current_require(
        _resolve(str(active_pointer.get("quality_ledger_path") or "")) == ledger_path,
        "PIT ledger path changed",
        status="REFRESH_REQUIRED",
    )
    active_plan_hash = str((pit.get("active_pointer") or {}).get("plan_hash") or "")
    _current_require(active_pointer.get("plan_hash") == active_plan_hash, "active PIT plan changed", status="REFRESH_REQUIRED")
    extension_hash = str((pit.get("extension_plan") or {}).get("plan_hash") or "").lower()
    _current_require(
        HASH_PATTERN.fullmatch(extension_hash) is not None,
        "invalid PIT extension plan hash",
    )
    _current_require(extension_plan.get("plan_hash") == extension_hash, "PIT extension hash binding mismatch")
    _current_require(extension_plan.get("mode") == "PlanOnly", "PIT extension is not PlanOnly")
    _current_require(extension_plan.get("schedule_approved") is False, "PIT extension is already approved")
    _current_require(extension_plan.get("collection_started") is False, "PIT extension collection already started")
    _current_require(pit.get("accepted_distinct_dates") == 10, "PIT accepted date count mismatch")
    _current_require(pit.get("train_target_distinct_dates") == 20, "PIT train target mismatch")
    _current_require(pit.get("extension_segments") == 10, "PIT extension segment count mismatch")
    _current_require(pit.get("extension_approval_required") is True, "PIT approval checkpoint is missing")
    _current_require(pit.get("extension_activation_authorized") is False, "PIT activation is authorized")
    _current_require(pit.get("collector_launch_authorized") is False, "PIT collector launch is authorized")
    segments = extension_plan.get("sealed_schedule", {}).get("segments")
    if not isinstance(segments, list):
        segments = extension_plan.get("segments")
    _current_require(isinstance(segments, list) and len(segments) == 10, "PIT extension segments are invalid")
    for segment in segments:
        _current_require(isinstance(segment, dict), "PIT extension segment is invalid")
        _current_require(segment.get("duration_sec") == 1_200, "PIT extension duration changed")

    dense_path, dense_payload = _current_ref(dense, "Dense proposal", parse_json=True)
    dense_hash = str(dense.get("proposal_hash") or "").lower()
    _current_require(
        HASH_PATTERN.fullmatch(dense_hash) is not None,
        "invalid Dense proposal hash",
    )
    _current_require(isinstance(dense_payload, dict), "Dense proposal payload is missing")
    _current_require(dense_payload.get("proposal_hash") == dense_hash, "Dense proposal hash binding mismatch")
    _current_require(dense.get("status") == "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL", "Dense status mismatch")
    for field in (
        "phase_1_approved",
        "implementation_authorized",
        "collector_launch_authorized",
    ):
        _current_require(dense.get(field) is False, f"Dense illegally enables {field}")

    checkpoints = report.get("approval_checkpoints")
    _current_require(isinstance(checkpoints, list), "approval checkpoints are missing")
    expected_checkpoint_ids = (
        IDENTITY_RUNTIME_CHECKPOINT_IDS
        if identity_runtime_frozen
        else CURRENT_CHECKPOINT_IDS
    )
    _current_require(len(checkpoints) == len(expected_checkpoint_ids), "approval checkpoint count mismatch")
    _current_require(
        [str(item.get("id") or "") for item in checkpoints if isinstance(item, dict)]
        == list(expected_checkpoint_ids),
        "approval checkpoint allowlist mismatch",
    )
    checkpoint_by_id = {str(item["id"]): item for item in checkpoints}
    for checkpoint in checkpoints:
        _current_require(isinstance(checkpoint, dict), "approval checkpoint is invalid")
        checkpoint_id = str(checkpoint.get("id") or "")
        expected_status = "AWAIT_EXACT_HASH_BOUND_APPROVAL"
        if checkpoint_id == IDENTITY_PHASE2_CHECKPOINT_ID:
            expected_status = (
                "APPROVED_SINGLE_USE"
                if identity_execution_authorized
                else "AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
            )
        _current_require(checkpoint.get("status") == expected_status, "approval checkpoint status mismatch")
    _current_require(
        checkpoint_by_id[expected_checkpoint_ids[0]].get("plan_hash") == extension_hash
        and checkpoint_by_id[expected_checkpoint_ids[0]].get("plan_file_sha256")
        == str((pit.get("extension_plan") or {}).get("file_sha256") or ""),
        "PIT approval checkpoint binding mismatch",
    )
    identity_checkpoint = checkpoint_by_id[expected_checkpoint_ids[1]]
    if identity_runtime_frozen:
        _current_require(identity_runtime_state is not None, "identity runtime state is missing")
        _current_require(
            identity_checkpoint.get("runtime_manifest_file_sha256")
            == identity_runtime_state["file_sha256"]
            and identity_checkpoint.get("runtime_manifest_hash")
            == identity_runtime_state["manifest_hash"],
            "identity runtime checkpoint binding mismatch",
        )
        if identity_execution_authorized:
            _current_require(identity_execution_state is not None, "identity execution state is missing")
            for key in (
                "execution_approval_receipt_file_sha256",
                "execution_approval_receipt_hash",
                "request_plan_sha256",
            ):
                _current_require(
                    identity_checkpoint.get(key) == identity_execution_state[key],
                    f"identity execution checkpoint binding mismatch: {key}",
                )
    else:
        _current_require(
            identity_checkpoint.get("proposal_hash") == identity_hash
            and identity_checkpoint.get("proposal_file_sha256")
            == str(identity.get("file_sha256") or ""),
            "identity approval checkpoint binding mismatch",
        )
    _current_require(
        checkpoint_by_id[expected_checkpoint_ids[2]].get("proposal_hash") == dense_hash
        and checkpoint_by_id[expected_checkpoint_ids[2]].get("proposal_file_sha256")
        == str(dense.get("file_sha256") or ""),
        "Dense approval checkpoint binding mismatch",
    )
    expected_next_safe_action = "await_one_exact_approval_checkpoint"
    if identity_runtime_frozen:
        expected_next_safe_action = "await_exact_code_bound_identity_execution_approval"
    if identity_execution_authorized:
        expected_next_safe_action = "run_exact_approved_slow_liquidity_official_identity_visible"
    _current_require(
        report.get("next_safe_action") == expected_next_safe_action,
        "readiness next action changed",
    )
    if writer_claim_file.exists():
        _current_error(
            "global market-data writer claim appeared after readiness",
            status="REFRESH_REQUIRED",
        )
    try:
        rebuilt = build_readiness(
            gate_path=gate_file,
            writer_claim_path=writer_claim_file,
            slow_plan_path=_resolve(str((slow.get("plan") or {}).get("path") or "")),
            expected_slow_plan_hash=slow_plan_hash,
            expected_slow_plan_file_sha256=str(
                (slow.get("plan") or {}).get("file_sha256") or ""
            ),
            identity_proposal_path=_resolve(str(identity.get("path") or "")),
            expected_identity_proposal_hash=identity_hash,
            expected_identity_proposal_file_sha256=str(
                identity.get("file_sha256") or ""
            ),
            pit_pointer_path=active_pointer_path,
            pit_extension_plan_path=extension_path,
            expected_pit_extension_plan_hash=extension_hash,
            expected_pit_extension_plan_file_sha256=str(
                (pit.get("extension_plan") or {}).get("file_sha256") or ""
            ),
            dense_proposal_path=dense_path,
            expected_dense_proposal_hash=dense_hash,
            expected_dense_proposal_file_sha256=str(
                dense.get("file_sha256") or ""
            ),
            identity_runtime_manifest_path=(
                _resolve(str(identity_runtime_state["path"]))
                if identity_runtime_state is not None
                else None
            ),
            identity_execution_manifest_path=(
                _resolve(
                    str(
                        (identity_execution_state["execution_manifest"])["path"]
                    )
                )
                if identity_execution_state is not None
                else None
            ),
            generated_at_utc=str(report.get("generated_at_utc") or ""),
        )
    except ReadinessError as exc:
        raise CurrentSprintReadinessError(
            f"current readiness evidence validation failed: {exc}",
            status="INVALID",
        ) from exc
    _current_require(
        rebuilt == report,
        "readiness report no longer matches current evidence",
    )

    return {
        "status": "READY",
        "pointer_path": str(pointer_file),
        "pointer_file_sha256": pointer_sha,
        "readiness_path": str(readiness_path),
        "readiness_file_sha256": report_sha,
        "readiness_hash": report_hash,
        "generated_at_utc": report["generated_at_utc"],
        "source_status": report["status"],
        "execution_authorized": identity_execution_authorized,
        "next_safe_action": report["next_safe_action"],
        "approval_checkpoints": checkpoints,
        "primary_frozen_basis_terminal": primary_basis,
        "official_identity_phase_1": {
            "status": identity["status"],
            "proposal_path": str(_resolve(str(identity["path"]))),
            "proposal_file_sha256": identity["file_sha256"],
            "proposal_hash": identity_hash,
            "implementation_authorized": identity_runtime_frozen,
            "network_execution_authorized": False,
            **(
                {
                    "runtime_manifest_path": identity_runtime_state["path"],
                    "runtime_manifest_file_sha256": identity_runtime_state[
                        "file_sha256"
                    ],
                    "runtime_manifest_hash": identity_runtime_state[
                        "manifest_hash"
                    ],
                }
                if identity_runtime_state is not None
                else {}
            ),
        },
        **(
            {"official_identity_phase_2": identity_execution_state}
            if identity_execution_state is not None
            else {}
        ),
        "pit_schedule_extension_candidate": {
            "status": "READY_FOR_APPROVAL",
            "approval_request_status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
            "plan_path": str(extension_path),
            "plan_file_sha256": (pit.get("extension_plan") or {})["file_sha256"],
            "plan_hash": extension_hash,
            "source_plan_hash": active_plan_hash,
            "nights": len(segments),
            "segment_duration_sec": 1_200,
            "first_start_local": pit.get("extension_first_start_local"),
            "last_end_local": pit.get("extension_last_end_local"),
            "schedule_approved": False,
            "automatic_launch_allowed": False,
            "approval_phrase": "",
        },
        "long_campaign_candidate": {
            "status": "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
            "campaign_id": dense_payload.get("campaign_id"),
            "hypothesis_id": dense_payload.get("hypothesis_id"),
            "data_type": dense_payload.get("data_type"),
            "proposal_path": str(dense_path),
            "proposal_file_sha256": dense["file_sha256"],
            "proposal_hash": dense_hash,
            "phase_1_approved": False,
            "implementation_authorized": False,
            "actual_collection_allowed": False,
            "collector_launch_authorized": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "active_pit_pointer_path": str(active_pointer_path),
    }


def _validate_primary_frozen_basis_terminal(
) -> dict[str, Any]:
    anchor = PRODUCTION_PRIMARY_BASIS_TRUST_ANCHOR
    sprint_plan_path = anchor.sprint_plan_path
    currentness_audit_path = anchor.currentness_audit_path
    terminal_report_path = anchor.terminal_report_path
    _require_file_hash(
        sprint_plan_path,
        anchor.sprint_plan_file_sha256,
        "primary basis sprint plan",
    )
    _require_file_hash(
        currentness_audit_path,
        anchor.currentness_audit_file_sha256,
        "primary basis currentness audit",
    )
    _require_file_hash(
        terminal_report_path,
        anchor.terminal_report_file_sha256,
        "primary basis terminal report",
    )
    audit = _load_json(currentness_audit_path, "primary basis currentness audit")
    terminal = _load_json(terminal_report_path, "primary basis terminal report")
    _reject_unsafe_true_flags(audit, "primary basis currentness audit")
    _reject_unsafe_true_flags(terminal, "primary basis terminal report")

    _require(
        audit.get("schema")
        == "trading_mvp_cross_venue_basis_terminal_currentness_audit_v1",
        "primary basis currentness audit schema mismatch",
    )
    goal_binding = audit.get("goal_binding")
    evidence = audit.get("v1_terminal_evidence")
    audit_verdict = audit.get("verdict")
    audit_safety = audit.get("safety")
    _require(isinstance(goal_binding, dict), "primary basis goal binding is missing")
    _require(isinstance(evidence, dict), "primary basis terminal evidence is missing")
    _require(isinstance(audit_verdict, dict), "primary basis audit verdict is missing")
    _require(isinstance(audit_safety, dict), "primary basis audit safety is missing")
    _require(
        goal_binding.get("named_primary_hypothesis")
        == EXPECTED_PRIMARY_BASIS_HYPOTHESIS,
        "primary basis goal hypothesis mismatch",
    )
    _require_exact_path(
        goal_binding.get("original_sprint_plan_path"),
        sprint_plan_path,
        "primary basis sprint plan",
    )
    _require(
        goal_binding.get("original_sprint_plan_sha256")
        == _sha256(sprint_plan_path),
        "primary basis sprint plan hash binding mismatch",
    )
    _require(
        evidence.get("hypothesis_id") == EXPECTED_PRIMARY_BASIS_HYPOTHESIS,
        "primary basis terminal hypothesis mismatch",
    )
    _require_exact_path(
        evidence.get("report_path"),
        terminal_report_path,
        "primary basis terminal report",
    )
    _require(
        evidence.get("report_file_sha256") == _sha256(terminal_report_path),
        "primary basis terminal report hash binding mismatch",
    )

    _require(
        terminal.get("schema")
        == "trading_mvp_historical_basis_retention_closure_v1",
        "primary basis terminal report schema mismatch",
    )
    _require(
        terminal.get("hypothesis_id") == EXPECTED_PRIMARY_BASIS_HYPOTHESIS,
        "primary basis terminal report hypothesis mismatch",
    )
    for mapping, label in ((evidence, "audit evidence"), (terminal, "terminal report")):
        _require(mapping.get("final") is True, f"primary basis {label} is not final")
        _require(
            mapping.get("verdict") == EXPECTED_PRIMARY_BASIS_VERDICT,
            f"primary basis {label} verdict mismatch",
        )
        _require(
            mapping.get("reason_code") == EXPECTED_PRIMARY_BASIS_REASON,
            f"primary basis {label} reason mismatch",
        )
        _require(
            mapping.get("edge_evaluated") is False,
            f"primary basis {label} says the edge was evaluated",
        )
        _require(
            mapping.get("pnl_read") is False,
            f"primary basis {label} says PnL was read",
        )
        _require(
            mapping.get("next_allowed_command")
            == EXPECTED_PRIMARY_BASIS_NEXT_COMMAND,
            f"primary basis {label} next command mismatch",
        )

    artifact_hash = _require_hash(
        terminal.get("artifact_hash"),
        "primary basis artifact hash",
    )
    _require(
        artifact_hash == anchor.artifact_hash,
        "primary basis artifact hash does not match trust anchor",
    )
    _require(
        evidence.get("artifact_hash") == artifact_hash,
        "primary basis artifact hash binding mismatch",
    )
    _require(
        evidence.get("retune_or_repeat_same_contract_allowed") is False,
        "primary basis audit enables repeat same contract",
    )
    _require(
        audit_verdict.get("v1_may_be_reopened_without_new_contract") is False,
        "primary basis audit permits reopening without a new contract",
    )
    _require(
        audit_verdict.get("basis_oos_or_pnl_action_due") is False,
        "primary basis audit schedules OOS or PnL",
    )
    _require_false(
        audit_safety,
        (
            "network_access",
            "new_collector_started",
            "market_rows_read",
            "oos_read",
            "returns_read",
            "pnl_read",
            "grid_or_retune",
            "paper_or_live",
            "private_api_keys",
            "real_capital",
            "leverage_or_margin",
        ),
        "primary basis audit",
    )

    frozen = terminal.get("frozen_contract")
    gate_evidence = terminal.get("gate_public_api_evidence")
    terminal_safety = terminal.get("safety")
    _require(isinstance(frozen, dict), "primary basis frozen contract is missing")
    _require(isinstance(gate_evidence, dict), "primary basis Gate evidence is missing")
    _require(isinstance(terminal_safety, dict), "primary basis terminal safety is missing")
    _require(
        frozen
        == {
            "interval": "5m",
            "required_history_days": 220,
            "warmup_days": 20,
            "train_days": 100,
            "oos_days": 100,
            "strategy_change_allowed": False,
        },
        "primary basis frozen contract mismatch",
    )
    _require(
        evidence.get("required_history_days") == 220
        and gate_evidence.get("required_days") == 220,
        "primary basis required history mismatch",
    )
    _require(
        evidence.get("maximum_recent_gate_history_days_at_5m") == 34.722
        and gate_evidence.get("maximum_recent_days_at_5m") == 34.722
        and gate_evidence.get("maximum_recent_points") == 10_000
        and gate_evidence.get("venue") == "gateio",
        "primary basis public retention evidence mismatch",
    )
    _require(
        gate_evidence.get("endpoint_family")
        == "/api/v4/futures/usdt/candlesticks"
        and gate_evidence.get("old_boundary_status") == 400
        and gate_evidence.get("old_boundary_label") == "INVALID_PARAM_VALUE"
        and "Maximum 10000 points recently are allowed"
        in str(gate_evidence.get("old_boundary_message") or "")
        and gate_evidence.get("recent_status") == 200
        and int(gate_evidence.get("recent_rows", 0)) > 0,
        "primary basis public retention evidence response mismatch",
    )
    _require(
        terminal_safety.get("research_only") is True
        and terminal_safety.get("public_api_only") is True,
        "primary basis terminal safety scope mismatch",
    )
    _require_false(
        terminal_safety,
        ("live_orders", "api_keys", "leverage_or_margin"),
        "primary basis terminal report",
    )
    _require(
        tuple(terminal.get("forbidden_actions") or ())
        == EXPECTED_PRIMARY_BASIS_FORBIDDEN_ACTIONS,
        "primary basis forbidden action contract mismatch",
    )

    return {
        "status": "TERMINAL_CLOSED_INSUFFICIENT_DATA",
        "hypothesis_id": EXPECTED_PRIMARY_BASIS_HYPOTHESIS,
        "sprint_plan": _file_ref(sprint_plan_path),
        "currentness_audit": _file_ref(currentness_audit_path),
        "terminal_report": {
            **_file_ref(terminal_report_path),
            "artifact_hash": artifact_hash,
        },
        "verdict": EXPECTED_PRIMARY_BASIS_VERDICT,
        "reason_code": EXPECTED_PRIMARY_BASIS_REASON,
        "required_history_days": 220,
        "maximum_recent_gate_history_days_at_5m": 34.722,
        "edge_evaluated": False,
        "market_rows_read": False,
        "oos_read": False,
        "returns_read": False,
        "pnl_read": False,
        "next_allowed_command": EXPECTED_PRIMARY_BASIS_NEXT_COMMAND,
        "forbidden_actions": list(EXPECTED_PRIMARY_BASIS_FORBIDDEN_ACTIONS),
        "repeat_same_contract_authorized": False,
        "retune_authorized": False,
        "collector_launch_authorized": False,
        "execution_authorized": False,
    }


def _validate_slow_liquidity(
    *,
    gate_path: Path,
    plan_path: Path,
    expected_plan_hash: str,
    expected_plan_file_sha256: str,
) -> dict[str, Any]:
    _require_file_hash(plan_path, expected_plan_file_sha256, "slow plan file")
    plan = _load_json(plan_path, "slow plan")
    _require(
        plan.get("schema")
        == "trading_mvp_slow_liquidity_history_recollect_planonly_v1",
        "slow plan schema mismatch",
    )
    _require(plan.get("mode") == "PlanOnly", "slow plan mode mismatch")
    _require(
        plan.get("status") == "AWAIT_EXACT_HASH_BOUND_APPROVAL",
        "slow plan immutable status mismatch",
    )
    _require(plan.get("actual_collection_allowed") is False, "slow plan is mutable")
    _require(
        plan.get("plan_hash") == expected_plan_hash,
        "slow plan hash mismatch",
    )

    execution = plan.get("execution")
    quality_contract = plan.get("data_quality_after_success")
    receipt_contract = plan.get("approval_receipt")
    _require(isinstance(execution, dict), "slow execution contract is missing")
    _require(isinstance(quality_contract, dict), "slow quality contract is missing")
    _require(isinstance(receipt_contract, dict), "slow approval contract is missing")
    run_id = str(execution.get("run_id") or "")
    _require(bool(run_id), "slow run id is missing")

    receipt_path = _resolve(str(receipt_contract.get("path") or ""))
    launch_path = _resolve(str(execution.get("launch_record_path") or ""))
    manifest_path = _resolve(str(execution.get("manifest_path") or ""))
    output_path = _resolve(str(execution.get("output_jsonl") or ""))
    quality_path = _resolve(str(quality_contract.get("output_path") or ""))
    for path, label in (
        (receipt_path, "approval receipt"),
        (launch_path, "launch record"),
        (manifest_path, "collection manifest"),
        (output_path, "collection output"),
        (quality_path, "quality report"),
    ):
        _require(path.is_file(), f"{label} is missing: {path}")

    receipt = _load_json(receipt_path, "approval receipt")
    launch = _load_json(launch_path, "launch record")
    manifest = _load_json(manifest_path, "collection manifest")
    quality = _load_json(quality_path, "quality report")
    gate = _load_json(gate_path, "active gate")
    provenance = quality.get("exact_recollect_provenance")
    _require(isinstance(provenance, dict), "quality provenance is missing")
    _require(provenance.get("run_id") == run_id, "quality run binding mismatch")

    provenance_bindings = (
        ("plan_path", "plan_file_sha256", plan_path, "slow plan"),
        (
            "approval_receipt_path",
            "approval_receipt_file_sha256",
            receipt_path,
            "approval receipt",
        ),
        (
            "launch_record_path",
            "launch_record_file_sha256",
            launch_path,
            "launch record",
        ),
        (
            "manifest_path",
            "manifest_file_sha256",
            manifest_path,
            "collection manifest",
        ),
        (
            "output_jsonl_path",
            "output_jsonl_file_sha256",
            output_path,
            "collection output",
        ),
    )
    for path_field, hash_field, expected_path, label in provenance_bindings:
        _require_exact_path(provenance.get(path_field), expected_path, label)
        _require_file_hash(expected_path, provenance.get(hash_field), label)
    _require(
        provenance.get("plan_hash") == expected_plan_hash,
        "quality plan hash binding mismatch",
    )
    _require(
        provenance.get("technical_quality_only") is True,
        "quality is not technical-only",
    )
    _require_false(
        provenance,
        (
            "official_identity_verification_authorized",
            "evaluator_or_oos_authorized",
            "stopped_incomplete_retry_authorized",
        ),
        "quality provenance",
    )

    _require(receipt.get("run_id") == run_id, "approval receipt run binding mismatch")
    _require(launch.get("run_id") == run_id, "launch run binding mismatch")
    _require(launch.get("status") == "COMPLETE", "launch is not COMPLETE")
    _require(manifest.get("run_id") == run_id, "manifest run binding mismatch")
    _require(manifest.get("final") is True, "manifest is not final")
    _require(int(manifest.get("rows", -1)) > 0, "manifest has no rows")
    _require(int(manifest.get("errors", -1)) == 0, "manifest contains errors")
    _require(
        tuple(manifest.get("selected_bases") or ()) == EXPECTED_BASES,
        "manifest base universe mismatch",
    )
    _require(
        tuple(manifest.get("exchanges") or ()) == EXPECTED_VENUES,
        "manifest venue universe mismatch",
    )
    _require(
        tuple(manifest.get("granularities") or ()) == EXPECTED_GRANULARITIES,
        "manifest granularity mismatch",
    )
    _require(manifest.get("history_days") == 56, "manifest history changed")

    _require(
        quality.get("decision") == EXPECTED_QUALITY_DECISION,
        "quality decision mismatch",
    )
    _require(quality.get("accepted") is True, "technical quality was not accepted")
    _require(quality.get("terminal") is False, "accepted quality is terminal")
    _require(
        quality.get("identity_verification_required") is True,
        "identity checkpoint is missing",
    )
    _require_false(
        quality,
        (
            "identity_verification_authorized",
            "retry_authorized",
            "rescope_authorized",
            "evaluator_or_oos_authorized",
            "replay_allowed",
            "grid_allowed",
            "paper_forward_allowed",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ),
        "quality report",
    )
    metrics = quality.get("metrics")
    _require(isinstance(metrics, dict), "quality metrics are missing")
    _require(metrics.get("line_count") == manifest.get("rows"), "row count mismatch")
    _require(metrics.get("manifest_errors") == 0, "quality reports manifest errors")
    _require(int(metrics.get("ok_rows", -1)) > 0, "quality has no valid rows")
    _require(metrics.get("ok_bases") == 9, "quality base count mismatch")
    _require(metrics.get("ok_exchanges") == 2, "quality venue count mismatch")
    _require(
        metrics.get("two_exchange_full_coverage_1h4h_bases") == 9,
        "quality full coverage base count mismatch",
    )
    _require(metrics.get("duplicate_candles") == 0, "quality has duplicates")

    _require(gate.get("status") == "READY_FOR_POSTPROCESS", "gate is not open")
    _require(gate.get("run_id") == run_id, "gate run binding mismatch")
    _require(
        gate.get("next_goal_decision") == EXPECTED_QUALITY_DECISION,
        "gate quality decision mismatch",
    )
    _require_exact_path(gate.get("manifest_path"), manifest_path, "gate manifest")
    _require_exact_path(
        gate.get("last_slow_liquidity_history_data_quality_output_path"),
        quality_path,
        "gate quality report",
    )
    _require_file_hash(
        quality_path,
        gate.get("last_slow_liquidity_history_data_quality_output_sha256"),
        "gate quality report",
    )
    _require_false(
        gate,
        (
            "replay_allowed",
            "grid_allowed",
            "paper_forward_allowed",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "identity_verification_authorized",
        ),
        "active gate",
    )
    _require(
        gate.get("identity_verification_required") is True,
        "gate identity checkpoint is missing",
    )
    _require(
        quality_contract.get("evaluator_or_oos_authorized") is False,
        "plan quality contract enables evaluator or OOS",
    )
    _require(
        quality_contract.get("official_identity_verification_authorized_by_this_plan")
        is False,
        "plan quality contract enables identity verification",
    )

    return {
        "run_id": run_id,
        "plan": {
            **_file_ref(plan_path),
            "plan_hash": expected_plan_hash,
        },
        "approval_receipt": _file_ref(receipt_path),
        "launch_record": _file_ref(launch_path),
        "manifest": {
            **_file_ref(manifest_path),
            "final": True,
            "rows": int(manifest["rows"]),
            "errors": 0,
        },
        "output": _file_ref(output_path),
        "technical_quality": {
            **_file_ref(quality_path),
            "decision": EXPECTED_QUALITY_DECISION,
            "accepted": True,
            "ok_rows": int(metrics["ok_rows"]),
            "ok_bases": int(metrics["ok_bases"]),
            "ok_exchanges": int(metrics["ok_exchanges"]),
            "two_exchange_full_coverage_1h4h_bases": int(
                metrics["two_exchange_full_coverage_1h4h_bases"]
            ),
            "duplicate_candles": int(metrics["duplicate_candles"]),
        },
        "gate": _file_ref(gate_path),
        "identity_verification_required": True,
        "identity_verification_authorized": False,
        "evaluator_or_oos_authorized": False,
    }


def _validate_identity_proposal(
    *,
    proposal_path: Path,
    expected_proposal_hash: str,
    expected_file_sha256: str,
    slow: Mapping[str, Any],
) -> dict[str, Any]:
    _require_file_hash(proposal_path, expected_file_sha256, "identity proposal")
    proposal = _load_json(proposal_path, "identity proposal")
    _require(
        proposal.get("schema")
        == "trading_mvp_slow_liquidity_official_identity_proposal_v1",
        "identity proposal schema mismatch",
    )
    _require(
        proposal.get("mode") == "PlanOnlyReviewProposal",
        "identity proposal mode mismatch",
    )
    _require(
        proposal.get("status") == "AWAIT_EXACT_HASH_BOUND_APPROVAL",
        "identity proposal status mismatch",
    )
    _require(
        proposal.get("proposal_hash_method")
        == "sha256_canonical_json_excluding_proposal_hash",
        "identity proposal hash method mismatch",
    )
    _require(
        proposal.get("proposal_hash") == expected_proposal_hash,
        "identity proposal hash mismatch",
    )
    _require(
        canonical_hash_without(proposal, "proposal_hash") == expected_proposal_hash,
        "identity proposal canonical hash mismatch",
    )
    authorization = proposal.get("authorization_now")
    _require(isinstance(authorization, dict), "identity authorization is missing")
    _require(
        authorization.get("exact_user_approval_required") is True,
        "identity proposal does not require exact approval",
    )
    _require(
        authorization.get("actual_network_run_allowed") is False,
        "identity proposal illegally enables network run",
    )
    _require_false(
        authorization,
        (
            "offline_runtime_implementation_allowed",
            "synthetic_runtime_tests_allowed",
            "official_source_content_read_allowed",
            "identity_claim_allowed",
            "candidate_planonly_creation_allowed",
            "evaluator_or_oos_allowed",
            "returns_or_pnl_allowed",
            "grid_or_retune_allowed",
            "execution_probe_allowed",
            "paper_or_live_allowed",
            "private_api_keys_allowed",
            "real_capital_allowed",
            "leverage_or_margin_allowed",
        ),
        "identity proposal",
    )
    checkpoint = proposal.get("next_checkpoint")
    _require(isinstance(checkpoint, dict), "identity checkpoint is missing")
    _require(
        checkpoint.get("required_action")
        == "REQUEST_EXACT_HASH_BOUND_IDENTITY_APPROVAL",
        "identity checkpoint changed",
    )

    bindings = proposal.get("source_bindings")
    _require(isinstance(bindings, dict), "identity source bindings are missing")
    expected_bindings = {
        "recollect_plan": (
            slow["plan"],
            "path",
            "file_sha256",
        ),
        "approval_receipt": (
            slow["approval_receipt"],
            "path",
            "file_sha256",
        ),
        "completed_launch": (
            slow["launch_record"],
            "path",
            "file_sha256",
        ),
        "collection_manifest": (
            slow["manifest"],
            "path",
            "file_sha256",
        ),
        "technical_quality": (
            slow["technical_quality"],
            "path",
            "file_sha256",
        ),
    }
    for name, (expected, path_key, hash_key) in expected_bindings.items():
        binding = bindings.get(name)
        _require(isinstance(binding, dict), f"identity {name} binding is missing")
        _require_exact_path(binding.get(path_key), _resolve(expected["path"]), name)
        _require(
            str(binding.get(hash_key) or "").lower()
            == str(expected["file_sha256"]).lower(),
            f"identity {name} hash binding mismatch",
        )
    technical_binding = bindings["technical_quality"]
    _require(
        technical_binding.get("decision") == EXPECTED_QUALITY_DECISION,
        "identity quality decision binding mismatch",
    )
    _require(
        technical_binding.get("accepted") is True,
        "identity quality acceptance binding mismatch",
    )
    _require(
        bindings["recollect_plan"].get("plan_hash")
        == slow["plan"]["plan_hash"],
        "identity slow plan hash binding mismatch",
    )

    return {
        **_file_ref(proposal_path),
        "proposal_hash": expected_proposal_hash,
        "status": proposal["status"],
        "phase_1_approved": False,
        "network_execution_authorized": False,
        "identity_output_authorized": False,
        "next_required_action": checkpoint["required_action"],
    }


def _validate_pit_shadow_track(
    *,
    pointer_path: Path,
    extension_path: Path,
    expected_plan_hash: str,
    expected_file_sha256: str,
) -> dict[str, Any]:
    pointer = _load_json(pointer_path, "PIT pointer")
    _require(pointer.get("status") == "ACTIVE", "PIT pointer is not ACTIVE")
    _require(pointer.get("project") == "trading_mvp", "PIT pointer project mismatch")
    _require(
        pointer.get("hypothesis_id") == EXPECTED_PIT_HYPOTHESIS,
        "PIT pointer hypothesis mismatch",
    )
    _require(
        pointer.get("data_type") == EXPECTED_PIT_DATA_TYPE,
        "PIT pointer data type mismatch",
    )
    _require(
        pointer.get("collection_stage") == EXPECTED_PIT_STAGE,
        "PIT pointer stage mismatch",
    )
    _require(
        pointer.get("plan_hash") != expected_plan_hash,
        "PIT extension is already active without audited approval binding",
    )
    ledger_path = _resolve(str(pointer.get("quality_ledger_path") or ""))
    _require(ledger_path.is_file(), "PIT quality ledger is missing")
    ledger = _load_jsonl(ledger_path, "PIT quality ledger")
    accepted_rows = [
        row
        for row in ledger
        if row.get("technical_quality_accepted") is True
        and row.get("track_key")
        == f"{EXPECTED_PIT_HYPOTHESIS}|{EXPECTED_PIT_DATA_TYPE}"
    ]
    accepted_dates = {str(row.get("scheduled_date") or "") for row in accepted_rows}
    _require("" not in accepted_dates, "PIT accepted date is missing")
    _require(len(accepted_dates) == 10, "PIT accepted date count mismatch")
    contract_hashes = {
        str(row.get("hypothesis_contract_sha256") or "") for row in accepted_rows
    }
    _require(len(contract_hashes) == 1, "PIT ledger contract hash mismatch")
    contract_hash = next(iter(contract_hashes))
    _require_hash(contract_hash, "PIT contract")

    _require_file_hash(extension_path, expected_file_sha256, "PIT extension plan")
    plan = _load_json(extension_path, "PIT extension plan")
    _require(
        plan.get("schema") == "fast_first_night_schedule_plan_v2",
        "PIT extension schema mismatch",
    )
    _require(plan.get("mode") == "PlanOnly", "PIT extension mode mismatch")
    _require(plan.get("plan_hash") == expected_plan_hash, "PIT plan hash mismatch")
    sealed = plan.get("sealed_schedule")
    _require(isinstance(sealed, dict), "PIT sealed schedule is missing")
    _require(
        canonical_hash_without(sealed, "never-present") == expected_plan_hash,
        "PIT sealed schedule hash mismatch",
    )
    _require(
        plan.get("sealed_schedule_hash") == expected_plan_hash,
        "PIT sealed schedule binding mismatch",
    )
    _require_false(
        plan,
        (
            "schedule_approved",
            "collection_started",
            "network_access",
            "oos_returns_read",
            "pnl_or_returns_read",
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ),
        "PIT extension",
    )
    _require(
        plan.get("explicit_approval_required") is True,
        "PIT extension does not require approval",
    )
    _require(
        plan.get("next_allowed_action") == "await_explicit_night_schedule_approval",
        "PIT extension next action changed",
    )
    _require(
        sealed.get("hypothesis_id") == EXPECTED_PIT_HYPOTHESIS,
        "PIT extension hypothesis mismatch",
    )
    _require(
        sealed.get("data_type") == EXPECTED_PIT_DATA_TYPE,
        "PIT extension data type mismatch",
    )
    _require(
        sealed.get("hypothesis_contract_sha256") == contract_hash,
        "PIT extension contract hash mismatch",
    )
    stage = sealed.get("collection_stage")
    _require(isinstance(stage, dict), "PIT extension stage is missing")
    _require(stage.get("name") == EXPECTED_PIT_STAGE, "PIT extension stage mismatch")
    _require(
        stage.get("initial_accepted_distinct_dates") == 10,
        "PIT extension initial date count mismatch",
    )
    _require(
        stage.get("stage_target_distinct_dates") == 20,
        "PIT extension target date count mismatch",
    )
    _require(
        stage.get("maximum_new_accepted_dates") == 10,
        "PIT extension maximum date count mismatch",
    )
    ledger_binding = stage.get("quality_ledger")
    _require(isinstance(ledger_binding, dict), "PIT ledger binding is missing")
    _require_exact_path(ledger_binding.get("path"), ledger_path, "PIT ledger")
    _require_file_hash(
        ledger_path,
        ledger_binding.get("file_sha256_at_plan"),
        "PIT ledger",
    )
    initial = ledger_binding.get("initial_accepted_certifications")
    _require(isinstance(initial, list), "PIT initial certifications are missing")
    initial_ids = {str(row.get("certification_id") or "") for row in initial}
    ledger_ids = {str(row.get("certification_id") or "") for row in accepted_rows}
    _require(initial_ids == ledger_ids, "PIT initial certification binding mismatch")
    segments = sealed.get("segments")
    _require(isinstance(segments, list), "PIT extension segments are missing")
    _require(len(segments) == 10, "PIT extension segment count mismatch")
    for index, segment in enumerate(segments, start=1):
        _require(isinstance(segment, dict), f"PIT segment {index} is invalid")
        _require(segment.get("sequence") == index, "PIT segment sequence mismatch")
        _require(segment.get("duration_sec") == 1200, "PIT segment duration changed")

    return {
        "active_pointer": {
            **_file_ref(pointer_path),
            "plan_hash": str(pointer["plan_hash"]),
            "status": "ACTIVE",
            "has_pending_segment": False,
        },
        "quality_ledger": {
            **_file_ref(ledger_path),
            "accepted_distinct_dates": len(accepted_dates),
            "hypothesis_contract_sha256": contract_hash,
        },
        "accepted_distinct_dates": len(accepted_dates),
        "train_target_distinct_dates": 20,
        "extension_plan": {
            **_file_ref(extension_path),
            "plan_hash": expected_plan_hash,
            "mode": "PlanOnly",
            "schedule_approved": False,
        },
        "extension_segments": len(segments),
        "extension_first_start_local": segments[0].get("start_local"),
        "extension_last_end_local": segments[-1].get("end_local"),
        "extension_approval_required": True,
        "extension_activation_authorized": False,
        "collector_launch_authorized": False,
    }


def _validate_dense_proposal(
    *,
    proposal_path: Path,
    expected_proposal_hash: str,
    expected_file_sha256: str,
) -> dict[str, Any]:
    _require_file_hash(proposal_path, expected_file_sha256, "Dense proposal")
    proposal = _load_json(proposal_path, "Dense proposal")
    _require(
        proposal.get("schema")
        == "trading_mvp_dense_ws_three_hour_segmented_refreeze_proposal_v1",
        "Dense proposal schema mismatch",
    )
    _require(proposal.get("mode") == "PlanOnly", "Dense proposal mode mismatch")
    _require(
        proposal.get("status") == "AWAIT_EXACT_SEGMENTED_REFREEZE_APPROVAL",
        "Dense proposal status mismatch",
    )
    _require(
        proposal.get("proposal_hash_method")
        == "sha256_canonical_json_excluding_proposal_hash",
        "Dense proposal hash method mismatch",
    )
    _require(
        proposal.get("proposal_hash") == expected_proposal_hash,
        "Dense proposal hash mismatch",
    )
    _require(
        canonical_hash_without(proposal, "proposal_hash") == expected_proposal_hash,
        "Dense proposal canonical hash mismatch",
    )
    authorization = proposal.get("authorization_boundary")
    _require(isinstance(authorization, dict), "Dense authorization is missing")
    _require(
        authorization.get("proposal_preparation_authorized") is True,
        "Dense proposal preparation binding mismatch",
    )
    _require_false(
        authorization,
        (
            "implementation_authorized",
            "contract_refreeze_authorized",
            "runtime_manifest_creation_authorized",
            "collector_launch_authorized",
            "network_access",
            "market_data_read",
            "returns_or_pnl_read",
            "oos_read",
            "grid_or_retune",
            "paper_or_live",
            "private_api_keys",
            "real_capital",
            "leverage_or_margin",
            "stopped_incomplete_retry_authorized",
        ),
        "Dense proposal",
    )
    checkpoint = proposal.get("approval_checkpoint")
    _require(isinstance(checkpoint, dict), "Dense approval checkpoint is missing")
    _require(
        checkpoint.get("phase_1_does_not_authorize_collection") is True,
        "Dense phase 1 collection boundary changed",
    )
    _require(
        proposal.get("next_allowed_action")
        == "request_exact_proposal_bound_segmented_refreeze_implementation_approval",
        "Dense proposal next action changed",
    )
    return {
        **_file_ref(proposal_path),
        "proposal_hash": expected_proposal_hash,
        "status": proposal["status"],
        "phase_1_approved": False,
        "implementation_authorized": False,
        "collector_launch_authorized": False,
    }


def build_readiness(
    *,
    gate_path: str | Path,
    writer_claim_path: str | Path,
    slow_plan_path: str | Path,
    expected_slow_plan_hash: str,
    expected_slow_plan_file_sha256: str,
    identity_proposal_path: str | Path,
    expected_identity_proposal_hash: str,
    expected_identity_proposal_file_sha256: str,
    pit_pointer_path: str | Path,
    pit_extension_plan_path: str | Path,
    expected_pit_extension_plan_hash: str,
    expected_pit_extension_plan_file_sha256: str,
    dense_proposal_path: str | Path,
    expected_dense_proposal_hash: str,
    expected_dense_proposal_file_sha256: str,
    identity_runtime_manifest_path: str | Path | None = None,
    identity_execution_manifest_path: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    gate = _resolve(gate_path)
    writer_claim = _resolve(writer_claim_path)
    _require(not writer_claim.exists(), "global market-data writer claim is present")
    primary_basis = _validate_primary_frozen_basis_terminal()
    slow = _validate_slow_liquidity(
        gate_path=gate,
        plan_path=_resolve(slow_plan_path),
        expected_plan_hash=_require_hash(
            expected_slow_plan_hash,
            "slow plan hash",
        ),
        expected_plan_file_sha256=expected_slow_plan_file_sha256,
    )
    identity = _validate_identity_proposal(
        proposal_path=_resolve(identity_proposal_path),
        expected_proposal_hash=_require_hash(
            expected_identity_proposal_hash,
            "identity proposal hash",
        ),
        expected_file_sha256=expected_identity_proposal_file_sha256,
        slow=slow,
    )
    identity_runtime: dict[str, Any] | None = None
    identity_execution: dict[str, Any] | None = None
    if identity_execution_manifest_path is not None:
        _require(
            identity_runtime_manifest_path is not None,
            "identity execution manifest requires the exact runtime manifest",
        )
    if identity_runtime_manifest_path is not None:
        identity_runtime = _validate_identity_runtime_manifest(
            _resolve(identity_runtime_manifest_path),
            identity=identity,
        )
        identity = {
            **identity,
            "status": IDENTITY_PHASE1_STATUS,
            "phase_1_approved": True,
            "offline_implementation_completed": True,
            "network_execution_authorized": False,
            "identity_output_authorized": False,
            "runtime_manifest": identity_runtime,
        }
    if identity_execution_manifest_path is not None:
        _require(identity_runtime is not None, "identity runtime state is missing")
        identity_execution = _validate_identity_execution_manifest(
            _resolve(identity_execution_manifest_path),
            runtime_state=identity_runtime,
        )
    pit = _validate_pit_shadow_track(
        pointer_path=_resolve(pit_pointer_path),
        extension_path=_resolve(pit_extension_plan_path),
        expected_plan_hash=_require_hash(
            expected_pit_extension_plan_hash,
            "PIT extension plan hash",
        ),
        expected_file_sha256=expected_pit_extension_plan_file_sha256,
    )
    dense = _validate_dense_proposal(
        proposal_path=_resolve(dense_proposal_path),
        expected_proposal_hash=_require_hash(
            expected_dense_proposal_hash,
            "Dense proposal hash",
        ),
        expected_file_sha256=expected_dense_proposal_file_sha256,
    )

    observed_at = generated_at_utc or datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadinessError("generated_at_utc is invalid") from exc
    _require(parsed.tzinfo is not None, "generated_at_utc must be timezone-aware")

    readiness_status = CURRENT_READINESS_STATUS
    next_safe_action = "await_one_exact_approval_checkpoint"
    identity_checkpoint: dict[str, Any] = {
        "id": "slow_liquidity_identity_offline_phase_1",
        "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
        "proposal_hash": identity["proposal_hash"],
        "proposal_file_sha256": identity["file_sha256"],
    }
    if identity_runtime is not None:
        readiness_status = IDENTITY_PHASE1_READINESS_STATUS
        next_safe_action = "await_exact_code_bound_identity_execution_approval"
        identity_checkpoint = {
            "id": IDENTITY_PHASE2_CHECKPOINT_ID,
            "status": "AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL",
            "runtime_manifest_file_sha256": identity_runtime["file_sha256"],
            "runtime_manifest_hash": identity_runtime["manifest_hash"],
        }
    if identity_execution is not None:
        readiness_status = IDENTITY_PHASE2_READINESS_STATUS
        next_safe_action = "run_exact_approved_slow_liquidity_official_identity_visible"
        identity_checkpoint = {
            "id": IDENTITY_PHASE2_CHECKPOINT_ID,
            "status": "APPROVED_SINGLE_USE",
            "runtime_manifest_file_sha256": identity_execution[
                "runtime_manifest_file_sha256"
            ],
            "runtime_manifest_hash": identity_execution["runtime_manifest_hash"],
            "execution_approval_receipt_file_sha256": identity_execution[
                "execution_approval_receipt_file_sha256"
            ],
            "execution_approval_receipt_hash": identity_execution[
                "execution_approval_receipt_hash"
            ],
            "request_plan_sha256": identity_execution["request_plan_sha256"],
        }

    report: dict[str, Any] = {
        "schema": READINESS_SCHEMA,
        "status": readiness_status,
        "generated_at_utc": observed_at,
        "project": "trading_mvp",
        "goal": "One-Week Historical Edge Sprint",
        "research_only": True,
        "primary_frozen_basis_terminal": primary_basis,
        "slow_liquidity": slow,
        "official_identity_phase_1": identity,
        **(
            {"official_identity_phase_2": identity_execution}
            if identity_execution is not None
            else {}
        ),
        "pit_shadow_track": pit,
        "dense_three_hour_refreeze_phase_1": dense,
        "permissions": {
            "global_writer_present": False,
            "identity_offline_implementation_authorized": False,
            "identity_verification_authorized": identity_execution is not None,
            "pit_extension_activation_authorized": False,
            "dense_refreeze_implementation_authorized": False,
            "collector_launch_authorized": False,
            "evaluator_or_oos_authorized": False,
            "returns_or_pnl_authorized": False,
            "grid_or_retune_authorized": False,
            "execution_probe_authorized": False,
            "paper_or_live_authorized": False,
            "private_api_or_real_capital_authorized": False,
            "leverage_or_margin_authorized": False,
            "stopped_incomplete_retry_authorized": False,
        },
        "approval_checkpoints": [
            {
                "id": "pit_extension_schedule_activation",
                "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                "plan_hash": pit["extension_plan"]["plan_hash"],
                "plan_file_sha256": pit["extension_plan"]["file_sha256"],
            },
            identity_checkpoint,
            {
                "id": "dense_three_hour_segmented_refreeze_phase_1",
                "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
                "proposal_hash": dense["proposal_hash"],
                "proposal_file_sha256": dense["file_sha256"],
            },
        ],
        "next_safe_action": next_safe_action,
        "readiness_hash_method": READINESS_HASH_METHOD,
    }
    report["readiness_hash"] = canonical_hash_without(report, "readiness_hash")
    return report


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
        if path.exists():
            raise ReadinessError(f"output already exists: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_readiness_bundle(
    report: Mapping[str, Any],
    output_path: str | Path,
    pointer_path: str | Path,
) -> dict[str, Any]:
    output = _resolve(output_path)
    pointer = _resolve(pointer_path)
    expected_readiness_root = (pointer.parent / "readiness").resolve()
    _require(
        output != expected_readiness_root
        and expected_readiness_root in output.parents,
        "readiness output must be inside the pointer's readiness directory",
    )
    _require(
        report.get("schema") == READINESS_SCHEMA,
        "readiness schema mismatch before write",
    )
    readiness_hash = _require_hash(report.get("readiness_hash"), "readiness hash")
    _require(
        canonical_hash_without(report, "readiness_hash") == readiness_hash,
        "readiness canonical hash mismatch before write",
    )
    _write_json_new(output, report)
    output_sha256 = _sha256(output)
    pointer_value = {
        "schema": POINTER_SCHEMA,
        "status": "ACTIVE",
        "project": "trading_mvp",
        "readiness_path": str(output),
        "readiness_file_sha256": output_sha256,
        "readiness_hash": readiness_hash,
        "updated_at_utc": report.get("generated_at_utc"),
    }
    try:
        _write_json_atomic(pointer, pointer_value)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {
        "decision": "CURRENT_READINESS_WRITTEN",
        "readiness_path": str(output),
        "readiness_file_sha256": output_sha256,
        "readiness_hash": readiness_hash,
        "pointer_path": str(pointer),
        "pointer_file_sha256": _sha256(pointer),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a current fail-closed One-Week Edge Sprint readiness audit."
    )
    parser.add_argument("--gate", required=True)
    parser.add_argument("--writer-claim", required=True)
    parser.add_argument("--slow-plan", required=True)
    parser.add_argument("--expected-slow-plan-hash", required=True)
    parser.add_argument("--expected-slow-plan-file-sha256", required=True)
    parser.add_argument("--identity-proposal", required=True)
    parser.add_argument("--expected-identity-proposal-hash", required=True)
    parser.add_argument("--expected-identity-proposal-file-sha256", required=True)
    parser.add_argument("--pit-pointer", required=True)
    parser.add_argument("--pit-extension-plan", required=True)
    parser.add_argument("--expected-pit-extension-plan-hash", required=True)
    parser.add_argument("--expected-pit-extension-plan-file-sha256", required=True)
    parser.add_argument("--dense-proposal", required=True)
    parser.add_argument("--expected-dense-proposal-hash", required=True)
    parser.add_argument("--expected-dense-proposal-file-sha256", required=True)
    parser.add_argument("--identity-runtime-manifest")
    parser.add_argument("--identity-execution-manifest")
    parser.add_argument("--generated-at-utc")
    parser.add_argument("--output", required=True)
    parser.add_argument("--pointer-output", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_readiness(
        gate_path=args.gate,
        writer_claim_path=args.writer_claim,
        slow_plan_path=args.slow_plan,
        expected_slow_plan_hash=args.expected_slow_plan_hash,
        expected_slow_plan_file_sha256=args.expected_slow_plan_file_sha256,
        identity_proposal_path=args.identity_proposal,
        expected_identity_proposal_hash=args.expected_identity_proposal_hash,
        expected_identity_proposal_file_sha256=(
            args.expected_identity_proposal_file_sha256
        ),
        pit_pointer_path=args.pit_pointer,
        pit_extension_plan_path=args.pit_extension_plan,
        expected_pit_extension_plan_hash=args.expected_pit_extension_plan_hash,
        expected_pit_extension_plan_file_sha256=(
            args.expected_pit_extension_plan_file_sha256
        ),
        dense_proposal_path=args.dense_proposal,
        expected_dense_proposal_hash=args.expected_dense_proposal_hash,
        expected_dense_proposal_file_sha256=(
            args.expected_dense_proposal_file_sha256
        ),
        identity_runtime_manifest_path=args.identity_runtime_manifest,
        identity_execution_manifest_path=args.identity_execution_manifest,
        generated_at_utc=args.generated_at_utc,
    )
    if args.preflight_only:
        result = {
            "decision": "READY_TO_WRITE_CURRENT_READINESS",
            "side_effects": "NONE",
            "readiness_hash": report["readiness_hash"],
            "output_path": str(_resolve(args.output)),
            "pointer_output_path": str(_resolve(args.pointer_output)),
        }
    else:
        result = write_readiness_bundle(report, args.output, args.pointer_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReadinessError as exc:
        print(json.dumps({"decision": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        sys.exit(1)
