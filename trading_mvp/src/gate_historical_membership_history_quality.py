from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from gate_historical_archive import (
    parse_gate_archive_candlestick,
    parse_gate_archive_funding_apply,
)
from gate_historical_membership_history_collector import (
    MANIFEST_SCHEMA as COLLECT_MANIFEST_SCHEMA,
    READY_FOR_QUALITY_DECISION,
    _manifest_hash as collect_manifest_hash,
    validate_gzip_file,
)
from gate_historical_membership_history_plan import (
    MINIMUM_CANONICAL_ASSETS,
    authorize_history_collect,
    sha256_file,
    sha256_json,
)


SCHEMA = "trading_mvp_gate_historical_membership_history_quality_v1"
NORMALIZED_MANIFEST_SCHEMA = "trading_mvp_gate_membership_daily_history_v1"
SPLIT_MANIFEST_SCHEMA = "trading_mvp_gate_membership_daily_history_split_v1"
ACCEPTED_DECISION = "GATE_MEMBERSHIP_HISTORY_QUALITY_ACCEPTED_READY_FOR_FROZEN_TRAIN_PLANONLY"
REJECTED_DECISION = "GATE_MEMBERSHIP_HISTORY_QUALITY_REJECTED"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_HISTORY_QUALITY_STOPPED_INCOMPLETE"
MAX_RUNTIME_SEC = 1800
HOUR_SEC = 3_600
DAY_SEC = 86_400
MINIMUM_SERIES_COVERAGE = 0.98
MAX_REPORTED_PARSE_ERRORS = 20


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


def _quality_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
        }
    )


def _normalized_manifest_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "artifact_hash"}
        }
    )


def partition_rows_by_embargo(
    rows: Iterable[Mapping[str, Any]],
    *,
    train_view_start_sec: int,
    oos_start_sec: int,
    history_end_sec: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start = int(train_view_start_sec)
    boundary = int(oos_start_sec)
    end = int(history_end_sec)
    if start < 0 or not start < boundary < end:
        raise ValueError("invalid train/OOS embargo range")
    train: list[dict[str, Any]] = []
    oos: list[dict[str, Any]] = []
    previous: int | None = None
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("embargo row must be an object")
        timestamp = int(raw.get("ts"))
        if previous is not None and timestamp <= previous:
            raise ValueError("embargo rows must be strictly timestamp ordered")
        previous = timestamp
        if timestamp < start or timestamp >= end:
            continue
        target = train if timestamp < boundary else oos
        target.append(dict(raw))
    return train, oos


def _validate_collect_manifest(
    path: Path,
    *,
    expected_plan_hash: str,
    expected_artifact_hash: str,
) -> dict[str, Any]:
    manifest = _read_json_object(path)
    stored_hash = str(manifest.get("artifact_hash") or "")
    if (
        manifest.get("schema") != COLLECT_MANIFEST_SCHEMA
        or manifest.get("final") is not True
        or manifest.get("decision") != READY_FOR_QUALITY_DECISION
        or str(manifest.get("plan_hash") or "") != expected_plan_hash
        or stored_hash != collect_manifest_hash(manifest)
        or stored_hash != expected_artifact_hash
    ):
        raise ValueError("collector manifest is not a hash-valid final quality input")
    summary = manifest.get("summary")
    if not isinstance(summary, Mapping) or int(summary.get("errors") or 0) != 0:
        raise ValueError("collector manifest contains task errors")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("collector manifest files are missing")
    return manifest


def _expected_hour_count(start_sec: int, end_sec: int) -> int:
    first = ((int(start_sec) + HOUR_SEC - 1) // HOUR_SEC) * HOUR_SEC
    if first >= int(end_sec):
        return 0
    return ((int(end_sec) - 1 - first) // HOUR_SEC) + 1


def _iter_gzip_lines(paths: Iterable[Path]) -> Iterable[tuple[Path, int, str]]:
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.strip()
                if text:
                    yield path, line_number, text


def normalize_candlestick_archives(
    paths: Iterable[Path],
    *,
    contract_multiplier: float,
    start_sec: int,
    end_sec: int,
    deadline_monotonic: float | None = None,
) -> tuple[list[dict[str, float | int]], dict[str, Any], list[str]]:
    multiplier = float(contract_multiplier)
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("contract_multiplier must be positive")
    observed: dict[int, dict[str, float]] = {}
    parse_errors: list[str] = []
    duplicates = 0
    outside_before = 0
    outside_after = 0
    line_count = 0
    for path, line_number, line in _iter_gzip_lines(paths):
        line_count += 1
        if deadline_monotonic is not None and line_count % 10_000 == 0 and time.monotonic() >= deadline_monotonic:
            raise TimeoutError("history-quality runtime exhausted while parsing candlesticks")
        try:
            row = parse_gate_archive_candlestick(line)
            timestamp = int(row["ts"])
            if timestamp % HOUR_SEC:
                raise ValueError("candlestick timestamp is not hourly aligned")
            if timestamp < int(start_sec):
                outside_before += 1
                continue
            if timestamp >= int(end_sec):
                outside_after += 1
                continue
            if timestamp in observed:
                duplicates += 1
                continue
            base_volume = float(row["volume_contracts"]) * multiplier
            quote_volume = base_volume * float(row["close"])
            if not all(math.isfinite(value) and value >= 0 for value in (base_volume, quote_volume)):
                raise ValueError("derived volume is invalid")
            observed[timestamp] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume_base": base_volume,
                "volume_quote": quote_volume,
            }
        except Exception as exc:  # noqa: BLE001 - parse failures are quality evidence.
            if len(parse_errors) < MAX_REPORTED_PARSE_ERRORS:
                parse_errors.append(f"{path.name}:{line_number}: {type(exc).__name__}: {exc}")

    daily: dict[int, dict[str, float | int]] = {}
    for timestamp in sorted(observed):
        row = observed[timestamp]
        day_ts = (timestamp // DAY_SEC) * DAY_SEC
        target = daily.get(day_ts)
        if target is None:
            target = {
                "ts": day_ts,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume_base": row["volume_base"],
                "volume_quote": row["volume_quote"],
                "observed_hours": 1,
            }
            daily[day_ts] = target
        else:
            target["high"] = max(float(target["high"]), row["high"])
            target["low"] = min(float(target["low"]), row["low"])
            target["close"] = row["close"]
            target["volume_base"] = float(target["volume_base"]) + row["volume_base"]
            target["volume_quote"] = float(target["volume_quote"]) + row["volume_quote"]
            target["observed_hours"] = int(target["observed_hours"]) + 1

    expected_hours = _expected_hour_count(start_sec, end_sec)
    coverage = min(1.0, len(observed) / expected_hours) if expected_hours else 0.0
    metrics = {
        "raw_nonempty_lines": line_count,
        "observed_hourly_rows": len(observed),
        "expected_hourly_rows": expected_hours,
        "hourly_coverage": coverage,
        "daily_rows": len(daily),
        "duplicate_timestamps": duplicates,
        "parse_error_count": len(parse_errors),
        "rows_before_lifecycle_filtered": outside_before,
        "rows_after_closed_window_filtered": outside_after,
        "quote_volume_formula": "volume_contracts * close_price * contract_multiplier",
    }
    reasons: list[str] = []
    if coverage < MINIMUM_SERIES_COVERAGE:
        reasons.append("candlestick_coverage_below_0_98")
    if duplicates:
        reasons.append("duplicate_candlestick_timestamps")
    if parse_errors:
        reasons.append("candlestick_parse_errors")
    if not daily:
        reasons.append("no_daily_candlesticks")
    return [daily[key] for key in sorted(daily)], metrics, reasons


def normalize_funding_archives(
    paths: Iterable[Path],
    *,
    start_sec: int,
    end_sec: int,
    funding_interval_sec: int,
    deadline_monotonic: float | None = None,
) -> tuple[list[dict[str, float]], dict[str, Any], list[str]]:
    interval = int(funding_interval_sec)
    if interval <= 0:
        raise ValueError("funding_interval_sec must be positive")
    observed: dict[float, float] = {}
    parse_errors: list[str] = []
    duplicates = 0
    outside_before = 0
    outside_after = 0
    line_count = 0
    for path, line_number, line in _iter_gzip_lines(paths):
        line_count += 1
        if deadline_monotonic is not None and line_count % 10_000 == 0 and time.monotonic() >= deadline_monotonic:
            raise TimeoutError("history-quality runtime exhausted while parsing funding")
        try:
            row = parse_gate_archive_funding_apply(line)
            timestamp = float(row["ts"])
            if timestamp < float(start_sec):
                outside_before += 1
                continue
            if timestamp >= float(end_sec):
                outside_after += 1
                continue
            if timestamp in observed:
                duplicates += 1
                continue
            observed[timestamp] = float(row["funding_rate"])
        except Exception as exc:  # noqa: BLE001 - parse failures are quality evidence.
            if len(parse_errors) < MAX_REPORTED_PARSE_ERRORS:
                parse_errors.append(f"{path.name}:{line_number}: {type(exc).__name__}: {exc}")

    expected = max(1, int((int(end_sec) - int(start_sec)) // interval))
    coverage = min(1.0, len(observed) / expected)
    metrics = {
        "raw_nonempty_lines": line_count,
        "observed_settlements": len(observed),
        "expected_settlements": expected,
        "settlement_coverage": coverage,
        "funding_interval_sec": interval,
        "duplicate_timestamps": duplicates,
        "parse_error_count": len(parse_errors),
        "rows_before_lifecycle_filtered": outside_before,
        "rows_after_closed_window_filtered": outside_after,
    }
    reasons: list[str] = []
    if coverage < MINIMUM_SERIES_COVERAGE:
        reasons.append("funding_coverage_below_0_98")
    if duplicates:
        reasons.append("duplicate_funding_timestamps")
    if parse_errors:
        reasons.append("funding_parse_errors")
    return (
        [{"ts": timestamp, "funding_rate": observed[timestamp]} for timestamp in sorted(observed)],
        metrics,
        reasons,
    )


def _manifest_file_index(manifest: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for raw in manifest.get("files") or []:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid collector file record")
        key = (
            str(raw.get("symbol") or ""),
            str(raw.get("archive_type") or ""),
            str(raw.get("year_month") or ""),
        )
        if not all(key) or key in index:
            raise ValueError("duplicate or incomplete collector file record")
        index[key] = raw
    return index


def _validated_paths_for_asset(
    *,
    symbol: str,
    archive_type: str,
    plan: Mapping[str, Any],
    file_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> tuple[list[Path], list[str], int]:
    paths: list[Path] = []
    reasons: list[str] = []
    missing = 0
    tasks = [
        task
        for task in plan.get("archive_tasks") or []
        if str(task.get("symbol") or "") == symbol
        and str(task.get("archive_type") or "") == archive_type
    ]
    for task in sorted(tasks, key=lambda row: str(row["year_month"])):
        key = (symbol, archive_type, str(task["year_month"]))
        record = file_index.get(key)
        if record is None:
            reasons.append(f"missing_manifest_record:{archive_type}:{task['year_month']}")
            continue
        status = str(record.get("status") or "")
        if status == "missing":
            missing += 1
            continue
        if status not in {"downloaded", "cached"}:
            reasons.append(f"invalid_file_status:{archive_type}:{task['year_month']}:{status}")
            continue
        path = Path(str(record.get("path") or "")).expanduser().resolve()
        if not path.is_file():
            reasons.append(f"archive_file_missing:{archive_type}:{task['year_month']}")
            continue
        details = validate_gzip_file(path)
        if str(record.get("sha256") or "") != str(details["sha256"]):
            reasons.append(f"archive_sha256_mismatch:{archive_type}:{task['year_month']}")
            continue
        paths.append(path)
    if not tasks:
        reasons.append(f"no_planned_tasks:{archive_type}")
    return paths, reasons, missing


def _write_normalized_asset(
    output_root: Path,
    *,
    symbol: str,
    candles: list[dict[str, float | int]],
    funding: list[dict[str, float]],
) -> dict[str, Any]:
    kline_path = output_root / "gateio" / "klines" / f"{symbol}.json"
    funding_path = output_root / "gateio" / "funding" / f"{symbol}.json"
    _atomic_write_json(
        kline_path,
        {
            "schema": "trading_mvp_daily_ohlcv_v1",
            "exchange": "gateio",
            "symbol": symbol,
            "interval": "1d",
            "rows": candles,
        },
    )
    _atomic_write_json(
        funding_path,
        {
            "schema": "trading_mvp_funding_settlements_v1",
            "exchange": "gateio",
            "symbol": symbol,
            "rows": funding,
        },
    )
    return {
        "kline_path": str(kline_path),
        "kline_sha256": sha256_file(kline_path),
        "funding_path": str(funding_path),
        "funding_sha256": sha256_file(funding_path),
    }


def _build_split_manifest(
    *,
    run_id: str,
    stage: str,
    start_sec: int,
    end_sec: int,
    sealed: bool,
    universe: list[dict[str, Any]],
    normalized_files: list[dict[str, Any]],
    plan_path: Path,
    plan_hash: str,
    collect_manifest_path: Path,
    collect_artifact_hash: str,
) -> dict[str, Any]:
    if stage not in {"train_view", "sealed_oos"}:
        raise ValueError(f"unsupported split stage: {stage}")
    manifest: dict[str, Any] = {
        "schema": SPLIT_MANIFEST_SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": run_id,
        "stage": stage,
        "range": {"start_sec": int(start_sec), "end_sec": int(end_sec)},
        "sealed": bool(sealed),
        "oos_paths_present": stage == "sealed_oos",
        "point_in_time_universe": True,
        "historical_universe": True,
        "lifecycle_mask_applied": True,
        "no_interpolation": True,
        "universe": universe,
        "normalized_files": normalized_files,
        "input_provenance": {
            "plan_sha256": sha256_file(plan_path),
            "plan_hash": plan_hash,
            "collect_manifest_sha256": sha256_file(collect_manifest_path),
            "collect_artifact_hash": collect_artifact_hash,
        },
    }
    manifest["artifact_hash"] = _normalized_manifest_hash(manifest)
    return manifest


def _cached_split_is_valid(
    *,
    root_manifest: Mapping[str, Any],
    report: Mapping[str, Any],
) -> bool:
    split_index = root_manifest.get("split_manifests")
    if not isinstance(split_index, Mapping):
        return False
    expected = {
        "train": ("train_view", str(report.get("train_manifest_hash") or "")),
        "oos": ("sealed_oos", str(report.get("oos_commitment_hash") or "")),
    }
    for key, (stage, expected_hash) in expected.items():
        record = split_index.get(key)
        if not isinstance(record, Mapping):
            return False
        path = Path(str(record.get("path") or "")).expanduser().resolve()
        if not path.is_file() or str(record.get("file_sha256") or "") != sha256_file(path):
            return False
        manifest = _read_json_object(path)
        artifact_hash = str(manifest.get("artifact_hash") or "")
        if (
            manifest.get("schema") != SPLIT_MANIFEST_SCHEMA
            or manifest.get("stage") != stage
            or artifact_hash != _normalized_manifest_hash(manifest)
            or artifact_hash != str(record.get("artifact_hash") or "")
            or artifact_hash != expected_hash
        ):
            return False
        normalized_files = manifest.get("normalized_files")
        if not isinstance(normalized_files, list):
            return False
        split_root = path.parent.resolve()
        for file_record in normalized_files:
            if not isinstance(file_record, Mapping):
                return False
            for path_key, hash_key in (
                ("kline_path", "kline_sha256"),
                ("funding_path", "funding_sha256"),
            ):
                target = Path(str(file_record.get(path_key) or "")).expanduser().resolve()
                if (
                    not target.is_file()
                    or not target.is_relative_to(split_root)
                    or str(file_record.get(hash_key) or "") != sha256_file(target)
                ):
                    return False
    return True


def build_history_quality(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    collect_manifest_path: str | Path,
    expected_collect_artifact_hash: str,
    output_root: str | Path,
    report_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    started = time.monotonic()
    deadline = started + runtime
    resolved_plan = Path(plan_path).expanduser().resolve()
    resolved_collect = Path(collect_manifest_path).expanduser().resolve()
    resolved_output = Path(output_root).expanduser().resolve()
    resolved_report = Path(report_path).expanduser().resolve()
    plan = authorize_history_collect(resolved_plan, expected_plan_hash)
    collect_manifest = _validate_collect_manifest(
        resolved_collect,
        expected_plan_hash=expected_plan_hash,
        expected_artifact_hash=expected_collect_artifact_hash,
    )

    if resolved_report.is_file():
        cached = _read_json_object(resolved_report)
        normalized_path = resolved_output / "manifest.json"
        if (
            cached.get("schema") == SCHEMA
            and cached.get("final") is True
            and cached.get("plan_hash") == expected_plan_hash
            and cached.get("collect_artifact_hash") == expected_collect_artifact_hash
            and cached.get("artifact_hash") == _quality_hash(cached)
            and normalized_path.is_file()
        ):
            normalized = _read_json_object(normalized_path)
            if (
                normalized.get("artifact_hash") == _normalized_manifest_hash(normalized)
                and _cached_split_is_valid(root_manifest=normalized, report=cached)
            ):
                cached["cache_reused"] = True
                return cached

    file_index = _manifest_file_index(collect_manifest)
    per_asset: list[dict[str, Any]] = []
    normalized_universe: list[dict[str, Any]] = []
    train_files: list[dict[str, Any]] = []
    oos_files: list[dict[str, Any]] = []
    accepted_asset_ids: set[str] = set()
    parse_error_samples: list[str] = []
    split_contract = plan.get("split_contract")
    if not isinstance(split_contract, Mapping):
        raise ValueError("history plan split contract is missing")
    warmup = split_contract.get("warmup")
    train = split_contract.get("train")
    oos = split_contract.get("oos")
    if not all(isinstance(item, Mapping) for item in (warmup, train, oos)):
        raise ValueError("history plan split ranges are missing")
    train_view_start_sec = int(warmup["start_sec"])
    oos_start_sec = int(oos["start_sec"])
    history_end_sec = int(oos["end_sec"])
    if int(train["end_sec"]) != oos_start_sec:
        raise ValueError("history plan train/OOS boundary is not contiguous")
    train_root = resolved_output / "train"
    oos_root = resolved_output / "oos-sealed"
    try:
        planned_assets = list(plan["universe"]["eligible"])
        for asset_index, asset in enumerate(planned_assets, 1):
            if time.monotonic() >= deadline:
                raise TimeoutError("history-quality runtime exhausted before all assets")
            symbol = str(asset["symbol"])
            canonical_id = str(asset["canonical_asset_id"])
            reasons: list[str] = []
            candle_paths, candle_file_reasons, candle_missing = _validated_paths_for_asset(
                symbol=symbol,
                archive_type="candlesticks_1h",
                plan=plan,
                file_index=file_index,
            )
            funding_paths, funding_file_reasons, funding_missing = _validated_paths_for_asset(
                symbol=symbol,
                archive_type="funding_applies",
                plan=plan,
                file_index=file_index,
            )
            reasons.extend(candle_file_reasons)
            reasons.extend(funding_file_reasons)
            try:
                candles, candle_metrics, candle_reasons = normalize_candlestick_archives(
                    candle_paths,
                    contract_multiplier=float(asset["contract_multiplier"]),
                    start_sec=int(asset["history_start_sec"]),
                    end_sec=int(asset["history_end_sec"]),
                    deadline_monotonic=deadline,
                )
                reasons.extend(candle_reasons)
            except Exception as exc:  # noqa: BLE001 - asset-level quality failure.
                candles = []
                candle_metrics = {"error": f"{type(exc).__name__}: {exc}"}
                reasons.append("candlestick_normalization_failed")
            try:
                funding_interval = int(asset.get("funding_interval_sec") or 0)
                funding, funding_metrics, funding_reasons = normalize_funding_archives(
                    funding_paths,
                    start_sec=int(asset["history_start_sec"]),
                    end_sec=int(asset["history_end_sec"]),
                    funding_interval_sec=funding_interval,
                    deadline_monotonic=deadline,
                )
                reasons.extend(funding_reasons)
            except Exception as exc:  # noqa: BLE001 - asset-level quality failure.
                funding = []
                funding_metrics = {"error": f"{type(exc).__name__}: {exc}"}
                reasons.append("funding_normalization_failed")
            reasons = sorted(set(reasons))
            accepted = not reasons
            if accepted:
                train_candles, oos_candles = partition_rows_by_embargo(
                    candles,
                    train_view_start_sec=train_view_start_sec,
                    oos_start_sec=oos_start_sec,
                    history_end_sec=history_end_sec,
                )
                train_funding, oos_funding = partition_rows_by_embargo(
                    funding,
                    train_view_start_sec=train_view_start_sec,
                    oos_start_sec=oos_start_sec,
                    history_end_sec=history_end_sec,
                )
                train_file_hashes = _write_normalized_asset(
                    train_root,
                    symbol=symbol,
                    candles=train_candles,
                    funding=train_funding,
                )
                oos_file_hashes = _write_normalized_asset(
                    oos_root,
                    symbol=symbol,
                    candles=oos_candles,
                    funding=oos_funding,
                )
                daily_quote = [
                    float(row["volume_quote"])
                    for row in train_candles
                    if float(row["volume_quote"]) > 0
                ]
                historical_median_quote = statistics.median(daily_quote) if daily_quote else 0.0
                normalized_universe.append(
                    {
                        "exchange": "gateio",
                        "symbol": symbol,
                        "base": str(asset["base"]),
                        "quote": "USDT",
                        "canonical_asset_id": canonical_id,
                        "coin_id": str(asset["coin_id"]),
                        "non_binance_baseline": True,
                        "non_binance_evidence": str(asset["non_binance_evidence"]),
                        "volume_24h_quote": historical_median_quote,
                        "volume_source": "historical_daily_median_quote_volume",
                        "listed_from_ts": int(asset["listed_from_ts"]),
                        "listed_to_ts": asset.get("listed_to_ts"),
                        "status": "active" if asset.get("listed_to_ts") is None else "delisted",
                        "is_delisted": asset.get("listed_to_ts") is not None,
                        "survivorship_status": str(asset["lifecycle_status"]),
                        "contract_multiplier": float(asset["contract_multiplier"]),
                    }
                )
                train_files.append({"symbol": symbol, **train_file_hashes})
                oos_files.append({"symbol": symbol, **oos_file_hashes})
                accepted_asset_ids.add(canonical_id)
            for metric in (candle_metrics, funding_metrics):
                error = metric.get("error") if isinstance(metric, Mapping) else None
                if error and len(parse_error_samples) < MAX_REPORTED_PARSE_ERRORS:
                    parse_error_samples.append(f"{symbol}: {error}")
            per_asset.append(
                {
                    "symbol": symbol,
                    "base": str(asset["base"]),
                    "canonical_asset_id": canonical_id,
                    "accepted": accepted,
                    "reasons": reasons,
                    "missing_archive_files": {
                        "candlesticks_1h": candle_missing,
                        "funding_applies": funding_missing,
                    },
                    "candlesticks": candle_metrics,
                    "funding": funding_metrics,
                }
            )
            candle_coverage = candle_metrics.get("hourly_coverage", 0.0)
            funding_coverage = funding_metrics.get("settlement_coverage", 0.0)
            print(
                "[membership-history-quality] "
                f"{asset_index}/{len(planned_assets)} symbol={symbol} accepted={accepted} "
                f"candle_coverage={float(candle_coverage):.4f} "
                f"funding_coverage={float(funding_coverage):.4f} "
                f"reasons={','.join(reasons) if reasons else '-'}",
                flush=True,
            )
    except Exception as exc:
        report: dict[str, Any] = {
            "schema": SCHEMA,
            "generated_at_utc": _utc_now(),
            "run_id": plan["run_id"],
            "plan_path": str(resolved_plan),
            "plan_hash": expected_plan_hash,
            "collect_manifest_path": str(resolved_collect),
            "collect_artifact_hash": expected_collect_artifact_hash,
            "output_root": str(resolved_output),
            "final": False,
            "accepted": False,
            "decision": STOPPED_INCOMPLETE_DECISION,
            "runtime_sec": time.monotonic() - started,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "processed_assets": len(per_asset),
            "per_asset": per_asset,
            "cache_reused": False,
            "replay_allowed": False,
            "oos_allowed": False,
            "grid_allowed": False,
            "live_orders": False,
            "private_api_keys": False,
            "next_allowed_command": "fast-edge-membership-history-quality",
        }
        report["artifact_hash"] = _quality_hash(report)
        _atomic_write_json(resolved_report, report)
        return report

    normalized_universe.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    train_files.sort(key=lambda row: row["symbol"])
    oos_files.sort(key=lambda row: row["symbol"])
    accepted_count = len(accepted_asset_ids)
    quality_accepted = accepted_count >= MINIMUM_CANONICAL_ASSETS
    train_manifest = _build_split_manifest(
        run_id=str(plan["run_id"]),
        stage="train_view",
        start_sec=train_view_start_sec,
        end_sec=oos_start_sec,
        sealed=False,
        universe=normalized_universe,
        normalized_files=train_files,
        plan_path=resolved_plan,
        plan_hash=expected_plan_hash,
        collect_manifest_path=resolved_collect,
        collect_artifact_hash=expected_collect_artifact_hash,
    )
    oos_manifest = _build_split_manifest(
        run_id=str(plan["run_id"]),
        stage="sealed_oos",
        start_sec=oos_start_sec,
        end_sec=history_end_sec,
        sealed=True,
        universe=normalized_universe,
        normalized_files=oos_files,
        plan_path=resolved_plan,
        plan_hash=expected_plan_hash,
        collect_manifest_path=resolved_collect,
        collect_artifact_hash=expected_collect_artifact_hash,
    )
    train_manifest_path = train_root / "manifest.json"
    oos_manifest_path = oos_root / "manifest.json"
    _atomic_write_json(train_manifest_path, train_manifest)
    _atomic_write_json(oos_manifest_path, oos_manifest)
    normalized_manifest: dict[str, Any] = {
        "schema": NORMALIZED_MANIFEST_SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": plan["run_id"],
        "params": {
            "start_sec": int(plan["history_window"]["start_sec"]),
            "end_sec": int(plan["history_window"]["end_sec"]),
            "exchanges": ["gateio"],
            "interval": "1d",
        },
        "point_in_time_universe": True,
        "historical_universe": True,
        "lifecycle_mask_applied": True,
        "no_interpolation": True,
        "current_non_binance_registry_reference_only": True,
        "historical_binance_membership_proven": False,
        "quality_accepted": quality_accepted,
        "replay_allowed": False,
        "oos_allowed": False,
        "grid_allowed": False,
        "universe": normalized_universe,
        "split_contract": split_contract,
        "split_manifests": {
            "train": {
                "stage": "train_view",
                "path": str(train_manifest_path),
                "file_sha256": sha256_file(train_manifest_path),
                "artifact_hash": train_manifest["artifact_hash"],
            },
            "oos": {
                "stage": "sealed_oos",
                "path": str(oos_manifest_path),
                "file_sha256": sha256_file(oos_manifest_path),
                "artifact_hash": oos_manifest["artifact_hash"],
            },
        },
        "input_provenance": {
            "plan_path": str(resolved_plan),
            "plan_sha256": sha256_file(resolved_plan),
            "plan_hash": expected_plan_hash,
            "collect_manifest_path": str(resolved_collect),
            "collect_manifest_sha256": sha256_file(resolved_collect),
            "collect_artifact_hash": expected_collect_artifact_hash,
        },
    }
    normalized_manifest["artifact_hash"] = _normalized_manifest_hash(normalized_manifest)
    _atomic_write_json(resolved_output / "manifest.json", normalized_manifest)

    rejection_reasons = (
        []
        if quality_accepted
        else [f"fewer_than_{MINIMUM_CANONICAL_ASSETS}_quality_accepted_canonical_assets"]
    )
    report = {
        "schema": SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": plan["run_id"],
        "plan_path": str(resolved_plan),
        "plan_hash": expected_plan_hash,
        "collect_manifest_path": str(resolved_collect),
        "collect_artifact_hash": expected_collect_artifact_hash,
        "normalized_manifest_path": str(resolved_output / "manifest.json"),
        "normalized_manifest_hash": normalized_manifest["artifact_hash"],
        "train_manifest_path": str(train_manifest_path),
        "train_manifest_hash": train_manifest["artifact_hash"],
        "oos_manifest_path": str(oos_manifest_path),
        "oos_commitment_hash": oos_manifest["artifact_hash"],
        "output_root": str(resolved_output),
        "final": True,
        "accepted": quality_accepted,
        "decision": ACCEPTED_DECISION if quality_accepted else REJECTED_DECISION,
        "runtime_sec": time.monotonic() - started,
        "cache_reused": False,
        "minimum_canonical_assets": MINIMUM_CANONICAL_ASSETS,
        "minimum_series_coverage": MINIMUM_SERIES_COVERAGE,
        "planned_assets": len(plan["universe"]["eligible"]),
        "accepted_assets": accepted_count,
        "rejected_assets": len(per_asset) - accepted_count,
        "rejection_reasons": rejection_reasons,
        "per_asset": sorted(per_asset, key=lambda row: (row["canonical_asset_id"], row["symbol"])),
        "parse_error_samples": parse_error_samples,
        "data_access_audit": {
            "prices_read_for_normalization": True,
            "returns_computed": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_read": False,
        },
        "research_only": True,
        "public_data_only": True,
        "replay_allowed": False,
        "oos_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "next_allowed_command": (
            "create_hash_bound_gate_membership_momentum_train_planonly"
            if quality_accepted
            else "none_membership_history_branch_closed"
        ),
        "limitations": [
            "Gate-only history is weaker evidence and does not establish MEXC portability.",
            "The frozen registry proves current Binance exclusion only, not historical exclusion.",
            "Historical OHLCV and funding do not prove executable fills or capacity.",
        ],
    }
    report["artifact_hash"] = _quality_hash(report)
    _atomic_write_json(resolved_report, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize and quality-gate Gate membership history archives.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--collect-manifest", required=True)
    parser.add_argument("--expected-collect-artifact-hash", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    args = parser.parse_args()
    result = build_history_quality(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        collect_manifest_path=args.collect_manifest,
        expected_collect_artifact_hash=args.expected_collect_artifact_hash,
        output_root=args.output_root,
        report_path=args.report,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("final") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
