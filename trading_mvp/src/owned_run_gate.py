from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


POINTER_SCHEMA = "active_run_pointer_v1"
LAUNCH_SCHEMA = "active_run_launch_record_v1"
IMMUTABLE_GOVERNANCE_FIELDS = ("approved_night_schedule",)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _safe_run_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    if not safe:
        raise ValueError("run_id must not be blank")
    return safe


def publish_owned_run_gate(
    gate_path: str | Path,
    payload: dict[str, Any],
    *,
    run_type: str,
) -> dict[str, str]:
    """Publish the legacy gate and the canonical current-run pointer atomically per file."""
    gate_target = Path(gate_path).expanduser().resolve()
    outgoing = dict(payload)
    if gate_target.exists():
        existing = json.loads(gate_target.read_text(encoding="utf-8"))
        for field in IMMUTABLE_GOVERNANCE_FIELDS:
            if field not in existing:
                continue
            if field in outgoing and outgoing[field] != existing[field]:
                raise ValueError(f"owned run cannot replace immutable {field}")
            outgoing[field] = existing[field]
    run_id = str(payload.get("run_id") or "").strip()
    safe_run_id = _safe_run_id(run_id)
    project = str(payload.get("project") or "trading_mvp")
    status = str(payload.get("status") or payload.get("gate_status") or "")
    if not status:
        raise ValueError("owned run status is required")
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {
        "path": str(payload.get("output_path") or ""),
        "kind": "file",
    }
    manifest_path = str(payload.get("manifest_path") or "")
    run_gate_root = gate_target.parent / "run-gates"
    launch_path = run_gate_root / f"{safe_run_id}.launch.json"
    if not launch_path.exists():
        launch = {
            "schema": LAUNCH_SCHEMA,
            "project": project,
            "run_id": run_id,
            "run_type": run_type,
            "created_at": payload.get("updated_at"),
            "command": " ".join(sys.argv),
            "cwd": str(Path.cwd()),
            "output": output,
            "manifest_path": manifest_path,
            "owner_output_prefix": payload.get("owner_output_prefix"),
            "code_snapshot_hash": payload.get("code_snapshot_hash"),
            "parallel_parent_run_id": payload.get("parallel_parent_run_id"),
            "research_only": True,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
        }
        _atomic_write_json(launch_path, launch)
    pointer = {
        "schema": POINTER_SCHEMA,
        "project": project,
        "run_id": run_id,
        "status": status,
        "updated_at": payload.get("updated_at"),
        "manifest_path": manifest_path,
        "output": output,
        "collector_pid": payload.get("collector_pid"),
        "monitor_pid": payload.get("monitor_pid"),
        "process_ids": list(payload.get("process_ids") or []),
        "launch_record_path": str(launch_path),
    }
    _atomic_write_json(gate_target, outgoing)
    _atomic_write_json(gate_target.parent / "current-run.json", pointer)
    return {
        "gate_path": str(gate_target),
        "pointer_path": str(gate_target.parent / "current-run.json"),
        "launch_record_path": str(launch_path),
    }
