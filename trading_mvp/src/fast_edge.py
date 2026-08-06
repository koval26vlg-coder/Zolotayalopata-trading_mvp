from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from costs import (
    DEFAULT_RUNTIME_SEC,
    MAX_RUNTIME_SEC,
    CostProfile,
    base_api_cost_profile,
    route_legs,
    validate_runtime_sec,
)
from execution_gate import (
    book_stats,
    capacity_within_impact_bps,
    market_impact_bps,
    normalize_gate_perp,
    normalize_mexc_perp,
    normalize_mexc_spot,
)


DAY_SEC = 86_400
DEFAULT_SHORTLIST_LIMIT = 20
DEFAULT_NOTIONAL_PER_LEG = 1_000.0
DEFAULT_PROBE_DURATION_SEC = 1_200
DEFAULT_PROBE_INTERVAL_SEC = 5.0
DEFAULT_PROBE_NOTIONAL = 500.0

ACCEPTANCE_GATES: dict[str, Any] = {
    "min_oos_aligned_days": 60,
    "min_oos_settlements": 60,
    "min_dual_leg_coverage": 0.80,
    "min_oos_net_expectancy_quote": 0.0,
    "min_oos_profit_factor": 1.20,
    "min_positive_settlement_rate": 0.60,
    "min_positive_walk_forward_folds": 4,
    "walk_forward_folds": 5,
    "min_stress_net_pnl_quote": 0.0,
    "max_break_even_days": 14.0,
    "max_single_funding_event_share": 0.25,
    "min_execution_snapshots": 180,
    "min_execution_coverage": 0.80,
    "min_capacity_usd_per_leg": 500.0,
    "max_p95_impact_bps": 10.0,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_day(ts: float) -> int:
    return int(float(ts) // DAY_SEC)


def day_iso(day: int) -> str:
    return datetime.fromtimestamp(day * DAY_SEC, tz=timezone.utc).date().isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def default_output_root() -> Path:
    external = Path(r"E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge")
    if external.parent.parent.parent.exists():
        return external
    return Path(__file__).resolve().parents[2] / "exports" / "trading-mvp" / "fast-edge"


def _artifact_path(folder: str, prefix: str, suffix: str = ".json") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return default_output_root() / folder / f"{prefix}_{stamp}{suffix}"


def discover_fixed_branch_evidence(dataset: Path) -> dict[str, dict[str, str]]:
    evidence_root = dataset.parent.parent if dataset.parent.name == "daily" else dataset.parent
    backtests = evidence_root / "backtests"
    patterns = {
        "listing_event_drift_reversal": "listing_event_replay_planonly_*.json",
        "slow_liquidity_fixed_v1": "slow_liquidity_fixed_v1_replay_planonly_*.json",
    }
    evidence: dict[str, dict[str, str]] = {}
    for branch, pattern in patterns.items():
        matches = sorted(backtests.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        if not matches:
            continue
        path = matches[0].resolve()
        evidence[branch] = {"path": str(path), "sha256": sha256_file(path)}
    return evidence


def _plan_payload_for_hash(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "plan_hash"}


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != "fast_edge_plan_v1":
        raise ValueError("Unsupported fast-edge plan schema")
    expected = sha256_json(_plan_payload_for_hash(plan))
    if expected != plan.get("plan_hash"):
        raise ValueError("Fast-edge plan hash mismatch; frozen config was modified")
    validate_runtime_sec(plan["runtime"]["max_runtime_sec"])


def create_plan(
    dataset_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    max_runtime_sec: int = DEFAULT_RUNTIME_SEC,
    shortlist_limit: int = DEFAULT_SHORTLIST_LIMIT,
    notional_per_leg: float = DEFAULT_NOTIONAL_PER_LEG,
) -> dict[str, Any]:
    runtime = validate_runtime_sec(max_runtime_sec)
    if not 1 <= int(shortlist_limit) <= DEFAULT_SHORTLIST_LIMIT:
        raise ValueError(f"shortlist_limit must be in [1, {DEFAULT_SHORTLIST_LIMIT}]")
    if notional_per_leg <= 0.0:
        raise ValueError("notional_per_leg must be > 0")
    dataset = Path(dataset_dir).resolve()
    manifest_path = dataset / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Daily history manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    if manifest.get("schema") != "daily_collect_v1":
        raise ValueError("Fast-edge v1 requires a daily_collect_v1 dataset")
    profile = base_api_cost_profile()
    frozen_config = {
        "hypothesis": "funding_basis_carry",
        "routes": ["same_venue_mexc_spot_perp", "cross_venue_perp_perp"],
        "universe": {
            "exchanges": ["mexc", "gateio"],
            "quote": "USDT",
            "non_binance_spot_only": True,
            "shortlist_limit": int(shortlist_limit),
            "selection": "dual_leg_availability_then_min_24h_volume",
        },
        "split": {
            "method": "chronological",
            "train_fraction": 0.70,
            "oos_fraction": 0.30,
            "walk_forward_folds": 5,
            "parameter_selection_on_oos": False,
        },
        "notional_per_leg_quote": float(notional_per_leg),
        "leverage": 1.0,
        "grid_search": False,
        "acceptance_gates": ACCEPTANCE_GATES,
        "fallback_policy": {
            "order": ["listing_event_drift_reversal", "slow_liquidity_fixed_v1"],
            "one_fixed_test_per_branch": True,
            "reuse_frozen_artifacts": True,
            "retuning_on_same_sample": False,
        },
    }
    fixed_branch_evidence = discover_fixed_branch_evidence(dataset)
    created_at = utc_now()
    cache_key = sha256_json(
        {
            "manifest_sha256": sha256_file(manifest_path),
            "frozen_config": frozen_config,
            "cost_profile": profile.as_dict(),
            "fixed_branch_evidence": fixed_branch_evidence,
        }
    )
    plan: dict[str, Any] = {
        "schema": "fast_edge_plan_v1",
        "plan_id": f"fast_edge_{created_at.replace(':', '').replace('-', '').replace('+00:00', 'Z')}",
        "created_at_utc": created_at,
        "status": "FROZEN",
        "research_only": True,
        "live_orders": False,
        "api_keys": False,
        "margin_or_leverage": False,
        "dataset": {
            "path": str(dataset),
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "source_run_id": manifest.get("run_id"),
            "source_duration_sec": manifest.get("duration_sec"),
        },
        "frozen_config": frozen_config,
        "cost_profile": profile.as_dict(),
        "fixed_branch_evidence": fixed_branch_evidence,
        "runtime": {
            "max_runtime_sec": runtime,
            "default_network_collect_sec": min(DEFAULT_RUNTIME_SEC, runtime),
            "absolute_cap_sec": MAX_RUNTIME_SEC,
            "long_runs_require_separate_request": True,
        },
        "cache_key": cache_key,
        "fee_provenance": {
            exchange: schedule["source"]
            for exchange, schedule in profile.as_dict()["schedules"].items()
        },
        "next_allowed_command": "fast-edge-evaluate",
    }
    plan["plan_hash"] = sha256_json(_plan_payload_for_hash(plan))
    destination = Path(output_path) if output_path else _artifact_path("plans", "fast_edge_plan")
    write_json_atomic(destination, plan)
    plan["artifact_path"] = str(destination.resolve())
    return plan


def load_plan(path: str | Path) -> dict[str, Any]:
    plan = read_json(path)
    validate_plan(plan)
    return plan


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = read_json(path)
    return [row for row in payload.get("rows") or [] if isinstance(row, dict)]


def load_funding_events(dataset: Path, exchange: str, symbol: str) -> list[tuple[float, float]]:
    rows = _load_rows(dataset / exchange / "funding" / f"{symbol}.json")
    events: list[tuple[float, float]] = []
    for row in rows:
        try:
            ts = float(row["ts"])
            rate = float(row["funding_rate"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(ts) and math.isfinite(rate):
            events.append((ts, rate))
    events.sort()
    return events


def aggregate_funding_daily(events: Iterable[tuple[float, float]]) -> dict[int, float]:
    daily: dict[int, float] = {}
    for ts, rate in events:
        day = utc_day(ts)
        daily[day] = daily.get(day, 0.0) + rate
    return daily


def load_closes(dataset: Path, exchange: str, symbol: str, folder: str = "klines") -> dict[int, float]:
    rows = _load_rows(dataset / exchange / folder / f"{symbol}.json")
    closes: dict[int, float] = {}
    for row in rows:
        try:
            ts = float(row["ts"])
            close = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if close > 0.0 and math.isfinite(close):
            closes[utc_day(ts)] = close
    return closes


def select_shortlist(manifest: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    by_exchange: dict[str, dict[str, dict[str, Any]]] = {}
    for row in manifest.get("universe") or []:
        exchange = str(row.get("exchange") or "").lower()
        symbol = str(row.get("symbol") or "").upper()
        if exchange and symbol:
            by_exchange.setdefault(exchange, {})[symbol] = row
    mexc = by_exchange.get("mexc", {})
    gate = by_exchange.get("gateio", {})
    candidates: list[dict[str, Any]] = []
    for symbol in set(mexc) & set(gate):
        if mexc[symbol].get("non_binance_baseline") is not True:
            continue
        if gate[symbol].get("non_binance_baseline") is not True:
            continue
        min_volume = min(
            float(mexc[symbol].get("volume_24h_quote") or 0.0),
            float(gate[symbol].get("volume_24h_quote") or 0.0),
        )
        candidates.append(
            {
                "symbol": symbol,
                "base": str(mexc[symbol].get("base") or symbol.replace("_USDT", "")),
                "min_volume_24h_quote": min_volume,
                "non_binance_baseline": True,
            }
        )
    candidates.sort(key=lambda row: (-row["min_volume_24h_quote"], row["symbol"]))
    return candidates[:limit]


def merge_event_differential(
    positive_leg_events: Iterable[tuple[float, float]],
    negative_leg_events: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    merged: dict[float, float] = {}
    for ts, rate in positive_leg_events:
        merged[ts] = merged.get(ts, 0.0) + rate
    for ts, rate in negative_leg_events:
        merged[ts] = merged.get(ts, 0.0) - rate
    return sorted(merged.items())


@dataclass(frozen=True)
class CandidateSeries:
    route: str
    symbol: str
    observations: list[dict[str, float]]
    settlement_events: list[tuple[float, float]]
    expected_days: int
    valid_days: int
    input_files: list[Path]
    fixed_direction: int | None = None


def build_cross_venue_series(dataset: Path, symbol: str) -> CandidateSeries:
    mexc_events = load_funding_events(dataset, "mexc", symbol)
    gate_events = load_funding_events(dataset, "gateio", symbol)
    mexc_daily = aggregate_funding_daily(mexc_events)
    gate_daily = aggregate_funding_daily(gate_events)
    mexc_close = load_closes(dataset, "mexc", symbol)
    gate_close = load_closes(dataset, "gateio", symbol)
    days = sorted(set(mexc_daily) & set(gate_daily) & set(mexc_close) & set(gate_close))
    observations = [
        {
            "day": float(day),
            "funding_diff": gate_daily[day] - mexc_daily[day],
            "leg_a_close": mexc_close[day],
            "leg_b_close": gate_close[day],
        }
        for day in days
    ]
    expected = days[-1] - days[0] + 1 if days else 0
    return CandidateSeries(
        route="cross_venue_perp_perp",
        symbol=symbol,
        observations=observations,
        settlement_events=merge_event_differential(gate_events, mexc_events),
        expected_days=expected,
        valid_days=len(days),
        input_files=[
            dataset / "mexc" / "funding" / f"{symbol}.json",
            dataset / "gateio" / "funding" / f"{symbol}.json",
            dataset / "mexc" / "klines" / f"{symbol}.json",
            dataset / "gateio" / "klines" / f"{symbol}.json",
        ],
    )


def build_same_venue_series(dataset: Path, symbol: str) -> CandidateSeries | None:
    spot_path = dataset / "mexc" / "spot_klines" / f"{symbol}.json"
    if not spot_path.exists():
        return None
    funding_events = load_funding_events(dataset, "mexc", symbol)
    funding_daily = aggregate_funding_daily(funding_events)
    spot_close = load_closes(dataset, "mexc", symbol, folder="spot_klines")
    perp_close = load_closes(dataset, "mexc", symbol)
    days = sorted(set(funding_daily) & set(spot_close) & set(perp_close))
    observations = [
        {
            "day": float(day),
            "funding_diff": funding_daily[day],
            "leg_a_close": spot_close[day],
            "leg_b_close": perp_close[day],
        }
        for day in days
    ]
    expected = days[-1] - days[0] + 1 if days else 0
    return CandidateSeries(
        route="same_venue_mexc_spot_perp",
        symbol=symbol,
        observations=observations,
        settlement_events=funding_events,
        expected_days=expected,
        valid_days=len(days),
        input_files=[
            dataset / "mexc" / "funding" / f"{symbol}.json",
            spot_path,
            dataset / "mexc" / "klines" / f"{symbol}.json",
        ],
        fixed_direction=1,
    )


def _profit_factor(pnls: list[float]) -> tuple[float, bool]:
    gross_profit = sum(value for value in pnls if value > 0.0)
    gross_loss = -sum(value for value in pnls if value < 0.0)
    if gross_loss <= 1e-12:
        return (999_999.0 if gross_profit > 0.0 else 0.0), gross_profit > 0.0
    return gross_profit / gross_loss, False


def _max_drawdown(pnls: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in pnls:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return max_drawdown


def _settlement_pnls(
    events: list[tuple[float, float]],
    *,
    first_day: int,
    last_day: int,
    direction: int,
    notional: float,
    funding_haircut: float,
) -> list[float]:
    first_ts = first_day * DAY_SEC
    last_ts = (last_day + 1) * DAY_SEC
    return [
        direction * rate * funding_haircut * notional
        for ts, rate in events
        if first_ts <= ts < last_ts
    ]


def window_metrics(
    series: CandidateSeries,
    observations: list[dict[str, float]],
    *,
    direction: int,
    profile: CostProfile,
    notional: float,
    stress: bool = False,
) -> dict[str, Any]:
    if len(observations) < 2:
        return {"ok": False, "reason": "insufficient_aligned_days", "aligned_days": len(observations)}
    effective_profile = profile.stress_profile() if stress else profile
    cost = profile.cycle_cost(route_legs(series.route, profile=profile), stress=stress)
    first = observations[0]
    last = observations[-1]
    first_day = int(first["day"])
    last_day = int(last["day"])
    cost_quote = cost["total_bps"] / 1e4 * notional
    daily_pnls: list[float] = []
    previous_basis_pnl = 0.0
    funding_pnl = 0.0
    for index, row in enumerate(observations):
        day_funding = direction * row["funding_diff"] * effective_profile.funding_haircut * notional
        funding_pnl += day_funding
        basis_pnl_to_date = direction * (
            row["leg_a_close"] / first["leg_a_close"] - 1.0
            - (row["leg_b_close"] / first["leg_b_close"] - 1.0)
        ) * notional
        day_basis = basis_pnl_to_date - previous_basis_pnl
        previous_basis_pnl = basis_pnl_to_date
        day_cost = 0.0
        if index == 0:
            day_cost += cost_quote / 2.0
        if index == len(observations) - 1:
            day_cost += cost_quote / 2.0
        daily_pnls.append(day_funding + day_basis - day_cost)
    settlement_pnls = _settlement_pnls(
        series.settlement_events,
        first_day=first_day,
        last_day=last_day,
        direction=direction,
        notional=notional,
        funding_haircut=effective_profile.funding_haircut,
    )
    positive_events = [value for value in settlement_pnls if value > 0.0]
    positive_total = sum(positive_events)
    positive_rate = (
        sum(1 for value in settlement_pnls if value > 0.0) / len(settlement_pnls)
        if settlement_pnls
        else 0.0
    )
    max_event_share = max(positive_events) / positive_total if positive_total > 0.0 else 1.0
    profit_factor, profit_factor_infinite = _profit_factor(daily_pnls)
    basis_pnl = previous_basis_pnl
    net_pnl = sum(daily_pnls)
    expected_days = last_day - first_day + 1
    coverage = len(observations) / expected_days if expected_days > 0 else 0.0
    return {
        "ok": True,
        "start_day": day_iso(first_day),
        "end_day": day_iso(last_day),
        "aligned_days": len(observations),
        "calendar_days": expected_days,
        "dual_leg_coverage": round(coverage, 6),
        "settlement_count": len(settlement_pnls),
        "positive_settlement_rate": round(positive_rate, 6),
        "max_positive_funding_event_share": round(max_event_share, 6),
        "funding_pnl_quote": round(funding_pnl, 8),
        "basis_pnl_quote": round(basis_pnl, 8),
        "fees_spread_impact_slippage_rebalance_quote": round(cost_quote, 8),
        "net_pnl_quote": round(net_pnl, 8),
        "net_expectancy_per_settlement_quote": round(
            net_pnl / len(settlement_pnls) if settlement_pnls else 0.0,
            8,
        ),
        "profit_factor": round(profit_factor, 6),
        "profit_factor_infinite": profit_factor_infinite,
        "max_drawdown_quote": round(_max_drawdown(daily_pnls), 8),
        "cycle_cost": cost,
        "funding_haircut": effective_profile.funding_haircut,
        "daily_pnls_quote": [round(value, 8) for value in daily_pnls],
    }


def walk_forward_metrics(
    series: CandidateSeries,
    *,
    profile: CostProfile,
    notional: float,
    folds: int = 5,
) -> dict[str, Any]:
    rows = series.observations
    initial_train = max(2, len(rows) // 2)
    remaining = len(rows) - initial_train
    if remaining < folds * 2:
        return {
            "ok": False,
            "folds_requested": folds,
            "folds_completed": 0,
            "positive_folds": 0,
            "reason": "insufficient_rows_for_walk_forward",
            "folds": [],
        }
    base_size, extra = divmod(remaining, folds)
    fold_rows: list[dict[str, Any]] = []
    test_start = initial_train
    for fold_index in range(folds):
        test_size = base_size + (1 if fold_index < extra else 0)
        test_end = test_start + test_size
        train = rows[:test_start]
        test = rows[test_start:test_end]
        mean_train_diff = statistics.mean(row["funding_diff"] for row in train)
        direction = series.fixed_direction or (1 if mean_train_diff >= 0.0 else -1)
        metrics = window_metrics(
            series,
            test,
            direction=direction,
            profile=profile,
            notional=notional,
        )
        fold_rows.append(
            {
                "fold": fold_index + 1,
                "train_days": len(train),
                "test_days": len(test),
                "direction": direction,
                "train_mean_funding_diff_bps_per_day": round(mean_train_diff * 1e4, 6),
                "test_net_pnl_quote": metrics.get("net_pnl_quote"),
                "positive": bool(metrics.get("ok") and float(metrics.get("net_pnl_quote") or 0.0) > 0.0),
                "metrics": metrics,
            }
        )
        test_start = test_end
    positive = sum(1 for row in fold_rows if row["positive"])
    return {
        "ok": True,
        "folds_requested": folds,
        "folds_completed": len(fold_rows),
        "positive_folds": positive,
        "positive_fold_ratio": round(positive / len(fold_rows), 6),
        "folds": fold_rows,
    }


def _hash_input_files(files: Iterable[Path], dataset: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in files:
        if path.exists():
            try:
                key = str(path.relative_to(dataset))
            except ValueError:
                key = str(path)
            result[key] = sha256_file(path)
    return result


def evaluate_series(
    series: CandidateSeries,
    *,
    profile: CostProfile,
    notional: float,
    gates: dict[str, Any],
    dataset: Path,
) -> dict[str, Any]:
    rows = series.observations
    if len(rows) < 4:
        return {
            "symbol": series.symbol,
            "route": series.route,
            "status": "INSUFFICIENT_DATA",
            "rejection_reasons": ["insufficient_aligned_history"],
            "aligned_days_total": len(rows),
            "input_hashes": _hash_input_files(series.input_files, dataset),
        }
    split_index = max(2, min(len(rows) - 2, int(len(rows) * 0.70)))
    train = rows[:split_index]
    oos = rows[split_index:]
    mean_train_diff = statistics.mean(row["funding_diff"] for row in train)
    direction = series.fixed_direction or (1 if mean_train_diff >= 0.0 else -1)
    oos_metrics = window_metrics(
        series,
        oos,
        direction=direction,
        profile=profile,
        notional=notional,
    )
    stress_metrics = window_metrics(
        series,
        oos,
        direction=direction,
        profile=profile,
        notional=notional,
        stress=True,
    )
    walk = walk_forward_metrics(series, profile=profile, notional=notional, folds=5)
    train_edge_bps_per_day = direction * mean_train_diff * profile.funding_haircut * 1e4
    cycle_cost_bps = profile.cycle_cost(route_legs(series.route, profile=profile))["total_bps"]
    break_even_days = cycle_cost_bps / train_edge_bps_per_day if train_edge_bps_per_day > 0.0 else None
    reasons: list[str] = []
    if series.fixed_direction == 1 and mean_train_diff <= 0.0:
        reasons.append("train_funding_not_positive_for_fixed_same_venue_route")
    if int(oos_metrics.get("aligned_days") or 0) < gates["min_oos_aligned_days"]:
        reasons.append("oos_aligned_days_below_min")
    if int(oos_metrics.get("settlement_count") or 0) < gates["min_oos_settlements"]:
        reasons.append("oos_settlements_below_min")
    if float(oos_metrics.get("dual_leg_coverage") or 0.0) < gates["min_dual_leg_coverage"]:
        reasons.append("dual_leg_coverage_below_min")
    if float(oos_metrics.get("net_expectancy_per_settlement_quote") or 0.0) <= gates["min_oos_net_expectancy_quote"]:
        reasons.append("oos_net_expectancy_not_positive")
    if float(oos_metrics.get("profit_factor") or 0.0) < gates["min_oos_profit_factor"]:
        reasons.append("oos_profit_factor_below_min")
    if float(oos_metrics.get("positive_settlement_rate") or 0.0) < gates["min_positive_settlement_rate"]:
        reasons.append("positive_settlement_rate_below_min")
    if int(walk.get("positive_folds") or 0) < gates["min_positive_walk_forward_folds"]:
        reasons.append("walk_forward_positive_folds_below_min")
    if float(stress_metrics.get("net_pnl_quote") or 0.0) < gates["min_stress_net_pnl_quote"]:
        reasons.append("stress_net_pnl_negative")
    if break_even_days is None or break_even_days > gates["max_break_even_days"]:
        reasons.append("break_even_holding_period_too_long")
    if float(oos_metrics.get("max_positive_funding_event_share") or 1.0) > gates["max_single_funding_event_share"]:
        reasons.append("single_funding_event_concentration_too_high")
    sample_reasons = {
        "oos_aligned_days_below_min",
        "oos_settlements_below_min",
        "dual_leg_coverage_below_min",
    }
    if not reasons:
        status = "HISTORICAL_PASS_PENDING_EXECUTION"
    elif all(reason in sample_reasons for reason in reasons):
        status = "INSUFFICIENT_DATA"
    else:
        status = "REJECT"
    direction_name = (
        "long_mexc_spot_short_mexc_perp"
        if series.route == "same_venue_mexc_spot_perp"
        else ("long_mexc_perp_short_gate_perp" if direction == 1 else "short_mexc_perp_long_gate_perp")
    )
    return {
        "symbol": series.symbol,
        "route": series.route,
        "status": status,
        "direction": direction_name,
        "direction_sign": direction,
        "selection_is_train_only": True,
        "train": {
            "aligned_days": len(train),
            "start_day": day_iso(int(train[0]["day"])),
            "end_day": day_iso(int(train[-1]["day"])),
            "mean_funding_diff_bps_per_day": round(mean_train_diff * 1e4, 6),
            "expected_edge_bps_per_day": round(train_edge_bps_per_day, 6),
        },
        "oos": oos_metrics,
        "walk_forward": walk,
        "stress": {
            **stress_metrics,
            "execution_price_source": "conservative_defaults_pending_execution_probe_p95",
        },
        "break_even_holding_days": None if break_even_days is None else round(break_even_days, 6),
        "rejection_reasons": reasons,
        "input_hashes": _hash_input_files(series.input_files, dataset),
    }


def evaluate_fixed_branch_evidence(plan: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = plan.get("fixed_branch_evidence") or {}
    order = (plan.get("frozen_config") or {}).get("fallback_policy", {}).get("order") or []
    results: list[dict[str, Any]] = []
    for branch in order:
        source = evidence.get(branch)
        if not source:
            results.append(
                {
                    "branch": branch,
                    "status": "INSUFFICIENT_DATA",
                    "rejection_reasons": ["frozen_fixed_test_artifact_missing"],
                }
            )
            continue
        path = Path(source["path"])
        if not path.exists() or sha256_file(path) != source.get("sha256"):
            results.append(
                {
                    "branch": branch,
                    "status": "INSUFFICIENT_DATA",
                    "source": source,
                    "rejection_reasons": ["frozen_fixed_test_artifact_changed_or_missing"],
                }
            )
            continue
        payload = read_json(path)
        accepted = bool(payload.get("strategy_accepted"))
        research_acceptance = payload.get("research_acceptance") or {}
        reasons = list(research_acceptance.get("reasons") or [])
        if not accepted and not reasons:
            reasons = ["fixed_test_rejected_no_robust_edge"]
        results.append(
            {
                "branch": branch,
                "status": "HISTORICAL_PASS_PENDING_EXECUTION" if accepted else "REJECT",
                "decision": payload.get("decision"),
                "strategy_accepted": accepted,
                "research_only": payload.get("research_only"),
                "grid_search": payload.get("grid_search"),
                "summary": payload.get("summary"),
                "train": payload.get("train"),
                "oos": payload.get("oos"),
                "walk_forward": payload.get("walk_forward"),
                "stress": payload.get("stress"),
                "research_acceptance": research_acceptance,
                "rejection_reasons": reasons,
                "source": source,
                "evaluation_mode": "reuse_frozen_fixed_test_no_rerun_no_retuning",
            }
        )
    return results


def evaluate_plan(
    plan_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    plan = load_plan(plan_path)
    max_runtime = validate_runtime_sec(plan["runtime"]["max_runtime_sec"])
    dataset = Path(plan["dataset"]["path"])
    manifest_path = Path(plan["dataset"]["manifest_path"])
    if sha256_file(manifest_path) != plan["dataset"]["manifest_sha256"]:
        raise ValueError("Dataset manifest changed after plan freeze")
    manifest = read_json(manifest_path)
    shortlist = select_shortlist(
        manifest,
        int(plan["frozen_config"]["universe"]["shortlist_limit"]),
    )
    profile = base_api_cost_profile()
    gates = dict(plan["frozen_config"]["acceptance_gates"])
    notional = float(plan["frozen_config"]["notional_per_leg_quote"])
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(shortlist, start=1):
        if time.monotonic() - started > max_runtime:
            raise TimeoutError(f"fast-edge evaluation exceeded MaxRuntimeSec={max_runtime}")
        symbol = item["symbol"]
        cross = evaluate_series(
            build_cross_venue_series(dataset, symbol),
            profile=profile,
            notional=notional,
            gates=gates,
            dataset=dataset,
        )
        cross["selection"] = item
        candidates.append(cross)
        same_series = build_same_venue_series(dataset, symbol)
        if same_series is None:
            candidates.append(
                {
                    "symbol": symbol,
                    "route": "same_venue_mexc_spot_perp",
                    "status": "INSUFFICIENT_DATA",
                    "selection": item,
                    "rejection_reasons": ["historical_spot_leg_missing"],
                    "required_path": str(dataset / "mexc" / "spot_klines" / f"{symbol}.json"),
                }
            )
        else:
            same = evaluate_series(
                same_series,
                profile=profile,
                notional=notional,
                gates=gates,
                dataset=dataset,
            )
            same["selection"] = item
            candidates.append(same)
        print(f"[{index}/{len(shortlist)}] evaluated {symbol}", flush=True)
    candidates.sort(
        key=lambda row: (
            row.get("status") == "HISTORICAL_PASS_PENDING_EXECUTION",
            float((row.get("oos") or {}).get("net_pnl_quote") or -1e18),
        ),
        reverse=True,
    )
    passed = [row for row in candidates if row.get("status") == "HISTORICAL_PASS_PENDING_EXECUTION"]
    fallback_branches = evaluate_fixed_branch_evidence(plan)
    fallback_passed = [
        row for row in fallback_branches
        if row.get("status") == "HISTORICAL_PASS_PENDING_EXECUTION"
    ]
    missing_fallback = [
        row for row in fallback_branches
        if row.get("status") == "INSUFFICIENT_DATA"
    ]
    if passed or fallback_passed:
        overall_decision = "HISTORICAL_CANDIDATE_FOUND"
    elif missing_fallback:
        overall_decision = "NO_FUNDING_EDGE_FALLBACK_EVIDENCE_INCOMPLETE"
    else:
        overall_decision = "NO_FAST_EDGE_FOUND"
    deterministic = {
        "plan_hash": plan["plan_hash"],
        "dataset_manifest_sha256": plan["dataset"]["manifest_sha256"],
        "shortlist": shortlist,
        "candidates": candidates,
        "fallback_branches": fallback_branches,
    }
    report: dict[str, Any] = {
        "schema": "fast_edge_evaluation_v1",
        "created_at_utc": plan["created_at_utc"],
        "plan_path": str(Path(plan_path).resolve()),
        "plan_hash": plan["plan_hash"],
        "frozen_config": plan["frozen_config"],
        "cost_profile": profile.as_dict(),
        "dataset": plan["dataset"],
        "shortlist": shortlist,
        "candidates": candidates,
        "fallback_branches": fallback_branches,
        "summary": {
            "shortlist_count": len(shortlist),
            "route_evaluations": len(candidates),
            "historical_pass_count": len(passed),
            "fallback_historical_pass_count": len(fallback_passed),
            "fallback_rejected_count": sum(1 for row in fallback_branches if row.get("status") == "REJECT"),
            "fallback_insufficient_data_count": len(missing_fallback),
            "rejected_count": sum(1 for row in candidates if row.get("status") == "REJECT"),
            "insufficient_data_count": sum(1 for row in candidates if row.get("status") == "INSUFFICIENT_DATA"),
            "decision": overall_decision,
        },
        "next_allowed_command": "fast-edge-execution-probe" if (passed or fallback_passed) else "fast-edge-report",
        "runtime_sec": round(time.monotonic() - started, 3),
        "deterministic_result_hash": sha256_json(deterministic),
    }
    destination = Path(output_path) if output_path else _artifact_path("evaluations", "fast_edge_evaluation")
    write_json_atomic(destination, report)
    report["artifact_path"] = str(destination.resolve())
    return report


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def execution_leg_metrics(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    *,
    notional_quote: float = DEFAULT_PROBE_NOTIONAL,
) -> dict[str, Any]:
    stats = book_stats(bids, asks)
    if stats is None:
        return {"ok": False, "reason": "invalid_book"}
    buy_impact = market_impact_bps(asks, side="buy", notional_quote=notional_quote)
    sell_impact = market_impact_bps(bids, side="sell", notional_quote=notional_quote)
    return {
        "ok": buy_impact is not None and sell_impact is not None,
        "mid": stats["mid"],
        "spread_bps": stats["spread_bps"],
        "buy_impact_bps": buy_impact,
        "sell_impact_bps": sell_impact,
        "max_impact_bps": max(buy_impact, sell_impact) if buy_impact is not None and sell_impact is not None else None,
        "capacity_at_10bps_usd": capacity_within_impact_bps(bids, asks, max_impact_bps=10.0),
        "depth": stats["depth"],
    }


def summarize_execution_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("symbol") or ""), str(row.get("route") or ""))
        if all(key):
            by_key.setdefault(key, []).append(row)
    candidates: list[dict[str, Any]] = []
    for (symbol, route), samples in sorted(by_key.items()):
        valid = [row for row in samples if row.get("dual_leg_valid") is True]
        max_impacts = [float(row["max_leg_impact_bps"]) for row in valid if row.get("max_leg_impact_bps") is not None]
        capacities = [float(row["min_leg_capacity_usd"]) for row in valid if row.get("min_leg_capacity_usd") is not None]
        spreads = [float(row["max_leg_spread_bps"]) for row in valid if row.get("max_leg_spread_bps") is not None]
        candidates.append(
            {
                "symbol": symbol,
                "route": route,
                "snapshots": len(samples),
                "valid_dual_leg_snapshots": len(valid),
                "dual_leg_coverage": round(len(valid) / len(samples), 6) if samples else 0.0,
                "p95_impact_bps_at_500": None if not max_impacts else round(_percentile(max_impacts, 0.95) or 0.0, 6),
                "p95_spread_bps": None if not spreads else round(_percentile(spreads, 0.95) or 0.0, 6),
                "p05_capacity_at_10bps_usd": None if not capacities else round(_percentile(capacities, 0.05) or 0.0, 2),
                "errors": sum(len(row.get("errors") or []) for row in samples),
            }
        )
    return {"candidates": candidates, "rows": sum(len(rows) for rows in by_key.values())}


def _new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> Any:
    response = session.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def fetch_contract_sizes(cache_path: Path) -> tuple[dict[str, float], dict[str, float]]:
    if cache_path.exists():
        payload = read_json(cache_path)
        return (
            {str(key): float(value) for key, value in (payload.get("mexc") or {}).items()},
            {str(key): float(value) for key, value in (payload.get("gateio") or {}).items()},
        )
    session = _new_session()
    mexc_payload = _get_json(session, "https://contract.mexc.com/api/v1/contract/detail")
    gate_payload = _get_json(session, "https://api.gateio.ws/api/v4/futures/usdt/contracts")
    mexc = {
        str(item.get("symbol")): float(item.get("contractSize") or 1.0)
        for item in mexc_payload.get("data") or []
    }
    gate = {
        str(item.get("name")): float(item.get("quanto_multiplier") or 1.0)
        for item in gate_payload
    }
    write_json_atomic(
        cache_path,
        {
            "schema": "fast_edge_contract_sizes_v1",
            "created_at_utc": utc_now(),
            "mexc": mexc,
            "gateio": gate,
        },
    )
    return mexc, gate


def fetch_execution_snapshot(
    symbol: str,
    route: str,
    mexc_sizes: dict[str, float],
    gate_sizes: dict[str, float],
    *,
    notional_quote: float = DEFAULT_PROBE_NOTIONAL,
) -> dict[str, Any]:
    session = _new_session()
    errors: list[str] = []
    legs: dict[str, Any] = {}
    try:
        payload = _get_json(
            session,
            f"https://contract.mexc.com/api/v1/contract/depth/{symbol}",
            {"limit": 100},
        )
        bids, asks = normalize_mexc_perp(payload, mexc_sizes.get(symbol, 1.0))
        legs["mexc_perp"] = execution_leg_metrics(bids, asks, notional_quote=notional_quote)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mexc_perp {type(exc).__name__}: {exc}")
    if route == "cross_venue_perp_perp":
        try:
            payload = _get_json(
                session,
                "https://api.gateio.ws/api/v4/futures/usdt/order_book",
                {"contract": symbol, "limit": 100},
            )
            bids, asks = normalize_gate_perp(payload, gate_sizes.get(symbol, 1.0))
            legs["gate_perp"] = execution_leg_metrics(bids, asks, notional_quote=notional_quote)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"gate_perp {type(exc).__name__}: {exc}")
    else:
        try:
            base = symbol.removesuffix("_USDT")
            payload = _get_json(
                session,
                "https://api.mexc.com/api/v3/depth",
                {"symbol": f"{base}USDT", "limit": 100},
            )
            bids, asks = normalize_mexc_spot(payload)
            legs["mexc_spot"] = execution_leg_metrics(bids, asks, notional_quote=notional_quote)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mexc_spot {type(exc).__name__}: {exc}")
    expected_legs = ["mexc_perp", "gate_perp"] if route == "cross_venue_perp_perp" else ["mexc_perp", "mexc_spot"]
    valid = all((legs.get(name) or {}).get("ok") is True for name in expected_legs)
    valid_legs = [legs[name] for name in expected_legs if (legs.get(name) or {}).get("ok") is True]
    return {
        "symbol": symbol,
        "route": route,
        "dual_leg_valid": valid,
        "legs": legs,
        "max_leg_impact_bps": max((float(row["max_impact_bps"]) for row in valid_legs), default=None),
        "max_leg_spread_bps": max((float(row["spread_bps"]) for row in valid_legs), default=None),
        "min_leg_capacity_usd": min((float(row["capacity_at_10bps_usd"]) for row in valid_legs), default=None),
        "errors": errors,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def run_execution_probe(
    plan_path: str | Path,
    evaluation_path: str | Path,
    *,
    output_path: str | Path | None = None,
    duration_sec: int = DEFAULT_PROBE_DURATION_SEC,
    interval_sec: float = DEFAULT_PROBE_INTERVAL_SEC,
    max_runtime_sec: int = DEFAULT_RUNTIME_SEC,
    top_n: int = 10,
    resume: bool = False,
    snapshot_fetcher: Callable[[str, str, dict[str, float], dict[str, float]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    duration = validate_runtime_sec(duration_sec, name="duration_sec")
    runtime = validate_runtime_sec(max_runtime_sec)
    if duration > runtime:
        raise ValueError("duration_sec must be <= max_runtime_sec")
    if interval_sec <= 0.0:
        raise ValueError("interval_sec must be > 0")
    plan = load_plan(plan_path)
    evaluation = read_json(evaluation_path)
    if evaluation.get("plan_hash") != plan["plan_hash"]:
        raise ValueError("Evaluation does not belong to the frozen plan")
    passed = [
        row
        for row in evaluation.get("candidates") or []
        if row.get("status") == "HISTORICAL_PASS_PENDING_EXECUTION"
    ][: max(1, int(top_n))]
    if not passed:
        raise ValueError("No historical candidate is eligible for execution probe")
    destination = Path(output_path) if output_path else _artifact_path("execution", "fast_edge_execution", ".jsonl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = destination.with_suffix(".manifest.json")
    summary_path = destination.with_suffix(".summary.json")
    target_cycles = max(1, int(math.ceil(duration / interval_sec)))
    config = {
        "plan_hash": plan["plan_hash"],
        "evaluation_result_hash": evaluation.get("deterministic_result_hash"),
        "candidates": [{"symbol": row["symbol"], "route": row["route"]} for row in passed],
        "duration_sec": duration,
        "interval_sec": interval_sec,
        "target_cycles": target_cycles,
        "notional_quote": DEFAULT_PROBE_NOTIONAL,
    }
    config_hash = sha256_json(config)
    existing_manifest = read_json(manifest_path) if manifest_path.exists() else None
    if existing_manifest:
        if existing_manifest.get("config_hash") != config_hash:
            raise ValueError("Existing execution probe has a different config hash")
        if existing_manifest.get("final") is True:
            summary = read_json(summary_path)
            summary["cache_hit"] = True
            return summary
        if not resume:
            raise ValueError("Execution probe is STOPPED_INCOMPLETE; use --resume with the same output path")
    existing_rows = _load_jsonl(destination)
    completed_cycles = int((existing_manifest or {}).get("completed_cycles") or 0)
    contract_cache = destination.parent / f"contract_sizes_{plan['cache_key'][:16]}.json"
    mexc_sizes: dict[str, float] = {}
    gate_sizes: dict[str, float] = {}
    fetcher = fetch_execution_snapshot if snapshot_fetcher is None else snapshot_fetcher
    started_utc = (existing_manifest or {}).get("started_at_utc") or utc_now()
    manifest: dict[str, Any] = {
        "schema": "fast_edge_execution_probe_manifest_v1",
        "status": "RUNNING",
        "final": False,
        "started_at_utc": started_utc,
        "updated_at_utc": utc_now(),
        "output_path": str(destination.resolve()),
        "summary_path": str(summary_path.resolve()),
        "config": config,
        "config_hash": config_hash,
        "completed_cycles": completed_cycles,
        "target_cycles": target_cycles,
        "rows": len(existing_rows),
        "errors": sum(len(row.get("errors") or []) for row in existing_rows),
        "resume_supported": True,
    }
    write_json_atomic(manifest_path, manifest)
    started = time.monotonic()
    failure: str | None = None
    try:
        if snapshot_fetcher is None:
            mexc_sizes, gate_sizes = fetch_contract_sizes(contract_cache)
        with destination.open("a", encoding="utf-8") as handle:
            for cycle in range(completed_cycles, target_cycles):
                cycle_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=min(8, len(passed))) as executor:
                    futures = {
                        executor.submit(
                            fetcher,
                            row["symbol"],
                            row["route"],
                            mexc_sizes,
                            gate_sizes,
                        ): row
                        for row in passed
                    }
                    cycle_rows: list[dict[str, Any]] = []
                    for future in as_completed(futures):
                        candidate = futures[future]
                        try:
                            snapshot = future.result()
                        except Exception as exc:  # noqa: BLE001
                            snapshot = {
                                "symbol": candidate["symbol"],
                                "route": candidate["route"],
                                "dual_leg_valid": False,
                                "errors": [f"snapshot {type(exc).__name__}: {exc}"],
                            }
                        snapshot["ts"] = time.time()
                        snapshot["cycle"] = cycle + 1
                        cycle_rows.append(snapshot)
                for row in sorted(cycle_rows, key=lambda value: (value["symbol"], value["route"])):
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                existing_rows.extend(cycle_rows)
                completed_cycles = cycle + 1
                manifest.update(
                    {
                        "updated_at_utc": utc_now(),
                        "completed_cycles": completed_cycles,
                        "rows": len(existing_rows),
                        "errors": sum(len(row.get("errors") or []) for row in existing_rows),
                    }
                )
                write_json_atomic(manifest_path, manifest)
                remaining = max(0, target_cycles - completed_cycles)
                eta_sec = remaining * interval_sec
                print(
                    f"cycle={completed_cycles}/{target_cycles} rows={len(existing_rows)} "
                    f"errors={manifest['errors']} eta_sec={eta_sec:.0f}",
                    flush=True,
                )
                elapsed = time.monotonic() - started
                if elapsed > runtime:
                    raise TimeoutError(f"execution probe exceeded MaxRuntimeSec={runtime}")
                sleep_for = interval_sec - (time.monotonic() - cycle_started)
                if sleep_for > 0.0 and completed_cycles < target_cycles:
                    time.sleep(sleep_for)
    except KeyboardInterrupt:
        failure = "KeyboardInterrupt"
    except Exception as exc:  # noqa: BLE001
        failure = f"{type(exc).__name__}: {exc}"
    final = completed_cycles >= target_cycles and failure is None
    manifest.update(
        {
            "status": "READY_FOR_POSTPROCESS" if final else "STOPPED_INCOMPLETE",
            "final": final,
            "finished_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "completed_cycles": completed_cycles,
            "rows": len(existing_rows),
            "failure": failure,
        }
    )
    write_json_atomic(manifest_path, manifest)
    summary = {
        "schema": "fast_edge_execution_probe_summary_v1",
        "status": manifest["status"],
        "final": final,
        "manifest_path": str(manifest_path.resolve()),
        "output_path": str(destination.resolve()),
        "config": config,
        "config_hash": config_hash,
        "summary": summarize_execution_rows(existing_rows),
        "failure": failure,
        "cache_hit": False,
    }
    write_json_atomic(summary_path, summary)
    if failure:
        print(f"STOPPED_INCOMPLETE: {failure}", file=sys.stderr, flush=True)
    return summary


def build_fast_edge_report(
    plan_path: str | Path,
    evaluation_path: str | Path,
    *,
    execution_probe_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    plan = load_plan(plan_path)
    evaluation = read_json(evaluation_path)
    if evaluation.get("plan_hash") != plan["plan_hash"]:
        raise ValueError("Evaluation does not belong to the frozen plan")
    historical = [
        row
        for row in evaluation.get("candidates") or []
        if row.get("status") == "HISTORICAL_PASS_PENDING_EXECUTION"
    ]
    fallback_branches = evaluation.get("fallback_branches") or []
    fallback_historical = [
        row
        for row in fallback_branches
        if row.get("status") == "HISTORICAL_PASS_PENDING_EXECUTION"
    ]
    probe = read_json(execution_probe_path) if execution_probe_path else None
    probe_final = bool((probe or {}).get("final"))
    probe_by_key = {
        (row["symbol"], row["route"]): row
        for row in ((probe or {}).get("summary") or {}).get("candidates") or []
    }
    gates = plan["frozen_config"]["acceptance_gates"]
    accepted: list[dict[str, Any]] = []
    assessed: list[dict[str, Any]] = []
    for candidate in historical:
        key = (candidate["symbol"], candidate["route"])
        execution = probe_by_key.get(key)
        reasons: list[str] = []
        if probe is not None and not probe_final:
            reasons.append("execution_probe_not_final")
        if execution is None:
            reasons.append("execution_probe_missing")
        else:
            if int(execution.get("valid_dual_leg_snapshots") or 0) < gates["min_execution_snapshots"]:
                reasons.append("execution_snapshots_below_min")
            if float(execution.get("dual_leg_coverage") or 0.0) < gates["min_execution_coverage"]:
                reasons.append("execution_coverage_below_min")
            impact = execution.get("p95_impact_bps_at_500")
            if impact is None or float(impact) > gates["max_p95_impact_bps"]:
                reasons.append("p95_impact_above_max")
            capacity = execution.get("p05_capacity_at_10bps_usd")
            if capacity is None or float(capacity) < gates["min_capacity_usd_per_leg"]:
                reasons.append("capacity_below_min")
        row = {
            "symbol": candidate["symbol"],
            "route": candidate["route"],
            "historical_status": candidate["status"],
            "execution": execution,
            "accepted_for_paper": not reasons,
            "rejection_reasons": reasons,
        }
        assessed.append(row)
        if not reasons:
            accepted.append(row)
    for branch in fallback_historical:
        assessed.append(
            {
                "branch": branch["branch"],
                "historical_status": branch["status"],
                "execution": None,
                "accepted_for_paper": False,
                "rejection_reasons": ["specialized_execution_probe_required"],
            }
        )
    if accepted:
        verdict = "ACCEPT_FOR_PAPER"
        next_command = "paper-forward-segment"
    elif (historical or fallback_historical) and (probe is None or not probe_final):
        verdict = "INSUFFICIENT_DATA"
        next_command = "fast-edge-execution-probe"
    elif historical or fallback_historical:
        verdict = "REJECT"
        next_command = "fast-edge-report"
    else:
        verdict = "REJECT"
        next_command = "fast-edge-report"
    report = {
        "schema": "fast_edge_report_v1",
        "created_at_utc": plan["created_at_utc"],
        "verdict": verdict,
        "research_only": True,
        "plan_hash": plan["plan_hash"],
        "evaluation_result_hash": evaluation.get("deterministic_result_hash"),
        "execution_config_hash": (probe or {}).get("config_hash"),
        "execution_probe_final": probe_final if probe is not None else None,
        "acceptance_gates": gates,
        "historical_candidate_count": len(historical) + len(fallback_historical),
        "paper_candidate_count": len(accepted),
        "candidates": assessed,
        "fallback_branches": fallback_branches,
        "next_allowed_command": next_command,
        "live_review_eligible": False,
        "live_orders_allowed": False,
    }
    report["deterministic_result_hash"] = sha256_json(report)
    destination = Path(output_path) if output_path else _artifact_path("reports", "fast_edge_report")
    write_json_atomic(destination, report)
    report["artifact_path"] = str(destination.resolve())
    return report


def record_paper_segment(
    report_path: str | Path,
    observation_path: str | Path,
    *,
    state_path: str | Path,
) -> dict[str, Any]:
    report = read_json(report_path)
    if report.get("verdict") != "ACCEPT_FOR_PAPER":
        raise ValueError("Paper segment requires an ACCEPT_FOR_PAPER report")
    observation = read_json(observation_path)
    settlement_id = str(observation.get("settlement_id") or "").strip()
    if not settlement_id:
        raise ValueError("Paper observation requires settlement_id")
    destination = Path(state_path)
    state = read_json(destination) if destination.exists() else {
        "schema": "fast_edge_paper_state_v1",
        "created_at_utc": utc_now(),
        "report_hash": report.get("deterministic_result_hash"),
        "observations": [],
    }
    if state.get("report_hash") != report.get("deterministic_result_hash"):
        raise ValueError("Paper state belongs to another fast-edge report")
    if any(str(row.get("settlement_id")) == settlement_id for row in state["observations"]):
        raise ValueError(f"Duplicate settlement_id: {settlement_id}")
    normalized = {
        "settlement_id": settlement_id,
        "ts": observation.get("ts") or utc_now(),
        "symbol": observation.get("symbol"),
        "route": observation.get("route"),
        "net_pnl_quote": float(observation.get("net_pnl_quote") or 0.0),
        "execution_divergence_bps": float(observation.get("execution_divergence_bps") or 0.0),
        "window_duration_sec": float(observation.get("window_duration_sec") or 0.0),
        "kill_switch_breach": bool(observation.get("kill_switch_breach")),
        "data_quality_breach": bool(observation.get("data_quality_breach")),
    }
    state["observations"].append(normalized)
    observations = state["observations"]
    critical = [
        row
        for row in observations
        if row["kill_switch_breach"]
        or row["data_quality_breach"]
        or abs(float(row["execution_divergence_bps"])) > 10.0
    ]
    total_net = sum(float(row["net_pnl_quote"]) for row in observations)
    qualified = [row for row in observations if float(row["window_duration_sec"]) >= 1200.0]
    if len(qualified) >= 15 and total_net > 0.0 and not critical:
        status = "LIVE_REVIEW_ELIGIBLE"
    elif len(qualified) >= 3 and total_net > 0.0 and not critical:
        status = "PAPER_READY"
    else:
        status = "PAPER_COLLECTING"
    state.update(
        {
            "updated_at_utc": utc_now(),
            "status": status,
            "settlement_observations": len(observations),
            "qualified_20m_settlement_windows": len(qualified),
            "net_pnl_quote": round(total_net, 8),
            "critical_breaches": len(critical),
            "live_orders_allowed": False,
        }
    )
    write_json_atomic(destination, state)
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fast-First funding/basis edge lab (research-only)")
    subparsers = parser.add_subparsers(dest="action", required=True)

    plan_parser = subparsers.add_parser("fast-edge-plan")
    plan_parser.add_argument("--dataset", required=True)
    plan_parser.add_argument("--output")
    plan_parser.add_argument("--max-runtime-sec", type=int, default=DEFAULT_RUNTIME_SEC)
    plan_parser.add_argument("--shortlist-limit", type=int, default=DEFAULT_SHORTLIST_LIMIT)
    plan_parser.add_argument("--notional-per-leg", type=float, default=DEFAULT_NOTIONAL_PER_LEG)

    evaluate_parser = subparsers.add_parser("fast-edge-evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--output")

    probe_parser = subparsers.add_parser("fast-edge-execution-probe")
    probe_parser.add_argument("--plan", required=True)
    probe_parser.add_argument("--evaluation", required=True)
    probe_parser.add_argument("--output")
    probe_parser.add_argument("--duration-sec", type=int, default=DEFAULT_PROBE_DURATION_SEC)
    probe_parser.add_argument("--interval-sec", type=float, default=DEFAULT_PROBE_INTERVAL_SEC)
    probe_parser.add_argument("--max-runtime-sec", type=int, default=DEFAULT_RUNTIME_SEC)
    probe_parser.add_argument("--top-n", type=int, default=10)
    probe_parser.add_argument("--resume", action="store_true")

    report_parser = subparsers.add_parser("fast-edge-report")
    report_parser.add_argument("--plan", required=True)
    report_parser.add_argument("--evaluation", required=True)
    report_parser.add_argument("--execution-probe")
    report_parser.add_argument("--output")

    paper_parser = subparsers.add_parser("paper-forward-segment")
    paper_parser.add_argument("--report", required=True)
    paper_parser.add_argument("--observation", required=True)
    paper_parser.add_argument("--state", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    if args.action == "fast-edge-plan":
        result = create_plan(
            args.dataset,
            output_path=args.output,
            max_runtime_sec=args.max_runtime_sec,
            shortlist_limit=args.shortlist_limit,
            notional_per_leg=args.notional_per_leg,
        )
        print(f"FROZEN plan={result['artifact_path']} hash={result['plan_hash']}")
        return 0
    if args.action == "fast-edge-evaluate":
        result = evaluate_plan(args.plan, output_path=args.output)
        print(
            f"{result['summary']['decision']} historical_pass={result['summary']['historical_pass_count']} "
            f"artifact={result['artifact_path']}"
        )
        return 0
    if args.action == "fast-edge-execution-probe":
        result = run_execution_probe(
            args.plan,
            args.evaluation,
            output_path=args.output,
            duration_sec=args.duration_sec,
            interval_sec=args.interval_sec,
            max_runtime_sec=args.max_runtime_sec,
            top_n=args.top_n,
            resume=args.resume,
        )
        print(f"{result['status']} summary={result['manifest_path']}")
        return 0 if result["final"] else 2
    if args.action == "fast-edge-report":
        result = build_fast_edge_report(
            args.plan,
            args.evaluation,
            execution_probe_path=args.execution_probe,
            output_path=args.output,
        )
        print(f"{result['verdict']} artifact={result['artifact_path']}")
        return 0
    if args.action == "paper-forward-segment":
        result = record_paper_segment(
            args.report,
            args.observation,
            state_path=args.state,
        )
        print(
            f"{result['status']} observations={result['settlement_observations']} "
            f"net={result['net_pnl_quote']} state={Path(args.state).resolve()}"
        )
        return 0
    raise AssertionError(f"Unhandled action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
