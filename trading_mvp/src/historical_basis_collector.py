from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from costs import validate_runtime_sec
from daily_collector import (
    GateDailyClient,
    MexcDailyClient,
    parse_gate_candles,
    parse_mexc_kline_payload,
)
from historical_basis_code_snapshot import require_plan_code_snapshot, validate_basis_code_snapshot_reference
from historical_basis_edge import sha256_file, sha256_json, validate_historical_basis_plan
from owned_run_gate import publish_owned_run_gate


SCHEMA = "trading_mvp_historical_basis_collect_v1"
CACHE_SCHEMA = "trading_mvp_historical_basis_cache_v1"
CANDLE_SEC = 300
MAX_PAGE_BARS = 2000
DEFAULT_OUTPUT_ROOT = Path(r"E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis")
SERIES = ("trade", "mark", "index")


class HistoricalDataRetentionError(RuntimeError):
    def __init__(self, venue: str, interval: str, maximum_recent_points: int, message: str) -> None:
        self.venue = venue
        self.interval = interval
        self.maximum_recent_points = int(maximum_recent_points)
        self.api_message = message
        super().__init__(
            f"{venue}:{interval}:maximum_recent_points={self.maximum_recent_points}: {message}"
        )


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float = 1.0) -> None:
        if rate_per_sec <= 0 or capacity <= 0:
            raise ValueError("token bucket rate and capacity must be positive")
        self.rate_per_sec = float(rate_per_sec)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity,
                    self._tokens + (now - self._updated) * self.rate_per_sec,
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_sec = (1.0 - self._tokens) / self.rate_per_sec
            time.sleep(wait_sec)


class HistoricalBasisClient(Protocol):
    exchange_id: str

    def fetch_5m_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]: ...

    def fetch_funding_range(
        self,
        symbol: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]: ...


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _closed_range(days: int = 220, now_sec: int | None = None) -> tuple[int, int]:
    now = int(now_sec if now_sec is not None else time.time())
    end = (now // CANDLE_SEC) * CANDLE_SEC - CANDLE_SEC
    start = end - days * 86_400 + CANDLE_SEC
    return start, end


def strict_merge_rows(*pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for page in pages:
        for raw in page:
            if not isinstance(raw, dict) or raw.get("ts") is None:
                continue
            ts = int(float(raw["ts"]))
            row = dict(raw)
            row["ts"] = float(ts)
            existing = merged.get(ts)
            if existing is not None and _canonical_json(existing) != _canonical_json(row):
                raise ValueError(f"conflicting duplicate timestamp: {ts}")
            merged[ts] = row
    return [merged[ts] for ts in sorted(merged)]


def _validate_rows(rows: list[dict[str, Any]], start_sec: int, end_sec: int) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    previous: int | None = None
    for row in strict_merge_rows(rows):
        ts = int(float(row["ts"]))
        if not start_sec <= ts <= end_sec:
            continue
        if previous is not None and ts <= previous:
            raise ValueError("timestamps must be strictly increasing")
        previous = ts
        validated.append(row)
    return validated


class MexcHistoricalBasisClient(MexcDailyClient):
    SERIES_PATHS = {
        "trade": "/api/v1/contract/kline/{symbol}",
        "mark": "/api/v1/contract/kline/fair_price/{symbol}",
        "index": "/api/v1/contract/kline/index_price/{symbol}",
    }

    def __init__(self, timeout_sec: int = 10, requests_per_sec: float = 5.0) -> None:
        super().__init__(timeout_sec=timeout_sec)
        self._request_bucket = TokenBucket(requests_per_sec)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._request_bucket.acquire()
        return super()._get(path, params)

    def fetch_5m_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]:
        if series not in self.SERIES_PATHS:
            raise ValueError(f"unsupported MEXC series: {series}")
        pages: list[list[dict[str, Any]]] = []
        cursor = int(start_sec)
        while cursor <= end_sec:
            page_end = min(int(end_sec), cursor + (MAX_PAGE_BARS - 1) * CANDLE_SEC)
            payload = self._get(
                self.SERIES_PATHS[series].format(symbol=symbol),
                {"interval": "Min5", "start": cursor, "end": page_end},
            )
            data = payload.get("data") if isinstance(payload, dict) else payload
            pages.append(parse_mexc_kline_payload(data))
            cursor = page_end + CANDLE_SEC
        return _validate_rows(strict_merge_rows(*pages), int(start_sec), int(end_sec))

    def fetch_funding_range(
        self,
        symbol: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]:
        rows = self.fetch_funding_history_full(symbol, page_size=1000, max_pages=60)
        return _validate_rows(rows, int(start_sec), int(end_sec))


class GateHistoricalBasisClient(GateDailyClient):
    def __init__(self, timeout_sec: int = 10, requests_per_sec: float = 5.0) -> None:
        super().__init__(timeout_sec=timeout_sec)
        self._request_bucket = TokenBucket(requests_per_sec)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._request_bucket.acquire()
        try:
            return super()._get(path, params)
        except Exception as exc:
            response = getattr(exc, "response", None)
            payload: Any = None
            if response is not None:
                try:
                    payload = response.json()
                except Exception:  # noqa: BLE001
                    payload = None
            message = str(payload.get("message") or "") if isinstance(payload, dict) else ""
            normalized = message.lower()
            if "maximum 10000 points recently are allowed" in normalized:
                raise HistoricalDataRetentionError("gateio", "5m", 10_000, message) from exc
            raise

    def fetch_5m_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]:
        if series not in SERIES:
            raise ValueError(f"unsupported Gate series: {series}")
        contract = symbol if series == "trade" else f"{series}_{symbol}"
        pages: list[list[dict[str, Any]]] = []
        cursor = int(start_sec)
        while cursor <= end_sec:
            page_end = min(int(end_sec), cursor + (MAX_PAGE_BARS - 1) * CANDLE_SEC)
            payload = self._get(
                "/futures/usdt/candlesticks",
                {
                    "contract": contract,
                    "interval": "5m",
                    "from": cursor,
                    "to": page_end,
                },
            )
            pages.append(parse_gate_candles(payload))
            cursor = page_end + CANDLE_SEC
        return _validate_rows(strict_merge_rows(*pages), int(start_sec), int(end_sec))

    def fetch_funding_range(
        self,
        symbol: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]:
        # Explicit windows avoid Gate's short default lookback and the 1000-row cap.
        window_sec = 30 * 86_400
        pages: list[list[dict[str, Any]]] = []
        cursor = int(start_sec)
        while cursor <= end_sec:
            page_end = min(int(end_sec), cursor + window_sec - 1)
            pages.append(self._fetch_funding_window(symbol, cursor, page_end, 1000))
            cursor = page_end + 1
        return _validate_rows(strict_merge_rows(*pages), int(start_sec), int(end_sec))


def cache_key(
    plan_hash: str,
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> str:
    payload = {
        "plan_hash": str(plan_hash),
        "venue": str(venue),
        "symbol": str(symbol),
        "series": str(series),
        "interval": "5m" if series != "funding" else "settlement",
        "start_sec": int(start_sec),
        "end_sec": int(end_sec),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _cache_path(
    cache_root: Path,
    plan_hash: str,
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> Path:
    key = cache_key(plan_hash, venue, symbol, series, start_sec, end_sec)
    safe_symbol = symbol.replace("/", "_").replace("\\", "_")
    return cache_root / venue / safe_symbol / f"{series}_{key}.json"


def _read_valid_cache(
    path: Path,
    *,
    plan_hash: str,
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "schema": CACHE_SCHEMA,
        "plan_hash": plan_hash,
        "venue": venue,
        "symbol": symbol,
        "series": series,
        "start_sec": int(start_sec),
        "end_sec": int(end_sec),
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_sha256") != sha256_json(rows):
        return None
    return payload


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, path)


def _replace_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _write_owned_gate(path: Path, payload: dict[str, Any]) -> None:
    publish_owned_run_gate(path, payload, run_type="historical_basis_history_collect")


def _source_family(venue: str, series: str) -> str:
    if venue == "mexc":
        if series == "funding":
            return "/api/v1/contract/funding_rate/history"
        return MexcHistoricalBasisClient.SERIES_PATHS[series]
    if series == "funding":
        return "/futures/usdt/funding_rate"
    return "/futures/usdt/candlesticks"


def _collect_venue(
    *,
    venue: str,
    client: HistoricalBasisClient,
    candidates: list[dict[str, Any]],
    plan_hash: str,
    cache_root: Path,
    start_sec: int,
    end_sec: int,
    deadline_monotonic: float,
) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    cache_hits = 0
    error_count = 0
    symbol_key = f"{venue}_symbol"
    total = len(candidates) * 4
    completed = 0
    started = time.monotonic()
    for candidate in candidates:
        symbol = str(candidate[symbol_key])
        for series in (*SERIES, "funding"):
            completed += 1
            if time.monotonic() >= deadline_monotonic:
                statuses.append({
                    "venue": venue,
                    "symbol": symbol,
                    "series": series,
                    "status": "timeout",
                    "rows": 0,
                    "error": "MaxRuntimeSec exceeded",
                })
                error_count += 1
                continue
            path = _cache_path(cache_root, plan_hash, venue, symbol, series, start_sec, end_sec)
            cached = _read_valid_cache(
                path,
                plan_hash=plan_hash,
                venue=venue,
                symbol=symbol,
                series=series,
                start_sec=start_sec,
                end_sec=end_sec,
            )
            if cached is not None:
                cache_hits += 1
                rows_count = len(cached["rows"])
                status = "cache_hit"
                error = None
                rows_sha256 = cached["rows_sha256"]
                cache_file_sha256 = sha256_file(path)
            else:
                try:
                    if series == "funding":
                        rows = client.fetch_funding_range(symbol, start_sec, end_sec)
                    else:
                        rows = client.fetch_5m_series(symbol, series, start_sec, end_sec)
                    rows = _validate_rows(list(rows), start_sec, end_sec)
                    payload = {
                        "schema": CACHE_SCHEMA,
                        "created_at_utc": _utc_now(),
                        "plan_hash": plan_hash,
                        "venue": venue,
                        "symbol": symbol,
                        "series": series,
                        "interval": "settlement" if series == "funding" else "5m",
                        "start_sec": int(start_sec),
                        "end_sec": int(end_sec),
                        "source_family": _source_family(venue, series),
                        "rows_sha256": sha256_json(rows),
                        "rows": rows,
                    }
                    _write_cache(path, payload)
                    rows_count = len(rows)
                    status = "collected"
                    error = None
                    rows_sha256 = payload["rows_sha256"]
                    cache_file_sha256 = sha256_file(path)
                except Exception as exc:  # noqa: BLE001
                    rows_count = 0
                    status = "error"
                    error = f"{type(exc).__name__}: {exc}"
                    rows_sha256 = None
                    cache_file_sha256 = None
                    error_count += 1
            statuses.append({
                "venue": venue,
                "symbol": symbol,
                "series": series,
                "status": status,
                "rows": rows_count,
                "cache_path": str(path),
                "cache_file_sha256": cache_file_sha256,
                "rows_sha256": rows_sha256,
                "error": error,
            })
            elapsed = max(0.001, time.monotonic() - started)
            rate = completed / elapsed
            eta = max(0.0, (total - completed) / rate)
            print(
                f"[{venue}] {completed}/{total} {symbol} {series} "
                f"status={status} rows={rows_count} eta_sec={eta:.1f}",
                flush=True,
            )
    return {"venue": venue, "statuses": statuses, "cache_hits": cache_hits, "error_count": error_count}


def collect_historical_basis(
    plan: dict[str, Any],
    *,
    plan_path: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    clients: dict[str, HistoricalBasisClient] | None = None,
    start_sec: int | None = None,
    end_sec: int | None = None,
    max_runtime_sec: int = 7200,
    run_id: str | None = None,
    parallel_parent_run_id: str | None = None,
    active_gate_path: str | Path | None = None,
    resume: bool = False,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
) -> dict[str, Any]:
    validate_runtime_sec(max_runtime_sec)
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    require_plan_code_snapshot(plan, snapshot)
    frozen_limit = int((plan.get("runtime") or {}).get("history_collect_max_runtime_sec") or 7200)
    if max_runtime_sec > frozen_limit:
        raise ValueError(f"MaxRuntimeSec exceeds frozen collector limit: {frozen_limit}")
    start_was_explicit = start_sec is not None
    end_was_explicit = end_sec is not None
    if start_sec is None or end_sec is None:
        default_start, default_end = _closed_range(int((plan.get("sample_plan") or {}).get("total_closed_days") or 220))
        start_sec = default_start if start_sec is None else int(start_sec)
        end_sec = default_end if end_sec is None else int(end_sec)
    start_sec, end_sec = int(start_sec), int(end_sec)

    plan_hash = str(plan.get("plan_hash") or "")
    if not plan_hash:
        raise ValueError("plan_hash is required")
    candidates = list((plan.get("universe") or {}).get("candidates") or [])
    if not candidates:
        raise ValueError("frozen universe is empty")
    output_root = Path(output_root).expanduser().resolve()
    cache_root = output_root / "cache"
    run_id = run_id or f"basis_history_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = output_root / "runs" / run_id
    if run_dir.exists() and not resume:
        raise FileExistsError(f"run_id already exists: {run_dir}")
    if run_dir.exists() and resume:
        prior_manifest = run_dir / "manifest.json"
        if not prior_manifest.is_file():
            raise ValueError("cannot resume without the original collector manifest")
        prior = json.loads(prior_manifest.read_text(encoding="utf-8"))
        if prior.get("final"):
            raise ValueError("cannot resume an already final collector run")
        if prior.get("plan_hash") != plan_hash:
            raise ValueError("resume plan hash mismatch")
        if prior.get("code_snapshot_hash") != snapshot.get("code_snapshot_hash"):
            raise ValueError("resume code snapshot hash mismatch")
        prior_start = int(prior.get("start_sec"))
        prior_end = int(prior.get("end_sec"))
        if start_was_explicit and start_sec != prior_start:
            raise ValueError("resume start_sec mismatch")
        if end_was_explicit and end_sec != prior_end:
            raise ValueError("resume end_sec mismatch")
        start_sec, end_sec = prior_start, prior_end
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
    if start_sec < 0 or end_sec <= start_sec or (end_sec - start_sec) % CANDLE_SEC != 0:
        raise ValueError("invalid closed 5m collection range")
    manifest_path = run_dir / "manifest.json"
    started_utc = _utc_now()
    started_monotonic = time.monotonic()
    deadline = started_monotonic + max_runtime_sec
    _replace_json_atomic(
        manifest_path,
        {
            "schema": SCHEMA,
            "run_id": run_id,
            "status": "RUNNING",
            "decision": "HISTORICAL_COLLECT_RUNNING",
            "final": False,
            "started_at_utc": started_utc,
            "max_runtime_sec": int(max_runtime_sec),
            "plan_path": str(Path(plan_path).expanduser().resolve()),
            "plan_file_sha256": sha256_file(plan_path),
            "plan_hash": plan_hash,
            "code_snapshot_hash": snapshot["code_snapshot_hash"],
            "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
            "immutable_code_snapshot": snapshot["immutable_snapshot"],
            "parallel_parent_run_id": parallel_parent_run_id,
            "resumed": bool(resume),
            "output_prefix": str(run_dir),
            "cache_root": str(cache_root),
            "start_sec": start_sec,
            "end_sec": end_sec,
            "next_allowed_command": "wait-for-visible-collector",
        },
    )
    clients = clients or {
        "mexc": MexcHistoricalBasisClient(),
        "gateio": GateHistoricalBasisClient(),
    }
    if set(clients) != {"mexc", "gateio"}:
        raise ValueError("collector requires exactly mexc and gateio clients")

    gate_path = Path(active_gate_path).expanduser().resolve() if active_gate_path else None
    if gate_path is not None:
        _write_owned_gate(
            gate_path,
            {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": run_id,
                "status": "RUNNING",
                "gate_status": "RUNNING",
                "collector_pid": os.getpid(),
                "process_ids": [os.getpid()],
                "monitor_pid": None,
                "output": {"path": str(run_dir), "kind": "directory"},
                "output_path": str(run_dir),
                "manifest_path": str(manifest_path),
                "locks": ["market_data_writer"],
                "owner_output_prefix": str(run_dir),
                "code_snapshot_hash": snapshot["code_snapshot_hash"],
                "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
                "parallel_safe_actions": ["code_work", "unit_tests", "fixtures", "static_analysis", "immutable_cache_compute"],
                "forbidden_overlapping_actions": ["collector", "probe", "consumer_of_owner_output", "postprocess", "grid_search"],
                "parallel_parent_run_id": parallel_parent_run_id,
                "replay_allowed": False,
                "grid_allowed": False,
                "live_orders_allowed": False,
                "updated_at": _utc_now(),
            },
        )

    print(
        f"START run_id={run_id} assets={len(candidates)} range={start_sec}..{end_sec} "
        f"max_runtime_sec={max_runtime_sec} output={run_dir}",
        flush=True,
    )
    venue_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="basis-history") as pool:
        futures = {
            pool.submit(
                _collect_venue,
                venue=venue,
                client=clients[venue],
                candidates=candidates,
                plan_hash=plan_hash,
                cache_root=cache_root,
                start_sec=start_sec,
                end_sec=end_sec,
                deadline_monotonic=deadline,
            ): venue
            for venue in ("mexc", "gateio")
        }
        for future in as_completed(futures):
            venue = futures[future]
            try:
                venue_results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                venue_results.append({
                    "venue": venue,
                    "statuses": [],
                    "cache_hits": 0,
                    "error_count": 1,
                    "fatal_error": f"{type(exc).__name__}: {exc}",
                })

    statuses = [row for result in venue_results for row in result.get("statuses") or []]
    error_count = sum(int(result.get("error_count") or 0) for result in venue_results)
    expected_items = len(candidates) * 8
    final = error_count == 0 and len(statuses) == expected_items and time.monotonic() <= deadline
    status = "READY_FOR_POSTPROCESS" if final else "STOPPED_INCOMPLETE"
    decision = "HISTORICAL_DATA_COLLECTED_NOT_EVALUATED" if final else "HISTORICAL_COLLECT_INCOMPLETE"
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": run_id,
        "status": status,
        "decision": decision,
        "final": final,
        "started_at_utc": started_utc,
        "finished_at_utc": _utc_now(),
        "duration_sec": round(time.monotonic() - started_monotonic, 3),
        "max_runtime_sec": int(max_runtime_sec),
        "plan_path": str(Path(plan_path).expanduser().resolve()),
        "plan_file_sha256": sha256_file(plan_path),
        "plan_hash": plan_hash,
        "code_hash": sha256_file(__file__),
        "code_snapshot_hash": snapshot["code_snapshot_hash"],
        "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
        "immutable_code_snapshot": snapshot["immutable_snapshot"],
        "parallel_parent_run_id": parallel_parent_run_id,
        "resumed": bool(resume),
        "output_prefix": str(run_dir),
        "cache_root": str(cache_root),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "expected_items": expected_items,
        "completed_items": len(statuses),
        "cache_hits": sum(int(result.get("cache_hits") or 0) for result in venue_results),
        "error_count": error_count,
        "source_families": {
            "mexc": [
                "/api/v1/contract/kline/{symbol}",
                "/api/v1/contract/kline/fair_price/{symbol}",
                "/api/v1/contract/kline/index_price/{symbol}",
                "/api/v1/contract/funding_rate/history",
            ],
            "gateio": ["/futures/usdt/candlesticks", "/futures/usdt/funding_rate"],
        },
        "retry_policy": {"max_attempts_per_request": 3, "backoff_sec": [0.5, 1.0]},
        "rate_limit_policy": {
            "scope": "independent_token_bucket_per_venue",
            "mexc_requests_per_sec": getattr(getattr(clients.get("mexc"), "_request_bucket", None), "rate_per_sec", None),
            "gateio_requests_per_sec": getattr(getattr(clients.get("gateio"), "_request_bucket", None), "rate_per_sec", None),
        },
        "universe_mode": "current_active_contracts_as_of_plan_freeze",
        "statuses": sorted(statuses, key=lambda row: (row["venue"], row["symbol"], row["series"])),
        "fatal_errors": [result.get("fatal_error") for result in venue_results if result.get("fatal_error")],
        "next_allowed_command": "fast-edge-basis-history-quality" if final else "visible-resume-or-reject",
    }
    manifest["input_merkle_sha256"] = sha256_json(
        sorted(
            [
                {
                    "venue": row["venue"],
                    "symbol": row["symbol"],
                    "series": row["series"],
                "cache_file_sha256": row.get("cache_file_sha256"),
                "rows_sha256": row.get("rows_sha256"),
                "rows": row.get("rows"),
                }
                for row in statuses
                if row.get("status") in {"collected", "cache_hit"}
            ],
            key=lambda row: (row["venue"], row["symbol"], row["series"]),
        )
    )
    manifest["manifest_hash"] = sha256_json({key: value for key, value in manifest.items() if key != "manifest_hash"})
    _replace_json_atomic(manifest_path, manifest)
    if gate_path is not None:
        _write_owned_gate(
            gate_path,
            {
                "schema": "active_run_gate_v2",
                "project": "trading_mvp",
                "run_id": run_id,
                "status": status,
                "gate_status": status,
                "final": final,
                "collector_pid": None,
                "process_ids": [],
                "monitor_pid": None,
                "output": {"path": str(run_dir), "kind": "directory"},
                "output_path": str(run_dir),
                "manifest_path": str(manifest_path),
                "locks": ["market_data_writer"],
                "owner_output_prefix": str(run_dir),
                "code_snapshot_hash": snapshot["code_snapshot_hash"],
                "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
                "parallel_safe_actions": ["code_work", "unit_tests", "fixtures", "static_analysis", "immutable_cache_compute"],
                "forbidden_overlapping_actions": ["collector", "probe", "consumer_of_owner_output", "postprocess", "grid_search"],
                "parallel_parent_run_id": parallel_parent_run_id,
                "replay_allowed": False,
                "grid_allowed": False,
                "live_orders_allowed": False,
                "next_goal_decision": "BASIS_HISTORY_QUALITY_READY" if final else "BASIS_HISTORY_COLLECT_INCOMPLETE",
                "next_step_after_ready": manifest["next_allowed_command"],
                "updated_at": _utc_now(),
            },
        )
    print(
        f"DONE run_id={run_id} status={status} items={len(statuses)}/{expected_items} "
        f"cache_hits={manifest['cache_hits']} errors={error_count} manifest={manifest_path}",
        flush=True,
    )
    return manifest


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="MEXC/Gate 5m perp basis history collector")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--start-sec", type=int)
    parser.add_argument("--end-sec", type=int)
    parser.add_argument("--max-runtime-sec", type=int, default=7200)
    parser.add_argument("--parallel-parent-run-id")
    parser.add_argument("--active-run-gate")
    parser.add_argument("--code-snapshot-hash")
    parser.add_argument("--code-snapshot-manifest")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    validated = validate_historical_basis_plan(args.plan, args.expected_plan_hash)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if validated["plan_hash"] != plan["plan_hash"]:
        raise ValueError("validated plan hash changed during read")
    result = collect_historical_basis(
        plan,
        plan_path=args.plan,
        output_root=args.output_root,
        start_sec=args.start_sec,
        end_sec=args.end_sec,
        max_runtime_sec=args.max_runtime_sec,
        run_id=args.run_id,
        parallel_parent_run_id=args.parallel_parent_run_id,
        active_gate_path=args.active_run_gate,
        resume=args.resume,
        code_snapshot_hash=args.code_snapshot_hash,
        code_snapshot_manifest=args.code_snapshot_manifest,
    )
    return 0 if result["final"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
