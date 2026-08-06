from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from funding_regime_persistence_v2 import (
    DAY_SEC,
    PLAN_SCHEMA,
    canonical_plan_hash,
    validate_plan,
)


FEASIBILITY_SCHEMA = "fast_first_funding_regime_persistence_train_feasibility_v2"
MAX_RUNTIME_SEC = 1_800
FUNDING_SCHEMA = "trading_mvp_historical_basis_v2_funding_events_v2"
CANDLE_SCHEMA = "trading_mvp_historical_basis_v2_normalized_candles_v2"
_SETTLEMENT_TS_PATTERN = re.compile(rb'"settlement_ts"\s*:\s*(\d+)')


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _runtime(value: int | float) -> int:
    runtime = int(value)
    if runtime <= 0 or runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"max_runtime_sec must be in [1, {MAX_RUNTIME_SEC}]")
    return runtime


def _finite_number(value: Any, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def aggregate_daily_funding(
    rows: Iterable[Mapping[str, Any]],
    *,
    candidate_ids: set[str],
    before_ts: int,
) -> dict[str, dict[int, dict[str, float]]]:
    sums: dict[str, dict[int, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"mexc": 0.0, "gateio": 0.0})
    )
    seen_venues: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    seen_events: set[str] = set()
    for row in rows:
        canonical_id = str(row.get("canonical_asset_id") or "")
        if canonical_id not in candidate_ids:
            continue
        venue = str(row.get("venue") or "").lower()
        if venue not in {"mexc", "gateio"}:
            continue
        ts = int(row.get("settlement_ts") or row.get("ts") or 0)
        if ts <= 0 or ts >= int(before_ts):
            continue
        event_id = str(row.get("event_id") or f"{canonical_id}:{venue}:{ts}")
        if event_id in seen_events:
            raise ValueError(f"duplicate funding event_id: {event_id}")
        seen_events.add(event_id)
        rate_bps = _finite_number(row.get("funding_rate"), label="funding_rate") * 10_000.0
        day = ts // DAY_SEC
        sums[canonical_id][day][venue] += rate_bps
        seen_venues[canonical_id][day].add(venue)

    result: dict[str, dict[int, dict[str, float]]] = {}
    for canonical_id in sorted(candidate_ids):
        days: dict[int, dict[str, float]] = {}
        for day, venue_sums in sorted(sums.get(canonical_id, {}).items()):
            if seen_venues[canonical_id][day] != {"mexc", "gateio"}:
                continue
            mexc_bps = round(float(venue_sums["mexc"]), 12)
            gateio_bps = round(float(venue_sums["gateio"]), 12)
            days[day] = {
                "mexc_bps": mexc_bps,
                "gateio_bps": gateio_bps,
                "differential_bps": round(mexc_bps - gateio_bps, 12),
            }
        result[canonical_id] = days
    return result


def _qualifying_direction(
    days: Mapping[int, Mapping[str, float]],
    signal_day: int,
    *,
    confirmation_days: int,
    minimum_abs_daily_bps: float,
) -> tuple[int, float] | None:
    window: list[float] = []
    for day in range(signal_day - confirmation_days + 1, signal_day + 1):
        row = days.get(day)
        if row is None:
            return None
        value = float(row["differential_bps"])
        if value == 0.0:
            return None
        window.append(value)
    signs = {1 if value > 0.0 else -1 for value in window}
    if len(signs) != 1:
        return None
    mean_abs = abs(sum(window) / len(window))
    if mean_abs < float(minimum_abs_daily_bps):
        return None
    return signs.pop(), mean_abs


def detect_regime_episodes(
    daily: Mapping[str, Mapping[int, Mapping[str, float]]],
    *,
    train_start_sec: int,
    train_end_sec: int,
    candidate_ids: set[str],
    entry_bar_timestamps: Mapping[str, set[int]],
    confirmation_days: int,
    minimum_abs_daily_bps: float,
    adverse_exit_days: int,
    maximum_holding_days: int,
) -> list[dict[str, Any]]:
    start_day = int(train_start_sec) // DAY_SEC
    end_day = int(train_end_sec) // DAY_SEC
    episodes: list[dict[str, Any]] = []
    for canonical_id in sorted(candidate_ids):
        asset_days = daily.get(canonical_id) or {}
        available_entries = entry_bar_timestamps.get(canonical_id) or set()
        signal_day = start_day
        while signal_day < end_day - 1:
            qualifying = _qualifying_direction(
                asset_days,
                signal_day,
                confirmation_days=confirmation_days,
                minimum_abs_daily_bps=minimum_abs_daily_bps,
            )
            entry_day = signal_day + 1
            if qualifying is None or entry_day * DAY_SEC not in available_entries:
                signal_day += 1
                continue
            direction_sign, mean_abs = qualifying
            adverse_count = 0
            exit_day: int | None = None
            exit_reason = ""
            complete = True
            maximum_exit_day = entry_day + int(maximum_holding_days)
            for observed_day in range(entry_day, maximum_exit_day):
                row = asset_days.get(observed_day)
                if row is None:
                    complete = False
                    break
                directional_carry = direction_sign * float(row["differential_bps"])
                adverse_count = adverse_count + 1 if directional_carry <= 0.0 else 0
                if adverse_count >= int(adverse_exit_days):
                    exit_day = observed_day + 1
                    exit_reason = "two_complete_utc_days_nonpositive_in_entry_direction"
                    break
            if exit_day is None and complete:
                exit_day = maximum_exit_day
                exit_reason = "maximum_holding_days"
            if not complete or exit_day is None or exit_day > end_day:
                signal_day += 1
                continue
            episodes.append(
                {
                    "canonical_asset_id": canonical_id,
                    "signal_day": signal_day,
                    "entry_day": entry_day,
                    "exit_day": exit_day,
                    "holding_days": exit_day - entry_day,
                    "direction": (
                        "short_mexc_long_gate" if direction_sign > 0 else "long_mexc_short_gate"
                    ),
                    "confirmation_mean_abs_daily_bps": mean_abs,
                    "exit_reason": exit_reason,
                }
            )
            signal_day = exit_day
    return sorted(episodes, key=lambda row: (row["signal_day"], row["canonical_asset_id"]))


def _read_train_candles(
    path: Path,
    *,
    candidate_ids: set[str],
    train_start_sec: int,
    train_end_sec: int,
    deadline: float,
) -> tuple[dict[str, set[int]], int]:
    timestamps = {canonical_id: set() for canonical_id in candidate_ids}
    rows_read = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if time.monotonic() > deadline:
                raise TimeoutError("train feasibility exceeded max_runtime_sec while reading candles")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid train candle JSONL at line {line_number}") from exc
            if row.get("schema") != CANDLE_SCHEMA:
                raise ValueError(f"unexpected train candle schema at line {line_number}")
            canonical_id = str(row.get("canonical_asset_id") or "")
            if canonical_id not in candidate_ids:
                continue
            ts = int(row.get("ts") or 0)
            if int(train_start_sec) <= ts < int(train_end_sec):
                timestamps[canonical_id].add(ts)
                rows_read += 1
    return timestamps, rows_read


def _read_train_funding(
    path: Path,
    *,
    train_end_sec: int,
    deadline: float,
) -> tuple[list[dict[str, Any]], int, bool]:
    rows: list[dict[str, Any]] = []
    parsed_rows = 0
    first_oos_row_detected_without_json_decode = False
    previous_ts = -1
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if time.monotonic() > deadline:
                raise TimeoutError("train feasibility exceeded max_runtime_sec while reading funding")
            if not raw_line.strip():
                continue
            match = _SETTLEMENT_TS_PATTERN.search(raw_line)
            if match is None:
                raise ValueError(f"funding settlement_ts missing at line {line_number}")
            ts = int(match.group(1))
            if ts < previous_ts:
                raise ValueError("funding ledger is not sorted by settlement_ts")
            previous_ts = ts
            if ts >= int(train_end_sec):
                first_oos_row_detected_without_json_decode = True
                break
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid funding JSONL at line {line_number}") from exc
            if row.get("schema") != FUNDING_SCHEMA:
                raise ValueError(f"unexpected funding schema at line {line_number}")
            rows.append(row)
            parsed_rows += 1
    return rows, parsed_rows, first_oos_row_detected_without_json_decode


def _coverage_metrics(
    daily: Mapping[str, Mapping[int, Mapping[str, float]]],
    *,
    candidate_ids: set[str],
    train_start_sec: int,
    train_end_sec: int,
) -> dict[str, Any]:
    start_day = int(train_start_sec) // DAY_SEC
    end_day = int(train_end_sec) // DAY_SEC
    expected_days = end_day - start_day
    by_asset: dict[str, dict[str, Any]] = {}
    minimum = 1.0
    for canonical_id in sorted(candidate_ids):
        aligned = sum(1 for day in range(start_day, end_day) if day in (daily.get(canonical_id) or {}))
        coverage = aligned / expected_days if expected_days else 0.0
        minimum = min(minimum, coverage)
        by_asset[canonical_id] = {
            "aligned_complete_utc_days": aligned,
            "expected_train_days": expected_days,
            "dual_leg_coverage": coverage,
        }
    return {"minimum_dual_leg_coverage": minimum, "by_asset": by_asset}


def run_train_feasibility(
    plan_path: str | Path,
    *,
    expected_plan_hash: str,
    output_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = _runtime(max_runtime_sec)
    started = time.monotonic()
    deadline = started + runtime
    plan_target = Path(plan_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise ValueError(f"refusing to overwrite immutable feasibility artifact: {output_target}")
    plan = _load_json_object(plan_target, label="frozen plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unexpected frozen plan schema")
    expected = str(expected_plan_hash or "").lower()
    observed = str(plan.get("plan_hash") or "").lower()
    if expected != observed:
        raise ValueError("Expected plan hash does not match frozen artifact")
    if canonical_plan_hash(plan) != observed:
        raise ValueError("frozen plan hash mismatch")
    validate_plan(plan, verify_files=True)

    sealed = plan["sealed_input"]
    split = sealed["split"]
    train_start_sec = int(split["train_start_sec"])
    train_end_sec = int(split["train_end_sec"])
    candidate_ids = {
        str(row["canonical_asset_id"])
        for row in plan["universe"]["candidates"]
    }
    candle_timestamps, candle_rows_read = _read_train_candles(
        Path(sealed["train_path"]),
        candidate_ids=candidate_ids,
        train_start_sec=train_start_sec,
        train_end_sec=train_end_sec,
        deadline=deadline,
    )
    funding_rows, funding_rows_parsed, oos_boundary_seen = _read_train_funding(
        Path(sealed["funding_path"]),
        train_end_sec=train_end_sec,
        deadline=deadline,
    )
    daily = aggregate_daily_funding(
        funding_rows,
        candidate_ids=candidate_ids,
        before_ts=train_end_sec,
    )
    coverage = _coverage_metrics(
        daily,
        candidate_ids=candidate_ids,
        train_start_sec=train_start_sec,
        train_end_sec=train_end_sec,
    )
    strategy = plan["strategy"]
    episodes = detect_regime_episodes(
        daily,
        train_start_sec=train_start_sec,
        train_end_sec=train_end_sec,
        candidate_ids=candidate_ids,
        entry_bar_timestamps=candle_timestamps,
        confirmation_days=int(strategy["regime_confirmation_complete_utc_days"]),
        minimum_abs_daily_bps=float(strategy["minimum_abs_daily_funding_differential_bps"]),
        adverse_exit_days=int(strategy["adverse_exit_complete_utc_days"]),
        maximum_holding_days=int(strategy["maximum_holding_days"]),
    )

    gates = plan["validation"]["train_feasibility_gates"]
    data_gates = plan["validation"]["data_gates"]
    unique_dates = sorted({int(row["signal_day"]) for row in episodes})
    directions = sorted({str(row["direction"]) for row in episodes})
    reasons: list[str] = []
    minimum_coverage = float(coverage["minimum_dual_leg_coverage"])
    if minimum_coverage < float(data_gates["minimum_dual_leg_coverage"]):
        reasons.append("dual_leg_coverage_below_minimum")
        verdict = "INSUFFICIENT_DATA"
    else:
        if len(episodes) < int(gates["minimum_independent_regime_episodes"]):
            reasons.append("independent_regime_episodes_below_minimum")
        if len(unique_dates) < int(gates["minimum_unique_signal_dates"]):
            reasons.append("unique_signal_dates_below_minimum")
        expected_directions = {"short_mexc_long_gate", "long_mexc_short_gate"}
        if gates.get("both_route_directions_required") is True and set(directions) != expected_directions:
            reasons.append("both_route_directions_not_observed")
        verdict = "FEASIBLE_FOR_OOS" if not reasons else "INFEASIBLE_ON_CURRENT_DATA"

    result: dict[str, Any] = {
        "schema": FEASIBILITY_SCHEMA,
        "stage": "train_feasibility",
        "final": True,
        "verdict": verdict,
        "reasons": reasons,
        "plan_path": str(plan_target),
        "plan_file_sha256": _sha256_file(plan_target),
        "plan_hash": observed,
        "input_hashes": {
            "train_sha256": sealed["train_sha256"],
            "funding_sha256": sealed["funding_sha256"],
            "oos_sha256_hash_verified_only": sealed["oos_sha256"],
        },
        "evaluator_code": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256_file(Path(__file__).resolve()),
        },
        "metrics": {
            "candidate_count": len(candidate_ids),
            "train_candle_rows_read": candle_rows_read,
            "train_funding_rows_parsed": funding_rows_parsed,
            "minimum_dual_leg_coverage": minimum_coverage,
            "coverage_by_asset": coverage["by_asset"],
            "independent_regime_episodes": len(episodes),
            "unique_signal_dates": len(unique_dates),
            "route_directions": directions,
            "episodes_by_asset": {
                canonical_id: sum(1 for row in episodes if row["canonical_asset_id"] == canonical_id)
                for canonical_id in sorted(candidate_ids)
            },
            "episodes": episodes,
        },
        "gate_results": {
            "minimum_dual_leg_coverage": {
                "observed": minimum_coverage,
                "required": data_gates["minimum_dual_leg_coverage"],
                "passed": minimum_coverage >= float(data_gates["minimum_dual_leg_coverage"]),
            },
            "minimum_independent_regime_episodes": {
                "observed": len(episodes),
                "required": gates["minimum_independent_regime_episodes"],
                "passed": len(episodes) >= int(gates["minimum_independent_regime_episodes"]),
            },
            "minimum_unique_signal_dates": {
                "observed": len(unique_dates),
                "required": gates["minimum_unique_signal_dates"],
                "passed": len(unique_dates) >= int(gates["minimum_unique_signal_dates"]),
            },
            "both_route_directions_required": {
                "observed": directions,
                "required": ["long_mexc_short_gate", "short_mexc_long_gate"],
                "passed": set(directions) == {"short_mexc_long_gate", "long_mexc_short_gate"},
            },
        },
        "data_access_audit": {
            "plan_hash_verified_before_market_values": True,
            "source_hashes_verified_before_market_values": True,
            "train_values_read": True,
            "funding_rows_at_or_after_train_end_json_decoded": 0,
            "first_oos_funding_boundary_detected_without_json_decode": oos_boundary_seen,
            "oos_values_read": False,
            "oos_candle_file_opened_for_values": False,
            "oos_file_hash_verified": True,
            "pnl_computed": False,
            "returns_computed": False,
            "parameter_search": False,
        },
        "runtime_policy": {
            "max_runtime_sec": runtime,
            "network_used": False,
            "grid_search": False,
        },
        "next_allowed_action": (
            "implement_hash_bound_oos_evaluator"
            if verdict == "FEASIBLE_FOR_OOS"
            else "NO_COMMAND_TERMINAL_TRAIN_FEASIBILITY_NOT_PASSED"
        ),
    }
    result["deterministic_result_hash"] = _sha256_bytes(_canonical_json(result).encode("utf-8"))
    output_target.parent.mkdir(parents=True, exist_ok=True)
    output_target.write_text(_canonical_json(result) + "\n", encoding="utf-8")
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Funding regime persistence v2 train-only feasibility")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_train_feasibility(
        args.plan,
        expected_plan_hash=args.expected_plan_hash,
        output_path=args.output,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "reasons": result["reasons"],
                "plan_hash": result["plan_hash"],
                "deterministic_result_hash": result["deterministic_result_hash"],
                "next_allowed_action": result["next_allowed_action"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
