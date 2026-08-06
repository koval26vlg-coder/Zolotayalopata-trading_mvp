from __future__ import annotations

import argparse
import json
import math
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pit_universe_snapshot_collector import CollectorLock, append_jsonl, atomic_write_json
from spot_pit_event_public_preflight import (
    BINANCE_INFO,
    GATE_PAIRS,
    GATE_TICKERS,
    MEXC_24H,
    MEXC_BOOK,
    MEXC_INFO,
    _binance_bases,
    _default_fetcher,
    _gate_markets,
    _mexc_markets,
)
from universe import UniverseRow, is_focus_candidate


MANIFEST_SCHEMA = "spot_pit_event_collector_manifest_v1"
STATE_SCHEMA = "spot_pit_event_collector_state_v1"
EXPECTED_EXCHANGES = {"mexc", "gateio"}
CheckpointCallback = Callable[[dict[str, Any]], dict[str, Any] | None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_paths(output_root: Path, run_id: str) -> dict[str, Path]:
    run_dir = output_root / run_id
    return {
        "run_dir": run_dir,
        "segments": run_dir / "segments",
        "cycles": run_dir / "cycles.jsonl",
        "manifest": run_dir / "manifest.json",
        "state": run_dir / "state.json",
        "alert": run_dir / "alert.json",
        "lock": run_dir / "collector.lock",
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _scan_journal(path: Path, run_id: str) -> tuple[int, int, int]:
    if not path.exists():
        return 0, 0, 0
    rows = 0
    max_cycle = 0
    declared_segment_rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid cycle journal at {path}:{line_number}: {exc}") from exc
            if str(item.get("run_id")) != run_id:
                raise ValueError(f"cycle journal run_id mismatch at line {line_number}")
            cycle = int(item.get("cycle") or 0)
            if cycle != max_cycle + 1:
                raise ValueError(f"cycle journal is not contiguous: expected={max_cycle + 1}, observed={cycle}")
            cycle_rows = int(item.get("rows") or 0)
            if cycle_rows < 0:
                raise ValueError(f"cycle journal has negative rows at line {line_number}")
            rows += 1
            max_cycle = cycle
            declared_segment_rows += cycle_rows
    return rows, max_cycle, declared_segment_rows


def _scan_segments(segments_dir: Path, run_id: str) -> tuple[int, int, dict[str, int]]:
    rows = 0
    max_cycle = 0
    counts: dict[str, int] = {}
    if not segments_dir.exists():
        return rows, max_cycle, counts
    for path in sorted(segments_dir.glob("segment_*.jsonl")):
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid segment at {path}:{line_number}: {exc}") from exc
                if str(item.get("run_id")) != run_id:
                    raise ValueError(f"segment run_id mismatch: {path}:{line_number}")
                count += 1
                max_cycle = max(max_cycle, int(item.get("cycle") or 0))
        counts[path.name] = count
        rows += count
    return rows, max_cycle, counts


def _segment_path(paths: dict[str, Path], cycle: int, interval_sec: int, segment_sec: int) -> Path:
    cycles_per_segment = max(1, segment_sec // interval_sec)
    index = (cycle - 1) // cycles_per_segment + 1
    return paths["segments"] / f"segment_{index:06d}.jsonl"


def _write_state(path: Path, run_id: str, universe: dict[str, dict[str, Any]], symbols: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(
        path,
        {
            "schema": STATE_SCHEMA,
            "run_id": run_id,
            "updated_at_utc": utc_now(),
            "universe": universe,
            "symbols": symbols,
        },
    )


def _initial_universe(preflight: dict[str, Any]) -> dict[str, dict[str, Any]]:
    universe: dict[str, dict[str, Any]] = {}
    for row in preflight.get("frozen_universe_preview") or []:
        if not isinstance(row, dict):
            continue
        base = str(row.get("base") or "").upper()
        if not base:
            continue
        universe[base] = {
            "base": base,
            "rank": row.get("rank"),
            "name": row.get("name"),
            "coin_id": row.get("coin_id"),
            "initial_venues": list(row.get("venues") or []),
            "universe_origin": "frozen_preflight",
            "universe_first_seen_ts": preflight.get("generated_at"),
        }
    if not universe:
        raise ValueError("accepted preflight contains no frozen universe")
    return universe


def _focus_symbol(base: str) -> bool:
    return is_focus_candidate(
        UniverseRow(rank=10**9, symbol=base, name=base, coin_id=base.lower(), market_cap_usd=0.0, price_usd=0.0)
    )


class PublicCycleProvider:
    def __init__(self, timeout_sec: int = 15, metadata_refresh_cycles: int = 60) -> None:
        self.fetch = _default_fetcher(timeout_sec)
        self.metadata_refresh_cycles = max(1, metadata_refresh_cycles)
        self.mexc_info: Any = None
        self.gate_pairs: Any = None
        self.binance_bases: set[str] = set()
        self.binance_reference_loaded = False

    def __call__(self, cycle: int) -> dict[str, Any]:
        errors: dict[str, str] = {}
        latency: dict[str, float] = {}

        def get(name: str, url: str) -> Any:
            try:
                payload, elapsed = self.fetch(url)
                latency[name] = elapsed
                return payload
            except Exception as exc:  # noqa: BLE001 - preserve endpoint failure evidence
                errors[name] = str(exc)
                return None

        refresh = (
            self.mexc_info is None
            or self.gate_pairs is None
            or not self.binance_reference_loaded
            or cycle == 1
            or (cycle - 1) % self.metadata_refresh_cycles == 0
        )
        if refresh:
            value = get("mexc_exchange_info", MEXC_INFO)
            if value is not None:
                self.mexc_info = value
            value = get("gate_pairs", GATE_PAIRS)
            if value is not None:
                self.gate_pairs = value
            value = get("binance_exchange_info", BINANCE_INFO)
            if value is not None:
                self.binance_bases = _binance_bases(value)
                self.binance_reference_loaded = True
        mexc_book = get("mexc_book_ticker", MEXC_BOOK)
        mexc_24h = get("mexc_24h", MEXC_24H)
        gate_tickers = get("gate_tickers", GATE_TICKERS)
        mexc = _mexc_markets(self.mexc_info, mexc_book, mexc_24h) if self.mexc_info is not None else {}
        gate = _gate_markets(self.gate_pairs, gate_tickers) if self.gate_pairs is not None else {}
        successful: set[str] = set()
        if self.mexc_info is not None and mexc_book is not None and mexc_24h is not None:
            successful.add("mexc")
        if self.gate_pairs is not None and gate_tickers is not None:
            successful.add("gateio")
        return {
            "snapshot_ts": utc_now(),
            "markets": {"mexc": mexc, "gateio": gate},
            "binance_bases": sorted(self.binance_bases),
            "binance_reference_available": self.binance_reference_loaded,
            "successful_exchanges": sorted(successful),
            "errors": errors,
            "latency_sec": latency,
            "metadata_refreshed": refresh,
        }


def _apply_cycle(
    report: dict[str, Any],
    universe: dict[str, dict[str, Any]],
    symbols: dict[str, dict[str, Any]],
    *,
    run_id: str,
    cycle: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    snapshot_ts = str(report.get("snapshot_ts") or utc_now())
    markets = report.get("markets") if isinstance(report.get("markets"), dict) else {}
    mexc = markets.get("mexc") if isinstance(markets.get("mexc"), dict) else {}
    gate = markets.get("gateio") if isinstance(markets.get("gateio"), dict) else {}
    binance = {str(value).upper() for value in report.get("binance_bases") or []}
    binance_reference_available = report.get("binance_reference_available") is True
    successful = {str(value) for value in report.get("successful_exchanges") or []}

    # A genuinely new non-Binance base is appended only when both spot venues
    # report it simultaneously, preventing one-venue symbol collisions.
    for base in sorted((set(mexc) & set(gate)) - set(universe)) if binance_reference_available else []:
        if base in binance or not _focus_symbol(base):
            continue
        universe[base] = {
            "base": base,
            "rank": None,
            "name": base,
            "coin_id": None,
            "initial_venues": ["mexc", "gateio"],
            "universe_origin": "new_two_venue_listing_after_start",
            "universe_first_seen_ts": snapshot_ts,
        }

    rows: list[dict[str, Any]] = []
    counts = {"observed": 0, "missing": 0, "binance_excluded": 0, "new_universe_bases": 0, "binance_reference_unavailable": 0}
    for base, meta in sorted(universe.items()):
        if meta.get("universe_origin") == "new_two_venue_listing_after_start" and meta.get("universe_first_seen_ts") == snapshot_ts:
            counts["new_universe_bases"] += 1
        for exchange, exchange_markets in (("mexc", mexc), ("gateio", gate)):
            key = f"{exchange}|{base}"
            previous = symbols.get(key, {})
            market = exchange_markets.get(base) if exchange in successful else None
            if market is not None:
                first_seen = previous.get("first_seen_ts") or snapshot_ts
                row = {
                    "run_id": run_id,
                    "cycle": cycle,
                    "snapshot_ts": snapshot_ts,
                    "exchange": exchange,
                    "symbol": market.get("symbol"),
                    "base": base,
                    "quote": "USDT",
                    "status": "trading",
                    "listed_now": True,
                    "inactive_or_delisted": False,
                    "first_seen_ts": first_seen,
                    "last_seen_ts": snapshot_ts,
                    "missing_since_ts": None,
                    "tombstone": False,
                    "bid": market.get("bid"),
                    "ask": market.get("ask"),
                    "bid_qty": market.get("bid_qty"),
                    "ask_qty": market.get("ask_qty"),
                    "last": market.get("last"),
                    "spread_bps": market.get("spread_bps"),
                    "base_volume_24h": market.get("base_volume_24h"),
                    "quote_volume_24h": market.get("quote_volume_24h"),
                    "source_endpoint": "bulk_spot_tickers",
                    "binance_spot_listed_now": (base in binance) if binance_reference_available else None,
                    "eligible_non_binance_spot": bool(binance_reference_available and base not in binance),
                    "universe_rank": meta.get("rank"),
                    "universe_origin": meta.get("universe_origin"),
                    "error": "" if binance_reference_available else "binance_reference_unavailable",
                }
                symbols[key] = {"first_seen_ts": first_seen, "last_seen_ts": snapshot_ts, "missing_since_ts": None, "last_row": row}
                counts["observed"] += 1
                counts["binance_excluded"] += int(binance_reference_available and base in binance)
                counts["binance_reference_unavailable"] += int(not binance_reference_available)
                rows.append(row)
            elif exchange in successful:
                first_seen = previous.get("first_seen_ts")
                missing_since = previous.get("missing_since_ts") or snapshot_ts
                prior = previous.get("last_row") if isinstance(previous.get("last_row"), dict) else {}
                row = {
                    **prior,
                    "run_id": run_id,
                    "cycle": cycle,
                    "snapshot_ts": snapshot_ts,
                    "exchange": exchange,
                    "symbol": prior.get("symbol"),
                    "base": base,
                    "quote": "USDT",
                    "status": "missing",
                    "listed_now": False,
                    "inactive_or_delisted": True,
                    "first_seen_ts": first_seen,
                    "last_seen_ts": previous.get("last_seen_ts"),
                    "missing_since_ts": missing_since,
                    "tombstone": True,
                    "bid": None,
                    "ask": None,
                    "bid_qty": None,
                    "ask_qty": None,
                    "last": None,
                    "spread_bps": None,
                    "base_volume_24h": None,
                    "quote_volume_24h": None,
                    "binance_spot_listed_now": (base in binance) if binance_reference_available else None,
                    "eligible_non_binance_spot": bool(binance_reference_available and base not in binance),
                    "universe_rank": meta.get("rank"),
                    "universe_origin": meta.get("universe_origin"),
                    "error": "market_missing_after_successful_bulk_response",
                }
                symbols[key] = {"first_seen_ts": first_seen, "last_seen_ts": previous.get("last_seen_ts"), "missing_since_ts": missing_since, "last_row": row}
                counts["missing"] += 1
                rows.append(row)
    return rows, counts


def collect(
    *,
    plan_path: Path,
    plan_sha256: str,
    preflight_path: Path,
    preflight_sha256: str,
    output_root: Path,
    run_id: str,
    duration_sec: int,
    interval_sec: int,
    segment_sec: int,
    resume: bool = False,
    provider: Callable[[int], dict[str, Any]] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    max_cycles: int = 0,
    checkpoint_callback: CheckpointCallback | None = None,
) -> dict[str, Any]:
    if duration_sec < 0 or interval_sec <= 0 or segment_sec <= 0 or segment_sec % interval_sec != 0:
        raise ValueError("duration/interval/segment parameters are invalid")
    if not plan_path.is_file() or not preflight_path.is_file():
        raise FileNotFoundError("sealed plan and accepted preflight are required")
    from hashlib import sha256

    def file_hash(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    if file_hash(plan_path).lower() != plan_sha256.lower():
        raise ValueError("collector plan sha256 mismatch")
    if file_hash(preflight_path).lower() != preflight_sha256.lower():
        raise ValueError("collector preflight sha256 mismatch")
    plan = _load_json(plan_path)
    preflight = _load_json(preflight_path)
    if plan.get("schema") != "spot_pit_event_forward_plan_v1" or preflight.get("schema") != "spot_pit_event_public_preflight_v1":
        raise ValueError("collector plan/preflight schema mismatch")
    if plan.get("research_only") is not True or plan.get("strategy_accepted") is not False:
        raise ValueError("collector requires a research-only unaccepted strategy plan")
    if preflight.get("accepted") is not True:
        raise ValueError("collector requires accepted public preflight")
    if str(preflight.get("plan_sha256") or "").lower() != plan_sha256.lower():
        raise ValueError("collector preflight belongs to a different plan")
    collection = plan.get("collection") if isinstance(plan.get("collection"), dict) else {}
    expected_contract = {
        "duration_sec": int(collection["duration_days"]) * 86400 if collection.get("duration_days") is not None else duration_sec,
        "interval_sec": int(collection["interval_sec"]) if collection.get("interval_sec") is not None else interval_sec,
        "segment_sec": int(collection["segment_sec"]) if collection.get("segment_sec") is not None else segment_sec,
    }
    observed_contract = {"duration_sec": duration_sec, "interval_sec": interval_sec, "segment_sec": segment_sec}
    if observed_contract != expected_contract:
        raise ValueError(f"collector parameters differ from sealed plan: expected={expected_contract}, observed={observed_contract}")
    stop_requested = stop_requested or (lambda: False)
    provider = provider or PublicCycleProvider()
    paths = build_paths(output_root, run_id)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)
    paths["segments"].mkdir(parents=True, exist_ok=True)
    lock = CollectorLock(paths["lock"], run_id)
    lock.acquire()
    session_start = time.monotonic()
    failure: BaseException | None = None
    try:
        if paths["manifest"].exists() and not resume:
            raise FileExistsError(f"run_id={run_id} already exists; use resume=True")
        if resume and not paths["manifest"].exists():
            raise FileNotFoundError(f"cannot resume missing run_id={run_id}")
        if resume:
            manifest = _load_json(paths["manifest"])
            if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("run_id") != run_id or manifest.get("mode") != "spot_pit_event_forward_collect":
                raise ValueError("resume manifest schema/mode/run_id mismatch")
            if manifest.get("final") is True:
                raise ValueError("cannot resume final collector")
            for name, expected in (
                ("plan_sha256", plan_sha256),
                ("preflight_sha256", preflight_sha256),
                ("duration_sec", duration_sec),
                ("interval_sec", interval_sec),
                ("segment_sec", segment_sec),
            ):
                if str(manifest.get(name)) != str(expected):
                    raise ValueError(f"resume parameter mismatch: {name}")
            journal_rows, journal_cycle, journal_segment_rows = _scan_journal(paths["cycles"], run_id)
            segment_rows, segment_cycle, segment_counts = _scan_segments(paths["segments"], run_id)
            if journal_rows != journal_cycle or segment_cycle > journal_cycle or journal_segment_rows != segment_rows:
                raise ValueError("resume journals/segments are inconsistent")
            state_payload = _load_json(paths["state"])
            if state_payload.get("schema") != STATE_SCHEMA or state_payload.get("run_id") != run_id:
                raise ValueError("resume state schema/run_id mismatch")
            universe = {str(key): dict(value) for key, value in (state_payload.get("universe") or {}).items()}
            symbols = {str(key): dict(value) for key, value in (state_payload.get("symbols") or {}).items()}
            cycle = journal_cycle
            rows_total = segment_rows
            elapsed_before = float(manifest.get("elapsed_active_sec") or 0.0)
            errors_total = int(manifest.get("errors_total") or 0)
            manifest.update({"status": "RUNNING", "final": False, "incomplete": False, "stop_reason": None, "resume_count": int(manifest.get("resume_count") or 0) + 1, "last_resume_at_utc": utc_now(), "segment_rows": segment_counts})
        else:
            universe = _initial_universe(preflight)
            symbols: dict[str, dict[str, Any]] = {}
            cycle = 0
            rows_total = 0
            elapsed_before = 0.0
            errors_total = 0
            started = utc_now()
            manifest = {
                "schema": MANIFEST_SCHEMA,
                "mode": "spot_pit_event_forward_collect",
                "run_id": run_id,
                "started_at_utc": started,
                "updated_at_utc": started,
                "finished_at_utc": None,
                "status": "RUNNING",
                "final": False,
                "incomplete": False,
                "stop_reason": None,
                "research_only": True,
                "live_orders": False,
                "api_keys": False,
                "leverage_or_margin": False,
                "plan_path": str(plan_path),
                "plan_sha256": plan_sha256,
                "preflight_path": str(preflight_path),
                "preflight_sha256": preflight_sha256,
                "duration_sec": duration_sec,
                "duration_basis": "active_runtime",
                "interval_sec": interval_sec,
                "segment_sec": segment_sec,
                "elapsed_active_sec": 0.0,
                "cycle_count": 0,
                "rows_total": 0,
                "errors_total": 0,
                "resume_count": 0,
                "segments_dir": str(paths["segments"]),
                "cycles_path": str(paths["cycles"]),
                "state_path": str(paths["state"]),
                "alert_path": str(paths["alert"]),
                "futility_gate": "pending_until_48h",
                "segment_rows": {},
            }
        _write_state(paths["state"], run_id, universe, symbols)
        atomic_write_json(paths["manifest"], manifest)
        deadline = time.monotonic() + max(0.0, duration_sec - elapsed_before)
        cycles_this_session = 0
        interrupted = False
        checkpoint_stop_reason: str | None = None
        checkpoint_stop_final = False
        while (time.monotonic() < deadline or cycles_this_session == 0) and not stop_requested():
            if max_cycles and cycles_this_session >= max_cycles:
                interrupted = True
                break
            cycle += 1
            cycles_this_session += 1
            cycle_started = utc_now()
            report = provider(cycle)
            errors = report.get("errors") if isinstance(report.get("errors"), dict) else {}
            errors_total += len(errors)
            rows, counts = _apply_cycle(report, universe, symbols, run_id=run_id, cycle=cycle)
            segment = _segment_path(paths, cycle, interval_sec, segment_sec)
            append_jsonl(segment, rows)
            _write_state(paths["state"], run_id, universe, symbols)
            append_jsonl(
                paths["cycles"],
                [
                    {
                        "run_id": run_id,
                        "cycle": cycle,
                        "cycle_started_at_utc": cycle_started,
                        "cycle_finished_at_utc": utc_now(),
                        "segment": segment.name,
                        "rows": len(rows),
                        "counts": counts,
                        "errors": errors,
                        "successful_exchanges": report.get("successful_exchanges") or [],
                        "metadata_refreshed": bool(report.get("metadata_refreshed")),
                    }
                ],
            )
            rows_total += len(rows)
            segment_rows = dict(manifest.get("segment_rows") or {})
            segment_rows[segment.name] = int(segment_rows.get(segment.name) or 0) + len(rows)
            manifest.update(
                {
                    "updated_at_utc": utc_now(),
                    "elapsed_active_sec": elapsed_before + (time.monotonic() - session_start),
                    "cycle_count": cycle,
                    "rows_total": rows_total,
                    "errors_total": errors_total,
                    "universe_bases": len(universe),
                    "last_cycle_rows": len(rows),
                    "last_counts": counts,
                    "last_errors": errors,
                    "last_successful_exchanges": report.get("successful_exchanges") or [],
                    "segment_rows": segment_rows,
                }
            )
            atomic_write_json(paths["manifest"], manifest)
            print(f"[spot-pit] cycle={cycle} rows={len(rows)} total={rows_total} bases={len(universe)} errors={len(errors)} segment={segment.name}", flush=True)
            if checkpoint_callback is not None:
                checkpoint = checkpoint_callback(dict(manifest))
                if checkpoint is not None:
                    if not isinstance(checkpoint, dict):
                        raise TypeError("checkpoint callback must return a dict or None")
                    manifest["last_checkpoint"] = checkpoint
                    atomic_write_json(paths["manifest"], manifest)
                    if checkpoint.get("stop") is True:
                        checkpoint_stop_reason = str(checkpoint.get("stop_reason") or "checkpoint_stop")
                        checkpoint_stop_final = checkpoint.get("final") is True
                        interrupted = not checkpoint_stop_final
                        break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_for = min(float(interval_sec), remaining)
            sleep_deadline = time.monotonic() + sleep_for
            while time.monotonic() < sleep_deadline and not stop_requested():
                time.sleep(min(0.25, sleep_deadline - time.monotonic()))
        interrupted = interrupted or stop_requested()
        final = checkpoint_stop_final if checkpoint_stop_reason else not interrupted
        now = utc_now()
        manifest.update(
            {
                "updated_at_utc": now,
                "finished_at_utc": now if final else None,
                "stopped_at_utc": None if final else now,
                "status": "COMPLETED" if final else "STOPPED_INCOMPLETE",
                "final": final,
                "incomplete": not final,
                "stop_reason": checkpoint_stop_reason or ("duration_sec" if final else "interrupted_or_test_cycle_limit"),
                "elapsed_active_sec": elapsed_before + (time.monotonic() - session_start),
                "cycle_count": cycle,
                "rows_total": rows_total,
                "errors_total": errors_total,
            }
        )
        atomic_write_json(paths["manifest"], manifest)
        atomic_write_json(
            paths["alert"],
            {
                "schema": "spot_pit_event_collector_alert_v1",
                "run_id": run_id,
                "generated_at_utc": now,
                "status": manifest["status"],
                "final": final,
                "cycle_count": cycle,
                "rows_total": rows_total,
                "errors_total": errors_total,
                "action": "postprocess" if final else "resume_same_run_id_after_confirming_no_live_writer",
            },
        )
        return manifest
    except BaseException as exc:
        failure = exc
        if "manifest" in locals():
            manifest.update(
                {
                    "updated_at_utc": utc_now(),
                    "status": "STOPPED_INCOMPLETE",
                    "final": False,
                    "incomplete": True,
                    "stop_reason": f"{type(exc).__name__}: {exc}",
                    "elapsed_active_sec": float(locals().get("elapsed_before", 0.0)) + (time.monotonic() - session_start),
                }
            )
            atomic_write_json(paths["manifest"], manifest)
            atomic_write_json(paths["alert"], {"schema": "spot_pit_event_collector_alert_v1", "run_id": run_id, "generated_at_utc": utc_now(), "status": "STOPPED_INCOMPLETE", "final": False, "error": manifest["stop_reason"], "action": "inspect_then_resume_same_run_id"})
        raise
    finally:
        lock.release()
        if failure is not None:
            print(f"[spot-pit] stopped with {type(failure).__name__}: {failure}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Durable segmented public spot PIT event collector.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-sec", type=int, required=True)
    parser.add_argument("--interval-sec", type=int, default=60)
    parser.add_argument("--segment-sec", type=int, default=21600)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--analysis-output")
    parser.add_argument("--checkpoint-every-cycles", type=int, default=60)
    args = parser.parse_args()
    stop_event = threading.Event()

    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, name, None)
        if value is not None:
            signal.signal(value, stop)
    plan_file = Path(args.plan)
    manifest_file = build_paths(Path(args.output_root), args.run_id)["manifest"]
    analysis_output = Path(args.analysis_output) if args.analysis_output else None
    checkpoint_every_cycles = max(1, int(args.checkpoint_every_cycles))

    def checkpoint_callback(manifest: dict[str, Any]) -> dict[str, Any] | None:
        if analysis_output is None:
            return None
        plan = _load_json(plan_file)
        early = plan["early_gates"]
        elapsed_hours = float(manifest.get("elapsed_active_sec") or 0.0) / 3600.0
        coverage_after = float(early["coverage_gate_after_hours"])
        futility_after = float(early["futility_gate_after_hours"])
        if elapsed_hours < coverage_after:
            return None
        last = manifest.get("last_checkpoint") if isinstance(manifest.get("last_checkpoint"), dict) else {}
        if last.get("futility_gate_passed") is True:
            return None
        if elapsed_hours < futility_after and last.get("data_quality_passed") is True:
            return None
        last_cycle = int(last.get("cycle") or 0)
        if last_cycle and int(manifest.get("cycle_count") or 0) - last_cycle < checkpoint_every_cycles:
            return None

        from spot_pit_event_analyzer import run_analysis

        report = run_analysis(plan_file, manifest_file, analysis_output, expected_plan_sha256=args.plan_sha256)
        decision = str(report["decision"])
        stop_for_quality = decision.endswith("DATA_QUALITY_STOP_RECOMMENDED")
        stop_for_futility = decision.endswith("FUTILITY_STOP_RECOMMENDED")
        return {
            "schema": "spot_pit_event_collector_checkpoint_v1",
            "generated_at_utc": utc_now(),
            "cycle": int(manifest.get("cycle_count") or 0),
            "elapsed_hours": elapsed_hours,
            "decision": decision,
            "analysis_output_path": str(analysis_output),
            "data_quality_passed": report["data_quality"]["passed"] is True,
            "futility_gate_due": report["futility_gate"]["due"] is True,
            "futility_gate_passed": report["futility_gate"]["passed"] is True,
            "stop": bool(stop_for_quality or stop_for_futility),
            "final": bool(stop_for_futility),
            "stop_reason": "futility_gate" if stop_for_futility else "data_quality_gate" if stop_for_quality else None,
        }

    manifest = collect(
        plan_path=plan_file,
        plan_sha256=args.plan_sha256,
        preflight_path=Path(args.preflight),
        preflight_sha256=args.preflight_sha256,
        output_root=Path(args.output_root),
        run_id=args.run_id,
        duration_sec=args.duration_sec,
        interval_sec=args.interval_sec,
        segment_sec=args.segment_sec,
        resume=args.resume,
        stop_requested=stop_event.is_set,
        max_cycles=args.max_cycles,
        checkpoint_callback=checkpoint_callback if analysis_output is not None else None,
    )
    if analysis_output is not None and manifest.get("final") is True:
        from spot_pit_event_analyzer import run_analysis

        report = run_analysis(plan_file, manifest_file, analysis_output, expected_plan_sha256=args.plan_sha256)
        latest_manifest = _load_json(manifest_file)
        latest_manifest["analysis_output_path"] = str(analysis_output)
        latest_manifest["analysis_decision"] = report["decision"]
        latest_manifest["futility_gate"] = report["futility_gate"]
        latest_manifest["data_quality"] = report["data_quality"]
        atomic_write_json(manifest_file, latest_manifest)
        manifest = latest_manifest
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("final") else 3


if __name__ == "__main__":
    raise SystemExit(main())
