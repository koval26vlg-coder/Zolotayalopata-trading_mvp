from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from autopilot_research_backlog import next_task as next_research_task
from codex_weekly_usage import collect_weekly_usage, evaluate_usage_guard
from continuous_production import resolve_run_window
import dense_ws_materialization_bound_plan as dense_ws_bound_plan
from one_week_edge_sprint_readiness import (
    CurrentSprintReadinessError,
    resolve_current_sprint_readiness,
)


LIMIT_PAUSE_DECISIONS = {
    "PAUSE_WEEKLY_LIMIT",
    "PAUSE_USAGE_TELEMETRY_STALE",
    "PAUSE_USAGE_TELEMETRY_UNAVAILABLE",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


STANDING_RESEARCH_REQUIRED_ACTIONS = {
    "technical_quality",
    "public_identity_discovery",
    "public_request_plan_discovery",
    "public_topology_discovery",
    "synthetic_tests",
    "immutable_manifest_refreeze",
    "preflight_only",
}
STANDING_RESEARCH_REQUIRED_GUARDS = {
    "fresh_authoritative_guard",
    "active_run_gate_must_be_ready_for_postprocess",
    "single_global_market_data_writer",
    "visible_terminal_for_network_writers",
    "exact_hash_and_schema_binding",
    "public_read_only_only",
    "no_redirects_proxies_or_retries",
    "no_private_api_or_real_capital",
}
STANDING_RESEARCH_REQUIRED_CHECKPOINTS = {
    "hypothesis_change",
    "venue_change",
    "universe_change",
    "signal_cost_risk_or_acceptance_contract_change",
    "stopped_incomplete_resume",
    "integrity_conflict",
    "evaluator_oos_returns_pnl_grid_retune",
    "paper_live_private_api_real_capital_leverage_margin_or_withdrawal",
}


def _standing_research_scope_matches(
    policy: dict[str, Any],
    *,
    current_readiness: dict[str, Any],
    required_action: str,
) -> bool:
    authorization = policy.get("standing_research_authorization")
    if not isinstance(authorization, dict):
        return False
    if (
        authorization.get("schema")
        != "trading_mvp_standing_same_scope_public_research_authorization_v1"
        or authorization.get("enabled") is not True
        or authorization.get("same_scope_auto_continue") is not True
    ):
        return False
    if current_readiness.get("status") != "READY":
        return False

    authorized_actions = {
        str(value) for value in authorization.get("authorized_actions") or []
    }
    if required_action not in authorized_actions:
        return False
    if not STANDING_RESEARCH_REQUIRED_ACTIONS.issubset(authorized_actions):
        return False
    if not STANDING_RESEARCH_REQUIRED_GUARDS.issubset(
        {str(value) for value in authorization.get("technical_guards") or []}
    ):
        return False
    if not STANDING_RESEARCH_REQUIRED_CHECKPOINTS.issubset(
        {
            str(value)
            for value in authorization.get("user_checkpoint_required_for") or []
        }
    ):
        return False

    binding = policy.get("slow_liquidity_history_recollect")
    scope = authorization.get("scope_binding")
    if not isinstance(binding, dict) or not isinstance(scope, dict):
        return False
    plan_path_value = str(binding.get("plan_path") or "").strip()
    expected_file_sha = str(binding.get("plan_file_sha256") or "").lower()
    expected_plan_hash = str(binding.get("plan_hash") or "").lower()
    if not plan_path_value or len(expected_file_sha) != 64 or len(expected_plan_hash) != 64:
        return False

    plan_path = Path(plan_path_value).expanduser().resolve()
    if not plan_path.is_file() or _sha256(plan_path) != expected_file_sha:
        return False
    try:
        plan = _load_json(plan_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if str(plan.get("plan_hash") or "").lower() != expected_plan_hash:
        return False
    execution = plan.get("execution")
    universe = plan.get("universe")
    if not isinstance(execution, dict) or not isinstance(universe, dict):
        return False

    if str(scope.get("strategy_branch") or "") != str(
        plan.get("strategy_branch") or ""
    ):
        return False
    if list(scope.get("exchanges") or []) != list(execution.get("exchanges") or []):
        return False
    if list(scope.get("bases") or []) != list(universe.get("bases") or []):
        return False
    if list(scope.get("timeframes") or []) != list(execution.get("timeframes") or []):
        return False
    try:
        if int(scope.get("history_days")) != int(execution.get("history_days")):
            return False
    except (TypeError, ValueError):
        return False
    return True


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object: {path}:{line_number}")
        rows.append(value)
    return rows


def resolve_productive_fallback(
    policy: dict[str, Any],
    *,
    ledger_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    queue = policy.get("productive_fallback_queue")
    if not isinstance(queue, dict):
        return {"status": "NOT_CONFIGURED", "task": None}
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("productive_fallback_queue.tasks must be a list")

    entries = ledger_entries or []
    task_events: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        task_id = str(entry.get("task_id") or "")
        if task_id:
            task_events.setdefault(task_id, []).append(entry)

    in_progress: list[str] = []
    for raw_task in tasks:
        if not isinstance(raw_task, dict):
            raise ValueError("productive fallback task must be an object")
        task_id = str(raw_task.get("id") or "").strip()
        runner = str(raw_task.get("runner") or "").strip()
        if not task_id or not runner:
            raise ValueError("productive fallback task id and runner are required")
        max_runtime_sec = int(raw_task.get("max_runtime_sec") or 0)
        if max_runtime_sec <= 0 or max_runtime_sec > 1_800:
            raise ValueError(
                f"productive fallback task {task_id} max_runtime_sec must be in [1, 1800]"
            )
        max_attempts = int(raw_task.get("max_attempts") or 1)
        if max_attempts <= 0 or max_attempts > 2:
            raise ValueError(
                f"productive fallback task {task_id} max_attempts must be in [1, 2]"
            )

        events = task_events.get(task_id, [])
        statuses = [str(event.get("status") or "") for event in events]
        if "COMPLETED" in statuses:
            continue
        attempts = sum(status == "STARTED" for status in statuses)
        if statuses and statuses[-1] == "STARTED":
            in_progress.append(task_id)
            continue
        if attempts >= max_attempts:
            continue
        return {
            "status": "READY",
            "task": dict(raw_task),
            "attempts": attempts,
            "remaining_task_count": sum(
                1
                for candidate in tasks
                if isinstance(candidate, dict)
                and str(candidate.get("id") or "") not in {
                    task_id_value
                    for task_id_value, values in task_events.items()
                    if any(str(value.get("status") or "") == "COMPLETED" for value in values)
                }
            ),
        }

    if in_progress:
        return {
            "status": "IN_PROGRESS",
            "task": None,
            "in_progress_task_ids": in_progress,
        }
    return {"status": "EXHAUSTED", "task": None}


def resolve_research_critical_checkpoint(
    backlog_path: str | Path,
    research_fallback: dict[str, Any],
) -> dict[str, Any]:
    if str(research_fallback.get("status") or "") != "EXHAUSTED":
        return research_fallback

    target = Path(backlog_path).expanduser().resolve()
    backlog = _load_json(target)
    tasks = backlog.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("research backlog tasks must be a list")

    latest_completed = next(
        (
            task
            for task in reversed(tasks)
            if isinstance(task, dict)
            and str(task.get("status") or "") == "COMPLETED"
        ),
        None,
    )
    if latest_completed is None:
        return research_fallback

    artifact_value = (
        latest_completed.get("artifact_path")
        or latest_completed.get("output_path")
    )
    expected_file_hash = str(
        latest_completed.get("artifact_sha256") or ""
    ).lower()
    if not artifact_value or len(expected_file_hash) != 64:
        raise ValueError(
            "latest completed research task lacks immutable artifact metadata"
        )

    artifact_path = Path(str(artifact_value)).expanduser().resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(
            f"latest completed research artifact is missing: {artifact_path}"
        )
    actual_file_hash = _sha256(artifact_path)
    if actual_file_hash != expected_file_hash:
        raise ValueError(
            "latest completed research artifact hash mismatch: "
            f"expected={expected_file_hash} actual={actual_file_hash}"
        )

    artifact = _load_json(artifact_path)
    expected_result_hash = str(
        artifact.get("deterministic_result_hash") or ""
    ).lower()
    deterministic = {
        key: value
        for key, value in artifact.items()
        if key not in {"deterministic_result_hash", "generated_at_utc"}
    }
    actual_result_hash = _sha256_json(deterministic)
    if (
        len(expected_result_hash) != 64
        or actual_result_hash != expected_result_hash
    ):
        raise ValueError(
            "research artifact deterministic hash mismatch"
        )

    checkpoint = artifact.get("critical_checkpoint")
    if isinstance(checkpoint, dict) and str(
        checkpoint.get("status") or ""
    ) == "USER_REVIEW_REQUIRED":
        requested_action = str(
            checkpoint.get("requested_action") or ""
        ).strip()
        if not requested_action:
            raise ValueError(
                "critical research checkpoint requested_action is missing"
            )
        return {
            "status": "USER_REVIEW_REQUIRED",
            "task": None,
            "critical_checkpoint": dict(checkpoint),
            "audit_path": str(artifact_path),
            "audit_sha256": actual_file_hash,
            "deterministic_result_hash": actual_result_hash,
            "backlog_path": str(target),
        }

    offline_gap = artifact.get("offline_gap_assessment")
    no_catalog = artifact.get("next_bounded_catalog_requirement") == []
    if (
        artifact.get("next_allowed_action")
        == "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
        and no_catalog
        and isinstance(offline_gap, dict)
        and offline_gap.get(
            "materially_useful_same_contract_tasks_remaining"
        )
        is False
    ):
        return {
            "status": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
            "task": None,
            "audit_path": str(artifact_path),
            "audit_sha256": actual_file_hash,
            "deterministic_result_hash": actual_result_hash,
            "backlog_path": str(target),
        }

    return research_fallback


def _pid_alive(pid: Any) -> bool:
    """Return True if *pid* refers to a running process."""
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            value,
        )
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def check_global_active_writer_claim(
    gate_path: str | Path,
) -> dict[str, Any]:
    """Atomic cross-launcher active-writer CAS check.

    Reads the authoritative ``active-run-gate.json`` and determines whether
    any market-data writer is currently active.  The result is a structured
    dict that callers can use to decide whether a new writer may safely start.

    Parameters
    ----------
    gate_path:
        Path to ``docs/agent-log/active-run-gate.json`` (or equivalent).

    Returns
    -------
    dict with keys:
        ``cas_implemented``  - always ``True`` (function exists = CAS is implemented)
        ``claim_clear``      - ``True`` when no active writer was detected
        ``gate_status``      - raw ``status`` field from the gate file
        ``active_run_id``    - ``run_id`` from the gate file (or ``None``)
        ``active_pids``      - list of live PIDs found in the gate
        ``gate_path``        - resolved path that was checked
        ``checked_at_utc``   - ISO-8601 UTC timestamp of the check
    """
    target = Path(gate_path).expanduser().resolve()
    if not target.is_file():
        return {
            "cas_implemented": True,
            "claim_clear": True,
            "gate_status": "NO_GATE_FILE",
            "active_run_id": None,
            "active_pids": [],
            "gate_path": str(target),
            "checked_at_utc": _iso_now(),
        }

    gate = _load_json(target)
    gate_status_value = str(gate.get("status") or "").strip()
    run_id = gate.get("run_id") or None
    final_flag = bool(gate.get("final"))

    # Collect PIDs that the gate reports as active.
    raw_pids: list[Any] = []
    for key in ("process_ids", "collector_pid", "monitor_pid", "stale_monitor_pid"):
        value = gate.get(key)
        if isinstance(value, list):
            raw_pids.extend(value)
        elif value is not None:
            raw_pids.append(value)

    live_pids = [int(p) for p in raw_pids if _pid_alive(p)]

    # The claim is clear when:
    #  - gate status is NOT "RUNNING", AND
    #  - no live PIDs are associated with the gate.
    is_running = gate_status_value == "RUNNING"
    claim_clear = (not is_running) and len(live_pids) == 0

    return {
        "cas_implemented": True,
        "claim_clear": claim_clear,
        "gate_status": gate_status_value or "UNKNOWN",
        "active_run_id": run_id,
        "final": final_flag,
        "active_pids": live_pids,
        "gate_path": str(target),
        "checked_at_utc": _iso_now(),
    }


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def resolve_long_campaign_approval(
    policy: dict[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    candidate = policy.get("next_long_campaign")
    if not isinstance(candidate, dict):
        return {"status": "NOT_CONFIGURED", "launch_window_status": "NOT_CONFIGURED"}
    approval = candidate.get("user_launch_approval")
    approval_status = (
        str(approval.get("status") or "") if isinstance(approval, dict) else ""
    )
    if approval_status != "APPROVED":
        start_value = candidate.get("start_local")
        hard_deadline_value = candidate.get("hard_deadline_local")
        if not start_value or not hard_deadline_value:
            return {
                "status": "NOT_APPROVED",
                "launch_window_status": "NOT_APPROVED",
            }

        writer_start = _parse_timestamp(
            start_value,
            label="long candidate start_local",
        )
        earliest = (
            _parse_timestamp(
                candidate.get("earliest_launch_local"),
                label="long candidate earliest_launch_local",
            )
            if candidate.get("earliest_launch_local")
            else writer_start - timedelta(seconds=1_800)
        )
        latest = (
            _parse_timestamp(
                candidate.get("latest_launch_local"),
                label="long candidate latest_launch_local",
            )
            if candidate.get("latest_launch_local")
            else writer_start + timedelta(seconds=300)
        )
        hard_deadline = _parse_timestamp(
            hard_deadline_value,
            label="long candidate hard_deadline_local",
        )
        if not earliest <= writer_start <= latest < hard_deadline:
            raise ValueError("unapproved long campaign launch window is invalid")
        if (writer_start - earliest).total_seconds() > 1_800:
            raise ValueError("unapproved long campaign countdown lead exceeds 1800 seconds")
        if (latest - writer_start).total_seconds() > 300:
            raise ValueError("unapproved long campaign launch grace exceeds 300 seconds")

        observed = _parse_timestamp(observed_at_utc, label="observed_at_utc")
        if observed < earliest:
            launch_window_status = "WAITING"
        elif observed <= latest:
            launch_window_status = "DUE"
        else:
            launch_window_status = "EXPIRED"
        return {
            "status": "NOT_APPROVED",
            "launch_window_status": launch_window_status,
            "campaign_id": str(candidate.get("campaign_id") or ""),
            "plan_path": str(candidate.get("plan_path") or ""),
            "plan_file_sha256": str(candidate.get("plan_file_sha256") or ""),
            "plan_hash": str(candidate.get("plan_hash") or ""),
            "earliest_launch_local": earliest.isoformat(),
            "writer_start_local": writer_start.isoformat(),
            "latest_launch_local": latest.isoformat(),
            "hard_deadline_local": hard_deadline.isoformat(),
            "single_use": True,
            "stop_incomplete_recovery_authorized": False,
        }

    receipt_path = Path(str(approval.get("receipt_path") or "")).expanduser().resolve()
    expected_receipt_sha = str(approval.get("receipt_sha256") or "").lower()
    if not receipt_path.is_file() or len(expected_receipt_sha) != 64:
        raise ValueError("approved long campaign receipt is missing or unbound")
    actual_receipt_sha = _sha256(receipt_path)
    if actual_receipt_sha != expected_receipt_sha:
        raise ValueError("approved long campaign receipt hash mismatch")
    receipt = _load_json(receipt_path)

    plan_path = Path(str(candidate.get("plan_path") or "")).expanduser().resolve()
    expected_plan_sha = str(candidate.get("plan_file_sha256") or "").lower()
    if not plan_path.is_file() or len(expected_plan_sha) != 64:
        raise ValueError("approved long campaign plan is missing or unbound")
    actual_plan_sha = _sha256(plan_path)
    if actual_plan_sha != expected_plan_sha:
        raise ValueError("approved long campaign plan file hash mismatch")

    exact_bindings = {
        "schema": "trading_mvp_long_campaign_approval_v1",
        "status": "APPROVED",
        "campaign_id": str(candidate.get("campaign_id") or ""),
        "plan_path": str(plan_path),
        "plan_file_sha256": expected_plan_sha,
        "plan_hash": str(candidate.get("plan_hash") or ""),
        "writer_start_local": str(candidate.get("start_local") or ""),
        "hard_deadline_local": str(candidate.get("hard_deadline_local") or ""),
        "single_use": True,
        "stop_incomplete_recovery_authorized": False,
    }
    for key, expected in exact_bindings.items():
        if receipt.get(key) != expected:
            raise ValueError(
                f"approved long campaign receipt {key} mismatch: "
                f"expected {expected!r}, got {receipt.get(key)!r}"
            )

    earliest = _parse_timestamp(
        receipt.get("earliest_launch_local"),
        label="long approval earliest_launch_local",
    )
    writer_start = _parse_timestamp(
        receipt.get("writer_start_local"),
        label="long approval writer_start_local",
    )
    latest = _parse_timestamp(
        receipt.get("latest_launch_local"),
        label="long approval latest_launch_local",
    )
    hard_deadline = _parse_timestamp(
        receipt.get("hard_deadline_local"),
        label="long approval hard_deadline_local",
    )
    if not earliest <= writer_start <= latest < hard_deadline:
        raise ValueError("approved long campaign launch window is invalid")
    if (writer_start - earliest).total_seconds() > 1_800:
        raise ValueError("approved long campaign countdown lead exceeds 1800 seconds")
    if (latest - writer_start).total_seconds() > 300:
        raise ValueError("approved long campaign launch grace exceeds 300 seconds")

    observed = _parse_timestamp(observed_at_utc, label="observed_at_utc")
    if observed < earliest:
        launch_window_status = "WAITING"
    elif observed <= latest:
        launch_window_status = "DUE"
    else:
        launch_window_status = "EXPIRED"
    return {
        "status": "APPROVED",
        "launch_window_status": launch_window_status,
        "campaign_id": exact_bindings["campaign_id"],
        "plan_path": str(plan_path),
        "plan_file_sha256": expected_plan_sha,
        "plan_hash": exact_bindings["plan_hash"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": actual_receipt_sha,
        "approved_at_utc": receipt.get("approved_at_utc"),
        "earliest_launch_local": earliest.isoformat(),
        "writer_start_local": writer_start.isoformat(),
        "latest_launch_local": latest.isoformat(),
        "hard_deadline_local": hard_deadline.isoformat(),
        "single_use": True,
        "stop_incomplete_recovery_authorized": False,
    }


def _dense_ws_postrun_base(
    *,
    status: str,
    campaign_id: str | None = None,
    plan_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "trading_mvp_dense_ws_postrun_disposition_v1",
        "status": status,
        "campaign_id": campaign_id,
        "plan_hash": plan_hash,
        "market_rows_read": False,
        "returns_read": False,
        "pnl_read": False,
        "oos_run": False,
        "grid_or_retune": False,
    }


def _resolve_dense_ws_output_path(
    campaign_root: Path,
    output_names: dict[str, Any],
    key: str,
) -> Path:
    name = str(output_names.get(key) or "").strip()
    if not name or Path(name).name != name:
        raise ValueError(f"dense_ws_postrun.output_names.{key} must be a file name")
    target = (campaign_root / "_postrun" / name).resolve()
    if campaign_root not in target.parents:
        raise ValueError(f"dense WS postrun output escapes campaign root: {target}")
    return target


def _load_sha256_bound_json(
    binding: dict[str, Any],
    *,
    label: str,
    path_key: str = "path",
    sha_key: str = "file_sha256",
) -> tuple[Path, dict[str, Any]]:
    path = Path(str(binding.get(path_key) or "")).expanduser().resolve()
    expected_sha = str(binding.get(sha_key) or "").lower()
    if not path.is_file() or len(expected_sha) != 64:
        raise ValueError(f"{label} is missing or not SHA-256 bound")
    if _sha256(path) != expected_sha:
        raise ValueError(f"{label} file hash mismatch")
    return path, _load_json(path)


def _validate_dense_ws_deferred_handoff_freeze(
    handoff: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    handoff_status = handoff.get("status")
    if (
        handoff_status
        not in {
            "FROZEN_IMPLEMENTATION_ONLY_AWAITING_EXECUTION_APPROVAL",
            "FROZEN_WITH_EXACT_MANIFEST_BOUND_EXECUTION_APPROVAL",
        }
        or handoff.get("implementation_authorized") is not True
        or handoff.get("future_execution_requires_exact_manifest_bound_approval")
        is not True
        or handoff.get("stopped_incomplete_retry_authorized") is not False
    ):
        raise ValueError("dense WS deferred handoff freeze safety state mismatch")

    execution_approval = handoff.get("execution_approval")
    if (
        not isinstance(execution_approval, dict)
        or (
            handoff_status
            == "FROZEN_IMPLEMENTATION_ONLY_AWAITING_EXECUTION_APPROVAL"
            and (
                handoff.get("postrun_execution_authorized") is not False
                or execution_approval.get("status") != "NOT_APPROVED"
            )
        )
        or (
            handoff_status
            == "FROZEN_WITH_EXACT_MANIFEST_BOUND_EXECUTION_APPROVAL"
            and (
                handoff.get("postrun_execution_authorized") is not True
                or execution_approval.get("status") != "APPROVED"
            )
        )
    ):
        raise ValueError("dense WS deferred handoff execution state mismatch")

    proposal_binding = handoff.get("proposal")
    approval_binding = handoff.get("approval_receipt")
    manifest_binding = handoff.get("canonical_manifest")
    if not all(
        isinstance(value, dict)
        for value in (proposal_binding, approval_binding, manifest_binding)
    ):
        raise ValueError("dense WS deferred handoff freeze bindings are missing")

    _, proposal = _load_sha256_bound_json(
        proposal_binding,
        label="dense WS deferred handoff proposal",
    )
    approval_path, approval = _load_sha256_bound_json(
        approval_binding,
        label="dense WS deferred handoff approval receipt",
    )
    manifest_path, manifest = _load_sha256_bound_json(
        manifest_binding,
        label="dense WS deferred handoff canonical manifest",
    )

    proposal_hash = str(proposal_binding.get("proposal_hash") or "")
    profile_hash = str(handoff.get("handoff_profile_hash") or "")
    if (
        len(proposal_hash) != 64
        or proposal.get("proposal_hash") != proposal_hash
        or proposal.get("handoff_profile_hash") != profile_hash
        or approval.get("schema")
        != "trading_mvp_dense_ws_deferred_postrun_handoff_freeze_approval_v1"
        or approval.get("status") != "APPROVED_IMPLEMENTATION_FREEZE_ONLY"
        or approval.get("proposal_hash") != proposal_hash
        or approval.get("handoff_profile_hash") != profile_hash
        or approval.get("implementation_or_policy_rebind_authorized") is not True
        or approval.get("postrun_execution_authorized") is not False
        or approval.get("future_postrun_execution_requires_separate_exact_manifest_bound_approval")
        is not True
        or approval.get("stopped_incomplete_retry_authorized") is not False
    ):
        raise ValueError("dense WS deferred handoff approval semantic mismatch")

    campaign_id = str(candidate.get("campaign_id") or "")
    plan_hash = str(candidate.get("plan_hash") or "")
    if (
        manifest.get("schema")
        != "trading_mvp_dense_ws_deferred_postrun_handoff_manifest_v1"
        or manifest.get("mode") != "IMMUTABLE_PLANONLY_RUNTIME_BINDING"
        or manifest.get("campaign", {}).get("campaign_id") != campaign_id
        or manifest.get("campaign", {}).get("plan_hash") != plan_hash
        or manifest.get("proposal", {}).get("proposal_hash") != proposal_hash
        or manifest.get("handoff_profile_hash") != profile_hash
        or Path(
            str(manifest.get("approval_receipt", {}).get("path") or "")
        ).expanduser().resolve()
        != approval_path
        or manifest.get("approval_receipt", {}).get("file_sha256")
        != str(approval_binding.get("file_sha256") or "")
        or manifest.get("authorization", {}).get("postrun_execution_authorized")
        is not False
        or manifest.get("authorization", {}).get(
            "future_execution_requires_exact_manifest_bound_approval"
        )
        is not True
    ):
        raise ValueError("dense WS deferred handoff canonical manifest mismatch")
    return manifest_path, manifest


def _resolve_dense_ws_deferred_completion_evidence(
    handoff: dict[str, Any],
    *,
    candidate: dict[str, Any],
    plan: dict[str, Any],
    plan_path: Path,
    campaign_root: Path,
    gate: dict[str, Any],
    usage: dict[str, Any] | None,
) -> dict[str, Any]:
    handoff_manifest_path, _ = _validate_dense_ws_deferred_handoff_freeze(
        handoff,
        candidate=candidate,
    )
    n14 = handoff.get("required_pit_completion")
    campaign_binding = handoff.get("campaign")
    if not isinstance(n14, dict) or not isinstance(campaign_binding, dict):
        raise ValueError("dense WS deferred handoff identity bindings are missing")

    campaign_id = str(candidate.get("campaign_id") or "")
    plan_hash = str(candidate.get("plan_hash") or "")
    expected_campaign_manifest = (campaign_root / "campaign-manifest.json").resolve()
    if (
        campaign_binding.get("campaign_id") != campaign_id
        or Path(str(campaign_binding.get("plan_path") or "")).expanduser().resolve()
        != plan_path
        or campaign_binding.get("plan_file_sha256")
        != str(candidate.get("plan_file_sha256") or "")
        or campaign_binding.get("plan_hash") != plan_hash
        or campaign_binding.get("contract_hash")
        != str(candidate.get("contract_hash") or "")
        or campaign_binding.get("candidate_contract_hash")
        != str(candidate.get("candidate_contract_hash") or "")
        or Path(
            str(campaign_binding.get("campaign_manifest_path") or "")
        ).expanduser().resolve()
        != expected_campaign_manifest
    ):
        raise ValueError("dense WS deferred handoff campaign binding mismatch")

    gate_status = str(gate.get("gate_status") or gate.get("status") or "")
    if gate_status == "RUNNING":
        return {"ready": False, "reason": "required_pit_run_still_running"}
    if gate_status == "STOPPED_INCOMPLETE":
        raise ValueError("required PIT run is STOPPED_INCOMPLETE")
    if str(gate.get("run_id") or "") != str(n14.get("run_id") or ""):
        return {"ready": False, "reason": "required_pit_run_not_current_gate"}
    if gate_status != "READY_FOR_POSTPROCESS":
        return {"ready": False, "reason": "required_pit_run_not_ready"}
    if (
        gate.get("final") is not True
        or gate.get("primary_output_complete") is not True
        or gate.get("expected_outputs_complete") is not True
        or str(gate.get("stop_reason") or "") != "completed"
    ):
        raise ValueError("required PIT gate is not final and complete")

    schedule_path, schedule = _load_sha256_bound_json(
        n14,
        label="dense WS deferred handoff PIT schedule",
        path_key="schedule_path",
        sha_key="schedule_file_sha256",
    )
    schedule_plan_hash = str(n14.get("schedule_plan_hash") or "")
    segments = schedule.get("segments")
    if (
        schedule.get("plan_hash") != schedule_plan_hash
        or not isinstance(segments, list)
    ):
        raise ValueError("dense WS deferred handoff PIT schedule binding mismatch")
    exact_segments = [
        item
        for item in segments
        if isinstance(item, dict) and item.get("run_id") == n14.get("run_id")
    ]
    if len(exact_segments) != 1:
        raise ValueError("dense WS deferred handoff PIT segment is not unique")
    segment = exact_segments[0]
    if (
        segment.get("start_local") != n14.get("start_local")
        or segment.get("end_local") != n14.get("end_local")
        or int(segment.get("duration_sec") or 0) != 1_200
    ):
        raise ValueError("dense WS deferred handoff PIT timing changed")

    pit_manifest_path = (
        Path(str(segment.get("output_dir") or "")).expanduser().resolve()
        / "manifest.json"
    ).resolve()
    if (
        Path(str(gate.get("manifest_path") or "")).expanduser().resolve()
        != pit_manifest_path
        or not pit_manifest_path.is_file()
    ):
        raise ValueError("required PIT gate manifest binding mismatch")
    pit_manifest = _load_json(pit_manifest_path)
    if (
        pit_manifest.get("schema") != "pit_universe_snapshot_manifest_v2"
        or pit_manifest.get("run_id") != n14.get("run_id")
        or pit_manifest.get("final") is not True
        or pit_manifest.get("incomplete") is not False
        or pit_manifest.get("status") != "COMPLETED"
    ):
        raise ValueError("required PIT manifest is not clean and complete")

    claim_path = Path(
        str(handoff.get("global_writer_claim_path") or "")
    ).expanduser().resolve()
    if claim_path.exists():
        claim = _load_json(claim_path)
        if _pid_alive(claim.get("owner_pid")):
            return {"ready": False, "reason": "live_global_writer_claim"}
        raise ValueError("stale global market-data writer claim")

    if (
        not isinstance(usage, dict)
        or usage.get("status") != "AVAILABLE"
        or float(usage.get("remaining_percent") or 0.0) <= 15.0
    ):
        return {"ready": False, "reason": "weekly_quota_or_telemetry_block"}

    summary_path = Path(
        str(n14.get("postrun_summary_path") or "")
    ).expanduser().resolve()
    reconciliation_path = Path(
        str(n14.get("postrun_reconciliation_path") or "")
    ).expanduser().resolve()
    if not summary_path.is_file():
        return {"ready": False, "reason": "required_pit_postrun_summary_missing"}
    if reconciliation_path.exists():
        raise ValueError("required PIT postrun uses an unapproved reconciliation")
    summary = _load_json(summary_path)
    deferred_actions = {
        "wait_for_fresh_weekly_quota_above_15_percent_then_retry_postrun",
        "run_train_feasibility_after_weekly_quota_reset",
        "refresh_horizon_after_weekly_quota_reset_then_request_exact_schedule_approval",
    }
    if (
        summary.get("schema") != "trading_mvp_pit_postrun_v1"
        or summary.get("project") != "trading_mvp"
        or summary.get("run_id") != n14.get("run_id")
        or summary.get("schedule_plan_hash") != schedule_plan_hash
        or Path(str(summary.get("schedule_plan_path") or "")).expanduser().resolve()
        != schedule_path
        or Path(str(summary.get("quality_ledger_path") or "")).expanduser().resolve()
        != Path(str(n14.get("quality_ledger_path") or "")).expanduser().resolve()
        or not str(summary.get("decision") or "")
        or summary.get("decision") == "PIT_POSTRUN_FAILED"
        or str(summary.get("decision") or "").startswith("PAUSED")
        or not str(summary.get("next_allowed_action") or "")
        or summary.get("next_allowed_action") in deferred_actions
        or summary.get("returns_read") is not False
        or summary.get("pnl_read") is not False
        or summary.get("oos_run") is not False
        or summary.get("grid_search") is not False
        or summary.get("live_orders") is not False
        or summary.get("private_api_keys") is not False
    ):
        raise ValueError("required PIT postrun summary is not COMPLETE")

    if not expected_campaign_manifest.is_file():
        return {"ready": False, "reason": "dense_campaign_manifest_missing"}
    campaign_manifest = _load_json(expected_campaign_manifest)
    phase_results = campaign_manifest.get("phase_results")
    phases = plan.get("phases")
    if (
        campaign_manifest.get("schema") != "trading_mvp_dense_ws_campaign_manifest_v1"
        or campaign_manifest.get("campaign_id") != campaign_id
        or Path(str(campaign_manifest.get("plan_path") or "")).expanduser().resolve()
        != plan_path
        or campaign_manifest.get("plan_hash") != plan_hash
        or campaign_manifest.get("contract_hash")
        != campaign_binding.get("contract_hash")
        or campaign_manifest.get("candidate_contract_hash")
        != campaign_binding.get("candidate_contract_hash")
        or campaign_manifest.get("universe_sha256")
        != campaign_binding.get("universe_sha256")
        or campaign_manifest.get("runtime_completed") is not True
        or campaign_manifest.get("liveness_clean") is not True
        or campaign_manifest.get("quality_eligible") is not True
        or campaign_manifest.get("completed") is not True
        or campaign_manifest.get("final") is not True
        or campaign_manifest.get("dirty_segment_ids") != []
        or not isinstance(phases, list)
        or not isinstance(phase_results, list)
        or len(phase_results) != len(phases)
        or int(campaign_manifest.get("phases_completed") or 0) != len(phases)
        or any(
            item.get("runtime_completed") is not True
            or item.get("liveness_clean") is not True
            or item.get("quality_eligible") is not True
            for item in phase_results
            if isinstance(item, dict)
        )
        or any(not isinstance(item, dict) for item in phase_results)
    ):
        raise ValueError("dense WS deferred campaign manifest is not clean and complete")

    return {
        "ready": True,
        "completion_evidence_mode": "IMMUTABLE_COMPLETED_CAMPAIGN_MANIFEST_AFTER_PIT",
        "campaign_manifest_path": str(expected_campaign_manifest),
        "campaign_manifest_sha256": _sha256(expected_campaign_manifest),
        "required_prior_pit_run_id": str(n14.get("run_id") or ""),
        "required_prior_pit_plan_hash": schedule_plan_hash,
        "required_prior_pit_manifest_path": str(pit_manifest_path),
        "required_prior_pit_manifest_sha256": _sha256(pit_manifest_path),
        "required_prior_pit_postrun_summary_path": str(summary_path),
        "required_prior_pit_postrun_summary_sha256": _sha256(summary_path),
        "handoff_manifest_path": str(handoff_manifest_path),
        "handoff_manifest_sha256": _sha256(handoff_manifest_path),
    }


def _dense_ws_postrun_execution_is_authorized(
    handoff: dict[str, Any],
    *,
    candidate: dict[str, Any],
    completion_evidence: dict[str, Any],
) -> bool:
    if handoff.get("postrun_execution_authorized") is not True:
        return False
    approval_binding = handoff.get("execution_approval")
    if not isinstance(approval_binding, dict) or approval_binding.get("status") != "APPROVED":
        raise ValueError("dense WS postrun execution flag lacks an approved receipt")
    approval_path, approval = _load_sha256_bound_json(
        approval_binding,
        label="dense WS manifest-bound postrun execution approval",
        path_key="receipt_path",
        sha_key="receipt_file_sha256",
    )
    runtime = handoff.get("runtime_window")
    canonical_manifest = handoff.get("canonical_manifest")
    if not isinstance(runtime, dict) or not isinstance(canonical_manifest, dict):
        raise ValueError("dense WS postrun execution runtime binding is missing")
    if (
        approval.get("schema")
        != "trading_mvp_dense_ws_manifest_bound_postrun_execution_approval_v1"
        or approval.get("status") != "APPROVED_SINGLE_USE"
        or approval.get("campaign_id") != candidate.get("campaign_id")
        or approval.get("campaign_plan_hash") != candidate.get("plan_hash")
        or approval.get("campaign_manifest_path")
        != completion_evidence.get("campaign_manifest_path")
        or approval.get("campaign_manifest_sha256")
        != completion_evidence.get("campaign_manifest_sha256")
        or approval.get("handoff_manifest_path")
        != str(Path(str(canonical_manifest.get("path") or "")).expanduser().resolve())
        or approval.get("handoff_manifest_sha256")
        != canonical_manifest.get("file_sha256")
        or approval.get("postrun_not_before_local")
        != runtime.get("postrun_not_before_local")
        or approval.get("postrun_latest_full_runtime_start_local")
        != runtime.get("latest_full_runtime_start_local")
        or approval.get("postrun_hard_deadline_local")
        != runtime.get("postrun_hard_deadline_local")
        or int(approval.get("total_max_runtime_sec") or 0)
        != int(runtime.get("total_max_runtime_sec") or 0)
        or approval.get("postrun_execution_authorized") is not True
        or approval.get("collector_launch_authorized") is not False
        or approval.get("network_market_data_authorized") is not False
        or approval.get("evaluator_authorized") is not False
        or approval.get("returns_pnl_oos_authorized") is not False
        or approval.get("grid_or_retune_authorized") is not False
        or approval.get("paper_live_private_api_real_capital_leverage_margin_authorized")
        is not False
        or approval.get("stopped_incomplete_retry_authorized") is not False
    ):
        raise ValueError(
            f"dense WS manifest-bound execution approval mismatch: {approval_path}"
        )
    return True


def _resolve_dense_ws_materialization_bound_planonly(
    policy: dict[str, Any],
    *,
    candidate: dict[str, Any],
    campaign_root: Path,
    materialization_path: Path,
    materialization: dict[str, Any],
) -> dict[str, Any]:
    config = policy.get("dense_ws_materialization_bound_planonly")
    if not isinstance(config, dict):
        return {"status": "MATERIALIZATION_ACCEPTED"}
    if (
        config.get("status") != "READY_CONTRACT_FREEZE_ONLY"
        or config.get("automatic_same_hash_planonly_build_authorized") is not True
        or config.get("evaluation_authorized") is not False
        or config.get("returns_pnl_oos_allowed") is not False
        or config.get("network_collector_allowed") is not False
        or config.get("grid_or_retune_allowed") is not False
        or config.get("paper_live_private_api_real_capital_leverage_margin_allowed")
        is not False
    ):
        raise ValueError("dense WS materialization-bound PlanOnly safety policy mismatch")

    for label in ("builder", "visible_wrapper"):
        path = Path(str(config.get(f"{label}_path") or "")).expanduser().resolve()
        expected_sha = str(config.get(f"{label}_sha256") or "").lower()
        if not path.is_file() or len(expected_sha) != 64:
            raise ValueError(f"dense WS {label} is missing or unbound")
        if _sha256(path) != expected_sha:
            raise ValueError(f"dense WS {label} file hash mismatch")

    output_name = str(config.get("output_name") or "").strip()
    owner_name = str(config.get("owner_name") or "").strip()
    if (
        not output_name
        or Path(output_name).name != output_name
        or not owner_name
        or Path(owner_name).name != owner_name
    ):
        raise ValueError("dense WS materialization-bound output names are invalid")
    postrun_root = (campaign_root / "_postrun").resolve()
    output_path = (postrun_root / output_name).resolve()
    owner_path = (postrun_root / owner_name).resolve()
    if campaign_root not in output_path.parents or campaign_root not in owner_path.parents:
        raise ValueError("dense WS materialization-bound output escapes campaign root")

    result: dict[str, Any] = {
        "status": "MATERIALIZATION_ACCEPTED",
        "materialization_bound_planonly_path": str(output_path),
        "materialization_bound_owner_path": str(owner_path),
        "materialization_bound_builder_path": str(
            Path(str(config["builder_path"])).expanduser().resolve()
        ),
        "materialization_bound_visible_wrapper_path": str(
            Path(str(config["visible_wrapper_path"])).expanduser().resolve()
        ),
    }

    owner: dict[str, Any] | None = None
    if owner_path.is_file():
        owner = _load_json(owner_path)
        if (
            owner.get("schema")
            != "trading_mvp_dense_ws_materialization_bound_plan_owner_v1"
            or owner.get("campaign_id") != candidate.get("campaign_id")
            or owner.get("campaign_plan_hash") != candidate.get("plan_hash")
            or owner.get("frozen_plan_hash")
            != (policy.get("dense_ws_signal_evaluator_freeze") or {}).get(
                "plan_hash"
            )
        ):
            raise ValueError("dense WS materialization-bound owner binding mismatch")
        if owner.get("final") is not True:
            if _pid_alive(owner.get("terminal_pid")):
                result.update(
                    {
                        "status": "MATERIALIZATION_BOUND_PLAN_RUNNING",
                        "terminal_pid": owner.get("terminal_pid"),
                    }
                )
                return result
            result.update(
                {
                    "status": "STOPPED_INCOMPLETE",
                    "reason": "materialization_bound_owner_not_final_and_terminal_is_dead",
                }
            )
            return result
        if owner.get("status") != "COMPLETE":
            result.update(
                {
                    "status": "STOPPED_INCOMPLETE",
                    "reason": "materialization_bound_owner_final_status:"
                    f"{owner.get('status') or 'UNKNOWN'}",
                }
            )
            return result

    if not output_path.is_file():
        if owner is not None and owner.get("status") == "COMPLETE":
            raise ValueError("dense WS bound owner is COMPLETE but output is missing")
        return result
    if owner is None or owner.get("status") != "COMPLETE":
        raise ValueError("dense WS bound PlanOnly exists without a completed visible owner")

    bound = _load_json(output_path)
    dense_ws_bound_plan.validate_materialization_bound_plan(bound)
    frozen = policy.get("dense_ws_signal_evaluator_freeze")
    if not isinstance(frozen, dict):
        raise ValueError("dense WS signal/evaluator freeze is missing")
    if (
        bound.get("identity", {}).get("campaign_id") != candidate.get("campaign_id")
        or bound.get("campaign", {}).get("plan", {}).get("plan_hash")
        != candidate.get("plan_hash")
        or bound.get("frozen_signal_evaluator_plan", {}).get("plan_hash")
        != frozen.get("plan_hash")
        or bound.get("frozen_signal_evaluator_contract", {}).get("contract_hash")
        != frozen.get("contract_hash")
        or bound.get("materialization", {}).get("manifest", {}).get("path")
        != str(materialization_path)
        or bound.get("materialization", {}).get("manifest", {}).get("file_sha256")
        != _sha256(materialization_path)
        or bound.get("materialization", {})
        .get("manifest", {})
        .get("deterministic_result_hash")
        != materialization.get("deterministic_result_hash")
    ):
        raise ValueError("dense WS materialization-bound PlanOnly binding mismatch")
    result.update(
        {
            "status": "MATERIALIZATION_BOUND_PLANONLY_READY",
            "materialization_bound_planonly_sha256": _sha256(output_path),
            "materialization_bound_plan_hash": bound.get("plan_hash"),
            "evaluation_authorized": False,
            "returns_pnl_oos_allowed": False,
            "next_allowed_action": "REQUEST_EXACT_HASH_BOUND_EVALUATOR_APPROVAL",
        }
    )
    return result


def resolve_dense_ws_postrun(
    policy: dict[str, Any],
    gate: dict[str, Any],
    *,
    usage: dict[str, Any] | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    candidate = policy.get("next_long_campaign")
    if not isinstance(candidate, dict):
        return _dense_ws_postrun_base(status="NOT_APPLICABLE")

    campaign_id = str(candidate.get("campaign_id") or "")
    plan_hash = str(candidate.get("plan_hash") or "")
    exact_completed_campaign = bool(
        campaign_id
        and str(gate.get("run_id") or "") == campaign_id
        and str(gate.get("run_type") or "") == "dense_ws_campaign"
        and str(gate.get("gate_status") or gate.get("status") or "")
        == "READY_FOR_POSTPROCESS"
        and gate.get("completed") is True
        and gate.get("final") is True
    )

    config = policy.get("dense_ws_postrun")
    if not isinstance(config, dict):
        if not exact_completed_campaign:
            return _dense_ws_postrun_base(status="NOT_APPLICABLE")
        return _dense_ws_postrun_base(
            status="QUALITY_MISSING",
            campaign_id=campaign_id,
            plan_hash=plan_hash,
        )
    if config.get("automatic_same_hash_through_materialization") is not True:
        raise ValueError("dense WS automatic postrun progression is not enabled")

    plan_path = Path(str(candidate.get("plan_path") or "")).expanduser().resolve()
    expected_plan_file_sha = str(candidate.get("plan_file_sha256") or "").lower()
    if not plan_path.is_file() or len(expected_plan_file_sha) != 64:
        raise ValueError("dense WS postrun PlanOnly is missing or unbound")
    if _sha256(plan_path) != expected_plan_file_sha:
        raise ValueError("dense WS postrun PlanOnly file hash mismatch")
    plan = _load_json(plan_path)
    if plan.get("campaign_id") != campaign_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("dense WS postrun PlanOnly identity mismatch")

    outputs = plan.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("dense WS postrun PlanOnly outputs are missing")
    campaign_root = Path(str(outputs.get("campaign_root") or "")).expanduser().resolve()
    expected_campaign_manifest = (campaign_root / "campaign-manifest.json").resolve()
    handoff = config.get("deferred_handoff")
    completion_evidence: dict[str, Any]
    if exact_completed_campaign:
        gate_manifest = Path(str(gate.get("manifest_path") or "")).expanduser().resolve()
        if gate_manifest != expected_campaign_manifest or not gate_manifest.is_file():
            raise ValueError("dense WS completed gate manifest binding mismatch")
        completion_evidence = {
            "ready": True,
            "completion_evidence_mode": "ACTIVE_DENSE_GATE",
            "campaign_manifest_path": str(gate_manifest),
            "campaign_manifest_sha256": _sha256(gate_manifest),
        }
        if isinstance(handoff, dict):
            _validate_dense_ws_deferred_handoff_freeze(
                handoff,
                candidate=candidate,
            )
    elif isinstance(handoff, dict):
        completion_evidence = _resolve_dense_ws_deferred_completion_evidence(
            handoff,
            candidate=candidate,
            plan=plan,
            plan_path=plan_path,
            campaign_root=campaign_root,
            gate=gate,
            usage=usage,
        )
        if completion_evidence.get("ready") is not True:
            result = _dense_ws_postrun_base(
                status="NOT_APPLICABLE",
                campaign_id=campaign_id,
                plan_hash=plan_hash,
            )
            result.update(
                {
                    "reason": completion_evidence.get("reason"),
                    "deferred_handoff_configured": True,
                    "execution_authorized": False,
                }
            )
            return result
    else:
        return _dense_ws_postrun_base(status="NOT_APPLICABLE")

    output_names = config.get("output_names")
    if not isinstance(output_names, dict):
        raise ValueError("dense_ws_postrun.output_names is missing")
    paths = {
        key: _resolve_dense_ws_output_path(campaign_root, output_names, key)
        for key in (
            "quality_report",
            "regime_labels",
            "execution_snapshots",
            "materialization_manifest",
            "owner",
        )
    }

    base = _dense_ws_postrun_base(
        status="UNKNOWN",
        campaign_id=campaign_id,
        plan_hash=plan_hash,
    )
    base.update(
        {
            "plan_path": str(plan_path),
            "campaign_manifest_path": completion_evidence[
                "campaign_manifest_path"
            ],
            "campaign_manifest_sha256": completion_evidence[
                "campaign_manifest_sha256"
            ],
            "completion_evidence_mode": completion_evidence[
                "completion_evidence_mode"
            ],
            "campaign_root": str(campaign_root),
            "quality_report_path": str(paths["quality_report"]),
            "materialization_manifest_path": str(paths["materialization_manifest"]),
            "labels_path": str(paths["regime_labels"]),
            "snapshots_path": str(paths["execution_snapshots"]),
            "owner_path": str(paths["owner"]),
        }
    )
    base.update(
        {
            key: value
            for key, value in completion_evidence.items()
            if key not in {"ready", "campaign_manifest_path", "campaign_manifest_sha256"}
        }
    )

    if isinstance(handoff, dict):
        runtime = handoff.get("runtime_window")
        if not isinstance(runtime, dict):
            raise ValueError("dense WS deferred handoff runtime window is missing")
        execution_authorized = _dense_ws_postrun_execution_is_authorized(
            handoff,
            candidate=candidate,
            completion_evidence=completion_evidence,
        )
        base.update(
            {
                "execution_authorized": execution_authorized,
                "future_execution_requires_exact_manifest_bound_approval": True,
                "postrun_not_before_local": runtime.get("postrun_not_before_local"),
                "latest_full_runtime_start_local": runtime.get(
                    "latest_full_runtime_start_local"
                ),
                "postrun_hard_deadline_local": runtime.get(
                    "postrun_hard_deadline_local"
                ),
                "total_max_runtime_sec": runtime.get("total_max_runtime_sec"),
            }
        )
        if not execution_authorized:
            unauthorized_outputs = [
                str(path)
                for path in paths.values()
                if path.exists()
            ]
            if unauthorized_outputs:
                raise ValueError(
                    "dense WS postrun artifacts exist without manifest-bound "
                    f"execution approval: {unauthorized_outputs}"
                )
            base["status"] = "AWAITING_EXACT_MANIFEST_BOUND_POSTRUN_APPROVAL"
            return base

        observed = _parse_timestamp(
            observed_at_utc or _iso_now(),
            label="dense_ws_postrun.observed_at_utc",
        )
        not_before = _parse_timestamp(
            runtime.get("postrun_not_before_local"),
            label="dense_ws_postrun.postrun_not_before_local",
        )
        latest_start = _parse_timestamp(
            runtime.get("latest_full_runtime_start_local"),
            label="dense_ws_postrun.latest_full_runtime_start_local",
        )
        hard_deadline = _parse_timestamp(
            runtime.get("postrun_hard_deadline_local"),
            label="dense_ws_postrun.postrun_hard_deadline_local",
        )
        if not (
            not_before < latest_start < hard_deadline
            and int(runtime.get("total_max_runtime_sec") or 0) == 3_600
            and int(runtime.get("quality_max_runtime_sec") or 0) == 1_800
            and int(runtime.get("materialization_max_runtime_sec") or 0) == 1_800
        ):
            raise ValueError("dense WS deferred handoff runtime contract mismatch")
        if observed < not_before:
            base["status"] = "POSTRUN_WINDOW_NOT_OPEN"
            return base
        if observed > latest_start:
            base["status"] = "POSTRUN_WINDOW_EXPIRED"
            return base

    if paths["owner"].is_file():
        owner = _load_json(paths["owner"])
        if (
            owner.get("schema") != "trading_mvp_dense_ws_postrun_owner_v1"
            or owner.get("campaign_id") != campaign_id
            or owner.get("plan_hash") != plan_hash
        ):
            raise ValueError("dense WS postrun owner binding mismatch")
        if owner.get("final") is not True:
            if _pid_alive(owner.get("terminal_pid")):
                base.update(
                    {
                        "status": "RUNNING",
                        "terminal_pid": owner.get("terminal_pid"),
                        "stage": owner.get("stage"),
                    }
                )
                return base
            base.update(
                {
                    "status": "STOPPED_INCOMPLETE",
                    "reason": "postrun_owner_not_final_and_terminal_is_dead",
                }
            )
            return base
        owner_status = str(owner.get("status") or "")
        if owner_status not in {
            "COMPLETE",
            "QUALITY_REJECTED",
            "MATERIALIZATION_REJECTED",
        }:
            base.update(
                {
                    "status": "STOPPED_INCOMPLETE",
                    "reason": f"postrun_owner_final_status:{owner_status or 'UNKNOWN'}",
                }
            )
            return base

    quality_exists = paths["quality_report"].is_file()
    materialization_exists = paths["materialization_manifest"].is_file()
    labels_exists = paths["regime_labels"].is_file()
    snapshots_exists = paths["execution_snapshots"].is_file()

    if materialization_exists:
        if not quality_exists or not labels_exists or not snapshots_exists:
            raise ValueError("dense WS materialization evidence set is incomplete")
        quality = _load_json(paths["quality_report"])
        materialization = _load_json(paths["materialization_manifest"])
        if (
            quality.get("schema") != "trading_mvp_dense_ws_campaign_quality_v1"
            or quality.get("campaign_id") != campaign_id
            or quality.get("plan_hash") != plan_hash
        ):
            raise ValueError("dense WS quality report binding mismatch")
        if (
            materialization.get("schema")
            != "trading_mvp_dense_ws_causal_materialization_v1"
            or materialization.get("campaign_id") != campaign_id
            or materialization.get("plan_hash") != plan_hash
        ):
            raise ValueError("dense WS materialization manifest binding mismatch")
        quality_ref = materialization.get("quality_report")
        labels_ref = materialization.get("labels")
        snapshots_ref = materialization.get("execution_snapshots")
        if not all(isinstance(item, dict) for item in (quality_ref, labels_ref, snapshots_ref)):
            raise ValueError("dense WS materialization evidence references are missing")
        if (
            Path(str(quality_ref.get("path") or "")).expanduser().resolve()
            != paths["quality_report"]
            or str(quality_ref.get("sha256") or "") != _sha256(paths["quality_report"])
            or Path(str(labels_ref.get("path") or "")).expanduser().resolve()
            != paths["regime_labels"]
            or Path(str(snapshots_ref.get("path") or "")).expanduser().resolve()
            != paths["execution_snapshots"]
        ):
            raise ValueError("dense WS materialization evidence path/hash mismatch")
        base.update(
            {
                "status": (
                    "MATERIALIZATION_ACCEPTED"
                    if materialization.get("accepted") is True
                    and materialization.get("decision")
                    == "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW"
                    else "MATERIALIZATION_REJECTED"
                    if materialization.get("accepted") is False
                    and materialization.get("decision")
                    == "REJECT_CAUSAL_MATERIALIZATION"
                    else "INTEGRITY_CONFLICT"
                ),
                "decision": materialization.get("decision"),
                "deterministic_result_hash": materialization.get(
                    "deterministic_result_hash"
                ),
                "materialization_manifest_sha256": _sha256(
                    paths["materialization_manifest"]
                ),
                "quality_report_sha256": _sha256(paths["quality_report"]),
                "regime_labels_sha256": labels_ref.get("sha256"),
                "execution_snapshots_sha256": snapshots_ref.get("sha256"),
                "full_data_hash_revalidation_required_before_evaluator": True,
            }
        )
        if base["status"] == "MATERIALIZATION_ACCEPTED":
            base.update(
                _resolve_dense_ws_materialization_bound_planonly(
                    policy,
                    candidate=candidate,
                    campaign_root=campaign_root,
                    materialization_path=paths["materialization_manifest"],
                    materialization=materialization,
                )
            )
        return base

    if labels_exists or snapshots_exists:
        raise ValueError("dense WS materialization outputs exist without final manifest")
    if not quality_exists:
        base["status"] = "QUALITY_MISSING"
        return base

    quality = _load_json(paths["quality_report"])
    if (
        quality.get("schema") != "trading_mvp_dense_ws_campaign_quality_v1"
        or quality.get("campaign_id") != campaign_id
        or quality.get("plan_hash") != plan_hash
    ):
        raise ValueError("dense WS quality report binding mismatch")
    if quality.get("accepted") is True and quality.get("decision") == (
        "DATA_READY_FOR_TRAIN_ONLY_REVIEW"
    ):
        base.update(
            {
                "status": "QUALITY_ACCEPTED",
                "decision": quality.get("decision"),
                "quality_report_sha256": _sha256(paths["quality_report"]),
            }
        )
        return base
    if quality.get("accepted") is False and quality.get("decision") == (
        "REJECT_DATA_QUALITY"
    ):
        base.update(
            {
                "status": "QUALITY_REJECTED",
                "decision": quality.get("decision"),
                "quality_report_sha256": _sha256(paths["quality_report"]),
                "reasons": quality.get("reasons"),
            }
        )
        return base
    raise ValueError("dense WS quality report decision is inconsistent")


def resolve_schedule_window(
    policy: dict[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any] | None:
    schedule_config = policy.get("current_pit_schedule")
    if not isinstance(schedule_config, dict):
        return None
    pointer_value = schedule_config.get("pointer_path")
    if not pointer_value:
        return None

    pointer_path = Path(str(pointer_value)).expanduser().resolve()
    pointer = _load_json(pointer_path)
    pointer_status = str(pointer.get("status") or "")
    if pointer_status in {"PAUSED", "SUPERSEDED"}:
        return {
            "status": pointer_status,
            "pointer_path": str(pointer_path),
        }
    if pointer_status != "ACTIVE":
        raise ValueError(
            f"schedule pointer must be ACTIVE, observed={pointer_status!r}"
        )
    plan_path = Path(str(pointer.get("plan_path") or "")).expanduser().resolve()
    ledger_path = Path(
        str(pointer.get("quality_ledger_path") or "")
    ).expanduser().resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(f"schedule plan is missing: {plan_path}")
    if not ledger_path.is_file():
        raise FileNotFoundError(f"quality ledger is missing: {ledger_path}")

    plan = _load_json(plan_path)
    pointer_hash = str(pointer.get("plan_hash") or "")
    plan_hash = str(plan.get("plan_hash") or "")
    if not pointer_hash or pointer_hash != plan_hash:
        raise ValueError(
            "schedule pointer/plan hash mismatch: "
            f"pointer={pointer_hash!r} plan={plan_hash!r}"
        )

    hypothesis = plan.get("hypothesis")
    sealed_schedule = plan.get("sealed_schedule")
    if not isinstance(hypothesis, dict) or not isinstance(sealed_schedule, dict):
        raise ValueError("schedule plan lacks frozen hypothesis or sealed_schedule")
    stage = sealed_schedule.get("collection_stage")
    quality_policy = sealed_schedule.get("quality_policy")
    if not isinstance(stage, dict) or not isinstance(quality_policy, dict):
        raise ValueError("schedule plan lacks collection stage or quality policy")

    hypothesis_id = str(hypothesis.get("id") or "")
    data_type = str(hypothesis.get("required_data_type") or "")
    collection_stage = str(stage.get("name") or "")
    contract_hash = str(
        sealed_schedule.get("hypothesis_contract_sha256") or ""
    )
    stage_target = int(stage.get("stage_target_distinct_dates") or 0)
    if (
        not hypothesis_id
        or not data_type
        or not collection_stage
        or len(contract_hash) != 64
        or stage_target <= 0
    ):
        raise ValueError("schedule plan frozen stage contract is incomplete")
    if str(plan.get("collection_stage") or "") != collection_stage:
        raise ValueError("schedule plan collection_stage mismatch")
    if str(pointer.get("hypothesis_id") or "") != hypothesis_id:
        raise ValueError("schedule pointer hypothesis mismatch")
    if str(pointer.get("data_type") or "") != data_type:
        raise ValueError("schedule pointer data_type mismatch")
    if str(pointer.get("collection_stage") or "") != collection_stage:
        raise ValueError("schedule pointer collection_stage mismatch")
    sealed_ledger_path = Path(
        str((stage.get("quality_ledger") or {}).get("path") or "")
    ).expanduser().resolve()
    if sealed_ledger_path != ledger_path:
        raise ValueError("schedule plan quality ledger mismatch")
    if collection_stage == "train_accrual":
        train_target = int(
            quality_policy.get("train_feasibility_distinct_days") or 0
        )
        if train_target <= 0 or stage_target != train_target:
            raise ValueError("train-accrual stage target/quality policy mismatch")

    accepted_dates: set[str] = set()
    for line_number, line in enumerate(
        ledger_path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        entry = json.loads(line)
        if not isinstance(entry, dict):
            raise ValueError(
                f"quality ledger row must be an object: {ledger_path}:{line_number}"
            )
        if (
            str(entry.get("hypothesis_id") or "") != hypothesis_id
            or str(entry.get("data_type") or "") != data_type
            or str(entry.get("hypothesis_contract_sha256") or "")
            != contract_hash
        ):
            raise ValueError(
                "quality ledger contains a foreign hypothesis/data/contract entry"
            )
        if entry.get("technical_quality_accepted") is True:
            scheduled_date = str(entry.get("scheduled_date") or "")
            if not scheduled_date:
                raise ValueError("accepted quality certification lacks scheduled_date")
            accepted_dates.add(scheduled_date)

    stage_metadata = {
        "pointer_path": str(pointer_path),
        "plan_path": str(plan_path),
        "plan_hash": plan_hash,
        "hypothesis_id": hypothesis_id,
        "data_type": data_type,
        "collection_stage": collection_stage,
        "hypothesis_contract_sha256": contract_hash,
        "accepted_distinct_dates": len(accepted_dates),
        "stage_target_distinct_dates": stage_target,
    }
    if len(accepted_dates) > stage_target:
        return {
            **stage_metadata,
            "status": "STAGE_TARGET_OVERSHOOT",
            "overshoot_distinct_dates": len(accepted_dates) - stage_target,
        }
    if len(accepted_dates) == stage_target:
        return {
            **stage_metadata,
            "status": "STAGE_TARGET_REACHED",
        }

    now = _parse_timestamp(observed_at_utc, label="observed_at_utc")
    pending: list[tuple[datetime, datetime, datetime, dict[str, Any]]] = []
    expired_unaccepted = 0
    for raw_segment in plan.get("segments") or []:
        if not isinstance(raw_segment, dict):
            raise ValueError("schedule segment must be an object")
        start = _parse_timestamp(raw_segment.get("start_local"), label="segment.start_local")
        end = _parse_timestamp(raw_segment.get("end_local"), label="segment.end_local")
        deadline = _parse_timestamp(
            raw_segment.get("hard_deadline_local"),
            label="segment.hard_deadline_local",
        )
        if end <= start:
            raise ValueError("segment.end_local must be after segment.start_local")
        if deadline < end:
            raise ValueError(
                "segment.hard_deadline_local must not precede segment.end_local"
            )
        scheduled_date = start.date().isoformat()
        if scheduled_date in accepted_dates:
            continue
        if deadline <= now:
            expired_unaccepted += 1
            continue
        pending.append((start, end, deadline, raw_segment))

    if not pending:
        return {
            **stage_metadata,
            "status": "NO_PENDING_SEGMENT",
            "expired_unaccepted_segments": expired_unaccepted,
        }

    start, end, deadline, segment = min(pending, key=lambda item: item[0])
    duration_sec = math.ceil((end - start).total_seconds())
    status = "WAITING" if now < start else "DUE"
    return {
        **stage_metadata,
        "status": status,
        "classification": (
            "PREAPPROVED_SHORT_SEGMENT"
            if duration_sec <= 1_800
            else "LONG_CAMPAIGN"
        ),
        "run_id": segment.get("run_id"),
        "start_local": start.isoformat(),
        "end_local": end.isoformat(),
        "duration_sec": duration_sec,
        "hard_deadline_local": deadline.isoformat(),
        "eta_sec": max(0, math.ceil((start - now).total_seconds())),
        "expired_unaccepted_segments": expired_unaccepted,
    }


def resolve_continuous_production_window(
    policy: dict[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any] | None:
    config = policy.get("continuous_production_policy")
    if not isinstance(config, dict):
        return None
    policy_value = config.get("path")
    expected_hash = str(config.get("sha256") or "").strip().lower()
    if not policy_value:
        raise ValueError("continuous_production_policy.path is missing")
    if len(expected_hash) != 64:
        raise ValueError("continuous_production_policy.sha256 is invalid")

    policy_path = Path(str(policy_value)).expanduser().resolve()
    if not policy_path.is_file():
        raise FileNotFoundError(
            f"continuous production policy is missing: {policy_path}"
        )
    observed_hash = _sha256(policy_path)
    if observed_hash != expected_hash:
        raise ValueError(
            "continuous production policy hash mismatch: "
            f"expected={expected_hash} observed={observed_hash}"
        )
    window = resolve_run_window(
        _load_json(policy_path),
        observed_at_utc=observed_at_utc,
    )
    window["policy_path"] = str(policy_path)
    window["policy_sha256"] = observed_hash
    return window


def resolve_pit_schedule_extension(
    policy: dict[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    candidate = policy.get("pit_schedule_extension_candidate")
    if not isinstance(candidate, dict):
        return {"status": "NOT_CONFIGURED"}

    audit_path = Path(
        str(candidate.get("horizon_audit_path") or "")
    ).expanduser().resolve()
    plan_path = Path(
        str(candidate.get("plan_path") or "")
    ).expanduser().resolve()
    if not audit_path.is_file() or not plan_path.is_file():
        raise ValueError("PIT schedule extension artifacts are missing")

    expected_audit_sha = str(candidate.get("horizon_audit_sha256") or "")
    expected_plan_sha = str(candidate.get("plan_file_sha256") or "")
    expected_plan_hash = str(candidate.get("plan_hash") or "")
    if len(expected_audit_sha) != 64 or _sha256(audit_path) != expected_audit_sha:
        raise ValueError("PIT schedule extension horizon audit hash mismatch")
    if len(expected_plan_sha) != 64 or _sha256(plan_path) != expected_plan_sha:
        raise ValueError("PIT schedule extension plan file hash mismatch")

    audit = _load_json(audit_path)
    plan = _load_json(plan_path)
    if str(plan.get("plan_hash") or "") != expected_plan_hash:
        raise ValueError("PIT schedule extension plan hash mismatch")
    if (
        str(audit.get("schema") or "")
        != "trading_mvp_pit_schedule_horizon_audit_v1"
        or str(audit.get("mode") or "") != "PlanOnly"
    ):
        raise ValueError("PIT horizon audit schema or mode mismatch")
    source_plan_hash = str(candidate.get("source_plan_hash") or "")
    source_schedule = audit.get("source_schedule")
    if (
        not isinstance(source_schedule, dict)
        or str(source_schedule.get("plan_hash") or "") != source_plan_hash
    ):
        raise ValueError("PIT horizon audit source schedule binding mismatch")
    proposal = audit.get("extension_proposal")
    if not isinstance(proposal, dict):
        raise ValueError("PIT horizon audit is missing extension_proposal")
    if str(proposal.get("plan_hash") or "") != expected_plan_hash:
        raise ValueError("PIT horizon audit extension plan binding mismatch")
    if Path(
        str(proposal.get("output_path") or "")
    ).expanduser().resolve() != plan_path:
        raise ValueError("PIT horizon audit extension path binding mismatch")
    if str(proposal.get("output_sha256") or "") != expected_plan_sha:
        raise ValueError("PIT horizon audit extension file hash mismatch")
    if bool(proposal.get("activated")):
        raise ValueError("PIT horizon audit extension must remain inactive")
    if proposal.get("requires_explicit_schedule_approval") is not True:
        raise ValueError("PIT horizon audit must require explicit approval")

    nights = int(candidate.get("nights") or 0)
    horizon = audit.get("horizon")
    if not isinstance(horizon, dict):
        raise ValueError("PIT horizon audit is missing horizon")
    if str(horizon.get("decision") or "") != "PLANONLY_EXTENSION_REQUIRED":
        raise ValueError("PIT horizon audit does not require an extension")
    if int(horizon.get("recommended_extension_nights") or 0) != nights:
        raise ValueError("PIT horizon audit recommended nights mismatch")
    if int(proposal.get("nights") or 0) != nights:
        raise ValueError("PIT horizon audit proposal nights mismatch")
    if int(
        proposal.get("combined_maximum_reachable_distinct_dates") or 0
    ) < int(horizon.get("target_distinct_dates") or 0):
        raise ValueError("PIT horizon audit extension cannot reach the train gate")
    if bool(plan.get("schedule_approved")) or bool(plan.get("collection_started")):
        raise ValueError("PIT schedule extension candidate must remain inactive")

    observed = datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00"))
    request_at = datetime.fromisoformat(
        str(candidate.get("approval_request_not_before_local") or "")
    )
    starts_at = datetime.fromisoformat(str(candidate.get("start_local") or ""))
    hard_deadline = datetime.fromisoformat(
        str(candidate.get("hard_deadline_local") or "")
    )
    for name, value in (
        ("observed_at_utc", observed),
        ("approval_request_not_before_local", request_at),
        ("start_local", starts_at),
        ("hard_deadline_local", hard_deadline),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must include a UTC offset")

    requires_fresh = bool(
        candidate.get("requires_fresh_horizon_audit_before_approval")
    )
    max_audit_age_sec = int(
        candidate.get("fresh_horizon_audit_max_age_sec") or 0
    )
    require_post_window_audit = (
        candidate.get(
            "fresh_horizon_audit_must_not_predate_approval_window"
        )
        is True
    )
    require_current_ledger = (
        candidate.get(
            "fresh_horizon_audit_must_match_current_quality_ledger"
        )
        is True
    )
    if requires_fresh and (
        max_audit_age_sec <= 0
        or not require_post_window_audit
        or not require_current_ledger
    ):
        raise ValueError("PIT extension fresh horizon policy is incomplete")

    audit_observed = _parse_timestamp(
        audit.get("observed_at"),
        label="horizon_audit.observed_at",
    )
    quality_ledger = audit.get("quality_ledger")
    if not isinstance(quality_ledger, dict):
        raise ValueError("PIT horizon audit quality ledger binding is missing")
    ledger_path = Path(
        str(quality_ledger.get("path") or "")
    ).expanduser().resolve()
    if not ledger_path.is_file():
        raise ValueError("PIT horizon audit quality ledger is missing")
    audit_ledger_sha = str(quality_ledger.get("file_sha256") or "")
    current_ledger_sha = _sha256(ledger_path)
    if len(audit_ledger_sha) != 64:
        raise ValueError("PIT horizon audit quality ledger hash is invalid")

    audit_age_sec = (observed - audit_observed).total_seconds()
    if audit_age_sec < -300:
        raise ValueError("PIT horizon audit timestamp is in the future")
    freshness_reasons: list[str] = []
    if requires_fresh and audit_observed < request_at:
        freshness_reasons.append("audit_predates_approval_window")
    if (
        requires_fresh
        and observed >= request_at
        and audit_age_sec > max_audit_age_sec
    ):
        freshness_reasons.append("audit_age_exceeds_limit")
    if require_current_ledger and audit_ledger_sha != current_ledger_sha:
        freshness_reasons.append("quality_ledger_hash_changed")

    if observed > hard_deadline:
        status = "EXPIRED"
        approval_status = "EXPIRED"
        freshness_status = "NOT_ACTIONABLE"
    elif observed >= request_at:
        if freshness_reasons:
            status = "REFRESH_REQUIRED"
            approval_status = "BLOCKED_STALE_HORIZON"
            freshness_status = "STALE"
        else:
            status = "READY_FOR_APPROVAL"
            approval_status = "DUE"
            freshness_status = "FRESH"
    else:
        status = "READY_FOR_APPROVAL"
        approval_status = "NOT_DUE"
        freshness_status = (
            "REFRESH_REQUIRED_AT_APPROVAL_WINDOW"
            if requires_fresh
            else "NOT_REQUIRED"
        )
    return {
        "status": status,
        "approval_request_status": approval_status,
        "approval_request_not_before_local": request_at.isoformat(),
        "campaign_start_local": starts_at.isoformat(),
        "hard_deadline_local": hard_deadline.isoformat(),
        "plan_path": str(plan_path),
        "plan_file_sha256": expected_plan_sha,
        "plan_hash": expected_plan_hash,
        "horizon_audit_path": str(audit_path),
        "horizon_audit_sha256": expected_audit_sha,
        "source_plan_hash": source_plan_hash,
        "nights": nights,
        "segment_duration_sec": int(
            candidate.get("segment_duration_sec") or 0
        ),
        "requires_fresh_horizon_audit_before_approval": requires_fresh,
        "horizon_freshness": {
            "status": freshness_status,
            "audit_observed_at": audit_observed.isoformat(),
            "audit_age_sec": max(0, math.ceil(audit_age_sec)),
            "max_age_sec": max_audit_age_sec,
            "must_not_predate_approval_window": require_post_window_audit,
            "must_match_current_quality_ledger": require_current_ledger,
            "audit_quality_ledger_sha256": audit_ledger_sha,
            "current_quality_ledger_sha256": current_ledger_sha,
            "reasons": freshness_reasons,
        },
        "schedule_approved": False,
        "automatic_launch_allowed": False,
        "approval_phrase": (
            str(plan.get("approval_phrase") or "")
            if approval_status == "DUE" and freshness_status == "FRESH"
            else ""
        ),
    }


def evaluate_autopilot_state(
    *,
    policy: dict[str, Any],
    policy_hash: str,
    gate: dict[str, Any],
    usage: dict[str, Any],
    prior_state: dict[str, Any] | None,
    observed_at_utc: str,
    schedule_window: dict[str, Any] | None = None,
    campaign_window: dict[str, Any] | None = None,
    productive_fallback: dict[str, Any] | None = None,
    research_fallback: dict[str, Any] | None = None,
    pit_schedule_extension: dict[str, Any] | None = None,
    long_campaign_approval: dict[str, Any] | None = None,
    dense_ws_postrun: dict[str, Any] | None = None,
    current_sprint_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage_decision = str(usage.get("decision", "PAUSE_USAGE_TELEMETRY_UNAVAILABLE"))
    gate_status = str(gate.get("gate_status") or gate.get("status") or "UNKNOWN")
    prior_status = str((prior_state or {}).get("status") or "")
    resumed_after_limit = False
    transitioned_to_pause = False
    run_approval_notification_required = False
    critical_checkpoint_notification_required = False
    standing_research_authorized = False
    standing_research_scope_binding_valid = False
    dense_ws_postrun_state = (
        dense_ws_postrun
        if isinstance(dense_ws_postrun, dict)
        else _dense_ws_postrun_base(status="NOT_APPLICABLE")
    )
    current_readiness = (
        current_sprint_readiness
        if isinstance(current_sprint_readiness, dict)
        else None
    )
    current_readiness_status = str((current_readiness or {}).get("status") or "")
    superseded_policy_candidates: dict[str, Any] | None = None
    effective_long_campaign_candidate = (
        policy.get("next_long_campaign")
        if isinstance(policy.get("next_long_campaign"), dict)
        else None
    )
    effective_pit_schedule_extension = pit_schedule_extension
    if current_readiness_status == "READY":
        superseded_policy_candidates = {
            "long_campaign": effective_long_campaign_candidate,
            "pit_schedule_extension": pit_schedule_extension,
            "long_campaign_approval": long_campaign_approval,
            "dense_ws_postrun_disposition": dense_ws_postrun_state,
        }
        effective_long_campaign_candidate = current_readiness.get(
            "long_campaign_candidate"
        )
        effective_pit_schedule_extension = current_readiness.get(
            "pit_schedule_extension_candidate"
        )
        long_campaign_approval = None
        dense_ws_postrun_state = _dense_ws_postrun_base(
            status="NOT_APPLICABLE_CURRENT_SPRINT_READINESS"
        )
        dense_ws_postrun_state["reason"] = (
            "legacy_dense_policy_superseded_by_current_sprint_readiness"
        )
        dense_ws_postrun_state["execution_authorized"] = False

    if usage_decision in LIMIT_PAUSE_DECISIONS:
        status = (
            "PAUSED_WEEKLY_LIMIT"
            if usage_decision == "PAUSE_WEEKLY_LIMIT"
            else "PAUSED_USAGE_TELEMETRY"
        )
        decision = usage_decision
        stop_new_actions = True
        allow_running_writer_to_finish = gate_status == "RUNNING"
        action_due = False
        next_action = "wait_for_weekly_limit_reset"
        transitioned_to_pause = prior_status != status
    elif gate_status == "RUNNING":
        status = "RUNNING_MONITOR_ONLY"
        decision = "MONITOR_ACTIVE_RUN"
        stop_new_actions = True
        allow_running_writer_to_finish = True
        action_due = False
        next_action = "status_eta_only"
        resumed_after_limit = prior_status.startswith("PAUSED_")
    elif gate_status == "STOPPED_INCOMPLETE":
        recovery = policy.get("recovery")
        if not isinstance(recovery, dict):
            recovery = {}
        same_run_allowed = bool(recovery.get("same_immutable_run_auto_recovery"))
        has_resume_command = bool(gate.get("resume_command"))
        status = "RECOVERY_PREFLIGHT"
        decision = (
            "SAFE_RECOVERY_PREFLIGHT_REQUIRED"
            if same_run_allowed and has_resume_command
            else "CRITICAL_STOP_INCOMPLETE"
        )
        stop_new_actions = True
        allow_running_writer_to_finish = False
        action_due = False
        next_action = (
            "verify_dead_pids_hashes_deadline_and_append_safety"
            if decision == "SAFE_RECOVERY_PREFLIGHT_REQUIRED"
            else "notify_incomplete_run"
        )
        resumed_after_limit = prior_status.startswith("PAUSED_")
    elif gate_status == "READY_FOR_POSTPROCESS":
        allow_running_writer_to_finish = False
        schedule_status = str((schedule_window or {}).get("status") or "")
        campaign_status = str((campaign_window or {}).get("status") or "")
        run_policy = policy.get("run_policy")
        if not isinstance(run_policy, dict):
            run_policy = {}
        per_campaign_approval = bool(
            run_policy.get(
                "long_run_requires_explicit_per_campaign_approval"
            )
        )
        pit_schedule = policy.get("current_pit_schedule")
        if not isinstance(pit_schedule, dict):
            pit_schedule = {}
        short_segment_limit_sec = int(
            run_policy.get("preapproved_short_segment_max_runtime_sec")
            or 1_800
        )
        schedule_duration_sec = int(
            (schedule_window or {}).get("duration_sec") or 0
        )
        preapproved_short_segment = bool(
            pit_schedule.get("all_listed_segments_are_preapproved")
            and not pit_schedule.get("per_segment_launch_approval_required")
            and pit_schedule.get("automatic_launch_allowed")
            and schedule_duration_sec > 0
            and schedule_duration_sec <= short_segment_limit_sec
        )
        long_campaign_candidate = effective_long_campaign_candidate
        if not isinstance(long_campaign_candidate, dict):
            long_campaign_candidate = {}
        long_candidate_ready = bool(
            long_campaign_candidate.get("status") == "READY_FOR_APPROVAL"
            and long_campaign_candidate.get("campaign_id")
            and long_campaign_candidate.get("plan_path")
            and len(str(long_campaign_candidate.get("plan_hash") or "")) == 64
            and int(long_campaign_candidate.get("max_runtime_sec") or 0)
            > short_segment_limit_sec
        )
        long_approval_status = str(
            (long_campaign_approval or {}).get("status") or "NOT_APPROVED"
        )
        long_approval_window_status = str(
            (long_campaign_approval or {}).get("launch_window_status") or ""
        )
        active_dense_gate_data_quality_ready = bool(
            str(gate.get("run_id") or "")
            == str(long_campaign_candidate.get("campaign_id") or "")
            and str(gate.get("run_type") or "") == "dense_ws_campaign"
            and gate.get("completed") is True
            and gate.get("final") is True
            and str(gate.get("manifest_path") or "").strip()
            and str(long_campaign_candidate.get("plan_path") or "").strip()
            and len(str(long_campaign_candidate.get("plan_hash") or "")) == 64
        )
        if current_readiness_status == "READY":
            pass
        elif isinstance(dense_ws_postrun, dict):
            dense_ws_postrun_state = dense_ws_postrun
        elif active_dense_gate_data_quality_ready:
            dense_ws_postrun_state = _dense_ws_postrun_base(
                status="QUALITY_MISSING",
                campaign_id=str(long_campaign_candidate.get("campaign_id") or ""),
                plan_hash=str(long_campaign_candidate.get("plan_hash") or ""),
            )
        else:
            dense_ws_postrun_state = _dense_ws_postrun_base(
                status="NOT_APPLICABLE"
            )
        deferred_dense_manifest_ready = bool(
            dense_ws_postrun_state.get("completion_evidence_mode")
            == "IMMUTABLE_COMPLETED_CAMPAIGN_MANIFEST_AFTER_PIT"
            and dense_ws_postrun_state.get("campaign_id")
            == long_campaign_candidate.get("campaign_id")
            and dense_ws_postrun_state.get("plan_hash")
            == long_campaign_candidate.get("plan_hash")
            and len(
                str(dense_ws_postrun_state.get("campaign_manifest_sha256") or "")
            )
            == 64
        )
        long_campaign_data_quality_ready = bool(
            active_dense_gate_data_quality_ready or deferred_dense_manifest_ready
        )
        dense_ws_postrun_status = str(
            dense_ws_postrun_state.get("status") or "NOT_APPLICABLE"
        )
        prior_dense_ws_postrun = (
            (prior_state or {}).get("dense_ws_postrun_disposition") or {}
        )
        dense_ws_postrun_changed = bool(
            str(prior_dense_ws_postrun.get("status") or "")
            != dense_ws_postrun_status
            or str(prior_dense_ws_postrun.get("campaign_id") or "")
            != str(dense_ws_postrun_state.get("campaign_id") or "")
            or str(prior_dense_ws_postrun.get("deterministic_result_hash") or "")
            != str(dense_ws_postrun_state.get("deterministic_result_hash") or "")
            or str(prior_dense_ws_postrun.get("reason") or "")
            != str(dense_ws_postrun_state.get("reason") or "")
            or str(prior_dense_ws_postrun.get("completion_evidence_mode") or "")
            != str(dense_ws_postrun_state.get("completion_evidence_mode") or "")
            or str(prior_dense_ws_postrun.get("campaign_manifest_sha256") or "")
            != str(dense_ws_postrun_state.get("campaign_manifest_sha256") or "")
        )
        if current_readiness_status == "INVALID":
            status = "CRITICAL_STOP"
            decision = "CRITICAL_STOP_CURRENT_SPRINT_READINESS_INTEGRITY"
            stop_new_actions = True
            critical_checkpoint_notification_required = (
                str((prior_state or {}).get("decision") or "") != decision
                or str(
                    ((prior_state or {}).get("current_sprint_readiness") or {}).get(
                        "error"
                    )
                    or ""
                )
                != str((current_readiness or {}).get("error") or "")
            )
            action_due = critical_checkpoint_notification_required
            next_action = "notify_current_sprint_readiness_integrity_conflict"
        elif current_readiness_status == "MISSING":
            status = "CRITICAL_STOP"
            decision = "CRITICAL_STOP_CURRENT_SPRINT_READINESS_MISSING"
            stop_new_actions = True
            critical_checkpoint_notification_required = (
                str((prior_state or {}).get("decision") or "") != decision
            )
            action_due = critical_checkpoint_notification_required
            next_action = "notify_current_sprint_readiness_missing"
        elif current_readiness_status == "REFRESH_REQUIRED":
            status = "ACTIVE"
            decision = "REFRESH_CURRENT_SPRINT_READINESS"
            stop_new_actions = True
            action_due = True
            next_action = "rebuild_current_sprint_readiness_without_execution"
        elif current_readiness_status == "READY":
            status = "ACTIVE"
            readiness_source_status = str(
                current_readiness.get("source_status") or ""
            )
            readiness_execution_authorized = (
                current_readiness.get("execution_authorized") is True
            )
            standing_auto_continue = False
            standing_next_action = "continue_next_bounded_same_scope_public_research"
            if (
                readiness_source_status
                == (
                    "REQUEST_PLAN_DISCOVERY_V3_RUNTIME_FROZEN_WITH_"
                    "EXACT_EXECUTION_APPROVAL"
                )
                and readiness_execution_authorized
            ):
                decision = (
                    "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V3"
                )
            elif (
                readiness_source_status
                == (
                    "REQUEST_PLAN_DISCOVERY_V3_RUNTIME_FROZEN_AWAIT_"
                    "EXACT_EXECUTION_APPROVAL"
                )
                and not readiness_execution_authorized
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="public_request_plan_discovery",
                )
                if standing_research_scope_binding_valid:
                    decision = "CONTINUE_STANDING_PUBLIC_RESEARCH"
                    standing_research_authorized = True
                    standing_auto_continue = True
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_"
                        "DISCOVERY_V3_EXECUTION_APPROVAL"
                    )
            elif (
                readiness_source_status
                == "REQUEST_PLAN_DISCOVERY_V4_RUNTIME_FROZEN_STANDING_PUBLIC_RESEARCH"
                and not readiness_execution_authorized
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="public_request_plan_discovery",
                )
                if standing_research_scope_binding_valid:
                    decision = (
                        "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4"
                    )
                    standing_research_authorized = True
                    standing_auto_continue = True
                    standing_next_action = (
                        "run_slow_liquidity_identity_request_plan_discovery_v4_visible"
                    )
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_"
                        "DISCOVERY_V4_EXECUTION_APPROVAL"
                    )
            elif (
                readiness_source_status
                == "TOPOLOGY_RUNTIME_FROZEN_WITH_EXACT_EXECUTION_APPROVAL"
                and readiness_execution_authorized
            ):
                decision = (
                    "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                    "TOPOLOGY_DISCOVERY"
                )
            elif (
                readiness_source_status
                == "TOPOLOGY_V4_RUNTIME_FROZEN_WITH_EXACT_EXECUTION_APPROVAL"
                and readiness_execution_authorized
            ):
                decision = (
                    "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                    "TOPOLOGY_DISCOVERY_V4"
                )
            elif (
                readiness_source_status
                == "TOPOLOGY_V3_RUNTIME_FROZEN_WITH_EXACT_EXECUTION_APPROVAL"
                and readiness_execution_authorized
            ):
                decision = (
                    "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                    "TOPOLOGY_DISCOVERY_V3"
                )
            elif (
                readiness_source_status
                == (
                    "TOPOLOGY_V2_LAUNCHER_REJECTED_AWAIT_V3_OFFLINE_"
                    "REFREEZE_APPROVAL"
                )
                and not readiness_execution_authorized
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="immutable_manifest_refreeze",
                )
                if standing_research_scope_binding_valid:
                    decision = "CONTINUE_STANDING_PUBLIC_RESEARCH"
                    standing_research_authorized = True
                    standing_auto_continue = True
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                        "TOPOLOGY_V3_OFFLINE_REFREEZE_APPROVAL"
                    )
            elif (
                readiness_source_status
                == "TOPOLOGY_V4_RUNTIME_FROZEN_AWAIT_EXACT_EXECUTION_APPROVAL"
                and not readiness_execution_authorized
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="public_topology_discovery",
                )
                if standing_research_scope_binding_valid:
                    decision = "CONTINUE_STANDING_PUBLIC_RESEARCH"
                    standing_research_authorized = True
                    standing_auto_continue = True
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                        "TOPOLOGY_V4_EXECUTION_APPROVAL"
                    )
            elif (
                readiness_source_status
                == "TOPOLOGY_V3_RUNTIME_FROZEN_AWAIT_EXACT_EXECUTION_APPROVAL"
                and not readiness_execution_authorized
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="public_topology_discovery",
                )
                if standing_research_scope_binding_valid:
                    decision = "CONTINUE_STANDING_PUBLIC_RESEARCH"
                    standing_research_authorized = True
                    standing_auto_continue = True
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                        "TOPOLOGY_V3_EXECUTION_APPROVAL"
                    )
            elif (
                readiness_source_status
                == "TOPOLOGY_V2_RUNTIME_FROZEN_AWAIT_EXACT_EXECUTION_APPROVAL"
                and not readiness_execution_authorized
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="public_topology_discovery",
                )
                if standing_research_scope_binding_valid:
                    decision = "CONTINUE_STANDING_PUBLIC_RESEARCH"
                    standing_research_authorized = True
                    standing_auto_continue = True
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                        "TOPOLOGY_V2_EXECUTION_APPROVAL"
                    )
            elif (
                readiness_source_status
                == "IDENTITY_RUNTIME_FROZEN_WITH_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
                and readiness_execution_authorized
            ):
                decision = "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION"
            elif (
                readiness_source_status
                == "IDENTITY_RUNTIME_FROZEN_AWAIT_EXACT_CODE_BOUND_EXECUTION_APPROVAL"
            ):
                standing_research_scope_binding_valid = _standing_research_scope_matches(
                    policy,
                    current_readiness=current_readiness,
                    required_action="public_identity_discovery",
                )
                if standing_research_scope_binding_valid:
                    decision = "CONTINUE_STANDING_PUBLIC_RESEARCH"
                    standing_research_authorized = True
                    standing_auto_continue = True
                else:
                    decision = (
                        "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_"
                        "EXECUTION_APPROVAL"
                    )
            else:
                decision = "AWAIT_EXACT_ONE_WEEK_EDGE_SPRINT_APPROVAL_CHECKPOINT"
            stop_new_actions = False
            action_due = decision in {
                "RUN_SLOW_LIQUIDITY_OFFICIAL_IDENTITY_VERIFICATION",
                "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY",
                "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY_V3",
                "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY_V4",
                "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V3",
                "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4",
                "CONTINUE_STANDING_PUBLIC_RESEARCH",
                "AWAIT_EXACT_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V3_EXECUTION_APPROVAL",
                "AWAIT_EXACT_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4_EXECUTION_APPROVAL",
                "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_V3_OFFLINE_REFREEZE_APPROVAL",
                "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_V4_EXECUTION_APPROVAL",
                "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_V3_EXECUTION_APPROVAL",
                "AWAIT_EXACT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_V2_EXECUTION_APPROVAL",
            }
            if standing_auto_continue:
                next_action = standing_next_action
            else:
                next_action = str(
                    current_readiness.get("next_safe_action")
                    or "await_one_exact_approval_checkpoint"
                )
            if decision in {
                "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY",
                "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY_V3",
                "RUN_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_TOPOLOGY_DISCOVERY_V4",
            }:
                topology = current_readiness.get("official_currentness_topology") or {}
                topology_run_id = str(topology.get("run_id") or "")
                launch_record_path = (
                    Path(__file__).resolve().parents[2]
                    / "docs"
                    / "agent-log"
                    / "run-gates"
                    / f"{topology_run_id}.launch.json"
                )
                if topology_run_id and launch_record_path.is_file():
                    topology_launch = _load_json(launch_record_path)
                    topology_launch_status = str(topology_launch.get("status") or "")
                    if topology_launch_status == "STOPPED_INCOMPLETE":
                        decision = (
                            "TERMINAL_REJECT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                            "TOPOLOGY_STOPPED_INCOMPLETE_NO_RETRY"
                        )
                        stop_new_actions = True
                        action_due = True
                        critical_checkpoint_notification_required = True
                        next_action = "do_not_retry_without_new_exact_approval"
                    elif topology_launch_status == "COMPLETE":
                        decision = (
                            "TERMINAL_ACCEPT_SLOW_LIQUIDITY_OFFICIAL_CURRENTNESS_"
                            "TOPOLOGY_COMPLETE"
                        )
                        stop_new_actions = True
                        action_due = True
                        critical_checkpoint_notification_required = True
                        next_action = "await_separate_official_identity_approval"
            if decision == "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V3":
                discovery = (
                    current_readiness.get("official_identity_request_plan_discovery")
                    or {}
                )
                discovery_run_id = str(discovery.get("run_id") or "")
                launch_record_path = (
                    Path(__file__).resolve().parents[2]
                    / "docs"
                    / "agent-log"
                    / "run-gates"
                    / f"{discovery_run_id}.launch.json"
                )
                if discovery_run_id and launch_record_path.is_file():
                    launch = _load_json(launch_record_path)
                    launch_status = str(launch.get("status") or "")
                    if launch_status == "STOPPED_INCOMPLETE":
                        decision = (
                            "TERMINAL_REJECT_SLOW_LIQUIDITY_IDENTITY_REQUEST_"
                            "PLAN_DISCOVERY_V3_STOPPED_INCOMPLETE_NO_RETRY"
                        )
                        stop_new_actions = True
                        action_due = True
                        critical_checkpoint_notification_required = True
                        next_action = "do_not_retry_without_new_exact_approval"
                    elif launch_status == "COMPLETE":
                        decision = (
                            "TERMINAL_ACCEPT_SLOW_LIQUIDITY_IDENTITY_REQUEST_"
                            "PLAN_DISCOVERY_V3_COMPLETE"
                        )
                        stop_new_actions = True
                        action_due = True
                        critical_checkpoint_notification_required = True
                        next_action = "await_separate_exact_official_identity_approval"
            if decision == "RUN_SLOW_LIQUIDITY_IDENTITY_REQUEST_PLAN_DISCOVERY_V4":
                discovery = (
                    current_readiness.get("official_identity_request_plan_discovery_v4")
                    or {}
                )
                discovery_run_id = str(discovery.get("run_id") or "")
                launch_record_path = (
                    Path(__file__).resolve().parents[2]
                    / "docs"
                    / "agent-log"
                    / "run-gates"
                    / f"{discovery_run_id}.launch.json"
                )
                if discovery_run_id and launch_record_path.is_file():
                    launch = _load_json(launch_record_path)
                    launch_status = str(launch.get("status") or "")
                    if launch_status == "STOPPED_INCOMPLETE":
                        decision = (
                            "TERMINAL_REJECT_SLOW_LIQUIDITY_IDENTITY_REQUEST_"
                            "PLAN_DISCOVERY_V4_STOPPED_INCOMPLETE_NO_RETRY"
                        )
                        standing_research_authorized = False
                        standing_research_scope_binding_valid = False
                        standing_auto_continue = False
                        stop_new_actions = True
                        action_due = True
                        critical_checkpoint_notification_required = True
                        next_action = "do_not_retry_without_new_exact_approval"
                    elif launch_status == "COMPLETE":
                        decision = (
                            "TERMINAL_ACCEPT_SLOW_LIQUIDITY_IDENTITY_REQUEST_"
                            "PLAN_DISCOVERY_V4_COMPLETE"
                        )
                        standing_research_authorized = False
                        standing_research_scope_binding_valid = False
                        standing_auto_continue = False
                        stop_new_actions = True
                        action_due = True
                        critical_checkpoint_notification_required = True
                        next_action = "continue_same_scope_public_research"
        elif schedule_status == "INVALID" or campaign_status == "INVALID":
            status = "CRITICAL_STOP"
            decision = "CRITICAL_STOP_INVALID_SCHEDULE"
            stop_new_actions = True
            action_due = False
            next_action = "notify_invalid_schedule_or_run_window_policy"
        elif schedule_status == "STAGE_TARGET_OVERSHOOT":
            status = "CRITICAL_STOP"
            decision = "CRITICAL_STOP_PIT_STAGE_TARGET_OVERSHOOT"
            stop_new_actions = True
            action_due = False
            next_action = "notify_pit_stage_target_overshoot"
        elif schedule_status == "STAGE_TARGET_REACHED":
            status = "ACTIVE"
            stop_new_actions = False
            stage_name = str(
                (schedule_window or {}).get("collection_stage") or ""
            )
            gate_decision = str(gate.get("next_goal_decision") or "")
            if stage_name == "train_accrual" and gate_decision in {
                "PIT_OOS_ACCRUAL_PLAN_READY_FOR_APPROVAL",
                "PIT_TRAIN_INFEASIBLE_ON_CURRENT_DATA",
            }:
                decision = gate_decision
                prior_gate_run_id = str(
                    ((prior_state or {}).get("gate") or {}).get("run_id") or ""
                )
                critical_checkpoint_notification_required = (
                    str((prior_state or {}).get("decision") or "")
                    != decision
                    or prior_gate_run_id != str(gate.get("run_id") or "")
                )
                action_due = critical_checkpoint_notification_required
                next_action = (
                    "request_exact_pit_oos_schedule_approval"
                    if gate_decision
                    == "PIT_OOS_ACCRUAL_PLAN_READY_FOR_APPROVAL"
                    else "review_pit_train_infeasible_branch_closure"
                )
            elif stage_name == "train_accrual":
                decision = "RUN_PIT_TRAIN_FEASIBILITY"
                action_due = True
                next_action = (
                    "run_visible_deterministic_train_only_feasibility"
                )
            else:
                decision = "PIT_COLLECTION_STAGE_TARGET_REACHED"
                action_due = True
                next_action = str(
                    gate.get("next_step_after_ready")
                    or gate.get("next_allowed_action")
                    or "derive_next_stage_action"
                )
        elif schedule_status == "DUE" and preapproved_short_segment:
            status = "ACTIVE"
            decision = "START_PREAPPROVED_SHORT_SEGMENT_VISIBLE"
            stop_new_actions = False
            action_due = True
            next_action = (
                "start_preapproved_short_segment_"
                f"{str((schedule_window or {}).get('run_id') or 'due_run')}"
            )
        elif schedule_status == "DUE" and per_campaign_approval:
            status = "ACTIVE"
            decision = "AWAIT_EXPLICIT_LONG_CAMPAIGN_APPROVAL"
            stop_new_actions = False
            current_window_id = str(
                (campaign_window or {}).get("window_id") or ""
            )
            prior_window_id = str(
                ((prior_state or {}).get("campaign_window") or {}).get(
                    "window_id"
                )
                or ""
            )
            run_approval_notification_required = (
                str((prior_state or {}).get("decision") or "") != decision
                or prior_window_id != current_window_id
            )
            action_due = run_approval_notification_required
            next_action = (
                "prepare_and_request_exact_approval_for_"
                f"{str((schedule_window or {}).get('run_id') or 'due_run')}"
            )
        elif (
            deferred_dense_manifest_ready
            and dense_ws_postrun_status
            == "AWAITING_EXACT_MANIFEST_BOUND_POSTRUN_APPROVAL"
        ):
            status = "ACTIVE"
            decision = "AWAIT_EXACT_MANIFEST_BOUND_POSTRUN_APPROVAL"
            stop_new_actions = False
            critical_checkpoint_notification_required = dense_ws_postrun_changed
            action_due = critical_checkpoint_notification_required
            next_action = "request_exact_manifest_bound_dense_ws_postrun_approval"
        elif (
            deferred_dense_manifest_ready
            and dense_ws_postrun_status == "POSTRUN_WINDOW_NOT_OPEN"
        ):
            status = "ACTIVE"
            decision = "WAIT_FOR_DENSE_WS_POSTRUN_WINDOW"
            stop_new_actions = False
            action_due = False
            next_action = "wait_for_frozen_dense_ws_postrun_not_before"
        elif (
            deferred_dense_manifest_ready
            and dense_ws_postrun_status == "POSTRUN_WINDOW_EXPIRED"
        ):
            status = "ACTIVE"
            decision = "USER_REVIEW_REQUIRED_DENSE_WS_POSTRUN_WINDOW_EXPIRED"
            stop_new_actions = False
            critical_checkpoint_notification_required = dense_ws_postrun_changed
            action_due = critical_checkpoint_notification_required
            next_action = "request_new_exact_dense_ws_postrun_window_refreeze"
        elif long_campaign_data_quality_ready and dense_ws_postrun_status in {
            "RUNNING",
            "MATERIALIZATION_BOUND_PLAN_RUNNING",
        }:
            status = "RUNNING_MONITOR_ONLY"
            decision = "MONITOR_DENSE_WS_POSTRUN"
            stop_new_actions = True
            action_due = False
            next_action = "status_eta_only_dense_ws_postrun"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status == "QUALITY_MISSING"
        ):
            status = "ACTIVE"
            decision = "RUN_DENSE_WS_CAMPAIGN_DATA_QUALITY"
            stop_new_actions = False
            action_due = True
            next_action = "run_dense_ws_postrun_visible"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status == "QUALITY_ACCEPTED"
        ):
            status = "ACTIVE"
            decision = "RUN_DENSE_WS_CAUSAL_MATERIALIZATION"
            stop_new_actions = False
            action_due = True
            next_action = "run_dense_ws_postrun_visible"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status == "MATERIALIZATION_ACCEPTED"
        ):
            evaluator_freeze = policy.get("dense_ws_signal_evaluator_freeze")
            if not isinstance(evaluator_freeze, dict):
                evaluator_freeze = {}
            status = "ACTIVE"
            stop_new_actions = False
            if (
                evaluator_freeze.get("status") == "FROZEN_NOT_AUTHORIZED"
                and evaluator_freeze.get("executable") is False
                and evaluator_freeze.get("evaluation_authorized") is False
                and len(str(evaluator_freeze.get("plan_hash") or "")) == 64
            ):
                decision = "BUILD_DENSE_WS_MATERIALIZATION_BOUND_EVALUATOR_PLANONLY"
                action_due = True
                next_action = (
                    "run_dense_ws_materialization_bound_planonly_visible"
                )
            else:
                decision = "USER_REVIEW_REQUIRED_SIGNAL_AND_EVALUATOR_CONTRACT"
                critical_checkpoint_notification_required = dense_ws_postrun_changed
                action_due = critical_checkpoint_notification_required
                next_action = "request_exact_signal_and_evaluator_contract_review"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status == "MATERIALIZATION_BOUND_PLANONLY_READY"
        ):
            status = "ACTIVE"
            decision = "USER_REVIEW_REQUIRED_EXACT_DENSE_WS_EVALUATOR_APPROVAL"
            stop_new_actions = False
            critical_checkpoint_notification_required = dense_ws_postrun_changed
            action_due = critical_checkpoint_notification_required
            next_action = "request_exact_hash_bound_evaluator_approval"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status
            in {"QUALITY_REJECTED", "MATERIALIZATION_REJECTED"}
        ):
            status = "ACTIVE"
            decision = "DENSE_WS_DATA_REJECTED_USER_REVIEW_REQUIRED"
            stop_new_actions = False
            critical_checkpoint_notification_required = dense_ws_postrun_changed
            action_due = critical_checkpoint_notification_required
            next_action = "notify_dense_ws_data_rejection_and_stop_dense_branch"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status == "STOPPED_INCOMPLETE"
        ):
            status = "ACTIVE"
            decision = "USER_REVIEW_REQUIRED_DENSE_WS_POSTRUN_RECOVERY"
            stop_new_actions = False
            critical_checkpoint_notification_required = dense_ws_postrun_changed
            action_due = critical_checkpoint_notification_required
            next_action = "request_exact_dense_ws_postrun_recovery_approval"
        elif (
            long_campaign_data_quality_ready
            and dense_ws_postrun_status == "INTEGRITY_CONFLICT"
        ):
            status = "ACTIVE"
            decision = "USER_REVIEW_REQUIRED_DENSE_WS_POSTRUN_INTEGRITY"
            stop_new_actions = False
            critical_checkpoint_notification_required = dense_ws_postrun_changed
            action_due = critical_checkpoint_notification_required
            next_action = "notify_dense_ws_postrun_integrity_conflict"
        elif (
            long_candidate_ready
            and long_approval_status == "APPROVED"
            and long_approval_window_status == "DUE"
        ):
            status = "ACTIVE"
            decision = "START_APPROVED_LONG_CAMPAIGN_VISIBLE"
            stop_new_actions = False
            action_due = True
            next_action = (
                "start_approved_long_campaign_"
                f"{str(long_campaign_candidate.get('campaign_id') or '')}"
            )
        elif (
            long_candidate_ready
            and long_approval_window_status == "EXPIRED"
        ):
            status = "ACTIVE"
            decision = "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_WINDOW_EXPIRED"
            stop_new_actions = False
            critical_checkpoint_notification_required = (
                str((prior_state or {}).get("decision") or "") != decision
            )
            action_due = critical_checkpoint_notification_required
            next_action = "prepare_new_exact_long_campaign_window_without_resume"
        elif long_candidate_ready and long_approval_status == "INVALID":
            status = "ACTIVE"
            decision = "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_APPROVAL_INTEGRITY"
            stop_new_actions = False
            critical_checkpoint_notification_required = (
                str((prior_state or {}).get("decision") or "") != decision
            )
            action_due = critical_checkpoint_notification_required
            next_action = "notify_long_campaign_approval_integrity_conflict"
        elif schedule_status in {
            "WAITING",
            "NO_PENDING_SEGMENT",
            "PAUSED",
            "SUPERSEDED",
        } or (
            not schedule_status
            and bool(policy.get("continuous_production_policy"))
        ):
            fallback_status = str((productive_fallback or {}).get("status") or "")
            fallback_task = (productive_fallback or {}).get("task")
            research_status = str((research_fallback or {}).get("status") or "")
            research_task = (research_fallback or {}).get("task")
            research_checkpoint = (research_fallback or {}).get(
                "critical_checkpoint"
            )
            extension_status = str(
                (effective_pit_schedule_extension or {}).get("status") or ""
            )
            extension_approval_status = str(
                (effective_pit_schedule_extension or {}).get(
                    "approval_request_status"
                )
                or ""
            )
            if research_status == "USER_REVIEW_REQUIRED" and isinstance(
                research_checkpoint, dict
            ):
                status = "CRITICAL_STOP"
                decision = "USER_REVIEW_REQUIRED"
                stop_new_actions = True
                action_due = False
                next_action = str(
                    research_checkpoint.get("requested_action") or ""
                )
            elif fallback_status == "READY" and isinstance(fallback_task, dict):
                status = "ACTIVE"
                decision = "CONTINUE_PRODUCTIVE_FALLBACK"
                stop_new_actions = False
                action_due = True
                next_action = str(fallback_task.get("id") or "")
            elif research_status in {"READY", "IN_PROGRESS"} and isinstance(
                research_task, dict
            ):
                status = "ACTIVE"
                decision = "CONTINUE_BOUNDED_RESEARCH"
                stop_new_actions = False
                action_due = True
                next_action = str(research_task.get("id") or "")
            elif (
                extension_status == "REFRESH_REQUIRED"
                and extension_approval_status == "BLOCKED_STALE_HORIZON"
            ):
                status = "ACTIVE"
                decision = "REFRESH_PIT_SCHEDULE_EXTENSION_HORIZON"
                stop_new_actions = False
                action_due = True
                source_hash = str(
                    (effective_pit_schedule_extension or {}).get(
                        "source_plan_hash"
                    )
                    or ""
                )
                next_action = (
                    "derive_fresh_hash_bound_pit_schedule_extension_"
                    f"{source_hash}"
                )
            elif (
                extension_status == "READY_FOR_APPROVAL"
                and extension_approval_status == "DUE"
            ):
                status = "ACTIVE"
                decision = "AWAIT_EXPLICIT_PIT_SCHEDULE_EXTENSION_APPROVAL"
                stop_new_actions = False
                extension_hash = str(
                    (effective_pit_schedule_extension or {}).get("plan_hash") or ""
                )
                prior_extension_hash = str(
                    (
                        (prior_state or {}).get(
                            "pit_schedule_extension_candidate"
                        )
                        or {}
                    ).get("plan_hash")
                    or ""
                )
                run_approval_notification_required = (
                    str((prior_state or {}).get("decision") or "")
                    != decision
                    or prior_extension_hash != extension_hash
                )
                action_due = run_approval_notification_required
                next_action = (
                    "request_exact_pit_schedule_extension_approval_"
                    f"{extension_hash}"
                )
            elif (
                long_candidate_ready
                and long_approval_status == "APPROVED"
                and long_approval_window_status == "WAITING"
            ):
                status = "ACTIVE"
                decision = "WAIT_APPROVED_LONG_CAMPAIGN_WINDOW"
                stop_new_actions = False
                action_due = False
                next_action = "continue_safe_offline_work_until_approved_window"
            elif (
                research_status
                == "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
            ):
                status = "ACTIVE"
                stop_new_actions = False
                approval_due = (
                    campaign_status == "OPEN"
                    or str(
                        (campaign_window or {}).get(
                            "approval_request_status"
                        )
                        or ""
                    )
                    == "DUE"
                )
                if str(long_campaign_candidate.get("status") or "").startswith(
                    "USER_REVIEW_REQUIRED"
                ):
                    decision = "USER_REVIEW_REQUIRED_LONG_CAMPAIGN_CONTRACT"
                    critical_checkpoint_notification_required = (
                        str((prior_state or {}).get("decision") or "")
                        != decision
                        or str(
                            ((prior_state or {}).get("long_campaign_candidate") or {}).get(
                                "candidate_contract_hash"
                            )
                            or ""
                        )
                        != str(
                            long_campaign_candidate.get(
                                "candidate_contract_hash"
                            )
                            or ""
                        )
                    )
                    action_due = critical_checkpoint_notification_required
                    next_action = str(
                        long_campaign_candidate.get("requested_action")
                        or "review_long_campaign_contract"
                    )
                elif (
                    per_campaign_approval
                    and approval_due
                    and long_candidate_ready
                ):
                    decision = "AWAIT_EXPLICIT_LONG_CAMPAIGN_APPROVAL"
                    current_window_id = str(
                        (campaign_window or {}).get("window_id")
                        or (campaign_window or {}).get("next_opens_at_local")
                        or ""
                    )
                    prior_window_id = str(
                        (
                            (prior_state or {}).get("campaign_window")
                            or {}
                        ).get("window_id")
                        or (
                            (prior_state or {}).get("campaign_window")
                            or {}
                        ).get("next_opens_at_local")
                        or ""
                    )
                    run_approval_notification_required = (
                        str((prior_state or {}).get("decision") or "")
                        != decision
                        or prior_window_id != current_window_id
                    )
                    action_due = run_approval_notification_required
                    pending_run_id = str(
                        long_campaign_candidate.get("campaign_id")
                    )
                    next_action = (
                        "prepare_and_request_exact_approval_for_"
                        f"{pending_run_id}"
                    )
                elif policy.get("continuous_production_policy"):
                    decision = "ACTIVE_NO_POSITIVE_RUN_CANDIDATE"
                    action_due = False
                    next_action = (
                        "prepare_next_long_campaign_planonly_without_start"
                    )
                else:
                    decision = "WAITING_SCHEDULE_WINDOW_NO_FALLBACK"
                    action_due = False
                    next_action = "wait_for_exact_pit_segment_due"
            elif fallback_status == "INVALID" or research_status == "INVALID":
                status = "CRITICAL_STOP"
                decision = "CRITICAL_STOP_INVALID_FALLBACK_QUEUE"
                stop_new_actions = True
                action_due = False
                next_action = "notify_invalid_fallback_queue"
            else:
                status = "ACTIVE"
                decision = "REFRESH_BOUNDED_RESEARCH_CATALOG"
                stop_new_actions = False
                action_due = True
                next_action = "derive_next_catalog_from_latest_readiness_audit"
        else:
            status = "ACTIVE"
            decision = "CONTINUE_NEXT_ALLOWED_ACTION"
            stop_new_actions = False
            action_due = True
            next_action = str(
                gate.get("next_step_after_ready")
                or gate.get("next_allowed_action")
                or "derive_next_allowed_action"
            )
        resumed_after_limit = prior_status.startswith("PAUSED_")
    else:
        status = "CRITICAL_STOP"
        decision = "CRITICAL_STOP_UNKNOWN_GATE"
        stop_new_actions = True
        allow_running_writer_to_finish = False
        action_due = False
        next_action = "notify_unknown_gate_state"

    return {
        "schema": "trading_mvp_autopilot_state_v1",
        "project": "trading_mvp",
        "status": status,
        "decision": decision,
        "observed_at_utc": observed_at_utc,
        "policy_id": policy.get("policy_id"),
        "policy_hash": policy_hash,
        "thread_id": policy.get("thread_id"),
        "stop_new_actions": stop_new_actions,
        "allow_running_writer_to_finish": allow_running_writer_to_finish,
        "action_due": action_due,
        "resumed_after_limit": resumed_after_limit,
        "transitioned_to_pause": transitioned_to_pause,
        "pause_notification_required": transitioned_to_pause,
        "run_approval_notification_required": (
            run_approval_notification_required
        ),
        "critical_checkpoint_notification_required": (
            critical_checkpoint_notification_required
        ),
        "standing_research_authorized": standing_research_authorized,
        "standing_research_scope_binding_valid": standing_research_scope_binding_valid,
        "next_action": next_action,
        "schedule_window": schedule_window,
        "campaign_window": campaign_window,
        "current_sprint_readiness": current_readiness,
        "superseded_policy_candidates": superseded_policy_candidates,
        "long_campaign_candidate": effective_long_campaign_candidate,
        "long_campaign_approval": long_campaign_approval,
        "dense_ws_postrun_disposition": dense_ws_postrun_state,
        "productive_fallback": productive_fallback,
        "research_fallback": research_fallback,
        "pit_schedule_extension_candidate": effective_pit_schedule_extension,
        "usage": usage,
        "gate": {
            "status": gate_status,
            "run_id": gate.get("run_id"),
            "next_goal_decision": gate.get("next_goal_decision"),
            "next_step_after_ready": gate.get("next_step_after_ready"),
            "manifest_path": gate.get("manifest_path"),
            "verdict": gate.get("verdict"),
            "deterministic_result_hash": gate.get(
                "feasibility_result_hash"
            ),
            "oos_schedule_path": gate.get("oos_schedule_path"),
            "oos_schedule_plan_hash": gate.get(
                "oos_schedule_plan_hash"
            ),
            "resume_command_present": bool(gate.get("resume_command")),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the trading_mvp autonomous execution guard."
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--current-readiness-pointer", type=Path)
    parser.add_argument("--global-writer-claim", type=Path)
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--min-remaining-percent", type=float, default=15.0)
    parser.add_argument("--stale-after-sec", type=int, default=108_000)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = _load_json(args.policy)
    gate = _load_json(args.gate)
    prior_state = _load_json(args.state) if args.state.exists() else None
    usage_raw = collect_weekly_usage(
        args.session_root,
        thread_id=args.thread_id,
        stale_after_sec=args.stale_after_sec,
    )
    usage = evaluate_usage_guard(
        usage_raw,
        min_remaining_percent=args.min_remaining_percent,
    )
    observed_at = _iso_now()
    if args.current_readiness_pointer is not None:
        current_pit_schedule = policy.get("current_pit_schedule")
        current_pit_pointer_value = (
            current_pit_schedule.get("pointer_path")
            if isinstance(current_pit_schedule, dict)
            else None
        )
        if not current_pit_pointer_value or args.global_writer_claim is None:
            current_sprint_readiness = {
                "status": "INVALID",
                "error": (
                    "current readiness requires the current PIT pointer and "
                    "global writer claim path"
                ),
            }
        else:
            try:
                current_sprint_readiness = resolve_current_sprint_readiness(
                    args.current_readiness_pointer,
                    gate_path=args.gate,
                    pit_pointer_path=Path(str(current_pit_pointer_value)),
                    writer_claim_path=args.global_writer_claim,
                )
            except CurrentSprintReadinessError as exc:
                current_sprint_readiness = {
                    "status": exc.status,
                    "error": str(exc),
                    "pointer_path": str(
                        args.current_readiness_pointer.expanduser().resolve()
                    ),
                    "execution_authorized": False,
                }
    else:
        current_sprint_readiness = None
    try:
        schedule_window = resolve_schedule_window(
            policy,
            observed_at_utc=observed_at,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        schedule_window = {
            "status": "INVALID",
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        campaign_window = resolve_continuous_production_window(
            policy,
            observed_at_utc=observed_at,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        campaign_window = {
            "status": "INVALID",
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        pit_schedule_extension = resolve_pit_schedule_extension(
            policy,
            observed_at_utc=observed_at,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        pit_schedule_extension = {
            "status": "INVALID",
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        long_campaign_approval = resolve_long_campaign_approval(
            policy,
            observed_at_utc=observed_at,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        long_campaign_approval = {
            "status": "INVALID",
            "launch_window_status": "INVALID",
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        dense_ws_postrun = resolve_dense_ws_postrun(
            policy,
            gate,
            usage=usage,
            observed_at_utc=observed_at,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        candidate = policy.get("next_long_campaign")
        if not isinstance(candidate, dict):
            candidate = {}
        dense_ws_postrun = _dense_ws_postrun_base(
            status="INTEGRITY_CONFLICT",
            campaign_id=str(candidate.get("campaign_id") or "") or None,
            plan_hash=str(candidate.get("plan_hash") or "") or None,
        )
        dense_ws_postrun["reason"] = f"{type(exc).__name__}: {exc}"
    try:
        queue = policy.get("productive_fallback_queue")
        ledger_path_value = (
            queue.get("ledger_path")
            if isinstance(queue, dict)
            else None
        )
        ledger_entries = (
            _load_jsonl(Path(str(ledger_path_value)).expanduser().resolve())
            if ledger_path_value
            else []
        )
        productive_fallback = resolve_productive_fallback(
            policy,
            ledger_entries=ledger_entries,
        )
        if ledger_path_value:
            productive_fallback["ledger_path"] = str(
                Path(str(ledger_path_value)).expanduser().resolve()
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        productive_fallback = {
            "status": "INVALID",
            "task": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        research_config = policy.get("bounded_research_backlog")
        research_path_value = (
            research_config.get("path")
            if isinstance(research_config, dict)
            else None
        )
        research_fallback = (
            next_research_task(
                Path(str(research_path_value)).expanduser().resolve()
            )
            if research_path_value
            else {"status": "NOT_CONFIGURED", "task": None}
        )
        if research_path_value:
            research_fallback = resolve_research_critical_checkpoint(
                Path(str(research_path_value)).expanduser().resolve(),
                research_fallback,
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        research_fallback = {
            "status": "INVALID",
            "task": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    result = evaluate_autopilot_state(
        policy=policy,
        policy_hash=_sha256(args.policy),
        gate=gate,
        usage=usage,
        prior_state=prior_state,
        observed_at_utc=observed_at,
        schedule_window=schedule_window,
        campaign_window=campaign_window,
        productive_fallback=productive_fallback,
        research_fallback=research_fallback,
        pit_schedule_extension=pit_schedule_extension,
        long_campaign_approval=long_campaign_approval,
        dense_ws_postrun=dense_ws_postrun,
        current_sprint_readiness=current_sprint_readiness,
    )
    _write_json_atomic(args.state, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
