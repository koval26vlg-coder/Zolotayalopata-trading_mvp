from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from costs import RouteLeg, base_api_cost_profile


PLAN_SCHEMA = "fast_first_weekend_liquidity_window_plan_v1"
HYPOTHESIS_ID = "venue_local_weekend_liquidity_window_v1"
MAX_PLAN_RUNTIME_SEC = 1_200
MAX_EVALUATION_RUNTIME_SEC = 1_800


@dataclass(frozen=True)
class Bar:
    day: int
    ts: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float


@dataclass
class MarketSeries:
    exchange: str
    symbol: str
    base: str
    bars: dict[int, Bar] = field(default_factory=dict)


@dataclass(frozen=True)
class WeekendSignal:
    exchange: str
    signal_day: int
    entry_day: int
    exit_day: int
    symbols: tuple[str, str, str, str]
    bases: tuple[str, str, str, str]
    selected_quote_volumes: tuple[float, float, float, float]
    eligible_markets: int


@dataclass(frozen=True)
class WeekendEvent:
    exchange: str
    signal_day: int
    entry_day: int
    exit_day: int
    symbols: tuple[str, str, str, str]
    bases: tuple[str, str, str, str]
    gross_price_pnl_quote: float
    normal_cost_quote: float
    stress_cost_quote: float
    net_pnl_quote: float
    stress_net_pnl_quote: float
    capacity_proxy_quote: float
    leg_contributions_quote: tuple[tuple[str, float], ...]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _verify_source_plan_hash(source: dict[str, Any]) -> None:
    expected = str(source.get("plan_hash") or "").lower()
    if len(expected) != 64:
        raise ValueError("Source plan is missing a valid plan_hash")
    observed = canonical_plan_hash(source)
    if observed != expected:
        raise ValueError("Source plan hash mismatch")


def _normalized_timestamp(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid timestamp: {value!r}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid timestamp: {value!r}")
    if number >= 10_000_000_000:
        number /= 1000.0
    return int(number)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    payload = _load_json_object(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"Expected rows list in {path}")
    return [row for row in rows if isinstance(row, dict)]


def _inclusive_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _walk_forward_contract() -> dict[str, Any]:
    return {
        "method": "five_chronological_folds_on_closed_daily_bars",
        "folds": [
            {"fold": 1, "train": {"start": "2025-12-26", "end": "2026-02-23"}, "test": {"start": "2026-02-24", "end": "2026-03-24"}},
            {"fold": 2, "train": {"start": "2026-01-24", "end": "2026-03-24"}, "test": {"start": "2026-03-25", "end": "2026-04-22"}},
            {"fold": 3, "train": {"start": "2026-02-22", "end": "2026-04-22"}, "test": {"start": "2026-04-23", "end": "2026-05-21"}},
            {"fold": 4, "train": {"start": "2026-03-23", "end": "2026-05-21"}, "test": {"start": "2026-05-22", "end": "2026-06-19"}},
            {"fold": 5, "train": {"start": "2026-04-21", "end": "2026-06-19"}, "test": {"start": "2026-06-20", "end": "2026-07-12"}},
        ],
        "parameter_selection_per_fold": False,
        "folds_required_positive": 4,
    }


def verify_sealed_input(sealed_input: dict[str, Any]) -> dict[str, Any]:
    dataset_root = Path(str(sealed_input.get("dataset_root") or "")).expanduser().resolve()
    if not dataset_root.is_dir():
        raise ValueError(f"Sealed dataset root does not exist: {dataset_root}")
    source_files = sealed_input.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ValueError("sealed_input.source_files must be a non-empty list")

    aggregate = hashlib.sha256()
    verified = 0
    total_bytes = 0
    for item in sorted(source_files, key=lambda row: str(row.get("relative_path") or "")):
        relative = str(item.get("relative_path") or "").replace("\\", "/")
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError(f"Unsafe sealed input relative path: {relative!r}")
        path = (dataset_root / relative).resolve()
        try:
            path.relative_to(dataset_root)
        except ValueError as exc:
            raise ValueError(f"Sealed input file escapes dataset root: {relative}") from exc
        if not path.is_file():
            raise ValueError(f"Sealed input file is missing: {path}")
        observed = _sha256_file(path)
        expected = str(item.get("sha256") or "").lower()
        if observed != expected:
            raise ValueError(f"Sealed input hash mismatch for {relative}")
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(observed.encode("ascii"))
        aggregate.update(b"\n")
        verified += 1
        total_bytes += path.stat().st_size

    observed_merkle = aggregate.hexdigest()
    expected_merkle = str(sealed_input.get("input_merkle_sha256") or "").lower()
    if observed_merkle != expected_merkle:
        raise ValueError("Sealed input Merkle mismatch")
    if int(sealed_input.get("source_file_count") or 0) != verified:
        raise ValueError("sealed_input.source_file_count does not match verified files")
    return {
        "status": "MATCH",
        "dataset_root": str(dataset_root),
        "verified_source_files": verified,
        "verified_total_bytes": total_bytes,
        "input_merkle_sha256": observed_merkle,
    }


def inspect_data_availability(sealed_input: dict[str, Any]) -> dict[str, Any]:
    dataset_root = Path(str(sealed_input.get("dataset_root") or "")).expanduser().resolve()
    last_closed_day = date.fromisoformat(str(sealed_input.get("last_closed_daily_bar_date")))
    by_venue: dict[str, dict[str, Any]] = {}
    markets_total = 0
    candidate_weekend_entries: set[str] = set()

    for item in sealed_input.get("universe") or []:
        if not isinstance(item, dict):
            continue
        exchange = str(item.get("exchange") or "").lower()
        symbol = str(item.get("symbol") or "")
        base = str(item.get("base") or symbol.removesuffix("_USDT")).upper()
        if exchange not in {"mexc", "gateio"} or not symbol:
            continue
        kline_path = dataset_root / exchange / "klines" / f"{symbol}.json"
        if not kline_path.is_file():
            continue
        closed_days: set[date] = set()
        future_rows = 0
        for row in _read_rows(kline_path):
            if "ts" not in row:
                continue
            bar_date = datetime.fromtimestamp(_normalized_timestamp(row["ts"]), tz=timezone.utc).date()
            if bar_date <= last_closed_day:
                closed_days.add(bar_date)
                if bar_date.weekday() == 5:
                    candidate_weekend_entries.add(bar_date.isoformat())
            else:
                future_rows += 1
        if not closed_days:
            continue

        venue = by_venue.setdefault(
            exchange,
            {
                "markets": 0,
                "bases": set(),
                "min_closed_daily_bars": None,
                "max_closed_daily_bars": 0,
                "future_or_open_rows_excluded": 0,
            },
        )
        venue["markets"] += 1
        venue["bases"].add(base)
        venue["future_or_open_rows_excluded"] += future_rows
        count = len(closed_days)
        venue["min_closed_daily_bars"] = count if venue["min_closed_daily_bars"] is None else min(venue["min_closed_daily_bars"], count)
        venue["max_closed_daily_bars"] = max(int(venue["max_closed_daily_bars"]), count)
        markets_total += 1

    return {
        "markets_total": markets_total,
        "candidate_weekend_entry_days": len(candidate_weekend_entries),
        "by_venue": {
            venue: {
                "markets": int(value["markets"]),
                "bases": len(value["bases"]),
                "min_closed_daily_bars": int(value["min_closed_daily_bars"] or 0),
                "max_closed_daily_bars": int(value["max_closed_daily_bars"]),
                "future_or_open_rows_excluded": int(value["future_or_open_rows_excluded"]),
            }
            for venue, value in sorted(by_venue.items())
        },
        "performance_metrics_computed": False,
        "signal_scores_computed": False,
        "oos_returns_read": False,
    }


def create_plan_from_sealed_source(
    source_plan_path: str | Path,
    *,
    goal_path: str | Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    source_path = Path(source_plan_path).expanduser().resolve()
    goal = Path(goal_path).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"Source plan does not exist: {source_path}")
    if not goal.is_file():
        raise ValueError(f"Goal document does not exist: {goal}")
    source = _load_json_object(source_path)
    _verify_source_plan_hash(source)
    sealed_input = copy.deepcopy(source.get("sealed_input") or {})
    verification = verify_sealed_input(sealed_input)
    availability = inspect_data_availability(sealed_input)
    created_at = created_at_utc or datetime.now(timezone.utc).isoformat()
    datetime.fromisoformat(created_at.replace("Z", "+00:00"))

    profile = base_api_cost_profile()
    notional = 500.0
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "created_at_utc": created_at,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "evaluation_allowed": False,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "oos_metrics": {},
        "observed_performance": {},
        "hypothesis": {
            "id": HYPOTHESIS_ID,
            "family": "venue_local_weekend_liquidity_calendar_window",
            "economic_claim": (
                "Weekend liquidity thinning on non-Binance venues may create a fixed calendar "
                "holding-window edge that is independent from funding, wick, momentum, listing, "
                "cross-venue and order-book signals."
            ),
            "not_funding_carry": True,
            "not_cross_venue": True,
            "not_hft_or_orderbook": True,
            "not_listing_event": True,
            "not_slow_liquidity_branch": True,
            "not_wick_rejection_branch": True,
            "not_momentum_or_breakout_branch": True,
            "acceptance_requires_net_after_costs": True,
        },
        "goal_document": {"path": str(goal), "sha256": _sha256_file(goal)},
        "source_plan": {
            "path": str(source_path),
            "schema": str(source.get("schema") or ""),
            "plan_hash": str(source["plan_hash"]),
            "artifact_sha256": _sha256_file(source_path),
            "reuse_scope": "sealed_input_only_no_performance_reuse",
        },
        "sealed_input": sealed_input,
        "sealed_input_verification": verification,
        "data_availability": availability,
        "data_access_audit": {
            "planonly_scope": "hashes_schema_timestamps_and_coverage_only",
            "market_fields_read": ["exchange", "symbol", "base", "bar.ts"],
            "ohlc_values_read": False,
            "volume_values_read_for_signal": False,
            "oos_returns_read": False,
            "signal_scores_computed": False,
            "pnl_computed": False,
            "funding_rates_read_for_signal": False,
        },
        "signal": {
            "venues": ["mexc", "gateio"],
            "instrument": "USDT linear perpetual",
            "timeframe": "1d",
            "closed_utc_daily_bars_only": True,
            "funding_inputs_used": False,
            "main_score": "fixed UTC weekend liquidity window, not optimized on train or OOS",
            "entry_rule": "enter at Saturday UTC daily open if Friday is a fully closed bar",
            "exit_rule": "exit at Monday UTC daily open proxy after Sunday close",
            "selection": "per venue choose four highest trailing 30-day quote-volume eligible markets, deterministic tie-break by base then symbol",
            "direction": "long-only equal-notional venue basket; no short leg and no cross-venue hedge",
            "tie_break": "normalized base then symbol",
            "hold_days": 2,
            "rebalance_every_days": 7,
            "calendar_anchor": "first Saturday on or after 2026-02-24",
            "overlapping_positions": False,
            "max_concurrent_portfolios_per_venue": 1,
            "parameter_selection_on_train": False,
            "parameter_selection_on_oos": False,
        },
        "eligibility": {
            "venues": ["mexc", "gateio"],
            "minimum_prior_closed_daily_bars": 60,
            "minimum_candidate_pool_markets": 8,
            "selected_markets_per_venue": 4,
            "minimum_selected_leg_capacity_quote": 500.0,
            "non_binance_baseline_required": True,
            "exclude_synthetic_equity_index_proxies": True,
            "exclude_stablecoins": True,
            "exclude_wrapped_or_staked_assets": True,
            "exclude_open_or_future_bars": True,
        },
        "economics": {
            "collateralization": "fully_collateralized_1x_research_assumption",
            "notional_quote_per_leg": notional,
            "legs_per_portfolio": 4,
            "gross_notional_quote_per_venue": 4.0 * notional,
            "orders_per_full_cycle": 8,
            "cost_profile": profile.as_dict(),
            "execution_model": {
                "entry": "post_only_if_filled_else_skip_no_taker_entry",
                "exit": "taker_exit_at_monday_open_proxy",
                "stress": "taker_exit_plus_p95_spread_impact_buffer",
            },
            "acceptance_metric": "price_net_after_costs_quote",
            "funding_pnl_excluded": True,
        },
        "validation": {
            "chronological_split": {
                "method": "fixed_common_closed_calendar_139_60",
                "train": {"start": "2025-12-26", "end": "2026-05-13", "calendar_days": 139},
                "oos": {"start": "2026-05-14", "end": "2026-07-12", "calendar_days": 60},
            },
            "walk_forward": _walk_forward_contract(),
            "acceptance_gates": {
                "input_hashes_must_match": True,
                "minimum_oos_closed_calendar_days": 60,
                "minimum_oos_portfolio_events_total": 8,
                "minimum_oos_portfolio_events_per_venue": 4,
                "minimum_unique_oos_signal_dates": 4,
                "combined_oos_net_pnl_quote_gt": 0.0,
                "combined_oos_profit_factor_gte": 1.2,
                "oos_positive_event_rate_gte": 0.58,
                "minimum_positive_combined_walk_forward_folds": 4,
                "stress_net_pnl_quote_gte": 0.0,
                "maximum_single_event_positive_pnl_share": 0.25,
                "maximum_single_base_positive_pnl_share": 0.25,
                "minimum_capacity_proxy_quote_per_selected_leg": 500.0,
            },
            "verdicts": ["ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA"],
            "acceptance_ceiling": "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        },
        "runtime_policy": {
            "plan_max_runtime_sec": MAX_PLAN_RUNTIME_SEC,
            "evaluation_max_runtime_sec": MAX_EVALUATION_RUNTIME_SEC,
            "visible_terminal_required_for_evaluation_or_probe": True,
            "network_collection_required_for_plan": False,
            "explicit_confirmation_not_required_for_short_owned_no_grid_evaluation": True,
            "short_owned_no_grid_evaluation_max_runtime_sec": MAX_EVALUATION_RUNTIME_SEC,
        },
        "prohibited": [
            "grid search",
            "OOS tuning",
            "funding carry rescue",
            "wick-rejection retuning",
            "cross-venue spread retuning",
            "listing-event retuning",
            "HFT/orderbook inputs",
            "API keys",
            "live orders",
            "leverage",
            "margin",
            "hidden long-running processes",
        ],
        "setup_registry_state": "plan_frozen_oos_not_evaluated",
        "next_allowed_action": "implement_hash_bound_no_grid_evaluator",
    }
    plan["plan_hash"] = canonical_plan_hash(plan)
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"Unsupported plan schema: {plan.get('schema')!r}")
    if canonical_plan_hash(plan) != str(plan.get("plan_hash") or "").lower():
        raise ValueError("Plan hash mismatch; frozen configuration was modified")
    if plan.get("hypothesis", {}).get("id") != HYPOTHESIS_ID:
        raise ValueError("Unexpected hypothesis id")
    if plan.get("mode") != "PlanOnly" or plan.get("research_only") is not True:
        raise ValueError("Frozen plan must be research-only PlanOnly")
    if plan.get("frozen_parameters_no_grid") is not True:
        raise ValueError("Plan must freeze a no-grid contract")
    for name in (
        "evaluation_allowed",
        "strategy_accepted",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
    ):
        if plan.get(name) is not False:
            raise ValueError(f"{name} must be false in PlanOnly")
    if plan.get("oos_metrics") or plan.get("observed_performance"):
        raise ValueError("PlanOnly artifact must not contain observed performance")
    signal = plan.get("signal") or {}
    if signal.get("hold_days") != 2:
        raise ValueError("Frozen weekend window hold_days must remain 2")
    if signal.get("rebalance_every_days") != 7:
        raise ValueError("Frozen weekend window rebalance cadence must remain 7 days")
    if signal.get("funding_inputs_used") is not False:
        raise ValueError("V6 must not use funding inputs")
    audit = plan.get("data_access_audit") or {}
    for name in (
        "ohlc_values_read",
        "volume_values_read_for_signal",
        "oos_returns_read",
        "signal_scores_computed",
        "pnl_computed",
        "funding_rates_read_for_signal",
    ):
        if audit.get(name) is not False:
            raise ValueError(f"{name} must be false during PlanOnly")


def _day_from_iso(value: str) -> int:
    return int(datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc).timestamp() // 86_400)


def _date_from_day(day: int) -> str:
    return datetime.fromtimestamp(day * 86_400, tz=timezone.utc).date().isoformat()


def _normalized_base(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


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


def _parse_market(root: Path, item: dict[str, Any], *, last_closed_day: int) -> tuple[MarketSeries, dict[str, int]]:
    exchange = str(item.get("exchange") or "").lower()
    symbol = str(item.get("symbol") or "")
    base = str(item.get("base") or symbol.removesuffix("_USDT")).upper()
    if not exchange or not symbol or not base:
        raise ValueError("Sealed universe contains an incomplete market row")
    payload = _load_json_object(root / exchange / "klines" / f"{symbol}.json")
    bars: dict[int, Bar] = {}
    invalid_bars = 0
    duplicate_bars = 0
    excluded_incomplete_bars = 0
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            invalid_bars += 1
            continue
        try:
            ts = _normalized_timestamp(row["ts"])
            day = ts // 86_400
            open_price = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            quote_volume = float(row["volume_quote"])
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_bars += 1
            continue
        values = (open_price, high, low, close, quote_volume)
        if not all(math.isfinite(value) for value in values):
            invalid_bars += 1
            continue
        if open_price <= 0.0 or high <= 0.0 or low <= 0.0 or close <= 0.0 or quote_volume < 0.0:
            invalid_bars += 1
            continue
        if high < max(open_price, close) or low > min(open_price, close) or high <= low:
            invalid_bars += 1
            continue
        if day > last_closed_day:
            excluded_incomplete_bars += 1
            continue
        if day in bars:
            duplicate_bars += 1
            continue
        bars[day] = Bar(day, ts, open_price, high, low, close, quote_volume)
    return MarketSeries(exchange=exchange, symbol=symbol, base=base, bars=bars), {
        "invalid_bars": invalid_bars,
        "duplicate_bars": duplicate_bars,
        "excluded_incomplete_bars": excluded_incomplete_bars,
    }


def load_markets(plan: dict[str, Any]) -> tuple[list[MarketSeries], dict[str, Any]]:
    validate_plan(plan)
    sealed = plan["sealed_input"]
    root = Path(str(sealed["dataset_root"])).expanduser().resolve()
    last_closed_day = _day_from_iso(str(sealed["last_closed_daily_bar_date"]))
    markets: list[MarketSeries] = []
    quality: dict[str, Any] = {"markets": {}, "market_count": 0}
    for item in sorted(
        sealed.get("universe") or [],
        key=lambda row: (str(row.get("exchange") or ""), str(row.get("symbol") or "")),
    ):
        market, diagnostics = _parse_market(root, item, last_closed_day=last_closed_day)
        markets.append(market)
        quality["markets"][f"{market.exchange}:{market.symbol}"] = diagnostics
    quality["market_count"] = len(markets)
    return markets, quality


def _contiguous_bars(market: MarketSeries, start_day: int, end_day: int) -> list[Bar] | None:
    rows = [market.bars.get(day) for day in range(start_day, end_day + 1)]
    return None if any(row is None for row in rows) else [row for row in rows if row is not None]


def _first_saturday_on_or_after(day: int) -> int:
    current = datetime.fromtimestamp(day * 86_400, tz=timezone.utc).date().weekday()
    return day + ((5 - current) % 7)


def build_venue_signals(plan: dict[str, Any], markets: list[MarketSeries], exchange: str) -> tuple[list[WeekendSignal], dict[str, Any]]:
    venue_markets = [market for market in markets if market.exchange == exchange]
    split = plan["validation"]["chronological_split"]
    anchor = _first_saturday_on_or_after(_day_from_iso(str(split["train"]["start"])))
    last_closed = _day_from_iso(str(plan["sealed_input"]["last_closed_daily_bar_date"]))
    minimum_prior = int(plan["eligibility"]["minimum_prior_closed_daily_bars"])
    minimum_pool = int(plan["eligibility"]["minimum_candidate_pool_markets"])
    selected_count = int(plan["eligibility"]["selected_markets_per_venue"])
    diagnostics = {
        "scheduled_dates": 0,
        "insufficient_candidate_dates": 0,
        "missing_execution_dates": 0,
        "signal_count": 0,
    }
    signals: list[WeekendSignal] = []
    for entry_day in range(anchor, last_closed + 1, 7):
        diagnostics["scheduled_dates"] += 1
        signal_day = entry_day - 1
        exit_day = entry_day + int(plan["signal"]["hold_days"])
        if exit_day > last_closed:
            diagnostics["missing_execution_dates"] += 1
            continue
        candidates: list[tuple[float, MarketSeries]] = []
        for market in venue_markets:
            history = _contiguous_bars(market, signal_day - minimum_prior + 1, signal_day)
            if history is None or len(history) != minimum_prior:
                continue
            if entry_day not in market.bars or exit_day not in market.bars:
                continue
            quote_volume = statistics.median(row.quote_volume for row in history[-30:])
            capacity = 0.0001 * quote_volume
            if capacity < float(plan["eligibility"]["minimum_selected_leg_capacity_quote"]):
                continue
            candidates.append((quote_volume, market))
        if len(candidates) < minimum_pool:
            diagnostics["insufficient_candidate_dates"] += 1
            continue
        selected = [
            market
            for _, market in sorted(
                candidates,
                key=lambda row: (-row[0], _normalized_base(row[1].base), row[1].symbol),
            )[:selected_count]
        ]
        if len(selected) != selected_count:
            diagnostics["insufficient_candidate_dates"] += 1
            continue
        selected_volumes = tuple(
            statistics.median(row.quote_volume for row in _contiguous_bars(market, signal_day - 29, signal_day) or [])
            for market in selected
        )
        if any(entry_day not in market.bars or exit_day not in market.bars for market in selected):
            diagnostics["missing_execution_dates"] += 1
            continue
        signals.append(
            WeekendSignal(
                exchange=exchange,
                signal_day=signal_day,
                entry_day=entry_day,
                exit_day=exit_day,
                symbols=tuple(market.symbol for market in selected),  # type: ignore[arg-type]
                bases=tuple(market.base for market in selected),  # type: ignore[arg-type]
                selected_quote_volumes=selected_volumes,  # type: ignore[arg-type]
                eligible_markets=len(candidates),
            )
        )
    diagnostics["signal_count"] = len(signals)
    return signals, diagnostics


def simulate_signal(plan: dict[str, Any], signal: WeekendSignal, markets_by_symbol: dict[str, MarketSeries]) -> WeekendEvent:
    notional = float(plan["economics"]["notional_quote_per_leg"])
    gross_pnl = 0.0
    raw_contributions: list[tuple[str, float]] = []
    for symbol, base in zip(signal.symbols, signal.bases):
        market = markets_by_symbol.get(symbol)
        if market is None:
            raise ValueError(f"Selected market is unavailable: {symbol}")
        entry_bar = market.bars.get(signal.entry_day)
        exit_bar = market.bars.get(signal.exit_day)
        if entry_bar is None or exit_bar is None:
            raise ValueError(f"Execution bar missing for selected leg: {symbol}")
        if entry_bar.open <= 0.0 or exit_bar.open <= 0.0:
            raise ValueError(f"Execution price must be positive: {symbol}")
        leg_pnl = notional * (exit_bar.open / entry_bar.open - 1.0)
        gross_pnl += leg_pnl
        raw_contributions.append((base, leg_pnl))
    costs = _expected_four_leg_costs(notional)[signal.exchange]
    normal_cost = float(costs["normal"]["total_cost_quote"])
    stress_cost = float(costs["stress"]["total_cost_quote"])
    contributions = tuple((base, value - normal_cost / 4.0) for base, value in raw_contributions)
    return WeekendEvent(
        exchange=signal.exchange,
        signal_day=signal.signal_day,
        entry_day=signal.entry_day,
        exit_day=signal.exit_day,
        symbols=signal.symbols,
        bases=signal.bases,
        gross_price_pnl_quote=gross_pnl,
        normal_cost_quote=normal_cost,
        stress_cost_quote=stress_cost,
        net_pnl_quote=gross_pnl - normal_cost,
        stress_net_pnl_quote=gross_pnl - stress_cost,
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
    positive = [value for value in values if value > 0.0]
    total = sum(positive)
    return max(positive) / total if total > 0.0 else 1.0


def _window_metrics(plan: dict[str, Any], events: list[WeekendEvent], start_day: int, end_day: int) -> dict[str, Any]:
    selected = sorted(
        [event for event in events if start_day <= event.entry_day and event.exit_day <= end_day],
        key=lambda event: (event.entry_day, event.exchange, event.symbols),
    )
    net_values = [event.net_pnl_quote for event in selected]
    stress_values = [event.stress_net_pnl_quote for event in selected]
    profit_factor, uncapped = _profit_factor(net_values)
    base_contributions: dict[str, float] = {}
    venue_values: dict[str, list[float]] = {exchange: [] for exchange in plan["signal"]["venues"]}
    for event in selected:
        venue_values[event.exchange].append(event.net_pnl_quote)
        for base, contribution in event.leg_contributions_quote:
            base_contributions[base] = base_contributions.get(base, 0.0) + contribution
    positive_base_total = sum(value for value in base_contributions.values() if value > 0.0)
    max_base_share = (
        max((value for value in base_contributions.values() if value > 0.0), default=0.0) / positive_base_total
        if positive_base_total > 0.0
        else 1.0
    )
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
    drawdown = _max_drawdown(net_values)
    peak_collateral = float(plan["economics"]["gross_notional_quote_per_venue"]) * len(plan["signal"]["venues"])
    return {
        "start": _date_from_day(start_day),
        "end": _date_from_day(end_day),
        "calendar_days": end_day - start_day + 1,
        "event_count": len(selected),
        "unique_signal_dates": len({event.signal_day for event in selected}),
        "gross_price_pnl_quote": round(sum(event.gross_price_pnl_quote for event in selected), 8),
        "net_pnl_quote": round(sum(net_values), 8),
        "net_expectancy_quote": round(statistics.mean(net_values), 8) if net_values else 0.0,
        "profit_factor": round(profit_factor, 8),
        "profit_factor_uncapped": uncapped,
        "positive_event_rate": round(sum(value > 0.0 for value in net_values) / len(net_values), 8) if net_values else 0.0,
        "stress_net_pnl_quote": round(sum(stress_values), 8),
        "total_normal_cost_quote": round(sum(event.normal_cost_quote for event in selected), 8),
        "max_drawdown_quote": round(drawdown, 8),
        "peak_allocated_collateral_quote": peak_collateral,
        "max_drawdown_fraction_of_peak_allocated_collateral": round(drawdown / peak_collateral, 8),
        "max_single_event_positive_pnl_share": round(_positive_share(net_values), 8),
        "max_single_base_positive_pnl_share": round(max_base_share, 8),
        "minimum_capacity_proxy_quote": round(min((event.capacity_proxy_quote for event in selected), default=0.0), 8) if selected else None,
        "by_venue": by_venue,
    }


def _walk_forward_metrics(plan: dict[str, Any], events: list[WeekendEvent]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for fold in plan["validation"]["walk_forward"]["folds"]:
        test = fold["test"]
        metrics = _window_metrics(plan, events, _day_from_iso(str(test["start"])), _day_from_iso(str(test["end"])))
        rows.append({"fold": int(fold["fold"]), **metrics, "positive": metrics["net_pnl_quote"] > 0.0})
    return {
        "folds_requested": 5,
        "folds_completed": len(rows),
        "positive_combined_folds": sum(bool(row["positive"]) for row in rows),
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
    oos = (metrics.get("main") or {}).get("oos") or {}
    walk = (metrics.get("main") or {}).get("walk_forward") or {}
    by_venue = oos.get("by_venue") or {}
    gate_results: dict[str, Any] = {}
    insufficient: list[str] = []

    def record(name: str, observed: Any, required: Any, passed: bool) -> None:
        gate_results[name] = {"observed": observed, "required": required, "passed": bool(passed)}

    hashes_match = data.get("input_hashes_match") is True
    record("input_hashes_must_match", hashes_match, True, hashes_match)
    if not hashes_match:
        insufficient.append("input_hashes_do_not_match")
    oos_days = int(_metric_number(data, "oos_closed_calendar_days"))
    min_days = int(gates["minimum_oos_closed_calendar_days"])
    record("minimum_oos_closed_calendar_days", oos_days, min_days, oos_days >= min_days)
    if oos_days < min_days:
        insufficient.append("oos_closed_calendar_days_below_minimum")
    events = int(_metric_number(oos, "event_count"))
    min_events = int(gates["minimum_oos_portfolio_events_total"])
    record("minimum_oos_portfolio_events_total", events, min_events, events >= min_events)
    if events < min_events:
        insufficient.append("oos_portfolio_events_total_below_minimum")
    min_per_venue = int(gates["minimum_oos_portfolio_events_per_venue"])
    for exchange in plan["signal"]["venues"]:
        count = int(_metric_number(by_venue.get(exchange) or {}, "event_count"))
        record(f"minimum_oos_portfolio_events:{exchange}", count, min_per_venue, count >= min_per_venue)
        if count < min_per_venue:
            insufficient.append(f"oos_portfolio_events_below_minimum:{exchange}")
    unique_dates = int(_metric_number(oos, "unique_signal_dates"))
    min_dates = int(gates["minimum_unique_oos_signal_dates"])
    record("minimum_unique_oos_signal_dates", unique_dates, min_dates, unique_dates >= min_dates)
    if unique_dates < min_dates:
        insufficient.append("unique_oos_signal_dates_below_minimum")
    capacity = oos.get("minimum_capacity_proxy_quote")
    capacity_available = capacity is not None and math.isfinite(_metric_number(oos, "minimum_capacity_proxy_quote", float("nan")))
    record("capacity_proxy_available", capacity_available, True, capacity_available)
    if not capacity_available:
        insufficient.append("capacity_proxy_unavailable")
    if insufficient:
        return {"verdict": "INSUFFICIENT_DATA", "reasons": insufficient, "gate_results": gate_results}

    rejection: list[str] = []

    def reject_gate(name: str, observed: Any, required: Any, passed: bool, reason: str) -> None:
        record(name, observed, required, passed)
        if not passed:
            rejection.append(reason)

    net = _metric_number(oos, "net_pnl_quote")
    reject_gate("oos_net_pnl_quote", net, "> 0", net > float(gates["combined_oos_net_pnl_quote_gt"]), "oos_net_not_positive")
    pf = _metric_number(oos, "profit_factor")
    reject_gate("oos_profit_factor", pf, f">= {gates['combined_oos_profit_factor_gte']}", pf >= float(gates["combined_oos_profit_factor_gte"]), "oos_profit_factor_below_minimum")
    rate = _metric_number(oos, "positive_event_rate")
    reject_gate("oos_positive_event_rate", rate, f">= {gates['oos_positive_event_rate_gte']}", rate >= float(gates["oos_positive_event_rate_gte"]), "oos_positive_event_rate_below_minimum")
    folds = int(_metric_number(walk, "positive_combined_folds"))
    reject_gate("positive_combined_walk_forward_folds", folds, f">= {gates['minimum_positive_combined_walk_forward_folds']}", folds >= int(gates["minimum_positive_combined_walk_forward_folds"]), "walk_forward_folds_below_minimum")
    stress = _metric_number(oos, "stress_net_pnl_quote")
    reject_gate("stress_net_pnl_quote", stress, ">= 0", stress >= float(gates["stress_net_pnl_quote_gte"]), "stress_net_negative")
    for metric, gate, reason in (
        ("max_single_event_positive_pnl_share", "maximum_single_event_positive_pnl_share", "single_event_concentration_above_maximum"),
        ("max_single_base_positive_pnl_share", "maximum_single_base_positive_pnl_share", "single_base_concentration_above_maximum"),
    ):
        observed = _metric_number(oos, metric, 1.0)
        reject_gate(metric, observed, f"<= {gates[gate]}", observed <= float(gates[gate]), reason)
    observed_capacity = _metric_number(oos, "minimum_capacity_proxy_quote")
    minimum_capacity = float(gates["minimum_capacity_proxy_quote_per_selected_leg"])
    reject_gate("minimum_capacity_proxy_quote", observed_capacity, f">= {minimum_capacity}", observed_capacity >= minimum_capacity, "capacity_proxy_below_minimum")
    return {
        "verdict": "REJECT" if rejection else "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        "reasons": rejection,
        "gate_results": gate_results,
    }


def _deterministic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _serialize_signal(signal: WeekendSignal) -> dict[str, Any]:
    row = asdict(signal)
    row["signal_date"] = _date_from_day(signal.signal_day)
    row["entry_date"] = _date_from_day(signal.entry_day)
    row["exit_date"] = _date_from_day(signal.exit_day)
    return row


def _serialize_event(event: WeekendEvent) -> dict[str, Any]:
    row = asdict(event)
    row["signal_date"] = _date_from_day(event.signal_day)
    row["entry_date"] = _date_from_day(event.entry_day)
    row["exit_date"] = _date_from_day(event.exit_day)
    return row


def _sealed_input_evidence(plan: dict[str, Any]) -> dict[str, Any]:
    try:
        verified = verify_sealed_input(plan["sealed_input"])
    except (OSError, ValueError, KeyError) as exc:
        return {
            "input_hashes_match": False,
            "error": f"{type(exc).__name__}: {exc}",
            "expected_input_merkle_sha256": str((plan.get("sealed_input") or {}).get("input_merkle_sha256") or ""),
        }
    return {
        "input_hashes_match": True,
        "expected_input_merkle_sha256": verified["input_merkle_sha256"],
        "observed_input_merkle_sha256": verified["input_merkle_sha256"],
        "verified_source_files": verified["verified_source_files"],
        "verified_source_bytes": verified["verified_total_bytes"],
    }


def _empty_evaluation_report(
    plan: dict[str, Any],
    plan_path: Path,
    evidence: dict[str, Any],
    reasons: list[str],
    started: float,
) -> dict[str, Any]:
    metrics = {"data": {**evidence, "oos_closed_calendar_days": 0}, "main": {"train": None, "oos": None, "walk_forward": None}}
    deterministic = {"plan_hash": plan["plan_hash"], "metrics": metrics, "verdict": "INSUFFICIENT_DATA", "reasons": reasons}
    return {
        "schema": "fast_first_weekend_liquidity_window_evaluation_v1",
        "created_at_utc": plan.get("created_at_utc"),
        "plan_path": str(plan_path),
        "plan_hash": plan["plan_hash"],
        "hypothesis_id": HYPOTHESIS_ID,
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "grid_search": False,
        "parameter_combinations_evaluated": 1,
        "market_data_loaded": False,
        "execution_probe_started": False,
        "paper_forward_started": False,
        "live_orders": False,
        "api_keys": False,
        "verdict": "INSUFFICIENT_DATA",
        "rejection_reasons": reasons,
        "gate_results": {},
        "metrics": metrics,
        "signal_diagnostics": {},
        "signals": {"main": []},
        "events": {"main": []},
        "deterministic_result_hash": _deterministic_hash(deterministic),
        "next_allowed_command": "repair-sealed-input-or-new-planonly",
        "runtime_sec": round(time.monotonic() - started, 3),
    }


def evaluate_plan(
    plan_path: str | Path,
    *,
    output_path: str | Path | None = None,
    progress: Any = print,
) -> dict[str, Any]:
    started = time.monotonic()
    plan_file = Path(plan_path).expanduser().resolve()
    plan = _load_json_object(plan_file)
    validate_plan(plan)
    runtime_limit = int(plan["runtime_policy"]["evaluation_max_runtime_sec"])
    destination = Path(output_path).expanduser().resolve() if output_path else plan_file.with_name("weekend_liquidity_window_evaluation.json")

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    def check_runtime() -> None:
        if time.monotonic() - started > runtime_limit:
            raise TimeoutError(f"Weekend-liquidity evaluation exceeded {runtime_limit} seconds")

    emit("[1/5] verifying frozen plan and input seal")
    evidence = _sealed_input_evidence(plan)
    if evidence.get("input_hashes_match") is not True:
        report = _empty_evaluation_report(plan, plan_file, evidence, ["sealed_input_hash_mismatch_or_missing"], started)
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination)
        return report

    check_runtime()
    emit("[2/5] loading only closed daily OHLCV bars")
    try:
        markets, quality = load_markets(plan)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        report = _empty_evaluation_report(
            plan,
            plan_file,
            {**evidence, "input_parse_error": f"{type(exc).__name__}: {exc}"},
            ["sealed_input_parse_failure"],
            started,
        )
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination)
        return report

    all_signals: list[WeekendSignal] = []
    all_events: list[WeekendEvent] = []
    diagnostics: dict[str, Any] = {}
    for exchange in plan["signal"]["venues"]:
        check_runtime()
        emit(f"[3/5] building fixed weekend-liquidity signals for {exchange}")
        signals, details = build_venue_signals(plan, markets, exchange)
        diagnostics[exchange] = details
        all_signals.extend(signals)
        venue_markets = {market.symbol: market for market in markets if market.exchange == exchange}
        all_events.extend(simulate_signal(plan, signal, venue_markets) for signal in signals)

    check_runtime()
    emit("[4/5] calculating frozen split, walk-forward and gates")
    split = plan["validation"]["chronological_split"]
    train_start = _day_from_iso(str(split["train"]["start"]))
    train_end = _day_from_iso(str(split["train"]["end"]))
    oos_start = _day_from_iso(str(split["oos"]["start"]))
    oos_end = _day_from_iso(str(split["oos"]["end"]))
    coverage = {
        exchange: len(
            {
                day
                for market in markets
                if market.exchange == exchange
                for day in market.bars
                if oos_start <= day <= oos_end
            }
        )
        for exchange in plan["signal"]["venues"]
    }
    metrics = {
        "data": {
            **evidence,
            "quality": quality,
            "oos_closed_calendar_days_by_venue": coverage,
            "oos_closed_calendar_days": min(coverage.values(), default=0),
        },
        "main": {
            "train": _window_metrics(plan, all_events, train_start, train_end),
            "oos": _window_metrics(plan, all_events, oos_start, oos_end),
            "walk_forward": _walk_forward_metrics(plan, all_events),
        },
    }
    decision = decide_verdict(plan, metrics)
    serialized_signals = {"main": [_serialize_signal(signal) for signal in sorted(all_signals, key=lambda row: (row.signal_day, row.exchange, row.symbols))]}
    serialized_events = {"main": [_serialize_event(event) for event in sorted(all_events, key=lambda row: (row.entry_day, row.exchange, row.symbols))]}
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
        "schema": "fast_first_weekend_liquidity_window_evaluation_v1",
        "created_at_utc": plan.get("created_at_utc"),
        "plan_path": str(plan_file),
        "plan_hash": plan["plan_hash"],
        "hypothesis_id": HYPOTHESIS_ID,
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "grid_search": False,
        "parameter_combinations_evaluated": 1,
        "market_data_loaded": True,
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
            "fast-edge-v6-short-execution-probe-planonly"
            if decision["verdict"] == "ACCEPT_FOR_SHORT_EXECUTION_PROBE"
            else "close-fast-first-track-no-fast-edge-found"
        ),
        "runtime_sec": round(time.monotonic() - started, 3),
    }
    check_runtime()
    emit(f"[5/5] verdict={report['verdict']} main_events={len(all_events)}")
    _write_json_atomic(destination, report)
    report["artifact_path"] = str(destination)
    return report


def validate_evaluator_readiness(plan_path: str | Path, *, expected_plan_hash: str | None = None) -> dict[str, Any]:
    plan_file = Path(plan_path).expanduser().resolve()
    plan = _load_json_object(plan_file)
    validate_plan(plan)
    observed_hash = str(plan["plan_hash"])
    if expected_plan_hash and observed_hash.lower() != expected_plan_hash.lower():
        raise ValueError(f"Expected plan hash {expected_plan_hash}, observed {observed_hash}")
    evidence = _sealed_input_evidence(plan)
    hashes_match = evidence.get("input_hashes_match") is True
    return {
        "schema": "fast_first_v6_weekend_liquidity_evaluator_readiness_v1",
        "status": "FAST_FIRST_V6_EVALUATOR_READY_OOS_NOT_RUN" if hashes_match else "FAST_FIRST_V6_EVALUATOR_NOT_READY",
        "plan_path": str(plan_file),
        "plan_hash": observed_hash,
        "plan_file_sha256": _sha256_file(plan_file),
        "evaluator_path": str(Path(__file__).resolve()),
        "evaluator_sha256": _sha256_file(Path(__file__).resolve()),
        **evidence,
        "frozen_parameters_no_grid": True,
        "parameter_combinations": 1,
        "evaluation_started": False,
        "oos_metrics_read": False,
        "grid_search": False,
        "execution_probe_started": False,
        "paper_forward_started": False,
        "live_orders": False,
        "api_keys": False,
        "next_allowed_action": "prepare_visible_owned_oos_evaluation" if hashes_match else "repair_sealed_input_or_freeze_new_planonly",
    }


def write_plan_from_sealed_source(
    source_plan_path: str | Path,
    output_path: str | Path,
    *,
    goal_path: str | Path,
    max_runtime_sec: int = MAX_PLAN_RUNTIME_SEC,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    if isinstance(max_runtime_sec, bool) or not 1 <= int(max_runtime_sec) <= MAX_PLAN_RUNTIME_SEC:
        raise ValueError(f"MaxRuntimeSec must be between 1 and {MAX_PLAN_RUNTIME_SEC}")
    started = time.monotonic()
    plan = create_plan_from_sealed_source(
        source_plan_path,
        goal_path=goal_path,
        created_at_utc=created_at_utc,
    )
    if time.monotonic() - started > int(max_runtime_sec):
        raise TimeoutError(f"PlanOnly exceeded MaxRuntimeSec={max_runtime_sec} before write")

    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"Refusing to overwrite immutable PlanOnly artifact: {target}")
    _write_json_atomic(target, plan)
    persisted = _load_json_object(target)
    validate_plan(persisted)
    return {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "output_path": str(target),
        "output_sha256": _sha256_file(target),
        "plan_hash": str(plan["plan_hash"]),
        "input_merkle_sha256": str(plan["sealed_input"]["input_merkle_sha256"]),
        "markets_total": int(plan["data_availability"]["markets_total"]),
        "candidate_weekend_entry_days": int(plan["data_availability"]["candidate_weekend_entry_days"]),
        "elapsed_sec": round(time.monotonic() - started, 3),
        "evaluation_allowed": False,
        "next_allowed_action": str(plan["next_allowed_action"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze or validate Fast-First v6 weekend-liquidity PlanOnly")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build PlanOnly from an existing sealed source plan")
    build.add_argument("--source-plan", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--goal", required=True)
    build.add_argument("--max-runtime-sec", type=int, default=MAX_PLAN_RUNTIME_SEC)
    validate = subparsers.add_parser("validate", help="Validate a v6 PlanOnly artifact")
    validate.add_argument("--plan", required=True)
    validate_seal = subparsers.add_parser(
        "validate-seal",
        help="Validate the hash-bound evaluator without reading OOS performance",
    )
    validate_seal.add_argument("--plan", required=True)
    validate_seal.add_argument("--expected-plan-hash", required=True)
    validate_seal.add_argument("--output")
    evaluate = subparsers.add_parser("evaluate", help="Run one frozen no-grid historical evaluation")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--expected-plan-hash", required=True)
    evaluate.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        result = write_plan_from_sealed_source(
            args.source_plan,
            args.output,
            goal_path=args.goal,
            max_runtime_sec=args.max_runtime_sec,
        )
    elif args.command == "validate":
        path = Path(args.plan).expanduser().resolve()
        plan = _load_json_object(path)
        validate_plan(plan)
        result = {
            "schema": PLAN_SCHEMA,
            "mode": "PlanOnly",
            "plan": str(path),
            "plan_hash": plan["plan_hash"],
            "valid": True,
            "evaluation_allowed": False,
        }
    elif args.command == "validate-seal":
        result = validate_evaluator_readiness(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        if args.output:
            target = Path(args.output).expanduser().resolve()
            _write_json_atomic(target, result)
            result = {**result, "artifact_path": str(target)}
    else:
        readiness = validate_evaluator_readiness(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        if readiness["status"] != "FAST_FIRST_V6_EVALUATOR_READY_OOS_NOT_RUN":
            raise ValueError("Evaluator readiness failed; OOS evaluation is blocked")
        result = evaluate_plan(args.plan, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
