from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    import dense_ws_campaign_contract as campaign
    import dense_ws_signal_evaluator_freeze as freeze
    from dense_ws_campaign_quality import (
        CAMPAIGN_MANIFEST_SCHEMA,
        QUALITY_SCHEMA,
    )
    from dense_ws_causal_materializer import (
        LABEL_SCHEMA,
        MATERIALIZATION_SCHEMA,
        SNAPSHOT_SCHEMA,
    )
except ImportError:  # pragma: no cover - package execution
    from . import dense_ws_campaign_contract as campaign
    from . import dense_ws_signal_evaluator_freeze as freeze
    from .dense_ws_campaign_quality import (
        CAMPAIGN_MANIFEST_SCHEMA,
        QUALITY_SCHEMA,
    )
    from .dense_ws_causal_materializer import (
        LABEL_SCHEMA,
        MATERIALIZATION_SCHEMA,
        SNAPSHOT_SCHEMA,
    )


PLAN_SCHEMA = "trading_mvp_dense_ws_materialization_bound_planonly_v1"
PLAN_MODE = "NonExecutableMaterializationBoundPlanOnly"
PLAN_STATUS = "MATERIALIZATION_BOUND_NOT_AUTHORIZED"
NEXT_ACTION = "REQUEST_EXACT_HASH_BOUND_EVALUATOR_APPROVAL"
MAX_RUNTIME_SEC = 1_800
FALSE_SAFETY_KEYS = (
    "network_access",
    "returns_read",
    "pnl_computed",
    "oos_read",
    "grid_or_retune",
    "paper_forward",
    "live_orders",
    "private_api_keys",
    "real_capital",
    "leverage_or_margin",
)


class MaterializationBoundPlanIntegrityError(ValueError):
    """An immutable source or a no-evaluation safety boundary changed."""


class MaterializationBoundPlanRuntimeError(TimeoutError):
    """The bounded hash-binding operation exceeded its deadline."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _serialized_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_plan_hash(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return _hash_value(payload)


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = _resolved(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationBoundPlanIntegrityError(
            f"cannot read JSON evidence {target}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise MaterializationBoundPlanIntegrityError(
            f"JSON evidence must be an object: {target}"
        )
    return value


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MaterializationBoundPlanIntegrityError(f"{label} must be an object")
    return value


def _sequence(value: Any, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MaterializationBoundPlanIntegrityError(f"{label} must be an array")
    return value


def _expect(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise MaterializationBoundPlanIntegrityError(
            f"{label} mismatch: expected {expected!r}, got {actual!r}"
        )


def _sha256(value: Any, *, label: str) -> str:
    rendered = str(value or "").lower()
    if len(rendered) != 64 or any(char not in "0123456789abcdef" for char in rendered):
        raise MaterializationBoundPlanIntegrityError(
            f"{label} must be a lowercase SHA-256"
        )
    return rendered


def _inside(path: Path, root: Path, *, label: str) -> None:
    if path != root and root not in path.parents:
        raise MaterializationBoundPlanIntegrityError(
            f"{label} escapes campaign root: {path}"
        )


def _false_safety(value: Any, *, label: str) -> dict[str, bool]:
    safety = _mapping(value, label=label)
    for key in FALSE_SAFETY_KEYS:
        _expect(safety.get(key), False, label=f"{label}.{key}")
    return {key: False for key in FALSE_SAFETY_KEYS}


def _deterministic_result_hash(value: Mapping[str, Any]) -> str:
    payload = {
        key: item
        for key, item in value.items()
        if key != "deterministic_result_hash"
    }
    return _hash_value(payload)


def _deadline_checker(
    *,
    max_runtime_sec: int,
    deadline_monotonic: float | None,
) -> Callable[[], None]:
    if max_runtime_sec < 1 or max_runtime_sec > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    deadline = (
        float(deadline_monotonic)
        if deadline_monotonic is not None
        else time.monotonic() + max_runtime_sec
    )

    def check() -> None:
        if time.monotonic() > deadline:
            raise MaterializationBoundPlanRuntimeError(
                "materialization-bound PlanOnly build exceeded max_runtime_sec"
            )

    check()
    return check


def _hash_file(path: Path, *, deadline_check: Callable[[], None]) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                deadline_check()
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise MaterializationBoundPlanIntegrityError(
            f"cannot hash immutable evidence {path}: {exc}"
        ) from exc
    deadline_check()
    return digest.hexdigest()


def _verified_file_binding(
    value: Any,
    *,
    campaign_root: Path,
    label: str,
    deadline_check: Callable[[], None],
) -> dict[str, Any]:
    binding = _mapping(value, label=label)
    path = _resolved(str(binding.get("path") or ""))
    _inside(path, campaign_root, label=label)
    expected = _sha256(binding.get("sha256"), label=f"{label}.sha256")
    observed = _hash_file(path, deadline_check=deadline_check)
    _expect(observed, expected, label=f"{label}.sha256")
    return {
        "path": str(path),
        "sha256": observed,
        "bytes": path.stat().st_size,
    }


def _verified_json_binding(
    value: Any,
    *,
    campaign_root: Path,
    label: str,
    deadline_check: Callable[[], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = _verified_file_binding(
        value,
        campaign_root=campaign_root,
        label=label,
        deadline_check=deadline_check,
    )
    return binding, _read_json(binding["path"])


def _verified_jsonl_output(
    value: Any,
    *,
    campaign_root: Path,
    expected_schema: str,
    label: str,
    deadline_check: Callable[[], None],
) -> dict[str, Any]:
    source = _mapping(value, label=label)
    binding = _verified_file_binding(
        source,
        campaign_root=campaign_root,
        label=label,
        deadline_check=deadline_check,
    )
    expected_rows = int(source.get("rows") or 0)
    if expected_rows < 1:
        raise MaterializationBoundPlanIntegrityError(f"{label}.rows must be positive")
    observed_rows = 0
    first_schema: str | None = None
    try:
        with Path(binding["path"]).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                deadline_check()
                if not line.strip():
                    continue
                observed_rows += 1
                if first_schema is None:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise MaterializationBoundPlanIntegrityError(
                            f"{label} first row is invalid JSON at line {line_number}"
                        ) from exc
                    if not isinstance(row, Mapping):
                        raise MaterializationBoundPlanIntegrityError(
                            f"{label} first row must be an object"
                        )
                    first_schema = str(row.get("schema") or "")
    except OSError as exc:
        raise MaterializationBoundPlanIntegrityError(
            f"cannot scan {label}: {exc}"
        ) from exc
    _expect(observed_rows, expected_rows, label=f"{label}.rows")
    _expect(first_schema, expected_schema, label=f"{label}.schema")
    return {**binding, "rows": observed_rows, "schema": expected_schema}


def _validate_quality(
    quality: Mapping[str, Any],
    *,
    campaign_plan: Mapping[str, Any],
    campaign_contract: Mapping[str, Any],
) -> None:
    _expect(quality.get("schema"), QUALITY_SCHEMA, label="quality.schema")
    _expect(
        quality.get("campaign_id"),
        campaign_plan.get("campaign_id"),
        label="quality.campaign_id",
    )
    _expect(
        quality.get("plan_hash"),
        campaign_plan.get("plan_hash"),
        label="quality.plan_hash",
    )
    _expect(
        quality.get("contract_hash"),
        campaign_contract.get("contract_hash"),
        label="quality.contract_hash",
    )
    candidate_hash = _mapping(
        campaign_plan.get("contract"), label="campaign_plan.contract"
    ).get("candidate_contract_hash")
    _expect(
        quality.get("candidate_contract_hash"),
        candidate_hash,
        label="quality.candidate_contract_hash",
    )
    _expect(quality.get("accepted"), True, label="quality.accepted")
    _expect(
        quality.get("decision"),
        "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
        label="quality.decision",
    )
    _expect(
        quality.get("deterministic_result_hash"),
        _deterministic_result_hash(quality),
        label="quality.deterministic_result_hash",
    )
    _false_safety(quality.get("safety"), label="quality.safety")


def _validate_materialization(
    materialization: Mapping[str, Any],
    *,
    campaign_plan: Mapping[str, Any],
    campaign_contract: Mapping[str, Any],
    quality_path: Path,
    quality_sha256: str,
    quality_result_hash: str,
) -> None:
    _expect(
        materialization.get("schema"),
        MATERIALIZATION_SCHEMA,
        label="materialization.schema",
    )
    _expect(
        materialization.get("campaign_id"),
        campaign_plan.get("campaign_id"),
        label="materialization.campaign_id",
    )
    _expect(
        materialization.get("plan_hash"),
        campaign_plan.get("plan_hash"),
        label="materialization.plan_hash",
    )
    _expect(
        materialization.get("contract_hash"),
        campaign_contract.get("contract_hash"),
        label="materialization.contract_hash",
    )
    candidate_hash = _mapping(
        campaign_plan.get("contract"), label="campaign_plan.contract"
    ).get("candidate_contract_hash")
    _expect(
        materialization.get("candidate_contract_hash"),
        candidate_hash,
        label="materialization.candidate_contract_hash",
    )
    _expect(materialization.get("accepted"), True, label="materialization.accepted")
    _expect(
        materialization.get("decision"),
        "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW",
        label="materialization.decision",
    )
    _expect(
        materialization.get("deterministic_result_hash"),
        _deterministic_result_hash(materialization),
        label="materialization.deterministic_result_hash",
    )
    quality = _mapping(
        materialization.get("quality_report"),
        label="materialization.quality_report",
    )
    _expect(
        _resolved(str(quality.get("path") or "")),
        quality_path,
        label="materialization.quality_report.path",
    )
    _expect(
        quality.get("sha256"),
        quality_sha256,
        label="materialization.quality_report.sha256",
    )
    _expect(
        quality.get("deterministic_result_hash"),
        quality_result_hash,
        label="materialization.quality_report.deterministic_result_hash",
    )
    _false_safety(materialization.get("safety"), label="materialization.safety")


def _raw_segment_chain(
    quality: Mapping[str, Any],
    *,
    campaign_root: Path,
    deadline_check: Callable[[], None],
) -> dict[str, Any]:
    valid = [
        item
        for item in _sequence(quality.get("segments"), label="quality.segments")
        if isinstance(item, Mapping) and item.get("valid") is True
    ]
    if not valid:
        raise MaterializationBoundPlanIntegrityError("quality has no valid segments")
    valid.sort(
        key=lambda item: (
            str(item.get("phase_id") or ""),
            int(item.get("segment_index") or 0),
            str(item.get("segment_dir") or ""),
        )
    )
    seen_segments: set[tuple[str, int, str]] = set()
    seen_files: set[str] = set()
    entries: list[dict[str, Any]] = []
    previous_hash = "0" * 64
    total_bytes = 0
    for index, segment in enumerate(valid, start=1):
        deadline_check()
        identity = (
            str(segment.get("phase_id") or ""),
            int(segment.get("segment_index") or 0),
            str(segment.get("segment_dir") or ""),
        )
        if identity in seen_segments:
            raise MaterializationBoundPlanIntegrityError(
                f"duplicate valid segment identity: {identity!r}"
            )
        seen_segments.add(identity)
        manifest, _ = _verified_json_binding(
            segment.get("manifest"),
            campaign_root=campaign_root,
            label=f"quality.segments[{index}].manifest",
            deadline_check=deadline_check,
        )
        files: list[dict[str, Any]] = []
        source_files = [
            item
            for item in _sequence(
                segment.get("raw_files"),
                label=f"quality.segments[{index}].raw_files",
            )
            if isinstance(item, Mapping)
        ]
        if not source_files:
            raise MaterializationBoundPlanIntegrityError(
                f"quality.segments[{index}] has no raw files"
            )
        for file_index, source in enumerate(
            sorted(source_files, key=lambda item: str(item.get("path") or "")),
            start=1,
        ):
            binding = _verified_file_binding(
                source,
                campaign_root=campaign_root,
                label=f"quality.segments[{index}].raw_files[{file_index}]",
                deadline_check=deadline_check,
            )
            if binding["path"] in seen_files:
                raise MaterializationBoundPlanIntegrityError(
                    f"raw file is bound more than once: {binding['path']}"
                )
            seen_files.add(binding["path"])
            total_bytes += int(binding["bytes"])
            files.append(binding)
        core = {
            "ordinal": index,
            "phase_id": identity[0],
            "run_id": str(segment.get("run_id") or ""),
            "segment_index": identity[1],
            "segment_dir": identity[2],
            "manifest": manifest,
            "raw_files": files,
            "previous_entry_hash": previous_hash,
        }
        entry_hash = _hash_value(core)
        entries.append({**core, "entry_hash": entry_hash})
        previous_hash = entry_hash
    return {
        "status": "BOUND_AND_REHASHED",
        "valid_segments": len(entries),
        "raw_files": len(seen_files),
        "total_bytes": total_bytes,
        "entries": entries,
        "chain_hash": _hash_value(entries),
        "full_data_hash_revalidation_required_before_evaluator": False,
    }


def build_materialization_bound_plan(
    *,
    frozen_contract: Mapping[str, Any],
    frozen_contract_path: str | Path,
    frozen_plan: Mapping[str, Any],
    frozen_plan_path: str | Path,
    campaign_contract: Mapping[str, Any],
    campaign_contract_path: str | Path,
    campaign_plan: Mapping[str, Any],
    campaign_plan_path: str | Path,
    quality: Mapping[str, Any],
    quality_path: str | Path,
    materialization: Mapping[str, Any],
    materialization_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    _deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    deadline_check = _deadline_checker(
        max_runtime_sec=max_runtime_sec,
        deadline_monotonic=_deadline_monotonic,
    )
    frozen_contract_target = _resolved(frozen_contract_path)
    frozen_plan_target = _resolved(frozen_plan_path)
    campaign_contract_target = _resolved(campaign_contract_path)
    campaign_plan_target = _resolved(campaign_plan_path)
    quality_target = _resolved(quality_path)
    materialization_target = _resolved(materialization_path)

    freeze.validate_frozen_plan(frozen_plan, contract=frozen_contract)
    campaign.validate_contract(campaign_contract, verify_files=False)
    campaign.validate_plan(
        campaign_plan,
        contract=campaign_contract,
        verify_files=False,
    )
    _validate_quality(
        quality,
        campaign_plan=campaign_plan,
        campaign_contract=campaign_contract,
    )
    quality_sha = _hash_file(quality_target, deadline_check=deadline_check)
    materialization_sha = _hash_file(
        materialization_target,
        deadline_check=deadline_check,
    )
    _validate_materialization(
        materialization,
        campaign_plan=campaign_plan,
        campaign_contract=campaign_contract,
        quality_path=quality_target,
        quality_sha256=quality_sha,
        quality_result_hash=str(quality["deterministic_result_hash"]),
    )

    identity = _mapping(frozen_contract.get("identity"), label="frozen.identity")
    _expect(
        identity.get("campaign_id"),
        campaign_plan.get("campaign_id"),
        label="frozen.identity.campaign_id",
    )
    source_campaign = _mapping(
        frozen_contract.get("source_campaign"), label="frozen.source_campaign"
    )
    _expect(
        source_campaign.get("plan_hash"),
        campaign_plan.get("plan_hash"),
        label="frozen.source_campaign.plan_hash",
    )
    _expect(
        source_campaign.get("contract_hash"),
        campaign_contract.get("contract_hash"),
        label="frozen.source_campaign.contract_hash",
    )
    authorization = _mapping(
        frozen_contract.get("authorization"), label="frozen.authorization"
    )
    _expect(
        authorization.get("evaluation_authorized"),
        False,
        label="frozen.authorization.evaluation_authorized",
    )

    campaign_root = _resolved(
        str(
            _mapping(campaign_plan.get("outputs"), label="campaign_plan.outputs").get(
                "campaign_root"
            )
            or ""
        )
    )
    quality_inputs = _mapping(quality.get("inputs"), label="quality.inputs")
    campaign_manifest, manifest = _verified_json_binding(
        quality_inputs.get("campaign_manifest"),
        campaign_root=campaign_root,
        label="quality.inputs.campaign_manifest",
        deadline_check=deadline_check,
    )
    _expect(
        manifest.get("schema"),
        CAMPAIGN_MANIFEST_SCHEMA,
        label="campaign_manifest.schema",
    )
    _expect(manifest.get("completed"), True, label="campaign_manifest.completed")
    _expect(manifest.get("final"), True, label="campaign_manifest.final")
    _expect(
        manifest.get("campaign_id"),
        campaign_plan.get("campaign_id"),
        label="campaign_manifest.campaign_id",
    )
    _expect(
        manifest.get("plan_hash"),
        campaign_plan.get("plan_hash"),
        label="campaign_manifest.plan_hash",
    )

    phase_manifests: list[dict[str, Any]] = []
    for index, source in enumerate(
        _sequence(
            quality_inputs.get("phase_manifests"),
            label="quality.inputs.phase_manifests",
        ),
        start=1,
    ):
        binding = _mapping(source, label=f"quality.inputs.phase_manifests[{index}]")
        verified, _ = _verified_json_binding(
            binding,
            campaign_root=campaign_root,
            label=f"quality.inputs.phase_manifests[{index}]",
            deadline_check=deadline_check,
        )
        phase_manifests.append(
            {
                "phase_id": str(binding.get("phase_id") or ""),
                **verified,
            }
        )
    if not phase_manifests:
        raise MaterializationBoundPlanIntegrityError(
            "quality.inputs.phase_manifests is empty"
        )

    raw_chain = _raw_segment_chain(
        quality,
        campaign_root=campaign_root,
        deadline_check=deadline_check,
    )
    _expect(
        materialization.get("valid_segments"),
        raw_chain["valid_segments"],
        label="materialization.valid_segments",
    )
    labels = _verified_jsonl_output(
        materialization.get("labels"),
        campaign_root=campaign_root,
        expected_schema=LABEL_SCHEMA,
        label="materialization.labels",
        deadline_check=deadline_check,
    )
    snapshots = _verified_jsonl_output(
        materialization.get("execution_snapshots"),
        campaign_root=campaign_root,
        expected_schema=SNAPSHOT_SCHEMA,
        label="materialization.execution_snapshots",
        deadline_check=deadline_check,
    )

    frozen_contract_sha = _hash_file(
        frozen_contract_target,
        deadline_check=deadline_check,
    )
    frozen_plan_sha = _hash_file(frozen_plan_target, deadline_check=deadline_check)
    campaign_contract_sha = _hash_file(
        campaign_contract_target,
        deadline_check=deadline_check,
    )
    campaign_plan_sha = _hash_file(
        campaign_plan_target,
        deadline_check=deadline_check,
    )
    deadline_check()

    required_bindings = set(
        _sequence(
            _mapping(
                frozen_contract.get("materialization_binding_contract"),
                label="frozen.materialization_binding_contract",
            ).get("required_future_bindings"),
            label="frozen.required_future_bindings",
        )
    )
    bindings = {
        "campaign_manifest_sha256": campaign_manifest["sha256"],
        "campaign_quality_report_sha256": quality_sha,
        "causal_materialization_manifest_sha256": materialization_sha,
        "causal_materialization_deterministic_result_hash": materialization[
            "deterministic_result_hash"
        ],
        "regime_labels_sha256": labels["sha256"],
        "execution_snapshots_sha256": snapshots["sha256"],
        "raw_bbo_segment_chain_and_file_hashes": raw_chain["chain_hash"],
    }
    missing = sorted(required_bindings - set(bindings))
    if missing:
        raise MaterializationBoundPlanIntegrityError(
            f"frozen future bindings are not satisfied: {missing}"
        )

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": PLAN_MODE,
        "status": PLAN_STATUS,
        "research_only": True,
        "executable": False,
        "identity": copy.deepcopy(dict(identity)),
        "frozen_signal_evaluator_contract": {
            "path": str(frozen_contract_target),
            "file_sha256": frozen_contract_sha,
            "contract_hash": frozen_contract["contract_hash"],
        },
        "frozen_signal_evaluator_plan": {
            "path": str(frozen_plan_target),
            "file_sha256": frozen_plan_sha,
            "plan_hash": frozen_plan["plan_hash"],
        },
        "campaign": {
            "root": str(campaign_root),
            "contract": {
                "path": str(campaign_contract_target),
                "file_sha256": campaign_contract_sha,
                "contract_hash": campaign_contract["contract_hash"],
            },
            "plan": {
                "path": str(campaign_plan_target),
                "file_sha256": campaign_plan_sha,
                "plan_hash": campaign_plan["plan_hash"],
            },
            "manifest": campaign_manifest,
            "phase_manifests": phase_manifests,
        },
        "quality": {
            "path": str(quality_target),
            "file_sha256": quality_sha,
            "deterministic_result_hash": quality["deterministic_result_hash"],
            "decision": quality["decision"],
        },
        "materialization": {
            "manifest": {
                "path": str(materialization_target),
                "file_sha256": materialization_sha,
                "deterministic_result_hash": materialization[
                    "deterministic_result_hash"
                ],
                "decision": materialization["decision"],
            },
            "labels": labels,
            "execution_snapshots": snapshots,
            "raw_bbo": raw_chain,
            "required_future_bindings": bindings,
        },
        "evaluation_contract_hashes": {
            "signal_contract": _hash_value(frozen_contract["signal_contract"]),
            "execution_realization_contract": _hash_value(
                frozen_contract["execution_realization_contract"]
            ),
            "evaluation_design_contract": _hash_value(
                frozen_contract["evaluation_design_contract"]
            ),
            "acceptance_contract": _hash_value(
                frozen_contract["acceptance_contract"]
            ),
            "decision_contract": _hash_value(frozen_contract["decision_contract"]),
        },
        "runtime_contract": {
            "future_evaluator_max_runtime_sec": MAX_RUNTIME_SEC,
            "visible_run_required": True,
            "deterministic_repeats": frozen_contract["acceptance_contract"][
                "robustness"
            ]["deterministic_repeats"],
            "grid_search": False,
            "retune": False,
        },
        "allowed_actions": [
            "validate_this_non_executable_planonly",
            "prepare_exact_hash_bound_evaluator_approval_packet",
        ],
        "forbidden_actions_without_new_exact_approval": [
            "run_evaluator",
            "read_returns_or_pnl",
            "read_oos",
            "grid_or_retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
            "real_capital",
            "leverage_or_margin",
        ],
        "authorization": {
            "contract_freeze_authorized": True,
            "planonly_build_authorized": True,
            "materialization_output_bound": True,
            "evaluation_authorized": False,
            "returns_pnl_oos_allowed": False,
            "paper_forward_authorized": False,
            "live_or_private_api_authorized": False,
            "exact_evaluator_approval_required": True,
        },
        "safety": {key: False for key in FALSE_SAFETY_KEYS},
        "next_allowed_action": NEXT_ACTION,
    }
    plan["plan_hash"] = canonical_plan_hash(plan)
    validate_materialization_bound_plan(plan)
    return plan


def validate_materialization_bound_plan(plan: Mapping[str, Any]) -> None:
    _expect(plan.get("schema"), PLAN_SCHEMA, label="plan.schema")
    _expect(plan.get("mode"), PLAN_MODE, label="plan.mode")
    _expect(plan.get("status"), PLAN_STATUS, label="plan.status")
    _expect(plan.get("research_only"), True, label="plan.research_only")
    _expect(plan.get("executable"), False, label="plan.executable")
    observed_hash = _sha256(plan.get("plan_hash"), label="plan.plan_hash")
    _expect(canonical_plan_hash(plan), observed_hash, label="plan canonical hash")
    authorization = _mapping(plan.get("authorization"), label="plan.authorization")
    for key in (
        "evaluation_authorized",
        "returns_pnl_oos_allowed",
        "paper_forward_authorized",
        "live_or_private_api_authorized",
    ):
        _expect(authorization.get(key), False, label=f"plan.authorization.{key}")
    _expect(
        authorization.get("materialization_output_bound"),
        True,
        label="plan.authorization.materialization_output_bound",
    )
    _expect(
        authorization.get("exact_evaluator_approval_required"),
        True,
        label="plan.authorization.exact_evaluator_approval_required",
    )
    _false_safety(plan.get("safety"), label="plan.safety")
    runtime = _mapping(plan.get("runtime_contract"), label="plan.runtime_contract")
    _expect(
        runtime.get("future_evaluator_max_runtime_sec"),
        MAX_RUNTIME_SEC,
        label="plan.runtime_contract.future_evaluator_max_runtime_sec",
    )
    _expect(runtime.get("visible_run_required"), True, label="visible_run_required")
    _expect(runtime.get("grid_search"), False, label="runtime.grid_search")
    _expect(runtime.get("retune"), False, label="runtime.retune")
    raw = _mapping(
        _mapping(plan.get("materialization"), label="plan.materialization").get(
            "raw_bbo"
        ),
        label="plan.materialization.raw_bbo",
    )
    entries = list(_sequence(raw.get("entries"), label="raw_bbo.entries"))
    previous_hash = "0" * 64
    for index, raw_entry in enumerate(entries, start=1):
        entry = dict(_mapping(raw_entry, label=f"raw_bbo.entries[{index}]"))
        entry_hash = _sha256(
            entry.pop("entry_hash", None),
            label=f"raw_bbo.entries[{index}].entry_hash",
        )
        _expect(
            entry.get("previous_entry_hash"),
            previous_hash,
            label=f"raw_bbo.entries[{index}].previous_entry_hash",
        )
        _expect(_hash_value(entry), entry_hash, label=f"raw_bbo.entries[{index}]")
        previous_hash = entry_hash
    _expect(raw.get("chain_hash"), _hash_value(entries), label="raw_bbo.chain_hash")
    _expect(plan.get("next_allowed_action"), NEXT_ACTION, label="next_allowed_action")


def _write_immutable_json(
    path: str | Path,
    value: Mapping[str, Any],
    *,
    deadline_check: Callable[[], None],
) -> Path:
    target = _resolved(path)
    if target.exists():
        raise FileExistsError(f"immutable output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary output already exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_serialized_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        deadline_check()
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def build_materialization_bound_plan_file(
    *,
    proposal_path: str | Path,
    freeze_approval_receipt_path: str | Path,
    frozen_contract_path: str | Path,
    frozen_plan_path: str | Path,
    campaign_contract_path: str | Path,
    campaign_plan_path: str | Path,
    quality_path: str | Path,
    materialization_path: str | Path,
    output_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    _deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    deadline_monotonic = (
        float(_deadline_monotonic)
        if _deadline_monotonic is not None
        else time.monotonic() + max_runtime_sec
    )
    deadline_check = _deadline_checker(
        max_runtime_sec=max_runtime_sec,
        deadline_monotonic=deadline_monotonic,
    )
    output_target = _resolved(output_path)
    if output_target.exists():
        raise FileExistsError(f"immutable output already exists: {output_target}")
    freeze.validate_frozen_files(
        proposal_path=proposal_path,
        approval_receipt_path=freeze_approval_receipt_path,
        contract_path=frozen_contract_path,
        plan_path=frozen_plan_path,
    )
    deadline_check()
    frozen_contract = _read_json(frozen_contract_path)
    frozen_plan = _read_json(frozen_plan_path)
    campaign_contract = _read_json(campaign_contract_path)
    campaign_plan = _read_json(campaign_plan_path)
    quality = _read_json(quality_path)
    materialization = _read_json(materialization_path)
    campaign_contract_ref = _mapping(
        campaign_plan.get("contract"), label="campaign_plan.contract"
    )
    _expect(
        _resolved(str(campaign_contract_ref.get("path") or "")),
        _resolved(campaign_contract_path),
        label="campaign_plan.contract.path",
    )
    _expect(
        campaign_contract_ref.get("file_sha256"),
        _hash_file(
            _resolved(campaign_contract_path),
            deadline_check=deadline_check,
        ),
        label="campaign_plan.contract.file_sha256",
    )
    plan = build_materialization_bound_plan(
        frozen_contract=frozen_contract,
        frozen_contract_path=frozen_contract_path,
        frozen_plan=frozen_plan,
        frozen_plan_path=frozen_plan_path,
        campaign_contract=campaign_contract,
        campaign_contract_path=campaign_contract_path,
        campaign_plan=campaign_plan,
        campaign_plan_path=campaign_plan_path,
        quality=quality,
        quality_path=quality_path,
        materialization=materialization,
        materialization_path=materialization_path,
        max_runtime_sec=max_runtime_sec,
        _deadline_monotonic=deadline_monotonic,
    )
    output_sha256 = hashlib.sha256(
        _serialized_json(plan).encode("utf-8")
    ).hexdigest()
    target = _write_immutable_json(
        output_target,
        plan,
        deadline_check=deadline_check,
    )
    return {
        "status": "MATERIALIZATION_BOUND_PLANONLY_CREATED_NOT_AUTHORIZED",
        "path": str(target),
        "file_sha256": output_sha256,
        "plan_hash": plan["plan_hash"],
        "evaluation_authorized": False,
        "returns_pnl_oos_read": False,
        "next_allowed_action": NEXT_ACTION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bind accepted dense WS campaign/materialization hashes into a new "
            "non-executable PlanOnly. This command cannot run the evaluator."
        )
    )
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--freeze-approval-receipt", required=True)
    parser.add_argument("--frozen-contract", required=True)
    parser.add_argument("--frozen-plan", required=True)
    parser.add_argument("--campaign-contract", required=True)
    parser.add_argument("--campaign-plan", required=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--materialization", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--max-runtime-sec",
        type=int,
        default=MAX_RUNTIME_SEC,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = build_materialization_bound_plan_file(
        proposal_path=args.proposal,
        freeze_approval_receipt_path=args.freeze_approval_receipt,
        frozen_contract_path=args.frozen_contract,
        frozen_plan_path=args.frozen_plan,
        campaign_contract_path=args.campaign_contract,
        campaign_plan_path=args.campaign_plan,
        quality_path=args.quality,
        materialization_path=args.materialization,
        output_path=args.output,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
