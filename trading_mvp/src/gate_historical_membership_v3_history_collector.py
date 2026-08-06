from __future__ import annotations

import argparse
import json
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

import gate_historical_membership_history_collector as archive_io
from gate_historical_membership_v3_history_plan import (
    MAX_RUNTIME_SEC,
    authorize_history_collect,
    sha256_file,
    sha256_json,
)


MANIFEST_SCHEMA = "trading_mvp_gate_historical_membership_v3_history_collect_manifest_v1"
READY_FOR_QUALITY_PLAN_DECISION = "GATE_MEMBERSHIP_V3_HISTORY_COLLECT_READY_FOR_QUALITY_PLANONLY"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_V3_HISTORY_COLLECT_STOPPED_INCOMPLETE"
DEFAULT_MIN_FREE_BYTES = 2 * 1024**3


def _manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
        }
    )


def _summary(files: list[Mapping[str, Any]], total_tasks: int) -> dict[str, int]:
    counts = {
        status: sum(row.get("status") == status for row in files)
        for status in ("downloaded", "cached", "missing", "error")
    }
    return {
        "total_tasks": total_tasks,
        "completed_tasks": len(files),
        **counts,
        "errors": counts["error"],
    }


def _build_manifest(
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    output_root: Path,
    files: list[dict[str, Any]],
    started_monotonic: float,
    final: bool,
    decision: str,
) -> dict[str, Any]:
    summary = _summary(files, len(plan["archive_tasks"]))
    payload: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generated_at_utc": archive_io._utc_now(),
        "run_id": plan["run_id"],
        "plan_path": str(plan_path),
        "plan_sha256": sha256_file(plan_path),
        "plan_hash": plan["plan_hash"],
        "input_merkle_sha256": plan["input_merkle_sha256"],
        "output_root": str(output_root),
        "final": final,
        "decision": decision,
        "cache_reused": False,
        "runtime_sec": time.monotonic() - started_monotonic,
        "summary": summary,
        "files": sorted(
            files, key=lambda row: (row["symbol"], row["year_month"], row["archive_type"])
        ),
        "data_access_audit": {
            "archive_payload_read": True,
            "prices_parsed": False,
            "returns_read": False,
            "signals_read": False,
            "pnl_read": False,
            "oos_read": False,
        },
        "research_only": True,
        "public_data_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "next_allowed_command": (
            "create_hash_bound_membership_v3_history_quality_planonly"
            if final
            else "fast-edge-membership-v3-history-collect"
        ),
        "blocked_actions": [
            "history_quality_without_separate_hash_bound_plan",
            "signal_evaluation",
            "oos",
            "grid_search",
            "retune",
            "paper_forward",
            "live_orders",
            "private_api_keys",
        ],
    }
    if not final:
        payload["resume_contract"] = {
            "same_run_id": plan["run_id"],
            "same_plan_hash": plan["plan_hash"],
            "same_output_root": str(output_root),
            "visible_terminal_required": True,
        }
    payload["artifact_hash"] = _manifest_hash(payload)
    return payload


def _valid_final_manifest(manifest: Mapping[str, Any], plan_hash: str) -> bool:
    if (
        manifest.get("schema") != MANIFEST_SCHEMA
        or manifest.get("plan_hash") != plan_hash
        or manifest.get("final") is not True
        or manifest.get("decision") != READY_FOR_QUALITY_PLAN_DECISION
        or manifest.get("artifact_hash") != _manifest_hash(manifest)
    ):
        return False
    for row in manifest.get("files") or []:
        if row.get("status") not in {"downloaded", "cached"}:
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or sha256_file(path) != str(row.get("sha256") or ""):
            return False
    return True


def collect_history_archives(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_root: str | Path,
    manifest_path: str | Path,
    max_runtime_sec: int,
    request_timeout_sec: int = 30,
    max_workers: int = 4,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    fetch_override: archive_io.FetchOverride | None = None,
) -> dict[str, Any]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = authorize_history_collect(resolved_plan, expected_plan_hash)
    runtime = int(max_runtime_sec)
    planned_runtime = int(plan["runtime_contract"]["max_runtime_sec"])
    if runtime < 1 or runtime > MAX_RUNTIME_SEC or runtime > planned_runtime:
        raise ValueError(f"MaxRuntimeSec must be in [1, {planned_runtime}]")
    workers = int(max_workers)
    if workers < 1 or workers > 8:
        raise ValueError("max_workers must be in [1, 8]")
    resolved_output = Path(output_root).expanduser().resolve()
    resolved_manifest = Path(manifest_path).expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(resolved_output).free < int(min_free_bytes):
        raise OSError("disk free space is below collector guard")
    if resolved_manifest.is_file():
        cached = archive_io._read_json_object(resolved_manifest)
        if _valid_final_manifest(cached, plan["plan_hash"]):
            cached["cache_reused"] = True
            return cached

    started = time.monotonic()
    deadline = started + runtime
    files: list[dict[str, Any]] = []
    prior_missing: set[str] = set()
    if resolved_manifest.is_file():
        prior = archive_io._read_json_object(resolved_manifest)
        if prior.get("plan_hash") == plan["plan_hash"]:
            prior_missing = {
                str(row.get("cache_key"))
                for row in prior.get("files") or []
                if row.get("status") == "missing"
            }
    pending: list[dict[str, Any]] = []
    for raw in plan["archive_tasks"]:
        task = dict(raw)
        if task["cache_key"] in prior_missing:
            files.append(
                {
                    "cache_key": task["cache_key"],
                    "symbol": task["symbol"],
                    "canonical_asset_id": task["canonical_asset_id"],
                    "archive_type": task["archive_type"],
                    "year_month": task["year_month"],
                    "url": task["url"],
                    "path": str(archive_io._target_path(resolved_output, task).resolve()),
                    "status": "missing",
                    "http_status": 404,
                    "cache_reused": True,
                }
            )
        else:
            pending.append(task)
    archive_io._atomic_write_json(
        resolved_manifest,
        _build_manifest(
            plan=plan,
            plan_path=resolved_plan,
            output_root=resolved_output,
            files=files,
            started_monotonic=started,
            final=False,
            decision=STOPPED_INCOMPLETE_DECISION,
        ),
    )
    future_map: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gate-membership-v3-history") as executor:
        for task in pending:
            future = executor.submit(
                archive_io._download_task,
                task,
                output_root=resolved_output,
                deadline_monotonic=deadline,
                request_timeout_sec=request_timeout_sec,
                fetch_override=fetch_override,
            )
            future_map[future] = task
        for completed_index, future in enumerate(as_completed(future_map), start=1):
            files.append(future.result())
            if completed_index % 25 == 0 or completed_index == len(future_map):
                summary = _summary(files, len(plan["archive_tasks"]))
                print(
                    f"progress={summary['completed_tasks']}/{summary['total_tasks']} "
                    f"downloaded={summary['downloaded']} cached={summary['cached']} "
                    f"missing={summary['missing']} errors={summary['errors']}",
                    flush=True,
                )
                archive_io._atomic_write_json(
                    resolved_manifest,
                    _build_manifest(
                        plan=plan,
                        plan_path=resolved_plan,
                        output_root=resolved_output,
                        files=files,
                        started_monotonic=started,
                        final=False,
                        decision=STOPPED_INCOMPLETE_DECISION,
                    ),
                )
    summary = _summary(files, len(plan["archive_tasks"]))
    final = summary["completed_tasks"] == summary["total_tasks"] and summary["errors"] == 0
    manifest = _build_manifest(
        plan=plan,
        plan_path=resolved_plan,
        output_root=resolved_output,
        files=files,
        started_monotonic=started,
        final=final,
        decision=(
            READY_FOR_QUALITY_PLAN_DECISION if final else STOPPED_INCOMPLETE_DECISION
        ),
    )
    archive_io._atomic_write_json(resolved_manifest, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible Gate membership-v3 archive collector")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--max-runtime-sec", type=int, required=True)
    parser.add_argument("--request-timeout-sec", type=int, default=30)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    args = parser.parse_args()
    result = collect_history_archives(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        output_root=args.output_root,
        manifest_path=args.manifest,
        max_runtime_sec=args.max_runtime_sec,
        request_timeout_sec=args.request_timeout_sec,
        max_workers=args.max_workers,
        min_free_bytes=args.min_free_bytes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("final") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
