from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from gate_historical_membership_history_plan import (
    MAX_RUNTIME_SEC,
    authorize_history_collect,
    sha256_file,
    sha256_json,
)


MANIFEST_SCHEMA = "trading_mvp_gate_historical_membership_history_collect_manifest_v1"
READY_FOR_QUALITY_DECISION = "GATE_MEMBERSHIP_HISTORY_COLLECT_READY_FOR_QUALITY"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_HISTORY_COLLECT_STOPPED_INCOMPLETE"
DEFAULT_MIN_FREE_BYTES = 2 * 1024**3
MAX_COMPRESSED_FILE_BYTES = 512 * 1024**2
MAX_UNCOMPRESSED_FILE_BYTES = 2 * 1024**3
FetchOverride = Callable[[dict[str, Any], float], tuple[int, bytes, Mapping[str, str]]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
        }
    )


def _target_path(output_root: Path, task: Mapping[str, Any]) -> Path:
    return (
        output_root
        / "raw"
        / "gateio"
        / str(task["archive_type"])
        / str(task["year_month"])
        / f"{task['symbol']}-{task['year_month']}.csv.gz"
    )


def validate_gzip_file(path: Path) -> dict[str, int | str]:
    compressed_bytes = path.stat().st_size
    if compressed_bytes <= 0 or compressed_bytes > MAX_COMPRESSED_FILE_BYTES:
        raise ValueError("compressed archive size is outside bounds")
    uncompressed_bytes = 0
    newline_count = 0
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            uncompressed_bytes += len(chunk)
            if uncompressed_bytes > MAX_UNCOMPRESSED_FILE_BYTES:
                raise ValueError("uncompressed archive size is outside bounds")
            newline_count += chunk.count(b"\n")
    if uncompressed_bytes <= 0:
        raise ValueError("archive is empty after decompression")
    return {
        "compressed_bytes": compressed_bytes,
        "uncompressed_bytes": uncompressed_bytes,
        "line_count": newline_count,
        "sha256": sha256_file(path),
    }


def _write_and_validate_bytes(target: Path, content: bytes) -> dict[str, int | str]:
    if not content or len(content) > MAX_COMPRESSED_FILE_BYTES:
        raise ValueError("downloaded archive size is outside bounds")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".download",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        details = validate_gzip_file(temporary)
        os.replace(temporary, target)
        return details
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _stream_network_download(
    task: dict[str, Any],
    target: Path,
    timeout_sec: float,
) -> tuple[int, dict[str, int | str] | None]:
    session = requests.Session()
    session.trust_env = False
    try:
        with session.get(str(task["url"]), stream=True, timeout=max(1.0, timeout_sec)) as response:
            status = int(response.status_code)
            if status == 404:
                return status, None
            response.raise_for_status()
            raw_length = response.headers.get("Content-Length")
            if raw_length and int(raw_length) > MAX_COMPRESSED_FILE_BYTES:
                raise ValueError("remote archive exceeds compressed size cap")
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".download",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            written = 0
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_COMPRESSED_FILE_BYTES:
                            raise ValueError("downloaded archive exceeds compressed size cap")
                        handle.write(chunk)
                details = validate_gzip_file(temporary)
                os.replace(temporary, target)
                return status, details
            except Exception:
                try:
                    temporary.unlink()
                except OSError:
                    pass
                raise
    finally:
        session.close()


def _download_task(
    task: dict[str, Any],
    *,
    output_root: Path,
    deadline_monotonic: float,
    request_timeout_sec: int,
    fetch_override: FetchOverride | None,
) -> dict[str, Any]:
    target = _target_path(output_root, task)
    base = {
        "cache_key": task["cache_key"],
        "symbol": task["symbol"],
        "canonical_asset_id": task["canonical_asset_id"],
        "archive_type": task["archive_type"],
        "year_month": task["year_month"],
        "url": task["url"],
        "path": str(target.resolve()),
    }
    try:
        if target.is_file():
            details = validate_gzip_file(target)
            return {**base, "status": "cached", "http_status": None, **details}
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("collector runtime exhausted before request")
        timeout = min(float(request_timeout_sec), remaining)
        if fetch_override is not None:
            status, content, _headers = fetch_override(task, timeout)
            if int(status) == 404:
                return {**base, "status": "missing", "http_status": 404}
            if int(status) != 200:
                raise requests.HTTPError(f"HTTP {status}")
            details = _write_and_validate_bytes(target, bytes(content))
            return {**base, "status": "downloaded", "http_status": 200, **details}
        status, details = _stream_network_download(task, target, timeout)
        if status == 404:
            return {**base, "status": "missing", "http_status": 404}
        if details is None:
            raise ValueError("download completed without archive details")
        return {**base, "status": "downloaded", "http_status": status, **details}
    except Exception as exc:  # noqa: BLE001 - errors are persisted for an exact resume.
        return {
            **base,
            "status": "error",
            "http_status": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _summary(files: list[Mapping[str, Any]], total_tasks: int) -> dict[str, int]:
    counts = {status: sum(row.get("status") == status for row in files) for status in ("downloaded", "cached", "missing", "error")}
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
        "generated_at_utc": _utc_now(),
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
        "files": sorted(files, key=lambda row: (row["symbol"], row["year_month"], row["archive_type"])),
        "research_only": True,
        "public_data_only": True,
        "returns_read": False,
        "pnl_read": False,
        "oos_read": False,
        "grid_search": False,
        "live_orders": False,
        "private_api_keys": False,
        "next_allowed_command": (
            "fast-edge-membership-history-quality"
            if final
            else "fast-edge-membership-history-collect"
        ),
        "blocked_actions": [
            "momentum_evaluation_before_history_quality",
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
        or manifest.get("decision") != READY_FOR_QUALITY_DECISION
        or str(manifest.get("artifact_hash") or "") != _manifest_hash(manifest)
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
    fetch_override: FetchOverride | None = None,
) -> dict[str, Any]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = authorize_history_collect(resolved_plan, expected_plan_hash)
    runtime = int(max_runtime_sec)
    planned_runtime = int(plan["runtime_contract"]["max_runtime_sec"])
    if runtime < 1 or runtime > MAX_RUNTIME_SEC or runtime > planned_runtime:
        raise ValueError(f"max_runtime_sec must be in [1, {planned_runtime}]")
    workers = int(max_workers)
    if workers < 1 or workers > 8:
        raise ValueError("max_workers must be in [1, 8]")
    resolved_output = Path(output_root).expanduser().resolve()
    resolved_manifest = Path(manifest_path).expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(resolved_output).free < int(min_free_bytes):
        raise OSError("disk free space is below collector guard")
    if resolved_manifest.is_file():
        cached_manifest = _read_json_object(resolved_manifest)
        if _valid_final_manifest(cached_manifest, plan["plan_hash"]):
            cached_manifest["cache_reused"] = True
            return cached_manifest

    started = time.monotonic()
    deadline = started + runtime
    files: list[dict[str, Any]] = []
    prior_missing: set[str] = set()
    if resolved_manifest.is_file():
        prior = _read_json_object(resolved_manifest)
        if prior.get("plan_hash") == plan["plan_hash"]:
            prior_missing = {
                str(row.get("cache_key"))
                for row in prior.get("files") or []
                if row.get("status") == "missing"
            }
    pending: list[dict[str, Any]] = []
    for task in plan["archive_tasks"]:
        task_dict = dict(task)
        if task_dict["cache_key"] in prior_missing:
            files.append(
                {
                    "cache_key": task_dict["cache_key"],
                    "symbol": task_dict["symbol"],
                    "canonical_asset_id": task_dict["canonical_asset_id"],
                    "archive_type": task_dict["archive_type"],
                    "year_month": task_dict["year_month"],
                    "url": task_dict["url"],
                    "path": str(_target_path(resolved_output, task_dict).resolve()),
                    "status": "missing",
                    "http_status": 404,
                    "cache_reused": True,
                }
            )
        else:
            pending.append(task_dict)

    interim = _build_manifest(
        plan=plan,
        plan_path=resolved_plan,
        output_root=resolved_output,
        files=files,
        started_monotonic=started,
        final=False,
        decision=STOPPED_INCOMPLETE_DECISION,
    )
    _atomic_write_json(resolved_manifest, interim)
    future_map: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gate-archive") as executor:
        for task in pending:
            future = executor.submit(
                _download_task,
                task,
                output_root=resolved_output,
                deadline_monotonic=deadline,
                request_timeout_sec=request_timeout_sec,
                fetch_override=fetch_override,
            )
            future_map[future] = task
        for completed_index, future in enumerate(as_completed(future_map), start=1):
            files.append(future.result())
            summary = _summary(files, len(plan["archive_tasks"]))
            if completed_index % 5 == 0 or completed_index == len(future_map):
                print(
                    f"progress={summary['completed_tasks']}/{summary['total_tasks']} "
                    f"downloaded={summary['downloaded']} cached={summary['cached']} "
                    f"missing={summary['missing']} errors={summary['errors']}",
                    flush=True,
                )
                checkpoint = _build_manifest(
                    plan=plan,
                    plan_path=resolved_plan,
                    output_root=resolved_output,
                    files=files,
                    started_monotonic=started,
                    final=False,
                    decision=STOPPED_INCOMPLETE_DECISION,
                )
                _atomic_write_json(resolved_manifest, checkpoint)

    summary = _summary(files, len(plan["archive_tasks"]))
    final = summary["completed_tasks"] == summary["total_tasks"] and summary["errors"] == 0
    decision = READY_FOR_QUALITY_DECISION if final else STOPPED_INCOMPLETE_DECISION
    manifest = _build_manifest(
        plan=plan,
        plan_path=resolved_plan,
        output_root=resolved_output,
        files=files,
        started_monotonic=started,
        final=final,
        decision=decision,
    )
    _atomic_write_json(resolved_manifest, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible Gate historical-membership archive collector")
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["final"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
