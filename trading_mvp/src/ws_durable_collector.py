from __future__ import annotations

import argparse
import json
import math
import os
import signal
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ws_collector import collect_ws_markets

STATE_SCHEMA = "ws_durable_state_v1"
STITCHED_SCHEMA = "ws_collect_stitched_v1"
DEFAULT_SEGMENT_SEC = 3 * 3600
DEFAULT_HEARTBEAT_SEC = 30
STALE_HEARTBEAT_SEC = 120
# Пре-сегментный disk guard: не стартовать новый сегмент при нехватке места.
# 3h-сегмент пишет ~1.5-2 GB, дефолт с запасом. Корень disk-full 06.07.
DEFAULT_MIN_FREE_GB = 4.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def free_gb(path: str | Path) -> float:
    """Свободно ГБ на томе, где физически лежит path.

    Для junction/symlink shutil.disk_usage резолвит целевой том — измеряем
    там, куда реально пишутся данные, а не где расположена ссылка.
    """
    target = Path(path)
    while not target.exists():
        parent = target.parent
        if parent == target:
            break
        target = parent
    return shutil.disk_usage(target).free / (1024 ** 3)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Пишем через tmp+replace: смерть процесса не оставит битый state."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def parse_symbols_arg(raw: str) -> dict[str, list[str]]:
    """Формат: "mexc:AAA_USDT,BBB_USDT;gateio:CCC_USDT"."""
    result: dict[str, list[str]] = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"Ожидается 'exchange:SYM1,SYM2', получено: {chunk}")
        exchange, symbols = chunk.split(":", 1)
        items = [s.strip() for s in symbols.split(",") if s.strip()]
        if items:
            result[exchange.strip().lower()] = items
    if not result:
        raise ValueError("Пустой список символов")
    return result


def state_path_for(run_dir: Path) -> Path:
    return run_dir / "state.json"


def segment_dir_for(run_dir: Path, index: int) -> Path:
    return run_dir / f"seg_{index:03d}"


def segment_manifest_path(run_dir: Path, index: int) -> Path:
    return segment_dir_for(run_dir, index) / "manifest.json"


def _canonical_segment_dirs(run_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in run_dir.glob("seg_*")
        if path.is_dir() and len(path.name) == 7 and path.name[4:].isdigit()
    )


def _load_completed_segment_manifests(run_dir: Path, planned: int) -> dict[int, dict[str, Any]]:
    completed: dict[int, dict[str, Any]] = {}
    for index in range(1, planned + 1):
        manifest_path = segment_manifest_path(run_dir, index)
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        duration_completed = payload.get("duration_completed")
        if duration_completed is True or (
            duration_completed is None and payload.get("completed") is True
        ):
            completed[index] = payload
    return completed


def _archive_incomplete_segment_dir(run_dir: Path, index: int) -> str | None:
    """Move an incomplete retry target aside so resume does not mix raw files."""
    seg_dir = segment_dir_for(run_dir, index)
    if not seg_dir.exists():
        return None
    manifest_path = seg_dir / "manifest.json"
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            duration_completed = payload.get("duration_completed")
            if duration_completed is True or (
                duration_completed is None and payload.get("completed") is True
            ):
                return None
        except (OSError, json.JSONDecodeError):
            pass
    try:
        has_files = any(seg_dir.iterdir())
    except OSError:
        has_files = True
    if not has_files:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = run_dir / f"seg_{index:03d}_incomplete_{stamp}"
    suffix = 1
    while target.exists():
        suffix += 1
        target = run_dir / f"seg_{index:03d}_incomplete_{stamp}_{suffix}"
    shutil.move(str(seg_dir), str(target))
    return str(target)


def resolve_symbols_for_universe(
    *,
    config_path: str | Path,
    exchanges: str,
    universe_csv: str | Path,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
) -> dict[str, Any]:
    # Import lazily so pure stitch/status unit tests do not need REST dependencies.
    from config import load_config
    from multi_bot import build_pairs_for_universe

    cfg = load_config(config_path)
    exchange_ids = [item.strip().lower() for item in exchanges.split(",") if item.strip()]
    if not exchange_ids:
        raise ValueError("empty exchanges")
    universe_path = Path(universe_csv)
    if not universe_path.exists():
        raise FileNotFoundError(f"Universe CSV not found: {universe_path}")
    _clients, pairs_by_exchange, discovery = build_pairs_for_universe(
        exchange_ids=exchange_ids,
        universe_csv=universe_path,
        quote=quote.upper(),
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        timeout_sec=cfg.exchange.timeout_sec,
    )
    symbols_by_exchange = {
        exchange_id: [pair.symbol for pair in pairs]
        for exchange_id, pairs in pairs_by_exchange.items()
        if pairs
    }
    if not symbols_by_exchange:
        raise RuntimeError("No WS symbols discovered for durable collect")
    symbols_arg = ";".join(
        f"{exchange_id}:{','.join(symbols)}"
        for exchange_id, symbols in sorted(symbols_by_exchange.items())
    )
    return {
        "ok": True,
        "symbols_by_exchange": symbols_by_exchange,
        "symbols_arg": symbols_arg,
        "discovery": discovery,
        "universe_csv": str(universe_path),
        "exchanges": exchange_ids,
        "quote": quote.upper(),
        "max_symbols": max_symbols,
        "max_pairs_per_exchange": max_pairs_per_exchange,
    }


class DurableRun:
    def __init__(
        self,
        run_id: str,
        out_root: Path,
        symbols_by_exchange: dict[str, list[str]],
        total_duration_sec: int,
        segment_sec: int = DEFAULT_SEGMENT_SEC,
        update_interval: str = "100ms",
        depth_levels: int = 20,
        heartbeat_sec: int = DEFAULT_HEARTBEAT_SEC,
        resume: bool = False,
        min_free_gb: float = DEFAULT_MIN_FREE_GB,
    ) -> None:
        self.run_id = run_id
        self.run_dir = out_root / run_id
        self.symbols_by_exchange = symbols_by_exchange
        self.total_duration_sec = total_duration_sec
        self.segment_sec = segment_sec
        self.update_interval = update_interval
        self.depth_levels = depth_levels
        self.heartbeat_sec = heartbeat_sec
        self.resume = resume
        self.min_free_gb = min_free_gb
        self.segments_planned = max(1, math.ceil(total_duration_sec / segment_sec))
        self._stop_requested = False
        self._exit_reason = "unknown"
        self._segment_index = 0
        self._segments_completed = 0
        self._errors: list[str] = []
        self._started_epoch = 0.0
        self._hb_stop = threading.Event()

    # --- state ---

    def _raw_snapshot(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.run_dir.glob("seg_*/ws_*.jsonl")):
            try:
                stat = path.stat()
                rows.append(
                    {
                        "file": str(path.relative_to(self.run_dir)),
                        "size_bytes": stat.st_size,
                        "mtime_epoch": stat.st_mtime,
                    }
                )
            except OSError:
                continue
        return rows

    def write_state(self, status: str, extra: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "schema": STATE_SCHEMA,
            "run_id": self.run_id,
            "pid": os.getpid(),
            "status": status,
            "exit_reason": self._exit_reason,
            "started_at_utc": datetime.fromtimestamp(
                self._started_epoch or time.time(), tz=timezone.utc
            ).isoformat(),
            "heartbeat_utc": _utc_now_iso(),
            "heartbeat_epoch": time.time(),
            "requested_total_sec": self.total_duration_sec,
            "segment_sec": self.segment_sec,
            "segments_planned": self.segments_planned,
            "segment_index": self._segment_index,
            "segments_completed": self._segments_completed,
            "resume": self.resume,
            "elapsed_sec": round(time.time() - self._started_epoch, 1) if self._started_epoch else 0.0,
            "min_free_gb": self.min_free_gb,
            "free_gb_now": round(free_gb(self.run_dir), 1),
            "errors": self._errors[-20:],
            "raw_snapshot": self._raw_snapshot(),
        }
        if extra:
            payload.update(extra)
        atomic_write_json(state_path_for(self.run_dir), payload)

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop.wait(self.heartbeat_sec):
            try:
                self.write_state("running")
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"heartbeat {type(exc).__name__}: {exc}")

    def _signal_handler(self, signum: int, _frame: Any) -> None:
        self._stop_requested = True
        self._exit_reason = f"terminated_by_signal_{signum}"
        self.write_state("terminating")

    # --- run ---

    def run(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._started_epoch = time.time()
        for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    signal.signal(sig, self._signal_handler)
                except (ValueError, OSError):
                    pass
        self.write_state("running")
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb_thread.start()
        status = "failed"
        try:
            completed_manifests = (
                _load_completed_segment_manifests(self.run_dir, self.segments_planned)
                if self.resume
                else {}
            )
            completed_duration = sum(
                float(item.get("actual_duration_sec") or 0.0)
                for item in completed_manifests.values()
            )
            self._segments_completed = len(completed_manifests)
            if completed_manifests:
                print(
                    f"[resume] completed_segments={sorted(completed_manifests)} "
                    f"completed_duration={completed_duration:.1f}s",
                    flush=True,
                )
            for index in range(1, self.segments_planned + 1):
                if index in completed_manifests:
                    continue
                if self._stop_requested:
                    break
                remaining = self.total_duration_sec - completed_duration
                if remaining <= 5:
                    break
                self._segment_index = index
                seg_duration = int(min(self.segment_sec, remaining))
                # Disk guard: чистый стоп ДО старта сегмента при нехватке места.
                # Превращает disk-full из смерти-посреди-записи в resume-friendly
                # остановку (готовые сегменты уже имеют манифесты).
                available_gb = free_gb(self.run_dir)
                if available_gb < self.min_free_gb:
                    self._exit_reason = (
                        f"disk_space_below_threshold_free_{available_gb:.1f}gb"
                        f"_min_{self.min_free_gb}gb"
                    )
                    self._errors.append(
                        f"seg{index} preflight: free={available_gb:.1f}GB < "
                        f"min={self.min_free_gb}GB, чистый стоп перед сегментом"
                    )
                    self._stop_requested = True
                    print(
                        f"[segment {index}/{self.segments_planned}] DISK GUARD: "
                        f"free={available_gb:.1f}GB < {self.min_free_gb}GB, stop",
                        flush=True,
                    )
                    break
                seg_dir = segment_dir_for(self.run_dir, index)
                archived = _archive_incomplete_segment_dir(self.run_dir, index) if self.resume else None
                seg_dir.mkdir(parents=True, exist_ok=True)
                self.write_state(
                    "running",
                    extra={"archived_incomplete_segment_dir": archived},
                )
                print(
                    f"[segment {index}/{self.segments_planned}] start duration={seg_duration}s",
                    flush=True,
                )
                segment_started_epoch = time.time()
                result = collect_ws_markets(
                    symbols_by_exchange=self.symbols_by_exchange,
                    out_dir=seg_dir,
                    duration_sec=seg_duration,
                    update_interval=self.update_interval,
                    depth_levels=self.depth_levels,
                )
                result["segment_index"] = index
                result["segment_started_epoch"] = segment_started_epoch
                result["segment_finished_epoch"] = time.time()
                atomic_write_json(segment_manifest_path(self.run_dir, index), result)
                completed_duration += float(result.get("actual_duration_sec") or 0.0)
                if result.get("duration_completed"):
                    self._segments_completed += 1
                if result.get("errors"):
                    for exchange, messages in result["errors"].items():
                        self._errors.extend(f"seg{index} {exchange}: {m}" for m in messages[-3:])
                print(
                    f"[segment {index}/{self.segments_planned}] done events={result.get('total_events')} "
                    f"duration_completed={result.get('duration_completed')} "
                    f"quality_eligible={result.get('quality_eligible')}",
                    flush=True,
                )
                if not result.get("duration_completed"):
                    self._exit_reason = f"segment_{index}_incomplete"
                    break
            if self._stop_requested:
                status = "terminated"
            elif self._segments_completed >= self.segments_planned or completed_duration >= self.total_duration_sec * 0.99:
                status = "completed"
                self._exit_reason = "completed_all_segments"
            else:
                status = "failed"
                if self._exit_reason == "unknown":
                    self._exit_reason = "stopped_before_all_segments_completed"
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"run {type(exc).__name__}: {exc}")
            self._exit_reason = f"collector_exception_{type(exc).__name__}"
            status = "failed"
        finally:
            self._hb_stop.set()
            # Сначала финальный state (stitch читает его для exit_reason), потом stitch.
            finished_at = _utc_now_iso()
            self.write_state(status, extra={"finished_at_utc": finished_at})
            manifest = stitch_run(self.run_dir, expected_total_sec=self.total_duration_sec)
            self.write_state(
                status,
                extra={
                    "finished_at_utc": finished_at,
                    "stitched_manifest": str(manifest.get("_path", "")),
                },
            )
        return manifest


# --- stitching / finalize ---


def load_state(run_dir: Path) -> dict[str, Any] | None:
    path = state_path_for(run_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def infer_exit_reason(state: dict[str, Any] | None, now_epoch: float | None = None) -> str:
    """Постфактум-инференс причины остановки по state-файлу."""
    if state is None:
        return "no_state_file"
    status = state.get("status")
    reason = state.get("exit_reason") or "unknown"
    if status in ("completed", "terminated", "failed") and reason != "unknown":
        return str(reason)
    now = now_epoch if now_epoch is not None else time.time()
    hb = float(state.get("heartbeat_epoch") or 0.0)
    if status == "running" and now - hb > STALE_HEARTBEAT_SEC:
        return "killed_externally_inferred_stale_heartbeat"
    if status == "running":
        return "still_running"
    return str(reason)


def stitch_run(run_dir: Path, expected_total_sec: int | None = None) -> dict[str, Any]:
    """Собирает run-manifest из сегментных манифестов + gap accounting.

    Работает и постфактум после смерти процесса: незавершённые сегменты
    (raw есть, manifest нет) учитываются как incomplete по данным fs.
    """
    segments: list[dict[str, Any]] = []
    seg_dirs = _canonical_segment_dirs(run_dir)
    for seg_dir in seg_dirs:
        manifest_path = seg_dir / "manifest.json"
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload["_segment_dir"] = seg_dir.name
                payload["_manifest"] = True
                segments.append(payload)
                continue
            except (OSError, json.JSONDecodeError):
                pass
        raw_files = sorted(seg_dir.glob("ws_*.jsonl"))
        if raw_files:
            mtimes = [p.stat().st_mtime for p in raw_files]
            ctimes = [p.stat().st_ctime for p in raw_files]
            segments.append(
                {
                    "_segment_dir": seg_dir.name,
                    "_manifest": False,
                    "completed": False,
                    "duration_completed": False,
                    "liveness_clean": False,
                    "quality_eligible": False,
                    "total_events": None,
                    "transport_rows": None,
                    "market_envelope_rows": None,
                    "normalized_events": None,
                    "control_rows": None,
                    "unclassified_messages": None,
                    "market_silence_events": None,
                    "reconnect_attempts": None,
                    "actual_duration_sec": round(max(mtimes) - min(ctimes), 1),
                    "segment_started_epoch": min(ctimes),
                    "segment_finished_epoch": max(mtimes),
                    "results": [
                        {
                            "output": str(p),
                            "events": None,
                            "completed": False,
                            "duration_completed": False,
                            "liveness_clean": False,
                            "quality_eligible": False,
                            "size_bytes": p.stat().st_size,
                        }
                        for p in raw_files
                    ],
                    "stop_reasons": ["segment_incomplete_no_manifest"],
                }
            )

    gaps: list[dict[str, Any]] = []
    for prev, nxt in zip(segments, segments[1:]):
        prev_end = prev.get("segment_finished_epoch")
        next_start = nxt.get("segment_started_epoch")
        if prev_end and next_start and next_start > prev_end:
            gaps.append(
                {
                    "after_segment": prev.get("_segment_dir"),
                    "gap_sec": round(next_start - prev_end, 1),
                }
            )

    actual_total = sum(float(s.get("actual_duration_sec") or 0.0) for s in segments)
    known_events = [s.get("total_events") for s in segments if s.get("total_events") is not None]
    all_results: list[dict[str, Any]] = []
    for seg in segments:
        for item in seg.get("results") or []:
            row = dict(item)
            row["segment"] = seg.get("_segment_dir")
            all_results.append(row)

    state = load_state(run_dir)
    requested_duration = expected_total_sec or (state or {}).get("requested_total_sec")
    exit_reason = infer_exit_reason(state)

    def segment_flag(segment: dict[str, Any], name: str) -> bool:
        value = segment.get(name)
        if value is None and name in {"duration_completed", "liveness_clean", "quality_eligible"}:
            return segment.get("completed") is True
        return value is True

    runtime_completed = (
        bool(segments)
        and all(segment_flag(segment, "duration_completed") for segment in segments)
        and exit_reason == "completed_all_segments"
    )
    liveness_clean = runtime_completed and all(
        segment_flag(segment, "liveness_clean") for segment in segments
    )
    quality_eligible = liveness_clean and all(
        segment_flag(segment, "quality_eligible") for segment in segments
    )
    dirty_segment_ids = [
        str(segment.get("_segment_dir"))
        for segment in segments
        if segment_flag(segment, "duration_completed")
        and not segment_flag(segment, "quality_eligible")
    ]

    counter_names = (
        "transport_rows",
        "market_envelope_rows",
        "normalized_events",
        "control_rows",
        "unclassified_messages",
        "market_silence_events",
        "reconnect_attempts",
    )
    counter_totals = {
        name: sum(int(segment.get(name) or 0) for segment in segments)
        for name in counter_names
    }
    manifest = {
        "schema": STITCHED_SCHEMA,
        "run_id": run_dir.name,
        "stitched_at_utc": _utc_now_iso(),
        "segments_planned": (state or {}).get("segments_planned"),
        "segments_total": len(segments),
        "segments_with_manifest": sum(1 for s in segments if s.get("_manifest")),
        "segments_incomplete": sum(
            1 for segment in segments if not segment_flag(segment, "duration_completed")
        ),
        "requested_duration_sec": requested_duration,
        "actual_duration_sec": round(actual_total, 1),
        "coverage_ratio": round(actual_total / float(requested_duration), 4)
        if requested_duration
        else None,
        "total_events": sum(known_events) if known_events else None,
        "events_known_for_segments": len(known_events),
        "gaps": gaps,
        "gap_total_sec": round(sum(g["gap_sec"] for g in gaps), 1),
        "collector_exit_reason": exit_reason,
        "runtime_completed": runtime_completed,
        "duration_completed": runtime_completed,
        "liveness_clean": liveness_clean,
        "quality_eligible": quality_eligible,
        "dirty_segment_ids": dirty_segment_ids,
        "completed": quality_eligible,
        "final": quality_eligible,
        "stop_condition": (
            "duration_sec"
            if quality_eligible
            else "duration_sec_quality_ineligible"
            if runtime_completed
            else exit_reason
        ),
        **counter_totals,
        "errors": (state or {}).get("errors") or [],
        "results": all_results,
        "segments": [
            {
                "segment_dir": s.get("_segment_dir"),
                "has_manifest": s.get("_manifest", False),
                "completed": s.get("completed"),
                "duration_completed": segment_flag(s, "duration_completed"),
                "liveness_clean": segment_flag(s, "liveness_clean"),
                "quality_eligible": segment_flag(s, "quality_eligible"),
                "total_events": s.get("total_events"),
                **{name: s.get(name) for name in counter_names},
                "actual_duration_sec": s.get("actual_duration_sec"),
            }
            for s in segments
        ],
    }
    out_path = run_dir / f"ws_collect_{run_dir.name}.json"
    atomic_write_json(out_path, manifest)
    manifest["_path"] = str(out_path)
    return manifest


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    parser = argparse.ArgumentParser(description="Durable segmented WS collector (research-only)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Сегментированный сбор с child-owned state/manifest")
    p_collect.add_argument("--symbols", required=True, help='Формат: "mexc:AAA_USDT,BBB;gateio:CCC_USDT"')
    p_collect.add_argument("--out-dir", required=True)
    p_collect.add_argument("--run-id", default=None)
    p_collect.add_argument("--total-sec", type=int, required=True)
    p_collect.add_argument("--segment-sec", type=int, default=DEFAULT_SEGMENT_SEC)
    p_collect.add_argument("--update-interval", default="100ms")
    p_collect.add_argument("--depth-levels", type=int, default=20)
    p_collect.add_argument("--heartbeat-sec", type=int, default=DEFAULT_HEARTBEAT_SEC)
    p_collect.add_argument("--resume", action="store_true")
    p_collect.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB,
                           help="Чистый стоп перед сегментом при свободном месте ниже порога")

    p_plan = sub.add_parser("plan-symbols", help="Resolve universe CSV to durable --symbols arg")
    p_plan.add_argument("--config", required=True)
    p_plan.add_argument("--exchanges", default="mexc,gateio")
    p_plan.add_argument("--universe", required=True)
    p_plan.add_argument("--quote", default="USDT")
    p_plan.add_argument("--max-symbols", type=int, default=300)
    p_plan.add_argument("--max-pairs-per-exchange", type=int, default=16)

    p_finalize = sub.add_parser("finalize", help="Постфактум stitch manifest по сегментам")
    p_finalize.add_argument("--run-dir", required=True)
    p_finalize.add_argument("--expected-total-sec", type=int, default=None)

    p_status = sub.add_parser("status", help="Показать state рана")
    p_status.add_argument("--run-dir", required=True)

    args = parser.parse_args()

    if args.command == "collect":
        run_id = args.run_id or f"ws_durable_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        run = DurableRun(
            run_id=run_id,
            out_root=Path(args.out_dir),
            symbols_by_exchange=parse_symbols_arg(args.symbols),
            total_duration_sec=args.total_sec,
            segment_sec=args.segment_sec,
            update_interval=args.update_interval,
            depth_levels=args.depth_levels,
            heartbeat_sec=args.heartbeat_sec,
            resume=args.resume,
            min_free_gb=args.min_free_gb,
        )
        manifest = run.run()
        print(
            f"DONE run_id={run_id} exit_reason={manifest.get('collector_exit_reason')} "
            f"segments={manifest.get('segments_total')} events={manifest.get('total_events')} "
            f"coverage={manifest.get('coverage_ratio')}",
            flush=True,
        )
        return 0 if manifest.get("completed") else 1

    if args.command == "plan-symbols":
        payload = resolve_symbols_for_universe(
            config_path=args.config,
            exchanges=args.exchanges,
            universe_csv=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            max_pairs_per_exchange=args.max_pairs_per_exchange,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "finalize":
        manifest = stitch_run(Path(args.run_dir), expected_total_sec=args.expected_total_sec)
        print(json.dumps({k: v for k, v in manifest.items() if k != "results"}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        state = load_state(Path(args.run_dir))
        if state is None:
            print("no state file")
            return 1
        state["inferred_exit_reason"] = infer_exit_reason(state)
        state.pop("raw_snapshot", None)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
