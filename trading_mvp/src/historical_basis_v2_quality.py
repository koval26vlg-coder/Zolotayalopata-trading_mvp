from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from historical_basis_v2_collector import (
    CACHE_SCHEMA,
    SCHEMA as COLLECTOR_SCHEMA,
    data_request_descriptor,
    resolve_historical_basis_v2_plan_data_contract,
    sha256_file,
    sha256_json,
)
from historical_basis_code_snapshot import require_plan_runtime_code_snapshot
from historical_basis_v2_preflight import (
    DAY_SEC,
    HOUR_SEC,
    HYPOTHESIS_ID,
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    SERIES,
    VENUES,
    WINDOW_DAYS,
    audit_funding_events,
)


SCHEMA = "trading_mvp_historical_basis_v2_quality_v2"
CANDLE_LEDGER_SCHEMA = "trading_mvp_historical_basis_v2_normalized_candles_v2"
FUNDING_LEDGER_SCHEMA = "trading_mvp_historical_basis_v2_funding_events_v2"
MAX_RUNTIME_SEC = 1_800
REQUIRED_CANDLE_KEYS = tuple(
    f"{venue}:{series}" for venue in VENUES for series in SERIES
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _as_int_timestamp(value: Any) -> int | None:
    result = _as_float(value)
    if result is None or not result.is_integer():
        return None
    return int(result)


def _atomic_write(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _jsonl_text(rows: Sequence[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _merkle_root(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return hashlib.sha256(b"").hexdigest()
    level = [hashlib.sha256(_canonical_json(row).encode("utf-8")).digest() for row in rows]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def audit_candle_series(
    rows: Sequence[dict[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    closed_before_sec: int,
    minimum_coverage: float = 0.98,
) -> dict[str, Any]:
    expected = max(0, (int(end_sec) - int(start_sec)) // HOUR_SEC)
    timestamps: list[int] = []
    invalid_timestamp_count = 0
    invalid_value_count = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid_timestamp_count += 1
            continue
        ts = _as_int_timestamp(row.get("ts"))
        if ts is None:
            invalid_timestamp_count += 1
            continue
        timestamps.append(ts)
        prices = [_as_float(row.get(key)) for key in ("open", "high", "low", "close")]
        if any(value is None or value <= 0 for value in prices):
            invalid_value_count += 1
        elif prices[1] < max(prices[0], prices[2], prices[3]) or prices[2] > min(
            prices[0], prices[1], prices[3]
        ):
            invalid_value_count += 1
        for key in ("volume_base", "volume_quote"):
            value = _as_float(row.get(key))
            if value is None or value < 0:
                invalid_value_count += 1
                break
    unique = sorted(set(timestamps))
    duplicate_count = len(timestamps) - len(unique)
    in_range = [ts for ts in unique if start_sec <= ts < end_sec]
    out_of_range_count = len(unique) - len(in_range)
    off_grid_count = sum(ts % HOUR_SEC != 0 or (ts - start_sec) % HOUR_SEC != 0 for ts in in_range)
    open_bar_count = sum(ts + HOUR_SEC > closed_before_sec for ts in unique)
    coverage = len(in_range) / expected if expected else 0.0
    gaps = [right - left for left, right in zip(in_range, in_range[1:]) if right - left > HOUR_SEC]
    accepted = (
        coverage >= float(minimum_coverage)
        and duplicate_count == 0
        and out_of_range_count == 0
        and off_grid_count == 0
        and open_bar_count == 0
        and invalid_timestamp_count == 0
        and invalid_value_count == 0
    )
    return {
        "rows": len(rows),
        "unique_rows": len(unique),
        "expected_rows": expected,
        "coverage": coverage,
        "minimum_coverage": float(minimum_coverage),
        "duplicate_count": duplicate_count,
        "open_bar_count": open_bar_count,
        "off_grid_count": off_grid_count,
        "out_of_range_count": out_of_range_count,
        "invalid_timestamp_count": invalid_timestamp_count,
        "invalid_value_count": invalid_value_count,
        "gap_count": len(gaps),
        "maximum_gap_sec": max(gaps, default=0),
        "accepted": accepted,
    }


def _row_map(rows: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        ts = _as_int_timestamp(row.get("ts") if isinstance(row, dict) else None)
        if ts is None:
            raise ValueError("invalid candle timestamp")
        if ts in result:
            raise ValueError(f"duplicate candle timestamp: {ts}")
        result[ts] = row
    return result


def align_asset_candles(
    candidate: dict[str, Any],
    series: dict[str, list[dict[str, Any]]],
    *,
    start_sec: int,
    end_sec: int,
    maximum_gap_sec: int = 3 * HOUR_SEC,
) -> list[dict[str, Any]]:
    missing = [key for key in REQUIRED_CANDLE_KEYS if key not in series]
    if missing:
        raise ValueError(f"missing required candle series: {', '.join(missing)}")
    maps = {key: _row_map(series[key]) for key in REQUIRED_CANDLE_KEYS}
    aligned = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    lifecycle = candidate.get("lifecycle") if isinstance(candidate.get("lifecycle"), dict) else {}
    active_from = int(float(lifecycle.get("active_from_sec", start_sec)))
    active_until = int(float(lifecycle.get("active_until_sec", end_sec)))
    aligned = [
        ts
        for ts in aligned
        if start_sec <= ts < end_sec and active_from <= ts < active_until
    ]
    result: list[dict[str, Any]] = []
    segment = 0
    previous: int | None = None
    for ts in aligned:
        if previous is not None and ts - previous > int(maximum_gap_sec):
            segment += 1
        previous = ts
        row: dict[str, Any] = {
            "schema": CANDLE_LEDGER_SCHEMA,
            "ts": ts,
            "canonical_asset_id": str(candidate["canonical_asset_id"]),
            "base": str(candidate["base"]).upper(),
            "segment_id": segment,
        }
        for venue in VENUES:
            trade = maps[f"{venue}:trade"][ts]
            mark = maps[f"{venue}:mark"][ts]
            index = maps[f"{venue}:index"][ts]
            row.update(
                {
                    f"{venue}_trade_open": float(trade["open"]),
                    f"{venue}_trade_high": float(trade["high"]),
                    f"{venue}_trade_low": float(trade["low"]),
                    f"{venue}_trade_close": float(trade["close"]),
                    f"{venue}_mark_close": float(mark["close"]),
                    f"{venue}_index_close": float(index["close"]),
                    f"{venue}_volume_quote": float(trade.get("volume_quote") or 0.0),
                }
            )
        if any("funding" in key for key in row):
            raise AssertionError("normalized candle schema must not contain funding fields")
        result.append(row)
    return result


def train_only_seven_day_median_quote_volume(
    rows: Sequence[dict[str, Any]],
    *,
    train_start_sec: int,
    train_end_sec: int,
) -> float:
    if train_end_sec <= train_start_sec:
        raise ValueError("train interval must be non-empty")
    first_day = train_start_sec // DAY_SEC
    last_day_exclusive = (train_end_sec + DAY_SEC - 1) // DAY_SEC
    daily = {day: 0.0 for day in range(first_day, last_day_exclusive)}
    for row in rows:
        ts = _as_int_timestamp(row.get("ts") if isinstance(row, dict) else None)
        if ts is None or not train_start_sec <= ts < train_end_sec:
            continue
        value = _as_float(row.get("volume_quote"))
        if value is not None and value >= 0:
            daily[ts // DAY_SEC] = daily.get(ts // DAY_SEC, 0.0) + value
    values = [daily[day] for day in sorted(daily)]
    if not values:
        return 0.0
    if len(values) < 7:
        return float(statistics.median(values))
    rolling = [
        float(statistics.median(values[index : index + 7]))
        for index in range(len(values) - 6)
    ]
    return float(statistics.median(rolling))


def select_liquid_assets(
    reports: Sequence[dict[str, Any]],
    *,
    minimum_quote_volume: float,
    primary_limit: int = 12,
    reserve_limit: int = 8,
) -> dict[str, Any]:
    eligible = [
        row
        for row in reports
        if row.get("quality_accepted") is True
        and float(row.get("train_worse_leg_quote_volume") or 0.0) >= float(minimum_quote_volume)
    ]
    eligible.sort(
        key=lambda row: (
            -float(row["train_worse_leg_quote_volume"]),
            str(row["canonical_asset_id"]),
        )
    )
    primary_rows = eligible[: int(primary_limit)]
    reserve_rows = eligible[int(primary_limit) : int(primary_limit) + int(reserve_limit)]
    return {
        "primary": [str(row["canonical_asset_id"]) for row in primary_rows],
        "reserve": [str(row["canonical_asset_id"]) for row in reserve_rows],
        "eligible": [str(row["canonical_asset_id"]) for row in eligible],
        "ranking": [
            {
                "canonical_asset_id": row["canonical_asset_id"],
                "base": row.get("base"),
                "train_worse_leg_quote_volume": row["train_worse_leg_quote_volume"],
            }
            for row in eligible
        ],
    }


def _load_candle_cache(
    path: Path,
    *,
    expected_file_hash: str,
    expected_rows_hash: str,
    expected_data_request_hash: str,
    venue: str,
    symbol: str,
    series: str,
    start_sec: int,
    end_sec: int,
) -> list[dict[str, Any]]:
    if not path.is_file() or sha256_file(path) != expected_file_hash:
        raise ValueError(f"candle cache file hash mismatch: {path}")
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
        raise ValueError(f"candle cache metadata mismatch: {path}")
    if request_hash != expected_data_request_hash:
        raise ValueError(f"collector status data request hash mismatch: {path}")
    if payload.get("data_request_hash") != request_hash or payload.get("data_request") != descriptor:
        raise ValueError(f"candle cache data request mismatch: {path}")
    if not str(payload.get("origin_plan_hash") or ""):
        raise ValueError(f"candle cache origin plan missing: {path}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"candle cache rows missing: {path}")
    rows_hash = sha256_json(rows)
    if rows_hash != expected_rows_hash or payload.get("rows_sha256") != rows_hash:
        raise ValueError(f"candle cache rows hash mismatch: {path}")
    return rows


def _load_funding_cache(
    reference: dict[str, Any],
    *,
    venue: str,
    symbol: str,
) -> tuple[list[dict[str, Any]], Path, str]:
    path = Path(str(reference.get("path") or "")).expanduser().resolve()
    expected_hash = str(reference.get("file_sha256") or "")
    if not path.is_file() or not expected_hash or sha256_file(path) != expected_hash:
        raise ValueError(f"funding cache file hash mismatch: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("exchange") != venue or payload.get("symbol") != symbol:
        raise ValueError(f"funding cache metadata mismatch: {path}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"funding cache rows missing: {path}")
    return rows, path, expected_hash


def _funding_ledger_rows(
    candidate: dict[str, Any],
    *,
    venue: str,
    symbol: str,
    rows: Sequence[dict[str, Any]],
    source_path: Path,
    source_hash: str,
    start_sec: int,
    end_sec: int,
) -> list[dict[str, Any]]:
    lifecycle = candidate.get("lifecycle") if isinstance(candidate.get("lifecycle"), dict) else {}
    active_from = float(lifecycle.get("active_from_sec", start_sec))
    active_until = float(lifecycle.get("active_until_sec", end_sec))
    result: list[dict[str, Any]] = []
    for source_index, source in enumerate(rows):
        if not isinstance(source, dict):
            continue
        ts = _as_float(source.get("ts"))
        rate = _as_float(source.get("funding_rate"))
        if ts is None or rate is None:
            continue
        if not start_sec <= ts < end_sec or not active_from <= ts < active_until:
            continue
        exact_ts: int | float = int(ts) if ts.is_integer() else ts
        event_identity = {
            "canonical_asset_id": candidate["canonical_asset_id"],
            "venue": venue,
            "symbol": symbol,
            "source_file_sha256": source_hash,
            "source_row_index": source_index,
            "settlement_ts": exact_ts,
            "funding_rate": rate,
        }
        result.append(
            {
                "schema": FUNDING_LEDGER_SCHEMA,
                "event_id": sha256_json(event_identity),
                "canonical_asset_id": candidate["canonical_asset_id"],
                "base": str(candidate["base"]).upper(),
                "venue": venue,
                "symbol": symbol,
                "settlement_ts": exact_ts,
                "ts": exact_ts,
                "funding_rate": rate,
                "source_path": str(source_path),
                "source_file_sha256": source_hash,
                "source_row_index": source_index,
            }
        )
    return result


def _validate_contract(
    plan: dict[str, Any],
    manifest: dict[str, Any],
    *,
    expected_plan_hash: str,
) -> tuple[str, str | None, int, int, list[dict[str, Any]], dict[str, int]]:
    contract = resolve_historical_basis_v2_plan_data_contract(
        plan,
        expected_plan_hash=expected_plan_hash,
    )
    plan_hash = str(contract["plan_hash"])
    preflight_hash = contract.get("preflight_hash")
    start_sec = int(contract["start_sec"])
    end_sec = int(contract["end_sec"])
    candidates = list(contract["candidates"])
    split_raw = plan.get("sample_plan") or plan.get("split") or {}
    split = {
        "warmup_days": int(split_raw.get("warmup_days") or 0),
        "train_days": int(split_raw.get("train_days") or 0),
        "oos_days": int(split_raw.get("oos_days") or 0),
    }
    if split != {"warmup_days": 14, "train_days": 85, "oos_days": 80}:
        raise ValueError("frozen v2 split mismatch")
    if not MIN_CANDIDATES <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError("frozen v2 candidate count must be in [8, 20]")
    if manifest.get("schema") != COLLECTOR_SCHEMA:
        raise ValueError("unexpected collector manifest schema")
    if manifest.get("status") != "READY_FOR_POSTPROCESS" or manifest.get("final") is not True:
        raise ValueError("collector manifest is not final")
    if manifest.get("plan_hash") != plan_hash or manifest.get("expected_plan_hash") != plan_hash:
        raise ValueError("collector manifest plan hash mismatch")
    if (
        int(manifest.get("start_sec")) != start_sec
        or int(manifest.get("end_sec")) != end_sec
        or manifest.get("range") != "[start,end)"
        or manifest.get("interval") != "1h"
    ):
        raise ValueError("collector manifest window mismatch")
    if int(manifest.get("daily_or_funding_requests") or 0) != 0:
        raise ValueError("collector manifest reports forbidden daily/funding requests")
    if manifest.get("preflight_hash") != preflight_hash:
        raise ValueError("collector manifest preflight hash mismatch")
    return plan_hash, str(preflight_hash) if preflight_hash else None, start_sec, end_sec, candidates, split


def _derived_split_path(candles_path: Path, label: str) -> Path:
    suffix = candles_path.suffix or ".jsonl"
    return candles_path.with_name(f"{candles_path.stem}.{label}{suffix}")


def run_historical_basis_v2_quality(
    plan: dict[str, Any],
    manifest: dict[str, Any],
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    manifest_path: str | Path,
    candles_output: str | Path,
    funding_output: str | Path,
    report_output: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    require_plan_runtime_code_snapshot(plan, runtime_code_path=__file__)
    if not 0 < int(max_runtime_sec) <= MAX_RUNTIME_SEC:
        raise ValueError("quality max_runtime_sec must be in [1, 1800]")
    frozen_limit = int((plan.get("runtime") or {}).get("quality_max_runtime_sec") or MAX_RUNTIME_SEC)
    if int(max_runtime_sec) > frozen_limit:
        raise ValueError(f"MaxRuntimeSec exceeds frozen quality limit: {frozen_limit}")
    plan_hash, preflight_hash, start_sec, end_sec, candidates, split = _validate_contract(
        plan,
        manifest,
        expected_plan_hash=expected_plan_hash,
    )
    plan_target = Path(plan_path).expanduser().resolve()
    manifest_target = Path(manifest_path).expanduser().resolve()
    if not plan_target.is_file() or json.loads(plan_target.read_text(encoding="utf-8")).get("plan_hash") != plan_hash:
        raise ValueError("plan file and in-memory plan mismatch")
    if not manifest_target.is_file() or json.loads(manifest_target.read_text(encoding="utf-8")).get("run_id") != manifest.get("run_id"):
        raise ValueError("manifest file and in-memory manifest mismatch")
    candles_target = Path(candles_output).expanduser().resolve()
    funding_target = Path(funding_output).expanduser().resolve()
    report_target = Path(report_output).expanduser().resolve()
    train_target = _derived_split_path(candles_target, "train")
    oos_target = _derived_split_path(candles_target, "oos")
    targets = [candles_target, funding_target, train_target, oos_target, report_target]
    if len(set(targets)) != len(targets):
        raise ValueError("quality output paths must be distinct")
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError("quality output already exists: " + ", ".join(existing))

    started = time.monotonic()
    deadline = started + int(max_runtime_sec)
    gates = plan.get("quality_gates") or {}
    minimum_series = float(gates.get("minimum_series_coverage") or 0.98)
    minimum_aligned = float(gates.get("minimum_dual_venue_aligned_coverage") or 0.95)
    minimum_funding = float(
        gates.get("minimum_funding_settlement_coverage")
        or gates.get("minimum_funding_coverage")
        or 0.98
    )
    maximum_gap = int(
        gates.get("maximum_segment_gap_sec")
        or gates.get("maximum_gap_sec")
        or 3 * HOUR_SEC
    )
    minimum_liquidity = float(
        gates.get("minimum_train_median_quote_volume")
        or gates.get("minimum_median_quote_volume")
        or 1_000_000.0
    )
    expected_slots = (end_sec - start_sec) // HOUR_SEC
    train_start = start_sec + split["warmup_days"] * DAY_SEC
    train_end = train_start + split["train_days"] * DAY_SEC
    oos_start = train_end

    status_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in manifest.get("statuses") or []:
        key = (str(row.get("venue")), str(row.get("symbol")), str(row.get("series")))
        if key in status_index:
            raise ValueError(f"duplicate collector status: {key}")
        status_index[key] = row
    manifest_funding_index = {
        (str(row.get("canonical_asset_id")), str(row.get("venue"))): row
        for row in manifest.get("funding_cache_references") or []
    }
    asset_reports: list[dict[str, Any]] = []
    normalized_by_id: dict[str, list[dict[str, Any]]] = {}
    funding_by_id: dict[str, list[dict[str, Any]]] = {}
    input_paths: set[Path] = set()

    for candidate_index, candidate in enumerate(candidates, start=1):
        if time.monotonic() >= deadline:
            raise TimeoutError("quality MaxRuntimeSec exceeded")
        canonical_id = str(candidate["canonical_asset_id"])
        base = str(candidate["base"]).upper()
        series_rows: dict[str, list[dict[str, Any]]] = {}
        load_errors: list[str] = []
        candle_reports: dict[str, dict[str, Any]] = {}
        for venue in VENUES:
            symbol = str(candidate[f"{venue}_symbol"])
            for series_name in SERIES:
                key = f"{venue}:{series_name}"
                status = status_index.get((venue, symbol, series_name))
                if not status or status.get("status") not in {"collected", "cache_hit"}:
                    load_errors.append(f"missing:{key}")
                    series_rows[key] = []
                    continue
                path = Path(str(status.get("cache_path") or "")).expanduser().resolve()
                try:
                    rows = _load_candle_cache(
                        path,
                        expected_file_hash=str(status.get("cache_file_sha256") or ""),
                        expected_rows_hash=str(status.get("rows_sha256") or ""),
                        expected_data_request_hash=str(status.get("data_request_hash") or ""),
                        venue=venue,
                        symbol=symbol,
                        series=series_name,
                        start_sec=start_sec,
                        end_sec=end_sec,
                    )
                    input_paths.add(path)
                    series_rows[key] = rows
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    load_errors.append(f"{key}:{type(exc).__name__}:{exc}")
                    series_rows[key] = []
        for key in REQUIRED_CANDLE_KEYS:
            candle_reports[key] = audit_candle_series(
                series_rows.get(key, []),
                start_sec=start_sec,
                end_sec=end_sec,
                closed_before_sec=end_sec,
                minimum_coverage=minimum_series,
            )
        try:
            aligned_rows = align_asset_candles(
                candidate,
                series_rows,
                start_sec=start_sec,
                end_sec=end_sec,
                maximum_gap_sec=maximum_gap,
            )
        except (KeyError, TypeError, ValueError) as exc:
            load_errors.append(f"alignment:{type(exc).__name__}:{exc}")
            aligned_rows = []
        aligned_coverage = len(aligned_rows) / expected_slots if expected_slots else 0.0

        funding_reports: dict[str, dict[str, Any]] = {}
        funding_events: list[dict[str, Any]] = []
        candidate_funding = candidate.get("funding_cache")
        if not isinstance(candidate_funding, dict):
            candidate_funding = {}
        for venue in VENUES:
            symbol = str(candidate[f"{venue}_symbol"])
            reference = candidate_funding.get(venue)
            manifest_reference = manifest_funding_index.get((canonical_id, venue))
            if not isinstance(reference, dict) or not isinstance(manifest_reference, dict):
                load_errors.append(f"funding:{venue}:missing_reference")
                funding_reports[venue] = {"accepted": False}
                continue
            if (
                str(reference.get("path")) != str(manifest_reference.get("path"))
                or str(reference.get("file_sha256")) != str(manifest_reference.get("file_sha256"))
            ):
                load_errors.append(f"funding:{venue}:manifest_reference_mismatch")
                funding_reports[venue] = {"accepted": False}
                continue
            try:
                source_rows, source_path, source_hash = _load_funding_cache(
                    reference,
                    venue=venue,
                    symbol=symbol,
                )
                input_paths.add(source_path)
                audit = audit_funding_events(
                    source_rows,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    minimum_coverage=minimum_funding,
                )
                funding_reports[venue] = audit
                funding_events.extend(
                    _funding_ledger_rows(
                        candidate,
                        venue=venue,
                        symbol=symbol,
                        rows=source_rows,
                        source_path=source_path,
                        source_hash=source_hash,
                        start_sec=start_sec,
                        end_sec=end_sec,
                    )
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                load_errors.append(f"funding:{venue}:{type(exc).__name__}:{exc}")
                funding_reports[venue] = {"accepted": False}

        venue_liquidity = {
            venue: train_only_seven_day_median_quote_volume(
                series_rows.get(f"{venue}:trade", []),
                train_start_sec=train_start,
                train_end_sec=train_end,
            )
            for venue in VENUES
        }
        worse_liquidity = min(venue_liquidity.values())
        reasons = list(load_errors)
        reasons.extend(
            f"series:{key}" for key, report in candle_reports.items() if not report["accepted"]
        )
        if aligned_coverage < minimum_aligned:
            reasons.append("dual_venue_aligned_coverage")
        reasons.extend(
            f"funding:{venue}" for venue, report in funding_reports.items() if not report.get("accepted")
        )
        quality_accepted = not reasons
        report = {
            "canonical_asset_id": canonical_id,
            "base": base,
            "quality_accepted": quality_accepted,
            "rejection_reasons": sorted(set(reasons)),
            "candle_series": candle_reports,
            "aligned_rows": len(aligned_rows),
            "aligned_expected_rows": expected_slots,
            "aligned_coverage": aligned_coverage,
            "funding": funding_reports,
            "train_liquidity_interval": {
                "start_sec": train_start,
                "end_sec": train_end,
                "range": "[start,end)",
                "days": split["train_days"],
            },
            "train_venue_quote_volume": venue_liquidity,
            "train_worse_leg_quote_volume": worse_liquidity,
            "full_window_or_current_liquidity_used": False,
        }
        asset_reports.append(report)
        if quality_accepted:
            normalized_by_id[canonical_id] = aligned_rows
            funding_by_id[canonical_id] = funding_events
        print(
            f"[basis-v2-quality] {candidate_index}/{len(candidates)} {base} "
            f"quality={quality_accepted} aligned={aligned_coverage:.4f} "
            f"train_worse_leg={worse_liquidity:.2f}",
            flush=True,
        )

    universe = plan.get("universe") or {}
    selection = select_liquid_assets(
        asset_reports,
        minimum_quote_volume=minimum_liquidity,
        primary_limit=int(universe.get("primary_limit") or 12),
        reserve_limit=int(universe.get("reserve_limit") or 8),
    )
    selected_ids = selection["primary"] + selection["reserve"]
    id_to_base = {str(candidate["canonical_asset_id"]): str(candidate["base"]).upper() for candidate in candidates}
    minimum_survivors = int(universe.get("minimum_surviving_assets") or MIN_CANDIDATES)
    accepted = len(selected_ids) >= minimum_survivors
    verdict = "QUALITY_ACCEPTED_NOT_EVALUATED" if accepted else "INSUFFICIENT_EXECUTABLE_UNIVERSE"
    next_command = "fast-edge-basis-v2-evaluate" if accepted else "none-branch-insufficient-quality-universe"

    candle_rows = [row for canonical_id in selected_ids for row in normalized_by_id.get(canonical_id, [])]
    candle_rows.sort(key=lambda row: (row["ts"], row["canonical_asset_id"]))
    funding_rows = [row for canonical_id in selected_ids for row in funding_by_id.get(canonical_id, [])]
    funding_rows.sort(
        key=lambda row: (
            float(row["settlement_ts"]),
            row["canonical_asset_id"],
            row["venue"],
            row["event_id"],
        )
    )
    if len({row["event_id"] for row in funding_rows}) != len(funding_rows):
        raise ValueError("funding ledger event ids are not unique")
    train_rows = [row for row in candle_rows if train_start <= int(row["ts"]) < train_end]
    oos_rows = [row for row in candle_rows if oos_start <= int(row["ts"]) < end_sec]
    _atomic_write(candles_target, _jsonl_text(candle_rows))
    _atomic_write(funding_target, _jsonl_text(funding_rows))
    _atomic_write(train_target, _jsonl_text(train_rows))
    _atomic_write(oos_target, _jsonl_text(oos_rows))

    output_artifacts: dict[str, dict[str, Any]] = {
        "candles": {
            "path": str(candles_target),
            "sha256": sha256_file(candles_target),
            "rows": len(candle_rows),
            "schema": CANDLE_LEDGER_SCHEMA,
        },
        "funding": {
            "path": str(funding_target),
            "sha256": sha256_file(funding_target),
            "rows": len(funding_rows),
            "schema": FUNDING_LEDGER_SCHEMA,
        },
        "train": {
            "path": str(train_target),
            "sha256": sha256_file(train_target),
            "rows": len(train_rows),
            "range": "[start,end)",
            "start_sec": train_start,
            "end_sec": train_end,
        },
        "oos": {
            "path": str(oos_target),
            "sha256": sha256_file(oos_target),
            "rows": len(oos_rows),
            "range": "[start,end)",
            "start_sec": oos_start,
            "end_sec": end_sec,
            "sealed": True,
        },
        "report": {
            "path": str(report_target),
            "sha256": None,
            "sha256_scope": "canonical_report_payload_with_report_sha256_null",
        },
    }
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _utc_now(),
        "status": verdict,
        "verdict": verdict,
        "final": True,
        "plan_path": str(plan_target),
        "plan_file_sha256": sha256_file(plan_target),
        "plan_hash": plan_hash,
        "expected_plan_hash": expected_plan_hash,
        "preflight_hash": preflight_hash,
        "collector_manifest_path": str(manifest_target),
        "collector_manifest_file_sha256": sha256_file(manifest_target),
        "collector_run_id": manifest.get("run_id"),
        "window": {
            "start_sec": start_sec,
            "end_sec": end_sec,
            "range": "[start,end)",
            "interval": "1h",
            "expected_rows_per_series": expected_slots,
        },
        "split": {
            **split,
            "train_start_sec": train_start,
            "train_end_sec": train_end,
            "oos_start_sec": oos_start,
            "oos_end_sec": end_sec,
        },
        "quality_gates": {
            "minimum_series_coverage": minimum_series,
            "minimum_dual_venue_aligned_coverage": minimum_aligned,
            "minimum_funding_coverage": minimum_funding,
            "maximum_gap_sec": maximum_gap,
            "minimum_train_median_quote_volume": minimum_liquidity,
        },
        "asset_reports": asset_reports,
        "quality_surviving_asset_count": sum(row["quality_accepted"] for row in asset_reports),
        "surviving_asset_count": len(selected_ids),
        "primary_asset_ids": selection["primary"],
        "reserve_asset_ids": selection["reserve"],
        "primary_assets": [id_to_base[value] for value in selection["primary"]],
        "reserve_assets": [id_to_base[value] for value in selection["reserve"]],
        "train_liquidity_ranking": selection["ranking"],
        "train_row_count": len(train_rows),
        "oos_row_count": len(oos_rows),
        "funding_event_count": len(funding_rows),
        "candle_merkle_sha256": _merkle_root(candle_rows),
        "funding_event_merkle_sha256": _merkle_root(funding_rows),
        "input_file_merkle_sha256": _merkle_root(
            [{"path": str(path), "sha256": sha256_file(path)} for path in sorted(input_paths)]
        ),
        "candles_output": str(candles_target),
        "candles_output_sha256": output_artifacts["candles"]["sha256"],
        "funding_output": str(funding_target),
        "funding_output_sha256": output_artifacts["funding"]["sha256"],
        "train_output": str(train_target),
        "train_output_sha256": output_artifacts["train"]["sha256"],
        "oos_output": str(oos_target),
        "oos_output_sha256": output_artifacts["oos"]["sha256"],
        "report_output": str(report_target),
        "output_artifacts": output_artifacts,
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "pnl_computed": False,
            "signals_read": False,
            "oos_metrics_read": False,
            "oos_candle_values_used_for_liquidity": False,
            "funding_exact_joined_to_candles": False,
        },
        "runtime": {
            "duration_sec": round(time.monotonic() - started, 3),
            "max_runtime_sec": int(max_runtime_sec),
        },
        "next_allowed_command": next_command,
    }
    report_payload_hash = sha256_json(result)
    result["output_artifacts"]["report"]["sha256"] = report_payload_hash
    result["report_payload_sha256"] = report_payload_hash
    _atomic_write(report_target, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    result["report_file_sha256"] = sha256_file(report_target)
    return result


# Compatibility aliases remain in the v2 module namespace only.
run_historical_basis_quality = run_historical_basis_v2_quality
align_asset_rows = align_asset_candles


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit and normalize historical-basis 1h v2 data")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--candles-output", required=True)
    parser.add_argument("--funding-output", required=True)
    parser.add_argument("--report-output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        plan_path = Path(args.plan).expanduser().resolve()
        manifest_path = Path(args.manifest).expanduser().resolve()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = run_historical_basis_v2_quality(
            plan,
            manifest,
            plan_path=plan_path,
            expected_plan_hash=args.expected_plan_hash,
            manifest_path=manifest_path,
            candles_output=args.candles_output,
            funding_output=args.funding_output,
            report_output=args.report_output,
            max_runtime_sec=args.max_runtime_sec,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "report": result["report_output"],
                "report_file_sha256": result["report_file_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
