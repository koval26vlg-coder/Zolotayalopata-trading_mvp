from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pit_membership_drift_execution_probe import (
    MANIFEST_MODE,
    MANIFEST_SCHEMA,
    SAMPLE_SCHEMA,
    SUPPORTED_VENUES,
    validate_execution_probe_plan,
)


PairFetcher = Callable[[str], dict[str, Any]]


def collect_execution_probe(
    plan_path: str | Path,
    output_root: str | Path,
    run_id: str,
    *,
    resume: bool = False,
    pair_fetcher: PairFetcher | None = None,
    monotonic_fn: Callable[[], float] = time.monotonic,
    wall_time_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    plan_target = Path(plan_path).expanduser().resolve()
    root = Path(output_root).expanduser().resolve()
    if not run_id.strip():
        raise ValueError("execution-probe run_id is required")
    validation = validate_execution_probe_plan(plan_target)
    plan = _load_json(plan_target)
    contract = plan["collection_contract"]
    candidates = validation["candidate_bases"]
    duration_sec = float(contract["duration_sec"])
    interval_sec = float(contract["interval_sec"])
    run_dir = root / run_id
    sample_path = run_dir / "samples.jsonl"
    manifest_path = run_dir / "manifest.json"
    lock = _CollectorLock(run_dir / "collector.lock", run_id)
    should_stop = stop_requested or (lambda: False)

    if run_dir.exists() and any(run_dir.iterdir()) and not resume:
        raise FileExistsError(f"execution-probe run_id already has artifacts: {run_id}")
    if resume and not manifest_path.is_file():
        raise FileNotFoundError(f"execution-probe resume manifest not found: {manifest_path}")
    run_dir.mkdir(parents=True, exist_ok=True)
    lock.acquire()
    try:
        rows = _scan_samples(sample_path, run_id, validation["plan_hash"], candidates)
        if resume:
            prior = _load_json(manifest_path)
            _validate_resume_manifest(prior, plan_target, validation, rows)
            elapsed_before = float(prior.get("elapsed_active_sec") or 0.0)
            resume_count = int(prior.get("resume_count") or 0) + 1
            started_at_utc = str(prior.get("started_at_utc") or _iso_utc(wall_time_fn()))
        else:
            if rows:
                raise ValueError("new execution-probe run unexpectedly has samples")
            elapsed_before = 0.0
            resume_count = 0
            started_at_utc = _iso_utc(wall_time_fn())
        if elapsed_before >= duration_sec:
            raise ValueError("cannot resume an execution probe whose active duration is already complete")

        fetch = pair_fetcher or _build_public_pair_fetcher(plan)
        attempt_index = len(rows)
        valid_count = sum((row.get("pair") or {}).get("fully_valid") is True for row in rows)
        error_count = sum(bool(row.get("fetch_error")) for row in rows)
        session_started = monotonic_fn()
        session_attempts = 0
        final = False
        stop_reason = "stop_requested"
        manifest = _manifest(
            plan_target=plan_target,
            validation=validation,
            run_id=run_id,
            sample_path=sample_path,
            started_at_utc=started_at_utc,
            elapsed_active_sec=elapsed_before,
            attempts=attempt_index,
            valid_count=valid_count,
            error_count=error_count,
            resume_count=resume_count,
            final=False,
            stop_reason="running",
        )
        _atomic_write_json(manifest_path, manifest)

        while True:
            elapsed = elapsed_before + max(0.0, monotonic_fn() - session_started)
            if elapsed >= duration_sec:
                final = True
                stop_reason = "duration_complete"
                break
            if should_stop():
                break
            base = candidates[attempt_index % len(candidates)]
            started = wall_time_fn()
            fetch_error: str | None = None
            try:
                pair = fetch(base)
                if not isinstance(pair, dict):
                    raise TypeError("pair fetcher must return a JSON object")
            except Exception as exc:  # Network failures are evidence, not a partial accepted sample.
                fetch_error = f"{type(exc).__name__}: {exc}"[:1000]
                pair = {
                    "base": base,
                    "fully_valid": False,
                    "invalid_reasons": ["public_pair_fetch_failed"],
                    "venues": {},
                    "depth_fills": {},
                }
            finished = wall_time_fn()
            row = {
                "schema": SAMPLE_SCHEMA,
                "run_id": run_id,
                "plan_hash": validation["plan_hash"],
                "attempt_index": attempt_index,
                "base": base,
                "started_at_utc": _iso_utc(started),
                "finished_at_utc": _iso_utc(finished),
                "fetch_error": fetch_error,
                "pair": pair,
            }
            _append_jsonl(sample_path, row)
            rows.append(row)
            attempt_index += 1
            session_attempts += 1
            valid_count += int(pair.get("fully_valid") is True)
            error_count += int(fetch_error is not None)

            elapsed = min(duration_sec, elapsed_before + max(0.0, monotonic_fn() - session_started))
            manifest = _manifest(
                plan_target=plan_target,
                validation=validation,
                run_id=run_id,
                sample_path=sample_path,
                started_at_utc=started_at_utc,
                elapsed_active_sec=elapsed,
                attempts=attempt_index,
                valid_count=valid_count,
                error_count=error_count,
                resume_count=resume_count,
                final=False,
                stop_reason="running",
            )
            _atomic_write_json(manifest_path, manifest)

            target_elapsed = min(duration_sec, elapsed_before + session_attempts * interval_sec)
            current_elapsed = elapsed_before + max(0.0, monotonic_fn() - session_started)
            if target_elapsed > current_elapsed:
                sleep_fn(target_elapsed - current_elapsed)

        elapsed = min(duration_sec, elapsed_before + max(0.0, monotonic_fn() - session_started))
        manifest = _manifest(
            plan_target=plan_target,
            validation=validation,
            run_id=run_id,
            sample_path=sample_path,
            started_at_utc=started_at_utc,
            elapsed_active_sec=elapsed,
            attempts=attempt_index,
            valid_count=valid_count,
            error_count=error_count,
            resume_count=resume_count,
            final=final,
            stop_reason=stop_reason,
            finished_at_utc=_iso_utc(wall_time_fn()) if final else None,
        )
        _atomic_write_json(manifest_path, manifest)
        return manifest
    except BaseException as exc:
        if "manifest_path" in locals():
            failure = {
                "schema": MANIFEST_SCHEMA,
                "mode": MANIFEST_MODE,
                "run_id": run_id,
                "plan_path": str(plan_target),
                "plan_file_sha256": validation["plan_file_sha256"],
                "plan_hash": validation["plan_hash"],
                "sample_path": str(sample_path),
                "sample_file_sha256": _sha256_file(sample_path) if sample_path.is_file() else None,
                "attempted_snapshots": len(rows) if "rows" in locals() else 0,
                "valid_snapshots": valid_count if "valid_count" in locals() else 0,
                "fetch_errors": error_count if "error_count" in locals() else 0,
                "elapsed_active_sec": (
                    min(duration_sec, elapsed_before + max(0.0, monotonic_fn() - session_started))
                    if "session_started" in locals()
                    else 0.0
                ),
                "resume_count": resume_count if "resume_count" in locals() else 0,
                "final": False,
                "incomplete": True,
                "stop_reason": "collector_exception",
                "error": f"{type(exc).__name__}: {exc}"[:2000],
                "network_access": pair_fetcher is None,
                "grid_search": False,
                "retune": False,
                "paper_forward": False,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
            }
            _atomic_write_json(manifest_path, failure)
        raise
    finally:
        lock.release()


def _build_public_pair_fetcher(plan: dict[str, Any]) -> PairFetcher:
    from concurrent.futures import ThreadPoolExecutor

    from funding import build_funding_clients
    from perp_collector import build_perp_rest_clients
    from pit_cross_venue_forward_probe import (
        ForwardProbeConfig,
        _collect_venue_evidence,
        _contracts_by_base,
        _failed_venue_evidence,
        _missing_contract_evidence,
        evaluate_pair_evidence,
    )

    contract = plan["collection_contract"]
    funding_clients = build_funding_clients(list(SUPPORTED_VENUES), timeout_sec=10)
    rest_clients = build_perp_rest_clients(list(SUPPORTED_VENUES), timeout_sec=10)
    for client in [*funding_clients.values(), *rest_clients.values()]:
        session = getattr(client, "session", None)
        if session is not None:
            session.trust_env = False
    config = ForwardProbeConfig(
        target_notional_quote=float(contract["target_notional_quote_per_leg"]),
        depth_limit=int(contract["depth_limit"]),
        timeout_sec=10,
        max_index_divergence_bps=float(contract["max_index_divergence_bps"]),
        max_mark_index_divergence_bps=float(contract["max_mark_index_divergence_bps"]),
        max_quote_age_sec=float(contract["max_quote_age_sec"]),
        max_cross_venue_skew_sec=float(contract["max_cross_venue_skew_sec"]),
        min_provisional_identity_pairs=1,
        min_fully_valid_pairs=1,
        progress=False,
    )
    candidates = list(plan["instrument_scope"]["candidate_bases"])
    contract_maps: dict[str, dict[str, list[Any]]] = {}
    for exchange in SUPPORTED_VENUES:
        try:
            contract_maps[exchange] = _contracts_by_base(
                funding_clients[exchange].fetch_contracts(),
                candidates,
            )
        except Exception as exc:
            raise RuntimeError(f"initial contract discovery failed for {exchange}: {exc}") from exc

    def fetch(base: str) -> dict[str, Any]:
        mexc_client = funding_clients.get("mexc")
        if mexc_client is not None and hasattr(mexc_client, "_tickers_cache"):
            setattr(mexc_client, "_tickers_cache", None)
            setattr(mexc_client, "_tickers_cache_ts", 0.0)
        metadata_snapshot_ts = time.time()
        venue_rows: dict[str, dict[str, Any]] = {}
        futures: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="membership-probe") as pool:
            for exchange in SUPPORTED_VENUES:
                matches = contract_maps.get(exchange, {}).get(base, [])
                if len(matches) != 1:
                    venue_rows[exchange] = _missing_contract_evidence(exchange, base, matches)
                    continue
                futures[exchange] = pool.submit(
                    _collect_venue_evidence,
                    matches[0],
                    funding_clients[exchange],
                    rest_clients[exchange],
                    config,
                    metadata_snapshot_ts,
                    time.time,
                )
            for exchange, future in futures.items():
                matches = contract_maps[exchange][base]
                try:
                    venue_rows[exchange] = future.result()
                except Exception as exc:
                    venue_rows[exchange] = _failed_venue_evidence(exchange, base, matches[0], exc)
        return evaluate_pair_evidence(
            base,
            venue_rows.get("mexc"),
            venue_rows.get("gateio"),
            config,
        )

    return fetch


def _manifest(
    *,
    plan_target: Path,
    validation: dict[str, Any],
    run_id: str,
    sample_path: Path,
    started_at_utc: str,
    elapsed_active_sec: float,
    attempts: int,
    valid_count: int,
    error_count: int,
    resume_count: int,
    final: bool,
    stop_reason: str,
    finished_at_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "mode": MANIFEST_MODE,
        "run_id": run_id,
        "plan_path": str(plan_target),
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": validation["plan_hash"],
        "sample_path": str(sample_path),
        "sample_file_sha256": _sha256_file(sample_path) if sample_path.is_file() else None,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "elapsed_active_sec": round(float(elapsed_active_sec), 6),
        "attempted_snapshots": attempts,
        "valid_snapshots": valid_count,
        "fetch_errors": error_count,
        "resume_count": resume_count,
        "final": final,
        "incomplete": not final,
        "stop_reason": stop_reason,
        "network_access": True,
        "grid_search": False,
        "retune": False,
        "paper_forward": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
    }


def _validate_resume_manifest(
    manifest: dict[str, Any],
    plan_path: Path,
    validation: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("mode") != MANIFEST_MODE:
        raise ValueError("execution-probe resume manifest schema/mode mismatch")
    if manifest.get("final") is True:
        raise ValueError("cannot resume a final execution probe")
    if Path(str(manifest.get("plan_path") or "")).expanduser().resolve() != plan_path:
        raise ValueError("execution-probe resume plan path mismatch")
    if manifest.get("plan_file_sha256") != validation["plan_file_sha256"]:
        raise ValueError("execution-probe resume plan file hash mismatch")
    if manifest.get("plan_hash") != validation["plan_hash"]:
        raise ValueError("execution-probe resume plan hash mismatch")
    if int(manifest.get("attempted_snapshots") or 0) != len(rows):
        raise ValueError("execution-probe resume manifest is inconsistent with immutable samples")
    sample_path = Path(str(manifest.get("sample_path") or "")).expanduser().resolve()
    if sample_path.is_file() and manifest.get("sample_file_sha256") != _sha256_file(sample_path):
        raise ValueError("execution-probe resume sample hash mismatch")


def _scan_samples(
    path: Path,
    run_id: str,
    plan_hash: str,
    candidates: list[str],
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid execution-probe JSONL {path}:{line_number}: {exc}") from exc
            index = len(rows)
            if row.get("schema") != SAMPLE_SCHEMA or row.get("run_id") != run_id:
                raise ValueError("execution-probe resume sample schema/run mismatch")
            if row.get("plan_hash") != plan_hash or int(row.get("attempt_index", -1)) != index:
                raise ValueError("execution-probe resume sample provenance/index mismatch")
            if str(row.get("base") or "").upper() != candidates[index % len(candidates)]:
                raise ValueError("execution-probe resume sample round-robin mismatch")
            rows.append(row)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class _CollectorLock:
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            raise RuntimeError(f"execution-probe collector lock already exists for run_id={self.run_id}") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"run_id": self.run_id, "pid": os.getpid()}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                # Windows scanners can briefly hold a freshly fsynced file.
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect a bounded public PIT membership-drift execution probe")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirmed-public-probe", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirmed_public_probe:
        raise ValueError("public execution probe requires --confirmed-public-probe")
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, request_stop)
        except (OSError, ValueError):
            pass
    manifest = collect_execution_probe(
        args.plan,
        args.output_root,
        args.run_id,
        resume=args.resume,
        stop_requested=stop_event.is_set,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0 if manifest.get("final") is True else 130


if __name__ == "__main__":
    raise SystemExit(main())
