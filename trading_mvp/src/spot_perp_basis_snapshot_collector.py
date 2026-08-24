from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import shutil
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SRC_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SRC_DIR.parent.parent
for _p in (_SRC_DIR, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import requests

from spot_perp_basis_public_probe import (
    candidate_pairs_from_preflight,
    load_preflight,
    _probe_mexc,
    _probe_gateio,
    paired_base_ok,
)


MANIFEST_SCHEMA = "spot_perp_basis_snapshot_manifest_v1"


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


def _free_disk_gib(path: Path) -> float:
    probe = path.expanduser().resolve()
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1024**3)


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
            self.acquired = True
            return
        raise RuntimeError(f"could not acquire lock at {self.path}")

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def update_active_run_gate(
    *,
    gate_path: Path,
    run_id: str,
    status: str,
    manifest_path: Path,
    snapshots_path: Path,
    completed_cycles: int,
    total_cycles: int,
    rows: int,
    errors: int,
    stop_reason: str | None = None,
    final: bool = False,
    monitor_pid: int | None = None,
) -> None:
    if not gate_path.exists():
        return
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except Exception:
        return
    gate["run_id"] = run_id
    gate["status"] = status
    gate["updated_at"] = utc_now()
    gate["manifest_path"] = str(manifest_path)
    gate["output_path"] = str(snapshots_path)
    gate["completed_cycles"] = completed_cycles
    gate["total_cycles"] = total_cycles
    gate["rows"] = rows
    gate["errors"] = errors
    gate["final"] = final
    gate["stop_reason"] = stop_reason or gate.get("stop_reason")
    if monitor_pid:
        gate["monitor_pid"] = monitor_pid
    if final and status == "READY_FOR_POSTPROCESS":
        gate["next_goal_decision"] = "SPOT_PERP_BASIS_SNAPSHOT_COLLECT_READY_FOR_EVALUATION"
        gate["next_step_after_ready"] = "Run spot/perp basis mean-reversion evaluator and convergence analysis on collected snapshots."
    atomic_write_json(gate_path, gate)


def collect_snapshot_cycle(
    session: requests.Session,
    candidates: list[dict[str, Any]],
    depth_limit: int,
    timeout_sec: int,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    error_count = 0
    cycle_ts = datetime.now(timezone.utc).isoformat()
    for candidate in candidates:
        venues: dict[str, Any] = {}
        for exchange, probe in (("mexc", _probe_mexc), ("gateio", _probe_gateio)):
            try:
                venues[exchange] = probe(session, candidate, depth_limit, timeout_sec)
            except Exception as exc:
                error_count += 1
                venues[exchange] = {
                    "exchange": exchange,
                    "base": candidate["base"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        base = candidate["base"]
        mexc = venues.get("mexc") or {}
        gate = venues.get("gateio") or {}
        basis_mexc = None
        basis_gate = None
        if mexc.get("ok") and mexc.get("spot", {}).get("mid") and mexc.get("perp", {}).get("mid_or_mark"):
            s_mid = mexc["spot"]["mid"]
            p_mid = mexc["perp"]["mid_or_mark"]
            basis_mexc = (p_mid - s_mid) / s_mid * 10000.0
        if gate.get("ok") and gate.get("spot", {}).get("mid") and gate.get("perp", {}).get("mid_or_mark"):
            s_mid = gate["spot"]["mid"]
            p_mid = gate["perp"]["mid_or_mark"]
            basis_gate = (p_mid - s_mid) / s_mid * 10000.0

        record = {
            "timestamp": cycle_ts,
            "base": base,
            "quote": "USDT",
            "basis_bps_mexc": basis_mexc,
            "basis_bps_gateio": basis_gate,
            "venues": venues,
            "paired_ok": paired_base_ok({"base": base, "quote": "USDT", "venues": venues}),
        }
        rows.append(record)
    return rows, error_count


def run_snapshot_collector(
    *,
    preflight_path: Path,
    output_root: Path,
    run_id: str,
    hours: float,
    interval_sec: int,
    timeout_sec: int,
    depth_limit: int,
    gate_path: Path,
    target_bases: list[str] | None = None,
    max_cycles: int | None = None,
) -> None:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshots_path = run_dir / "snapshots.jsonl"
    manifest_path = run_dir / "manifest.json"
    lock_path = run_dir / "collector.lock"

    lock = CollectorLock(lock_path, run_id)
    lock.acquire()

    preflight = load_preflight(preflight_path)
    all_candidates = candidate_pairs_from_preflight(preflight, max_bases=50)
    if target_bases:
        allowed = {b.strip().upper() for b in target_bases}
        candidates = [c for c in all_candidates if c["base"].upper() in allowed]
    else:
        candidates = all_candidates[:6]

    total_duration_sec = int(round(hours * 3600))
    total_expected_cycles = max(1, total_duration_sec // interval_sec)
    if max_cycles is not None:
        total_expected_cycles = min(total_expected_cycles, max_cycles)

    session = requests.Session()
    session.trust_env = False

    stop_requested = False

    def handle_signal(sig: int, frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except Exception:
        pass

    completed_cycles = 0
    total_rows = 0
    total_errors = 0
    start_time = time.monotonic()

    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            completed_cycles = int(existing.get("completed_cycles") or 0)
            total_rows = int(existing.get("total_rows") or 0)
            total_errors = int(existing.get("total_errors") or 0)
            manifest = existing
            manifest["status"] = "RUNNING"
            manifest["final"] = False
            manifest["updated_at_utc"] = utc_now()
        except Exception:
            manifest = None
    else:
        manifest = None

    if manifest is None:
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "run_id": run_id,
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "status": "RUNNING",
            "final": False,
            "target_bases": [c["base"] for c in candidates],
            "planned_hours": hours,
            "interval_sec": interval_sec,
            "timeout_sec": timeout_sec,
            "depth_limit": depth_limit,
            "expected_cycles": total_expected_cycles,
            "completed_cycles": completed_cycles,
            "total_rows": total_rows,
            "total_errors": total_errors,
            "snapshots_path": str(snapshots_path),
            "manifest_path": str(manifest_path),
        }
    atomic_write_json(manifest_path, manifest)
    update_active_run_gate(
        gate_path=gate_path,
        run_id=run_id,
        status="RUNNING",
        manifest_path=manifest_path,
        snapshots_path=snapshots_path,
        completed_cycles=completed_cycles,
        total_cycles=total_expected_cycles,
        rows=total_rows,
        errors=total_errors,
        monitor_pid=os.getpid(),
    )

    try:
        while completed_cycles < total_expected_cycles and not stop_requested:
            cycle_start = time.monotonic()
            rows, errs = collect_snapshot_cycle(
                session=session,
                candidates=candidates,
                depth_limit=depth_limit,
                timeout_sec=timeout_sec,
            )
            append_jsonl(snapshots_path, rows)
            completed_cycles += 1
            total_rows += len(rows)
            total_errors += errs

            manifest["updated_at_utc"] = utc_now()
            manifest["completed_cycles"] = completed_cycles
            manifest["total_rows"] = total_rows
            manifest["total_errors"] = total_errors
            atomic_write_json(manifest_path, manifest)

            update_active_run_gate(
                gate_path=gate_path,
                run_id=run_id,
                status="RUNNING",
                manifest_path=manifest_path,
                snapshots_path=snapshots_path,
                completed_cycles=completed_cycles,
                total_cycles=total_expected_cycles,
                rows=total_rows,
                errors=total_errors,
                monitor_pid=os.getpid(),
            )

            print(
                f"[{utc_now()}] Cycle {completed_cycles}/{total_expected_cycles} done. "
                f"Rows: {total_rows}, Errors: {total_errors}. Bases: {[c['base'] for c in candidates]}"
            )

            elapsed = time.monotonic() - cycle_start
            remaining_sleep = interval_sec - elapsed
            if remaining_sleep > 0 and completed_cycles < total_expected_cycles and not stop_requested:
                time.sleep(remaining_sleep)

        status = "READY_FOR_POSTPROCESS" if completed_cycles >= total_expected_cycles else "STOPPED_INCOMPLETE"
        manifest["status"] = status
        manifest["final"] = True
        manifest["completed_at_utc"] = utc_now()
        atomic_write_json(manifest_path, manifest)

        update_active_run_gate(
            gate_path=gate_path,
            run_id=run_id,
            status=status,
            manifest_path=manifest_path,
            snapshots_path=snapshots_path,
            completed_cycles=completed_cycles,
            total_cycles=total_expected_cycles,
            rows=total_rows,
            errors=total_errors,
            stop_reason="completed" if status == "READY_FOR_POSTPROCESS" else "stopped_early",
            final=True,
        )
    finally:
        lock.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="spot/perp basis snapshot collector")
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--depth-limit", type=int, default=5)
    parser.add_argument("--gate-path", required=True)
    parser.add_argument("--bases", default="AERO,B,BAS,BIRB,DEEP,ESPORTS")
    parser.add_argument("--max-cycles", type=int, default=None)
    args = parser.parse_args()

    bases = [b.strip().strip('"\'') for b in args.bases.split(",") if b.strip().strip('"\'')]
    run_snapshot_collector(
        preflight_path=Path(str(args.preflight).strip().strip('"\'')),
        output_root=Path(str(args.output_root).strip().strip('"\'')),
        run_id=str(args.run_id).strip().strip('"\''),
        hours=float(args.hours),
        interval_sec=int(args.interval_sec),
        timeout_sec=int(args.timeout_sec),
        depth_limit=int(args.depth_limit),
        gate_path=Path(str(args.gate_path).strip().strip('"\'')),
        target_bases=bases,
        max_cycles=args.max_cycles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
