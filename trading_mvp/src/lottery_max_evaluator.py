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
from typing import Any, Callable, Iterable

from costs import RouteLeg, base_api_cost_profile


PLAN_SCHEMA = "fast_first_lottery_max_plan_v1"
EVALUATION_SCHEMA = "fast_first_lottery_max_evaluation_v1"
HYPOTHESIS_ID = "venue_local_lottery_max_factor_v1"
VERDICTS = ("ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA")
SCORE_TYPES = ("main", "robustness")
MAX_RUN_RUNTIME_SEC = 10_800
MAX_EVALUATION_RUNTIME_SEC = 1_800
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
class PortfolioSignal:
    exchange: str
    score_type: str
    signal_day: int
    entry_day: int
    exit_day: int
    long_symbols: tuple[str, str]
    long_bases: tuple[str, str]
    short_symbols: tuple[str, str]
    short_bases: tuple[str, str]
    long_scores: tuple[float, float]
    short_scores: tuple[float, float]
    eligible_markets: int
    selected_quote_volumes: tuple[float, float, float, float]


@dataclass(frozen=True)
class PortfolioEvent:
    exchange: str
    score_type: str
    signal_day: int
    entry_day: int
    exit_day: int
    long_symbols: tuple[str, str]
    long_bases: tuple[str, str]
    short_symbols: tuple[str, str]
    short_bases: tuple[str, str]
    price_pnl_quote: float
    funding_pnl_quote: float
    stress_funding_pnl_quote: float
    normal_cost_quote: float
    stress_cost_quote: float
    price_only_net_pnl_quote: float
    normal_net_pnl_quote: float
    stress_net_pnl_quote: float
    capacity_proxy_quote: float
    leg_contributions_quote: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class _FeatureRow:
    market: MarketSeries
    max_return: float
    cumulative_return: float
    quote_volume: float


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _deterministic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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


def _expected_four_leg_costs(notional: float) -> dict[str, Any]:
    profile = base_api_cost_profile()
    result: dict[str, Any] = {}
    for exchange in ("mexc", "gateio"):
        venue: dict[str, Any] = {}
        for label, stress in (("normal", False), ("stress", True)):
            pair_cycle = profile.cycle_cost(
                [RouteLeg(exchange, "perp"), RouteLeg(exchange, "perp")],
                stress=stress,
            )
            total_cost_quote = 2.0 * notional * float(pair_cycle["total_bps"]) / 10_000.0
            gross_notional = 4.0 * notional
            venue[label] = {
                "entry_orders": 4,
                "exit_orders": 4,
                "gross_notional_quote": gross_notional,
                "legs_total": 4,
                "notional_quote_per_leg": notional,
                "orders_total": 8,
                "pair_count": 2,
                "pair_cycle": pair_cycle,
                "total_cost_bps_on_gross_notional": total_cost_quote / gross_notional * 10_000.0,
                "total_cost_bps_on_single_leg_notional": total_cost_quote / notional * 10_000.0,
                "total_cost_quote": total_cost_quote,
            }
        result[exchange] = venue
    return result


def _costs_equal(observed: Any, expected: Any) -> bool:
    if isinstance(observed, dict) and isinstance(expected, dict):
        return observed.keys() == expected.keys() and all(
            _costs_equal(observed[key], expected[key]) for key in observed
        )
    if isinstance(observed, list) and isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _costs_equal(left, right) for left, right in zip(observed, expected)
        )
    if (
        isinstance(observed, (int, float))
        and not isinstance(observed, bool)
        and isinstance(expected, (int, float))
        and not isinstance(expected, bool)
    ):
        return math.isclose(float(observed), float(expected), rel_tol=1e-12, abs_tol=1e-12)
    return observed == expected


def validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"Unsupported plan schema: {plan.get('schema')!r}")
    if canonical_plan_hash(plan) != str(plan.get("plan_hash") or "").lower():
        raise ValueError("Plan hash mismatch; frozen configuration was modified")
    if plan.get("mode") != "PlanOnly":
        raise ValueError("Frozen plan must use PlanOnly mode")
    if plan.get("research_only") is not True:
        raise ValueError("research_only must be true")
    if plan.get("frozen_parameters_no_grid") is not True:
        raise ValueError("Frozen evaluator requires an explicit no-grid contract")
    for name in (
        "strategy_accepted",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        if plan.get(name) is not False:
            raise ValueError(f"{name} must be false in PlanOnly")

    hypothesis = plan.get("hypothesis") or {}
    if hypothesis.get("id") != HYPOTHESIS_ID:
        raise ValueError("Unexpected frozen hypothesis id")

    signal = plan.get("signal") or {}
    if signal.get("venues") != ["mexc", "gateio"]:
        raise ValueError("Frozen evaluator requires mexc and gateio venue replication")
    if signal.get("timeframe") != "1d":
        raise ValueError("Lottery-MAX evaluator requires closed daily bars")
    if signal.get("entry") != "next closed-session daily open t+1":
        raise ValueError("Unsupported frozen entry timing")
    if signal.get("exit") != "close of fifth daily bar after entry":
        raise ValueError("Unsupported frozen exit timing")
    if int(signal.get("hold_days") or 0) != 5:
        raise ValueError("Lottery-MAX evaluator requires a five-day hold")
    if int(signal.get("rebalance_every_days") or 0) != 5:
        raise ValueError("Lottery-MAX evaluator requires a five-day rebalance")
    date.fromisoformat(str(signal.get("rebalance_anchor_date")))
    if signal.get("overlapping_positions") is not False:
        raise ValueError("Overlapping positions are forbidden")
    if int(signal.get("max_concurrent_portfolios_per_venue") or 0) != 1:
        raise ValueError("Only one portfolio per venue may be active")
    if signal.get("parameter_selection_on_train") is not False or signal.get("parameter_selection_on_oos") is not False:
        raise ValueError("Parameter selection on train/OOS is forbidden")
    if signal.get("main_score_uses_cumulative_return_rank") is not False:
        raise ValueError("Cumulative-return momentum ranking is forbidden in the main score")

    eligibility = plan.get("eligibility") or {}
    exact_integer_fields = {
        "minimum_prior_closed_days": 60,
        "max_return_lookback_days": 20,
        "liquidity_lookback_days": 30,
        "candidate_pool_max_markets": 12,
        "minimum_candidate_pool_markets": 8,
        "selected_long_markets": 2,
        "selected_short_markets": 2,
    }
    for name, expected in exact_integer_fields.items():
        if int(eligibility.get(name) or 0) != expected:
            raise ValueError(f"eligibility.{name} must remain frozen at {expected}")
    for name in (
        "minimum_selected_leg_trailing_median_quote_volume",
        "minimum_selected_leg_capacity_quote",
    ):
        _require_positive_number(eligibility.get(name), f"eligibility.{name}")
    if eligibility.get("require_contiguous_feature_history") is not True:
        raise ValueError("Contiguous feature history is mandatory")
    if eligibility.get("no_future_membership_or_volume_data") is not True:
        raise ValueError("Future membership/volume data is forbidden")
    if eligibility.get("non_binance_baseline_required") is not True:
        raise ValueError("Non-Binance universe is mandatory")
    if eligibility.get("venues") != signal["venues"]:
        raise ValueError("Signal and eligibility venues must match")

    economics = plan.get("economics") or {}
    notional = _require_positive_number(
        economics.get("notional_quote_per_leg"), "economics.notional_quote_per_leg"
    )
    if int(economics.get("legs_per_portfolio") or 0) != 4:
        raise ValueError("Exactly four portfolio legs are required")
    if float(economics.get("gross_notional_quote_per_venue") or 0.0) != 4.0 * notional:
        raise ValueError("Gross venue notional must equal four leg notionals")
    profile = base_api_cost_profile()
    if economics.get("cost_profile") != profile.as_dict():
        raise ValueError("Frozen CostProfile does not match the unified base_api model")
    if not _costs_equal(
        economics.get("same_venue_four_perp_portfolio_cycle_costs"),
        _expected_four_leg_costs(notional),
    ):
        raise ValueError("Frozen four-leg costs do not match the unified CostProfile")
    funding = economics.get("funding_treatment") or {}
    if funding.get("signal_use") != "forbidden":
        raise ValueError("Funding cannot be used as a signal")
    if funding.get("price_only_net_after_cost_must_be_positive") is not True:
        raise ValueError("Price-only net-after-cost gate is mandatory")

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
    if int(oos.get("calendar_days") or 0) < 60:
        raise ValueError("Frozen OOS must contain at least 60 closed calendar days")
    folds = (validation.get("walk_forward") or {}).get("folds") or []
    if len(folds) != 5:
        raise ValueError("Exactly five walk-forward folds are required")
    previous_end: date | None = None
    for expected_fold, fold in enumerate(folds, start=1):
        if int(fold.get("fold") or 0) != expected_fold:
            raise ValueError("Walk-forward fold numbering mismatch")
        start = date.fromisoformat(str(fold.get("test_start")))
        end = date.fromisoformat(str(fold.get("test_end")))
        if _inclusive_days(start.isoformat(), end.isoformat()) != int(fold.get("calendar_days") or 0):
            raise ValueError("Walk-forward calendar_days mismatch")
        if end < start or (previous_end is not None and start <= previous_end):
            raise ValueError("Walk-forward folds must be chronological and non-overlapping")
        previous_end = end

    runtime = plan.get("runtime_policy") or {}
    evaluation_sec = int(_require_positive_number(runtime.get("evaluation_max_runtime_sec"), "evaluation_max_runtime_sec"))
    network_sec = int(_require_positive_number(runtime.get("network_probe_max_runtime_sec"), "network_probe_max_runtime_sec"))
    absolute_sec = int(_require_positive_number(runtime.get("absolute_run_max_runtime_sec"), "absolute_run_max_runtime_sec"))
    if absolute_sec > MAX_RUN_RUNTIME_SEC or evaluation_sec > min(absolute_sec, MAX_EVALUATION_RUNTIME_SEC):
        raise ValueError("Evaluation runtime exceeds the Fast-First cap")
    if network_sec > MAX_NETWORK_PROBE_SEC:
        raise ValueError("Network probe runtime exceeds the Fast-First cap")
    if runtime.get("visible_terminal_required_for_evaluation_or_probe") is not True:
        raise ValueError("Visible terminal is mandatory")
    if runtime.get("network_collection_required_for_plan") is not False:
        raise ValueError("The frozen evaluation must not require a new collector")

    sealed = plan.get("sealed_input") or {}
    source_files = sealed.get("source_files") or []
    if not source_files or len(source_files) != int(sealed.get("source_file_count") or 0):
        raise ValueError("Sealed source file inventory is empty or inconsistent")
    if "manifest.json" not in {str(item.get("relative_path")) for item in source_files}:
        raise ValueError("Sealed dataset manifest.json is required")
    date.fromisoformat(str(sealed.get("last_closed_daily_bar_date")))
    if sealed.get("open_or_partial_bars_after_date_must_be_excluded") is not True:
        raise ValueError("Closed-bar exclusion must remain enabled")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        if observed != expected:
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


def _day_from_iso(value: str) -> int:
    timestamp = datetime.combine(
        date.fromisoformat(value), datetime_time.min, tzinfo=timezone.utc
    ).timestamp()
    return int(timestamp // 86_400)


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
        bars[day] = Bar(day, ts, open_price, close, quote_volume)
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
    return MarketSeries(exchange, symbol, base, bars, funding), {
        "invalid_bars": invalid_bars,
        "duplicate_bars": duplicate_bars,
        "excluded_incomplete_bars": excluded_incomplete_bars,
        "invalid_funding_rows": invalid_funding,
    }


def _load_markets(plan: dict[str, Any]) -> tuple[list[MarketSeries], dict[str, Any]]:
    sealed = plan["sealed_input"]
    root = Path(sealed["dataset_root"])
    last_closed_day = _day_from_iso(sealed["last_closed_daily_bar_date"])
    seen: set[tuple[str, str]] = set()
    markets: list[MarketSeries] = []
    quality_by_market: dict[str, Any] = {}
    duplicate_universe_rows = 0
    for item in sorted(
        sealed.get("universe") or [],
        key=lambda row: (str(row.get("exchange")), str(row.get("base")), str(row.get("symbol"))),
    ):
        key = str(item["exchange"]), str(item["symbol"])
        if key in seen:
            duplicate_universe_rows += 1
            continue
        seen.add(key)
        market, quality = _parse_market(root, item, last_closed_day)
        markets.append(market)
        quality_by_market[f"{market.exchange}:{market.symbol}"] = {
            "bars": len(market.bars),
            "funding_rows": len(market.funding),
            **quality,
        }
    return markets, {
        "frozen_universe_rows": len(sealed.get("universe") or []),
        "deduplicated_market_count": len(markets),
        "duplicate_universe_rows": duplicate_universe_rows,
        "last_closed_daily_bar_date": sealed["last_closed_daily_bar_date"],
        "markets": quality_by_market,
    }


def _contiguous_bars(market: MarketSeries, start_day: int, end_day: int) -> list[Bar] | None:
    rows = [market.bars.get(day) for day in range(start_day, end_day + 1)]
    if any(row is None for row in rows):
        return None
    return [row for row in rows if row is not None]


def _feature_row(plan: dict[str, Any], market: MarketSeries, day: int) -> _FeatureRow | None:
    eligibility = plan["eligibility"]
    minimum_history = int(eligibility["minimum_prior_closed_days"])
    if sum(observed < day for observed in market.bars) < minimum_history:
        return None
    max_window = int(eligibility["max_return_lookback_days"])
    liquidity_window = int(eligibility["liquidity_lookback_days"])
    start_day = day - max(max_window, liquidity_window - 1)
    rows = _contiguous_bars(market, start_day, day)
    if rows is None:
        return None
    max_rows = _contiguous_bars(market, day - max_window, day)
    liquidity_rows = _contiguous_bars(market, day - liquidity_window + 1, day)
    if max_rows is None or liquidity_rows is None:
        return None
    returns: list[float] = []
    for previous, current in zip(max_rows, max_rows[1:]):
        if previous.close <= 0.0 or current.close <= 0.0:
            return None
        returns.append(math.log(current.close / previous.close))
    if len(returns) != max_window:
        return None
    cumulative = math.log(max_rows[-1].close / max_rows[0].close)
    qvolume = statistics.median(row.quote_volume for row in liquidity_rows)
    if not all(math.isfinite(value) for value in (*returns, cumulative, qvolume)):
        return None
    return _FeatureRow(market, max(returns), cumulative, qvolume)


def _solve_two_factor_residuals(rows: list[_FeatureRow]) -> dict[str, float]:
    y = [row.max_return for row in rows]
    x1 = [row.cumulative_return for row in rows]
    x2 = [math.log(row.quote_volume) for row in rows]
    mean_y = statistics.mean(y)
    mean_x1 = statistics.mean(x1)
    mean_x2 = statistics.mean(x2)
    centered_y = [value - mean_y for value in y]
    centered_x1 = [value - mean_x1 for value in x1]
    centered_x2 = [value - mean_x2 for value in x2]
    s11 = sum(value * value for value in centered_x1)
    s22 = sum(value * value for value in centered_x2)
    s12 = sum(left * right for left, right in zip(centered_x1, centered_x2))
    sy1 = sum(left * right for left, right in zip(centered_x1, centered_y))
    sy2 = sum(left * right for left, right in zip(centered_x2, centered_y))
    determinant = s11 * s22 - s12 * s12
    scale = max(s11 * s22, 1.0)
    if abs(determinant) > 1e-14 * scale:
        beta1 = (sy1 * s22 - sy2 * s12) / determinant
        beta2 = (sy2 * s11 - sy1 * s12) / determinant
    elif s11 >= s22 and s11 > 1e-24:
        beta1, beta2 = sy1 / s11, 0.0
    elif s22 > 1e-24:
        beta1, beta2 = 0.0, sy2 / s22
    else:
        beta1 = beta2 = 0.0
    alpha = mean_y - beta1 * mean_x1 - beta2 * mean_x2
    return {
        row.market.symbol: row.max_return - (alpha + beta1 * row.cumulative_return + beta2 * math.log(row.quote_volume))
        for row in rows
    }


def _candidate_rows(
    plan: dict[str, Any], markets: list[MarketSeries], exchange: str, day: int
) -> list[_FeatureRow]:
    excluded = {str(value).upper() for value in plan["eligibility"].get("excluded_synthetic_proxy_bases") or []}
    by_base: dict[str, _FeatureRow] = {}
    for market in markets:
        if market.exchange != exchange or market.base.upper() in excluded:
            continue
        row = _feature_row(plan, market, day)
        if row is None:
            continue
        current = by_base.get(market.base.upper())
        if current is None or (-row.quote_volume, market.symbol) < (-current.quote_volume, current.market.symbol):
            by_base[market.base.upper()] = row
    maximum = int(plan["eligibility"]["candidate_pool_max_markets"])
    return sorted(
        by_base.values(),
        key=lambda row: (-row.quote_volume, row.market.base, row.market.symbol),
    )[:maximum]


def build_venue_signals(
    plan: dict[str, Any],
    markets: list[MarketSeries],
    exchange: str,
    *,
    score_type: str = "main",
) -> tuple[list[PortfolioSignal], dict[str, Any]]:
    if score_type not in SCORE_TYPES:
        raise ValueError(f"Unknown score_type: {score_type}")
    if exchange not in plan["signal"]["venues"]:
        raise ValueError(f"Exchange is outside the frozen plan: {exchange}")
    anchor = _day_from_iso(plan["signal"]["rebalance_anchor_date"])
    every = int(plan["signal"]["rebalance_every_days"])
    hold = int(plan["signal"]["hold_days"])
    minimum_candidates = int(plan["eligibility"]["minimum_candidate_pool_markets"])
    minimum_volume = float(plan["eligibility"]["minimum_selected_leg_trailing_median_quote_volume"])
    minimum_capacity = float(plan["eligibility"]["minimum_selected_leg_capacity_quote"])
    venue_markets = [market for market in markets if market.exchange == exchange]
    all_days = sorted({day for market in venue_markets for day in market.bars if day >= anchor})
    diagnostics: dict[str, Any] = {
        "exchange": exchange,
        "score_type": score_type,
        "market_count": len(venue_markets),
        "scheduled_dates": 0,
        "signal_count": 0,
        "skipped": {
            "insufficient_candidate_pool": 0,
            "selected_leg_liquidity_or_capacity": 0,
            "missing_execution_bars": 0,
        },
    }
    signals: list[PortfolioSignal] = []
    for day in all_days:
        if (day - anchor) % every != 0:
            continue
        diagnostics["scheduled_dates"] += 1
        candidates = _candidate_rows(plan, venue_markets, exchange, day)
        if len(candidates) < minimum_candidates:
            diagnostics["skipped"]["insufficient_candidate_pool"] += 1
            continue
        scores = (
            {row.market.symbol: row.max_return for row in candidates}
            if score_type == "main"
            else _solve_two_factor_residuals(candidates)
        )
        ordered = sorted(
            candidates,
            key=lambda row: (scores[row.market.symbol], row.market.base, row.market.symbol),
        )
        longs = ordered[:2]
        shorts = list(reversed(ordered[-2:]))
        selected = longs + shorts
        if any(
            row.quote_volume < minimum_volume or 0.0001 * row.quote_volume < minimum_capacity
            for row in selected
        ):
            diagnostics["skipped"]["selected_leg_liquidity_or_capacity"] += 1
            continue
        entry_day = day + 1
        exit_day = day + hold
        if any(
            _contiguous_bars(row.market, entry_day, exit_day) is None for row in selected
        ):
            diagnostics["skipped"]["missing_execution_bars"] += 1
            continue
        signals.append(
            PortfolioSignal(
                exchange=exchange,
                score_type=score_type,
                signal_day=day,
                entry_day=entry_day,
                exit_day=exit_day,
                long_symbols=(longs[0].market.symbol, longs[1].market.symbol),
                long_bases=(longs[0].market.base, longs[1].market.base),
                short_symbols=(shorts[0].market.symbol, shorts[1].market.symbol),
                short_bases=(shorts[0].market.base, shorts[1].market.base),
                long_scores=(scores[longs[0].market.symbol], scores[longs[1].market.symbol]),
                short_scores=(scores[shorts[0].market.symbol], scores[shorts[1].market.symbol]),
                eligible_markets=len(candidates),
                selected_quote_volumes=tuple(row.quote_volume for row in selected),
            )
        )
    diagnostics["signal_count"] = len(signals)
    return signals, diagnostics


def _funding_sum(market: MarketSeries, entry_ts: int, exit_ts: int) -> float:
    return sum(rate for ts, rate in market.funding if entry_ts < ts <= exit_ts)


def simulate_signal(
    plan: dict[str, Any],
    signal: PortfolioSignal,
    markets_by_symbol: dict[str, MarketSeries],
) -> PortfolioEvent:
    notional = float(plan["economics"]["notional_quote_per_leg"])
    leg_specs = [
        (symbol, base, 1.0)
        for symbol, base in zip(signal.long_symbols, signal.long_bases)
    ] + [
        (symbol, base, -1.0)
        for symbol, base in zip(signal.short_symbols, signal.short_bases)
    ]
    price_pnl = 0.0
    funding_pnl = 0.0
    stress_funding_pnl = 0.0
    raw_contributions: list[tuple[str, float]] = []
    for symbol, base, side in leg_specs:
        market = markets_by_symbol[symbol]
        entry_bar = market.bars.get(signal.entry_day)
        exit_bar = market.bars.get(signal.exit_day)
        if entry_bar is None or exit_bar is None:
            raise ValueError(f"Execution bar missing for selected leg: {symbol}")
        if entry_bar.open <= 0.0 or exit_bar.close <= 0.0:
            raise ValueError(f"Execution price must be positive: {symbol}")
        leg_price = side * notional * (exit_bar.close / entry_bar.open - 1.0)
        entry_ts = entry_bar.ts
        exit_close_ts = exit_bar.ts + 86_400
        leg_funding = -side * notional * _funding_sum(market, entry_ts, exit_close_ts)
        leg_stress_funding = leg_funding if leg_funding <= 0.0 else 0.5 * leg_funding
        price_pnl += leg_price
        funding_pnl += leg_funding
        stress_funding_pnl += leg_stress_funding
        raw_contributions.append((base, leg_price + leg_funding))
    costs = plan["economics"]["same_venue_four_perp_portfolio_cycle_costs"][signal.exchange]
    normal_cost = float(costs["normal"]["total_cost_quote"])
    stress_cost = float(costs["stress"]["total_cost_quote"])
    contributions = tuple(
        (base, value - normal_cost / 4.0) for base, value in raw_contributions
    )
    return PortfolioEvent(
        exchange=signal.exchange,
        score_type=signal.score_type,
        signal_day=signal.signal_day,
        entry_day=signal.entry_day,
        exit_day=signal.exit_day,
        long_symbols=signal.long_symbols,
        long_bases=signal.long_bases,
        short_symbols=signal.short_symbols,
        short_bases=signal.short_bases,
        price_pnl_quote=price_pnl,
        funding_pnl_quote=funding_pnl,
        stress_funding_pnl_quote=stress_funding_pnl,
        normal_cost_quote=normal_cost,
        stress_cost_quote=stress_cost,
        price_only_net_pnl_quote=price_pnl - normal_cost,
        normal_net_pnl_quote=price_pnl + funding_pnl - normal_cost,
        stress_net_pnl_quote=price_pnl + stress_funding_pnl - stress_cost,
        capacity_proxy_quote=0.0001 * min(signal.selected_quote_volumes),
        leg_contributions_quote=contributions,
    )


def _profit_factor(values: Iterable[float]) -> tuple[float, bool]:
    rows = list(values)
    gains = sum(value for value in rows if value > 0.0)
    losses = -sum(value for value in rows if value < 0.0)
    if losses > 0.0:
        return gains / losses, False
    if gains > 0.0:
        return 1_000_000_000.0, True
    return 0.0, False


def _max_drawdown(values: Iterable[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


def _positive_share(values: Iterable[float]) -> float:
    positives = [value for value in values if value > 0.0]
    total = sum(positives)
    return max(positives) / total if positives and total > 0.0 else 1.0


def _window_metrics(
    plan: dict[str, Any], events: list[PortfolioEvent], start_day: int, end_day: int
) -> dict[str, Any]:
    selected = sorted(
        [event for event in events if start_day <= event.entry_day and event.exit_day <= end_day],
        key=lambda event: (event.entry_day, event.exchange),
    )
    net = [event.normal_net_pnl_quote for event in selected]
    stress = [event.stress_net_pnl_quote for event in selected]
    price_only = [event.price_only_net_pnl_quote for event in selected]
    profit_factor, uncapped = _profit_factor(net)
    positive_pnl = sum(value for value in net if value > 0.0)
    base_contributions: dict[str, float] = {}
    venue_values: dict[str, list[float]] = {exchange: [] for exchange in plan["signal"]["venues"]}
    for event in selected:
        venue_values[event.exchange].append(event.normal_net_pnl_quote)
        for base, contribution in event.leg_contributions_quote:
            base_contributions[base] = base_contributions.get(base, 0.0) + contribution
    positive_base_total = sum(value for value in base_contributions.values() if value > 0.0)
    max_base_share = (
        max((value for value in base_contributions.values() if value > 0.0), default=0.0)
        / positive_base_total
        if positive_base_total > 0.0
        else 1.0
    )
    venue_positive = [sum(value for value in values if value > 0.0) for values in venue_values.values()]
    venue_positive_total = sum(venue_positive)
    max_venue_share = max(venue_positive, default=0.0) / venue_positive_total if venue_positive_total > 0.0 else 1.0
    by_venue: dict[str, Any] = {}
    for exchange in plan["signal"]["venues"]:
        values = venue_values[exchange]
        venue_pf, venue_uncapped = _profit_factor(values)
        by_venue[exchange] = {
            "event_count": len(values),
            "net_pnl_quote": round(sum(values), 8),
            "net_expectancy_quote": round(statistics.mean(values), 8) if values else 0.0,
            "profit_factor": round(venue_pf, 8),
            "profit_factor_uncapped": venue_uncapped,
            "positive_event_rate": round(sum(value > 0.0 for value in values) / len(values), 8) if values else 0.0,
        }
    hold_days = int(plan["signal"]["hold_days"])
    mean_price = statistics.mean(event.price_pnl_quote for event in selected) if selected else 0.0
    mean_cost = statistics.mean(event.normal_cost_quote for event in selected) if selected else 0.0
    break_even = hold_days * mean_cost / mean_price if mean_price > 0.0 else None
    peak_collateral = float(plan["economics"]["gross_notional_quote_per_venue"]) * len(plan["signal"]["venues"])
    drawdown = _max_drawdown(net)
    return {
        "start": datetime.fromtimestamp(start_day * 86_400, tz=timezone.utc).date().isoformat(),
        "end": datetime.fromtimestamp(end_day * 86_400, tz=timezone.utc).date().isoformat(),
        "calendar_days": end_day - start_day + 1,
        "event_count": len(selected),
        "unique_rebalance_dates": len({event.signal_day for event in selected}),
        "net_pnl_quote": round(sum(net), 8),
        "net_expectancy_quote": round(statistics.mean(net), 8) if net else 0.0,
        "profit_factor": round(profit_factor, 8),
        "profit_factor_uncapped": uncapped,
        "positive_event_rate": round(sum(value > 0.0 for value in net) / len(net), 8) if net else 0.0,
        "stress_net_pnl_quote": round(sum(stress), 8),
        "price_only_net_pnl_quote": round(sum(price_only), 8),
        "funding_pnl_quote": round(sum(event.funding_pnl_quote for event in selected), 8),
        "total_normal_cost_quote": round(sum(event.normal_cost_quote for event in selected), 8),
        "max_drawdown_quote": round(drawdown, 8),
        "peak_allocated_collateral_quote": peak_collateral,
        "max_drawdown_fraction_of_peak_allocated_collateral": round(drawdown / peak_collateral, 8),
        "max_single_event_positive_pnl_share": round(_positive_share(net), 8),
        "max_single_base_positive_pnl_share": round(max_base_share, 8),
        "max_single_venue_positive_pnl_share": round(max_venue_share, 8),
        "absolute_funding_share_of_positive_pnl": round(
            sum(abs(event.funding_pnl_quote) for event in selected) / positive_pnl, 8
        ) if positive_pnl > 0.0 else 1.0,
        "break_even_holding_days": None if break_even is None else round(break_even, 8),
        "minimum_capacity_proxy_quote": round(
            min((event.capacity_proxy_quote for event in selected), default=0.0), 8
        ) if selected else None,
        "by_venue": by_venue,
    }


def _walk_forward_metrics(
    plan: dict[str, Any], events: list[PortfolioEvent]
) -> dict[str, Any]:
    rows = []
    positive_by_venue = {exchange: 0 for exchange in plan["signal"]["venues"]}
    for fold in plan["validation"]["walk_forward"]["folds"]:
        metrics = _window_metrics(
            plan,
            events,
            _day_from_iso(fold["test_start"]),
            _day_from_iso(fold["test_end"]),
        )
        positive = metrics["net_pnl_quote"] > 0.0
        for exchange in plan["signal"]["venues"]:
            if metrics["by_venue"][exchange]["net_pnl_quote"] > 0.0:
                positive_by_venue[exchange] += 1
        rows.append({"fold": int(fold["fold"]), **metrics, "positive": positive})
    return {
        "folds_requested": 5,
        "folds_completed": len(rows),
        "positive_combined_folds": sum(row["positive"] for row in rows),
        "positive_folds_by_venue": positive_by_venue,
        "folds": rows,
    }


def _metric_number(container: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(container.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def decide_verdict(plan: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    gates = plan["validation"]["acceptance_gates"]
    data = metrics.get("data") or {}
    main = metrics.get("main") or {}
    oos = main.get("oos") or {}
    walk = main.get("walk_forward") or {}
    robustness_oos = ((metrics.get("robustness") or {}).get("oos") or {})
    by_venue = oos.get("by_venue") or {}
    gate_results: dict[str, Any] = {}
    insufficient: list[str] = []

    def record(name: str, observed: Any, required: Any, passed: bool) -> None:
        gate_results[name] = {"observed": observed, "required": required, "passed": bool(passed)}

    hashes_match = data.get("input_hashes_match") is True
    record("input_hashes_match", hashes_match, True, hashes_match)
    if not hashes_match:
        insufficient.append("sealed_input_hash_mismatch_or_missing")
    calendar_days = int(_metric_number(data, "oos_closed_calendar_days"))
    minimum_days = int(gates["minimum_oos_closed_calendar_days"])
    record("minimum_oos_closed_calendar_days", calendar_days, minimum_days, calendar_days >= minimum_days)
    if calendar_days < minimum_days:
        insufficient.append("oos_closed_calendar_days_below_minimum")
    event_count = int(_metric_number(oos, "event_count"))
    minimum_events = int(gates["minimum_oos_portfolio_events_total"])
    record("minimum_oos_portfolio_events_total", event_count, minimum_events, event_count >= minimum_events)
    if event_count < minimum_events:
        insufficient.append("oos_portfolio_events_total_below_minimum")
    minimum_per_venue = int(gates["minimum_oos_portfolio_events_per_venue"])
    for exchange in plan["signal"]["venues"]:
        count = int(_metric_number(by_venue.get(exchange) or {}, "event_count"))
        record(f"minimum_oos_portfolio_events:{exchange}", count, minimum_per_venue, count >= minimum_per_venue)
        if count < minimum_per_venue:
            insufficient.append(f"oos_portfolio_events_below_minimum:{exchange}")
    unique_dates = int(_metric_number(oos, "unique_rebalance_dates"))
    minimum_dates = int(gates["minimum_unique_oos_rebalance_dates"])
    record("minimum_unique_oos_rebalance_dates", unique_dates, minimum_dates, unique_dates >= minimum_dates)
    if unique_dates < minimum_dates:
        insufficient.append("unique_oos_rebalance_dates_below_minimum")
    capacity = oos.get("minimum_capacity_proxy_quote")
    capacity_available = capacity is not None and math.isfinite(_metric_number(oos, "minimum_capacity_proxy_quote", float("nan")))
    record("capacity_proxy_available", capacity_available, True, capacity_available)
    if not capacity_available:
        insufficient.append("capacity_proxy_unavailable")
    if insufficient:
        return {"verdict": "INSUFFICIENT_DATA", "reasons": insufficient, "gate_results": gate_results}

    rejection: list[str] = []

    def reject_gate(name: str, observed: float, required: Any, passed: bool, reason: str) -> None:
        record(name, observed, required, passed)
        if not passed:
            rejection.append(reason)

    expectancy = _metric_number(oos, "net_expectancy_quote")
    reject_gate("oos_net_expectancy_quote", expectancy, "> 0", expectancy > float(gates["oos_net_expectancy_quote_gt"]), "oos_net_expectancy_not_positive")
    profit_factor = _metric_number(oos, "profit_factor")
    reject_gate("oos_profit_factor", profit_factor, f">= {gates['oos_profit_factor_gte']}", profit_factor >= float(gates["oos_profit_factor_gte"]), "oos_profit_factor_below_minimum")
    positive_rate = _metric_number(oos, "positive_event_rate")
    reject_gate("oos_positive_event_rate", positive_rate, f">= {gates['oos_positive_portfolio_event_rate_gte']}", positive_rate >= float(gates["oos_positive_portfolio_event_rate_gte"]), "oos_positive_event_rate_below_minimum")
    positive_folds = int(_metric_number(walk, "positive_combined_folds"))
    reject_gate("positive_combined_walk_forward_folds", positive_folds, f">= {gates['minimum_positive_combined_walk_forward_folds']}", positive_folds >= int(gates["minimum_positive_combined_walk_forward_folds"]), "combined_walk_forward_folds_below_minimum")
    venue_folds = walk.get("positive_folds_by_venue") or {}
    for exchange in plan["signal"]["venues"]:
        observed = int(_metric_number(venue_folds, exchange))
        reject_gate(f"positive_walk_forward_folds:{exchange}", observed, f">= {gates['minimum_positive_walk_forward_folds_per_venue']}", observed >= int(gates["minimum_positive_walk_forward_folds_per_venue"]), f"walk_forward_folds_below_minimum:{exchange}")
    stress = _metric_number(oos, "stress_net_pnl_quote")
    reject_gate("stress_net_pnl_quote", stress, f">= {gates['stress_net_pnl_quote_gte']}", stress >= float(gates["stress_net_pnl_quote_gte"]), "stress_net_pnl_negative")
    for exchange in plan["signal"]["venues"]:
        venue_expectancy = _metric_number(by_venue.get(exchange) or {}, "net_expectancy_quote")
        reject_gate(f"venue_oos_net_expectancy:{exchange}", venue_expectancy, "> 0", venue_expectancy > 0.0, f"venue_oos_expectancy_not_positive:{exchange}")
    price_only = _metric_number(oos, "price_only_net_pnl_quote")
    reject_gate("price_only_oos_net_after_cost", price_only, "> 0", price_only > 0.0, "price_only_oos_net_not_positive")
    robust_net = _metric_number(robustness_oos, "net_pnl_quote")
    reject_gate("residualized_score_oos_net_after_cost", robust_net, "> 0", robust_net > 0.0, "residualized_score_oos_net_not_positive")
    funding_share = _metric_number(oos, "absolute_funding_share_of_positive_pnl", 1.0)
    reject_gate("absolute_funding_share", funding_share, f"<= {gates['maximum_absolute_funding_share_of_positive_oos_pnl']}", funding_share <= float(gates["maximum_absolute_funding_share_of_positive_oos_pnl"]), "funding_share_above_maximum")
    drawdown_fraction = _metric_number(oos, "max_drawdown_fraction_of_peak_allocated_collateral", 1.0)
    reject_gate("oos_drawdown_fraction", drawdown_fraction, f"<= {gates['maximum_oos_drawdown_fraction_of_peak_allocated_collateral']}", drawdown_fraction <= float(gates["maximum_oos_drawdown_fraction_of_peak_allocated_collateral"]), "oos_drawdown_fraction_above_maximum")
    for metric, gate, reason in (
        ("max_single_event_positive_pnl_share", "maximum_single_event_positive_pnl_share", "single_event_concentration_above_maximum"),
        ("max_single_base_positive_pnl_share", "maximum_single_base_positive_pnl_share", "single_base_concentration_above_maximum"),
        ("max_single_venue_positive_pnl_share", "maximum_single_venue_positive_pnl_share", "single_venue_concentration_above_maximum"),
    ):
        observed = _metric_number(oos, metric, 1.0)
        reject_gate(metric, observed, f"<= {gates[gate]}", observed <= float(gates[gate]), reason)
    break_even_raw = oos.get("break_even_holding_days")
    break_even = _metric_number(oos, "break_even_holding_days", float("inf")) if break_even_raw is not None else float("inf")
    reject_gate("break_even_holding_days", break_even_raw, f"<= {gates['maximum_break_even_holding_days']}", math.isfinite(break_even) and break_even <= float(gates["maximum_break_even_holding_days"]), "break_even_holding_period_above_maximum")
    minimum_capacity = float(gates["minimum_capacity_proxy_quote_per_selected_leg"])
    observed_capacity = _metric_number(oos, "minimum_capacity_proxy_quote")
    reject_gate("minimum_capacity_proxy_quote", observed_capacity, f">= {minimum_capacity}", observed_capacity >= minimum_capacity, "capacity_proxy_below_minimum")
    return {
        "verdict": "REJECT" if rejection else "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        "reasons": rejection,
        "gate_results": gate_results,
    }


def _serialize_signal(signal: PortfolioSignal) -> dict[str, Any]:
    row = asdict(signal)
    row["signal_date"] = datetime.fromtimestamp(signal.signal_day * 86_400, tz=timezone.utc).date().isoformat()
    row["entry_date"] = datetime.fromtimestamp(signal.entry_day * 86_400, tz=timezone.utc).date().isoformat()
    row["exit_date"] = datetime.fromtimestamp(signal.exit_day * 86_400, tz=timezone.utc).date().isoformat()
    return row


def _serialize_event(event: PortfolioEvent) -> dict[str, Any]:
    row = asdict(event)
    row["signal_date"] = datetime.fromtimestamp(event.signal_day * 86_400, tz=timezone.utc).date().isoformat()
    row["entry_date"] = datetime.fromtimestamp(event.entry_day * 86_400, tz=timezone.utc).date().isoformat()
    row["exit_date"] = datetime.fromtimestamp(event.exit_day * 86_400, tz=timezone.utc).date().isoformat()
    return row


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _empty_report(
    plan: dict[str, Any],
    plan_file: Path,
    evidence: dict[str, Any],
    reasons: list[str],
    started: float,
) -> dict[str, Any]:
    metrics = {
        "data": {
            **evidence,
            "oos_closed_calendar_days": int(
                plan["validation"]["chronological_split"]["oos"]["calendar_days"]
            ),
        },
        "main": {"train": None, "oos": None, "walk_forward": None},
        "robustness": {"train": None, "oos": None, "walk_forward": None},
    }
    deterministic = {
        "plan_hash": plan["plan_hash"],
        "metrics": metrics,
        "verdict": "INSUFFICIENT_DATA",
        "reasons": reasons,
    }
    return {
        "schema": EVALUATION_SCHEMA,
        "created_at_utc": plan.get("created_at_utc"),
        "plan_path": str(plan_file),
        "plan_hash": plan["plan_hash"],
        "hypothesis_id": HYPOTHESIS_ID,
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "grid_search": False,
        "parameter_combinations_evaluated": 1,
        "execution_probe_started": False,
        "paper_forward_started": False,
        "live_orders": False,
        "api_keys": False,
        "verdict": "INSUFFICIENT_DATA",
        "rejection_reasons": reasons,
        "gate_results": {},
        "metrics": metrics,
        "signal_diagnostics": {},
        "signals": [],
        "events": [],
        "deterministic_result_hash": _deterministic_hash(deterministic),
        "next_allowed_command": "repair-sealed-input-or-new-planonly",
        "runtime_sec": round(time.monotonic() - started, 3),
    }


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
            raise TimeoutError(f"Lottery-MAX evaluation exceeded {runtime_limit} seconds")

    destination = Path(output_path) if output_path else plan_file.with_name("lottery_max_evaluation.json")
    emit("[1/6] verifying frozen plan and sealed input hashes")
    evidence = _verify_sealed_input(plan)
    if not evidence["input_hashes_match"]:
        report = _empty_report(
            plan,
            plan_file,
            evidence,
            ["sealed_input_hash_mismatch_or_missing"],
            started,
        )
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination.resolve())
        return report

    check_runtime()
    emit("[2/6] loading closed daily MEXC/Gate markets")
    try:
        markets, quality = _load_markets(plan)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        report = _empty_report(
            plan,
            plan_file,
            {**evidence, "input_parse_error": f"{type(exc).__name__}: {exc}"},
            ["sealed_input_parse_failure"],
            started,
        )
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination.resolve())
        return report

    all_signals: dict[str, list[PortfolioSignal]] = {name: [] for name in SCORE_TYPES}
    all_events: dict[str, list[PortfolioEvent]] = {name: [] for name in SCORE_TYPES}
    diagnostics: dict[str, Any] = {name: {} for name in SCORE_TYPES}
    for score_type in SCORE_TYPES:
        for exchange in plan["signal"]["venues"]:
            check_runtime()
            emit(f"[3/6] building backward-only {score_type} signals for {exchange}")
            signals, details = build_venue_signals(
                plan, markets, exchange, score_type=score_type
            )
            diagnostics[score_type][exchange] = details
            all_signals[score_type].extend(signals)
            venue_markets = {
                market.symbol: market for market in markets if market.exchange == exchange
            }
            all_events[score_type].extend(
                simulate_signal(plan, signal, venue_markets) for signal in signals
            )

    check_runtime()
    emit("[4/6] calculating fixed train/OOS and walk-forward windows")
    split = plan["validation"]["chronological_split"]
    train_start = _day_from_iso(split["train"]["start"])
    train_end = _day_from_iso(split["train"]["end"])
    oos_start = _day_from_iso(split["oos"]["start"])
    oos_end = _day_from_iso(split["oos"]["end"])
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
    data_metrics = {
        **evidence,
        "quality": quality,
        "oos_closed_calendar_days_by_venue": actual_coverage,
        "oos_closed_calendar_days": min(actual_coverage.values(), default=0),
    }
    metrics: dict[str, Any] = {"data": data_metrics}
    for score_type in SCORE_TYPES:
        metrics[score_type] = {
            "train": _window_metrics(plan, all_events[score_type], train_start, train_end),
            "oos": _window_metrics(plan, all_events[score_type], oos_start, oos_end),
            "walk_forward": _walk_forward_metrics(plan, all_events[score_type]),
        }

    check_runtime()
    emit("[5/6] applying frozen economics and evidence gates")
    decision = decide_verdict(plan, metrics)
    serialized_signals = {
        name: [
            _serialize_signal(row)
            for row in sorted(
                all_signals[name],
                key=lambda item: (item.signal_day, item.exchange, item.long_symbols),
            )
        ]
        for name in SCORE_TYPES
    }
    serialized_events = {
        name: [
            _serialize_event(row)
            for row in sorted(
                all_events[name],
                key=lambda item: (item.entry_day, item.exchange, item.long_symbols),
            )
        ]
        for name in SCORE_TYPES
    }
    deterministic = {
        "plan_hash": plan["plan_hash"],
        "metrics": metrics,
        "verdict": decision["verdict"],
        "reasons": decision["reasons"],
        "signal_diagnostics": diagnostics,
        "signals": serialized_signals,
        "events": serialized_events,
    }
    report = {
        "schema": EVALUATION_SCHEMA,
        "created_at_utc": plan.get("created_at_utc"),
        "plan_path": str(plan_file),
        "plan_hash": plan["plan_hash"],
        "hypothesis_id": HYPOTHESIS_ID,
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "grid_search": False,
        "parameter_combinations_evaluated": 1,
        "execution_probe_started": False,
        "paper_forward_started": False,
        "live_orders": False,
        "api_keys": False,
        "verdict": decision["verdict"],
        "rejection_reasons": decision["reasons"],
        "gate_results": decision["gate_results"],
        "metrics": metrics,
        "signal_diagnostics": diagnostics,
        "signals": serialized_signals,
        "events": serialized_events,
        "deterministic_result_hash": _deterministic_hash(deterministic),
        "next_allowed_command": (
            "fast-edge-v3-short-execution-probe-planonly"
            if decision["verdict"] == "ACCEPT_FOR_SHORT_EXECUTION_PROBE"
            else "new-fast-first-hypothesis-planonly"
        ),
        "runtime_sec": round(time.monotonic() - started, 3),
    }
    check_runtime()
    emit(
        f"[6/6] verdict={report['verdict']} "
        f"main_events={len(all_events['main'])} robustness_events={len(all_events['robustness'])}"
    )
    _write_json_atomic(destination, report)
    report["artifact_path"] = str(destination.resolve())
    return report


def _load_bound_plan(
    path: str | Path, expected_plan_hash: str | None
) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate_plan(plan)
    if expected_plan_hash and plan["plan_hash"].lower() != expected_plan_hash.lower():
        raise ValueError(
            f"Expected plan hash {expected_plan_hash}, observed {plan['plan_hash']}"
        )
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frozen hash-bound no-grid lottery-MAX evaluator for trading_mvp Fast-First v3."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    validate_parser = subparsers.add_parser("validate-seal")
    validate_parser.add_argument("--plan", required=True)
    validate_parser.add_argument("--expected-plan-hash", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--plan", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument("--expected-plan-hash", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = _load_bound_plan(args.plan, args.expected_plan_hash)
    if args.action == "validate-seal":
        evidence = _verify_sealed_input(plan)
        print(
            json.dumps(
                {
                    "mode": "validation_only",
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
