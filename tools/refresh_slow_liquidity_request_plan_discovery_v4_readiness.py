from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trading_mvp.src import one_week_edge_sprint_readiness as readiness
from trading_mvp.src import slow_liquidity_official_identity_verification as identity_runtime
from trading_mvp.src import slow_liquidity_identity_request_plan_discovery_v4 as runtime


DEFAULT_SOURCE = (
    REPO_ROOT
    / "docs/agent-log/readiness/one-week-edge-sprint-current-readiness-20260816-v18.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs/agent-log/readiness/one-week-edge-sprint-current-readiness-20260816-v21.json"
)
DEFAULT_POINTER = (
    REPO_ROOT / "docs/agent-log/one-week-edge-sprint-readiness-pointer.json"
)
GATE_PATH = REPO_ROOT / "docs/agent-log/active-run-gate.json"
WRITER_CLAIM_PATH = (
    REPO_ROOT / "docs/agent-log/active-market-data-writer-claim.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path_value: str | Path, **extra: Any) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(path),
        "file_sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }
    result.update(extra)
    return result


def _hash_ref(source: dict[str, Any], key: str) -> tuple[Path, str, str]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"missing source reference: {key}")
    path = Path(str(value.get("path") or "")).expanduser().resolve()
    return path, str(value.get("proposal_hash") or value.get("plan_hash") or ""), str(
        value.get("file_sha256") or ""
    )


def _build_report(source_path: Path, generated_at_utc: str) -> dict[str, Any]:
    source = _read_json(source_path)
    slow = source["slow_liquidity"]
    identity = source["official_identity_phase_1"]
    pit = source["pit_shadow_track"]
    dense = source["dense_three_hour_refreeze_phase_1"]

    identity_path, identity_hash, identity_sha = _hash_ref(source, "official_identity_phase_1")
    dense_path, dense_hash, dense_sha = _hash_ref(source, "dense_three_hour_refreeze_phase_1")
    slow_plan = slow["plan"]
    pit_pointer = pit["active_pointer"]
    pit_extension = pit["extension_plan"]

    gate_path = Path(str(slow["gate"]["path"])).expanduser().resolve()
    slow_state = readiness._validate_slow_liquidity(
        gate_path=gate_path,
        plan_path=Path(str(slow_plan["path"])).expanduser().resolve(),
        expected_plan_hash=str(slow_plan["plan_hash"]),
        expected_plan_file_sha256=str(slow_plan["file_sha256"]),
    )
    identity_state = readiness._validate_identity_proposal(
        proposal_path=identity_path,
        expected_proposal_hash=identity_hash,
        expected_file_sha256=identity_sha,
        slow=slow_state,
    )
    identity_runtime_path = Path(
        str(identity["runtime_manifest"]["path"])
    ).expanduser().resolve()
    identity_runtime_manifest = _read_json(identity_runtime_path)
    identity_runtime.validate_runtime_manifest(identity_runtime_manifest)
    identity_state = {
        **identity_state,
        "phase_1_approved": True,
        "offline_implementation_completed": True,
        "network_execution_authorized": False,
        "identity_output_authorized": False,
        "runtime_manifest": copy.deepcopy(identity["runtime_manifest"]),
    }
    pit_state = readiness._validate_pit_shadow_track(
        pointer_path=Path(str(pit_pointer["path"])).expanduser().resolve(),
        extension_path=Path(str(pit_extension["path"])).expanduser().resolve(),
        expected_plan_hash=str(pit_extension["plan_hash"]),
        expected_file_sha256=str(pit_extension["file_sha256"]),
    )
    dense_state = readiness._validate_dense_proposal(
        proposal_path=dense_path,
        expected_proposal_hash=dense_hash,
        expected_file_sha256=dense_sha,
    )
    primary_state = readiness._validate_primary_frozen_basis_terminal()
    base = copy.deepcopy(source)
    base["schema"] = readiness.READINESS_SCHEMA
    base["generated_at_utc"] = generated_at_utc
    base["project"] = "trading_mvp"
    base["goal"] = "One-Week Historical Edge Sprint"
    base["research_only"] = True
    base["primary_frozen_basis_terminal"] = primary_state
    base["slow_liquidity"] = slow_state
    base["official_identity_phase_1"] = identity_state
    base["pit_shadow_track"] = pit_state
    base["dense_three_hour_refreeze_phase_1"] = dense_state
    base["permissions"] = {
        field: False for field in readiness.CURRENT_PERMISSION_FIELDS
    }

    runtime_raw = runtime.RUNTIME_MANIFEST_PATH.read_bytes()
    runtime_manifest = json.loads(runtime_raw.decode("utf-8"))
    runtime.validate_runtime_manifest(runtime_manifest)
    if runtime.EXECUTION_MANIFEST_PATH.exists():
        raise ValueError("v4 execution manifest exists; refusing readiness refresh")
    if runtime.APPROVAL_RECEIPT_PATH.exists():
        raise ValueError("v4 approval receipt exists; refusing readiness refresh")
    if runtime.OUTPUT_PATH.exists():
        raise ValueError("v4 output exists; refusing readiness refresh")

    terminal_attempt: dict[str, Any] | None = None
    terminal_attempt_sha: str | None = None
    if runtime.LAUNCH_RECORD_PATH.exists():
        terminal_attempt = _read_json(runtime.LAUNCH_RECORD_PATH)
        terminal_attempt_sha = _sha256(runtime.LAUNCH_RECORD_PATH)
        if not (
            terminal_attempt.get("run_id") == runtime.RUN_ID
            and terminal_attempt.get("status") == "STOPPED_INCOMPLETE"
            and terminal_attempt.get("terminal_ownership_verified") is True
            and terminal_attempt.get("retry_authorized") is False
            and terminal_attempt.get("network_accessed") is True
            and terminal_attempt.get("network_accessed_proven") is True
            and terminal_attempt.get("request_plan_output_created") is False
            and str(terminal_attempt.get("failure_reason_code") or "")
        ):
            raise ValueError("v4 launch record is not an immutable terminal rejection")
        terminal_runtime_path = Path(
            str(terminal_attempt.get("runtime_manifest_path") or "")
        ).expanduser().resolve()
        if not terminal_runtime_path.is_file() or terminal_attempt.get(
            "runtime_manifest_file_sha256"
        ) != _sha256(terminal_runtime_path):
            raise ValueError("v4 terminal launch runtime binding is invalid")

    discovery = {
        "status": runtime.RUNTIME_MANIFEST_STATUS,
        "run_id": runtime.RUN_ID,
        "runtime_manifest": {
            **_ref(runtime.RUNTIME_MANIFEST_PATH),
            "manifest_hash": runtime_manifest["manifest_hash"],
        },
        "visible_launcher": _ref(runtime.VISIBLE_LAUNCHER_PATH),
        "lineage": runtime_manifest["lineage"],
        "limits": runtime_manifest["limits"],
        "output_path": str(runtime.OUTPUT_PATH),
        "execution_manifest_path": str(runtime.EXECUTION_MANIFEST_PATH),
        "execution_approval_receipt_path": str(runtime.APPROVAL_RECEIPT_PATH),
        "launch_record_path": str(runtime.LAUNCH_RECORD_PATH),
        "required_future_guard_decision": (
            "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4"
        ),
        "execution_authorized": False,
        "network_authorized": False,
        "official_source_content_read_authorized": False,
        "request_plan_output_authorized": False,
        "global_writer_claim_authorized": False,
        "visible_launcher_execution_authorized": False,
        "standing_same_scope_public_research_allowed": True,
        "identity_output_authorized": False,
        "collector_or_evaluator_authorized": False,
        "evaluator_or_oos_authorized": False,
        "returns_or_pnl_authorized": False,
        "grid_or_retune_authorized": False,
        "execution_probe_authorized": False,
        "paper_or_live_authorized": False,
        "private_api_or_real_capital_authorized": False,
        "leverage_or_margin_authorized": False,
        "future_execution_single_use_required": True,
        "stopped_incomplete_retry_authorized": False,
        "execution_manifest_present": False,
        "execution_approval_receipt_present": False,
        "launch_record_present": terminal_attempt is not None,
        "writer_claim_present": False,
        "output_present": False,
        "separate_exact_code_bound_network_execution_approval_required": False,
        "terminal_attempt": (
            {
                "path": str(runtime.LAUNCH_RECORD_PATH),
                "file_sha256": terminal_attempt_sha,
                "status": terminal_attempt.get("status"),
                "failure_reason_code": terminal_attempt.get("failure_reason_code"),
                "network_accessed": terminal_attempt.get("network_accessed"),
                "network_accessed_proven": terminal_attempt.get(
                    "network_accessed_proven"
                ),
                "retry_authorized": terminal_attempt.get("retry_authorized"),
            }
            if terminal_attempt is not None
            else None
        ),
    }

    base.pop("official_identity_request_plan_discovery", None)
    base.pop("official_identity_phase_2", None)
    base["status"] = readiness.REQUEST_PLAN_V4_REFREEZE_READINESS_STATUS
    base["next_safe_action"] = (
        "do_not_retry_without_new_exact_approval"
        if terminal_attempt is not None
        else "run_slow_liquidity_identity_request_plan_discovery_v4_visible"
    )
    base["official_identity_request_plan_discovery_v4"] = discovery
    base["approval_checkpoints"] = [
        base["approval_checkpoints"][0],
        {
            "id": "slow_liquidity_identity_request_plan_discovery_v4_execution",
            "status": "STANDING_SAME_SCOPE_PUBLIC_RESEARCH_ALLOWED",
            "runtime_manifest_file_sha256": discovery["runtime_manifest"][
                "file_sha256"
            ],
            "runtime_manifest_hash": runtime_manifest["manifest_hash"],
            "visible_launcher_file_sha256": discovery["visible_launcher"][
                "file_sha256"
            ],
            "required_guard_decision": (
                "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4"
            ),
        },
        base["approval_checkpoints"][2],
    ]
    base["readiness_hash"] = readiness.canonical_hash_without(
        base, "readiness_hash"
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pointer-output", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--generated-at-utc")
    args = parser.parse_args()

    generated_at = args.generated_at_utc or datetime.now(timezone.utc).isoformat()
    report = _build_report(args.source.resolve(), generated_at)
    result = readiness.write_readiness_bundle(
        report,
        args.output.resolve(),
        args.pointer_output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
