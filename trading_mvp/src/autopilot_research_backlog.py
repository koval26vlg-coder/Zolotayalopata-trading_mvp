from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "trading_mvp_autopilot_research_backlog_v1"
CATALOG_SCHEMA = "trading_mvp_autopilot_research_catalog_v1"
MAX_RUNTIME_SEC = 1_800


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("invalid autopilot research backlog schema")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("research backlog tasks must be a list")
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("research backlog task must be an object")
        task_id = str(task.get("id") or "")
        if not task_id or task_id in ids:
            raise ValueError("research backlog task ids must be unique and non-empty")
        ids.add(task_id)
        runtime = int(task.get("max_runtime_sec") or 0)
        if runtime <= 0 or runtime > MAX_RUNTIME_SEC:
            raise ValueError(
                f"research backlog task {task_id} max_runtime_sec must be in [1, 1800]"
            )
        if str(task.get("status") or "") not in {
            "PENDING",
            "RUNNING",
            "COMPLETED",
            "FAILED",
        }:
            raise ValueError(f"invalid research backlog task status: {task_id}")
        if not str(task.get("output_path") or ""):
            raise ValueError(f"research backlog task output_path is required: {task_id}")
    return payload


def _read_catalog(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema") != CATALOG_SCHEMA:
        raise ValueError("invalid autopilot research catalog schema")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("research catalog tasks must be a list")
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("research catalog task must be an object")
        task_id = str(task.get("id") or "").strip()
        if not task_id or task_id in ids:
            raise ValueError("research catalog task ids must be unique and non-empty")
        ids.add(task_id)
        runtime = int(task.get("max_runtime_sec") or 0)
        if runtime <= 0 or runtime > MAX_RUNTIME_SEC:
            raise ValueError(
                f"research catalog task {task_id} max_runtime_sec must be in [1, 1800]"
            )
        if not str(task.get("output_path") or "").strip():
            raise ValueError(f"research catalog task output_path is required: {task_id}")
        if not str(task.get("objective") or "").strip():
            raise ValueError(f"research catalog task objective is required: {task_id}")
        allowed_inputs = task.get("allowed_inputs")
        if not isinstance(allowed_inputs, list) or not allowed_inputs:
            raise ValueError(
                f"research catalog task allowed_inputs must be a non-empty list: {task_id}"
            )
    return payload


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def ensure_backlog(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = _read(target)
    active = [
        task
        for task in payload["tasks"]
        if task.get("status") in {"PENDING", "RUNNING"}
    ]
    if active:
        return {
            "status": "NOOP_ACTIVE_TASKS",
            "added_task_ids": [],
            "backlog_path": str(target),
        }
    if payload.get("auto_refill") is not True:
        return {
            "status": "EXHAUSTED_NO_AUTO_REFILL",
            "added_task_ids": [],
            "backlog_path": str(target),
        }
    catalog_value = str(payload.get("catalog_path") or "").strip()
    expected_hash = str(payload.get("catalog_file_sha256") or "").strip().lower()
    if not catalog_value or len(expected_hash) != 64:
        raise ValueError("auto-refill catalog path and file hash are required")
    catalog_path = Path(catalog_value).expanduser().resolve()
    if not catalog_path.is_file():
        raise FileNotFoundError(f"research catalog is missing: {catalog_path}")
    if _sha256_file(catalog_path) != expected_hash:
        raise ValueError("research catalog file hash mismatch")
    catalog = _read_catalog(catalog_path)
    existing_ids = {str(task["id"]) for task in payload["tasks"]}
    added: list[str] = []
    for raw_task in catalog["tasks"]:
        task_id = str(raw_task["id"])
        if task_id in existing_ids:
            continue
        task = dict(raw_task)
        task["status"] = "PENDING"
        payload["tasks"].append(task)
        existing_ids.add(task_id)
        added.append(task_id)
    if not added:
        return {
            "status": "EXHAUSTED",
            "added_task_ids": [],
            "backlog_path": str(target),
        }
    payload["refill_count"] = int(payload.get("refill_count") or 0) + 1
    payload["last_refill_at_utc"] = _utc_now()
    payload["updated_at_utc"] = _utc_now()
    _write_atomic(target, payload)
    return {
        "status": "REFILLED",
        "added_task_ids": added,
        "backlog_path": str(target),
    }


def next_task(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = _read(target)
    running = [
        task for task in payload["tasks"] if task.get("status") == "RUNNING"
    ]
    if running:
        return {
            "status": "IN_PROGRESS",
            "task": dict(running[0]),
            "backlog_path": str(target),
        }
    pending = [
        task for task in payload["tasks"] if task.get("status") == "PENDING"
    ]
    if not pending:
        ensured = ensure_backlog(target)
        if ensured["status"] == "REFILLED":
            payload = _read(target)
            pending = [
                task for task in payload["tasks"] if task.get("status") == "PENDING"
            ]
        if not pending:
            return {
                "status": "EXHAUSTED",
                "task": None,
                "auto_refill_status": ensured["status"],
                "backlog_path": str(target),
            }
    return {
        "status": "READY",
        "task": dict(pending[0]),
        "backlog_path": str(target),
    }


def _task(payload: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in payload["tasks"]:
        if task.get("id") == task_id:
            return task
    raise ValueError(f"unknown research backlog task: {task_id}")


def claim_task(path: str | Path, task_id: str, *, owner: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = _read(target)
    if any(task.get("status") == "RUNNING" for task in payload["tasks"]):
        raise ValueError("another research backlog task is already RUNNING")
    task = _task(payload, task_id)
    if task.get("status") != "PENDING":
        raise ValueError(f"research backlog task is not PENDING: {task_id}")
    task["status"] = "RUNNING"
    task["owner"] = str(owner)
    task["started_at_utc"] = _utc_now()
    payload["updated_at_utc"] = _utc_now()
    _write_atomic(target, payload)
    return dict(task)


def complete_task(
    path: str | Path,
    task_id: str,
    artifact_path: str | Path,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = _read(target)
    task = _task(payload, task_id)
    if task.get("status") != "RUNNING":
        raise ValueError(f"research backlog task is not RUNNING: {task_id}")
    artifact = Path(artifact_path).expanduser().resolve()
    expected = Path(str(task["output_path"])).expanduser().resolve()
    if artifact != expected:
        raise ValueError("research artifact path does not match frozen output_path")
    if not artifact.is_file():
        raise FileNotFoundError(f"research artifact is missing: {artifact}")
    task["status"] = "COMPLETED"
    task["finished_at_utc"] = _utc_now()
    task["artifact_path"] = str(artifact)
    task["artifact_sha256"] = _sha256_file(artifact)
    payload["updated_at_utc"] = _utc_now()
    _write_atomic(target, payload)
    return dict(task)


def fail_task(path: str | Path, task_id: str, *, error: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = _read(target)
    task = _task(payload, task_id)
    if task.get("status") != "RUNNING":
        raise ValueError(f"research backlog task is not RUNNING: {task_id}")
    task["status"] = "FAILED"
    task["finished_at_utc"] = _utc_now()
    task["error"] = str(error)
    payload["updated_at_utc"] = _utc_now()
    _write_atomic(target, payload)
    return dict(task)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the bounded trading_mvp agent research backlog."
    )
    parser.add_argument("action", choices=("next", "ensure", "claim", "complete", "fail"))
    parser.add_argument("--backlog", type=Path, required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--owner", default="Codex")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--error")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "next":
        result = next_task(args.backlog)
    elif args.action == "ensure":
        result = ensure_backlog(args.backlog)
    elif args.action == "claim":
        if not args.task_id:
            raise ValueError("--task-id is required for claim")
        result = claim_task(args.backlog, args.task_id, owner=args.owner)
    elif args.action == "complete":
        if not args.task_id or args.artifact is None:
            raise ValueError("--task-id and --artifact are required for complete")
        result = complete_task(args.backlog, args.task_id, args.artifact)
    else:
        if not args.task_id or args.error is None:
            raise ValueError("--task-id and --error are required for fail")
        result = fail_task(args.backlog, args.task_id, error=args.error)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
