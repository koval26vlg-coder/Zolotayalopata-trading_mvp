from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from funding_regime_persistence_v2 import (
    DAY_SEC,
    PLAN_SCHEMA,
    canonical_plan_hash,
    validate_plan,
)
from funding_regime_persistence_v2_evaluator import (
    CANDLE_SCHEMA,
    FEASIBILITY_SCHEMA,
    FUNDING_SCHEMA,
    aggregate_daily_funding,
    detect_regime_episodes,
)


OOS_SCHEMA = "fast_first_funding_regime_persistence_oos_v2"
MAX_RUNTIME_SEC = 1_800
HOUR_SEC = 3_600
BOOTSTRAP_REPLICATES = 5_000
VALID_VERDICTS = frozenset({"ACCEPT_FOR_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA"})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


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


def _finite(value: Any, *, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _deterministic_result_hash(payload: Mapping[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("deterministic_result_hash", None)
    return _sha256_bytes(_canonical_json(normalized).encode("utf-8"))


def _validate_feasibility(
    path: Path,
    *,
    expected_result_hash: str,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _load_json_object(path, label="train feasibility")
    if payload.get("schema") != FEASIBILITY_SCHEMA or payload.get("stage") != "train_feasibility":
        raise ValueError("unexpected train feasibility schema")
    if payload.get("final") is not True or payload.get("verdict") != "FEASIBLE_FOR_OOS":
        raise ValueError("train feasibility is not FEASIBLE_FOR_OOS")
    observed_hash = str(payload.get("deterministic_result_hash") or "")
    if observed_hash != str(expected_result_hash):
        raise ValueError("feasibility result hash mismatch")
    if observed_hash != _deterministic_result_hash(payload):
        raise ValueError("train feasibility deterministic hash mismatch")
    if payload.get("plan_hash") != plan.get("plan_hash"):
        raise ValueError("train feasibility plan hash mismatch")
    sealed = plan["sealed_input"]
    expected_inputs = {
        "train_sha256": sealed["train_sha256"],
        "funding_sha256": sealed["funding_sha256"],
        "oos_sha256_hash_verified_only": sealed["oos_sha256"],
    }
    if payload.get("input_hashes") != expected_inputs:
        raise ValueError("train feasibility sealed input mismatch")
    audit = payload.get("data_access_audit") or {}
    if (
        audit.get("oos_values_read") is not False
        or audit.get("pnl_computed") is not False
        or audit.get("parameter_search") is not False
    ):
        raise ValueError("train feasibility violated OOS embargo")
    return payload


def _load_oos_candles(
    path: Path,
    *,
    candidate_ids: set[str],
    start_sec: int,
    end_sec: int,
    deadline: float,
) -> tuple[dict[str, dict[int, dict[str, Any]]], int]:
    rows: dict[str, dict[int, dict[str, Any]]] = {candidate_id: {} for candidate_id in candidate_ids}
    rows_read = 0
    previous_ts = -1
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if time.monotonic() > deadline:
                raise TimeoutError("OOS evaluation exceeded max_runtime_sec while reading candles")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid OOS candle JSONL at line {line_number}") from exc
            if not isinstance(row, dict) or row.get("schema") != CANDLE_SCHEMA:
                raise ValueError(f"unexpected OOS candle schema at line {line_number}")
            canonical_id = str(row.get("canonical_asset_id") or "")
            if canonical_id not in candidate_ids:
                continue
            ts = int(row.get("ts") or 0)
            if ts < previous_ts:
                raise ValueError("OOS candle ledger is not sorted by timestamp")
            previous_ts = ts
            if not start_sec <= ts < end_sec:
                raise ValueError(f"OOS candle timestamp outside sealed split at line {line_number}")
            if ts in rows[canonical_id]:
                raise ValueError(f"duplicate OOS candle for {canonical_id} at {ts}")
            normalized = dict(row)
            for field in ("mexc_trade_open", "gateio_trade_open"):
                value = _finite(row.get(field), label=field)
                if value <= 0.0:
                    raise ValueError(f"{field} must be positive at line {line_number}")
                normalized[field] = value
            normalized["segment_id"] = int(row.get("segment_id") or 0)
            rows[canonical_id][ts] = normalized
            rows_read += 1
    return rows, rows_read


def _load_funding_rows(
    path: Path,
    *,
    candidate_ids: set[str],
    before_ts: int,
    deadline: float,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    source_rows = 0
    oos_rows = 0
    previous_ts = -1
    seen_events: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if time.monotonic() > deadline:
                raise TimeoutError("OOS evaluation exceeded max_runtime_sec while reading funding")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid funding JSONL at line {line_number}") from exc
            if not isinstance(row, dict) or row.get("schema") != FUNDING_SCHEMA:
                raise ValueError(f"unexpected funding schema at line {line_number}")
            source_rows += 1
            ts = int(row.get("settlement_ts") or row.get("ts") or 0)
            if ts < previous_ts:
                raise ValueError("funding ledger is not sorted by settlement_ts")
            previous_ts = ts
            if ts >= before_ts:
                continue
            canonical_id = str(row.get("canonical_asset_id") or "")
            if canonical_id not in candidate_ids:
                continue
            venue = str(row.get("venue") or "").lower()
            if venue not in {"mexc", "gateio"}:
                continue
            event_id = str(row.get("event_id") or f"{canonical_id}:{venue}:{ts}")
            if event_id in seen_events:
                raise ValueError(f"duplicate funding event_id: {event_id}")
            seen_events.add(event_id)
            normalized = dict(row)
            normalized["settlement_ts"] = ts
            normalized["funding_rate"] = _finite(row.get("funding_rate"), label="funding_rate")
            normalized["venue"] = venue
            rows.append(normalized)
            oos_rows += 1
    return rows, source_rows, oos_rows


def _has_contiguous_candles(episode: Mapping[str, Any], rows: Mapping[int, Mapping[str, Any]]) -> bool:
    entry_ts = int(episode["entry_day"]) * DAY_SEC
    exit_ts = int(episode["exit_day"]) * DAY_SEC
    entry = rows.get(entry_ts)
    exit_row = rows.get(exit_ts)
    if entry is None or exit_row is None:
        return False
    if int(entry.get("segment_id") or 0) != int(exit_row.get("segment_id") or 0):
        return False
    return all(ts in rows for ts in range(entry_ts, exit_ts + 1, HOUR_SEC))


def calculate_episode_trade(
    episode: Mapping[str, Any],
    *,
    candles_by_ts: Mapping[int, Mapping[str, Any]],
    funding_events: Iterable[Mapping[str, Any]],
    notional_per_leg: float,
    normal_cycle_cost_bps: float,
    stress_cycle_cost_bps: float,
    stress_favorable_funding_haircut: float,
) -> dict[str, Any]:
    notional = _finite(notional_per_leg, label="notional_per_leg")
    if notional <= 0.0:
        raise ValueError("notional_per_leg must be positive")
    haircut = _finite(stress_favorable_funding_haircut, label="stress_favorable_funding_haircut")
    if not 0.0 <= haircut <= 1.0:
        raise ValueError("stress_favorable_funding_haircut must be in [0,1]")
    entry_ts = int(episode["entry_day"]) * DAY_SEC
    exit_ts = int(episode["exit_day"]) * DAY_SEC
    entry = candles_by_ts.get(entry_ts)
    exit_row = candles_by_ts.get(exit_ts)
    if entry is None or exit_row is None:
        raise ValueError("episode entry or exit candle is missing")
    direction = str(episode.get("direction") or "")
    if direction == "short_mexc_long_gate":
        positions = {"mexc": -1.0, "gateio": 1.0}
    elif direction == "long_mexc_short_gate":
        positions = {"mexc": 1.0, "gateio": -1.0}
    else:
        raise ValueError(f"unknown episode direction: {direction}")

    price_pnl = 0.0
    leg_price_pnl: dict[str, float] = {}
    for venue, position in positions.items():
        field = f"{venue}_trade_open"
        entry_price = _finite(entry.get(field), label=f"entry {field}")
        exit_price = _finite(exit_row.get(field), label=f"exit {field}")
        if entry_price <= 0.0 or exit_price <= 0.0:
            raise ValueError("episode prices must be positive")
        pnl = position * (exit_price / entry_price - 1.0) * notional
        leg_price_pnl[venue] = pnl
        price_pnl += pnl

    funding_pnl = 0.0
    stress_funding_pnl = 0.0
    funding_event_count = 0
    for event in funding_events:
        ts = int(event.get("settlement_ts") or event.get("ts") or 0)
        if not entry_ts < ts < exit_ts:
            continue
        venue = str(event.get("venue") or "").lower()
        if venue not in positions:
            continue
        rate = _finite(event.get("funding_rate"), label="funding_rate")
        cashflow = -positions[venue] * rate * notional
        funding_pnl += cashflow
        stress_funding_pnl += cashflow * haircut if cashflow > 0.0 else cashflow
        funding_event_count += 1

    normal_cost = notional * _finite(normal_cycle_cost_bps, label="normal_cycle_cost_bps") / 10_000.0
    stress_cost = notional * _finite(stress_cycle_cost_bps, label="stress_cycle_cost_bps") / 10_000.0
    normal_net = price_pnl + funding_pnl - normal_cost
    stress_net = price_pnl + stress_funding_pnl - stress_cost
    identity = {
        "canonical_asset_id": episode["canonical_asset_id"],
        "signal_day": int(episode["signal_day"]),
        "entry_day": int(episode["entry_day"]),
        "exit_day": int(episode["exit_day"]),
        "direction": direction,
    }
    return {
        "episode_id": _sha256_bytes(_canonical_json(identity).encode("utf-8")),
        **identity,
        "signal_ts": int(episode["signal_day"]) * DAY_SEC,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "signal_date_utc": datetime.fromtimestamp(int(episode["signal_day"]) * DAY_SEC, timezone.utc).date().isoformat(),
        "holding_days": int(episode["holding_days"]),
        "exit_reason": str(episode.get("exit_reason") or ""),
        "confirmation_mean_abs_daily_bps": float(episode.get("confirmation_mean_abs_daily_bps") or 0.0),
        "leg_price_pnl_quote": {key: round(value, 12) for key, value in sorted(leg_price_pnl.items())},
        "price_pnl_quote": round(price_pnl, 12),
        "funding_pnl_quote": round(funding_pnl, 12),
        "normal_cost_quote": round(normal_cost, 12),
        "price_only_net_pnl_quote": round(price_pnl - normal_cost, 12),
        "normal_net_pnl_quote": round(normal_net, 12),
        "stress_funding_pnl_quote": round(stress_funding_pnl, 12),
        "stress_cost_quote": round(stress_cost, 12),
        "stress_net_pnl_quote": round(stress_net, 12),
        "funding_event_count": funding_event_count,
    }


def _cluster_bootstrap_lower_bound(
    trades: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> float:
    clusters: dict[int, list[float]] = defaultdict(list)
    for trade in trades:
        clusters[int(trade["signal_day"])].append(float(trade["normal_net_pnl_quote"]))
    keys = sorted(clusters)
    if not keys:
        return 0.0
    generator = random.Random(seed)
    estimates: list[float] = []
    for _ in range(int(replicates)):
        values: list[float] = []
        for _cluster in keys:
            values.extend(clusters[generator.choice(keys)])
        estimates.append(sum(values) / len(values) if values else 0.0)
    estimates.sort()
    index = max(0, min(len(estimates) - 1, math.floor(0.025 * (len(estimates) - 1))))
    return estimates[index]


def _positive_concentration(
    trades: Sequence[Mapping[str, Any]],
    *,
    key: str,
) -> float:
    total = sum(max(0.0, float(trade["normal_net_pnl_quote"])) for trade in trades)
    if total <= 0.0:
        return 1.0
    grouped: dict[str, float] = defaultdict(float)
    for trade in trades:
        grouped[str(trade[key])] += max(0.0, float(trade["normal_net_pnl_quote"]))
    return max(grouped.values(), default=0.0) / total


def _maximum_drawdown(trades: Sequence[Mapping[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for trade in sorted(trades, key=lambda row: (int(row["exit_ts"]), str(row["episode_id"]))):
        equity += float(trade["normal_net_pnl_quote"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _peak_concurrent_positions(trades: Sequence[Mapping[str, Any]]) -> int:
    points: list[tuple[int, int]] = []
    for trade in trades:
        points.append((int(trade["entry_ts"]), 1))
        points.append((int(trade["exit_ts"]), -1))
    active = 0
    peak = 0
    for _ts, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return peak


def summarize_trades(
    trades: Sequence[Mapping[str, Any]],
    *,
    folds: Sequence[Mapping[str, Any]],
    plan_hash: str,
    notional_per_leg: float,
) -> dict[str, Any]:
    count = len(trades)
    normal_values = [float(trade["normal_net_pnl_quote"]) for trade in trades]
    stress_values = [float(trade["stress_net_pnl_quote"]) for trade in trades]
    gross_profit = sum(value for value in normal_values if value > 0.0)
    gross_loss = -sum(value for value in normal_values if value < 0.0)
    profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else None
    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        start = int(fold["start_sec"])
        end = int(fold["end_sec"])
        selected = [trade for trade in trades if start <= int(trade["entry_ts"]) < end]
        net = sum(float(trade["normal_net_pnl_quote"]) for trade in selected)
        fold_rows.append(
            {
                "fold": int(fold["fold"]),
                "start_sec": start,
                "end_sec": end,
                "episode_count": len(selected),
                "net_pnl_quote": round(net, 12),
                "expectancy_quote": round(net / len(selected), 12) if selected else 0.0,
                "positive": bool(selected) and net > 0.0,
            }
        )
    maximum_drawdown = _maximum_drawdown(trades)
    peak_concurrent = _peak_concurrent_positions(trades)
    collateral = peak_concurrent * float(notional_per_leg) * 2.0
    direction_metrics: dict[str, dict[str, Any]] = {}
    for direction in ("long_mexc_short_gate", "short_mexc_long_gate"):
        selected = [trade for trade in trades if trade["direction"] == direction]
        direction_metrics[direction] = {
            "episode_count": len(selected),
            "net_pnl_quote": round(sum(float(row["normal_net_pnl_quote"]) for row in selected), 12),
            "expectancy_quote": round(
                sum(float(row["normal_net_pnl_quote"]) for row in selected) / len(selected), 12
            ) if selected else 0.0,
        }
    return {
        "independent_episode_count": count,
        "unique_signal_dates": len({int(trade["signal_day"]) for trade in trades}),
        "unique_assets": len({str(trade["canonical_asset_id"]) for trade in trades}),
        "total_price_pnl_quote": round(sum(float(row["price_pnl_quote"]) for row in trades), 12),
        "total_funding_pnl_quote": round(sum(float(row["funding_pnl_quote"]) for row in trades), 12),
        "total_normal_cost_quote": round(sum(float(row["normal_cost_quote"]) for row in trades), 12),
        "price_only_net_pnl_quote": round(sum(float(row["price_only_net_pnl_quote"]) for row in trades), 12),
        "total_net_pnl_quote": round(sum(normal_values), 12),
        "total_net_expectancy_quote": round(sum(normal_values) / count, 12) if count else 0.0,
        "gross_profit_quote": round(gross_profit, 12),
        "gross_loss_quote": round(gross_loss, 12),
        "profit_factor": round(profit_factor, 12) if profit_factor is not None else None,
        "profit_factor_infinite": gross_loss == 0.0 and gross_profit > 0.0,
        "positive_event_rate": sum(value > 0.0 for value in normal_values) / count if count else 0.0,
        "stress_total_net_pnl_quote": round(sum(stress_values), 12),
        "stress_expectancy_quote": round(sum(stress_values) / count, 12) if count else 0.0,
        "cluster_bootstrap_lower_95_quote": round(
            _cluster_bootstrap_lower_bound(
                trades,
                seed=int(str(plan_hash)[:16], 16),
            ),
            12,
        ),
        "maximum_single_base_positive_pnl_share": round(
            _positive_concentration(trades, key="canonical_asset_id"), 12
        ),
        "maximum_single_date_positive_pnl_share": round(
            _positive_concentration(trades, key="signal_day"), 12
        ),
        "maximum_single_event_positive_pnl_share": round(
            _positive_concentration(trades, key="episode_id"), 12
        ),
        "maximum_drawdown_quote": round(maximum_drawdown, 12),
        "peak_concurrent_positions": peak_concurrent,
        "peak_collateral_quote": round(collateral, 12),
        "maximum_drawdown_fraction_of_collateral": round(
            maximum_drawdown / collateral if collateral > 0.0 else 0.0, 12
        ),
        "maximum_observed_holding_days": max((int(row["holding_days"]) for row in trades), default=0),
        "walk_forward_folds": fold_rows,
        "positive_walk_forward_folds": sum(bool(row["positive"]) for row in fold_rows),
        "direction_metrics": direction_metrics,
        "effective_sample_size_signal_dates": len({int(trade["signal_day"]) for trade in trades}),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
    }


def historical_oos_verdict(
    metrics: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> tuple[str, list[str]]:
    insufficient: list[str] = []
    if int(metrics.get("independent_episode_count") or 0) < int(gates["minimum_independent_regime_episodes"]):
        insufficient.append("independent_regime_episodes_below_minimum")
    if int(metrics.get("unique_signal_dates") or 0) < int(gates["minimum_unique_signal_dates"]):
        insufficient.append("unique_signal_dates_below_minimum")
    if insufficient:
        return "INSUFFICIENT_DATA", insufficient

    reasons: list[str] = []
    if float(metrics["total_net_expectancy_quote"]) <= float(gates["total_net_expectancy_after_costs_gt"]):
        reasons.append("total_net_expectancy_after_costs")
    profit_factor = metrics.get("profit_factor")
    if not bool(metrics.get("profit_factor_infinite")) and (
        profit_factor is None or float(profit_factor) < float(gates["profit_factor_gte"])
    ):
        reasons.append("profit_factor")
    if float(metrics["positive_event_rate"]) < float(gates["positive_event_rate_gte"]):
        reasons.append("positive_event_rate")
    if int(metrics["positive_walk_forward_folds"]) < int(gates["minimum_positive_walk_forward_folds"]):
        reasons.append("positive_walk_forward_folds")
    if float(metrics["stress_total_net_pnl_quote"]) < float(gates["stress_total_net_pnl_gte"]):
        reasons.append("stress_total_net_pnl")
    if float(metrics["cluster_bootstrap_lower_95_quote"]) <= float(
        gates["cluster_bootstrap_95pct_expectancy_lower_bound_gt"]
    ):
        reasons.append("cluster_bootstrap_lower_95")
    if float(metrics["maximum_single_base_positive_pnl_share"]) > float(
        gates["maximum_single_base_positive_pnl_share"]
    ):
        reasons.append("single_base_positive_pnl_concentration")
    if float(metrics["maximum_single_date_positive_pnl_share"]) > float(
        gates["maximum_single_date_positive_pnl_share"]
    ):
        reasons.append("single_date_positive_pnl_concentration")
    if float(metrics["maximum_single_event_positive_pnl_share"]) > float(
        gates["maximum_single_event_positive_pnl_share"]
    ):
        reasons.append("single_event_positive_pnl_concentration")
    if float(metrics["maximum_drawdown_fraction_of_collateral"]) > float(
        gates["maximum_drawdown_fraction_of_collateral"]
    ):
        reasons.append("maximum_drawdown_fraction_of_collateral")
    if int(metrics["maximum_observed_holding_days"]) > int(gates["maximum_holding_days"]):
        reasons.append("maximum_holding_days")
    return ("REJECT", reasons) if reasons else ("ACCEPT_FOR_EXECUTION_PROBE", [])


def validate_oos_result(
    result: Mapping[str, Any],
    *,
    require_accept: bool = False,
) -> dict[str, Any]:
    if result.get("schema") != OOS_SCHEMA or result.get("stage") != "full_oos_evaluation":
        raise ValueError("unexpected funding regime OOS result schema")
    verdict = str(result.get("verdict") or "")
    if verdict not in VALID_VERDICTS:
        raise ValueError("unsupported funding regime OOS verdict")
    if require_accept and verdict != "ACCEPT_FOR_EXECUTION_PROBE":
        raise ValueError("OOS result is not ACCEPT_FOR_EXECUTION_PROBE")
    audit = result.get("data_access_audit") or {}
    if (
        audit.get("oos_values_read") is not True
        or audit.get("network_used") is not False
        or audit.get("grid_search") is not False
        or audit.get("retune") is not False
    ):
        raise ValueError("invalid OOS data-access audit")
    permissions = result.get("permissions") or {}
    if any(permissions.get(key) is not False for key in ("live_orders", "private_api_keys", "leverage", "margin")):
        raise ValueError("OOS artifact grants forbidden permissions")
    if result.get("deterministic_result_hash") != _deterministic_result_hash(result):
        raise ValueError("OOS deterministic result hash mismatch")
    if require_accept:
        recomputed, reasons = historical_oos_verdict(
            result.get("metrics") or {},
            result.get("acceptance_gates") or {},
        )
        if recomputed != verdict or reasons or result.get("rejection_reasons"):
            raise ValueError("OOS ACCEPT does not satisfy frozen gates")
    return dict(result)


def _coverage_metrics(
    daily: Mapping[str, Mapping[int, Mapping[str, float]]],
    *,
    candidate_ids: set[str],
    start_sec: int,
    end_sec: int,
) -> dict[str, Any]:
    start_day = start_sec // DAY_SEC
    end_day = end_sec // DAY_SEC
    expected = end_day - start_day
    by_asset: dict[str, Any] = {}
    minimum = 1.0
    for canonical_id in sorted(candidate_ids):
        aligned = sum(day in (daily.get(canonical_id) or {}) for day in range(start_day, end_day))
        coverage = aligned / expected if expected else 0.0
        minimum = min(minimum, coverage)
        by_asset[canonical_id] = {
            "aligned_complete_utc_days": aligned,
            "expected_oos_days": expected,
            "dual_leg_coverage": coverage,
        }
    return {"minimum_dual_leg_coverage": minimum, "by_asset": by_asset}


def run_oos_evaluation(
    plan_path: str | Path,
    *,
    expected_plan_hash: str,
    feasibility_path: str | Path,
    expected_feasibility_result_hash: str,
    output_path: str | Path,
    max_runtime_sec: int = MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    runtime = _runtime(max_runtime_sec)
    started = time.monotonic()
    deadline = started + runtime
    plan_target = Path(plan_path).expanduser().resolve()
    feasibility_target = Path(feasibility_path).expanduser().resolve()
    output_target = Path(output_path).expanduser().resolve()
    if output_target.exists():
        raise ValueError(f"refusing to overwrite immutable OOS artifact: {output_target}")

    plan = _load_json_object(plan_target, label="frozen plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unexpected frozen plan schema")
    observed_plan_hash = str(plan.get("plan_hash") or "")
    if observed_plan_hash != str(expected_plan_hash):
        raise ValueError("Expected plan hash does not match frozen artifact")
    if canonical_plan_hash(plan) != observed_plan_hash:
        raise ValueError("frozen plan hash mismatch")
    validate_plan(plan, verify_files=True)
    feasibility = _validate_feasibility(
        feasibility_target,
        expected_result_hash=expected_feasibility_result_hash,
        plan=plan,
    )

    sealed = plan["sealed_input"]
    split = sealed["split"]
    oos_start = int(split["oos_start_sec"])
    oos_end = int(split["oos_end_sec"])
    candidate_ids = {str(row["canonical_asset_id"]) for row in plan["universe"]["candidates"]}

    candles, candle_rows_read = _load_oos_candles(
        Path(sealed["oos_path"]),
        candidate_ids=candidate_ids,
        start_sec=oos_start,
        end_sec=oos_end,
        deadline=deadline,
    )
    if candle_rows_read != int(sealed["oos_row_count"]):
        raise ValueError("OOS candle row count mismatch")
    funding_rows, funding_source_rows_read, selected_funding_rows = _load_funding_rows(
        Path(sealed["funding_path"]),
        candidate_ids=candidate_ids,
        before_ts=oos_end,
        deadline=deadline,
    )
    daily = aggregate_daily_funding(
        funding_rows,
        candidate_ids=candidate_ids,
        before_ts=oos_end,
    )
    coverage = _coverage_metrics(
        daily,
        candidate_ids=candidate_ids,
        start_sec=oos_start,
        end_sec=oos_end,
    )
    strategy = plan["strategy"]
    episodes = detect_regime_episodes(
        daily,
        train_start_sec=oos_start,
        train_end_sec=oos_end,
        candidate_ids=candidate_ids,
        entry_bar_timestamps={canonical_id: set(rows) for canonical_id, rows in candles.items()},
        confirmation_days=int(strategy["regime_confirmation_complete_utc_days"]),
        minimum_abs_daily_bps=float(strategy["minimum_abs_daily_funding_differential_bps"]),
        adverse_exit_days=int(strategy["adverse_exit_complete_utc_days"]),
        maximum_holding_days=int(strategy["maximum_holding_days"]),
    )
    right_censored = [
        episode
        for episode in episodes
        if int(episode["exit_day"]) * DAY_SEC >= oos_end
    ]
    gap_episodes = [
        episode
        for episode in episodes
        if episode not in right_censored
        and not _has_contiguous_candles(episode, candles[str(episode["canonical_asset_id"])])
    ]
    continuous = [
        episode
        for episode in episodes
        if episode not in right_censored and episode not in gap_episodes
    ]
    funding_by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in funding_rows:
        funding_by_asset[str(row["canonical_asset_id"])].append(row)
    economics = plan["economics"]
    normal_cost_bps = float(economics["normal_cycle_cost"]["total_bps"])
    stress_cost_bps = float(economics["stress_cycle_cost"]["total_bps"])
    notional = float(economics["notional_quote_per_leg"])
    haircut = float(economics["stress_favorable_funding_haircut"])
    trades = [
        calculate_episode_trade(
            episode,
            candles_by_ts=candles[str(episode["canonical_asset_id"])],
            funding_events=funding_by_asset[str(episode["canonical_asset_id"])],
            notional_per_leg=notional,
            normal_cycle_cost_bps=normal_cost_bps,
            stress_cycle_cost_bps=stress_cost_bps,
            stress_favorable_funding_haircut=haircut,
        )
        for episode in continuous
    ]
    if time.monotonic() > deadline:
        raise TimeoutError("OOS evaluation exceeded max_runtime_sec before metrics")

    metrics = summarize_trades(
        trades,
        folds=plan["validation"]["walk_forward"]["folds"],
        plan_hash=observed_plan_hash,
        notional_per_leg=notional,
    )
    data_gates = plan["validation"]["data_gates"]
    data_reasons: list[str] = []
    if len(candidate_ids) < int(data_gates["minimum_surviving_assets"]):
        data_reasons.append("surviving_assets_below_minimum")
    if float(coverage["minimum_dual_leg_coverage"]) < float(data_gates["minimum_dual_leg_coverage"]):
        data_reasons.append("dual_leg_coverage_below_minimum")
    oos_settlements = sum(oos_start <= int(row["settlement_ts"]) < oos_end for row in funding_rows)
    if oos_settlements < int(data_gates["minimum_funding_settlements"]):
        data_reasons.append("funding_settlements_below_minimum")
    if gap_episodes:
        data_reasons.append("episode_crossed_candle_gap")

    acceptance_gates = dict(plan["validation"]["oos_acceptance_gates"])
    if data_reasons:
        verdict = "INSUFFICIENT_DATA"
        rejection_reasons = data_reasons
    else:
        verdict, rejection_reasons = historical_oos_verdict(metrics, acceptance_gates)
    next_action = (
        "create_execution_probe_planonly"
        if verdict == "ACCEPT_FOR_EXECUTION_PROBE"
        else "NO_COMMAND_TERMINAL_HISTORICAL_BRANCH_CLOSED"
    )
    result: dict[str, Any] = {
        "schema": OOS_SCHEMA,
        "stage": "full_oos_evaluation",
        "final": True,
        "verdict": verdict,
        "rejection_reasons": rejection_reasons,
        "plan_path": str(plan_target),
        "plan_file_sha256": _sha256_file(plan_target),
        "plan_hash": observed_plan_hash,
        "feasibility_provenance": {
            "path": str(feasibility_target),
            "file_sha256": _sha256_file(feasibility_target),
            "deterministic_result_hash": feasibility["deterministic_result_hash"],
            "verdict": feasibility["verdict"],
        },
        "input_hashes": {
            "oos_sha256": sealed["oos_sha256"],
            "funding_sha256": sealed["funding_sha256"],
            "input_file_merkle_sha256": sealed["input_file_merkle_sha256"],
        },
        "strategy": strategy,
        "economics": economics,
        "acceptance_gates": acceptance_gates,
        "data_quality": {
            "candidate_count": len(candidate_ids),
            "oos_candle_rows_read": candle_rows_read,
            "funding_source_rows_read": funding_source_rows_read,
            "candidate_funding_rows_before_oos_end": selected_funding_rows,
            "oos_funding_settlements": oos_settlements,
            "minimum_dual_leg_coverage": coverage["minimum_dual_leg_coverage"],
            "coverage_by_asset": coverage["by_asset"],
            "episodes_before_candle_continuity_gate": len(episodes),
            "right_censored_episodes_excluded": len(right_censored),
            "internal_gap_episodes_rejected": len(gap_episodes),
            "episodes_after_candle_continuity_gate": len(continuous),
            "reasons": data_reasons,
        },
        "metrics": metrics,
        "trades": trades,
        "data_access_audit": {
            "plan_hash_verified_before_oos_values": True,
            "source_hashes_verified_before_oos_values": True,
            "feasibility_hash_verified_before_oos_values": True,
            "oos_values_read": True,
            "pnl_computed": True,
            "returns_computed": True,
            "network_used": False,
            "grid_search": False,
            "retune": False,
            "parameter_selection_on_oos": False,
        },
        "permissions": {
            "execution_probe": verdict == "ACCEPT_FOR_EXECUTION_PROBE",
            "paper_forward": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage": False,
            "margin": False,
        },
        "runtime_policy": {
            "max_runtime_sec": runtime,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        },
        "next_allowed_action": next_action,
    }
    result["deterministic_result_hash"] = _deterministic_result_hash(result)
    validate_oos_result(result, require_accept=False)
    output_target.parent.mkdir(parents=True, exist_ok=True)
    output_target.write_text(_canonical_json(result) + "\n", encoding="utf-8")
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Funding regime persistence v2 hash-bound OOS evaluator")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--feasibility", required=True)
    parser.add_argument("--expected-feasibility-result-hash", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-runtime-sec", type=int, default=MAX_RUNTIME_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_oos_evaluation(
        args.plan,
        expected_plan_hash=args.expected_plan_hash,
        feasibility_path=args.feasibility,
        expected_feasibility_result_hash=args.expected_feasibility_result_hash,
        output_path=args.output,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "rejection_reasons": result["rejection_reasons"],
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
