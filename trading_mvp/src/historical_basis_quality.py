from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from costs import validate_runtime_sec
from historical_basis_code_snapshot import require_plan_code_snapshot, validate_basis_code_snapshot_reference
from historical_basis_edge import sha256_file, sha256_json, validate_historical_basis_plan


SCHEMA = "trading_mvp_historical_basis_quality_v1"
CACHE_SCHEMA = "trading_mvp_historical_basis_cache_v1"
CANDLE_SEC = 300
DAY_SEC = 86_400
REQUIRED_CANDLE_KEYS = tuple(
    f"{venue}:{series}"
    for venue in ("mexc", "gateio")
    for series in ("trade", "mark", "index")
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path}")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _timestamps(rows: Iterable[dict[str, Any]]) -> list[int]:
    result: list[int] = []
    for row in rows:
        try:
            result.append(int(float(row["ts"])))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def audit_candle_series(
    rows: list[dict[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    closed_before_sec: int,
    minimum_coverage: float = 0.98,
) -> dict[str, Any]:
    timestamps = _timestamps(rows)
    unique = sorted(set(timestamps))
    expected = (int(end_sec) - int(start_sec)) // CANDLE_SEC + 1
    in_range = [ts for ts in unique if start_sec <= ts <= end_sec]
    duplicate_count = len(timestamps) - len(unique)
    open_count = sum(ts + CANDLE_SEC > closed_before_sec for ts in unique)
    off_grid_count = sum((ts - start_sec) % CANDLE_SEC != 0 for ts in in_range)
    out_of_range_count = len(unique) - len(in_range)
    coverage = len(in_range) / expected if expected > 0 else 0.0
    gaps = [right - left for left, right in zip(in_range, in_range[1:]) if right - left > CANDLE_SEC]
    accepted = (
        coverage >= float(minimum_coverage)
        and duplicate_count == 0
        and open_count == 0
        and off_grid_count == 0
        and out_of_range_count == 0
    )
    return {
        "rows": len(rows),
        "unique_rows": len(unique),
        "expected_rows": expected,
        "coverage": coverage,
        "duplicate_count": duplicate_count,
        "open_bar_count": open_count,
        "off_grid_count": off_grid_count,
        "out_of_range_count": out_of_range_count,
        "gap_count": len(gaps),
        "maximum_gap_sec": max(gaps, default=0),
        "accepted": accepted,
    }


def _audit_funding(
    rows: list[dict[str, Any]],
    *,
    start_sec: int,
    end_sec: int,
    minimum_coverage: float,
) -> dict[str, Any]:
    timestamps = sorted(ts for ts in _timestamps(rows) if start_sec <= ts <= end_sec)
    duplicate_count = len(timestamps) - len(set(timestamps))
    unique = sorted(set(timestamps))
    intervals = [right - left for left, right in zip(unique, unique[1:]) if right > left]
    interval = int(statistics.median(intervals)) if intervals else None
    if interval and interval > 0:
        expected = (end_sec - start_sec) // interval + 1
        coverage = len(unique) / expected if expected else 0.0
    else:
        expected = len(unique)
        coverage = 1.0 if unique else 0.0
    return {
        "rows": len(rows),
        "unique_rows": len(unique),
        "inferred_interval_sec": interval,
        "expected_settlements": expected,
        "coverage": coverage,
        "duplicate_count": duplicate_count,
        "accepted": duplicate_count == 0 and coverage >= float(minimum_coverage),
    }


def _row_map(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        ts = int(float(row["ts"]))
        if ts in result:
            raise ValueError(f"duplicate timestamp: {ts}")
        result[ts] = row
    return result


def align_asset_rows(
    base: str,
    series: dict[str, list[dict[str, Any]]],
    *,
    maximum_gap_sec: int,
) -> list[dict[str, Any]]:
    missing = [key for key in REQUIRED_CANDLE_KEYS if key not in series]
    if missing:
        raise ValueError(f"missing required series: {', '.join(missing)}")
    maps = {key: _row_map(series[key]) for key in REQUIRED_CANDLE_KEYS}
    aligned_ts = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    funding_maps = {
        venue: {
            int(float(row["ts"])): float(row["funding_rate"])
            for row in series.get(f"{venue}:funding", [])
        }
        for venue in ("mexc", "gateio")
    }
    result: list[dict[str, Any]] = []
    segment_id = 0
    previous: int | None = None
    for ts in aligned_ts:
        if previous is not None and ts - previous > int(maximum_gap_sec):
            segment_id += 1
        previous = ts
        mexc_trade = maps["mexc:trade"][ts]
        gate_trade = maps["gateio:trade"][ts]
        result.append(
            {
                "ts": ts,
                "base": str(base).upper(),
                "segment_id": segment_id,
                "mexc_trade_open": float(mexc_trade["open"]),
                "mexc_trade_close": float(mexc_trade["close"]),
                "mexc_mark_close": float(maps["mexc:mark"][ts]["close"]),
                "mexc_index_close": float(maps["mexc:index"][ts]["close"]),
                "mexc_volume_quote": float(mexc_trade.get("volume_quote") or 0.0),
                "gateio_trade_open": float(gate_trade["open"]),
                "gateio_trade_close": float(gate_trade["close"]),
                "gateio_mark_close": float(maps["gateio:mark"][ts]["close"]),
                "gateio_index_close": float(maps["gateio:index"][ts]["close"]),
                "gateio_volume_quote": float(gate_trade.get("volume_quote") or 0.0),
                "mexc_funding_rate": funding_maps["mexc"].get(ts),
                "gateio_funding_rate": funding_maps["gateio"].get(ts),
            }
        )
    return result


def _median_seven_day_daily_volume(rows: list[dict[str, Any]], cutoff_sec: int) -> float:
    daily: dict[int, float] = {}
    for row in rows:
        ts = int(float(row["ts"]))
        if ts >= cutoff_sec:
            continue
        day = ts // DAY_SEC
        daily[day] = daily.get(day, 0.0) + float(row.get("volume_quote") or 0.0)
    values = [daily[key] for key in sorted(daily)]
    if not values:
        return 0.0
    if len(values) < 7:
        return float(statistics.median(values))
    rolling = [statistics.fmean(values[index : index + 7]) for index in range(len(values) - 6)]
    return float(statistics.median(rolling))


def _load_cache(path: Path, expected: dict[str, Any]) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CACHE_SCHEMA:
        raise ValueError(f"unexpected cache schema: {path}")
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"cache metadata mismatch {key}: {path}")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("rows_sha256") != sha256_json(rows):
        raise ValueError(f"cache rows hash mismatch: {path}")
    return rows


def run_historical_basis_quality(
    plan: dict[str, Any],
    manifest: dict[str, Any],
    *,
    manifest_path: str | Path,
    normalized_output: str | Path,
    report_output: str | Path,
    max_runtime_sec: int = 1800,
    now_sec: int | None = None,
) -> dict[str, Any]:
    validate_runtime_sec(max_runtime_sec)
    snapshot = validate_basis_code_snapshot_reference(None, None, fallback_code_path=__file__)
    require_plan_code_snapshot(plan, snapshot)
    frozen_limit = int((plan.get("runtime") or {}).get("quality_max_runtime_sec") or 1800)
    if max_runtime_sec > frozen_limit:
        raise ValueError(f"MaxRuntimeSec exceeds frozen quality limit: {frozen_limit}")
    if not manifest.get("final") or manifest.get("status") != "READY_FOR_POSTPROCESS":
        raise ValueError("collector manifest is not final")
    if manifest.get("plan_hash") != plan.get("plan_hash"):
        raise ValueError("collector and plan hash mismatch")
    started = time.monotonic()
    deadline = started + max_runtime_sec
    start_sec = int(manifest["start_sec"])
    end_sec = int(manifest["end_sec"])
    now = int(time.time() if now_sec is None else now_sec)
    closed_before_sec = (now // CANDLE_SEC) * CANDLE_SEC
    gates = plan.get("quality_gates") or {}
    minimum_series = float(gates.get("minimum_series_coverage") or 0.98)
    minimum_aligned = float(gates.get("minimum_dual_venue_aligned_coverage") or 0.95)
    minimum_funding = float(gates.get("minimum_funding_coverage") or 0.98)
    maximum_gap = int(gates.get("maximum_gap_sec") or 900)
    minimum_volume = float(gates.get("minimum_median_quote_volume") or 1_000_000.0)
    expected_slots = (end_sec - start_sec) // CANDLE_SEC + 1
    status_index = {
        (row["venue"], row["symbol"], row["series"]): row
        for row in manifest.get("statuses") or []
    }
    all_cache_paths: list[Path] = []
    candidates_reports: list[dict[str, Any]] = []
    normalized_by_base: dict[str, list[dict[str, Any]]] = {}
    sample = plan.get("sample_plan") or {}
    liquidity_cutoff = start_sec + (
        int(sample.get("warmup_days") or 20) + int(sample.get("train_days") or 100)
    ) * DAY_SEC

    for candidate in (plan.get("universe") or {}).get("candidates") or []:
        if time.monotonic() >= deadline:
            raise TimeoutError("quality MaxRuntimeSec exceeded")
        base = str(candidate["base"]).upper()
        series: dict[str, list[dict[str, Any]]] = {}
        load_errors: list[str] = []
        for venue in ("mexc", "gateio"):
            symbol = str(candidate[f"{venue}_symbol"])
            for series_name in ("trade", "mark", "index", "funding"):
                status = status_index.get((venue, symbol, series_name))
                key = f"{venue}:{series_name}"
                if not status or status.get("status") not in {"collected", "cache_hit"}:
                    load_errors.append(f"missing:{key}")
                    continue
                path = Path(str(status.get("cache_path") or "")).expanduser().resolve()
                try:
                    series[key] = _load_cache(
                        path,
                        {
                            "plan_hash": plan["plan_hash"],
                            "venue": venue,
                            "symbol": symbol,
                            "series": series_name,
                            "start_sec": start_sec,
                            "end_sec": end_sec,
                        },
                    )
                    all_cache_paths.append(path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    load_errors.append(f"{key}:{type(exc).__name__}:{exc}")
        candle_reports = {
            key: audit_candle_series(
                series.get(key, []),
                start_sec=start_sec,
                end_sec=end_sec,
                closed_before_sec=closed_before_sec,
                minimum_coverage=minimum_series,
            )
            for key in REQUIRED_CANDLE_KEYS
        }
        funding_reports = {
            venue: _audit_funding(
                series.get(f"{venue}:funding", []),
                start_sec=start_sec,
                end_sec=end_sec,
                minimum_coverage=minimum_funding,
            )
            for venue in ("mexc", "gateio")
        }
        try:
            aligned = align_asset_rows(base, series, maximum_gap_sec=maximum_gap) if not load_errors else []
        except (KeyError, TypeError, ValueError) as exc:
            load_errors.append(f"alignment:{type(exc).__name__}:{exc}")
            aligned = []
        aligned_coverage = len(aligned) / expected_slots if expected_slots else 0.0
        venue_liquidity = {
            venue: _median_seven_day_daily_volume(series.get(f"{venue}:trade", []), liquidity_cutoff)
            for venue in ("mexc", "gateio")
        }
        worst_liquidity = min(venue_liquidity.values())
        reasons = list(load_errors)
        reasons.extend(f"series:{key}" for key, report in candle_reports.items() if not report["accepted"])
        reasons.extend(f"funding:{venue}" for venue, report in funding_reports.items() if not report["accepted"])
        if aligned_coverage < minimum_aligned:
            reasons.append("dual_venue_aligned_coverage")
        if worst_liquidity < minimum_volume:
            reasons.append("train_liquidity")
        accepted = not reasons
        if accepted:
            normalized_by_base[base] = aligned
        candidates_reports.append(
            {
                "canonical_asset_id": candidate["canonical_asset_id"],
                "base": base,
                "accepted": accepted,
                "rejection_reasons": reasons,
                "series": candle_reports,
                "funding": funding_reports,
                "aligned_rows": len(aligned),
                "aligned_coverage": aligned_coverage,
                "train_liquidity_by_venue": venue_liquidity,
                "worst_leg_train_median_7d_daily_volume_quote": worst_liquidity,
            }
        )
        print(
            f"QUALITY base={base} accepted={accepted} aligned={len(aligned)}/{expected_slots} "
            f"worst_volume={worst_liquidity:.2f} reasons={','.join(reasons) if reasons else '-'}",
            flush=True,
        )

    survivors = sorted(
        (row for row in candidates_reports if row["accepted"]),
        key=lambda row: (-row["worst_leg_train_median_7d_daily_volume_quote"], row["canonical_asset_id"]),
    )
    universe = plan.get("universe") or {}
    minimum_survivors = int(universe.get("minimum_surviving_assets") or 8)
    primary_limit = int(universe.get("primary_limit") or 12)
    reserve_limit = int(universe.get("reserve_limit") or 8)
    selected = survivors[: primary_limit + reserve_limit]
    primary = [row["base"] for row in selected[:primary_limit]]
    reserve = [row["base"] for row in selected[primary_limit : primary_limit + reserve_limit]]
    normalized_rows = [
        row
        for selected_asset in selected
        for row in normalized_by_base[selected_asset["base"]]
    ]
    normalized_rows.sort(key=lambda row: (row["ts"], row["base"]))
    normalized_path = Path(normalized_output).expanduser().resolve()
    normalized_text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in normalized_rows
    )
    _atomic_write(normalized_path, normalized_text)
    train_cutoff = start_sec + (
        int(sample.get("warmup_days") or 20) + int(sample.get("train_days") or 100)
    ) * DAY_SEC
    train_rows = [row for row in normalized_rows if int(row["ts"]) < train_cutoff]
    oos_rows = [row for row in normalized_rows if int(row["ts"]) >= train_cutoff]
    train_path = normalized_path.with_name(f"{normalized_path.stem}.train{normalized_path.suffix}")
    oos_path = normalized_path.with_name(f"{normalized_path.stem}.oos{normalized_path.suffix}")
    train_text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in train_rows
    )
    oos_text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in oos_rows
    )
    _atomic_write(train_path, train_text)
    _atomic_write(oos_path, oos_text)
    verdict = (
        "QUALITY_ACCEPTED_NOT_EVALUATED"
        if len(survivors) >= minimum_survivors
        else "INSUFFICIENT_EXECUTABLE_UNIVERSE"
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": _utc_now(),
        "status": "READY_FOR_EVALUATION" if verdict.startswith("QUALITY_ACCEPTED") else "REJECTED",
        "verdict": verdict,
        "plan_hash": plan["plan_hash"],
        "collect_run_id": manifest.get("run_id"),
        "collect_manifest_path": str(Path(manifest_path).expanduser().resolve()),
        "collect_manifest_sha256": sha256_file(manifest_path),
        "input_merkle_sha256": sha256_json(
            sorted(
                ({"path": str(path), "sha256": sha256_file(path)} for path in set(all_cache_paths)),
                key=lambda row: row["path"],
            )
        ),
        "code_provenance": snapshot,
        "normalized_output": str(normalized_path),
        "normalized_output_sha256": hashlib_sha256_text(normalized_text),
        "normalized_rows": len(normalized_rows),
        "train_output": str(train_path),
        "train_output_sha256": hashlib_sha256_text(train_text),
        "train_rows": len(train_rows),
        "oos_output": str(oos_path),
        "oos_output_sha256": hashlib_sha256_text(oos_text),
        "oos_rows": len(oos_rows),
        "surviving_asset_count": len(survivors),
        "primary_assets": primary,
        "reserve_assets": reserve,
        "candidates": candidates_reports,
        "data_access_audit": {
            "oos_returns_read": False,
            "pnl_computed": False,
            "selection_fields": ["canonical_identity", "data_quality", "train_liquidity"],
            "survivorship_bias": "current_active_contract_universe_as_of_collection",
        },
        "runtime_sec": round(time.monotonic() - started, 3),
        "next_allowed_command": (
            "fast-edge-basis-evaluate -Stage train_feasibility"
            if verdict.startswith("QUALITY_ACCEPTED")
            else "close-hypothesis-without-retune"
        ),
    }
    report["deterministic_result_hash"] = sha256_json(
        {key: value for key, value in report.items() if key not in {"generated_at_utc", "runtime_sec"}}
    )
    report_path = Path(report_output).expanduser().resolve()
    _atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def hashlib_sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical basis data-quality and normalization gate")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--normalized-output", required=True)
    parser.add_argument("--report-output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=1800)
    args = parser.parse_args()
    validate_historical_basis_plan(args.plan, args.expected_plan_hash)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = run_historical_basis_quality(
        plan,
        manifest,
        manifest_path=args.manifest,
        normalized_output=args.normalized_output,
        report_output=args.report_output,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "QUALITY_ACCEPTED_NOT_EVALUATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
