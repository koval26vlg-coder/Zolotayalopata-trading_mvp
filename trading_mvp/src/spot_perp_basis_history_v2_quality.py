from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from gate_historical_archive import (
    aggregate_gate_archive_mark_prices,
    parse_gate_archive_candlestick,
    parse_gate_archive_funding_apply,
    parse_gate_archive_mark_price,
)
from historical_basis_v2_preflight import audit_funding_events
from spot_perp_basis_history_v2 import (
    MINIMUM_ASSETS,
    PLAN_SCHEMA,
    sha256_file,
    sha256_json,
    validate_gate_spot_perp_plan,
)
from spot_perp_basis_history_v2_collector import COLLECT_SCHEMA


QUALITY_SCHEMA = "trading_mvp_gate_spot_perp_history_quality_v2"
HOUR_SEC = 3_600
DAY_SEC = 86_400


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _valid_ohlc(row: Mapping[str, Any]) -> bool:
    values = [_as_float(row.get(name)) for name in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in values):
        return False
    open_price, high, low, close = (float(value) for value in values)
    return high >= max(open_price, close, low) and low <= min(open_price, close, high)


def parse_rest_candles(payload: Any, *, market_type: str) -> list[dict[str, Any]]:
    market = market_type.strip().lower()
    if market not in {"spot", "perp", "mark"}:
        raise ValueError(f"unsupported market_type: {market_type}")
    if not isinstance(payload, list):
        raise ValueError("Gate REST candle payload must be a list")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, Mapping):
            ts = _as_float(item.get("t"))
            row = {
                "ts": int(ts) if ts is not None and ts.is_integer() else ts,
                "open": _as_float(item.get("o")),
                "high": _as_float(item.get("h")),
                "low": _as_float(item.get("l")),
                "close": _as_float(item.get("c")),
            }
            if market == "spot":
                row["volume_base"] = _as_float(item.get("v")) or 0.0
                row["volume_quote"] = _as_float(item.get("sum")) or 0.0
            elif market == "perp":
                row["volume_raw"] = _as_float(item.get("v")) or 0.0
                row["volume_quote"] = _as_float(item.get("sum")) or 0.0
        elif isinstance(item, (list, tuple)) and len(item) >= 6:
            ts = _as_float(item[0])
            row = {
                "ts": int(ts) if ts is not None and ts.is_integer() else ts,
                "open": _as_float(item[5]),
                "high": _as_float(item[3]),
                "low": _as_float(item[4]),
                "close": _as_float(item[2]),
            }
            if market == "spot":
                row["volume_quote"] = _as_float(item[1]) or 0.0
                row["volume_base"] = _as_float(item[6]) if len(item) > 6 else 0.0
            elif market == "perp":
                row["volume_raw"] = _as_float(item[1]) or 0.0
                row["volume_quote"] = _as_float(item[6]) if len(item) > 6 else 0.0
        else:
            continue
        if row.get("ts") is None or not float(row["ts"]).is_integer() or not _valid_ohlc(row):
            continue
        row["ts"] = int(row["ts"])
        rows.append(row)
    return rows


def parse_rest_funding(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Gate REST funding payload must be a list")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        ts = _as_float(item.get("t") if item.get("t") is not None else item.get("timestamp"))
        rate = _as_float(item.get("r") if item.get("r") is not None else item.get("funding_rate"))
        if ts is None or rate is None:
            continue
        rows.append({"ts": int(ts) if ts.is_integer() else ts, "funding_rate": rate})
    return rows


def merge_rows_strict(pages: Iterable[Iterable[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for page in pages:
        for raw in page:
            ts_value = _as_float(raw.get("ts"))
            if ts_value is None or not ts_value.is_integer():
                raise ValueError(f"invalid timestamp: {raw.get('ts')!r}")
            ts = int(ts_value)
            row = dict(raw)
            row["ts"] = ts
            prior = merged.get(ts)
            if prior is not None and prior != row:
                raise ValueError(f"conflicting duplicate timestamp: {ts}")
            merged[ts] = row
    return [merged[ts] for ts in sorted(merged)]


def verify_task_cache(task: Mapping[str, Any]) -> Path:
    path = Path(str(task.get("cache_path") or ""))
    expected_sha256 = str(task.get("data_sha256") or "").strip().lower()
    if not path.is_file():
        raise FileNotFoundError(f"task cache is missing: {path}")
    if len(expected_sha256) != 64:
        raise ValueError(f"task data_sha256 is missing or invalid: {task.get('task_id')}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"task cache hash mismatch: task_id={task.get('task_id')} "
            f"expected={expected_sha256} actual={actual_sha256}"
        )
    return path


def _series_coverage(rows: Sequence[Mapping[str, Any]], *, start_sec: int, end_sec: int) -> dict[str, Any]:
    expected = max(0, (int(end_sec) - int(start_sec)) // HOUR_SEC)
    in_window = [row for row in rows if start_sec <= int(row["ts"]) < end_sec]
    timestamps = [int(row["ts"]) for row in in_window]
    unique = len(set(timestamps))
    duplicate_count = len(timestamps) - unique
    off_grid_count = sum(ts % HOUR_SEC != 0 for ts in timestamps)
    missing = max(0, expected - unique)
    gaps = [right - left for left, right in zip(sorted(set(timestamps)), sorted(set(timestamps))[1:]) if right - left > HOUR_SEC]
    coverage = unique / expected if expected else 0.0
    exact_boundary = bool(timestamps) and min(timestamps) == start_sec and max(timestamps) == end_sec - HOUR_SEC
    return {
        "rows": len(in_window),
        "unique_rows": unique,
        "expected_rows": expected,
        "coverage": coverage,
        "duplicate_count": duplicate_count,
        "off_grid_count": off_grid_count,
        "missing_rows": missing,
        "gap_count": len(gaps),
        "maximum_gap_sec": max(gaps, default=HOUR_SEC),
        "exact_boundary": exact_boundary,
        "accepted": coverage >= 0.98 and duplicate_count == 0 and off_grid_count == 0 and exact_boundary,
    }


def _quote_volume(row: Mapping[str, Any], *, market: str, contract_multiplier: float) -> float:
    explicit = _as_float(row.get("volume_quote"))
    if explicit is not None and explicit > 0:
        return explicit
    close = _as_float(row.get("close")) or 0.0
    if market == "spot":
        return max(0.0, (_as_float(row.get("volume_base")) or 0.0) * close)
    return max(0.0, (_as_float(row.get("volume_raw")) or 0.0) * contract_multiplier * close)


def _median_rolling_quote_volume(
    rows: Sequence[Mapping[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    market: str,
    contract_multiplier: float,
    window_days: int,
) -> float:
    if window_days < 1:
        raise ValueError("liquidity window_days must be positive")
    daily: dict[int, float] = defaultdict(float)
    first_day = int(start_sec) // DAY_SEC * DAY_SEC
    last_day = (int(end_sec) - 1) // DAY_SEC * DAY_SEC
    for row in rows:
        ts = int(row["ts"])
        if start_sec <= ts < end_sec:
            daily[ts // DAY_SEC * DAY_SEC] += _quote_volume(
                row,
                market=market,
                contract_multiplier=contract_multiplier,
            )
    days = list(range(first_day, last_day + DAY_SEC, DAY_SEC))
    values = [daily.get(day, 0.0) for day in days]
    if len(values) < window_days:
        return 0.0
    rolling = [sum(values[index - window_days + 1 : index + 1]) for index in range(window_days - 1, len(values))]
    return float(statistics.median(rolling)) if rolling else 0.0


def assess_asset_quality(
    *,
    spot_rows: Sequence[Mapping[str, Any]],
    perp_rows: Sequence[Mapping[str, Any]],
    mark_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    start_sec: int,
    end_sec: int,
    liquidity_start_sec: int,
    liquidity_end_sec: int,
    contract_multiplier: float,
    minimum_median_seven_day_quote_volume: float = 1_000_000.0,
    liquidity_window_days: int = 7,
) -> dict[str, Any]:
    if contract_multiplier <= 0:
        raise ValueError("contract_multiplier must be positive")
    series = {
        "spot_trade": _series_coverage(spot_rows, start_sec=start_sec, end_sec=end_sec),
        "perp_trade": _series_coverage(perp_rows, start_sec=start_sec, end_sec=end_sec),
        "perp_mark": _series_coverage(mark_rows, start_sec=start_sec, end_sec=end_sec),
    }
    timestamp_sets = [
        {int(row["ts"]) for row in rows if start_sec <= int(row["ts"]) < end_sec}
        for rows in (spot_rows, perp_rows, mark_rows)
    ]
    aligned = set.intersection(*timestamp_sets) if timestamp_sets else set()
    expected = (end_sec - start_sec) // HOUR_SEC
    aligned_coverage = len(aligned) / expected if expected else 0.0
    funding = audit_funding_events(
        list(funding_rows),
        start_sec=start_sec,
        end_sec=end_sec,
        minimum_coverage=0.98,
    )
    spot_liquidity = _median_rolling_quote_volume(
        spot_rows,
        start_sec=liquidity_start_sec,
        end_sec=liquidity_end_sec,
        market="spot",
        contract_multiplier=contract_multiplier,
        window_days=liquidity_window_days,
    )
    perp_liquidity = _median_rolling_quote_volume(
        perp_rows,
        start_sec=liquidity_start_sec,
        end_sec=liquidity_end_sec,
        market="perp",
        contract_multiplier=contract_multiplier,
        window_days=liquidity_window_days,
    )
    minimum_liquidity = min(spot_liquidity, perp_liquidity)
    reasons: list[str] = []
    for name, metrics in series.items():
        if not metrics["accepted"]:
            reasons.append(f"{name}_coverage_or_boundary")
    if aligned_coverage < 0.95:
        reasons.append("aligned_coverage")
    if not funding["accepted"]:
        reasons.append("funding_coverage")
    if minimum_liquidity < minimum_median_seven_day_quote_volume:
        reasons.append("train_liquidity")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "series": series,
        "aligned_rows": len(aligned),
        "aligned_coverage": aligned_coverage,
        "funding": funding,
        "spot_median_rolling_quote_volume": spot_liquidity,
        "perp_median_rolling_quote_volume": perp_liquidity,
        "minimum_median_rolling_quote_volume": minimum_liquidity,
        "minimum_required_quote_volume": minimum_median_seven_day_quote_volume,
        "liquidity_window_days": liquidity_window_days,
        "liquidity_window": {"start_sec": liquidity_start_sec, "end_sec": liquidity_end_sec, "train_only": True},
    }


def _read_archive_task(task: Mapping[str, Any], *, start_sec: int, end_sec: int) -> list[dict[str, Any]]:
    path = verify_task_cache(task)
    series = str(task["series"])
    if series in {"spot_trade", "perp_trade"}:
        rows: list[dict[str, Any]] = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                parsed = parse_gate_archive_candlestick(line)
                row: dict[str, Any] = {
                    "ts": int(parsed["ts"]),
                    "open": parsed["open"],
                    "high": parsed["high"],
                    "low": parsed["low"],
                    "close": parsed["close"],
                }
                if series == "spot_trade":
                    row["volume_base"] = parsed["volume_contracts"]
                    row["volume_quote"] = parsed["volume_contracts"] * parsed["close"]
                else:
                    row["volume_raw"] = parsed["volume_contracts"]
                    row["volume_quote"] = 0.0
                rows.append(row)
        return rows
    if series == "perp_mark":
        raw: list[dict[str, float]] = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    raw.append(parse_gate_archive_mark_price(line))
        raw.sort(key=lambda row: row["ts"])
        return aggregate_gate_archive_mark_prices(
            raw,
            start_sec=start_sec,
            end_sec=end_sec,
            interval_sec=HOUR_SEC,
        )["mark"]
    if series == "funding":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return [parse_gate_archive_funding_apply(line) for line in handle if line.strip()]
    raise ValueError(f"unsupported archive series: {series}")


def _read_rest_task(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = json.loads(verify_task_cache(task).read_text(encoding="utf-8"))
    series = str(task["series"])
    if series == "spot_trade":
        return parse_rest_candles(payload, market_type="spot")
    if series == "perp_trade":
        return parse_rest_candles(payload, market_type="perp")
    if series == "perp_mark":
        return parse_rest_candles(payload, market_type="mark")
    if series == "funding":
        return parse_rest_funding(payload)
    raise ValueError(f"unsupported REST series: {series}")


def _contract_multipliers(pit_state: Mapping[str, Any]) -> dict[str, float]:
    if pit_state.get("schema") != "pit_universe_state_v1":
        raise ValueError("expected pit_universe_state_v1")
    out: dict[str, float] = {}
    for item in (pit_state.get("symbols") or {}).values():
        row = item.get("row") if isinstance(item, Mapping) else None
        if not isinstance(row, Mapping) or str(row.get("exchange") or "").lower() != "gateio":
            continue
        base = str(row.get("base") or "").upper()
        multiplier = _as_float(row.get("contract_multiplier"))
        if base and multiplier is not None and multiplier > 0:
            out[base] = multiplier
    return out


def _write_jsonl_atomic(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temp, path)


def normalize_and_audit(
    *,
    plan_path: str | Path,
    expected_plan_hash: str,
    collector_manifest_path: str | Path,
    pit_state_path: str | Path,
    output_path: str | Path,
    max_runtime_sec: int = 1_800,
) -> dict[str, Any]:
    if not 0 < int(max_runtime_sec) <= 1_800:
        raise ValueError("quality MaxRuntimeSec must be in [1, 1800]")
    started = time.monotonic()
    plan_target = Path(plan_path).expanduser().resolve()
    collect_target = Path(collector_manifest_path).expanduser().resolve()
    pit_target = Path(pit_state_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"quality output already exists: {output}")
    plan = json.loads(plan_target.read_text(encoding="utf-8"))
    validate_gate_spot_perp_plan(plan, expected_plan_hash=expected_plan_hash)
    collector = json.loads(collect_target.read_text(encoding="utf-8"))
    if (
        collector.get("schema") != COLLECT_SCHEMA
        or collector.get("final") is not True
        or collector.get("status") != "READY_FOR_POSTPROCESS"
        or collector.get("plan_hash") != expected_plan_hash
    ):
        raise ValueError("collector manifest is not final and hash-bound")
    pit_state = json.loads(pit_target.read_text(encoding="utf-8"))
    expected_pit_hash = str((plan.get("input_hashes") or {}).get("pit_state_sha256") or "")
    if not expected_pit_hash or sha256_file(pit_target) != expected_pit_hash:
        raise ValueError("PIT state hash mismatch")
    multipliers = _contract_multipliers(pit_state)
    tasks_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in collector.get("task_results") or []:
        if task.get("status") in {"downloaded", "cache_hit"}:
            tasks_by_base[str(task.get("base") or "").upper()].append(task)
    sample = plan["sample_plan"]
    start_sec = int(sample["window_start_sec"])
    end_sec = int(sample["window_end_sec"])
    liquidity_start = start_sec + int(sample["warmup_days"]) * DAY_SEC
    liquidity_end = liquidity_start + int(sample["train_days"]) * DAY_SEC
    asset_reports: list[dict[str, Any]] = []
    output.mkdir(parents=True, exist_ok=False)
    selected_assets = list(plan["universe"]["selected_assets"])
    for asset_index, asset in enumerate(selected_assets, start=1):
        if time.monotonic() - started >= int(max_runtime_sec):
            break
        base = str(asset["base"]).upper()
        print(
            f"[quality] asset={asset_index}/{len(selected_assets)} base={base} "
            f"elapsed={time.monotonic() - started:.1f}s",
            flush=True,
        )
        pages: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
        errors: list[str] = []
        for task in tasks_by_base.get(base, []):
            try:
                rows = (
                    _read_archive_task(task, start_sec=start_sec, end_sec=end_sec)
                    if task.get("source") == "gate_archive"
                    else _read_rest_task(task)
                )
                pages[str(task["series"])].append(rows)
            except Exception as exc:  # noqa: BLE001 - per-asset quality must preserve parser failures.
                errors.append(f"{task.get('series')}:{task.get('cache_path')}:{type(exc).__name__}:{exc}")
        try:
            spot = merge_rows_strict(pages.get("spot_trade") or [])
            perp = merge_rows_strict(pages.get("perp_trade") or [])
            mark = merge_rows_strict(pages.get("perp_mark") or [])
            funding = merge_rows_strict(pages.get("funding") or [])
            spot = [row for row in spot if start_sec <= int(row["ts"]) < end_sec]
            perp = [row for row in perp if start_sec <= int(row["ts"]) < end_sec]
            mark = [row for row in mark if start_sec <= int(row["ts"]) < end_sec]
            funding = [row for row in funding if start_sec <= float(row["ts"]) < end_sec]
            multiplier = multipliers.get(base)
            if multiplier is None:
                raise ValueError("contract_multiplier_missing")
            for row in perp:
                if (_as_float(row.get("volume_quote")) or 0.0) <= 0:
                    row["volume_quote"] = _quote_volume(row, market="perp", contract_multiplier=multiplier)
            quality = assess_asset_quality(
                spot_rows=spot,
                perp_rows=perp,
                mark_rows=mark,
                funding_rows=funding,
                start_sec=start_sec,
                end_sec=end_sec,
                liquidity_start_sec=liquidity_start,
                liquidity_end_sec=liquidity_end,
                contract_multiplier=multiplier,
            )
            if errors:
                quality["accepted"] = False
                quality["reasons"] = list(quality["reasons"]) + ["parser_error"]
            aligned_ts = sorted(
                {int(row["ts"]) for row in spot}
                & {int(row["ts"]) for row in perp}
                & {int(row["ts"]) for row in mark}
            )
            spot_by_ts = {int(row["ts"]): row for row in spot}
            perp_by_ts = {int(row["ts"]): row for row in perp}
            mark_by_ts = {int(row["ts"]): row for row in mark}
            normalized_rows = [
                {
                    "ts": ts,
                    "canonical_asset_id": asset["canonical_asset_id"],
                    "base": base,
                    "spot": spot_by_ts[ts],
                    "perp": perp_by_ts[ts],
                    "mark": mark_by_ts[ts],
                }
                for ts in aligned_ts
            ]
            normalized_path = output / "assets" / f"{base}.jsonl"
            funding_path = output / "funding" / f"{base}.jsonl"
            _write_jsonl_atomic(normalized_path, normalized_rows)
            _write_jsonl_atomic(funding_path, funding)
            asset_reports.append(
                {
                    "canonical_asset_id": asset["canonical_asset_id"],
                    "base": base,
                    "accepted": quality["accepted"],
                    "quality": quality,
                    "parser_errors": errors,
                    "normalized_path": str(normalized_path),
                    "normalized_sha256": sha256_file(normalized_path),
                    "funding_path": str(funding_path),
                    "funding_sha256": sha256_file(funding_path),
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve a deterministic per-asset rejection.
            asset_reports.append(
                {
                    "canonical_asset_id": asset["canonical_asset_id"],
                    "base": base,
                    "accepted": False,
                    "quality": None,
                    "parser_errors": errors + [f"{type(exc).__name__}:{exc}"],
                }
            )
    timed_out = len(asset_reports) < len(plan["universe"]["selected_assets"])
    accepted = [row for row in asset_reports if row.get("accepted") is True]
    if timed_out:
        decision = "STOPPED_INCOMPLETE"
    elif len(accepted) >= MINIMUM_ASSETS:
        decision = "GATE_SPOT_PERP_HISTORY_READY_FOR_TRAIN_FEASIBILITY"
    else:
        decision = "INSUFFICIENT_EXECUTABLE_UNIVERSE"
    report: dict[str, Any] = {
        "schema": QUALITY_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final": not timed_out,
        "decision": decision,
        "plan_path": str(plan_target),
        "plan_hash": expected_plan_hash,
        "collector_manifest_path": str(collect_target),
        "collector_manifest_sha256": sha256_file(collect_target),
        "pit_state_path": str(pit_target),
        "pit_state_sha256": sha256_file(pit_target),
        "asset_reports": asset_reports,
        "accepted_assets": [row["base"] for row in accepted],
        "accepted_asset_count": len(accepted),
        "minimum_assets": MINIMUM_ASSETS,
        "runtime_sec": round(time.monotonic() - started, 6),
        "max_runtime_sec": int(max_runtime_sec),
        "returns_read": False,
        "signals_read": False,
        "pnl_read": False,
        "oos_read": False,
        "grid_search": False,
        "live_orders": False,
        "next_allowed_command": (
            "fast-edge-gate-spot-perp-train-feasibility"
            if decision == "GATE_SPOT_PERP_HISTORY_READY_FOR_TRAIN_FEASIBILITY"
            else "none_quality_incomplete_or_insufficient"
        ),
    }
    report["artifact_hash"] = sha256_json(
        {key: value for key, value in report.items() if key not in {"generated_at_utc", "runtime_sec", "artifact_hash"}}
    )
    report_path = output / "quality-report.json"
    temp = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    report["output_path"] = str(report_path)
    report["output_file_sha256"] = sha256_file(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate spot/perp history normalizer and data-quality gate")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--collector-manifest", required=True)
    parser.add_argument("--pit-state", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=1_800)
    args = parser.parse_args()
    report = normalize_and_audit(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        collector_manifest_path=args.collector_manifest,
        pit_state_path=args.pit_state,
        output_path=args.out,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps({key: report[key] for key in ("decision", "final", "accepted_asset_count", "runtime_sec", "output_path")}, ensure_ascii=False, indent=2))
    return 0 if report.get("final") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
