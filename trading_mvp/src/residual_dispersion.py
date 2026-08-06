from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as datetime_time, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from costs import RouteLeg, base_api_cost_profile


PLAN_SCHEMA = "fast_first_residual_dispersion_plan_v1"
VERDICTS = ("ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA")
MAX_RUN_RUNTIME_SEC = 28_800
MAX_NETWORK_PROBE_SEC = 1_200


@dataclass(frozen=True)
class Bar:
    day: int
    ts: int
    open: float
    close: float
    quote_volume: float


@dataclass
class MarketSeries:
    exchange: str
    symbol: str
    base: str
    bars: dict[int, Bar] = field(default_factory=dict)
    funding: list[tuple[int, float]] = field(default_factory=list)


@dataclass(frozen=True)
class Signal:
    exchange: str
    signal_day: int
    entry_day: int
    long_symbol: str
    long_base: str
    short_symbol: str
    short_base: str
    long_residual: float
    short_residual: float
    residual_gap_bps: float
    dispersion: float
    trailing_dispersion: float
    eligible_markets: int
    long_trailing_quote_volume: float
    short_trailing_quote_volume: float


@dataclass(frozen=True)
class Event:
    exchange: str
    signal_day: int
    entry_day: int
    long_symbol: str
    long_base: str
    short_symbol: str
    short_base: str
    price_pnl_quote: float
    funding_pnl_quote: float
    stress_funding_pnl_quote: float
    normal_cost_quote: float
    stress_cost_quote: float
    price_only_net_pnl_quote: float
    normal_net_pnl_quote: float
    stress_net_pnl_quote: float
    capacity_proxy_quote: float
    long_contribution_quote: float
    short_contribution_quote: float


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_positive_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a positive number")
    return number


def _inclusive_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"Unsupported plan schema: {plan.get('schema')!r}")
    if canonical_plan_hash(plan) != plan.get("plan_hash"):
        raise ValueError("Plan hash mismatch; frozen configuration was modified")
    if plan.get("mode") != "PLAN_ONLY":
        raise ValueError("Frozen plan must use PLAN_ONLY mode")
    for name in ("research_only", "frozen_parameters_no_grid"):
        if plan.get(name) is not True:
            raise ValueError(f"{name} must be true")
    for name in (
        "strategy_accepted",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        if plan.get(name) is not False:
            if name == "execution_probe_allowed":
                raise ValueError("PlanOnly cannot authorize an execution probe")
            raise ValueError(f"{name} must be false in PlanOnly")

    hypothesis = plan.get("hypothesis") or {}
    if hypothesis.get("id") != "venue_local_perp_residual_dispersion_reversion_v1":
        raise ValueError("Unexpected frozen hypothesis id")
    signal = plan.get("signal") or {}
    if signal.get("venues") != ["mexc", "gateio"]:
        raise ValueError("Frozen evaluator requires mexc and gateio venue replication")
    if signal.get("entry") != "next_daily_open" or signal.get("exit") != "same_daily_close":
        raise ValueError("Unsupported entry or exit timing")
    if int(signal.get("hold_days") or 0) != 1:
        raise ValueError("Frozen evaluator requires a one-day hold")
    if signal.get("parameter_selection_on_train") is not False or signal.get("parameter_selection_on_oos") is not False:
        raise ValueError("Parameter selection is forbidden")
    for name in (
        "beta_lookback_days",
        "dispersion_history_days",
        "min_dispersion_ratio_to_trailing_median",
        "min_residual_tail_gap_bps",
    ):
        _require_positive_number(signal.get(name), f"signal.{name}")

    eligibility = plan.get("eligibility") or {}
    for name in (
        "minimum_prior_history_days",
        "liquidity_lookback_days",
        "minimum_trailing_median_quote_volume",
        "minimum_eligible_markets_per_venue",
        "minimum_finite_beta_observations",
    ):
        _require_positive_number(eligibility.get(name), f"eligibility.{name}")
    if eligibility.get("non_binance_baseline_required") is not True:
        raise ValueError("Non-Binance universe is mandatory")

    economics = plan.get("economics") or {}
    _require_positive_number(economics.get("notional_quote_per_leg"), "economics.notional_quote_per_leg")
    cost_profile = base_api_cost_profile()
    if economics.get("cost_profile") != cost_profile.as_dict():
        raise ValueError("Frozen CostProfile does not match the unified base_api cost model")
    funding = economics.get("funding_treatment") or {}
    if funding.get("signal_use") != "forbidden":
        raise ValueError("Funding cannot be used as a signal")
    if funding.get("price_only_net_after_cost_must_be_positive") is not True:
        raise ValueError("Price-only net-after-cost gate is mandatory")
    for exchange in signal["venues"]:
        venue_costs = (economics.get("same_venue_two_perp_leg_cycle_costs") or {}).get(exchange) or {}
        expected_legs = [RouteLeg(exchange, "perp"), RouteLeg(exchange, "perp")]
        expected_costs = {
            "normal": cost_profile.cycle_cost(expected_legs),
            "stress": cost_profile.cycle_cost(expected_legs, stress=True),
        }
        if venue_costs != expected_costs:
            raise ValueError(f"{exchange} frozen cycle costs do not match the unified CostProfile")
        normal = _require_positive_number((venue_costs.get("normal") or {}).get("total_bps"), f"{exchange}.normal_cost")
        stress = _require_positive_number((venue_costs.get("stress") or {}).get("total_bps"), f"{exchange}.stress_cost")
        if stress <= normal:
            raise ValueError(f"{exchange} stress cost must exceed normal cost")

    validation = plan.get("validation") or {}
    if tuple(validation.get("verdicts") or ()) != VERDICTS:
        raise ValueError("Verdict set does not match the frozen contract")
    if validation.get("acceptance_ceiling") != VERDICTS[0]:
        raise ValueError("Acceptance ceiling must remain a short execution probe")
    split = validation.get("chronological_split") or {}
    train = split.get("train") or {}
    oos = split.get("oos") or {}
    for name, window in (("train", train), ("oos", oos)):
        observed = _inclusive_days(str(window.get("start")), str(window.get("end")))
        if observed != int(window.get("calendar_days") or 0):
            raise ValueError(f"{name} calendar_days mismatch")
    if date.fromisoformat(str(train["end"])) >= date.fromisoformat(str(oos["start"])):
        raise ValueError("Train/OOS windows overlap")
    folds = (validation.get("walk_forward") or {}).get("folds") or []
    if len(folds) != 5:
        raise ValueError("Exactly five walk-forward folds are required")
    previous_end: date | None = None
    for expected_fold, fold in enumerate(folds, start=1):
        if int(fold.get("fold") or 0) != expected_fold:
            raise ValueError("Walk-forward fold numbering mismatch")
        start = date.fromisoformat(str(fold["test_start"]))
        end = date.fromisoformat(str(fold["test_end"]))
        if end < start or (previous_end is not None and start <= previous_end):
            raise ValueError("Walk-forward folds must be chronological and non-overlapping")
        previous_end = end

    runtime = plan.get("runtime_policy") or {}
    evaluation_sec = int(_require_positive_number(runtime.get("evaluation_max_runtime_sec"), "evaluation_max_runtime_sec"))
    network_sec = int(_require_positive_number(runtime.get("network_probe_max_runtime_sec"), "network_probe_max_runtime_sec"))
    absolute_sec = int(_require_positive_number(runtime.get("absolute_run_max_runtime_sec"), "absolute_run_max_runtime_sec"))
    if absolute_sec > MAX_RUN_RUNTIME_SEC or evaluation_sec > absolute_sec:
        raise ValueError(f"Evaluation runtime must not exceed {MAX_RUN_RUNTIME_SEC} seconds")
    if network_sec > MAX_NETWORK_PROBE_SEC:
        raise ValueError(f"Network probe runtime must not exceed {MAX_NETWORK_PROBE_SEC} seconds")
    if runtime.get("visible_terminal_required_for_evaluation_or_probe") is not True:
        raise ValueError("Visible terminal is mandatory")

    sealed = plan.get("sealed_input") or {}
    source_files = sealed.get("source_files") or []
    if not source_files or len(source_files) != int(sealed.get("source_file_count") or 0):
        raise ValueError("Sealed source file inventory is empty or inconsistent")
    if "manifest.json" not in {str(item.get("relative_path")) for item in source_files}:
        raise ValueError("Sealed dataset manifest.json is required")


def _market_return(market: MarketSeries, day: int) -> float | None:
    current = market.bars.get(day)
    previous = market.bars.get(day - 1)
    if current is None or previous is None or current.close <= 0.0 or previous.close <= 0.0:
        return None
    return math.log(current.close / previous.close)


def _trailing_quote_volume(market: MarketSeries, day: int, window: int) -> float | None:
    values: list[float] = []
    for observed_day in range(day - window + 1, day + 1):
        bar = market.bars.get(observed_day)
        if bar is None or not math.isfinite(bar.quote_volume) or bar.quote_volume < 0.0:
            return None
        values.append(bar.quote_volume)
    return statistics.median(values) if len(values) == window else None


def _prior_bar_count(market: MarketSeries, day: int) -> int:
    return sum(observed_day < day for observed_day in market.bars)


def _base_eligible(
    market: MarketSeries,
    day: int,
    *,
    minimum_history: int,
    liquidity_window: int,
    minimum_quote_volume: float,
) -> tuple[float, float] | None:
    if _prior_bar_count(market, day) < minimum_history:
        return None
    market_return = _market_return(market, day)
    if market_return is None or not math.isfinite(market_return):
        return None
    quote_volume = _trailing_quote_volume(market, day, liquidity_window)
    if quote_volume is None or quote_volume < minimum_quote_volume:
        return None
    return market_return, quote_volume


def _ols_with_intercept(x: list[float], y: list[float]) -> tuple[float, float]:
    if len(x) != len(y) or not x:
        raise ValueError("OLS inputs must have equal non-zero length")
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)
    denominator = sum((value - mean_x) ** 2 for value in x)
    if denominator <= 1e-24:
        return mean_y, 0.0
    beta = sum((left - mean_x) * (right - mean_y) for left, right in zip(x, y)) / denominator
    return mean_y - beta * mean_x, beta


def _scaled_mad(values: list[float]) -> float:
    center = statistics.median(values)
    return 1.4826 * statistics.median(abs(value - center) for value in values)


def build_venue_signals(
    plan: dict[str, Any],
    markets: list[MarketSeries],
    exchange: str,
) -> tuple[list[Signal], dict[str, Any]]:
    signal_cfg = plan["signal"]
    eligibility = plan["eligibility"]
    beta_window = int(signal_cfg["beta_lookback_days"])
    dispersion_window = int(signal_cfg["dispersion_history_days"])
    minimum_history = int(eligibility["minimum_prior_history_days"])
    liquidity_window = int(eligibility["liquidity_lookback_days"])
    minimum_quote_volume = float(eligibility["minimum_trailing_median_quote_volume"])
    minimum_markets = int(eligibility["minimum_eligible_markets_per_venue"])
    minimum_beta = int(eligibility["minimum_finite_beta_observations"])
    dispersion_ratio = float(signal_cfg["min_dispersion_ratio_to_trailing_median"])
    minimum_gap = float(signal_cfg["min_residual_tail_gap_bps"])
    require_opposite = bool(signal_cfg.get("require_opposite_tail_signs", True))

    venue_markets = sorted(
        [market for market in markets if market.exchange == exchange],
        key=lambda market: (market.base, market.symbol),
    )
    all_days = sorted({day for market in venue_markets for day in market.bars})
    eligible_by_day: dict[int, dict[str, tuple[float, float]]] = {}
    benchmark_by_day: dict[int, float] = {}
    for day in all_days:
        rows: dict[str, tuple[float, float]] = {}
        for market in venue_markets:
            candidate = _base_eligible(
                market,
                day,
                minimum_history=minimum_history,
                liquidity_window=liquidity_window,
                minimum_quote_volume=minimum_quote_volume,
            )
            if candidate is not None:
                rows[market.symbol] = candidate
        eligible_by_day[day] = rows
        if len(rows) >= minimum_markets:
            benchmark_by_day[day] = statistics.median(value[0] for value in rows.values())

    dispersion_by_day: dict[int, float] = {}
    residuals_by_day: dict[int, dict[str, float]] = {}
    quote_volume_by_day: dict[int, dict[str, float]] = {}
    skipped = {
        "insufficient_eligible_markets": 0,
        "insufficient_beta_history": 0,
        "insufficient_dispersion_history": 0,
        "dispersion_regime_not_met": 0,
        "tail_gap_not_met": 0,
        "missing_entry_bar": 0,
    }
    signals: list[Signal] = []
    markets_by_symbol = {market.symbol: market for market in venue_markets}

    for day in all_days:
        current_rows = eligible_by_day.get(day) or {}
        if len(current_rows) < minimum_markets or day not in benchmark_by_day:
            skipped["insufficient_eligible_markets"] += 1
            continue
        historical_days = list(range(day - beta_window, day))
        if any(history_day not in benchmark_by_day for history_day in historical_days):
            skipped["insufficient_beta_history"] += 1
            continue
        x = [benchmark_by_day[history_day] for history_day in historical_days]
        residuals: dict[str, float] = {}
        qvolumes: dict[str, float] = {}
        current_benchmark = benchmark_by_day[day]
        for symbol, (current_return, quote_volume) in current_rows.items():
            market = markets_by_symbol[symbol]
            y_values = [_market_return(market, history_day) for history_day in historical_days]
            finite = [value for value in y_values if value is not None and math.isfinite(value)]
            if len(finite) < minimum_beta or len(finite) != len(historical_days):
                continue
            alpha, beta = _ols_with_intercept(x, [float(value) for value in y_values if value is not None])
            residuals[symbol] = current_return - (alpha + beta * current_benchmark)
            qvolumes[symbol] = quote_volume
        if len(residuals) < minimum_markets:
            skipped["insufficient_beta_history"] += 1
            continue
        dispersion = _scaled_mad(list(residuals.values()))
        residuals_by_day[day] = residuals
        quote_volume_by_day[day] = qvolumes
        dispersion_by_day[day] = dispersion

        prior_dispersion_days = list(range(day - dispersion_window, day))
        if any(history_day not in dispersion_by_day for history_day in prior_dispersion_days):
            skipped["insufficient_dispersion_history"] += 1
            continue
        trailing_dispersion = statistics.median(dispersion_by_day[history_day] for history_day in prior_dispersion_days)
        regime_met = dispersion > 0.0 and (
            (trailing_dispersion == 0.0) or dispersion >= dispersion_ratio * trailing_dispersion
        )
        if not regime_met:
            skipped["dispersion_regime_not_met"] += 1
            continue
        ordered = sorted(residuals.items(), key=lambda item: (item[1], item[0]))
        long_symbol, long_residual = ordered[0]
        short_symbol, short_residual = ordered[-1]
        gap_bps = (short_residual - long_residual) * 10_000.0
        if gap_bps < minimum_gap or (require_opposite and not (long_residual < 0.0 < short_residual)):
            skipped["tail_gap_not_met"] += 1
            continue
        entry_day = day + 1
        long_market = markets_by_symbol[long_symbol]
        short_market = markets_by_symbol[short_symbol]
        if entry_day not in long_market.bars or entry_day not in short_market.bars:
            skipped["missing_entry_bar"] += 1
            continue
        signals.append(
            Signal(
                exchange=exchange,
                signal_day=day,
                entry_day=entry_day,
                long_symbol=long_symbol,
                long_base=long_market.base,
                short_symbol=short_symbol,
                short_base=short_market.base,
                long_residual=long_residual,
                short_residual=short_residual,
                residual_gap_bps=gap_bps,
                dispersion=dispersion,
                trailing_dispersion=trailing_dispersion,
                eligible_markets=len(residuals),
                long_trailing_quote_volume=qvolumes[long_symbol],
                short_trailing_quote_volume=qvolumes[short_symbol],
            )
        )
    return signals, {
        "exchange": exchange,
        "market_count": len(venue_markets),
        "calendar_days": len(all_days),
        "signal_count": len(signals),
        "skipped": skipped,
    }


def _funding_sum(market: MarketSeries, entry_ts: int, exit_ts: int) -> float:
    return sum(rate for ts, rate in market.funding if entry_ts < ts <= exit_ts)


def simulate_signal(
    plan: dict[str, Any],
    signal: Signal,
    markets_by_symbol: dict[str, MarketSeries],
) -> Event:
    notional = float(plan["economics"]["notional_quote_per_leg"])
    long_market = markets_by_symbol[signal.long_symbol]
    short_market = markets_by_symbol[signal.short_symbol]
    long_bar = long_market.bars.get(signal.entry_day)
    short_bar = short_market.bars.get(signal.entry_day)
    if long_bar is None or short_bar is None:
        raise ValueError("Entry bar missing for a selected signal leg")
    if min(long_bar.open, long_bar.close, short_bar.open, short_bar.close) <= 0.0:
        raise ValueError("Execution prices must be positive")
    long_return = long_bar.close / long_bar.open - 1.0
    short_return = short_bar.close / short_bar.open - 1.0
    long_price = notional * long_return
    short_price = -notional * short_return
    price_pnl = long_price + short_price
    exit_ts = max(long_bar.ts, short_bar.ts) + 86_400
    long_funding = -notional * _funding_sum(long_market, long_bar.ts, exit_ts)
    short_funding = notional * _funding_sum(short_market, short_bar.ts, exit_ts)
    funding_pnl = long_funding + short_funding
    stress_funding = funding_pnl if funding_pnl <= 0.0 else funding_pnl * 0.5
    costs = plan["economics"]["same_venue_two_perp_leg_cycle_costs"][signal.exchange]
    normal_cost = notional * float(costs["normal"]["total_bps"]) / 10_000.0
    stress_cost = notional * float(costs["stress"]["total_bps"]) / 10_000.0
    long_contribution = long_price + long_funding - normal_cost / 2.0
    short_contribution = short_price + short_funding - normal_cost / 2.0
    return Event(
        exchange=signal.exchange,
        signal_day=signal.signal_day,
        entry_day=signal.entry_day,
        long_symbol=signal.long_symbol,
        long_base=signal.long_base,
        short_symbol=signal.short_symbol,
        short_base=signal.short_base,
        price_pnl_quote=price_pnl,
        funding_pnl_quote=funding_pnl,
        stress_funding_pnl_quote=stress_funding,
        normal_cost_quote=normal_cost,
        stress_cost_quote=stress_cost,
        price_only_net_pnl_quote=price_pnl - normal_cost,
        normal_net_pnl_quote=price_pnl + funding_pnl - normal_cost,
        stress_net_pnl_quote=price_pnl + stress_funding - stress_cost,
        capacity_proxy_quote=0.0001 * min(
            signal.long_trailing_quote_volume,
            signal.short_trailing_quote_volume,
        ),
        long_contribution_quote=long_contribution,
        short_contribution_quote=short_contribution,
    )


def _metric_number(container: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = container.get(key, default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def decide_verdict(plan: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    gates = plan["validation"]["acceptance_gates"]
    data = metrics.get("data") or {}
    oos = metrics.get("oos") or {}
    walk = metrics.get("walk_forward") or {}
    by_venue = oos.get("by_venue") or {}
    gate_results: dict[str, dict[str, Any]] = {}
    insufficient: list[str] = []

    def record(name: str, observed: Any, required: Any, passed: bool) -> None:
        gate_results[name] = {
            "observed": observed,
            "required": required,
            "passed": bool(passed),
        }

    hashes_match = data.get("input_hashes_match") is True
    record("input_hashes_match", hashes_match, True, hashes_match)
    if not hashes_match:
        insufficient.append("sealed_input_hash_mismatch_or_missing")

    calendar_days = int(_metric_number(data, "oos_calendar_days"))
    minimum_days = int(gates["minimum_oos_calendar_days"])
    record("minimum_oos_calendar_days", calendar_days, minimum_days, calendar_days >= minimum_days)
    if calendar_days < minimum_days:
        insufficient.append("oos_calendar_days_below_minimum")

    event_count = int(_metric_number(oos, "event_count"))
    minimum_events = int(gates["minimum_oos_pair_events_total"])
    record("minimum_oos_pair_events_total", event_count, minimum_events, event_count >= minimum_events)
    if event_count < minimum_events:
        insufficient.append("oos_pair_events_total_below_minimum")

    minimum_per_venue = int(gates["minimum_oos_pair_events_per_venue"])
    for exchange in plan["signal"]["venues"]:
        venue_events = int(_metric_number(by_venue.get(exchange) or {}, "event_count"))
        record(
            f"minimum_oos_pair_events:{exchange}",
            venue_events,
            minimum_per_venue,
            venue_events >= minimum_per_venue,
        )
        if venue_events < minimum_per_venue:
            insufficient.append(f"oos_pair_events_below_minimum:{exchange}")

    capacity_value = oos.get("minimum_capacity_proxy_quote")
    capacity_available = capacity_value is not None and math.isfinite(_metric_number(oos, "minimum_capacity_proxy_quote", float("nan")))
    record("capacity_proxy_available", capacity_available, True, capacity_available)
    if not capacity_available:
        insufficient.append("capacity_proxy_unavailable")

    if insufficient:
        return {
            "verdict": "INSUFFICIENT_DATA",
            "reasons": insufficient,
            "gate_results": gate_results,
        }

    rejection_reasons: list[str] = []

    expectancy = _metric_number(oos, "net_expectancy_quote")
    minimum_expectancy = float(gates["oos_net_expectancy_quote_gt"])
    passed = expectancy > minimum_expectancy
    record("oos_net_expectancy_quote", expectancy, f"> {minimum_expectancy}", passed)
    if not passed:
        rejection_reasons.append("oos_net_expectancy_not_positive")

    profit_factor = _metric_number(oos, "profit_factor")
    minimum_pf = float(gates["oos_profit_factor_gte"])
    passed = profit_factor >= minimum_pf
    record("oos_profit_factor", profit_factor, f">= {minimum_pf}", passed)
    if not passed:
        rejection_reasons.append("oos_profit_factor_below_minimum")

    positive_rate = _metric_number(oos, "positive_event_rate")
    minimum_positive_rate = float(gates["oos_positive_event_rate_gte"])
    passed = positive_rate >= minimum_positive_rate
    record("oos_positive_event_rate", positive_rate, f">= {minimum_positive_rate}", passed)
    if not passed:
        rejection_reasons.append("oos_positive_event_rate_below_minimum")

    positive_folds = int(_metric_number(walk, "positive_folds"))
    minimum_folds = int(gates["minimum_positive_walk_forward_folds"])
    passed = positive_folds >= minimum_folds
    record("positive_walk_forward_folds", positive_folds, f">= {minimum_folds}", passed)
    if not passed:
        rejection_reasons.append("positive_walk_forward_folds_below_minimum")

    stress_net = _metric_number(oos, "stress_net_pnl_quote")
    minimum_stress = float(gates["stress_net_pnl_quote_gte"])
    passed = stress_net >= minimum_stress
    record("stress_net_pnl_quote", stress_net, f">= {minimum_stress}", passed)
    if not passed:
        rejection_reasons.append("stress_net_pnl_negative")

    if gates.get("both_venues_oos_net_expectancy_positive"):
        for exchange in plan["signal"]["venues"]:
            venue_expectancy = _metric_number(by_venue.get(exchange) or {}, "net_expectancy_quote")
            passed = venue_expectancy > 0.0
            record(f"venue_oos_expectancy:{exchange}", venue_expectancy, "> 0", passed)
            if not passed:
                rejection_reasons.append(f"venue_oos_expectancy_not_positive:{exchange}")

    price_only_net = _metric_number(oos, "price_only_net_pnl_quote")
    passed = price_only_net > 0.0
    record("price_only_oos_net_after_cost", price_only_net, "> 0", passed)
    if gates.get("price_only_oos_net_after_cost_positive") and not passed:
        rejection_reasons.append("price_only_oos_net_after_cost_not_positive")

    concentration_checks = (
        ("max_single_event_positive_pnl_share", "maximum_single_event_positive_pnl_share", "single_event_positive_pnl_concentration_above_maximum"),
        ("max_single_base_positive_pnl_share", "maximum_single_base_positive_pnl_share", "single_base_positive_pnl_concentration_above_maximum"),
        ("max_single_venue_positive_pnl_share", "maximum_single_venue_positive_pnl_share", "single_venue_positive_pnl_concentration_above_maximum"),
    )
    for metric_name, gate_name, reason in concentration_checks:
        observed = _metric_number(oos, metric_name, 1.0)
        maximum = float(gates[gate_name])
        passed = observed <= maximum
        record(metric_name, observed, f"<= {maximum}", passed)
        if not passed:
            rejection_reasons.append(reason)

    funding_share = _metric_number(oos, "absolute_funding_share_of_positive_pnl", 1.0)
    maximum_funding_share = float(
        plan["economics"]["funding_treatment"]["max_absolute_funding_share_of_positive_oos_pnl"]
    )
    passed = funding_share <= maximum_funding_share
    record("absolute_funding_share_of_positive_pnl", funding_share, f"<= {maximum_funding_share}", passed)
    if not passed:
        rejection_reasons.append("funding_share_above_maximum")

    break_even = oos.get("break_even_holding_days")
    maximum_break_even = float(gates["maximum_break_even_holding_days"])
    passed = break_even is not None and _metric_number(oos, "break_even_holding_days", float("inf")) <= maximum_break_even
    record("break_even_holding_days", break_even, f"<= {maximum_break_even}", passed)
    if not passed:
        rejection_reasons.append("break_even_holding_period_too_long")

    capacity = _metric_number(oos, "minimum_capacity_proxy_quote")
    minimum_capacity = float(gates["minimum_capacity_proxy_quote_per_leg"])
    passed = capacity >= minimum_capacity
    record("minimum_capacity_proxy_quote", capacity, f">= {minimum_capacity}", passed)
    if not passed:
        rejection_reasons.append("capacity_proxy_below_minimum")

    return {
        "verdict": "REJECT" if rejection_reasons else "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        "reasons": rejection_reasons,
        "gate_results": gate_results,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _day_from_iso(value: str) -> int:
    timestamp = datetime.combine(date.fromisoformat(value), datetime_time.min, tzinfo=timezone.utc).timestamp()
    return int(timestamp // 86_400)


def _verify_sealed_input(plan: dict[str, Any]) -> dict[str, Any]:
    sealed = plan["sealed_input"]
    root = Path(sealed["dataset_root"])
    rows = sorted(sealed["source_files"], key=lambda row: str(row["relative_path"]))
    aggregate = hashlib.sha256()
    mismatches: list[dict[str, Any]] = []
    observed_files = 0
    for row in rows:
        relative = str(row["relative_path"])
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            mismatches.append({"relative_path": relative, "reason": "missing"})
            continue
        observed_files += 1
        observed = _sha256_file(path)
        expected = str(row.get("sha256") or "").lower()
        if observed.lower() != expected:
            mismatches.append(
                {
                    "relative_path": relative,
                    "reason": "sha256_mismatch",
                    "expected": expected,
                    "observed": observed,
                }
            )
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(observed.encode("ascii"))
        aggregate.update(b"\n")
    expected_merkle = str(sealed.get("input_merkle_sha256") or "").lower()
    observed_merkle = aggregate.hexdigest()
    if observed_merkle != expected_merkle:
        mismatches.append(
            {
                "relative_path": None,
                "reason": "input_merkle_mismatch",
                "expected": expected_merkle,
                "observed": observed_merkle,
            }
        )
    return {
        "input_hashes_match": not mismatches,
        "expected_source_file_count": int(sealed["source_file_count"]),
        "observed_source_file_count": observed_files,
        "expected_input_merkle_sha256": expected_merkle,
        "observed_input_merkle_sha256": observed_merkle,
        "mismatches": mismatches,
    }


def _parse_market(
    root: Path,
    item: dict[str, Any],
    last_closed_day: int,
) -> tuple[MarketSeries, dict[str, int]]:
    exchange = str(item["exchange"])
    symbol = str(item["symbol"])
    base = str(item["base"]).upper()
    kline_path = root / exchange / "klines" / f"{symbol}.json"
    funding_path = root / exchange / "funding" / f"{symbol}.json"
    kline_payload = json.loads(kline_path.read_text(encoding="utf-8-sig"))
    funding_payload = json.loads(funding_path.read_text(encoding="utf-8-sig"))
    bars: dict[int, Bar] = {}
    invalid_bars = 0
    duplicate_bars = 0
    excluded_incomplete_bars = 0
    for row in kline_payload.get("rows") or []:
        try:
            ts = int(float(row["ts"]))
            day = ts // 86_400
            open_price = float(row["open"])
            close = float(row["close"])
            quote_volume = float(row["volume_quote"])
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_bars += 1
            continue
        if not all(math.isfinite(value) for value in (open_price, close, quote_volume)):
            invalid_bars += 1
            continue
        if open_price <= 0.0 or close <= 0.0 or quote_volume < 0.0:
            invalid_bars += 1
            continue
        if day > last_closed_day:
            excluded_incomplete_bars += 1
            continue
        if day in bars:
            duplicate_bars += 1
            continue
        bars[day] = Bar(day=day, ts=ts, open=open_price, close=close, quote_volume=quote_volume)
    funding: list[tuple[int, float]] = []
    invalid_funding = 0
    for row in funding_payload.get("rows") or []:
        try:
            ts = int(float(row["ts"]))
            rate = float(row["funding_rate"])
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_funding += 1
            continue
        if not math.isfinite(rate):
            invalid_funding += 1
            continue
        funding.append((ts, rate))
    funding.sort()
    return MarketSeries(exchange=exchange, symbol=symbol, base=base, bars=bars, funding=funding), {
        "invalid_bars": invalid_bars,
        "duplicate_bars": duplicate_bars,
        "excluded_incomplete_bars": excluded_incomplete_bars,
        "invalid_funding_rows": invalid_funding,
    }


def _dataset_last_closed_day(root: Path) -> tuple[int, str]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    finished_raw = manifest.get("finished_at_utc")
    if not finished_raw:
        raise ValueError("Dataset manifest is missing finished_at_utc")
    finished_at = datetime.fromisoformat(str(finished_raw).replace("Z", "+00:00"))
    if finished_at.tzinfo is None:
        raise ValueError("Dataset manifest finished_at_utc must include a timezone")
    finished_at_utc = finished_at.astimezone(timezone.utc)
    last_closed_day = int(finished_at_utc.timestamp() // 86_400) - 1
    return last_closed_day, finished_at_utc.isoformat()


def _load_markets(plan: dict[str, Any]) -> tuple[list[MarketSeries], dict[str, Any]]:
    root = Path(plan["sealed_input"]["dataset_root"])
    last_closed_day, dataset_finished_at_utc = _dataset_last_closed_day(root)
    best_by_venue_base: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_universe_rows = 0
    for item in plan["sealed_input"]["universe"]:
        exchange = str(item["exchange"])
        base = str(item["base"]).upper()
        key = exchange, base
        current = best_by_venue_base.get(key)
        volume = float(item.get("volume_24h_quote_at_collect") or item.get("volume_24h_quote") or 0.0)
        current_volume = (
            float(current.get("volume_24h_quote_at_collect") or current.get("volume_24h_quote") or 0.0)
            if current is not None
            else -1.0
        )
        if current is not None:
            duplicate_universe_rows += 1
        if current is None or volume > current_volume:
            best_by_venue_base[key] = item
    markets: list[MarketSeries] = []
    quality_by_market: dict[str, Any] = {}
    for key, item in sorted(best_by_venue_base.items()):
        market, quality = _parse_market(root, item, last_closed_day)
        markets.append(market)
        quality_by_market[f"{key[0]}:{market.symbol}"] = {
            "bars": len(market.bars),
            "funding_rows": len(market.funding),
            **quality,
        }
    return markets, {
        "frozen_universe_rows": len(plan["sealed_input"]["universe"]),
        "deduplicated_market_count": len(markets),
        "duplicate_universe_rows": duplicate_universe_rows,
        "dataset_finished_at_utc": dataset_finished_at_utc,
        "last_closed_daily_bar_date": datetime.fromtimestamp(
            last_closed_day * 86_400, tz=timezone.utc
        ).date().isoformat(),
        "markets": quality_by_market,
    }


def _profit_factor(values: list[float]) -> tuple[float, bool]:
    gains = sum(value for value in values if value > 0.0)
    losses = -sum(value for value in values if value < 0.0)
    if losses > 0.0:
        return gains / losses, False
    if gains > 0.0:
        return 1_000_000_000.0, True
    return 0.0, False


def _max_drawdown(values: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


def _positive_share(values: list[float]) -> float:
    positives = [value for value in values if value > 0.0]
    total = sum(positives)
    return max(positives) / total if positives and total > 0.0 else 1.0


def _window_metrics(
    plan: dict[str, Any],
    events: list[Event],
    start_day: int,
    end_day: int,
) -> dict[str, Any]:
    selected = sorted(
        [event for event in events if start_day <= event.entry_day <= end_day],
        key=lambda event: (event.entry_day, event.exchange, event.long_symbol, event.short_symbol),
    )
    net_values = [event.normal_net_pnl_quote for event in selected]
    stress_values = [event.stress_net_pnl_quote for event in selected]
    price_only_values = [event.price_only_net_pnl_quote for event in selected]
    profit_factor, uncapped = _profit_factor(net_values)
    positive_pnl = sum(value for value in net_values if value > 0.0)
    base_contributions: dict[str, float] = {}
    venue_pnl: dict[str, list[float]] = {exchange: [] for exchange in plan["signal"]["venues"]}
    for event in selected:
        base_contributions[event.long_base] = base_contributions.get(event.long_base, 0.0) + event.long_contribution_quote
        base_contributions[event.short_base] = base_contributions.get(event.short_base, 0.0) + event.short_contribution_quote
        venue_pnl.setdefault(event.exchange, []).append(event.normal_net_pnl_quote)
    positive_base_total = sum(value for value in base_contributions.values() if value > 0.0)
    max_base_share = (
        max((value for value in base_contributions.values() if value > 0.0), default=0.0) / positive_base_total
        if positive_base_total > 0.0
        else 1.0
    )
    venue_positive_totals = [sum(value for value in values if value > 0.0) for values in venue_pnl.values()]
    venue_positive_total = sum(venue_positive_totals)
    max_venue_share = max(venue_positive_totals, default=0.0) / venue_positive_total if venue_positive_total > 0.0 else 1.0
    notional = float(plan["economics"]["notional_quote_per_leg"])
    mean_price_bps = (
        statistics.mean(event.price_pnl_quote for event in selected) / notional * 10_000.0
        if selected
        else 0.0
    )
    mean_cost_bps = (
        statistics.mean(event.normal_cost_quote for event in selected) / notional * 10_000.0
        if selected
        else 0.0
    )
    break_even = mean_cost_bps / mean_price_bps if mean_price_bps > 0.0 else None
    by_venue: dict[str, Any] = {}
    for exchange in plan["signal"]["venues"]:
        values = venue_pnl.get(exchange) or []
        venue_pf, venue_uncapped = _profit_factor(values)
        by_venue[exchange] = {
            "event_count": len(values),
            "net_pnl_quote": round(sum(values), 8),
            "net_expectancy_quote": round(statistics.mean(values), 8) if values else 0.0,
            "profit_factor": round(venue_pf, 8),
            "profit_factor_uncapped": venue_uncapped,
            "positive_event_rate": round(sum(value > 0.0 for value in values) / len(values), 8) if values else 0.0,
        }
    funding_absolute = sum(abs(event.funding_pnl_quote) for event in selected)
    return {
        "start": datetime.fromtimestamp(start_day * 86_400, tz=timezone.utc).date().isoformat(),
        "end": datetime.fromtimestamp(end_day * 86_400, tz=timezone.utc).date().isoformat(),
        "calendar_days": end_day - start_day + 1,
        "event_count": len(selected),
        "net_pnl_quote": round(sum(net_values), 8),
        "net_expectancy_quote": round(statistics.mean(net_values), 8) if net_values else 0.0,
        "profit_factor": round(profit_factor, 8),
        "profit_factor_uncapped": uncapped,
        "positive_event_rate": round(sum(value > 0.0 for value in net_values) / len(net_values), 8) if net_values else 0.0,
        "stress_net_pnl_quote": round(sum(stress_values), 8),
        "price_only_net_pnl_quote": round(sum(price_only_values), 8),
        "funding_pnl_quote": round(sum(event.funding_pnl_quote for event in selected), 8),
        "total_normal_cost_quote": round(sum(event.normal_cost_quote for event in selected), 8),
        "max_drawdown_quote": round(_max_drawdown(net_values), 8),
        "max_single_event_positive_pnl_share": round(_positive_share(net_values), 8),
        "max_single_base_positive_pnl_share": round(max_base_share, 8),
        "max_single_venue_positive_pnl_share": round(max_venue_share, 8),
        "absolute_funding_share_of_positive_pnl": round(funding_absolute / positive_pnl, 8) if positive_pnl > 0.0 else 1.0,
        "break_even_holding_days": None if break_even is None else round(break_even, 8),
        "minimum_capacity_proxy_quote": round(min((event.capacity_proxy_quote for event in selected), default=0.0), 8) if selected else None,
        "by_venue": by_venue,
    }


def _serialize_event(event: Event) -> dict[str, Any]:
    row = asdict(event)
    row["signal_date"] = datetime.fromtimestamp(event.signal_day * 86_400, tz=timezone.utc).date().isoformat()
    row["entry_date"] = datetime.fromtimestamp(event.entry_day * 86_400, tz=timezone.utc).date().isoformat()
    return row


def _deterministic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def evaluate_plan(
    plan_path: str | Path,
    *,
    output_path: str | Path | None = None,
    progress: Callable[[str], None] | None = print,
) -> dict[str, Any]:
    started = time.monotonic()
    plan_file = Path(plan_path).resolve()
    plan = json.loads(plan_file.read_text(encoding="utf-8-sig"))
    validate_plan(plan)
    runtime_limit = int(plan["runtime_policy"]["evaluation_max_runtime_sec"])

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    def check_runtime() -> None:
        if time.monotonic() - started > runtime_limit:
            raise TimeoutError(f"Residual-dispersion evaluation exceeded {runtime_limit} seconds")

    emit("[1/5] verifying frozen plan and  input hashes")
    evidence = _verify_sealed_input(plan)
    split = plan["validation"]["chronological_split"]
    oos_start = _day_from_iso(split["oos"]["start"])
    oos_end = _day_from_iso(split["oos"]["end"])
    base_data_metrics = {
        **evidence,
        "oos_calendar_days": int(split["oos"]["calendar_days"]),
    }
    if not evidence["input_hashes_match"]:
        metrics = {"data": base_data_metrics, "train": None, "oos": None, "walk_forward": None}
        decision = decide_verdict(plan, metrics)
        deterministic = {
            "plan_hash": plan["plan_hash"],
            "metrics": metrics,
            "verdict": decision["verdict"],
            "reasons": decision["reasons"],
        }
        report = {
            "schema": "fast_first_residual_dispersion_evaluation_v1",
            "created_at_utc": plan.get("created_at_utc"),
            "plan_path": str(plan_file),
            "plan_hash": plan["plan_hash"],
            "hypothesis_id": plan["hypothesis"]["id"],
            "research_only": True,
            "grid_search": False,
            "execution_probe_started": False,
            "paper_forward_started": False,
            "live_orders": False,
            "verdict": decision["verdict"],
            "rejection_reasons": decision["reasons"],
            "gate_results": decision["gate_results"],
            "metrics": metrics,
            "signals": [],
            "events": [],
            "deterministic_result_hash": _deterministic_hash(deterministic),
            "next_allowed_command": "new-fast-first-hypothesis-planonly",
            "runtime_sec": round(time.monotonic() - started, 3),
        }
        destination = Path(output_path) if output_path else plan_file.with_name("residual_dispersion_evaluation.json")
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination.resolve())
        return report

    check_runtime()
    emit("[2/5] loading sealed MEXC/Gate daily markets")
    try:
        markets, quality = _load_markets(plan)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        metrics = {
            "data": {**base_data_metrics, "input_parse_error": f"{type(exc).__name__}: {exc}"},
            "train": None,
            "oos": None,
            "walk_forward": None,
        }
        decision = decide_verdict(plan, metrics)
        deterministic = {
            "plan_hash": plan["plan_hash"],
            "metrics": metrics,
            "verdict": decision["verdict"],
            "reasons": decision["reasons"],
        }
        report = {
            "schema": "fast_first_residual_dispersion_evaluation_v1",
            "created_at_utc": plan.get("created_at_utc"),
            "plan_path": str(plan_file),
            "plan_hash": plan["plan_hash"],
            "hypothesis_id": plan["hypothesis"]["id"],
            "research_only": True,
            "grid_search": False,
            "execution_probe_started": False,
            "paper_forward_started": False,
            "live_orders": False,
            "verdict": "INSUFFICIENT_DATA",
            "rejection_reasons": ["sealed_input_parse_failure"],
            "gate_results": decision["gate_results"],
            "metrics": metrics,
            "signals": [],
            "events": [],
            "deterministic_result_hash": _deterministic_hash(deterministic),
            "next_allowed_command": "repair-sealed-input-or-new-planonly",
            "runtime_sec": round(time.monotonic() - started, 3),
        }
        destination = Path(output_path) if output_path else plan_file.with_name("residual_dispersion_evaluation.json")
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination.resolve())
        return report

    all_signals: list[Signal] = []
    signal_diagnostics: dict[str, Any] = {}
    events: list[Event] = []
    for exchange in plan["signal"]["venues"]:
        check_runtime()
        emit(f"[3/5] building backward-only signals for {exchange}")
        venue_signals, diagnostics = build_venue_signals(plan, markets, exchange)
        signal_diagnostics[exchange] = diagnostics
        all_signals.extend(venue_signals)
        venue_market_map = {
            market.symbol: market
            for market in markets
            if market.exchange == exchange
        }
        for signal in venue_signals:
            events.append(simulate_signal(plan, signal, venue_market_map))

    check_runtime()
    emit("[4/5] calculating frozen train/OOS, walk-forward and stress metrics")
    train_start = _day_from_iso(split["train"]["start"])
    train_end = _day_from_iso(split["train"]["end"])
    train_metrics = _window_metrics(plan, events, train_start, train_end)
    oos_metrics = _window_metrics(plan, events, oos_start, oos_end)
    fold_rows: list[dict[str, Any]] = []
    for fold in plan["validation"]["walk_forward"]["folds"]:
        metrics = _window_metrics(
            plan,
            events,
            _day_from_iso(fold["test_start"]),
            _day_from_iso(fold["test_end"]),
        )
        fold_rows.append(
            {
                "fold": int(fold["fold"]),
                **metrics,
                "positive": metrics["net_pnl_quote"] > 0.0,
            }
        )
    walk = {
        "folds_requested": 5,
        "folds_completed": len(fold_rows),
        "positive_folds": sum(row["positive"] for row in fold_rows),
        "folds": fold_rows,
    }
    actual_coverage: dict[str, int] = {}
    for exchange in plan["signal"]["venues"]:
        venue_days = {
            day
            for market in markets
            if market.exchange == exchange
            for day in market.bars
            if oos_start <= day <= oos_end
        }
        actual_coverage[exchange] = len(venue_days)
    base_data_metrics.update(
        {
            "quality": quality,
            "oos_calendar_days_by_venue": actual_coverage,
            "oos_calendar_days": min(actual_coverage.values(), default=0),
        }
    )
    validation_metrics = {
        "data": base_data_metrics,
        "train": train_metrics,
        "oos": oos_metrics,
        "walk_forward": walk,
    }
    decision = decide_verdict(plan, validation_metrics)
    serialized_signals = [asdict(signal) for signal in sorted(all_signals, key=lambda row: (row.signal_day, row.exchange, row.long_symbol, row.short_symbol))]
    serialized_events = [_serialize_event(event) for event in sorted(events, key=lambda row: (row.entry_day, row.exchange, row.long_symbol, row.short_symbol))]
    deterministic = {
        "plan_hash": plan["plan_hash"],
        "metrics": validation_metrics,
        "verdict": decision["verdict"],
        "reasons": decision["reasons"],
        "signals": serialized_signals,
        "events": serialized_events,
        "signal_diagnostics": signal_diagnostics,
    }
    report = {
        "schema": "fast_first_residual_dispersion_evaluation_v1",
        "created_at_utc": plan.get("created_at_utc"),
        "plan_path": str(plan_file),
        "plan_hash": plan["plan_hash"],
        "hypothesis_id": plan["hypothesis"]["id"],
        "research_only": True,
        "grid_search": False,
        "execution_probe_started": False,
        "paper_forward_started": False,
        "live_orders": False,
        "verdict": decision["verdict"],
        "rejection_reasons": decision["reasons"],
        "gate_results": decision["gate_results"],
        "metrics": validation_metrics,
        "signal_diagnostics": signal_diagnostics,
        "signals": serialized_signals,
        "events": serialized_events,
        "deterministic_result_hash": _deterministic_hash(deterministic),
        "next_allowed_command": (
            "fast-edge-v2-short-execution-probe-planonly"
            if decision["verdict"] == "ACCEPT_FOR_SHORT_EXECUTION_PROBE"
            else "new-fast-first-hypothesis-planonly"
        ),
        "runtime_sec": round(time.monotonic() - started, 3),
    }
    check_runtime()
    emit(f"[5/5] verdict={report['verdict']} events={len(events)}")
    destination = Path(output_path) if output_path else plan_file.with_name("residual_dispersion_evaluation.json")
    _write_json_atomic(destination, report)
    report["artifact_path"] = str(destination.resolve())
    return report


def _load_bound_plan(path: str | Path, expected_plan_hash: str | None) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate_plan(plan)
    if expected_plan_hash and plan["plan_hash"].lower() != expected_plan_hash.lower():
        raise ValueError(
            f"Expected plan hash {expected_plan_hash}, observed {plan['plan_hash']}"
        )
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frozen no-grid residual-dispersion evaluator for trading_mvp Fast-First v2."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    validate_parser = subparsers.add_parser("validate-seal")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash")
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument("--expected-plan-hash", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = _load_bound_plan(args.plan, getattr(args, "expected_plan_hash", None))
    if args.action == "validate-seal":
        evidence = _verify_sealed_input(plan)
        print(
            json.dumps(
                {
                    "plan_hash": plan["plan_hash"],
                    **evidence,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0 if evidence["input_hashes_match"] else 2
    report = evaluate_plan(args.plan, output_path=args.output)
    print(
        json.dumps(
            {
                "artifact_path": report["artifact_path"],
                "plan_hash": report["plan_hash"],
                "verdict": report["verdict"],
                "rejection_reasons": report["rejection_reasons"],
                "deterministic_result_hash": report["deterministic_result_hash"],
                "runtime_sec": report["runtime_sec"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
