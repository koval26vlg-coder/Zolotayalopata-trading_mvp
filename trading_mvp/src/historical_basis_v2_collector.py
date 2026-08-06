from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

import requests

from historical_basis_code_snapshot import (
    require_plan_code_snapshot,
    validate_basis_code_snapshot_reference,
)
from historical_basis_v2 import (
    PLAN_SCHEMA,
    validate_historical_basis_v2_plan,
)
from historical_basis_v2_preflight import (
    DAY_SEC,
    HOUR_SEC,
    HYPOTHESIS_ID,
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    SCHEMA as PREFLIGHT_SCHEMA,
    SERIES,
    VENUES,
    WINDOW_DAYS,
)
from owned_run_gate import publish_owned_run_gate


SCHEMA = "trading_mvp_historical_basis_v2_collect_v2"
CACHE_SCHEMA = "trading_mvp_historical_basis_v2_candle_cache_v3"
CACHE_NORMALIZATION_CONTRACT = "strict_closed_hourly_rows_v2"
MAX_PAGE_BARS = 2_000
MAX_RUNTIME_SEC = 5_400
DEFAULT_OUTPUT_ROOT = Path(
    r"E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2"
)


class HistoricalBasisV2Client(Protocol):
    exchange_id: str
    public_only: bool

    def fetch_1h_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_cache_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _timestamp_seconds(value: Any) -> float | None:
    result = _as_float(value)
    if result is None:
        return None
    if abs(result) >= 1_000_000_000_000:
        result /= 1_000.0
    return result


def parse_mexc_candles(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict):
        return []
    timestamps = data.get("time")
    if not isinstance(timestamps, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, raw_ts in enumerate(timestamps):
        try:
            ts = _timestamp_seconds(raw_ts)
            if ts is None:
                continue
            row = {
                "ts": ts,
                "open": float(data["open"][index]),
                "high": float(data["high"][index]),
                "low": float(data["low"][index]),
                "close": float(data["close"][index]),
                "volume_base": _as_float((data.get("vol") or [0.0] * len(timestamps))[index]) or 0.0,
                "volume_quote": _as_float((data.get("amount") or [0.0] * len(timestamps))[index]) or 0.0,
            }
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            continue
        rows.append(row)
    return rows


def parse_gate_candles(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ts = _timestamp_seconds(item.get("t"))
        prices = [_as_float(item.get(key)) for key in ("o", "h", "l", "c")]
        if ts is None or any(value is None for value in prices):
            continue
        rows.append(
            {
                "ts": ts,
                "open": prices[0],
                "high": prices[1],
                "low": prices[2],
                "close": prices[3],
                "volume_base": _as_float(item.get("v")) or 0.0,
                "volume_quote": _as_float(item.get("sum")) or 0.0,
            }
        )
    return rows


def strict_merge_rows(*pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for page in pages:
        for raw in page:
            if not isinstance(raw, dict):
                raise ValueError("candle row must be an object")
            ts_value = _timestamp_seconds(raw.get("ts"))
            if ts_value is None or not ts_value.is_integer():
                raise ValueError(f"invalid candle timestamp: {raw.get('ts')!r}")
            ts = int(ts_value)
            if ts in merged:
                raise ValueError(f"duplicate timestamp across pages: {ts}")
            row = dict(raw)
            row["ts"] = float(ts)
            merged[ts] = row
    return [merged[ts] for ts in sorted(merged)]


def validate_candle_rows(
    rows: Iterable[dict[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    closed_before_sec: int,
) -> list[dict[str, Any]]:
    if start_sec < 0 or end_sec <= start_sec:
        raise ValueError("invalid half-open candle range")
    ordered = strict_merge_rows(rows)
    validated: list[dict[str, Any]] = []
    previous: int | None = None
    for raw in ordered:
        ts = int(raw["ts"])
        if not start_sec <= ts < end_sec:
            raise ValueError(f"out-of-range candle timestamp: {ts}")
        if ts % HOUR_SEC != 0 or (ts - start_sec) % HOUR_SEC != 0:
            raise ValueError(f"off-grid candle timestamp: {ts}")
        if ts + HOUR_SEC > closed_before_sec:
            raise ValueError(f"open candle timestamp: {ts}")
        if previous is not None and ts <= previous:
            raise ValueError("candle timestamps are not strictly increasing")
        previous = ts
        values: dict[str, float] = {}
        for key in ("open", "high", "low", "close"):
            value = _as_float(raw.get(key))
            if value is None or value <= 0:
                raise ValueError(f"invalid {key} at timestamp {ts}")
            values[key] = value
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"invalid high at timestamp {ts}")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"invalid low at timestamp {ts}")
        normalized: dict[str, Any] = {"ts": float(ts), **values}
        for key in ("volume_base", "volume_quote"):
            value = _as_float(raw.get(key))
            if value is None:
                value = 0.0
            if value < 0:
                raise ValueError(f"invalid {key} at timestamp {ts}")
            normalized[key] = value
        validated.append(normalized)
    return validated


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
                delay = (1.0 - self._tokens) / self.rate_per_sec
            time.sleep(delay)


class _PublicRequestsClient:
    public_only = True
    base_url = ""

    def __init__(
        self,
        *,
        timeout_sec: int = 15,
        requests_per_sec: float = 5.0,
        session: requests.Session | None = None,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        self.timeout_sec = int(timeout_sec)
        self.session = session or requests.Session()
        self._request_bucket = TokenBucket(requests_per_sec)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        errors: list[str] = []
        for attempt in range(3):
            self._request_bucket.acquire()
            try:
                response = self.session.get(
                    f"{self.base_url}{path}",
                    params=params,
                    timeout=self.timeout_sec,
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"attempt={attempt + 1}:{type(exc).__name__}:{exc}")
                if attempt < 2:
                    time.sleep((0.5, 1.0)[attempt])
        raise RuntimeError("public request failed: " + " | ".join(errors))


def _validate_fetch_range(start_sec: int, end_sec: int) -> tuple[int, int]:
    start, end = int(start_sec), int(end_sec)
    if start < 0 or end <= start or start % HOUR_SEC or end % HOUR_SEC:
        raise ValueError("1h fetch range must be aligned and half-open")
    return start, end


class MexcHistoricalBasisV2Client(_PublicRequestsClient):
    exchange_id = "mexc"
    base_url = "https://contract.mexc.com"
    SERIES_PATHS = {
        "trade": "/api/v1/contract/kline/{symbol}",
        "mark": "/api/v1/contract/kline/fair_price/{symbol}",
        "index": "/api/v1/contract/kline/index_price/{symbol}",
    }

    def fetch_1h_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]:
        if series not in self.SERIES_PATHS:
            raise ValueError(f"unsupported MEXC series: {series}")
        start, end = _validate_fetch_range(start_sec, end_sec)
        pages: list[list[dict[str, Any]]] = []
        cursor = start
        while cursor < end:
            page_end = min(end, cursor + MAX_PAGE_BARS * HOUR_SEC)
            payload = self._get(
                self.SERIES_PATHS[series].format(symbol=symbol),
                {
                    "interval": "Min60",
                    "start": cursor,
                    "end": page_end - HOUR_SEC,
                },
            )
            pages.append(parse_mexc_candles(payload))
            cursor = page_end
        return validate_candle_rows(
            strict_merge_rows(*pages),
            start_sec=start,
            end_sec=end,
            closed_before_sec=end,
        )


class GateHistoricalBasisV2Client(_PublicRequestsClient):
    exchange_id = "gateio"
    base_url = "https://api.gateio.ws/api/v4"

    def fetch_1h_series(
        self,
        symbol: str,
        series: str,
        start_sec: int,
        end_sec: int,
    ) -> list[dict[str, Any]]:
        if series not in SERIES:
            raise ValueError(f"unsupported Gate series: {series}")
        start, end = _validate_fetch_range(start_sec, end_sec)
        contract = symbol if series == "trade" else f"{series}_{symbol}"
        pages: list[list[dict[str, Any]]] = []
        cursor = start
        while cursor < end:
            page_end = min(end, cursor + MAX_PAGE_BARS * HOUR_SEC)
            payload = self._get(
                "/futures/usdt/candlesticks",
                {
                    "contract": contract,
                    "interval": "1h",
                    "from": cursor,
                    "to": page_end - 1,
                },
            )
            pages.append(parse_gate_candles(payload))
            cursor = page_end
        return validate_candle_rows(
            strict_merge_rows(*pages),
            start_sec=start,
            end_sec=end,
            closed_before_sec=end,
        )


def _source_family(venue: str, series: str) -> str:
    if venue == "mexc":
        return MexcHistoricalBasisV2Client.SERIES_PATHS[series]
    if venue == "gateio":
        return "/futures/usdt/candlesticks"
    raise ValueError(f"unsupported venue: {venue}")


def _source_base_url(venue: str) -> str:
    if venue == "mexc":
        return MexcHistoricalBasisV2Client.base_url
    if venue == "gateio":
        return GateHistoricalBasisV2Client.base_url
    raise ValueError(f"unsupported venue: {venue}")


def data_request_descriptor(
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> dict[str, Any]:
    normalized_venue = str(venue)
    normalized_series = str(series)
    if normalized_venue not in VENUES:
        raise ValueError(f"unsupported venue: {normalized_venue}")
    if normalized_series not in SERIES:
        raise ValueError(f"unsupported candle series: {normalized_series}")
    start, end = _validate_fetch_range(start_sec, end_sec)
    return {
        "schema": CACHE_SCHEMA,
        "data_type": "closed_trade_mark_index_candles",
        "venue": normalized_venue,
        "symbol": str(symbol),
        "series": normalized_series,
        "interval": "1h",
        "venue_interval": "Min60" if normalized_venue == "mexc" else "1h",
        "range": "[start,end)",
        "start_sec": start,
        "end_sec": end,
        "source_base_url": _source_base_url(normalized_venue),
        "source_family": _source_family(normalized_venue, normalized_series),
        "source_public_only": True,
        "request_stack": "requests",
        "normalization_contract": CACHE_NORMALIZATION_CONTRACT,
    }


def cache_key(
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> str:
    return sha256_json(data_request_descriptor(venue, symbol, series, start_sec, end_sec))


def _cache_path(
    root: Path,
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> Path:
    safe_symbol = symbol.replace("/", "_").replace("\\", "_")
    key = cache_key(venue, symbol, series, start_sec, end_sec)
    return root / venue / safe_symbol / f"{series}_{key}.json"


def _read_valid_cache(
    path: Path,
    *,
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        descriptor = data_request_descriptor(venue, symbol, series, start_sec, end_sec)
        request_hash = sha256_json(descriptor)
        expected = {
            "schema": CACHE_SCHEMA,
            "venue": venue,
            "symbol": symbol,
            "series": series,
            "interval": "1h",
            "range": "[start,end)",
            "start_sec": start_sec,
            "end_sec": end_sec,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            return None
        if payload.get("data_request") != descriptor:
            return None
        if payload.get("data_request_hash") != request_hash:
            return None
        if not str(payload.get("origin_plan_hash") or ""):
            return None
        rows = payload.get("rows")
        if not isinstance(rows, list) or payload.get("rows_sha256") != sha256_json(rows):
            return None
        validate_candle_rows(
            rows,
            start_sec=start_sec,
            end_sec=end_sec,
            closed_before_sec=end_sec,
        )
        return payload
    except (OSError, ValueError, json.JSONDecodeError):
        return None
def _plan_preflight_verdict(plan: dict[str, Any]) -> str:
    provenance = plan.get("preflight_provenance")
    if isinstance(provenance, dict) and provenance.get("verdict"):
        return str(provenance["verdict"])
    for key in ("preflight", "a0_preflight"):
        value = plan.get(key)
        if isinstance(value, dict) and value.get("verdict"):
            return str(value["verdict"])
    return str(plan.get("preflight_verdict") or "")


def _plan_preflight_hash(plan: dict[str, Any]) -> str | None:
    provenance = plan.get("preflight_provenance")
    if isinstance(provenance, dict) and provenance.get("preflight_hash"):
        return str(provenance["preflight_hash"])
    for key in ("preflight", "a0_preflight"):
        value = plan.get(key)
        if isinstance(value, dict):
            result = value.get("preflight_hash") or value.get("hash")
            if result:
                return str(result)
    value = plan.get("preflight_hash")
    return str(value) if value else None


def _load_bound_preflight(plan: dict[str, Any]) -> dict[str, Any]:
    provenance = plan.get("preflight_provenance")
    if isinstance(provenance, dict):
        path = Path(str(provenance.get("path") or "")).expanduser().resolve()
        expected_file_hash = str(provenance.get("file_sha256") or "")
        if not path.is_file() or not expected_file_hash or sha256_file(path) != expected_file_hash:
            raise ValueError("preflight artifact hash mismatch")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != PREFLIGHT_SCHEMA:
            raise ValueError("unexpected v2 preflight schema")
        if payload.get("verdict") != "PREFLIGHT_ACCEPTED_NOT_COLLECTED":
            raise ValueError("collector requires accepted v2 preflight")
        semantic_hash = str(payload.get("preflight_hash") or "")
        expected_semantic_hash = sha256_json(
            {key: value for key, value in payload.items() if key != "preflight_hash"}
        )
        if not semantic_hash or semantic_hash != expected_semantic_hash:
            raise ValueError("preflight semantic hash mismatch")
        if str(provenance.get("preflight_hash") or "") != semantic_hash:
            raise ValueError("preflight semantic hash binding mismatch")
        source_candidates = list((payload.get("universe") or {}).get("candidates") or [])
        if provenance.get("candidate_hash") != sha256_json(source_candidates):
            raise ValueError("preflight candidate binding mismatch")
        return payload

    inline = plan.get("preflight") or plan.get("a0_preflight")
    if isinstance(inline, dict):
        payload = dict(inline)
        payload.setdefault("window", plan.get("window"))
        payload.setdefault("universe", {"candidates": (plan.get("universe") or {}).get("candidates")})
        return payload
    raise ValueError("hash-bound v2 preflight provenance is required")


def _plan_window(plan: dict[str, Any]) -> tuple[int, int]:
    split = plan.get("split_contract")
    if isinstance(split, dict):
        start = int(split.get("window_start_ts"))
        end = int(split.get("window_end_ts"))
        sample = plan.get("sample_plan") or {}
        if split.get("interval") != "[start,end)" or sample.get("interval") != "1h":
            raise ValueError("frozen v2 window mismatch")
        return start, end
    window = plan.get("window")
    if not isinstance(window, dict):
        raise ValueError("frozen v2 window is required")
    if window.get("interval") != "[start,end)" or window.get("interval_name") != "1h":
        raise ValueError("frozen v2 window mismatch")
    return int(window.get("window_start_sec")), int(window.get("window_end_sec"))


def _enrich_plan_candidates(
    candidates: Sequence[dict[str, Any]],
    preflight: dict[str, Any],
) -> list[dict[str, Any]]:
    source_candidates = list((preflight.get("universe") or {}).get("candidates") or [])
    source_by_id: dict[str, dict[str, Any]] = {}
    for source in source_candidates:
        if not isinstance(source, dict):
            raise ValueError("invalid preflight candidate")
        canonical_id = str(source.get("canonical_asset_id") or "")
        if not canonical_id or canonical_id in source_by_id:
            raise ValueError("preflight canonical identities must be unique")
        source_by_id[canonical_id] = source
    plan_ids = [str(candidate.get("canonical_asset_id") or "") for candidate in candidates]
    if set(plan_ids) != set(source_by_id):
        raise ValueError("plan candidates do not match preflight candidates")

    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        canonical_id = str(candidate["canonical_asset_id"])
        source = source_by_id[canonical_id]
        for key in ("base", "mexc_symbol", "gateio_symbol"):
            if str(candidate.get(key) or "").upper() != str(source.get(key) or "").upper():
                raise ValueError(f"plan/preflight candidate mismatch: {canonical_id}:{key}")
        lifecycle = source.get("lifecycle")
        funding_cache = source.get("funding_cache")
        if not isinstance(lifecycle, dict):
            raise ValueError(f"preflight lifecycle missing: {canonical_id}")
        if not isinstance(funding_cache, dict) or set(funding_cache) != set(VENUES):
            raise ValueError(f"funding cache references missing: {canonical_id}")
        enriched.append(
            {
                **candidate,
                "lifecycle": dict(lifecycle),
                "funding_cache": {venue: dict(funding_cache[venue]) for venue in VENUES},
            }
        )
    return enriched


def resolve_historical_basis_v2_plan_data_contract(
    plan: dict[str, Any],
    *,
    expected_plan_hash: str,
) -> dict[str, Any]:
    plan_hash = str(plan.get("plan_hash") or "")
    if not expected_plan_hash or plan_hash != str(expected_plan_hash):
        raise ValueError("expected plan hash mismatch")
    if plan.get("schema") == PLAN_SCHEMA:
        validate_historical_basis_v2_plan(plan, expected_plan_hash=expected_plan_hash)
    hypothesis = plan.get("hypothesis")
    hypothesis_id = (
        hypothesis.get("id") if isinstance(hypothesis, dict) else plan.get("hypothesis_id")
    )
    if hypothesis_id != HYPOTHESIS_ID:
        raise ValueError("unexpected v2 hypothesis")
    if _plan_preflight_verdict(plan) != "PREFLIGHT_ACCEPTED_NOT_COLLECTED":
        raise ValueError("collector requires accepted v2 preflight")
    start, end = _plan_window(plan)
    if (
        end - start != WINDOW_DAYS * DAY_SEC
        or start % HOUR_SEC
        or end % HOUR_SEC
    ):
        raise ValueError("frozen v2 window mismatch")
    candidates = list((plan.get("universe") or {}).get("candidates") or [])
    if not MIN_CANDIDATES <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError("frozen v2 candidate count must be in [8, 20]")
    canonical_ids = [str(row.get("canonical_asset_id") or "") for row in candidates]
    if any(not value for value in canonical_ids) or len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("candidate canonical identities must be unique")
    preflight = _load_bound_preflight(plan)
    source_window = preflight.get("window") or {}
    if (
        int(source_window.get("window_start_sec")) != start
        or int(source_window.get("window_end_sec")) != end
    ):
        raise ValueError("plan/preflight window mismatch")
    enriched = _enrich_plan_candidates(candidates, preflight)
    return {
        "plan_hash": plan_hash,
        "preflight_hash": _plan_preflight_hash(plan),
        "start_sec": start,
        "end_sec": end,
        "candidates": enriched,
        "preflight": preflight,
    }


def _validate_plan(
    plan: dict[str, Any],
    *,
    expected_plan_hash: str,
) -> tuple[str, int, int, list[dict[str, Any]]]:
    contract = resolve_historical_basis_v2_plan_data_contract(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    return (
        str(contract["plan_hash"]),
        int(contract["start_sec"]),
        int(contract["end_sec"]),
        list(contract["candidates"]),
    )


def _funding_references(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for candidate in candidates:
        funding = candidate.get("funding_cache")
        if not isinstance(funding, dict) or set(funding) != set(VENUES):
            raise ValueError(f"funding cache references missing: {candidate.get('canonical_asset_id')}")
        for venue in VENUES:
            reference = funding[venue]
            if not isinstance(reference, dict):
                raise ValueError("invalid funding cache reference")
            path = Path(str(reference.get("path") or "")).expanduser().resolve()
            expected_hash = str(reference.get("file_sha256") or "")
            if not path.is_file() or not expected_hash or sha256_file(path) != expected_hash:
                raise ValueError(f"funding cache reference hash mismatch: {path}")
            references.append(
                {
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": candidate.get("base"),
                    "venue": venue,
                    "symbol": candidate[f"{venue}_symbol"],
                    "path": str(path),
                    "file_sha256": expected_hash,
                    "reused_without_download": True,
                }
            )
    return references


class _WriterLease(AbstractContextManager["_WriterLease"]):
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.acquired = False

    def __enter__(self) -> "_WriterLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"another historical-basis v2 writer owns {self.path}") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "run_id": self.run_id, "started_at_utc": _utc_now()}, handle)
        self.acquired = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.acquired = False


def _collect_venue(
    *,
    venue: str,
    client: HistoricalBasisV2Client,
    candidates: Sequence[dict[str, Any]],
    plan_hash: str,
    preflight_hash: str | None,
    cache_root: Path,
    start_sec: int,
    end_sec: int,
    deadline: float,
) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    cache_hits = 0
    errors = 0
    total = len(candidates) * len(SERIES)
    completed = 0
    started = time.monotonic()
    for candidate in candidates:
        symbol = str(candidate[f"{venue}_symbol"])
        for series in SERIES:
            completed += 1
            request_descriptor = data_request_descriptor(
                venue,
                symbol,
                series,
                start_sec,
                end_sec,
            )
            request_hash = sha256_json(request_descriptor)
            path = _cache_path(cache_root, venue, symbol, series, start_sec, end_sec)
            status = "collected"
            error = None
            rows_count = 0
            rows_hash = None
            file_hash = None
            cache_origin_plan_hash = None
            cache_reused_across_plan = False
            request_count = 0
            cached = _read_valid_cache(
                path,
                venue=venue,
                symbol=symbol,
                series=series,
                start_sec=start_sec,
                end_sec=end_sec,
            )
            if cached is not None:
                status = "cache_hit"
                cache_hits += 1
                rows_count = len(cached["rows"])
                rows_hash = cached["rows_sha256"]
                file_hash = sha256_file(path)
                cache_origin_plan_hash = str(cached["origin_plan_hash"])
                cache_reused_across_plan = cache_origin_plan_hash != plan_hash
            elif time.monotonic() >= deadline:
                status = "timeout"
                error = "MaxRuntimeSec exceeded"
                errors += 1
            else:
                try:
                    before = time.monotonic()
                    rows = client.fetch_1h_series(symbol, series, start_sec, end_sec)
                    request_count = max(1, math.ceil((end_sec - start_sec) / HOUR_SEC / MAX_PAGE_BARS))
                    if time.monotonic() > deadline:
                        raise TimeoutError("MaxRuntimeSec exceeded after public request")
                    rows = validate_candle_rows(
                        rows,
                        start_sec=start_sec,
                        end_sec=end_sec,
                        closed_before_sec=end_sec,
                    )
                    payload = {
                        "schema": CACHE_SCHEMA,
                        "created_at_utc": _utc_now(),
                        "origin_plan_hash": plan_hash,
                        "origin_preflight_hash": preflight_hash,
                        "data_request_hash": request_hash,
                        "data_request": request_descriptor,
                        "venue": venue,
                        "symbol": symbol,
                        "series": series,
                        "interval": "1h",
                        "range": "[start,end)",
                        "start_sec": start_sec,
                        "end_sec": end_sec,
                        "source_family": _source_family(venue, series),
                        "source_public_only": True,
                        "request_stack": "requests",
                        "request_duration_sec": round(time.monotonic() - before, 6),
                        "rows_sha256": sha256_json(rows),
                        "rows": rows,
                    }
                    _write_cache_atomic(path, payload)
                    rows_count = len(rows)
                    rows_hash = payload["rows_sha256"]
                    file_hash = sha256_file(path)
                    cache_origin_plan_hash = plan_hash
                except Exception as exc:  # noqa: BLE001
                    status = "timeout" if isinstance(exc, TimeoutError) else "error"
                    error = f"{type(exc).__name__}: {exc}"
                    errors += 1
            statuses.append(
                {
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": candidate.get("base"),
                    "venue": venue,
                    "symbol": symbol,
                    "series": series,
                    "interval": "1h",
                    "range": "[start,end)",
                    "status": status,
                    "rows": rows_count,
                    "cache_path": str(path),
                    "cache_file_sha256": file_hash,
                    "rows_sha256": rows_hash,
                    "cache_schema": CACHE_SCHEMA,
                    "data_request_hash": request_hash,
                    "cache_origin_plan_hash": cache_origin_plan_hash,
                    "cache_reused_across_plan": cache_reused_across_plan,
                    "estimated_public_requests": request_count,
                    "error": error,
                }
            )
            elapsed = max(0.001, time.monotonic() - started)
            eta = (total - completed) / (completed / elapsed)
            print(
                f"[basis-v2-collector:{venue}] {completed}/{total} {symbol} {series} "
                f"status={status} rows={rows_count} eta_sec={eta:.1f}",
                flush=True,
            )
    return {
        "venue": venue,
        "statuses": statuses,
        "cache_hits": cache_hits,
        "error_count": errors,
    }


def _gate_payload(
    *,
    run_id: str,
    status: str,
    final: bool,
    run_dir: Path,
    manifest_path: Path,
    code_snapshot: dict[str, Any],
) -> dict[str, Any]:
    active = status == "RUNNING"
    return {
        "schema": "active_run_gate_v2",
        "project": "trading_mvp",
        "run_id": run_id,
        "status": status,
        "gate_status": status,
        "final": final,
        "collector_pid": os.getpid() if active else None,
        "process_ids": [os.getpid()] if active else [],
        "monitor_pid": None,
        "output": {"path": str(run_dir), "kind": "directory"},
        "output_path": str(run_dir),
        "manifest_path": str(manifest_path),
        "locks": ["market_data_writer"],
        "owner_output_prefix": str(run_dir),
        "code_snapshot_hash": code_snapshot["code_snapshot_hash"],
        "code_snapshot_manifest": code_snapshot["code_snapshot_manifest"],
        "parallel_safe_actions": ["code_work", "unit_tests", "fixtures", "static_analysis"],
        "forbidden_overlapping_actions": ["collector", "probe", "postprocess", "grid_search"],
        "replay_allowed": False,
        "grid_allowed": False,
        "live_orders_allowed": False,
        "updated_at": _utc_now(),
    }


def collect_historical_basis_v2(
    plan: dict[str, Any],
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    clients: dict[str, HistoricalBasisV2Client] | None = None,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    active_run_gate_path: str | Path | None = None,
    code_snapshot_hash: str | None = None,
    code_snapshot_manifest: str | Path | None = None,
    run_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    if not 0 < int(max_runtime_sec) <= MAX_RUNTIME_SEC:
        raise ValueError("collector max_runtime_sec must be in [1, 5400]")
    frozen_limit = int((plan.get("runtime") or {}).get("history_collect_max_runtime_sec") or MAX_RUNTIME_SEC)
    if int(max_runtime_sec) > frozen_limit:
        raise ValueError(f"MaxRuntimeSec exceeds frozen collector limit: {frozen_limit}")
    plan_hash, start_sec, end_sec, candidates = _validate_plan(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    plan_target = Path(plan_path).expanduser().resolve()
    if not plan_target.is_file():
        raise ValueError("plan file is missing")
    if json.loads(plan_target.read_text(encoding="utf-8")).get("plan_hash") != plan_hash:
        raise ValueError("plan file and in-memory plan mismatch")
    funding_references = _funding_references(candidates)
    snapshot = validate_basis_code_snapshot_reference(
        code_snapshot_hash,
        code_snapshot_manifest,
        fallback_code_path=__file__,
    )
    require_plan_code_snapshot(plan, snapshot)
    output = Path(output_root).expanduser().resolve()
    cache_root = output / "cache"
    run_id = run_id or f"basis_v2_history_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = output / "runs" / run_id
    manifest_path = run_dir / "manifest.json"
    if run_dir.exists() and not resume:
        raise FileExistsError(f"run_id already exists: {run_dir}")
    if run_dir.exists():
        if not manifest_path.is_file():
            raise ValueError("cannot resume without original manifest")
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior.get("final"):
            raise ValueError("cannot resume a final collector run")
        if prior.get("plan_hash") != plan_hash:
            raise ValueError("resume plan hash mismatch")
    else:
        run_dir.mkdir(parents=True, exist_ok=False)

    clients = clients or {
        "mexc": MexcHistoricalBasisV2Client(),
        "gateio": GateHistoricalBasisV2Client(),
    }
    if set(clients) != set(VENUES):
        raise ValueError("collector requires exactly mexc and gateio clients")
    if any(getattr(client, "public_only", None) is not True for client in clients.values()):
        raise ValueError("collector clients must be public-only")
    started_utc = _utc_now()
    started = time.monotonic()
    deadline = started + int(max_runtime_sec)
    preflight_hash = _plan_preflight_hash(plan)
    running_manifest = {
        "schema": SCHEMA,
        "run_id": run_id,
        "status": "RUNNING",
        "decision": "HISTORICAL_BASIS_V2_COLLECT_RUNNING",
        "final": False,
        "started_at_utc": started_utc,
        "max_runtime_sec": int(max_runtime_sec),
        "plan_path": str(plan_target),
        "plan_file_sha256": sha256_file(plan_target),
        "plan_hash": plan_hash,
        "expected_plan_hash": expected_plan_hash,
        "preflight_hash": preflight_hash,
        "code_snapshot_hash": snapshot["code_snapshot_hash"],
        "code_snapshot_manifest": snapshot["code_snapshot_manifest"],
        "immutable_code_snapshot": snapshot["immutable_snapshot"],
        "resumed": bool(resume),
        "output_prefix": str(run_dir),
        "cache_root": str(cache_root),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "range": "[start,end)",
        "interval": "1h",
        "funding_cache_references": funding_references,
        "next_allowed_command": "wait-for-visible-fast-edge-basis-v2-history-collect",
    }
    _replace_json_atomic(manifest_path, running_manifest)
    gate_path = Path(active_run_gate_path).expanduser().resolve() if active_run_gate_path else None
    if gate_path is not None:
        publish_owned_run_gate(
            gate_path,
            _gate_payload(
                run_id=run_id,
                status="RUNNING",
                final=False,
                run_dir=run_dir,
                manifest_path=manifest_path,
                code_snapshot=snapshot,
            ),
            run_type="historical_basis_v2_history_collect",
        )
    print(
        f"START basis-v2 run_id={run_id} assets={len(candidates)} interval=1h "
        f"range=[{start_sec},{end_sec}) max_runtime_sec={max_runtime_sec} output={run_dir}",
        flush=True,
    )

    venue_results: list[dict[str, Any]] = []
    lease_path = output / ".historical-basis-v2-writer.lock"
    with _WriterLease(lease_path, run_id):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="basis-v2-history") as pool:
            futures = {
                pool.submit(
                    _collect_venue,
                    venue=venue,
                    client=clients[venue],
                    candidates=candidates,
                    plan_hash=plan_hash,
                    preflight_hash=preflight_hash,
                    cache_root=cache_root,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    deadline=deadline,
                ): venue
                for venue in VENUES
            }
            for future in as_completed(futures):
                venue = futures[future]
                try:
                    venue_results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    venue_results.append(
                        {
                            "venue": venue,
                            "statuses": [],
                            "cache_hits": 0,
                            "error_count": 1,
                            "fatal_error": f"{type(exc).__name__}: {exc}",
                        }
                    )

    statuses = [row for result in venue_results for row in result.get("statuses") or []]
    statuses.sort(key=lambda row: (row["canonical_asset_id"], row["venue"], row["series"]))
    error_count = sum(int(result.get("error_count") or 0) for result in venue_results)
    expected_items = len(candidates) * len(VENUES) * len(SERIES)
    timed_out = time.monotonic() > deadline or any(row["status"] == "timeout" for row in statuses)
    final = error_count == 0 and len(statuses) == expected_items and not timed_out
    status = "READY_FOR_POSTPROCESS" if final else "STOPPED_INCOMPLETE"
    decision = (
        "HISTORICAL_BASIS_V2_CANDLES_COLLECTED_NOT_EVALUATED"
        if final
        else "HISTORICAL_BASIS_V2_COLLECT_INCOMPLETE"
    )
    next_command = (
        "fast-edge-basis-v2-history-quality"
        if final
        else "visible-resume-fast-edge-basis-v2-history-collect"
    )
    manifest: dict[str, Any] = {
        **running_manifest,
        "status": status,
        "decision": decision,
        "final": final,
        "finished_at_utc": _utc_now(),
        "duration_sec": round(time.monotonic() - started, 3),
        "expected_items": expected_items,
        "completed_items": len(statuses),
        "cache_hits": sum(int(result.get("cache_hits") or 0) for result in venue_results),
        "error_count": error_count,
        "timeout": timed_out,
        "source_provenance": {
            "public_only": True,
            "request_stack": "requests",
            "requests_version": getattr(requests, "__version__", None),
            "mexc": {
                "base_url": MexcHistoricalBasisV2Client.base_url,
                "interval": "Min60",
                "series_paths": MexcHistoricalBasisV2Client.SERIES_PATHS,
            },
            "gateio": {
                "base_url": GateHistoricalBasisV2Client.base_url,
                "path": "/futures/usdt/candlesticks",
                "interval": "1h",
                "series_contract_prefixes": {"trade": "", "mark": "mark_", "index": "index_"},
            },
        },
        "cache_policy": {
            "schema": CACHE_SCHEMA,
            "identity": "data_request_hash",
            "plan_hash_part_of_cache_identity": False,
            "normalization_contract": CACHE_NORMALIZATION_CONTRACT,
            "immutable_on_hit": True,
        },
        "rate_limit_policy": {
            "scope": "independent_token_bucket_per_venue",
            "mexc_requests_per_sec": getattr(getattr(clients["mexc"], "_request_bucket", None), "rate_per_sec", None),
            "gateio_requests_per_sec": getattr(getattr(clients["gateio"], "_request_bucket", None), "rate_per_sec", None),
        },
        "pagination": {
            "maximum_bars_per_page": MAX_PAGE_BARS,
            "overlap_allowed": False,
            "duplicate_timestamp_allowed": False,
        },
        "daily_or_funding_requests": 0,
        "funding_cache_references": funding_references,
        "statuses": statuses,
        "fatal_errors": [result.get("fatal_error") for result in venue_results if result.get("fatal_error")],
        "next_allowed_command": next_command,
    }
    manifest["candle_input_merkle_sha256"] = sha256_json(
        [
            {
                "canonical_asset_id": row["canonical_asset_id"],
                "venue": row["venue"],
                "symbol": row["symbol"],
                "series": row["series"],
                "data_request_hash": row.get("data_request_hash"),
                "rows_sha256": row.get("rows_sha256"),
            }
            for row in statuses
            if row["status"] in {"collected", "cache_hit"}
        ]
    )
    manifest["manifest_hash"] = sha256_json(manifest)
    _replace_json_atomic(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    manifest["manifest_file_sha256"] = sha256_file(manifest_path)
    if gate_path is not None:
        publish_owned_run_gate(
            gate_path,
            _gate_payload(
                run_id=run_id,
                status=status,
                final=final,
                run_dir=run_dir,
                manifest_path=manifest_path,
                code_snapshot=snapshot,
            ),
            run_type="historical_basis_v2_history_collect",
        )
    print(
        f"END basis-v2 run_id={run_id} status={status} completed={len(statuses)}/{expected_items} "
        f"cache_hits={manifest['cache_hits']} errors={error_count} manifest={manifest_path}",
        flush=True,
    )
    return manifest


# Short alias for callers that already dispatch by module name.
collect_historical_basis = collect_historical_basis_v2


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect missing historical-basis 1h v2 candles")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    parser.add_argument("--active-run-gate")
    parser.add_argument("--code-snapshot-hash")
    parser.add_argument("--code-snapshot-manifest")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        plan_path = Path(args.plan).expanduser().resolve()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        result = collect_historical_basis_v2(
            plan,
            plan_path=plan_path,
            expected_plan_hash=args.expected_plan_hash,
            output_root=args.output_root,
            max_runtime_sec=args.max_runtime_sec,
            active_run_gate_path=args.active_run_gate,
            code_snapshot_hash=args.code_snapshot_hash,
            code_snapshot_manifest=args.code_snapshot_manifest,
            run_id=args.run_id,
            resume=args.resume,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "manifest": result["manifest_path"],
                "manifest_hash": result["manifest_hash"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["final"] else 2


if __name__ == "__main__":
    sys.exit(main())
