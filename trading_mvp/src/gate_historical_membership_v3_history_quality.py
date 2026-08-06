from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import gate_historical_archive as gate_archive
import gate_historical_membership_history_collector as archive_io
import gate_historical_membership_v3_history_collector as v3_collector
import gate_historical_membership_v3_history_plan as history_plan


PLAN_SCHEMA = "trading_mvp_gate_historical_membership_v3_history_quality_plan_v1"
REPORT_SCHEMA = "trading_mvp_gate_historical_membership_v3_history_quality_v1"
NORMALIZED_MANIFEST_SCHEMA = "trading_mvp_gate_membership_daily_history_v2"
SPLIT_MANIFEST_SCHEMA = "trading_mvp_gate_membership_daily_history_split_v2"
PLAN_DECISION = "GATE_MEMBERSHIP_V3_HISTORY_QUALITY_PLAN_READY"
ACCEPTED_DECISION = (
    "GATE_MEMBERSHIP_V3_HISTORY_QUALITY_ACCEPTED_READY_FOR_FROZEN_TRAIN_PLANONLY"
)
REJECTED_DECISION = "GATE_MEMBERSHIP_V3_HISTORY_QUALITY_REJECTED"
STOPPED_INCOMPLETE_DECISION = "GATE_MEMBERSHIP_V3_HISTORY_QUALITY_STOPPED_INCOMPLETE"
MAX_RUNTIME_SEC = 1800
HOUR_SEC = 3_600
DAY_SEC = 86_400
MINIMUM_SERIES_COVERAGE = 0.98
MINIMUM_DELISTED_END_COVERAGE = 0.90
MINIMUM_FUNDING_INTERVAL_CONFIDENCE = 0.80
ALLOWED_FUNDING_INTERVALS_SEC = (3_600, 7_200, 14_400, 28_800)
MAX_REPORTED_PARSE_ERRORS = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {resolved}")
    return payload


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved.name}.", suffix=".tmp", dir=resolved.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
        os.replace(temporary_name, resolved)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    if resolved.exists():
        if _read_json_object(resolved) != dict(payload):
            raise FileExistsError(f"refusing to overwrite immutable quality PlanOnly: {resolved}")
        return
    _atomic_write_json(resolved, payload)


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    return history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "runtime_sec", "artifact_hash", "cache_reused"}
        }
    )


def _normalized_manifest_hash(payload: Mapping[str, Any]) -> str:
    return history_plan.sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "artifact_hash"}
        }
    )


def _validate_collect_manifest_metadata(
    path: str | Path,
    *,
    frozen_history_plan: Mapping[str, Any],
    expected_artifact_hash: str,
) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    manifest = _read_json_object(resolved)
    artifact_hash = str(manifest.get("artifact_hash") or "")
    if (
        manifest.get("schema") != v3_collector.MANIFEST_SCHEMA
        or manifest.get("final") is not True
        or manifest.get("decision") != v3_collector.READY_FOR_QUALITY_PLAN_DECISION
        or manifest.get("plan_hash") != frozen_history_plan.get("plan_hash")
        or manifest.get("next_allowed_command")
        != "create_hash_bound_membership_v3_history_quality_planonly"
        or artifact_hash != v3_collector._manifest_hash(manifest)
        or artifact_hash != str(expected_artifact_hash)
    ):
        raise ValueError("collector manifest is not a hash-valid final v3 quality input")
    audit = manifest.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(
        audit.get(key) is not False
        for key in ("prices_parsed", "returns_read", "signals_read", "pnl_read", "oos_read")
    ):
        raise ValueError("collector manifest data-access audit is unsafe")
    summary = manifest.get("summary")
    records = manifest.get("files")
    tasks = frozen_history_plan.get("archive_tasks")
    if not isinstance(summary, Mapping) or not isinstance(records, list) or not isinstance(tasks, list):
        raise ValueError("collector manifest task inventory is missing")
    if (
        int(summary.get("errors") or 0) != 0
        or int(summary.get("total_tasks") or 0) != len(tasks)
        or int(summary.get("completed_tasks") or 0) != len(tasks)
        or len(records) != len(tasks)
    ):
        raise ValueError("collector manifest task coverage is incomplete")
    task_index = {str(task.get("cache_key") or ""): task for task in tasks}
    if len(task_index) != len(tasks) or "" in task_index:
        raise ValueError("history plan task inventory is invalid")
    output_root = Path(str(manifest.get("output_root") or "")).expanduser().resolve()
    seen: set[str] = set()
    status_counts: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("invalid collector file record")
        cache_key = str(record.get("cache_key") or "")
        task = task_index.get(cache_key)
        if task is None or cache_key in seen:
            raise ValueError("collector file record is not bound to exactly one planned task")
        seen.add(cache_key)
        for key in ("symbol", "canonical_asset_id", "archive_type", "year_month", "url"):
            if str(record.get(key) or "") != str(task.get(key) or ""):
                raise ValueError(f"collector file record differs from planned task: {key}")
        status = str(record.get("status") or "")
        if status not in {"downloaded", "cached", "missing"}:
            raise ValueError(f"collector file status is not final: {status}")
        status_counts[status] += 1
        if status in {"downloaded", "cached"}:
            target = Path(str(record.get("path") or "")).expanduser().resolve()
            if not target.is_relative_to(output_root):
                raise ValueError("collector file path is outside collector output root")
            if not target.is_file():
                raise ValueError("collector file declared complete but is missing")
    if seen != set(task_index):
        raise ValueError("collector file inventory does not cover the frozen task set")
    for key in ("downloaded", "cached", "missing"):
        if int(summary.get(key) or 0) != status_counts[key]:
            raise ValueError(f"collector summary count mismatch: {key}")
    return manifest, output_root


def build_quality_plan(
    *,
    history_plan_path: str | Path,
    expected_history_plan_hash: str,
    collect_manifest_path: str | Path,
    expected_collect_artifact_hash: str,
    output_path: str | Path | None,
    run_id: str,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    runtime = int(max_runtime_sec)
    if runtime < 1 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"MaxRuntimeSec must be in [1, {MAX_RUNTIME_SEC}]")
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise ValueError("run_id is required")
    history_path = Path(history_plan_path).expanduser().resolve()
    frozen_history = history_plan.authorize_history_collect(
        history_path, str(expected_history_plan_hash)
    )
    collect_path = Path(collect_manifest_path).expanduser().resolve()
    collect_manifest, collect_root = _validate_collect_manifest_metadata(
        collect_path,
        frozen_history_plan=frozen_history,
        expected_artifact_hash=expected_collect_artifact_hash,
    )
    module_path = Path(__file__).resolve()
    code_paths = {
        "module": module_path,
        "history_plan_module": Path(history_plan.__file__).resolve(),
        "collector_module": Path(v3_collector.__file__).resolve(),
        "archive_module": Path(gate_archive.__file__).resolve(),
        "archive_io_module": Path(archive_io.__file__).resolve(),
    }
    contract: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "run_id": normalized_run_id,
        "stage": "history_quality_planonly",
        "decision": PLAN_DECISION,
        "network_access": False,
        "quality_allowed_now": True,
        "history_input": {
            "plan_path": str(history_path),
            "plan_sha256": history_plan.sha256_file(history_path),
            "plan_hash": str(expected_history_plan_hash),
            "input_merkle_sha256": frozen_history["input_merkle_sha256"],
            "collect_manifest_path": str(collect_path),
            "collect_manifest_sha256": history_plan.sha256_file(collect_path),
            "collect_artifact_hash": str(expected_collect_artifact_hash),
            "collect_output_root": str(collect_root),
            "collect_file_count": len(collect_manifest["files"]),
        },
        "split_contract": frozen_history["split_contract"],
        "quality_gates": {
            "minimum_canonical_assets": int(
                frozen_history["future_quality_gates"]["minimum_canonical_assets"]
            ),
            "minimum_series_coverage": float(
                frozen_history["future_quality_gates"]["minimum_series_coverage"]
            ),
            "minimum_delisted_end_coverage": float(
                frozen_history["future_quality_gates"]["minimum_delisted_end_coverage"]
            ),
            "minimum_funding_interval_confidence": float(
                frozen_history["future_quality_gates"][
                    "minimum_funding_interval_confidence"
                ]
            ),
            "no_interpolation": True,
            "no_duplicate_timestamps": True,
            "physical_oos_embargo": True,
        },
        "runtime_contract": {
            "max_runtime_sec": runtime,
            "absolute_cap_sec": MAX_RUNTIME_SEC,
            "visible_terminal_required": True,
            "local_immutable_inputs_only": True,
            "timeout_verdict": STOPPED_INCOMPLETE_DECISION,
        },
        "code_provenance": {
            f"{name}_path": str(path) for name, path in code_paths.items()
        }
        | {
            f"{name}_sha256": history_plan.sha256_file(path)
            for name, path in code_paths.items()
        },
        "data_access_audit": {
            "archive_payload_read": False,
            "prices_read_for_normalization": False,
            "returns_computed": False,
            "signals_read": False,
            "pnl_read": False,
            "oos_evaluated": False,
        },
        "next_allowed_command": "fast-edge-membership-v3-history-quality",
        "blocked_actions": [
            "train_before_quality_accept",
            "oos",
            "grid_search",
            "retune",
            "execution_probe",
            "paper_forward",
            "live_orders",
            "private_api_keys",
        ],
    }
    contract["input_merkle_sha256"] = history_plan.sha256_json(
        {
            "history_plan_hash": expected_history_plan_hash,
            "history_plan_sha256": contract["history_input"]["plan_sha256"],
            "collect_artifact_hash": expected_collect_artifact_hash,
            "collect_manifest_sha256": contract["history_input"]["collect_manifest_sha256"],
            **{
                key: value
                for key, value in contract["code_provenance"].items()
                if key.endswith("_sha256")
            },
        }
    )
    plan_hash = history_plan.sha256_json(contract)
    payload: dict[str, Any] = {
        **contract,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "plan_hash": plan_hash,
        "frozen_contract": contract,
    }
    if output_path is not None:
        _write_json_immutable(output_path, payload)
    return payload


def authorize_quality_evaluation(
    plan_path: str | Path,
    expected_plan_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    resolved_plan = Path(plan_path).expanduser().resolve()
    plan = _read_json_object(resolved_plan)
    frozen = plan.get("frozen_contract")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("decision") != PLAN_DECISION:
        raise ValueError("unexpected membership-v3 quality PlanOnly artifact")
    if not isinstance(frozen, Mapping):
        raise ValueError("quality frozen contract is missing")
    computed = history_plan.sha256_json(frozen)
    if (
        plan.get("plan_hash") != computed
        or str(expected_plan_hash) != computed
        or not all(plan.get(key) == value for key, value in frozen.items())
    ):
        raise ValueError("quality plan hash mismatch")
    if plan.get("next_allowed_command") != "fast-edge-membership-v3-history-quality":
        raise ValueError("quality evaluation is not the next allowed command")
    code = plan.get("code_provenance")
    expected_paths = {
        "module": Path(__file__).resolve(),
        "history_plan_module": Path(history_plan.__file__).resolve(),
        "collector_module": Path(v3_collector.__file__).resolve(),
        "archive_module": Path(gate_archive.__file__).resolve(),
        "archive_io_module": Path(archive_io.__file__).resolve(),
    }
    if not isinstance(code, Mapping):
        raise ValueError("quality code provenance is missing")
    for name, expected_path in expected_paths.items():
        actual = Path(str(code.get(f"{name}_path") or "")).expanduser().resolve()
        if (
            actual != expected_path
            or not actual.is_file()
            or code.get(f"{name}_sha256") != history_plan.sha256_file(actual)
        ):
            raise ValueError(f"quality pipeline module hash mismatch: {expected_path.name}")
    inputs = plan.get("history_input")
    if not isinstance(inputs, Mapping):
        raise ValueError("quality input provenance is missing")
    source_plan_path = Path(str(inputs.get("plan_path") or "")).expanduser().resolve()
    if history_plan.sha256_file(source_plan_path) != str(inputs.get("plan_sha256") or ""):
        raise ValueError("history plan file hash mismatch")
    frozen_history = history_plan.authorize_history_collect(
        source_plan_path, str(inputs.get("plan_hash") or "")
    )
    collect_path = Path(str(inputs.get("collect_manifest_path") or "")).expanduser().resolve()
    if history_plan.sha256_file(collect_path) != str(inputs.get("collect_manifest_sha256") or ""):
        raise ValueError("collector manifest file hash mismatch")
    collect_manifest, collect_root = _validate_collect_manifest_metadata(
        collect_path,
        frozen_history_plan=frozen_history,
        expected_artifact_hash=str(inputs.get("collect_artifact_hash") or ""),
    )
    if str(collect_root) != str(inputs.get("collect_output_root") or ""):
        raise ValueError("collector output root differs from quality PlanOnly")
    return plan, frozen_history, collect_manifest, collect_root


def _iter_gzip_lines(paths: Iterable[Path]) -> Iterable[tuple[Path, int, str]]:
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.strip()
                if text:
                    yield path, line_number, text


def _expected_hour_count(start_sec: int, end_sec: int) -> int:
    first = ((int(start_sec) + HOUR_SEC - 1) // HOUR_SEC) * HOUR_SEC
    if first >= int(end_sec):
        return 0
    return ((int(end_sec) - 1 - first) // HOUR_SEC) + 1


def normalize_candlestick_archives_v3(
    paths: Iterable[Path],
    *,
    contract_multiplier: float,
    acquisition_start_sec: int,
    acquisition_end_sec: int,
    lifecycle_end_resolution: str,
    resolved_lifecycle_end_sec: int | None,
    minimum_coverage: float = MINIMUM_SERIES_COVERAGE,
    deadline_monotonic: float | None = None,
) -> tuple[list[dict[str, float | int]], dict[str, Any], list[str]]:
    multiplier = float(contract_multiplier)
    start = int(acquisition_start_sec)
    acquisition_end = int(acquisition_end_sec)
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("contract_multiplier must be positive")
    if start < 0 or acquisition_end <= start:
        raise ValueError("invalid acquisition range")
    resolution = str(lifecycle_end_resolution)
    observed: dict[int, dict[str, float]] = {}
    parse_errors: list[str] = []
    duplicates = 0
    outside_before = 0
    outside_after = 0
    line_count = 0
    for path, line_number, line in _iter_gzip_lines(paths):
        line_count += 1
        if (
            deadline_monotonic is not None
            and line_count % 10_000 == 0
            and time.monotonic() >= deadline_monotonic
        ):
            raise TimeoutError("membership-v3 candle normalization runtime exhausted")
        try:
            row = gate_archive.parse_gate_archive_candlestick(line)
            timestamp = int(row["ts"])
            if timestamp % HOUR_SEC:
                raise ValueError("candlestick timestamp is not hourly aligned")
            if timestamp < start:
                outside_before += 1
                continue
            if timestamp >= acquisition_end:
                outside_after += 1
                continue
            if timestamp in observed:
                duplicates += 1
                continue
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            contracts = float(row["volume_contracts"])
            if not all(
                math.isfinite(value)
                for value in (open_price, high_price, low_price, close_price, contracts)
            ):
                raise ValueError("candlestick contains non-finite values")
            if (
                min(open_price, high_price, low_price, close_price) <= 0
                or contracts < 0
                or high_price < max(open_price, close_price)
                or low_price > min(open_price, close_price)
            ):
                raise ValueError("candlestick values are inconsistent")
            base_volume = contracts * multiplier
            quote_volume = base_volume * close_price
            observed[timestamp] = {
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume_base": base_volume,
                "volume_quote": quote_volume,
            }
        except Exception as exc:  # parse failures are quality evidence
            if len(parse_errors) < MAX_REPORTED_PARSE_ERRORS:
                parse_errors.append(f"{path.name}:{line_number}: {type(exc).__name__}: {exc}")

    reasons: list[str] = []
    resolved_end: int | None
    quality_end: int | None
    output_resolution = resolution
    if resolution == "archive_observed_pending":
        if observed:
            quality_end = min(acquisition_end, max(observed) + HOUR_SEC)
            resolved_end = quality_end
            output_resolution = "archive_observed_end"
        else:
            quality_end = None
            resolved_end = None
            reasons.append("unresolved_archive_observed_lifecycle_end")
    elif resolution == "contract_metadata":
        resolved_end = int(resolved_lifecycle_end_sec or 0)
        quality_end = resolved_end
        if not start < resolved_end <= acquisition_end:
            reasons.append("invalid_contract_metadata_lifecycle_end")
            quality_end = None
    elif resolution == "open_at_frozen_snapshot":
        resolved_end = None
        quality_end = acquisition_end
    else:
        resolved_end = None
        quality_end = None
        reasons.append("unsupported_lifecycle_end_resolution")

    effective_observed: dict[int, dict[str, float]] = {}
    rows_after_lifecycle = 0
    if quality_end is not None:
        for timestamp, row in observed.items():
            if timestamp < quality_end:
                effective_observed[timestamp] = row
            else:
                rows_after_lifecycle += 1
    expected_hours = _expected_hour_count(start, quality_end) if quality_end is not None else 0
    coverage = min(1.0, len(effective_observed) / expected_hours) if expected_hours else 0.0
    daily: dict[int, dict[str, float | int]] = {}
    for timestamp in sorted(effective_observed):
        row = effective_observed[timestamp]
        day_ts = (timestamp // DAY_SEC) * DAY_SEC
        target = daily.get(day_ts)
        if target is None:
            daily[day_ts] = {
                "ts": day_ts,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume_base": row["volume_base"],
                "volume_quote": row["volume_quote"],
                "observed_hours": 1,
            }
        else:
            target["high"] = max(float(target["high"]), row["high"])
            target["low"] = min(float(target["low"]), row["low"])
            target["close"] = row["close"]
            target["volume_base"] = float(target["volume_base"]) + row["volume_base"]
            target["volume_quote"] = float(target["volume_quote"]) + row["volume_quote"]
            target["observed_hours"] = int(target["observed_hours"]) + 1
    if coverage < float(minimum_coverage):
        reasons.append("candlestick_coverage_below_minimum")
    if duplicates:
        reasons.append("duplicate_candlestick_timestamps")
    if parse_errors:
        reasons.append("candlestick_parse_errors")
    if not daily:
        reasons.append("no_daily_candlesticks")
    metrics = {
        "raw_nonempty_lines": line_count,
        "observed_hourly_rows": len(effective_observed),
        "expected_hourly_rows": expected_hours,
        "hourly_coverage": coverage,
        "daily_rows": len(daily),
        "duplicate_timestamps": duplicates,
        "parse_error_count": len(parse_errors),
        "parse_error_samples": parse_errors,
        "rows_before_lifecycle_filtered": outside_before,
        "rows_after_acquisition_filtered": outside_after,
        "rows_after_lifecycle_filtered": rows_after_lifecycle,
        "quality_window_start_sec": start,
        "quality_window_end_sec": quality_end,
        "lifecycle_end_resolution": output_resolution,
        "resolved_lifecycle_end_sec": resolved_end,
        "quote_volume_formula": "volume_contracts * close_price * contract_multiplier",
    }
    return [daily[key] for key in sorted(daily)], metrics, sorted(set(reasons))


def _infer_funding_interval(timestamps: list[int]) -> tuple[int | None, float]:
    if len(timestamps) < 2:
        return None, 0.0
    differences = [right - left for left, right in zip(timestamps, timestamps[1:]) if right > left]
    if not differences:
        return None, 0.0
    candidates: list[tuple[float, int, int]] = []
    for interval in ALLOWED_FUNDING_INTERVALS_SEC:
        divisible = sum(diff >= interval and diff % interval == 0 for diff in differences)
        exact = sum(diff == interval for diff in differences)
        confidence = divisible / len(differences)
        if exact or confidence == 1.0:
            candidates.append((confidence, interval, exact))
    if not candidates:
        return None, 0.0
    confidence, interval, _ = max(candidates, key=lambda row: (row[0], row[1], row[2]))
    return interval, confidence


def normalize_funding_archives_v3(
    paths: Iterable[Path],
    *,
    start_sec: int,
    end_sec: int,
    minimum_coverage: float = MINIMUM_SERIES_COVERAGE,
    minimum_interval_confidence: float = MINIMUM_FUNDING_INTERVAL_CONFIDENCE,
    deadline_monotonic: float | None = None,
) -> tuple[list[dict[str, float | int]], dict[str, Any], list[str]]:
    start = int(start_sec)
    end = int(end_sec)
    if start < 0 or end <= start:
        raise ValueError("invalid funding normalization range")
    observed: dict[int, float] = {}
    parse_errors: list[str] = []
    duplicates = 0
    outside_before = 0
    outside_after = 0
    line_count = 0
    for path, line_number, line in _iter_gzip_lines(paths):
        line_count += 1
        if (
            deadline_monotonic is not None
            and line_count % 10_000 == 0
            and time.monotonic() >= deadline_monotonic
        ):
            raise TimeoutError("membership-v3 funding normalization runtime exhausted")
        try:
            row = gate_archive.parse_gate_archive_funding_apply(line)
            raw_timestamp = float(row["ts"])
            timestamp = int(round(raw_timestamp))
            rate = float(row["funding_rate"])
            if abs(raw_timestamp - timestamp) > 1e-6 or not math.isfinite(rate):
                raise ValueError("invalid funding settlement values")
            if timestamp < start:
                outside_before += 1
                continue
            if timestamp >= end:
                outside_after += 1
                continue
            if timestamp in observed:
                duplicates += 1
                continue
            observed[timestamp] = rate
        except Exception as exc:  # parse failures are quality evidence
            if len(parse_errors) < MAX_REPORTED_PARSE_ERRORS:
                parse_errors.append(f"{path.name}:{line_number}: {type(exc).__name__}: {exc}")
    timestamps = sorted(observed)
    interval, confidence = _infer_funding_interval(timestamps)
    expected = max(1, math.ceil((end - start) / interval)) if interval else 0
    coverage = min(1.0, len(timestamps) / expected) if expected else 0.0
    reasons: list[str] = []
    if interval is None or confidence < float(minimum_interval_confidence):
        reasons.append("funding_interval_not_reliably_resolved")
    if coverage < float(minimum_coverage):
        reasons.append("funding_coverage_below_minimum")
    if duplicates:
        reasons.append("duplicate_funding_timestamps")
    if parse_errors:
        reasons.append("funding_parse_errors")
    metrics = {
        "raw_nonempty_lines": line_count,
        "observed_settlements": len(timestamps),
        "expected_settlements": expected,
        "settlement_coverage": coverage,
        "funding_interval_sec": interval,
        "funding_interval_confidence": confidence,
        "duplicate_timestamps": duplicates,
        "parse_error_count": len(parse_errors),
        "parse_error_samples": parse_errors,
        "rows_before_lifecycle_filtered": outside_before,
        "rows_after_lifecycle_filtered": outside_after,
    }
    rows = [{"ts": timestamp, "funding_rate": observed[timestamp]} for timestamp in timestamps]
    return rows, metrics, sorted(set(reasons))


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
        timestamp = int(raw.get("ts"))
        if previous is not None and timestamp <= previous:
            raise ValueError("embargo rows must be strictly timestamp ordered")
        previous = timestamp
        if start <= timestamp < end:
            (train if timestamp < boundary else oos).append(dict(raw))
    return train, oos


def _file_index(
    collect_manifest: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in collect_manifest.get("files") or []:
        cache_key = str(record.get("cache_key") or "")
        if not cache_key or cache_key in result:
            raise ValueError("duplicate collector file cache key")
        result[cache_key] = record
    return result


def _validated_paths_for_asset(
    *,
    asset: Mapping[str, Any],
    archive_type: str,
    frozen_history: Mapping[str, Any],
    collect_manifest: Mapping[str, Any],
    collect_root: Path,
    file_index: Mapping[str, Mapping[str, Any]],
) -> tuple[list[Path], list[str], int]:
    symbol = str(asset["symbol"])
    tasks = [
        task
        for task in frozen_history.get("archive_tasks") or []
        if task.get("symbol") == symbol and task.get("archive_type") == archive_type
    ]
    paths: list[Path] = []
    seen_paths: set[Path] = set()
    reasons: list[str] = []
    missing = 0
    for task in sorted(tasks, key=lambda row: str(row["year_month"])):
        record = file_index.get(str(task["cache_key"]))
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
        if not path.is_relative_to(collect_root):
            reasons.append(f"archive_path_outside_collect_root:{archive_type}:{task['year_month']}")
            continue
        if not path.is_file():
            reasons.append(f"archive_file_missing:{archive_type}:{task['year_month']}")
            continue
        details = archive_io.validate_gzip_file(path)
        if details["sha256"] != str(record.get("sha256") or ""):
            reasons.append(f"archive_sha256_mismatch:{archive_type}:{task['year_month']}")
            continue
        if path not in seen_paths:
            seen_paths.add(path)
            paths.append(path)
    if not tasks:
        reasons.append(f"no_planned_tasks:{archive_type}")
    return paths, reasons, missing


def _write_normalized_asset(
    output_root: Path,
    *,
    symbol: str,
    candles: list[dict[str, Any]],
    funding: list[dict[str, Any]],
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
        "kline_sha256": history_plan.sha256_file(kline_path),
        "funding_path": str(funding_path),
        "funding_sha256": history_plan.sha256_file(funding_path),
    }


def _build_split_manifest(
    *,
    run_id: str,
    stage: str,
    start_sec: int,
    end_sec: int,
    universe: list[dict[str, Any]],
    files: list[dict[str, Any]],
    quality_plan_hash: str,
    history_plan_hash: str,
    collect_artifact_hash: str,
) -> dict[str, Any]:
    if stage not in {"train_view", "sealed_oos"}:
        raise ValueError("unsupported split stage")
    payload: dict[str, Any] = {
        "schema": SPLIT_MANIFEST_SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": run_id,
        "stage": stage,
        "range": {"start_sec": int(start_sec), "end_sec": int(end_sec)},
        "sealed": stage == "sealed_oos",
        "oos_paths_present": stage == "sealed_oos",
        "point_in_time_universe": True,
        "historical_universe": True,
        "lifecycle_mask_applied": True,
        "no_interpolation": True,
        "universe": universe,
        "normalized_files": files,
        "input_provenance": {
            "quality_plan_hash": quality_plan_hash,
            "history_plan_hash": history_plan_hash,
            "collect_artifact_hash": collect_artifact_hash,
        },
    }
    payload["artifact_hash"] = _normalized_manifest_hash(payload)
    return payload


def _train_universe_view(
    universe: Iterable[Mapping[str, Any]],
    *,
    oos_start_sec: int,
) -> list[dict[str, Any]]:
    boundary = int(oos_start_sec)
    result: list[dict[str, Any]] = []
    for raw in universe:
        row = dict(raw)
        listed_to = row.get("listed_to_ts")
        if listed_to is None or int(listed_to) > boundary:
            row["listed_to_ts"] = None
            row["status"] = "active"
            row["is_delisted"] = False
            row["survivorship_status"] = "trading_at_train_boundary"
            row["lifecycle_end_resolution"] = "not_observed_by_train_boundary"
            row["resolved_lifecycle_end_sec"] = None
        result.append(row)
    return result


def _cached_outputs_valid(
    *,
    report: Mapping[str, Any],
    output_root: Path,
    expected_plan_hash: str,
) -> bool:
    if (
        report.get("schema") != REPORT_SCHEMA
        or report.get("final") is not True
        or report.get("plan_hash") != expected_plan_hash
        or report.get("artifact_hash") != _artifact_hash(report)
    ):
        return False
    root_path = output_root / "manifest.json"
    if not root_path.is_file():
        return False
    root = _read_json_object(root_path)
    if root.get("artifact_hash") != _normalized_manifest_hash(root):
        return False
    for key, expected_stage in (("train", "train_view"), ("oos", "sealed_oos")):
        record = (root.get("split_manifests") or {}).get(key)
        if not isinstance(record, Mapping):
            return False
        path = Path(str(record.get("path") or "")).expanduser().resolve()
        if not path.is_file() or record.get("file_sha256") != history_plan.sha256_file(path):
            return False
        split = _read_json_object(path)
        if (
            split.get("schema") != SPLIT_MANIFEST_SCHEMA
            or split.get("stage") != expected_stage
            or split.get("artifact_hash") != _normalized_manifest_hash(split)
            or split.get("artifact_hash") != record.get("artifact_hash")
        ):
            return False
        split_root = path.parent.resolve()
        for file_record in split.get("normalized_files") or []:
            for path_key, hash_key in (
                ("kline_path", "kline_sha256"),
                ("funding_path", "funding_sha256"),
            ):
                target = Path(str(file_record.get(path_key) or "")).expanduser().resolve()
                if (
                    not target.is_file()
                    or not target.is_relative_to(split_root)
                    or file_record.get(hash_key) != history_plan.sha256_file(target)
                ):
                    return False
    return True


def evaluate_history_quality(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
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
    resolved_output = Path(output_root).expanduser().resolve()
    resolved_report = Path(report_path).expanduser().resolve()
    quality_plan, frozen_history, collect_manifest, collect_root = authorize_quality_evaluation(
        resolved_plan, str(expected_plan_hash)
    )
    planned_runtime = int(quality_plan["runtime_contract"]["max_runtime_sec"])
    if runtime > planned_runtime:
        raise ValueError(f"max_runtime_sec exceeds frozen quality runtime: {planned_runtime}")
    if resolved_report.is_file():
        cached = _read_json_object(resolved_report)
        if _cached_outputs_valid(
            report=cached,
            output_root=resolved_output,
            expected_plan_hash=str(expected_plan_hash),
        ):
            cached["cache_reused"] = True
            return cached
    gates = quality_plan["quality_gates"]
    split = quality_plan["split_contract"]
    warmup = split["warmup"]
    train = split["train"]
    oos = split["oos"]
    train_view_start = int(warmup["start_sec"])
    oos_start = int(oos["start_sec"])
    history_end = int(oos["end_sec"])
    if int(train["end_sec"]) != oos_start:
        raise ValueError("train/OOS split is not contiguous")
    file_index = _file_index(collect_manifest)
    train_root = resolved_output / "train"
    oos_root = resolved_output / "oos-sealed"
    per_asset: list[dict[str, Any]] = []
    normalized_universe: list[dict[str, Any]] = []
    train_files: list[dict[str, Any]] = []
    oos_files: list[dict[str, Any]] = []
    accepted_asset_ids: set[str] = set()
    parse_error_samples: list[str] = []
    planned_delisted = 0
    resolved_delisted = 0
    planned_assets = list(frozen_history["universe"]["eligible"])
    try:
        for index, asset in enumerate(planned_assets, 1):
            if time.monotonic() >= deadline:
                raise TimeoutError("membership-v3 history quality runtime exhausted")
            symbol = str(asset["symbol"])
            canonical_id = str(asset["canonical_asset_id"])
            end_mode = str(asset["lifecycle_end_resolution"])
            is_delisted = end_mode in {"contract_metadata", "archive_observed_pending"}
            if is_delisted:
                planned_delisted += 1
            reasons: list[str] = []
            candle_paths, candle_path_reasons, candle_missing = _validated_paths_for_asset(
                asset=asset,
                archive_type="candlesticks_1h",
                frozen_history=frozen_history,
                collect_manifest=collect_manifest,
                collect_root=collect_root,
                file_index=file_index,
            )
            funding_paths, funding_path_reasons, funding_missing = _validated_paths_for_asset(
                asset=asset,
                archive_type="funding_applies",
                frozen_history=frozen_history,
                collect_manifest=collect_manifest,
                collect_root=collect_root,
                file_index=file_index,
            )
            reasons.extend(candle_path_reasons)
            reasons.extend(funding_path_reasons)
            try:
                candles, candle_metrics, candle_reasons = normalize_candlestick_archives_v3(
                    candle_paths,
                    contract_multiplier=float(asset["contract_multiplier"]),
                    acquisition_start_sec=int(asset["acquisition_start_sec"]),
                    acquisition_end_sec=int(asset["acquisition_end_sec"]),
                    lifecycle_end_resolution=end_mode,
                    resolved_lifecycle_end_sec=asset.get("resolved_lifecycle_end_sec"),
                    minimum_coverage=float(gates["minimum_series_coverage"]),
                    deadline_monotonic=deadline,
                )
                reasons.extend(candle_reasons)
            except Exception as exc:  # asset-level quality evidence
                candles = []
                candle_metrics = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "lifecycle_end_resolution": end_mode,
                    "resolved_lifecycle_end_sec": asset.get("resolved_lifecycle_end_sec"),
                    "quality_window_end_sec": None,
                }
                reasons.append("candlestick_normalization_failed")
            resolved_mode = str(candle_metrics.get("lifecycle_end_resolution") or end_mode)
            resolved_end = candle_metrics.get("resolved_lifecycle_end_sec")
            quality_end = candle_metrics.get("quality_window_end_sec")
            if is_delisted and resolved_mode in {"contract_metadata", "archive_observed_end"}:
                resolved_delisted += 1
            try:
                if quality_end is None:
                    raise ValueError("funding range unavailable until lifecycle end is resolved")
                funding, funding_metrics, funding_reasons = normalize_funding_archives_v3(
                    funding_paths,
                    start_sec=int(asset["acquisition_start_sec"]),
                    end_sec=int(quality_end),
                    minimum_coverage=float(gates["minimum_series_coverage"]),
                    minimum_interval_confidence=float(
                        gates["minimum_funding_interval_confidence"]
                    ),
                    deadline_monotonic=deadline,
                )
                reasons.extend(funding_reasons)
            except Exception as exc:  # asset-level quality evidence
                funding = []
                funding_metrics = {"error": f"{type(exc).__name__}: {exc}"}
                reasons.append("funding_normalization_failed")
            reasons = sorted(set(reasons))
            accepted = not reasons
            if accepted:
                train_candles, oos_candles = partition_rows_by_embargo(
                    candles,
                    train_view_start_sec=train_view_start,
                    oos_start_sec=oos_start,
                    history_end_sec=history_end,
                )
                train_funding, oos_funding = partition_rows_by_embargo(
                    funding,
                    train_view_start_sec=train_view_start,
                    oos_start_sec=oos_start,
                    history_end_sec=history_end,
                )
                train_hashes = _write_normalized_asset(
                    train_root,
                    symbol=symbol,
                    candles=train_candles,
                    funding=train_funding,
                )
                oos_hashes = _write_normalized_asset(
                    oos_root,
                    symbol=symbol,
                    candles=oos_candles,
                    funding=oos_funding,
                )
                quote_values = [
                    float(row["volume_quote"])
                    for row in train_candles
                    if float(row.get("volume_quote") or 0.0) > 0
                ]
                listed_to = asset.get("listed_to_ts")
                if listed_to is None and resolved_mode == "archive_observed_end":
                    listed_to = int(resolved_end)
                normalized_universe.append(
                    {
                        "exchange": "gateio",
                        "symbol": symbol,
                        "base": str(asset["base"]),
                        "quote": "USDT",
                        "canonical_asset_id": canonical_id,
                        "coin_id": str(asset.get("coin_id") or ""),
                        "non_binance_baseline": True,
                        "non_binance_evidence": str(asset["non_binance_evidence"]),
                        "volume_24h_quote": (
                            statistics.median(quote_values) if quote_values else 0.0
                        ),
                        "volume_source": "historical_train_daily_median_quote_volume",
                        "listed_from_ts": int(asset["listed_from_ts"]),
                        "listed_to_ts": listed_to,
                        "status": (
                            "active" if resolved_mode == "open_at_frozen_snapshot" else "delisted"
                        ),
                        "is_delisted": resolved_mode != "open_at_frozen_snapshot",
                        "survivorship_status": str(asset["lifecycle_status"]),
                        "lifecycle_end_resolution": resolved_mode,
                        "resolved_lifecycle_end_sec": resolved_end,
                        "funding_interval_sec": funding_metrics["funding_interval_sec"],
                        "contract_multiplier": float(asset["contract_multiplier"]),
                    }
                )
                train_files.append({"symbol": symbol, **train_hashes})
                oos_files.append({"symbol": symbol, **oos_hashes})
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
                    "lifecycle_end_resolution": resolved_mode,
                    "resolved_lifecycle_end_sec": resolved_end,
                    "missing_archive_files": {
                        "candlesticks_1h": candle_missing,
                        "funding_applies": funding_missing,
                    },
                    "candlesticks": candle_metrics,
                    "funding": funding_metrics,
                }
            )
            print(
                "[membership-v3-history-quality] "
                f"{index}/{len(planned_assets)} symbol={symbol} accepted={accepted} "
                f"candle_coverage={float(candle_metrics.get('hourly_coverage') or 0.0):.4f} "
                f"funding_coverage={float(funding_metrics.get('settlement_coverage') or 0.0):.4f} "
                f"reasons={','.join(reasons) if reasons else '-'}",
                flush=True,
            )
    except Exception as exc:
        report: dict[str, Any] = {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": _utc_now(),
            "run_id": quality_plan["run_id"],
            "plan_path": str(resolved_plan),
            "plan_hash": str(expected_plan_hash),
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
            "next_allowed_command": "fast-edge-membership-v3-history-quality",
        }
        report["artifact_hash"] = _artifact_hash(report)
        _atomic_write_json(resolved_report, report)
        return report

    normalized_universe.sort(key=lambda row: (row["canonical_asset_id"], row["symbol"]))
    train_universe = _train_universe_view(normalized_universe, oos_start_sec=oos_start)
    train_files.sort(key=lambda row: row["symbol"])
    oos_files.sort(key=lambda row: row["symbol"])
    accepted_count = len(accepted_asset_ids)
    delisted_end_coverage = (
        resolved_delisted / planned_delisted if planned_delisted else 1.0
    )
    rejection_reasons: list[str] = []
    if accepted_count < int(gates["minimum_canonical_assets"]):
        rejection_reasons.append("fewer_than_minimum_quality_accepted_canonical_assets")
    if delisted_end_coverage < float(gates["minimum_delisted_end_coverage"]):
        rejection_reasons.append("delisted_end_coverage_below_0_90")
    quality_accepted = not rejection_reasons
    train_manifest = _build_split_manifest(
        run_id=str(quality_plan["run_id"]),
        stage="train_view",
        start_sec=train_view_start,
        end_sec=oos_start,
        universe=train_universe,
        files=train_files,
        quality_plan_hash=str(expected_plan_hash),
        history_plan_hash=str(quality_plan["history_input"]["plan_hash"]),
        collect_artifact_hash=str(quality_plan["history_input"]["collect_artifact_hash"]),
    )
    oos_manifest = _build_split_manifest(
        run_id=str(quality_plan["run_id"]),
        stage="sealed_oos",
        start_sec=oos_start,
        end_sec=history_end,
        universe=normalized_universe,
        files=oos_files,
        quality_plan_hash=str(expected_plan_hash),
        history_plan_hash=str(quality_plan["history_input"]["plan_hash"]),
        collect_artifact_hash=str(quality_plan["history_input"]["collect_artifact_hash"]),
    )
    train_manifest_path = train_root / "manifest.json"
    oos_manifest_path = oos_root / "manifest.json"
    _atomic_write_json(train_manifest_path, train_manifest)
    _atomic_write_json(oos_manifest_path, oos_manifest)
    normalized_manifest: dict[str, Any] = {
        "schema": NORMALIZED_MANIFEST_SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": quality_plan["run_id"],
        "params": {
            "start_sec": int(frozen_history["history_window"]["start_sec"]),
            "end_sec": int(frozen_history["history_window"]["end_sec"]),
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
        "split_contract": quality_plan["split_contract"],
        "delisted_end_coverage": delisted_end_coverage,
        "split_manifests": {
            "train": {
                "stage": "train_view",
                "path": str(train_manifest_path),
                "file_sha256": history_plan.sha256_file(train_manifest_path),
                "artifact_hash": train_manifest["artifact_hash"],
            },
            "oos": {
                "stage": "sealed_oos",
                "path": str(oos_manifest_path),
                "file_sha256": history_plan.sha256_file(oos_manifest_path),
                "artifact_hash": oos_manifest["artifact_hash"],
            },
        },
        "input_provenance": {
            "quality_plan_path": str(resolved_plan),
            "quality_plan_sha256": history_plan.sha256_file(resolved_plan),
            "quality_plan_hash": str(expected_plan_hash),
            "history_plan_hash": str(quality_plan["history_input"]["plan_hash"]),
            "collect_artifact_hash": str(quality_plan["history_input"]["collect_artifact_hash"]),
        },
    }
    normalized_manifest["artifact_hash"] = _normalized_manifest_hash(normalized_manifest)
    _atomic_write_json(resolved_output / "manifest.json", normalized_manifest)
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "run_id": quality_plan["run_id"],
        "plan_path": str(resolved_plan),
        "plan_hash": str(expected_plan_hash),
        "history_plan_hash": str(quality_plan["history_input"]["plan_hash"]),
        "collect_artifact_hash": str(quality_plan["history_input"]["collect_artifact_hash"]),
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
        "minimum_canonical_assets": int(gates["minimum_canonical_assets"]),
        "minimum_series_coverage": float(gates["minimum_series_coverage"]),
        "minimum_delisted_end_coverage": float(gates["minimum_delisted_end_coverage"]),
        "planned_assets": len(planned_assets),
        "accepted_assets": accepted_count,
        "rejected_assets": len(per_asset) - accepted_count,
        "planned_delisted_assets": planned_delisted,
        "resolved_delisted_assets": resolved_delisted,
        "delisted_end_coverage": delisted_end_coverage,
        "rejection_reasons": rejection_reasons,
        "per_asset": sorted(per_asset, key=lambda row: (row["canonical_asset_id"], row["symbol"])),
        "parse_error_samples": parse_error_samples,
        "data_access_audit": {
            "archive_payload_read_for_normalization": True,
            "prices_read_for_normalization": True,
            "returns_computed": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_evaluated": False,
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
            "create_hash_bound_gate_membership_momentum_v2_train_planonly"
            if quality_accepted
            else "none_membership_v3_history_branch_closed"
        ),
        "limitations": [
            "Gate-only historical evidence does not establish MEXC portability.",
            "The frozen registry proves current Binance exclusion only, not historical exclusion.",
            "Historical OHLCV and funding do not prove executable fills or capacity.",
        ],
    }
    report["artifact_hash"] = _artifact_hash(report)
    _atomic_write_json(resolved_report, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate membership-v3 history quality PlanOnly/evaluator"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--history-plan", required=True)
    plan_parser.add_argument("--expected-history-plan-hash", required=True)
    plan_parser.add_argument("--collect-manifest", required=True)
    plan_parser.add_argument("--expected-collect-artifact-hash", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--expected-plan-hash", required=True)
    evaluate_parser.add_argument("--output-root", required=True)
    evaluate_parser.add_argument("--report", required=True)
    evaluate_parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    args = parser.parse_args()
    if args.command == "plan":
        result = build_quality_plan(
            history_plan_path=args.history_plan,
            expected_history_plan_hash=args.expected_history_plan_hash,
            collect_manifest_path=args.collect_manifest,
            expected_collect_artifact_hash=args.expected_collect_artifact_hash,
            output_path=args.output,
            run_id=args.run_id,
            max_runtime_sec=args.max_runtime_sec,
        )
    else:
        result = evaluate_history_quality(
            plan_path=args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_root=args.output_root,
            report_path=args.report,
            max_runtime_sec=args.max_runtime_sec,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if result.get("final", True) is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
