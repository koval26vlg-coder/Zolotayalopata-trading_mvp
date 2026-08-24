from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from costs import RouteLeg, base_api_cost_profile


PLAN_SCHEMA = "fast_first_funding_directional_momentum_plan_v1"
EVALUATION_SCHEMA = "fast_first_funding_directional_momentum_evaluation_v1"
HYPOTHESIS_ID = "venue_local_funding_directional_momentum_v1"
VERDICTS = ("ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA")
SCORE_TYPES = ("main", "robustness")
MAX_PLAN_RUNTIME_SEC = 1_200
MAX_EVALUATION_RUNTIME_SEC = 1_800
MAX_DAYTIME_RUNTIME_SEC = 10_800
MAX_NIGHT_RUNTIME_SEC = 28_800


@dataclass(frozen=True)
class Bar:
    day: int
    ts: int
    open: float
    high: float
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
class DirectionalSignal:
    exchange: str
    score_type: str
    signal_day: int
    entry_day: int
    exit_day: int
    symbol: str
    base: str
    score: float
    side: str
    eligible_markets: int
    selected_quote_volume: float


@dataclass(frozen=True)
class DirectionalEvent:
    exchange: str
    score_type: str
    signal_day: int
    entry_day: int
    exit_day: int
    symbol: str
    base: str
    side: str
    price_pnl_quote: float
    funding_pnl_quote: float
    stress_funding_pnl_quote: float
    normal_cost_quote: float
    stress_cost_quote: float
    price_only_net_pnl_quote: float
    normal_total_net_pnl_quote: float
    stress_price_only_net_pnl_quote: float
    stress_total_net_pnl_quote: float
    capacity_proxy_quote: float

@dataclass(frozen=True)
class _FundingFeature:
    market: MarketSeries
    funding_score: float
    cumulative_return_5d: float
    max20: float
    quote_volume: float
    capacity_quote: float


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
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


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


def infer_funding_interval_sec(rows: Iterable[dict[str, Any]]) -> int:
    timestamps = sorted({_normalized_timestamp(row.get("ts")) for row in rows})
    if len(timestamps) < 2:
        raise ValueError("Funding interval inference requires at least two unique timestamps")
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:]) if right > left]
    if not deltas:
        raise ValueError("Funding interval inference requires at least two distinct timestamps")
    interval = int(round(float(statistics.median(deltas))))
    if interval <= 0:
        raise ValueError("Inferred funding interval must be positive")
    return interval


def _verify_source_plan_hash(source: dict[str, Any]) -> None:
    observed = str(source.get("plan_hash") or "").lower()
    if len(observed) != 64 or canonical_plan_hash(source) != observed:
        raise ValueError("Source plan hash mismatch; sealed predecessor was modified")


def verify_sealed_input(sealed_input: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(sealed_input.get("dataset_root") or "")).expanduser().resolve()
    source_files = sealed_input.get("source_files") or []
    if not root.is_dir():
        raise ValueError(f"sealed input hash mismatch: dataset root is unavailable: {root}")
    if not isinstance(source_files, list) or not source_files:
        raise ValueError("sealed input hash mismatch: source file inventory is empty")
    if len(source_files) != int(sealed_input.get("source_file_count") or 0):
        raise ValueError("sealed input hash mismatch: source file count differs from inventory")

    aggregate = hashlib.sha256()
    total_bytes = 0
    relative_paths: list[str] = []
    for row in sorted(source_files, key=lambda item: str(item.get("relative_path") or "")):
        relative = str(row.get("relative_path") or "")
        posix = PurePosixPath(relative)
        if not relative or posix.is_absolute() or ".." in posix.parts:
            raise ValueError(f"sealed input hash mismatch: unsafe relative path {relative!r}")
        path = root.joinpath(*posix.parts).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"sealed input hash mismatch: path escapes dataset root: {relative}") from exc
        if not path.is_file():
            raise ValueError(f"sealed input hash mismatch: missing source file {relative}")

        expected_digest = str(row.get("sha256") or "").lower()
        observed_digest = _sha256_file(path)
        if observed_digest != expected_digest:
            raise ValueError(f"sealed input hash mismatch: {relative}")
        expected_size = int(row.get("size_bytes") or 0)
        observed_size = path.stat().st_size
        if observed_size != expected_size:
            raise ValueError(f"sealed input hash mismatch: size changed for {relative}")

        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(observed_digest.encode("ascii"))
        aggregate.update(b"\n")
        total_bytes += observed_size
        relative_paths.append(relative)

    observed_merkle = aggregate.hexdigest()
    expected_merkle = str(sealed_input.get("input_merkle_sha256") or "").lower()
    if observed_merkle != expected_merkle:
        raise ValueError("sealed input hash mismatch: input Merkle differs from inventory")
    if "manifest.json" not in relative_paths:
        raise ValueError("sealed input hash mismatch: manifest.json is absent")

    return {
        "dataset_root": str(root),
        "verified_source_files": len(relative_paths),
        "verified_source_bytes": total_bytes,
        "input_merkle_sha256": observed_merkle,
        "status": "MATCH",
    }


def _timestamp_rows(path: Path, *, cutoff_exclusive: int | None = None, cutoff_inclusive: int | None = None) -> list[int]:
    payload = _load_json_object(path)
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError(f"rows must be a list in {path}")
    timestamps: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or "ts" not in row:
            continue
        ts = _normalized_timestamp(row["ts"])
        if cutoff_exclusive is not None and ts >= cutoff_exclusive:
            continue
        if cutoff_inclusive is not None and ts > cutoff_inclusive:
            continue
        timestamps.add(ts)
    return sorted(timestamps)


def _iso_day(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def inspect_data_availability(sealed_input: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(sealed_input["dataset_root"])).resolve()
    universe = sealed_input.get("universe") or []
    if not isinstance(universe, list):
        raise ValueError("sealed_input.universe must be a list")

    cutoff_day = date.fromisoformat(str(sealed_input["last_closed_daily_bar_date"]))
    cutoff_start = int(datetime.combine(cutoff_day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    cutoff_end = int((datetime.combine(cutoff_day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)).timestamp())
    recent_start = cutoff_end - 3 * 86_400
    source_inventory = {str(row["relative_path"]) for row in sealed_input.get("source_files") or []}

    markets: list[dict[str, Any]] = []
    missing_market_files: list[dict[str, str]] = []
    for market in sorted(
        universe,
        key=lambda item: (
            str(item.get("exchange") or ""),
            str(item.get("symbol") or ""),
        ),
    ):
        exchange = str(market.get("exchange") or "").lower()
        symbol = str(market.get("symbol") or "")
        base = str(market.get("base") or symbol.removesuffix("_USDT"))
        kline_relative = f"{exchange}/klines/{symbol}.json"
        funding_relative = f"{exchange}/funding/{symbol}.json"
        if kline_relative not in source_inventory or funding_relative not in source_inventory:
            missing_market_files.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "missing": ",".join(
                        relative
                        for relative in (kline_relative, funding_relative)
                        if relative not in source_inventory
                    ),
                }
            )
            continue

        bar_timestamps = _timestamp_rows(
            root.joinpath(*PurePosixPath(kline_relative).parts),
            cutoff_inclusive=cutoff_start,
        )
        funding_timestamps = _timestamp_rows(
            root.joinpath(*PurePosixPath(funding_relative).parts),
            cutoff_exclusive=cutoff_end,
        )
        try:
            funding_interval_sec = infer_funding_interval_sec(
                {"ts": value} for value in funding_timestamps
            )
        except ValueError:
            funding_interval_sec = None

        recent_funding_count = sum(recent_start <= value < cutoff_end for value in funding_timestamps)
        markets.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "base": base,
                "closed_daily_bars": len(bar_timestamps),
                "first_closed_daily_bar_date": _iso_day(bar_timestamps[0] if bar_timestamps else None),
                "last_closed_daily_bar_date": _iso_day(bar_timestamps[-1] if bar_timestamps else None),
                "closed_funding_settlements": len(funding_timestamps),
                "funding_settlements_last_three_complete_utc_days": recent_funding_count,
                "inferred_funding_interval_sec": funding_interval_sec,
            }
        )

    by_venue: dict[str, Any] = {}
    for exchange in ("mexc", "gateio"):
        rows = [row for row in markets if row["exchange"] == exchange]
        intervals = sorted(
            {
                int(row["inferred_funding_interval_sec"])
                for row in rows
                if row["inferred_funding_interval_sec"] is not None
            }
        )
        by_venue[exchange] = {
            "markets": len(rows),
            "markets_with_at_least_60_prior_closed_daily_bars": sum(
                int(row["closed_daily_bars"]) >= 60 for row in rows
            ),
            "markets_with_at_least_6_recent_funding_settlements": sum(
                int(row["funding_settlements_last_three_complete_utc_days"]) >= 6
                for row in rows
            ),
            "markets_with_known_positive_funding_interval": sum(
                row["inferred_funding_interval_sec"] is not None for row in rows
            ),
            "inferred_funding_intervals_sec": intervals,
        }

    return {
        "scope": "timestamp_and_coverage_metadata_only",
        "cutoff_last_closed_daily_bar_date": cutoff_day.isoformat(),
        "markets_total": len(markets),
        "universe_rows_total": len(universe),
        "missing_market_files": missing_market_files,
        "by_venue": by_venue,
        "markets": markets,
        "liquidity_and_capacity_checks_deferred_to_hash_bound_evaluator": True,
        "performance_metrics_computed": False,
    }


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


def _inclusive_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _walk_forward_contract() -> dict[str, Any]:
    return {
        "method": "anchored_expanding_no_refit",
        "initial_train": {
            "start": "2025-12-26",
            "end": "2026-04-03",
            "calendar_days": 99,
        },
        "folds": [
            {"fold": 1, "test_start": "2026-04-04", "test_end": "2026-04-23", "calendar_days": 20},
            {"fold": 2, "test_start": "2026-04-24", "test_end": "2026-05-13", "calendar_days": 20},
            {"fold": 3, "test_start": "2026-05-14", "test_end": "2026-06-02", "calendar_days": 20},
            {"fold": 4, "test_start": "2026-06-03", "test_end": "2026-06-22", "calendar_days": 20},
            {"fold": 5, "test_start": "2026-06-23", "test_end": "2026-07-12", "calendar_days": 20},
        ],
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
        raise ValueError(f"Frozen goal document does not exist: {goal}")

    source = _load_json_object(source_path)
    _verify_source_plan_hash(source)
    sealed_input = copy.deepcopy(source.get("sealed_input") or {})
    verification = verify_sealed_input(sealed_input)
    availability = inspect_data_availability(sealed_input)
    created_at = created_at_utc or datetime.now(timezone.utc).isoformat()
    datetime.fromisoformat(created_at.replace("Z", "+00:00"))

    profile = base_api_cost_profile()
    notional = 500.0

    goal_data = _load_json_object(goal)

    goal_data = _load_json_object(goal)
    venues_list = ["mexc", "gateio"]
    if "parameters" in goal_data and "venues" in goal_data["parameters"]:
        venues_list = goal_data["parameters"]["venues"]

    short_thresh = -20.0

    long_thresh = 20.0
    if "parameters" in goal_data and "thresholds_bps" in goal_data["parameters"]:
        thresh = goal_data["parameters"]["thresholds_bps"][0]
        short_thresh = -abs(float(thresh))
        long_thresh = abs(float(thresh))

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
            "family": "venue_local_directional_funding_pressure_reversal",
            "economic_claim": (
                "Extreme positive normalized funding predicts relative underperformance and extreme "
                "negative normalized funding predicts relative outperformance within the same venue."
            ),
            "acceptance_requires_price_only_net_after_costs": True,
            "not_funding_carry": True,
        },
        "goal_document": {
            "path": str(goal),
            "sha256": _sha256_file(goal),
        },
        "source_plan": {
            "path": str(source_path),
            "schema": str(source.get("schema") or ""),
            "plan_hash": str(source["plan_hash"]),
            "artifact_sha256": _sha256_file(source_path),
            "reuse_scope": "sealed_input_only",
        },
        "sealed_input": sealed_input,
        "sealed_input_verification": verification,
        "data_availability": availability,
        "data_access_audit": {
            "planonly_scope": "hashes_schema_timestamps_and_coverage_only",
            "market_fields_read": ["exchange", "symbol", "base", "bar.ts", "funding.ts"],
            "oos_returns_read": False,
            "signal_scores_computed": False,
            "pnl_computed": False,
            "funding_rates_read_for_signal": False,
            "price_or_volume_values_read_for_performance": False,
        },

        "signal": {
            "short_threshold_bps": short_thresh,
            "long_threshold_bps": long_thresh,

            "venues": venues_list,
            "instrument": "USDT linear perpetual",
            "timeframe": "1d",
            "closed_utc_daily_bars_only": True,
            "closed_funding_settlements_only": True,
            "funding_normalization_target_sec": 28_800,
            "funding_normalization_formula": "rate * 28800 / inferred_funding_interval_sec",
            "funding_score_lookback_complete_utc_days": 3,
            "main_score": "mean normalized funding settlement rate over the last three complete UTC days",
            "robustness_score": (
                "same-date cross-sectional residual main score controlling prior five-day cumulative return, "
                "MAX20 and log trailing 30-day median quote volume"
            ),
            "selection": "long two lowest scores and short two highest scores per venue",
            "tie_break": "normalized base then symbol",
            "entry": "next daily open after closed signal day",
            "exit": "third fully closed daily bar close after entry",
            "hold_days": 3,
            "rebalance_anchor_date": "2026-02-24",
            "rebalance_every_days": 3,
            "overlapping_positions": False,
            "max_concurrent_portfolios_per_venue": 1,
            "parameter_selection_on_train": False,
            "parameter_selection_on_oos": False,
        },
        "eligibility": {
            "venues": venues_list,
            "minimum_prior_closed_daily_bars": 60,
            "minimum_funding_settlements_last_three_complete_utc_days": 6,
            "known_positive_funding_interval_required": True,
            "liquidity_lookback_days": 30,
            "minimum_selected_leg_trailing_median_quote_volume": 1_000_000.0,
            "minimum_selected_leg_capacity_quote": 500.0,
            "candidate_pool_max_markets": 12,
            "minimum_candidate_pool_markets": 2,
            "selected_long_markets": 2,
            "selected_short_markets": 2,
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
            "long_notional_quote_per_venue": 2.0 * notional,
            "short_notional_quote_per_venue": 2.0 * notional,
            "orders_per_full_cycle": 8,
            "cost_profile": profile.as_dict(),
            "same_venue_four_perp_portfolio_cycle_costs": _expected_four_leg_costs(notional),
            "funding_treatment": {
                "signal_use": "primary_predictor_from_closed_settlements",
                "normal_pnl": "actual funding cash flow is reported separately from price alpha",
                "stress_pnl": "zero favorable funding credit and retain all adverse funding",
                "price_only_net_after_cost_must_be_positive": True,
                "funding_cannot_rescue_negative_price_only_result": True,
            },
            "capacity_proxy": {
                "method": "0.0001 * trailing_30d_median_quote_volume per selected leg",
                "minimum_quote_per_leg": 500.0,
                "final_depth_validation_deferred_to_short_execution_probe": True,
                "future_short_probe_p95_impact_bps_max": 10.0,
            },
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
                "minimum_oos_portfolio_events_total": 20,
                "minimum_oos_portfolio_events_per_venue": 10,
                "minimum_unique_oos_rebalance_dates": 10,
                "both_venues_oos_price_only_expectancy_gt": 0.0,
                "combined_oos_price_only_profit_factor_gte": 1.2,
                "oos_positive_portfolio_event_rate_gte": 0.6,
                "minimum_positive_combined_walk_forward_folds": 4,
                "minimum_positive_walk_forward_folds_per_venue": 3,
                "normal_price_only_net_pnl_quote_gt": 0.0,
                "robustness_price_only_net_pnl_quote_gt": 0.0,
                "stress_price_only_net_pnl_quote_gte": 0.0,
                "maximum_oos_drawdown_fraction_of_peak_allocated_collateral": 0.1,
                "maximum_single_event_positive_pnl_share": 0.25,
                "maximum_single_base_positive_pnl_share": 0.25,
                "maximum_single_venue_positive_pnl_share": 0.75,
                "maximum_break_even_holding_days": 3.0,
                "minimum_capacity_proxy_quote_per_selected_leg": 500.0,
            },
            "verdicts": list(VERDICTS),
            "acceptance_ceiling": "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        },
        "runtime_policy": {
            "plan_max_runtime_sec": MAX_PLAN_RUNTIME_SEC,
            "evaluation_max_runtime_sec": MAX_EVALUATION_RUNTIME_SEC,
            "daytime_max_runtime_sec": MAX_DAYTIME_RUNTIME_SEC,
            "night_window_max_runtime_sec": MAX_NIGHT_RUNTIME_SEC,
            "absolute_run_max_runtime_sec": MAX_NIGHT_RUNTIME_SEC,
            "night_window": {
                "timezone": "Europe/Volgograd",
                "start_local": "23:00",
                "end_local": "07:00",
                "must_finish_by_end_local": True,
            },
            "defer_runs_over_three_hours_to_night_window": True,
            "night_run_requires_candidate_specific_frozen_plan": True,
            "night_run_does_not_relax_no_grid_or_live_boundaries": True,
            "visible_terminal_required_for_evaluation_or_probe": True,
            "visible_terminal_required_for_all_artifact_writing_runs": True,
            "explicit_duration_deadline_and_stop_conditions_required": True,
            "network_collection_required_for_plan": False,
        },
        "prohibited": [
            "grid search",
            "OOS tuning",
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
    if plan.get("mode") != "PlanOnly" or plan.get("research_only") is not True:
        raise ValueError("Frozen plan must be research-only PlanOnly")
    if plan.get("frozen_parameters_no_grid") is not True:
        raise ValueError("Frozen plan requires a no-grid contract")
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
    if plan.get("oos_metrics") != {} or plan.get("observed_performance") != {}:
        raise ValueError("PlanOnly OOS and observed performance containers must be empty")

    hypothesis = plan.get("hypothesis") or {}
    if hypothesis.get("id") != HYPOTHESIS_ID:
        raise ValueError("Unexpected frozen hypothesis id")
    if hypothesis.get("acceptance_requires_price_only_net_after_costs") is not True:
        raise ValueError("Price-only net-after-cost acceptance is mandatory")

    audit = plan.get("data_access_audit") or {}
    for name in ("oos_returns_read", "signal_scores_computed", "pnl_computed", "funding_rates_read_for_signal"):
        if audit.get(name) is not False:
            raise ValueError(f"data_access_audit.{name} must be false in PlanOnly")
    if (plan.get("data_availability") or {}).get("performance_metrics_computed") is not False:
        raise ValueError("PlanOnly data availability cannot contain performance metrics")


    signal = plan.get("signal") or {}
    expected_signal = {
        "venues": signal.get("venues", ["mexc", "gateio"]),

        "instrument": "USDT linear perpetual",
        "timeframe": "1d",
        "funding_normalization_target_sec": 28_800,
        "funding_score_lookback_complete_utc_days": 3,
        "entry": "next daily open after closed signal day",
        "exit": "third fully closed daily bar close after entry",
        "hold_days": 3,
        "rebalance_anchor_date": "2026-02-24",
        "rebalance_every_days": 3,
        "overlapping_positions": False,
        "max_concurrent_portfolios_per_venue": 1,
        "parameter_selection_on_train": False,
        "parameter_selection_on_oos": False,
    }
    for name, expected in expected_signal.items():
        if signal.get(name) != expected:
            raise ValueError(f"signal.{name} must remain frozen at {expected!r}")
    if signal.get("closed_utc_daily_bars_only") is not True or signal.get("closed_funding_settlements_only") is not True:
        raise ValueError("Only closed bars and settlements are allowed")

    eligibility = plan.get("eligibility") or {}
    exact_eligibility = {
        "minimum_prior_closed_daily_bars": 60,
        "minimum_funding_settlements_last_three_complete_utc_days": 6,
        "liquidity_lookback_days": 30,
        "minimum_selected_leg_trailing_median_quote_volume": 1_000_000.0,
        "minimum_selected_leg_capacity_quote": 500.0,
        "candidate_pool_max_markets": 12,
        "minimum_candidate_pool_markets": 2,
        "selected_long_markets": 2,
        "selected_short_markets": 2,
    }
    for name, expected in exact_eligibility.items():
        if eligibility.get(name) != expected:
            raise ValueError(f"eligibility.{name} must remain frozen at {expected!r}")
    for name in (
        "known_positive_funding_interval_required",
        "non_binance_baseline_required",
        "exclude_synthetic_equity_index_proxies",
        "exclude_stablecoins",
        "exclude_wrapped_or_staked_assets",
        "exclude_open_or_future_bars",
    ):
        if eligibility.get(name) is not True:
            raise ValueError(f"eligibility.{name} must be true")

    economics = plan.get("economics") or {}
    notional = float(economics.get("notional_quote_per_leg") or 0.0)
    if not math.isclose(notional, 500.0):
        raise ValueError("economics.notional_quote_per_leg must remain frozen at 500")
    if economics.get("legs_per_portfolio") != 4 or economics.get("orders_per_full_cycle") != 8:
        raise ValueError("The frozen portfolio requires four legs and eight orders")
    profile = base_api_cost_profile()
    if economics.get("cost_profile") != profile.as_dict():
        raise ValueError("Frozen CostProfile does not match base_api_cost_profile")
    if not _costs_equal(
        economics.get("same_venue_four_perp_portfolio_cycle_costs"),
        _expected_four_leg_costs(notional),
    ):
        raise ValueError("Frozen four-leg costs do not match the unified CostProfile")
    funding = economics.get("funding_treatment") or {}
    if funding.get("price_only_net_after_cost_must_be_positive") is not True:
        raise ValueError("Funding cannot rescue negative price-only economics")
    if funding.get("funding_cannot_rescue_negative_price_only_result") is not True:
        raise ValueError("Funding rescue must remain prohibited")

    validation = plan.get("validation") or {}
    if tuple(validation.get("verdicts") or ()) != VERDICTS:
        raise ValueError("Verdict set does not match the frozen contract")
    if validation.get("acceptance_ceiling") != VERDICTS[0]:
        raise ValueError("Historical acceptance ceiling must remain a short execution probe")
    split = validation.get("chronological_split") or {}
    train = split.get("train") or {}
    oos = split.get("oos") or {}
    if train != {"start": "2025-12-26", "end": "2026-05-13", "calendar_days": 139}:
        raise ValueError("Frozen train split changed")
    if oos != {"start": "2026-05-14", "end": "2026-07-12", "calendar_days": 60}:
        raise ValueError("Frozen OOS split changed")
    for name, window in (("train", train), ("oos", oos)):
        if _inclusive_days(str(window["start"]), str(window["end"])) != int(window["calendar_days"]):
            raise ValueError(f"{name} calendar day count mismatch")
    if (validation.get("walk_forward") or {}) != _walk_forward_contract():
        raise ValueError("Walk-forward folds changed")

    runtime = plan.get("runtime_policy") or {}
    if int(runtime.get("plan_max_runtime_sec") or 0) != MAX_PLAN_RUNTIME_SEC:
        raise ValueError("Plan runtime must remain frozen at 1200 seconds")
    if int(runtime.get("evaluation_max_runtime_sec") or 0) > MAX_EVALUATION_RUNTIME_SEC:
        raise ValueError("Evaluation runtime exceeds Fast-First limit")
    if int(runtime.get("daytime_max_runtime_sec") or 0) != MAX_DAYTIME_RUNTIME_SEC:
        raise ValueError("Daytime runtime must remain frozen at three hours")
    if int(runtime.get("night_window_max_runtime_sec") or 0) != MAX_NIGHT_RUNTIME_SEC:
        raise ValueError("Night-window runtime must remain frozen at eight hours")
    if int(runtime.get("absolute_run_max_runtime_sec") or 0) != MAX_NIGHT_RUNTIME_SEC:
        raise ValueError("Absolute runtime must match the eight-hour night window")
    if runtime.get("night_window") != {
        "timezone": "Europe/Volgograd",
        "start_local": "23:00",
        "end_local": "07:00",
        "must_finish_by_end_local": True,
    }:
        raise ValueError("Night-window schedule changed")
    for name in (
        "defer_runs_over_three_hours_to_night_window",
        "night_run_requires_candidate_specific_frozen_plan",
        "night_run_does_not_relax_no_grid_or_live_boundaries",
        "visible_terminal_required_for_all_artifact_writing_runs",
        "explicit_duration_deadline_and_stop_conditions_required",
    ):
        if runtime.get(name) is not True:
            raise ValueError(f"runtime_policy.{name} must be true")
    if runtime.get("visible_terminal_required_for_evaluation_or_probe") is not True:
        raise ValueError("Visible terminal is mandatory")
    if runtime.get("network_collection_required_for_plan") is not False:
        raise ValueError("PlanOnly must not require network collection")

    sealed = plan.get("sealed_input") or {}
    if not sealed.get("source_files") or len(sealed["source_files"]) != int(sealed.get("source_file_count") or 0):
        raise ValueError("Sealed source inventory is empty or inconsistent")
    date.fromisoformat(str(sealed.get("last_closed_daily_bar_date")))
    if sealed.get("open_or_partial_bars_after_date_must_be_excluded") is not True:
        raise ValueError("Open or partial bars must be excluded")
    verification = plan.get("sealed_input_verification") or {}
    if verification.get("status") != "MATCH":
        raise ValueError("Sealed input verification must match")
    if verification.get("input_merkle_sha256") != sealed.get("input_merkle_sha256"):
        raise ValueError("Sealed input verification Merkle mismatch")

    source_plan = plan.get("source_plan") or {}
    if len(str(source_plan.get("plan_hash") or "")) != 64:
        raise ValueError("Source plan hash is missing")
    goal = plan.get("goal_document") or {}
    if len(str(goal.get("sha256") or "")) != 64:
        raise ValueError("Goal document hash is missing")
    if plan.get("setup_registry_state") != "plan_frozen_oos_not_evaluated":
        raise ValueError("Unexpected setup registry state")
    if plan.get("next_allowed_action") != "implement_hash_bound_no_grid_evaluator":
        raise ValueError("Unexpected next allowed action")


def _day_from_iso(value: str) -> int:
    return int(
        datetime.combine(
            date.fromisoformat(value),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).timestamp()
        // 86_400
    )


def _normalized_base(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _parse_market(
    root: Path,
    item: dict[str, Any],
    *,
    last_closed_day: int,
    funding_cutoff_ts: int,
) -> tuple[MarketSeries, dict[str, int]]:
    exchange = str(item.get("exchange") or "").lower()
    symbol = str(item.get("symbol") or "")
    base = str(item.get("base") or symbol.removesuffix("_USDT")).upper()
    if not exchange or not symbol or not base:
        raise ValueError("Sealed universe contains an incomplete market row")

    kline_path = root / exchange / "klines" / f"{symbol}.json"
    funding_path = root / exchange / "funding" / f"{symbol}.json"
    kline_payload = _load_json_object(kline_path)
    funding_payload = _load_json_object(funding_path)
    bars: dict[int, Bar] = {}
    invalid_bars = 0
    duplicate_bars = 0
    excluded_incomplete_bars = 0
    for row in kline_payload.get("rows") or []:
        if not isinstance(row, dict):
            invalid_bars += 1
            continue
        try:
            ts = _normalized_timestamp(row["ts"])
            day = ts // 86_400
            open_price = float(row["open"])
            high = float(row.get("high", row["open"]))
            close = float(row["close"])
            quote_volume = float(row["volume_quote"])
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_bars += 1
            continue
        values = (open_price, high, close, quote_volume)
        if not all(math.isfinite(value) for value in values):
            invalid_bars += 1
            continue
        if open_price <= 0.0 or high <= 0.0 or close <= 0.0 or quote_volume < 0.0:
            invalid_bars += 1
            continue
        if day > last_closed_day:
            excluded_incomplete_bars += 1
            continue
        if day in bars:
            duplicate_bars += 1
            continue
        bars[day] = Bar(day, ts, open_price, high, close, quote_volume)

    funding: list[tuple[int, float]] = []
    invalid_funding = 0
    excluded_future_funding = 0
    seen_funding_ts: set[int] = set()
    for row in funding_payload.get("rows") or []:
        if not isinstance(row, dict):
            invalid_funding += 1
            continue
        try:
            ts = _normalized_timestamp(row["ts"])
            rate = float(row["funding_rate"])
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_funding += 1
            continue
        if not math.isfinite(rate):
            invalid_funding += 1
            continue
        if ts >= funding_cutoff_ts:
            excluded_future_funding += 1
            continue
        if ts in seen_funding_ts:
            invalid_funding += 1
            continue
        seen_funding_ts.add(ts)
        funding.append((ts, rate))
    funding.sort()
    return MarketSeries(exchange, symbol, base, bars, funding), {
        "invalid_bars": invalid_bars,
        "duplicate_bars": duplicate_bars,
        "excluded_incomplete_bars": excluded_incomplete_bars,
        "invalid_funding": invalid_funding,
        "excluded_future_funding": excluded_future_funding,
    }


def load_markets(plan: dict[str, Any]) -> tuple[list[MarketSeries], dict[str, Any]]:
    validate_plan(plan)
    sealed = plan["sealed_input"]
    root = Path(str(sealed["dataset_root"])).expanduser().resolve()
    last_closed_day = _day_from_iso(str(sealed["last_closed_daily_bar_date"]))
    funding_cutoff_ts = (last_closed_day + 1) * 86_400
    markets: list[MarketSeries] = []
    quality: dict[str, Any] = {"markets": {}, "market_count": 0}
    for item in sorted(
        sealed.get("universe") or [],
        key=lambda row: (str(row.get("exchange") or ""), str(row.get("symbol") or "")),
    ):
        market, diagnostics = _parse_market(
            root,
            item,
            last_closed_day=last_closed_day,
            funding_cutoff_ts=funding_cutoff_ts,
        )
        markets.append(market)
        quality["markets"][f"{market.exchange}:{market.symbol}"] = diagnostics
    quality["market_count"] = len(markets)
    return markets, quality


def _historical_funding_interval_sec(market: MarketSeries, cutoff_ts: int) -> int | None:
    timestamps = [ts for ts, _ in market.funding if ts < cutoff_ts]
    if len(timestamps) < 2:
        return None
    try:
        return infer_funding_interval_sec(
            {"ts": timestamp} for timestamp in timestamps[-256:]
        )
    except ValueError:
        return None


def funding_pressure_score(
    plan: dict[str, Any],
    market: MarketSeries,
    signal_day: int,
) -> float | None:
    signal_end_ts = (signal_day + 1) * 86_400
    lookback_days = int(plan["signal"]["funding_score_lookback_complete_utc_days"])
    lookback_start_ts = signal_end_ts - lookback_days * 86_400
    historical = [
        (ts, rate)
        for ts, rate in market.funding
        if lookback_start_ts <= ts < signal_end_ts
    ]
    minimum = int(
        plan["eligibility"]["minimum_funding_settlements_last_three_complete_utc_days"]
    )
    if len(historical) < minimum:
        return None
    interval = _historical_funding_interval_sec(market, signal_end_ts)
    if interval is None or interval <= 0:
        return None
    target = float(plan["signal"]["funding_normalization_target_sec"])
    normalized = [rate * target / interval for _, rate in historical]
    return statistics.mean(normalized) if normalized else None


def _contiguous_bars(
    market: MarketSeries,
    start_day: int,
    end_day: int,
) -> list[Bar] | None:
    rows = [market.bars.get(day) for day in range(start_day, end_day + 1)]
    return None if any(row is None for row in rows) else [row for row in rows if row is not None]


def _feature_for_day(
    plan: dict[str, Any],
    market: MarketSeries,
    signal_day: int,
) -> _FundingFeature | None:
    required_days = int(plan["eligibility"]["minimum_prior_closed_daily_bars"])
    history = _contiguous_bars(market, signal_day - required_days + 1, signal_day)
    if history is None or len(history) != required_days:
        return None
    score = funding_pressure_score(plan, market, signal_day)
    if score is None:
        return None

    liquidity_days = int(plan["eligibility"]["liquidity_lookback_days"])
    liquidity_rows = history[-liquidity_days:]
    quote_volume = statistics.median(row.quote_volume for row in liquidity_rows)
    minimum_volume = float(
        plan["eligibility"]["minimum_selected_leg_trailing_median_quote_volume"]
    )
    capacity = 0.0001 * quote_volume
    minimum_capacity = float(plan["eligibility"]["minimum_selected_leg_capacity_quote"])
    if quote_volume < minimum_volume or capacity < minimum_capacity:
        return None

    prior_5d = history[-6:]
    if len(prior_5d) < 6 or prior_5d[0].close <= 0.0:
        return None
    cumulative_return = prior_5d[-1].close / prior_5d[0].close - 1.0
    max20 = max(row.high / row.open - 1.0 for row in history[-20:])
    if not all(math.isfinite(value) for value in (score, cumulative_return, max20, quote_volume)):
        return None
    return _FundingFeature(
        market=market,
        funding_score=score,
        cumulative_return_5d=cumulative_return,
        max20=max20,
        quote_volume=quote_volume,
        capacity_quote=capacity,
    )


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [matrix[index][:] + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-14:
            raise ValueError("Singular robustness regression")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                left - factor * right
                for left, right in zip(augmented[row], augmented[column])
            ]
    return [augmented[index][-1] for index in range(size)]


def _standardized(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = statistics.mean(values)
    deviation = statistics.pstdev(values)
    if deviation <= 1e-15:
        return [0.0 for _ in values]
    return [(value - mean) / deviation for value in values]


def _robustness_residuals(rows: list[_FundingFeature]) -> dict[str, float]:
    if not rows:
        return {}
    columns = [
        _standardized([row.cumulative_return_5d for row in rows]),
        _standardized([row.max20 for row in rows]),
        _standardized([math.log(max(row.quote_volume, 1.0)) for row in rows]),
    ]
    design = [
        [1.0, columns[0][index], columns[1][index], columns[2][index]]
        for index in range(len(rows))
    ]
    response = [row.funding_score for row in rows]
    width = 4
    matrix = [[0.0 for _ in range(width)] for _ in range(width)]
    vector = [0.0 for _ in range(width)]
    for features, target in zip(design, response):
        for left in range(width):
            vector[left] += features[left] * target
            for right in range(width):
                matrix[left][right] += features[left] * features[right]
    for index in range(1, width):
        matrix[index][index] += 1e-12
    try:
        coefficients = _solve_linear_system(matrix, vector)
    except ValueError:
        centered = statistics.mean(response)
        return {row.market.symbol: row.funding_score - centered for row in rows}
    return {
        row.market.symbol: row.funding_score
        - sum(coefficient * feature for coefficient, feature in zip(coefficients, features))
        for row, features in zip(rows, design)
    }


def build_venue_signals(
    plan: dict[str, Any],
    markets: list[MarketSeries],
    exchange: str,
    *,
    score_type: str = "main",
) -> tuple[list[DirectionalSignal], dict[str, Any]]:
    if score_type not in SCORE_TYPES:
        raise ValueError(f"Unknown score_type: {score_type}")
    venue_markets = [market for market in markets if market.exchange == exchange]
    anchor = _day_from_iso(str(plan["signal"]["rebalance_anchor_date"]))
    last_closed = _day_from_iso(str(plan["sealed_input"]["last_closed_daily_bar_date"]))
    cadence = int(plan["signal"]["rebalance_every_days"])
    hold_days = int(plan["signal"]["hold_days"])
    minimum_pool = int(plan["eligibility"]["minimum_candidate_pool_markets"])
    short_threshold_bps = float(plan["signal"].get("short_threshold_bps", -20.0))
    long_threshold_bps = float(plan["signal"].get("long_threshold_bps", 20.0))
    
    diagnostics: dict[str, Any] = {
        "scheduled_dates": 0,
        "insufficient_candidate_dates": 0,
        "missing_execution_dates": 0,
        "signal_count": 0,
    }
    signals: list[DirectionalSignal] = []
    
    for signal_day in range(anchor, last_closed + 1, cadence):
        diagnostics["scheduled_dates"] += 1
        entry_day = signal_day + 1
        exit_day = signal_day + hold_days

        features = [
            feature
            for market in venue_markets
            if (feature := _feature_for_day(plan, market, signal_day)) is not None
        ]
        
        if len(features) < minimum_pool:
            diagnostics["insufficient_candidate_dates"] += 1
            continue
            
        if score_type == "main":
            scores = {row.market.symbol: row.funding_score for row in features}
        else:
            scores = _robustness_residuals(features)
            
        for row in features:
            score = scores[row.market.symbol]
            score_bps = score * 10000.0
            
            side = None
            if score_bps <= short_threshold_bps:
                side = "short"
            elif score_bps >= long_threshold_bps:
                side = "long"
                
            if side is not None:
                if entry_day not in row.market.bars or exit_day not in row.market.bars:
                    diagnostics["missing_execution_dates"] += 1
                    continue
                    
                signals.append(
                    DirectionalSignal(
                        exchange=exchange,
                        score_type=score_type,
                        signal_day=signal_day,
                        entry_day=entry_day,
                        exit_day=exit_day,
                        symbol=row.market.symbol,
                        base=row.market.base,
                        score=score,
                        side=side,
                        eligible_markets=len(features),
                        selected_quote_volume=row.quote_volume,
                    )
                )
                
    diagnostics["signal_count"] = len(signals)
    return signals, diagnostics


def _funding_sum(market: MarketSeries, entry_ts: int, exit_ts_exclusive: int) -> float:
    return sum(
        rate
        for ts, rate in market.funding
        if entry_ts < ts < exit_ts_exclusive
    )


def simulate_signal(
    plan: dict[str, Any],
    signal: DirectionalSignal,
    markets_by_symbol: dict[str, MarketSeries],
) -> DirectionalEvent:
    notional = float(plan["economics"]["notional_quote_per_leg"])
    market = markets_by_symbol.get(signal.symbol)
    if market is None:
        raise ValueError(f"Selected market is unavailable: {signal.symbol}")
    entry_bar = market.bars.get(signal.entry_day)
    exit_bar = market.bars.get(signal.exit_day)
    if entry_bar is None or exit_bar is None:
        raise ValueError(f"Execution bar missing for selected leg: {signal.symbol}")
    if entry_bar.open <= 0.0 or exit_bar.close <= 0.0:
        raise ValueError(f"Execution price must be positive: {signal.symbol}")
        
    side_mult = 1.0 if signal.side == "long" else -1.0
    price_return = (exit_bar.close / entry_bar.open - 1.0)
    leg_price = side_mult * notional * price_return
    
    exit_ts_exclusive = exit_bar.ts + 86_400
    funding_sum = _funding_sum(market, entry_bar.ts, exit_ts_exclusive)
    leg_funding = -side_mult * notional * funding_sum
    leg_stress_funding = min(leg_funding, 0.0)
    
    # Cost model - adjust to 1 leg instead of 4
    costs = plan["economics"].get("same_venue_single_perp_cost", {})
    if not costs and "same_venue_four_perp_portfolio_cycle_costs" in plan["economics"]:
        four_leg = plan["economics"]["same_venue_four_perp_portfolio_cycle_costs"].get(signal.exchange, {})
        normal_cost = float(four_leg.get("normal", {}).get("total_cost_quote", 10.0)) / 4.0
        stress_cost = float(four_leg.get("stress", {}).get("total_cost_quote", 20.0)) / 4.0
    else:
        cost_profile = costs.get(signal.exchange, {})
        normal_cost = float(cost_profile.get("normal", {}).get("total_cost_quote", 2.5))
        stress_cost = float(cost_profile.get("stress", {}).get("total_cost_quote", 5.0))
        
    return DirectionalEvent(
        exchange=signal.exchange,
        score_type=signal.score_type,
        signal_day=signal.signal_day,
        entry_day=signal.entry_day,
        exit_day=signal.exit_day,
        symbol=signal.symbol,
        base=signal.base,
        side=signal.side,
        price_pnl_quote=leg_price,
        funding_pnl_quote=leg_funding,
        stress_funding_pnl_quote=leg_stress_funding,
        normal_cost_quote=normal_cost,
        stress_cost_quote=stress_cost,
        price_only_net_pnl_quote=leg_price - normal_cost,
        normal_total_net_pnl_quote=leg_price + leg_funding - normal_cost,
        stress_price_only_net_pnl_quote=leg_price - stress_cost,
        stress_total_net_pnl_quote=leg_price + leg_stress_funding - stress_cost,
        capacity_proxy_quote=signal.selected_quote_volume * 0.0001,
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


def _window_metrics(
    plan: dict[str, Any],
    events: list[DirectionalEvent],
    start_day: int,
    end_day: int,
) -> dict[str, Any]:
    selected = sorted(
        [event for event in events if start_day <= event.entry_day and event.exit_day <= end_day],
        key=lambda event: (event.entry_day, event.exchange, event.symbol),
    )
    price_only = [event.price_only_net_pnl_quote for event in selected]
    normal_total = [event.normal_total_net_pnl_quote for event in selected]
    stress_price_only = [event.stress_price_only_net_pnl_quote for event in selected]
    stress_total = [event.stress_total_net_pnl_quote for event in selected]
    price_pf, price_pf_uncapped = _profit_factor(price_only)

    base_contributions: dict[str, float] = {}
    venue_values: dict[str, list[float]] = {
        exchange: [] for exchange in plan["signal"]["venues"]
    }
    for event in selected:
        venue_values[event.exchange].append(event.price_only_net_pnl_quote)
        base_contributions[event.base] = base_contributions.get(event.base, 0.0) + event.price_only_net_pnl_quote

    positive_base_total = sum(value for value in base_contributions.values() if value > 0.0)
    max_base_share = (
        max((value for value in base_contributions.values() if value > 0.0), default=0.0)
        / positive_base_total
        if positive_base_total > 0.0
        else 1.0
    )
    venue_positive = [
        sum(value for value in values if value > 0.0)
        for values in venue_values.values()
    ]
    venue_positive_total = sum(venue_positive)
    max_venue_share = (
        max(venue_positive, default=0.0) / venue_positive_total
        if venue_positive_total > 0.0
        else 1.0
    )
    by_venue: dict[str, Any] = {}
    for exchange in plan["signal"]["venues"]:
        values = venue_values[exchange]
        venue_pf, venue_uncapped = _profit_factor(values)
        by_venue[exchange] = {
            "event_count": len(values),
            "price_only_net_pnl_quote": round(sum(values), 8),
            "price_only_net_expectancy_quote": round(statistics.mean(values), 8)
            if values
            else 0.0,
            "price_only_profit_factor": round(venue_pf, 8),
            "price_only_profit_factor_uncapped": venue_uncapped,
            "price_only_positive_event_rate": round(
                sum(value > 0.0 for value in values) / len(values), 8
            )
            if values
            else 0.0,
        }

    hold_days = int(plan["signal"]["hold_days"])
    mean_gross_price = (
        statistics.mean(event.price_pnl_quote for event in selected) if selected else 0.0
    )
    mean_cost = (
        statistics.mean(event.normal_cost_quote for event in selected) if selected else 0.0
    )
    break_even = hold_days * mean_cost / mean_gross_price if mean_gross_price > 0.0 else None
    peak_collateral = float(plan["economics"]["gross_notional_quote_per_venue"]) * len(
        plan["signal"]["venues"]
    )
    drawdown = _max_drawdown(price_only)
    return {
        "start": datetime.fromtimestamp(start_day * 86_400, tz=timezone.utc).date().isoformat(),
        "end": datetime.fromtimestamp(end_day * 86_400, tz=timezone.utc).date().isoformat(),
        "calendar_days": end_day - start_day + 1,
        "event_count": len(selected),
        "unique_rebalance_dates": len({event.signal_day for event in selected}),
        "price_only_net_pnl_quote": round(sum(price_only), 8),
        "price_only_net_expectancy_quote": round(statistics.mean(price_only), 8)
        if price_only
        else 0.0,
        "price_only_profit_factor": round(price_pf, 8),
        "price_only_profit_factor_uncapped": price_pf_uncapped,
        "price_only_positive_event_rate": round(
            sum(value > 0.0 for value in price_only) / len(price_only), 8
        )
        if price_only
        else 0.0,
        "total_net_pnl_quote": round(sum(normal_total), 8),
        "funding_pnl_quote": round(sum(event.funding_pnl_quote for event in selected), 8),
        "stress_price_only_net_pnl_quote": round(sum(stress_price_only), 8),
        "stress_total_net_pnl_quote": round(sum(stress_total), 8),
        "total_normal_cost_quote": round(sum(event.normal_cost_quote for event in selected), 8),
        "max_drawdown_quote": round(drawdown, 8),
        "peak_allocated_collateral_quote": peak_collateral,
        "max_drawdown_fraction_of_peak_allocated_collateral": round(
            drawdown / peak_collateral, 8
        ),
        "max_single_event_positive_pnl_share": round(_positive_share(price_only), 8),
        "max_single_base_positive_pnl_share": round(max_base_share, 8),
        "max_single_venue_positive_pnl_share": round(max_venue_share, 8),
        "break_even_holding_days": None if break_even is None else round(break_even, 8),
        "minimum_capacity_proxy_quote": round(
            min((event.capacity_proxy_quote for event in selected), default=0.0), 8
        )
        if selected
        else None,
        "by_venue": by_venue,
    }


def _walk_forward_metrics(
    plan: dict[str, Any],
    events: list[DirectionalEvent],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    positive_by_venue = {
        exchange: 0 for exchange in plan["signal"]["venues"]
    }
    for fold in plan["validation"]["walk_forward"]["folds"]:
        metrics = _window_metrics(
            plan,
            events,
            _day_from_iso(str(fold["test_start"])),
            _day_from_iso(str(fold["test_end"])),
        )
        positive = metrics["price_only_net_pnl_quote"] > 0.0
        for exchange in plan["signal"]["venues"]:
            if metrics["by_venue"][exchange]["price_only_net_pnl_quote"] > 0.0:
                positive_by_venue[exchange] += 1
        rows.append({"fold": int(fold["fold"]), **metrics, "positive": positive})
    return {
        "folds_requested": 5,
        "folds_completed": len(rows),
        "positive_combined_folds": sum(bool(row["positive"]) for row in rows),
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
    robustness_oos = (metrics.get("robustness") or {}).get("oos") or {}
    by_venue = oos.get("by_venue") or {}
    gate_results: dict[str, Any] = {}
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
    capacity_available = capacity is not None and math.isfinite(
        _metric_number(oos, "minimum_capacity_proxy_quote", float("nan"))
    )
    record("capacity_proxy_available", capacity_available, True, capacity_available)
    if not capacity_available:
        insufficient.append("capacity_proxy_unavailable")
    if insufficient:
        return {
            "verdict": "INSUFFICIENT_DATA",
            "reasons": insufficient,
            "gate_results": gate_results,
        }

    rejection: list[str] = []

    def reject_gate(
        name: str,
        observed: Any,
        required: Any,
        passed: bool,
        reason: str,
    ) -> None:
        record(name, observed, required, passed)
        if not passed:
            rejection.append(reason)

    price_net = _metric_number(oos, "price_only_net_pnl_quote")
    reject_gate(
        "price_only_oos_net_pnl_quote",
        price_net,
        "> 0",
        price_net > float(gates["normal_price_only_net_pnl_quote_gt"]),
        "price_only_oos_net_not_positive",
    )
    expectancy = _metric_number(oos, "price_only_net_expectancy_quote")
    reject_gate(
        "price_only_oos_expectancy_quote",
        expectancy,
        "> 0",
        expectancy > 0.0,
        "price_only_oos_expectancy_not_positive",
    )
    profit_factor = _metric_number(oos, "price_only_profit_factor")
    reject_gate(
        "price_only_oos_profit_factor",
        profit_factor,
        f">= {gates['combined_oos_price_only_profit_factor_gte']}",
        profit_factor >= float(gates["combined_oos_price_only_profit_factor_gte"]),
        "price_only_oos_profit_factor_below_minimum",
    )
    positive_rate = _metric_number(oos, "price_only_positive_event_rate")
    reject_gate(
        "price_only_oos_positive_event_rate",
        positive_rate,
        f">= {gates['oos_positive_portfolio_event_rate_gte']}",
        positive_rate >= float(gates["oos_positive_portfolio_event_rate_gte"]),
        "price_only_oos_positive_event_rate_below_minimum",
    )
    positive_folds = int(_metric_number(walk, "positive_combined_folds"))
    reject_gate(
        "positive_combined_walk_forward_folds",
        positive_folds,
        f">= {gates['minimum_positive_combined_walk_forward_folds']}",
        positive_folds >= int(gates["minimum_positive_combined_walk_forward_folds"]),
        "combined_walk_forward_folds_below_minimum",
    )
    venue_folds = walk.get("positive_folds_by_venue") or {}
    for exchange in plan["signal"]["venues"]:
        observed = int(_metric_number(venue_folds, exchange))
        reject_gate(
            f"positive_walk_forward_folds:{exchange}",
            observed,
            f">= {gates['minimum_positive_walk_forward_folds_per_venue']}",
            observed >= int(gates["minimum_positive_walk_forward_folds_per_venue"]),
            f"walk_forward_folds_below_minimum:{exchange}",
        )
        venue_expectancy = _metric_number(
            by_venue.get(exchange) or {},
            "price_only_net_expectancy_quote",
        )
        reject_gate(
            f"venue_price_only_oos_expectancy:{exchange}",
            venue_expectancy,
            "> 0",
            venue_expectancy > float(gates["both_venues_oos_price_only_expectancy_gt"]),
            f"venue_price_only_oos_expectancy_not_positive:{exchange}",
        )
    robustness_net = _metric_number(robustness_oos, "price_only_net_pnl_quote")
    reject_gate(
        "robustness_price_only_oos_net_pnl_quote",
        robustness_net,
        "> 0",
        robustness_net > float(gates["robustness_price_only_net_pnl_quote_gt"]),
        "robustness_price_only_oos_net_not_positive",
    )
    stress_net = _metric_number(oos, "stress_price_only_net_pnl_quote")
    reject_gate(
        "stress_price_only_oos_net_pnl_quote",
        stress_net,
        ">= 0",
        stress_net >= float(gates["stress_price_only_net_pnl_quote_gte"]),
        "stress_price_only_oos_net_negative",
    )
    drawdown = _metric_number(
        oos,
        "max_drawdown_fraction_of_peak_allocated_collateral",
        1.0,
    )
    reject_gate(
        "oos_drawdown_fraction",
        drawdown,
        f"<= {gates['maximum_oos_drawdown_fraction_of_peak_allocated_collateral']}",
        drawdown <= float(gates["maximum_oos_drawdown_fraction_of_peak_allocated_collateral"]),
        "oos_drawdown_fraction_above_maximum",
    )
    for metric, gate, reason in (
        ("max_single_event_positive_pnl_share", "maximum_single_event_positive_pnl_share", "single_event_concentration_above_maximum"),
        ("max_single_base_positive_pnl_share", "maximum_single_base_positive_pnl_share", "single_base_concentration_above_maximum"),
        ("max_single_venue_positive_pnl_share", "maximum_single_venue_positive_pnl_share", "single_venue_concentration_above_maximum"),
    ):
        observed = _metric_number(oos, metric, 1.0)
        reject_gate(
            metric,
            observed,
            f"<= {gates[gate]}",
            observed <= float(gates[gate]),
            reason,
        )
    break_even_raw = oos.get("break_even_holding_days")
    break_even = (
        _metric_number(oos, "break_even_holding_days", float("inf"))
        if break_even_raw is not None
        else float("inf")
    )
    reject_gate(
        "break_even_holding_days",
        break_even_raw,
        f"<= {gates['maximum_break_even_holding_days']}",
        math.isfinite(break_even)
        and break_even <= float(gates["maximum_break_even_holding_days"]),
        "break_even_holding_period_above_maximum",
    )
    observed_capacity = _metric_number(oos, "minimum_capacity_proxy_quote")
    minimum_capacity = float(gates["minimum_capacity_proxy_quote_per_selected_leg"])
    reject_gate(
        "minimum_capacity_proxy_quote",
        observed_capacity,
        f">= {minimum_capacity}",
        observed_capacity >= minimum_capacity,
        "capacity_proxy_below_minimum",
    )
    return {
        "verdict": "REJECT" if rejection else "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        "reasons": rejection,
        "gate_results": gate_results,
    }


def _deterministic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _serialize_signal(signal: DirectionalSignal) -> dict[str, Any]:
    row = asdict(signal)
    row["signal_date"] = datetime.fromtimestamp(
        signal.signal_day * 86_400, tz=timezone.utc
    ).date().isoformat()
    row["entry_date"] = datetime.fromtimestamp(
        signal.entry_day * 86_400, tz=timezone.utc
    ).date().isoformat()
    row["exit_date"] = datetime.fromtimestamp(
        signal.exit_day * 86_400, tz=timezone.utc
    ).date().isoformat()
    return row


def _serialize_event(event: DirectionalEvent) -> dict[str, Any]:
    row = asdict(event)
    row["signal_date"] = datetime.fromtimestamp(
        event.signal_day * 86_400, tz=timezone.utc
    ).date().isoformat()
    row["entry_date"] = datetime.fromtimestamp(
        event.entry_day * 86_400, tz=timezone.utc
    ).date().isoformat()
    row["exit_date"] = datetime.fromtimestamp(
        event.exit_day * 86_400, tz=timezone.utc
    ).date().isoformat()
    return row


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sealed_input_evidence(plan: dict[str, Any]) -> dict[str, Any]:
    try:
        verified = verify_sealed_input(plan["sealed_input"])
    except (OSError, ValueError, KeyError) as exc:
        return {
            "input_hashes_match": False,
            "error": f"{type(exc).__name__}: {exc}",
            "expected_input_merkle_sha256": str(
                (plan.get("sealed_input") or {}).get("input_merkle_sha256") or ""
            ),
        }
    return {
        "input_hashes_match": True,
        "expected_input_merkle_sha256": verified["input_merkle_sha256"],
        "observed_input_merkle_sha256": verified["input_merkle_sha256"],
        "verified_source_files": verified["verified_source_files"],
        "verified_source_bytes": verified["verified_source_bytes"],
    }


def _empty_evaluation_report(
    plan: dict[str, Any],
    plan_path: Path,
    evidence: dict[str, Any],
    reasons: list[str],
    started: float,
) -> dict[str, Any]:
    metrics = {
        "data": {**evidence, "oos_closed_calendar_days": 0},
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
        "signals": {name: [] for name in SCORE_TYPES},
        "events": {name: [] for name in SCORE_TYPES},
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
    plan_file = Path(plan_path).expanduser().resolve()
    plan = _load_json_object(plan_file)
    validate_plan(plan)
    runtime_limit = int(plan["runtime_policy"]["evaluation_max_runtime_sec"])
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else plan_file.with_name("funding_pressure_reversal_evaluation.json")
    )

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    def check_runtime() -> None:
        if time.monotonic() - started > runtime_limit:
            raise TimeoutError(
                f"Funding-pressure evaluation exceeded {runtime_limit} seconds"
            )

    emit("[1/6] verifying frozen plan and 195-file input seal")
    evidence = _sealed_input_evidence(plan)
    if evidence.get("input_hashes_match") is not True:
        report = _empty_evaluation_report(
            plan,
            plan_file,
            evidence,
            ["sealed_input_hash_mismatch_or_missing"],
            started,
        )
        _write_json_atomic(destination, report)
        report["artifact_path"] = str(destination)
        return report

    check_runtime()
    emit("[2/6] loading only closed daily bars and funding settlements")
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

    all_signals: dict[str, list[DirectionalSignal]] = {name: [] for name in SCORE_TYPES}
    all_events: dict[str, list[DirectionalEvent]] = {name: [] for name in SCORE_TYPES}
    diagnostics: dict[str, Any] = {name: {} for name in SCORE_TYPES}
    for score_type in SCORE_TYPES:
        for exchange in plan["signal"]["venues"]:
            check_runtime()
            emit(f"[3/6] building frozen {score_type} signals for {exchange}")
            signals, details = build_venue_signals(
                plan,
                markets,
                exchange,
                score_type=score_type,
            )
            diagnostics[score_type][exchange] = details
            all_signals[score_type].extend(signals)
            venue_markets = {
                market.symbol: market
                for market in markets
                if market.exchange == exchange
            }
            all_events[score_type].extend(
                simulate_signal(plan, signal, venue_markets) for signal in signals
            )

    check_runtime()
    emit("[4/6] calculating frozen chronological split and walk-forward folds")
    split = plan["validation"]["chronological_split"]
    train_start = _day_from_iso(str(split["train"]["start"]))
    train_end = _day_from_iso(str(split["train"]["end"]))
    oos_start = _day_from_iso(str(split["oos"]["start"]))
    oos_end = _day_from_iso(str(split["oos"]["end"]))
    coverage: dict[str, int] = {}
    for exchange in plan["signal"]["venues"]:
        venue_days = {
            day
            for market in markets
            if market.exchange == exchange
            for day in market.bars
            if oos_start <= day <= oos_end
        }
        coverage[exchange] = len(venue_days)
    metrics: dict[str, Any] = {
        "data": {
            **evidence,
            "quality": quality,
            "oos_closed_calendar_days_by_venue": coverage,
            "oos_closed_calendar_days": min(coverage.values(), default=0),
        }
    }
    for score_type in SCORE_TYPES:
        metrics[score_type] = {
            "train": _window_metrics(
                plan,
                all_events[score_type],
                train_start,
                train_end,
            ),
            "oos": _window_metrics(
                plan,
                all_events[score_type],
                oos_start,
                oos_end,
            ),
            "walk_forward": _walk_forward_metrics(plan, all_events[score_type]),
        }

    check_runtime()
    emit("[5/6] applying frozen price-only economics and evidence gates")
    decision = decide_verdict(plan, metrics)
    serialized_signals = {
        name: [
            _serialize_signal(signal)
            for signal in sorted(
                all_signals[name],
                key=lambda row: (row.signal_day, row.exchange, row.symbol),
            )
        ]
        for name in SCORE_TYPES
    }
    serialized_events = {
        name: [
            _serialize_event(event)
            for event in sorted(
                all_events[name],
                key=lambda row: (row.entry_day, row.exchange, row.symbol),
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
            "fast-edge-v4-short-execution-probe-planonly"
            if decision["verdict"] == "ACCEPT_FOR_SHORT_EXECUTION_PROBE"
            else "new-fast-first-hypothesis-planonly"
        ),
        "runtime_sec": round(time.monotonic() - started, 3),
    }
    check_runtime()
    emit(
        f"[6/6] verdict={report['verdict']} "
        f"main_events={len(all_events['main'])} "
        f"robustness_events={len(all_events['robustness'])}"
    )
    _write_json_atomic(destination, report)
    report["artifact_path"] = str(destination)
    return report


def validate_evaluator_readiness(
    plan_path: str | Path,
    *,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    plan_file = Path(plan_path).expanduser().resolve()
    plan = _load_json_object(plan_file)
    validate_plan(plan)
    observed_hash = str(plan["plan_hash"])
    if expected_plan_hash and observed_hash.lower() != expected_plan_hash.lower():
        raise ValueError(
            f"Expected plan hash {expected_plan_hash}, observed {observed_hash}"
        )
    evidence = _sealed_input_evidence(plan)
    hashes_match = evidence.get("input_hashes_match") is True
    return {
        "schema": "fast_first_v4_funding_pressure_evaluator_readiness_v1",
        "status": (
            "FAST_FIRST_V4_EVALUATOR_READY_OOS_NOT_RUN"
            if hashes_match
            else "FAST_FIRST_V4_EVALUATOR_NOT_READY"
        ),
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
        "next_allowed_action": (
            "prepare_visible_owned_oos_evaluation"
            if hashes_match
            else "repair_sealed_input_or_freeze_new_planonly"
        ),
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
    elapsed = time.monotonic() - started
    if elapsed > int(max_runtime_sec):
        raise TimeoutError(f"PlanOnly exceeded MaxRuntimeSec={max_runtime_sec} before write")

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
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
        "elapsed_sec": round(time.monotonic() - started, 3),
        "evaluation_allowed": False,
        "next_allowed_action": str(plan["next_allowed_action"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze, validate or evaluate Fast-First v4 funding-pressure reversal"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build PlanOnly from an existing sealed predecessor")
    build.add_argument("--source-plan", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--goal", required=True)
    build.add_argument("--max-runtime-sec", type=int, default=MAX_PLAN_RUNTIME_SEC)

    validate = subparsers.add_parser("validate", help="Validate an existing v4 PlanOnly artifact")
    validate.add_argument("--plan", required=True)

    validate_seal = subparsers.add_parser(
        "validate-seal",
        help="Validate the hash-bound evaluator without reading OOS performance",
    )
    validate_seal.add_argument("--plan", required=True)
    validate_seal.add_argument("--expected-plan-hash", required=True)
    validate_seal.add_argument("--output")

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Run one frozen no-grid historical evaluation",
    )
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
        if readiness["status"] != "FAST_FIRST_V4_EVALUATOR_READY_OOS_NOT_RUN":
            raise ValueError("Evaluator readiness failed; OOS evaluation is blocked")
        result = evaluate_plan(args.plan, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
