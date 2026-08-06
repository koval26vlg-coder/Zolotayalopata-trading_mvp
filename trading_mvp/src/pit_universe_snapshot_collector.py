from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import shutil
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pit_universe_public_probe import run_public_probe


EXPECTED_EXCHANGES = {"mexc", "gateio"}
MANIFEST_SCHEMA = "pit_universe_snapshot_manifest_v2"
STATE_SCHEMA = "pit_universe_state_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    atomic_write_json(path, manifest)


def _free_disk_gib(path: Path) -> float:
    probe = path.expanduser().resolve()
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1024**3)


def build_paths(output_root: Path, run_id: str) -> dict[str, Path]:
    run_dir = output_root / run_id
    return {
        "run_dir": run_dir,
        "snapshots": run_dir / "snapshots.jsonl",
        "cycles": run_dir / "cycles.jsonl",
        "manifest": run_dir / "manifest.json",
        "state": run_dir / "universe_state.json",
        "lock": run_dir / "collector.lock",
    }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class CollectorLock:
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    owner_pid = int(payload.get("pid") or 0)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    owner_pid = 0
                if _pid_alive(owner_pid):
                    raise RuntimeError(f"collector already active for run_id={self.run_id}, pid={owner_pid}")
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"run_id": self.run_id, "pid": os.getpid(), "created_at_utc": utc_now()}, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.acquired = True
            return
        raise RuntimeError(f"could not acquire collector lock for run_id={self.run_id}")

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if int(payload.get("pid") or 0) == os.getpid():
            self.path.unlink(missing_ok=True)
        self.acquired = False


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _scan_snapshots(path: Path) -> tuple[int, int, dict[str, dict[str, Any]]]:
    if not path.exists():
        return 0, 0, {}
    rows_total = 0
    max_cycle = 0
    rebuilt_state: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            rows_total += 1
            max_cycle = max(max_cycle, int(row.get("cycle") or 0))
            exchange = str(row.get("exchange") or "")
            symbol = str(row.get("symbol") or "")
            if not exchange or not symbol:
                continue
            key = f"{exchange}|{symbol}"
            previous = rebuilt_state.get(key, {})
            first_seen = row.get("first_seen_ts") or previous.get("first_seen_ts") or row.get("snapshot_ts")
            if row.get("tombstone") or row.get("observed_now") is False:
                last_seen = previous.get("last_seen_ts") or row.get("last_seen_ts")
                missing_since = previous.get("missing_since_ts") or row.get("missing_since_ts") or row.get("snapshot_ts")
            else:
                last_seen = row.get("last_seen_ts") or row.get("snapshot_ts")
                missing_since = None
            rebuilt_state[key] = {
                "row": {k: v for k, v in row.items() if k not in {"run_id", "cycle", "cycle_started_at_utc", "collector_received_at_utc", "probe_decision"}},
                "first_seen_ts": first_seen,
                "last_seen_ts": last_seen,
                "missing_since_ts": missing_since,
                "observed_now": not bool(row.get("tombstone")) and row.get("observed_now") is not False,
            }
    return rows_total, max_cycle, rebuilt_state


def _scan_cycle_journal(path: Path, run_id: str) -> tuple[int, int]:
    if not path.exists():
        raise ValueError(f"resume cycle journal missing: {path}")
    row_count = 0
    max_cycle = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid cycle journal JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"invalid cycle journal row at {path}:{line_number}")
            if str(row.get("run_id") or "") != run_id:
                raise ValueError(f"cycle journal run_id mismatch at {path}:{line_number}")
            cycle = int(row.get("cycle") or 0)
            if cycle != max_cycle + 1:
                raise ValueError(
                    f"cycle journal is not contiguous at {path}:{line_number}: expected={max_cycle + 1}, observed={cycle}"
                )
            row_count += 1
            max_cycle = cycle
    return row_count, max_cycle


def _load_state(path: Path, snapshots_path: Path) -> dict[str, dict[str, Any]]:
    if path.exists():
        payload = _load_json(path)
        symbols = payload.get("symbols")
        if isinstance(symbols, dict):
            return {str(key): dict(value) for key, value in symbols.items() if isinstance(value, dict)}
    _, _, rebuilt = _scan_snapshots(snapshots_path)
    return rebuilt


def _write_state(path: Path, run_id: str, state: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(
        path,
        {
            "schema": STATE_SCHEMA,
            "run_id": run_id,
            "updated_at_utc": utc_now(),
            "symbols": state,
        },
    )


def _successful_exchanges(report: dict[str, Any]) -> set[str]:
    errors = {str(name) for name in (report.get("errors") or {})}
    exchange_summary = ((report.get("summary") or {}).get("exchanges") or {})
    if isinstance(exchange_summary, dict) and exchange_summary:
        return {
            exchange
            for exchange in EXPECTED_EXCHANGES
            if exchange not in errors
            and isinstance(exchange_summary.get(exchange), dict)
            and bool(exchange_summary[exchange].get("pass_min_contracts"))
        }
    return EXPECTED_EXCHANGES - errors


def _apply_universe_state(
    rows: list[dict[str, Any]],
    state: dict[str, dict[str, Any]],
    successful_exchanges: set[str],
    snapshot_ts: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    observed_keys: set[str] = set()
    for source in rows:
        row = dict(source)
        exchange = str(row.get("exchange") or "")
        symbol = str(row.get("symbol") or "")
        if not exchange or not symbol:
            continue
        key = f"{exchange}|{symbol}"
        observed_keys.add(key)
        previous = state.get(key, {})
        observed_ts = str(row.get("snapshot_ts") or snapshot_ts)
        first_seen = previous.get("first_seen_ts") or observed_ts
        row.update(
            {
                "first_seen_ts": first_seen,
                "last_seen_ts": observed_ts,
                "missing_since_ts": None,
                "observed_now": True,
                "tombstone": False,
                "presence_state": "observed",
            }
        )
        state[key] = {
            "row": dict(row),
            "first_seen_ts": first_seen,
            "last_seen_ts": observed_ts,
            "missing_since_ts": None,
            "observed_now": True,
        }
        output.append(row)

    for key, previous in list(state.items()):
        if key in observed_keys:
            continue
        exchange, _, symbol = key.partition("|")
        if exchange not in successful_exchanges:
            continue
        prior_row = dict(previous.get("row") or {})
        missing_since = previous.get("missing_since_ts") or snapshot_ts
        tombstone = {
            **prior_row,
            "snapshot_ts": snapshot_ts,
            "exchange": exchange,
            "symbol": symbol,
            "status": "missing",
            "listed_now": False,
            "inactive_or_delisted": True,
            "volume_24h_quote": None,
            "bid_price": None,
            "ask_price": None,
            "mid_price": None,
            "spread_bps": None,
            "bid_size_contracts": None,
            "ask_size_contracts": None,
            "mark_price": None,
            "index_price": None,
            "funding_rate": None,
            "funding_interval_sec": None,
            "funding_next_apply_ts": None,
            "raw_status": None,
            "first_seen_ts": previous.get("first_seen_ts"),
            "last_seen_ts": previous.get("last_seen_ts"),
            "missing_since_ts": missing_since,
            "observed_now": False,
            "tombstone": True,
            "presence_state": "missing",
        }
        state[key] = {
            "row": dict(tombstone),
            "first_seen_ts": previous.get("first_seen_ts"),
            "last_seen_ts": previous.get("last_seen_ts"),
            "missing_since_ts": missing_since,
            "observed_now": False,
        }
        output.append(tombstone)
    return output


def _sleep_interruptibly(seconds: float, stop_requested: Callable[[], bool]) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while not stop_requested():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def _next_cycle_sleep_sec(interval_sec: float, cycle_elapsed_sec: float, remaining_sec: float) -> float:
    return max(0.0, min(float(remaining_sec), float(interval_sec) - float(cycle_elapsed_sec)))


def collect_snapshots(
    *,
    output_root: Path,
    run_id: str,
    duration_sec: int,
    interval_sec: int,
    timeout_sec: int,
    min_contracts_per_exchange: int,
    min_free_disk_gib: float = 0.0,
    resume: bool = False,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if duration_sec < 0 or interval_sec <= 0 or timeout_sec <= 0 or min_contracts_per_exchange <= 0:
        raise ValueError("duration_sec must be non-negative and all other numeric parameters must be positive")
    if min_free_disk_gib < 0:
        raise ValueError("min_free_disk_gib must be non-negative")
    stop_requested = stop_requested or (lambda: False)
    paths = build_paths(output_root, run_id)
    failure_stage = "acquire_collector_lock"
    lock = CollectorLock(paths["lock"], run_id)
    lock.acquire()
    session_started_mono = time.monotonic()
    interrupted = False
    failure: BaseException | None = None

    try:
        failure_stage = "load_or_initialize_manifest"
        manifest_exists = paths["manifest"].exists()
        if manifest_exists and not resume:
            raise FileExistsError(f"run_id={run_id} already exists; pass resume=True/--resume explicitly")
        if resume and not manifest_exists:
            raise FileNotFoundError(f"cannot resume run_id={run_id}: manifest does not exist")

        if resume:
            resume_manifest = _load_json(paths["manifest"])
            if resume_manifest.get("schema") != MANIFEST_SCHEMA:
                raise ValueError(
                    f"resume schema mismatch: expected={MANIFEST_SCHEMA}, observed={resume_manifest.get('schema')!r}; "
                    "start a new clean run_id"
                )
            if resume_manifest.get("mode") != "pit_universe_snapshot_collect" or resume_manifest.get("run_id") != run_id:
                raise ValueError("resume manifest mode/run_id mismatch")
            if bool(resume_manifest.get("final")):
                raise ValueError(f"cannot resume final run_id={run_id}")
            for name, requested in (
                ("interval_sec", interval_sec),
                ("timeout_sec", timeout_sec),
                ("min_contracts_per_exchange", min_contracts_per_exchange),
            ):
                existing = int(resume_manifest.get(name, requested))
                if existing != requested:
                    raise ValueError(f"resume parameter mismatch for {name}: manifest={existing}, requested={requested}")
            existing_duration = int(resume_manifest.get("duration_sec", duration_sec))
            if existing_duration != duration_sec:
                raise ValueError(
                    f"resume parameter mismatch for duration_sec: manifest={existing_duration}, requested={duration_sec}"
                )
            scanned_rows, scanned_cycle, _ = _scan_snapshots(paths["snapshots"])
            manifest_cycle = int(resume_manifest.get("cycle_count") or 0)
            if manifest_cycle > 0:
                journal_rows, journal_cycle = _scan_cycle_journal(paths["cycles"], run_id)
                if journal_rows != journal_cycle:
                    raise ValueError(
                        f"cycle journal count mismatch: rows={journal_rows}, max_cycle={journal_cycle}"
                    )
                if manifest_cycle > journal_cycle:
                    raise ValueError(
                        f"manifest cycle exceeds cycle journal: manifest={manifest_cycle}, journal={journal_cycle}"
                    )
                if scanned_cycle > journal_cycle:
                    raise ValueError(
                        f"snapshot cycle exceeds cycle journal: snapshots={scanned_cycle}, journal={journal_cycle}"
                    )
            else:
                journal_cycle = 0
            manifest = resume_manifest
            cycle = max(manifest_cycle, journal_cycle, scanned_cycle)
            rows_total = scanned_rows
            errors_total = int(manifest.get("errors_total") or 0)
            depth_errors_total = int(manifest.get("depth_errors_total") or 0)
            depth_error_cycles = int(manifest.get("depth_error_cycles") or 0)
            decisions = {str(k): int(v) for k, v in (manifest.get("decisions") or {}).items()}
            elapsed_before = manifest.get("elapsed_active_sec")
            if elapsed_before is None:
                elapsed_before = min(float(duration_sec), max(0, cycle - 1) * float(interval_sec))
                manifest["resume_migration"] = "elapsed_active_sec_estimated_from_completed_cycles"
            elapsed_before = float(elapsed_before)
            manifest.update(
                {
                    "updated_at_utc": utc_now(),
                    "finished_at_utc": None,
                    "stopped_at_utc": None,
                    "final": False,
                    "incomplete": False,
                    "status": "RUNNING",
                    "stop_condition": None,
                    "stop_reason": None,
                    "cycle_count": cycle,
                    "rows_total": rows_total,
                    "resume_count": int(manifest.get("resume_count") or 0) + 1,
                    "last_resume_at_utc": utc_now(),
                    "snapshots_path": str(paths["snapshots"]),
                    "cycles_path": str(paths["cycles"]),
                    "state_path": str(paths["state"]),
                    "min_free_disk_gib": float(min_free_disk_gib),
                }
            )
        else:
            started_at = utc_now()
            cycle = 0
            rows_total = 0
            errors_total = 0
            depth_errors_total = 0
            depth_error_cycles = 0
            decisions: dict[str, int] = {}
            elapsed_before = 0.0
            manifest = {
                "schema": MANIFEST_SCHEMA,
                "mode": "pit_universe_snapshot_collect",
                "run_id": run_id,
                "started_at_utc": started_at,
                "updated_at_utc": started_at,
                "finished_at_utc": None,
                "stopped_at_utc": None,
                "final": False,
                "incomplete": False,
                "status": "RUNNING",
                "research_only": True,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
                "duration_sec": duration_sec,
                "duration_basis": "active_runtime",
                "elapsed_active_sec": 0.0,
                "interval_sec": interval_sec,
                "timeout_sec": timeout_sec,
                "min_contracts_per_exchange": min_contracts_per_exchange,
                "cycle_count": 0,
                "rows_total": 0,
                "errors_total": 0,
                "depth_errors_total": 0,
                "depth_error_cycles": 0,
                "decisions": {},
                "resume_count": 0,
                "snapshots_path": str(paths["snapshots"]),
                "cycles_path": str(paths["cycles"]),
                "state_path": str(paths["state"]),
                "min_free_disk_gib": float(min_free_disk_gib),
            }

        failure_stage = "load_universe_state"
        state = _load_state(paths["state"], paths["snapshots"])
        failure_stage = "write_initial_manifest"
        write_manifest(paths["manifest"], manifest)
        remaining_active_sec = max(0.0, float(duration_sec) - elapsed_before)
        deadline = time.monotonic() + remaining_active_sec
        cycles_this_session = 0

        try:
            while (time.monotonic() < deadline or cycles_this_session == 0) and not stop_requested():
                failure_stage = "disk_guard"
                free_disk_gib = _free_disk_gib(output_root)
                manifest["last_free_disk_gib"] = round(free_disk_gib, 3)
                if free_disk_gib < float(min_free_disk_gib):
                    write_manifest(paths["manifest"], manifest)
                    raise RuntimeError(
                        "disk_space_below_threshold: "
                        f"free_gib={free_disk_gib:.3f} required_gib={float(min_free_disk_gib):.3f}"
                    )
                cycle += 1
                cycles_this_session += 1
                cycle_started_mono = time.monotonic()
                cycle_started_at = utc_now()
                failure_stage = "public_probe"
                report = run_public_probe(
                    output_path=None,
                    min_contracts_per_exchange=min_contracts_per_exchange,
                    timeout_sec=timeout_sec,
                    include_mexc_depth=True,
                )
                decision = str(report.get("decision") or "unknown")
                decisions[decision] = decisions.get(decision, 0) + 1
                errors = report.get("errors") or {}
                errors_total += len(errors)
                depth_errors = report.get("depth_errors") or {}
                depth_errors_total += len(depth_errors)
                if depth_errors:
                    depth_error_cycles += 1
                mexc_depth = (report.get("summary") or {}).get("mexc_depth") or {}
                source_rows = [dict(row) for row in (report.get("rows") or []) if isinstance(row, dict)]
                cycle_snapshot_ts = str(report.get("generated_at") or cycle_started_at)
                stateful_rows = _apply_universe_state(
                    source_rows,
                    state,
                    _successful_exchanges(report),
                    cycle_snapshot_ts,
                )
                rows: list[dict[str, Any]] = []
                for row in stateful_rows:
                    item = dict(row)
                    item["run_id"] = run_id
                    item["cycle"] = cycle
                    item["cycle_started_at_utc"] = cycle_started_at
                    item["collector_received_at_utc"] = utc_now()
                    item["probe_decision"] = decision
                    rows.append(item)
                failure_stage = "append_snapshots"
                append_jsonl(paths["snapshots"], rows)
                failure_stage = "write_universe_state"
                _write_state(paths["state"], run_id, state)
                successful_exchanges = sorted(_successful_exchanges(report))
                failure_stage = "append_cycle_journal"
                append_jsonl(
                    paths["cycles"],
                    [
                        {
                            "run_id": run_id,
                            "cycle": cycle,
                            "cycle_started_at_utc": cycle_started_at,
                            "cycle_finished_at_utc": utc_now(),
                            "decision": decision,
                            "source_rows": len(source_rows),
                            "output_rows": len(rows),
                            "errors": errors,
                            "depth_errors": depth_errors,
                            "mexc_depth": mexc_depth,
                            "successful_exchanges": successful_exchanges,
                        }
                    ],
                )
                rows_total += len(rows)
                manifest.update(
                    {
                        "updated_at_utc": utc_now(),
                        "elapsed_active_sec": elapsed_before + (time.monotonic() - session_started_mono),
                        "cycle_count": cycle,
                        "rows_total": rows_total,
                        "errors_total": errors_total,
                        "depth_errors_total": depth_errors_total,
                        "depth_error_cycles": depth_error_cycles,
                        "decisions": decisions,
                        "last_decision": decision,
                        "last_cycle_rows": len(rows),
                        "last_errors": errors,
                        "last_depth_errors": depth_errors,
                        "last_mexc_depth_targets": int(mexc_depth.get("targets") or 0),
                        "last_mexc_depth_complete": int(mexc_depth.get("complete") or 0),
                        "last_mexc_depth_coverage": float(mexc_depth.get("coverage") or 0.0),
                        "last_successful_exchanges": successful_exchanges,
                        "last_free_disk_gib": round(free_disk_gib, 3),
                    }
                )
                failure_stage = "write_cycle_manifest"
                write_manifest(paths["manifest"], manifest)
                failure_stage = "visible_progress_output"
                print(
                    f"[pit-universe] cycle={cycle} rows={len(rows)} total={rows_total} "
                    f"decision={decision} errors={len(errors)} depth_errors={len(depth_errors)} "
                    f"depth_coverage={float(mexc_depth.get('coverage') or 0.0):.3f}",
                    flush=True,
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                cycle_elapsed = time.monotonic() - cycle_started_mono
                sleep_sec = _next_cycle_sleep_sec(interval_sec, cycle_elapsed, remaining)
                if sleep_sec > 0:
                    failure_stage = "interval_wait"
                    _sleep_interruptibly(sleep_sec, stop_requested)
        except KeyboardInterrupt:
            interrupted = True

        interrupted = interrupted or stop_requested()
        final = not interrupted
        now = utc_now()
        manifest.update(
            {
                "updated_at_utc": now,
                "finished_at_utc": now if final else None,
                "stopped_at_utc": None if final else now,
                "final": final,
                "incomplete": not final,
                "status": "COMPLETED" if final else "STOPPED_INCOMPLETE",
                "stop_condition": "duration_sec" if final else "signal_or_user_interrupt",
                "stop_reason": None if final else "collector interrupted before requested active duration",
                "elapsed_active_sec": elapsed_before + (time.monotonic() - session_started_mono),
                "cycle_count": cycle,
                "rows_total": rows_total,
                "errors_total": errors_total,
                "depth_errors_total": depth_errors_total,
                "depth_error_cycles": depth_error_cycles,
                "decisions": decisions,
            }
        )
        failure_stage = "write_final_manifest"
        write_manifest(paths["manifest"], manifest)
        return manifest
    except BaseException as exc:
        failure = exc
        if "manifest" in locals():
            now = utc_now()
            manifest.update(
                {
                    "updated_at_utc": now,
                    "stopped_at_utc": now,
                    "final": False,
                    "incomplete": True,
                    "status": "STOPPED_INCOMPLETE",
                    "stop_condition": "collector_exception",
                    "stop_reason": f"{type(exc).__name__}: {exc}",
                    "failure_stage": str(locals().get("failure_stage") or "unknown"),
                    "exception_type": type(exc).__name__,
                    "exception_errno": getattr(exc, "errno", None),
                    "failure_traceback": traceback.format_exc(limit=20),
                    "elapsed_active_sec": float(locals().get("elapsed_before", 0.0))
                    + (time.monotonic() - session_started_mono),
                }
            )
            write_manifest(paths["manifest"], manifest)
        raise
    finally:
        lock.release()
        if failure is not None:
            try:
                print(f"[pit-universe] stopped with {type(failure).__name__}: {failure}", flush=True)
            except (OSError, ValueError):
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible PIT universe snapshot collector")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-sec", type=int, required=True)
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--min-contracts-per-exchange", type=int, default=50)
    parser.add_argument("--min-free-disk-gib", type=float, default=0.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            signal.signal(signal_value, request_stop)

    manifest = collect_snapshots(
        output_root=Path(args.output_root),
        run_id=args.run_id,
        duration_sec=args.duration_sec,
        interval_sec=args.interval_sec,
        timeout_sec=args.timeout_sec,
        min_contracts_per_exchange=args.min_contracts_per_exchange,
        min_free_disk_gib=args.min_free_disk_gib,
        resume=args.resume,
        stop_requested=stop_event.is_set,
    )
    try:
        print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    except (OSError, ValueError):
        pass
    return 0 if manifest.get("final") else 130


if __name__ == "__main__":
    raise SystemExit(main())
