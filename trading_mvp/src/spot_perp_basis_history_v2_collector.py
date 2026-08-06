from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from costs import validate_runtime_sec
from gate_historical_archive import month_keys_for_range
from owned_run_gate import publish_owned_run_gate
from spot_perp_basis_history_v2 import (
    ARCHIVE_SERIES,
    PLAN_SCHEMA,
    required_archive_urls,
    sha256_file,
    sha256_json,
    validate_gate_spot_perp_plan,
)


COLLECT_SCHEMA = "trading_mvp_gate_spot_perp_history_collect_v2"
CACHE_META_SCHEMA = "trading_mvp_gate_spot_perp_history_cache_v1"
DEFAULT_OUTPUT_ROOT = Path(r"E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2")
DEFAULT_GATE_PATH = Path(r"C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json")
MAX_RUNTIME_SEC = 7_200


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _replace_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def archive_months_for_window(start_sec: int, end_sec: int) -> list[str]:
    start = int(start_sec)
    end = int(end_sec)
    if start < 0 or end <= start:
        raise ValueError("invalid collection window")
    end_dt = datetime.fromtimestamp(end, timezone.utc)
    current_month_start = int(
        end_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    archive_end = min(end, current_month_start)
    if archive_end <= start:
        return []
    return month_keys_for_range(start, archive_end)


def _rest_tail_start(end_sec: int) -> int:
    end_dt = datetime.fromtimestamp(int(end_sec), timezone.utc)
    return int(end_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())


def _task_id(payload: Mapping[str, Any]) -> str:
    return sha256_json(payload)


def _archive_cache_path(cache_root: Path, *, series: str, month: str, symbol: str) -> Path:
    return cache_root / "archive" / series / month / f"{symbol}-{month}.csv.gz"


def _tail_cache_path(cache_root: Path, *, series: str, start_sec: int, end_sec: int, symbol: str) -> Path:
    return cache_root / "rest-tail" / series / f"{start_sec}-{end_sec}" / f"{symbol}.json"


def build_collection_tasks(plan: Mapping[str, Any], cache_root: Path) -> list[dict[str, Any]]:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("final") is not True:
        raise ValueError("unexpected Gate spot/perp PlanOnly artifact")
    sample = plan.get("sample_plan")
    universe = plan.get("universe")
    if not isinstance(sample, Mapping) or not isinstance(universe, Mapping):
        raise ValueError("Gate spot/perp plan is missing sample or universe")
    start_sec = int(sample.get("window_start_sec") or 0)
    end_sec = int(sample.get("window_end_sec") or 0)
    months = archive_months_for_window(start_sec, end_sec)
    tail_start = _rest_tail_start(end_sec)
    assets = universe.get("selected_assets")
    if not isinstance(assets, list):
        raise ValueError("Gate spot/perp selected assets are missing")
    tasks: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise ValueError("invalid Gate spot/perp asset")
        base = str(asset.get("base") or "").upper()
        canonical_id = str(asset.get("canonical_asset_id") or "")
        spot_symbol = str(asset.get("gate_spot_symbol") or "").upper()
        perp_symbol = str(asset.get("gate_perp_symbol") or "").upper()
        if not all((base, canonical_id, spot_symbol, perp_symbol)):
            raise ValueError("invalid Gate spot/perp asset identity")
        for month in months:
            urls = required_archive_urls(base, month)
            for series in ARCHIVE_SERIES:
                symbol = spot_symbol if series == "spot_trade" else perp_symbol
                identity = {
                    "source": "gate_archive",
                    "canonical_asset_id": canonical_id,
                    "base": base,
                    "series": series,
                    "month": month,
                    "url": urls[series],
                }
                cache_path = _archive_cache_path(cache_root, series=series, month=month, symbol=symbol)
                tasks.append(
                    {
                        **identity,
                        "task_id": _task_id(identity),
                        "symbol": symbol,
                        "params": {},
                        "cache_path": str(cache_path),
                        "meta_path": str(cache_path.with_suffix(cache_path.suffix + ".meta.json")),
                    }
                )
        if tail_start < end_sec:
            tail_specs = {
                "spot_trade": (
                    "https://api.gateio.ws/api/v4/spot/candlesticks",
                    {"currency_pair": spot_symbol, "from": tail_start, "to": end_sec, "interval": "1h"},
                ),
                "perp_trade": (
                    "https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
                    {"contract": perp_symbol, "from": tail_start, "to": end_sec, "interval": "1h"},
                ),
                "perp_mark": (
                    "https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
                    {"contract": f"mark_{perp_symbol}", "from": tail_start, "to": end_sec, "interval": "1h"},
                ),
                "funding": (
                    "https://api.gateio.ws/api/v4/futures/usdt/funding_rate",
                    {"contract": perp_symbol, "limit": 1_000},
                ),
            }
            for series, (url, params) in tail_specs.items():
                symbol = spot_symbol if series == "spot_trade" else perp_symbol
                identity = {
                    "source": "gate_rest_tail",
                    "canonical_asset_id": canonical_id,
                    "base": base,
                    "series": series,
                    "start_sec": tail_start,
                    "end_sec": end_sec,
                    "url": url,
                    "params": params,
                }
                cache_path = _tail_cache_path(
                    cache_root,
                    series=series,
                    start_sec=tail_start,
                    end_sec=end_sec,
                    symbol=symbol,
                )
                tasks.append(
                    {
                        **identity,
                        "task_id": _task_id(identity),
                        "symbol": symbol,
                        "cache_path": str(cache_path),
                        "meta_path": str(cache_path.with_suffix(cache_path.suffix + ".meta.json")),
                    }
                )
    tasks.sort(key=lambda row: (row["source"], row["base"], row["series"], row.get("month") or ""))
    return tasks


def cached_task_result(task: Mapping[str, Any]) -> dict[str, Any] | None:
    data_path = Path(str(task["cache_path"]))
    meta_path = Path(str(task["meta_path"]))
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("schema") not in {None, CACHE_META_SCHEMA} or meta.get("task_id") != task.get("task_id"):
        return None
    status = str(meta.get("status") or "")
    if status == "missing":
        return {**dict(meta), "status": "cache_hit_missing", "network_request": False}
    if status != "downloaded" or not data_path.is_file():
        return None
    if int(meta.get("bytes") or -1) != data_path.stat().st_size:
        return None
    if str(meta.get("data_sha256") or "") != sha256_file(data_path):
        return None
    return {**dict(meta), "status": "cache_hit", "network_request": False}


def _validate_gzip(path: Path) -> None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            first = handle.readline()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid gzip archive: {path}") from exc
    if not first.strip():
        raise ValueError(f"empty gzip archive: {path}")


def _write_meta(task: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    _replace_json_atomic(
        Path(str(task["meta_path"])),
        {"schema": CACHE_META_SCHEMA, "task_id": task["task_id"], **dict(payload)},
    )


def execute_collection_task(task: Mapping[str, Any], *, timeout_sec: int = 30) -> dict[str, Any]:
    cached = cached_task_result(task)
    if cached is not None:
        return {**dict(task), **cached}
    data_path = Path(str(task["cache_path"]))
    last_error: Exception | None = None
    for attempt in range(3):
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(
                str(task["url"]),
                params=dict(task.get("params") or {}),
                timeout=timeout_sec,
                stream=task.get("source") == "gate_archive",
            )
            if response.status_code == 404 and task.get("source") == "gate_archive":
                meta = {
                    "status": "missing",
                    "http_status": 404,
                    "bytes": 0,
                    "data_sha256": None,
                    "url": task["url"],
                    "network_request": True,
                    "attempts": attempt + 1,
                }
                _write_meta(task, meta)
                return {**dict(task), **meta}
            response.raise_for_status()
            if task.get("source") == "gate_archive":
                payload = response.content
                _write_bytes_atomic(data_path, payload)
                _validate_gzip(data_path)
            else:
                decoded = response.json()
                if not isinstance(decoded, list):
                    raise ValueError("Gate REST tail payload must be a list")
                payload = (_canonical_json(decoded) + "\n").encode("utf-8")
                _write_bytes_atomic(data_path, payload)
            meta = {
                "status": "downloaded",
                "http_status": int(response.status_code),
                "bytes": data_path.stat().st_size,
                "data_sha256": sha256_file(data_path),
                "url": task["url"],
                "params": dict(task.get("params") or {}),
                "network_request": True,
                "attempts": attempt + 1,
            }
            _write_meta(task, meta)
            return {**dict(task), **meta}
        except (requests.RequestException, ValueError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            try:
                data_path.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    return {
        **dict(task),
        "status": "transient_error",
        "http_status": None,
        "bytes": 0,
        "data_sha256": None,
        "network_request": True,
        "attempts": 3,
        "error": f"{type(last_error).__name__}: {last_error}",
    }


def _manifest_payload(
    *,
    run_id: str,
    plan_path: Path,
    plan_hash: str,
    output_root: Path,
    run_dir: Path,
    manifest_path: Path,
    max_runtime_sec: int,
    started_at: str,
    results: Sequence[Mapping[str, Any]],
    expected_tasks: int,
    status: str,
    final: bool,
    stop_reason: str,
    runtime_sec: float,
) -> dict[str, Any]:
    completed = sum(row.get("status") in {"downloaded", "cache_hit", "missing", "cache_hit_missing"} for row in results)
    missing = sum(row.get("status") in {"missing", "cache_hit_missing"} for row in results)
    errors = sum(row.get("status") == "transient_error" for row in results)
    network_requests = sum(bool(row.get("network_request")) for row in results)
    bytes_total = sum(int(row.get("bytes") or 0) for row in results)
    payload: dict[str, Any] = {
        "schema": COLLECT_SCHEMA,
        "project": "trading_mvp",
        "run_id": run_id,
        "status": status,
        "gate_status": status if status == "STOPPED_INCOMPLETE" else status,
        "final": final,
        "started_at": started_at,
        "updated_at": _utc_now(),
        "stop_reason": stop_reason,
        "plan_path": str(plan_path),
        "plan_hash": plan_hash,
        "plan_file_sha256": sha256_file(plan_path),
        "output_root": str(output_root),
        "run_directory": str(run_dir),
        "manifest_path": str(manifest_path),
        "cache_root": str(output_root / "cache"),
        "max_runtime_sec": int(max_runtime_sec),
        "requested_duration_sec": int(max_runtime_sec),
        "actual_duration_sec": round(runtime_sec, 6),
        "expected_tasks": expected_tasks,
        "completed_tasks": completed,
        "completed_cycles": completed,
        "total_cycles": expected_tasks,
        "remaining_cycles": max(0, expected_tasks - completed),
        "rows": completed,
        "missing_archive_files": missing,
        "error_count": errors,
        "errors": errors,
        "network_requests": network_requests,
        "bytes_total": bytes_total,
        "task_results": list(results),
        "primary_output_complete": final,
        "expected_outputs_complete": final,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "research_only": True,
        "public_api_only": True,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "output": {"path": str(run_dir), "kind": "directory"},
        "owner_output_prefix": str(output_root),
        "locks": ["market_data_writer:gate_spot_perp_history_v2"],
        "parallel_safe_actions": ["unit_tests", "fixture_work", "static_analysis_on_other_output_namespace"],
        "forbidden_overlapping_actions": ["second_collector", "consumer_of_incomplete_output", "grid", "oos", "live"],
        "next_goal_decision": (
            "GATE_SPOT_PERP_HISTORY_COLLECT_READY_FOR_QUALITY"
            if final
            else "GATE_SPOT_PERP_HISTORY_COLLECT_STOPPED_INCOMPLETE"
        ),
        "next_step_after_ready": (
            "Run hash-bound archive normalization and data-quality only; do not read OOS or PnL."
            if final
            else "Resume this same run_id visibly after confirming no writer is active."
        ),
    }
    payload["manifest_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key not in {"updated_at", "actual_duration_sec", "manifest_hash"}}
    )
    return payload


def collect_gate_spot_perp_history(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_root: str | Path,
    run_id: str,
    max_runtime_sec: int = 1_200,
    gate_path: str | Path | None = None,
    resume: bool = False,
    workers: int = 6,
) -> dict[str, Any]:
    runtime_limit = validate_runtime_sec(max_runtime_sec)
    if runtime_limit > MAX_RUNTIME_SEC:
        raise ValueError(f"collector MaxRuntimeSec must be <= {MAX_RUNTIME_SEC}")
    if workers < 1 or workers > 12:
        raise ValueError("workers must be in [1, 12]")
    plan_target = Path(plan_path).expanduser().resolve()
    plan = json.loads(plan_target.read_text(encoding="utf-8"))
    validation = validate_gate_spot_perp_plan(plan, expected_plan_hash=expected_plan_hash)
    output = Path(output_root).expanduser().resolve()
    run_dir = output / "runs" / run_id
    manifest_path = run_dir / "manifest.json"
    lock_path = output / ".gate-spot-perp-history-writer.lock"
    if resume:
        if not manifest_path.is_file():
            raise ValueError("resume requires the original manifest")
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior.get("final") is True:
            raise ValueError("cannot resume a final collector")
        if prior.get("plan_hash") != expected_plan_hash or prior.get("run_id") != run_id:
            raise ValueError("resume identity mismatch")
    elif run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {run_dir}")
    output.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_fd: int | None = None
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, f"pid={os.getpid()} run_id={run_id}\n".encode("utf-8"))
        started = time.monotonic()
        started_at = _utc_now()
        deadline = started + runtime_limit
        tasks = build_collection_tasks(plan, output / "cache")
        results_by_id: dict[str, dict[str, Any]] = {}
        running = _manifest_payload(
            run_id=run_id,
            plan_path=plan_target,
            plan_hash=validation["plan_hash"],
            output_root=output,
            run_dir=run_dir,
            manifest_path=manifest_path,
            max_runtime_sec=runtime_limit,
            started_at=started_at,
            results=[],
            expected_tasks=len(tasks),
            status="RUNNING",
            final=False,
            stop_reason="running",
            runtime_sec=0.0,
        )
        running["collector_pid"] = os.getpid()
        running["process_ids"] = [os.getpid()]
        _replace_json_atomic(manifest_path, running)
        if gate_path:
            publish_owned_run_gate(gate_path, running, run_type="gate_spot_perp_history_v2")
        batch_size = max(1, workers * 2)
        for offset in range(0, len(tasks), batch_size):
            if time.monotonic() >= deadline:
                break
            batch = tasks[offset : offset + batch_size]
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(execute_collection_task, task): task
                    for task in batch
                    if task["task_id"] not in results_by_id
                }
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:  # noqa: BLE001 - manifest must preserve every worker failure.
                        result = {
                            **task,
                            "status": "transient_error",
                            "bytes": 0,
                            "network_request": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    results_by_id[task["task_id"]] = result
            ordered_results = [results_by_id[task["task_id"]] for task in tasks if task["task_id"] in results_by_id]
            elapsed = time.monotonic() - started
            progress = _manifest_payload(
                run_id=run_id,
                plan_path=plan_target,
                plan_hash=validation["plan_hash"],
                output_root=output,
                run_dir=run_dir,
                manifest_path=manifest_path,
                max_runtime_sec=runtime_limit,
                started_at=started_at,
                results=ordered_results,
                expected_tasks=len(tasks),
                status="RUNNING",
                final=False,
                stop_reason="running",
                runtime_sec=elapsed,
            )
            progress["collector_pid"] = os.getpid()
            progress["process_ids"] = [os.getpid()]
            _replace_json_atomic(manifest_path, progress)
            if gate_path:
                publish_owned_run_gate(gate_path, progress, run_type="gate_spot_perp_history_v2")
            print(
                f"[{progress['completed_tasks']}/{progress['expected_tasks']}] "
                f"missing={progress['missing_archive_files']} errors={progress['error_count']} "
                f"bytes={progress['bytes_total']} elapsed={elapsed:.1f}s",
                flush=True,
            )
            if progress["error_count"] > 0:
                break
        ordered_results = [results_by_id[task["task_id"]] for task in tasks if task["task_id"] in results_by_id]
        elapsed = time.monotonic() - started
        completed = sum(
            row.get("status") in {"downloaded", "cache_hit", "missing", "cache_hit_missing"}
            for row in ordered_results
        )
        errors = sum(row.get("status") == "transient_error" for row in ordered_results)
        final = completed == len(tasks) and errors == 0
        if final:
            status, stop_reason = "READY_FOR_POSTPROCESS", "completed"
        elif errors:
            status, stop_reason = "STOPPED_INCOMPLETE", "network_or_validation_error"
        else:
            status, stop_reason = "STOPPED_INCOMPLETE", "max_runtime_sec"
        manifest = _manifest_payload(
            run_id=run_id,
            plan_path=plan_target,
            plan_hash=validation["plan_hash"],
            output_root=output,
            run_dir=run_dir,
            manifest_path=manifest_path,
            max_runtime_sec=runtime_limit,
            started_at=started_at,
            results=ordered_results,
            expected_tasks=len(tasks),
            status=status,
            final=final,
            stop_reason=stop_reason,
            runtime_sec=elapsed,
        )
        manifest["collector_pid"] = os.getpid()
        manifest["process_ids"] = [os.getpid()]
        manifest["resume_command"] = (
            f"python {Path(__file__).resolve()} --plan {plan_target} --expected-plan-hash {expected_plan_hash} "
            f"--output-root {output} --run-id {run_id} --max-runtime-sec {runtime_limit} --resume"
        )
        _replace_json_atomic(manifest_path, manifest)
        if gate_path:
            publish_owned_run_gate(gate_path, manifest, run_type="gate_spot_perp_history_v2")
        print(
            f"{status}: completed={manifest['completed_tasks']}/{manifest['expected_tasks']} "
            f"missing={manifest['missing_archive_files']} errors={manifest['error_count']} manifest={manifest_path}",
            flush=True,
        )
        return manifest
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Resumable Gate spot/perp archive collector")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=1_200)
    parser.add_argument("--gate-path", default=str(DEFAULT_GATE_PATH))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    manifest = collect_gate_spot_perp_history(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        output_root=args.output_root,
        run_id=args.run_id,
        max_runtime_sec=args.max_runtime_sec,
        gate_path=args.gate_path or None,
        resume=args.resume,
        workers=args.workers,
    )
    return 0 if manifest.get("final") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
