from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from feasibility_gate import Z_90_ONE_SIDED, estimator_version_hash, sha256_file
from hypothesis_contract import validate_hypothesis_contract


LOCAL_TIMEZONE = timezone(timedelta(hours=3), name="Europe/Volgograd")
INPUT_PLAN_SCHEMA = "pit_membership_drift_input_plan_v3"
FEASIBILITY_SCHEMA = "pit_membership_drift_train_feasibility_v3"
EVALUATION_SCHEMA = "pit_membership_drift_oos_evaluation_v3"
QUALITY_CERTIFICATION_SCHEMA = "pit_universe_v2_quality_certification_v1"
GATE_FAILURE_SENTINEL = 1_000_000_000_000.0
TRAIN_FEASIBILITY_STAGE = "train_feasibility"
FULL_EVALUATION_STAGE = "full_evaluation"
PLAN_STAGES = frozenset({TRAIN_FEASIBILITY_STAGE, FULL_EVALUATION_STAGE})


@dataclass(frozen=True)
class MarketSnapshot:
    exchange: str
    base: str
    symbol: str
    observed: bool
    bid: float
    ask: float
    mid: float
    spread_bps: float
    volume_24h_quote: float
    non_binance_spot: bool
    funding_rate: float | None = None
    funding_interval_sec: int | None = None
    contract_multiplier: float | None = None
    minimum_order_size: float | None = None
    maximum_order_size: float | None = None
    mark_price: float | None = None
    index_price: float | None = None
    bid_size_contracts: float | None = None
    ask_size_contracts: float | None = None


@dataclass(frozen=True)
class SnapshotCycle:
    timestamp: datetime
    successful_exchanges: frozenset[str]
    markets: dict[tuple[str, str], MarketSnapshot]


@dataclass(frozen=True)
class ActivationEvent:
    base: str
    activation_venue: str
    reference_venue: str
    activation_cycle_index: int
    confirmation_cycle_index: int
    entry_cycle_index: int
    event_date: str
    segment_end_cycle_index: int | None = None


@dataclass(frozen=True)
class EventResult:
    base: str
    activation_venue: str
    reference_venue: str
    event_date: str
    long_venue: str
    short_venue: str
    entry_cycle_index: int
    exit_cycle_index: int
    entry_timestamp: datetime
    exit_timestamp: datetime
    holding_days: float
    break_even_holding_days: float
    gross_dislocation_bps: float
    gross_price_pnl_quote: float
    cost_quote: float
    net_price_pnl_quote: float
    executable_capacity_quote_per_leg: float
    long_quantity_contracts: float
    short_quantity_contracts: float
    spread_cost_embedded_in_bbo: bool
    exit_reason: str
    scenario: str


def _market(cycle: SnapshotCycle, venue: str, base: str) -> MarketSnapshot | None:
    row = cycle.markets.get((venue, base))
    if row is None or not row.observed:
        return None
    return row


def _both_venues_succeeded(cycle: SnapshotCycle, venues: tuple[str, str]) -> bool:
    return set(venues).issubset(cycle.successful_exchanges)


def _local_date(timestamp: datetime) -> str:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("snapshot cycle timestamps must be timezone-aware")
    return timestamp.astimezone(LOCAL_TIMEZONE).date().isoformat()


def split_quality_dates(dates: Iterable[str], contract: dict[str, Any]) -> dict[str, Any]:
    validate_hypothesis_contract(contract)
    ordered = sorted(set(str(value) for value in dates))
    sample = contract["sample_plan"]
    required = int(sample["required_quality_dates"])
    if len(ordered) < required:
        raise ValueError(f"insufficient quality dates: observed={len(ordered)}, required={required}")
    selected = ordered[:required]
    train_days = int(sample["train_eligibility_days"])
    oos_days = int(sample["oos_closed_days"])
    train_dates = selected[:train_days]
    oos_dates = selected[train_days : train_days + oos_days]
    walk = contract["validation_protocol"]["walk_forward"]
    fold_days = int(walk["test_days_per_fold"])
    folds = []
    for index in range(int(walk["folds"])):
        start = index * fold_days
        test_dates = oos_dates[start : start + fold_days]
        if len(test_dates) != fold_days:
            raise ValueError("quality date split cannot construct all frozen walk-forward folds")
        folds.append(
            {
                "fold": index + 1,
                "anchored_train_dates": train_dates + oos_dates[:start],
                "test_dates": test_dates,
                "refit": False,
            }
        )
    flattened = [value for fold in folds for value in fold["test_dates"]]
    if flattened != oos_dates or len(set(flattened)) != len(flattened):
        raise ValueError("walk-forward folds must be ordered and non-overlapping")
    return {
        "selected_quality_dates": selected,
        "train_dates": train_dates,
        "oos_dates": oos_dates,
        "walk_forward_folds": folds,
    }


def split_train_feasibility_dates(dates: Iterable[str], contract: dict[str, Any]) -> dict[str, Any]:
    validate_hypothesis_contract(contract)
    ordered = sorted(set(str(value) for value in dates))
    required = int(contract["sample_plan"]["train_eligibility_days"])
    if len(ordered) < required:
        raise ValueError(f"insufficient train quality dates: observed={len(ordered)}, required={required}")
    selected = ordered[:required]
    return {
        "selected_quality_dates": selected,
        "train_dates": selected,
        "oos_dates": [],
        "walk_forward_folds": [],
    }


def detect_activation_events(
    contract: dict[str, Any], cycles: list[SnapshotCycle]
) -> list[ActivationEvent]:
    validate_hypothesis_contract(contract)
    event_rule = contract["event_definition"]
    venues = tuple(str(value) for value in contract["universe"]["venues"])
    if len(venues) != 2:
        raise ValueError("membership drift evaluator requires exactly two venues")
    prior_count = int(event_rule["reference_continuity_prior_cycles"])
    confirmation_count = int(event_rule["activation_confirmation_cycles"])
    entry_delay = int(contract["signal"]["entry_delay_cycles"])
    cooldown_days = int(event_rule["dedup_cooldown_calendar_days"])
    events: list[ActivationEvent] = []
    last_event_date: dict[tuple[str, str], datetime] = {}

    for activation_venue, reference_venue in (venues, venues[::-1]):
        for activation_index in range(prior_count, len(cycles) - confirmation_count + 1):
            confirmation_index = activation_index + confirmation_count - 1
            required_indices = range(activation_index - prior_count, confirmation_index + 1)
            if any(
                not _both_venues_succeeded(cycles[index], (activation_venue, reference_venue))
                for index in required_indices
            ):
                continue
            activation_bases = {
                base
                for venue, base in cycles[activation_index].markets
                if venue == activation_venue and _market(cycles[activation_index], venue, base) is not None
            }
            for base in sorted(activation_bases):
                if any(
                    _market(cycles[index], activation_venue, base) is not None
                    for index in range(activation_index - prior_count, activation_index)
                ):
                    continue
                if any(
                    _market(cycles[index], activation_venue, base) is None
                    for index in range(activation_index, confirmation_index + 1)
                ):
                    continue
                if any(
                    _market(cycles[index], reference_venue, base) is None
                    for index in required_indices
                ):
                    continue
                activation_row = _market(cycles[confirmation_index], activation_venue, base)
                reference_row = _market(cycles[confirmation_index], reference_venue, base)
                if activation_row is None or reference_row is None:
                    continue
                if contract["universe"]["require_non_binance_spot_at_event"] and not (
                    activation_row.non_binance_spot and reference_row.non_binance_spot
                ):
                    continue
                event_date = _local_date(cycles[activation_index].timestamp)
                event_dt = datetime.fromisoformat(event_date)
                dedup_key = (base, activation_venue)
                prior_event = last_event_date.get(dedup_key)
                if prior_event is not None and (event_dt - prior_event).days < cooldown_days:
                    continue
                last_event_date[dedup_key] = event_dt
                events.append(
                    ActivationEvent(
                        base=base,
                        activation_venue=activation_venue,
                        reference_venue=reference_venue,
                        activation_cycle_index=activation_index,
                        confirmation_cycle_index=confirmation_index,
                        entry_cycle_index=confirmation_index + entry_delay,
                        event_date=event_date,
                        segment_end_cycle_index=len(cycles) - 1,
                    )
                )
    return sorted(events, key=lambda item: (item.confirmation_cycle_index, item.base, item.activation_venue))


def _valid_executable_row(row: MarketSnapshot | None, max_spread_bps: float, min_volume: float) -> bool:
    return bool(
        row is not None
        and row.observed
        and row.bid > 0
        and row.ask >= row.bid
        and row.mid > 0
        and math.isfinite(row.mid)
        and row.spread_bps <= max_spread_bps
        and row.volume_24h_quote >= min_volume
    )


def _contracts_for_notional(row: MarketSnapshot, price: float, notional: float) -> float | None:
    multiplier = row.contract_multiplier
    minimum = row.minimum_order_size
    if multiplier is None or minimum is None or multiplier <= 0 or minimum <= 0 or price <= 0:
        return None
    quantity = notional / (price * multiplier)
    if quantity < minimum:
        return None
    if row.maximum_order_size is not None and row.maximum_order_size > 0 and quantity > row.maximum_order_size:
        return None
    return quantity


def _top_of_book_capacity_quote(
    row: MarketSnapshot,
    *,
    price: float,
    size_contracts: float | None,
) -> float:
    multiplier = row.contract_multiplier
    if (
        multiplier is None
        or multiplier <= 0
        or size_contracts is None
        or size_contracts <= 0
        or price <= 0
    ):
        return 0.0
    return price * multiplier * size_contracts


def _entry_capacity_quote(long_row: MarketSnapshot, short_row: MarketSnapshot) -> float:
    return min(
        _top_of_book_capacity_quote(
            long_row,
            price=long_row.ask,
            size_contracts=long_row.ask_size_contracts,
        ),
        _top_of_book_capacity_quote(
            short_row,
            price=short_row.bid,
            size_contracts=short_row.bid_size_contracts,
        ),
    )


def _exit_capacity_quote(exit_long: MarketSnapshot, exit_short: MarketSnapshot) -> float:
    return min(
        _top_of_book_capacity_quote(
            exit_long,
            price=exit_long.bid,
            size_contracts=exit_long.bid_size_contracts,
        ),
        _top_of_book_capacity_quote(
            exit_short,
            price=exit_short.ask,
            size_contracts=exit_short.ask_size_contracts,
        ),
    )


def _bbo_price_pnl(
    *,
    notional: float,
    entry_long: MarketSnapshot,
    entry_short: MarketSnapshot,
    exit_long: MarketSnapshot,
    exit_short: MarketSnapshot,
) -> float:
    return notional * (exit_long.bid / entry_long.ask - 1.0) + notional * (
        1.0 - exit_short.ask / entry_short.bid
    )


def _dislocation_bps(first: MarketSnapshot, second: MarketSnapshot) -> float:
    reference = (first.mid + second.mid) / 2.0
    return abs(first.mid - second.mid) / reference * 10_000.0 if reference > 0 else 0.0


def simulate_event(
    contract: dict[str, Any],
    event: ActivationEvent,
    cycles: list[SnapshotCycle],
    *,
    scenario: str,
) -> EventResult | None:
    validate_hypothesis_contract(contract)
    if scenario not in {"normal", "robustness", "stress"}:
        raise ValueError(f"unknown scenario: {scenario}")
    delay = (
        int(contract["signal"]["entry_delay_cycles"])
        if scenario == "normal"
        else int(contract[scenario]["entry_delay_cycles"])
    )
    entry_index = event.confirmation_cycle_index + delay
    if event.segment_end_cycle_index is not None and entry_index > event.segment_end_cycle_index:
        return None
    if entry_index >= len(cycles):
        return None
    entry_cycle = cycles[entry_index]
    venues = (event.activation_venue, event.reference_venue)
    if not _both_venues_succeeded(entry_cycle, venues):
        return None
    first = _market(entry_cycle, event.activation_venue, event.base)
    second = _market(entry_cycle, event.reference_venue, event.base)
    max_spread = float(contract["signal"]["max_leg_spread_bps"])
    min_volume = float(contract["signal"]["minimum_volume_24h_quote_per_leg"])
    if not _valid_executable_row(first, max_spread, min_volume) or not _valid_executable_row(
        second, max_spread, min_volume
    ):
        return None
    assert first is not None and second is not None
    gross_dislocation = _dislocation_bps(first, second)
    if gross_dislocation < float(contract["signal"]["minimum_gross_dislocation_bps"]):
        return None
    long_row, short_row = (first, second) if first.mid < second.mid else (second, first)
    notional = float(contract["position"]["notional_quote_per_leg"])
    long_quantity = _contracts_for_notional(long_row, long_row.ask, notional)
    short_quantity = _contracts_for_notional(short_row, short_row.bid, notional)
    if long_quantity is None or short_quantity is None:
        return None
    entry_capacity = _entry_capacity_quote(long_row, short_row)
    if entry_capacity < notional:
        return None
    deadline = entry_cycle.timestamp + timedelta(days=int(contract["exit"]["maximum_holding_calendar_days"]))
    valid_exits: list[tuple[int, MarketSnapshot, MarketSnapshot]] = []
    converged: tuple[int, MarketSnapshot, MarketSnapshot] | None = None
    for index in range(entry_index + 1, len(cycles)):
        cycle = cycles[index]
        if cycle.timestamp > deadline:
            break
        if not _both_venues_succeeded(cycle, (long_row.exchange, short_row.exchange)):
            continue
        exit_long = _market(cycle, long_row.exchange, event.base)
        exit_short = _market(cycle, short_row.exchange, event.base)
        if not _valid_executable_row(exit_long, max_spread, 0.0) or not _valid_executable_row(
            exit_short, max_spread, 0.0
        ):
            continue
        assert exit_long is not None and exit_short is not None
        if _exit_capacity_quote(exit_long, exit_short) < notional:
            continue
        valid_exits.append((index, exit_long, exit_short))
        if _dislocation_bps(exit_long, exit_short) <= float(contract["exit"]["convergence_threshold_bps"]):
            converged = (index, exit_long, exit_short)
            break
    selected = converged or (valid_exits[-1] if valid_exits and contract["exit"]["force_end"] else None)
    if selected is None:
        return None
    exit_index, exit_long, exit_short = selected
    gross_price_pnl = _bbo_price_pnl(
        notional=notional,
        entry_long=long_row,
        entry_short=short_row,
        exit_long=exit_long,
        exit_short=exit_short,
    )
    cycle_cost = contract["economics"]["stress_cycle_cost" if scenario == "stress" else "normal_cycle_cost"]
    cost_quote = notional * float(cycle_cost["total_bps"]) / 10_000.0
    holding_days = max(0.0, (cycles[exit_index].timestamp - entry_cycle.timestamp).total_seconds() / 86_400.0)
    break_even_holding_days = GATE_FAILURE_SENTINEL
    for candidate_index, candidate_long, candidate_short in valid_exits:
        candidate_pnl = _bbo_price_pnl(
            notional=notional,
            entry_long=long_row,
            entry_short=short_row,
            exit_long=candidate_long,
            exit_short=candidate_short,
        ) - cost_quote
        if candidate_pnl >= 0.0:
            break_even_holding_days = max(
                0.0,
                (cycles[candidate_index].timestamp - entry_cycle.timestamp).total_seconds() / 86_400.0,
            )
            break
    capacity = min(entry_capacity, _exit_capacity_quote(exit_long, exit_short))
    return EventResult(
        base=event.base,
        activation_venue=event.activation_venue,
        reference_venue=event.reference_venue,
        event_date=event.event_date,
        long_venue=long_row.exchange,
        short_venue=short_row.exchange,
        entry_cycle_index=entry_index,
        exit_cycle_index=exit_index,
        entry_timestamp=entry_cycle.timestamp,
        exit_timestamp=cycles[exit_index].timestamp,
        holding_days=holding_days,
        break_even_holding_days=break_even_holding_days,
        gross_dislocation_bps=gross_dislocation,
        gross_price_pnl_quote=gross_price_pnl,
        cost_quote=cost_quote,
        net_price_pnl_quote=gross_price_pnl - cost_quote,
        executable_capacity_quote_per_leg=capacity,
        long_quantity_contracts=long_quantity,
        short_quantity_contracts=short_quantity,
        spread_cost_embedded_in_bbo=True,
        exit_reason="convergence" if converged is not None else "force_end",
        scenario=scenario,
    )


def decide_verdict(contract: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    validate_hypothesis_contract(contract)
    gates = contract["validation_protocol"]
    sample_reasons: list[str] = []
    if int(metrics.get("oos_closed_days") or 0) < int(gates["minimum_oos_closed_days"]):
        sample_reasons.append("insufficient_oos_closed_days")
    if int(metrics.get("event_count") or 0) < int(gates["minimum_oos_portfolio_events_total"]):
        sample_reasons.append("insufficient_oos_portfolio_events")
    by_venue = metrics.get("event_count_by_activation_venue") or {}
    for venue in contract["universe"]["venues"]:
        if int(by_venue.get(venue) or 0) < int(gates["minimum_oos_portfolio_events_per_venue"]):
            sample_reasons.append(f"insufficient_oos_events_{venue}")
    if int(metrics.get("unique_event_dates") or 0) < int(gates["minimum_unique_oos_signal_dates"]):
        sample_reasons.append("insufficient_unique_oos_signal_dates")
    if float(metrics.get("dual_venue_coverage") or 0.0) < float(gates["minimum_dual_venue_coverage"]):
        sample_reasons.append("insufficient_dual_venue_coverage")
    if sample_reasons:
        return _decision("INSUFFICIENT_DATA", sample_reasons, "close_hypothesis_without_retune")

    rejection_reasons: list[str] = []
    if float(metrics.get("net_expectancy_quote") or 0.0) <= 0.0:
        rejection_reasons.append("oos_net_expectancy_not_positive")
    if float(metrics.get("profit_factor") or 0.0) < float(gates["minimum_combined_profit_factor"]):
        rejection_reasons.append("oos_profit_factor_below_gate")
    if float(metrics.get("positive_event_rate") or 0.0) < float(gates["minimum_positive_event_rate"]):
        rejection_reasons.append("oos_positive_event_rate_below_gate")
    venue_expectancy = metrics.get("net_expectancy_by_activation_venue") or {}
    for venue in contract["universe"]["venues"]:
        if float(venue_expectancy.get(venue) or 0.0) <= 0.0:
            rejection_reasons.append(f"price_only_expectancy_not_positive_{venue}")
    if float(metrics.get("normal_net_pnl_quote") or 0.0) <= 0.0:
        rejection_reasons.append("normal_price_only_pnl_not_positive")
    if float(metrics.get("robustness_net_pnl_quote") or 0.0) <= 0.0:
        rejection_reasons.append("robustness_price_only_pnl_not_positive")
    if float(metrics.get("stress_net_pnl_quote") or 0.0) < 0.0:
        rejection_reasons.append("stress_price_only_pnl_negative")
    if metrics.get("scenario_event_coverage_complete") is False:
        rejection_reasons.append("robustness_or_stress_event_coverage_incomplete")
    if int(metrics.get("positive_combined_walk_forward_folds") or 0) < int(
        gates["walk_forward"]["minimum_positive_combined_folds"]
    ):
        rejection_reasons.append("insufficient_positive_combined_walk_forward_folds")
    folds_by_venue = metrics.get("positive_walk_forward_folds_by_activation_venue") or {}
    for venue in contract["universe"]["venues"]:
        if int(folds_by_venue.get(venue) or 0) < int(gates["walk_forward"]["minimum_positive_folds_per_venue"]):
            rejection_reasons.append(f"insufficient_positive_walk_forward_folds_{venue}")
    maximum_metrics = {
        "max_drawdown_fraction": "maximum_drawdown_fraction_allocated_collateral",
        "max_single_event_positive_pnl_share": "maximum_single_event_positive_pnl_share",
        "max_single_base_positive_pnl_share": "maximum_single_base_positive_pnl_share",
        "max_single_venue_positive_pnl_share": "maximum_single_venue_positive_pnl_share",
        "break_even_holding_days_p95": "maximum_break_even_holding_days",
    }
    for metric_key, gate_key in maximum_metrics.items():
        if float(metrics.get(metric_key, math.inf)) > float(gates[gate_key]):
            rejection_reasons.append(f"{metric_key}_above_gate")
    if float(metrics.get("minimum_executable_capacity_quote_per_leg") or 0.0) < float(
        gates["minimum_capacity_quote_per_leg"]
    ):
        rejection_reasons.append("executable_capacity_below_gate")
    if rejection_reasons:
        return _decision("REJECT", rejection_reasons, "close_hypothesis_without_retune")
    return _decision(
        str(gates["maximum_historical_verdict"]),
        [],
        "run_short_execution_probe_only_after_explicit_user_approval",
    )


def _decision(verdict: str, reasons: list[str], next_action: str) -> dict[str, Any]:
    next_command = {
        "close_hypothesis_without_retune": "NO_COMMAND_TERMINAL_HYPOTHESIS_CLOSED",
        "run_short_execution_probe_only_after_explicit_user_approval": (
            "REQUEST_EXPLICIT_USER_APPROVAL_FOR_PIT_SHORT_EXECUTION_PROBE_PLANONLY"
        ),
    }.get(next_action, "NO_COMMAND_FAIL_CLOSED_UNKNOWN_ROUTE")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "next_allowed_action": next_action,
        "next_allowed_command": next_command,
        "execution_probe_allowed": verdict == "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "grid_search": False,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _powershell_literal(value: str | Path | int | float) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_mvp_command(action: str, arguments: Iterable[tuple[str, str | Path | int | float]]) -> str:
    wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
    parts = ["&", _powershell_literal(wrapper), "-Action", action]
    for name, value in arguments:
        parts.extend((f"-{name}", _powershell_literal(value)))
    return " ".join(parts)


def _plan_next_command(
    *,
    target: Path,
    plan_hash: str,
    plan_stage: str,
    sealed_input: dict[str, Any],
) -> str:
    if plan_stage == TRAIN_FEASIBILITY_STAGE:
        return _run_mvp_command(
            "fast-edge-pit-feasibility",
            (
                ("PlanPath", target),
                ("ExpectedPlanHash", plan_hash),
                ("OutputPath", target.with_name(f"{target.stem}.feasibility.json")),
                ("MaxRuntimeSec", 1800),
            ),
        )
    upstream = sealed_input.get("upstream_train_feasibility") or {}
    feasibility = upstream.get("feasibility") or {}
    return _run_mvp_command(
        "fast-edge-pit-evaluate",
        (
            ("PlanPath", target),
            ("ExpectedPlanHash", plan_hash),
            ("FeasibilityPath", str(feasibility.get("path") or "MISSING_FAIL_CLOSED")),
            ("OutputPath", target.with_name(f"{target.stem}.oos-evaluation.json")),
            ("MaxRuntimeSec", 1800),
        ),
    )


def _feasibility_next_command(
    *,
    verdict: str,
    plan_target: Path,
    feasibility_target: Path,
    sealed: dict[str, Any],
) -> str:
    if verdict != "FEASIBLE_FOR_OOS":
        return "NO_COMMAND_TERMINAL_FEASIBILITY_REJECTED"
    train_dates = list(sealed["split"]["train_dates"])
    schedule_start = (date.fromisoformat(max(train_dates)) + timedelta(days=1)).isoformat()
    return _run_mvp_command(
        "fast-edge-night-schedule-plan",
        (
            ("Hypothesis", sealed["hypothesis_id"]),
            ("DataType", sealed["data_type"]),
            ("HypothesisBankPath", sealed["hypothesis_bank"]["path"]),
            ("ScheduleStartDate", schedule_start),
            ("ScheduleNights", 14),
            ("ScheduleCollectionStage", "oos_accrual"),
            ("QualityLedgerPath", sealed["quality_ledger"]["path"]),
            ("TrainPlanPath", plan_target),
            ("FeasibilityPath", feasibility_target),
            (
                "OutputPath",
                plan_target.with_name(f"{plan_target.stem}.oos-accrual-schedule-planonly.json"),
            ),
            ("MaxRuntimeSec", 1200),
        ),
    )


def _repository_metadata() -> dict[str, str]:
    start = Path(__file__).resolve()
    repository_root: Path | None = None
    git_marker: Path | None = None
    for candidate in (start.parent, *start.parents):
        marker = candidate / ".git"
        if marker.exists():
            repository_root = candidate
            git_marker = marker
            break
    if repository_root is None or git_marker is None:
        raise ValueError("cannot seal source control provenance: .git was not found")

    if git_marker.is_dir():
        git_dir = git_marker
    else:
        marker_text = git_marker.read_text(encoding="utf-8-sig").strip()
        if not marker_text.lower().startswith("gitdir:"):
            raise ValueError(f"invalid git worktree marker: {git_marker}")
        git_dir = Path(marker_text.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = (repository_root / git_dir).resolve()

    head_text = (git_dir / "HEAD").read_text(encoding="utf-8-sig").strip()
    git_ref = "DETACHED"
    if head_text.startswith("ref:"):
        git_ref = head_text.split(":", 1)[1].strip()
        ref_path = git_dir / Path(git_ref)
        if ref_path.is_file():
            commit = ref_path.read_text(encoding="utf-8-sig").strip()
        else:
            commit = ""
            packed_refs = git_dir / "packed-refs"
            if packed_refs.is_file():
                for line in packed_refs.read_text(encoding="utf-8-sig").splitlines():
                    if not line or line.startswith(("#", "^")):
                        continue
                    value, _, ref_name = line.partition(" ")
                    if ref_name.strip() == git_ref:
                        commit = value.strip()
                        break
    else:
        commit = head_text
    if len(commit) != 40 or any(character not in "0123456789abcdefABCDEF" for character in commit):
        raise ValueError(f"cannot resolve a 40-character git commit from {git_dir / 'HEAD'}")
    return {
        "repository_root": str(repository_root),
        "git_head_sha256": commit.lower(),
        "git_ref": git_ref,
    }


def _runtime_versions() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "os_name": os.name,
    }


def _input_artifact_hashes(descriptors: list[dict[str, Any]]) -> list[dict[str, str]]:
    keys = (
        "certification_id",
        "plan_file_sha256",
        "manifest_sha256",
        "snapshots_sha256",
        "cycles_sha256",
    )
    return [{key: str(descriptor[key]) for key in keys} for descriptor in descriptors]


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON object {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def _write_json_immutable(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite immutable artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    try:
        handle = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"cannot open JSONL artifact {path}: {exc}") from exc
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield line_number, payload


def _verify_file(path_value: Any, expected_hash: Any, label: str) -> Path:
    if not path_value or not expected_hash:
        raise ValueError(f"{label} provenance is incomplete")
    target = Path(str(path_value)).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"{label} file is missing: {target}")
    observed = sha256_file(target)
    if observed != str(expected_hash):
        raise ValueError(f"{label} hash mismatch: expected={expected_hash}, observed={observed}")
    return target


def _load_quality_ledger(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_runs: dict[tuple[str, str], str] = {}
    for line_number, entry in _iter_jsonl(path):
        if entry.get("schema") != QUALITY_CERTIFICATION_SCHEMA:
            raise ValueError(f"invalid quality certification schema at {path}:{line_number}")
        certification_id = str(entry.get("certification_id") or "")
        body = {key: value for key, value in entry.items() if key != "certification_id"}
        observed_id = _json_hash(body)
        if certification_id != observed_id:
            raise ValueError(
                f"certification_id mismatch at {path}:{line_number}: "
                f"expected={certification_id}, observed={observed_id}"
            )
        if certification_id in seen_ids:
            raise ValueError(f"duplicate certification_id at {path}:{line_number}: {certification_id}")
        run_key = (str(entry.get("data_type") or ""), str(entry.get("segment_run_id") or ""))
        prior = seen_runs.get(run_key)
        if prior is not None and prior != certification_id:
            raise ValueError(f"conflicting quality certification for run_id={run_key[1]}")
        seen_ids.add(certification_id)
        seen_runs[run_key] = certification_id
        entries.append(entry)
    return entries


def _load_hypothesis(bank_path: Path, hypothesis_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    bank = _read_json(bank_path)
    hypotheses = bank.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("hypothesis bank must contain a hypotheses list")
    for hypothesis in hypotheses:
        if isinstance(hypothesis, dict) and hypothesis.get("id") == hypothesis_id:
            return bank, hypothesis
    raise ValueError(f"hypothesis id not found in bank: {hypothesis_id}")


def _certification_descriptor(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "certification_id": str(entry["certification_id"]),
        "scheduled_date": str(entry["scheduled_date"]),
        "segment_run_id": str(entry["segment_run_id"]),
        "segment_sequence": int(entry.get("segment_sequence") or 0),
        "plan_path": str(Path(str(entry["plan_path"])).expanduser().resolve()),
        "plan_hash": str(entry["plan_hash"]),
        "plan_file_sha256": str(entry["plan_file_sha256"]),
        "manifest_path": str(Path(str(entry["manifest_path"])).expanduser().resolve()),
        "manifest_sha256": str(entry["manifest_sha256"]),
        "snapshots_path": str(Path(str(entry["snapshots_path"])).expanduser().resolve()),
        "snapshots_sha256": str(entry["snapshots_sha256"]),
        "cycles_path": str(Path(str(entry["cycles_path"])).expanduser().resolve()),
        "cycles_sha256": str(entry["cycles_sha256"]),
    }


def _verify_certification_artifacts(descriptor: dict[str, Any]) -> None:
    run_id = str(descriptor["segment_run_id"])
    _verify_file(descriptor["plan_path"], descriptor["plan_file_sha256"], f"schedule plan {run_id}")
    _verify_file(descriptor["manifest_path"], descriptor["manifest_sha256"], f"manifest {run_id}")
    _verify_file(descriptor["snapshots_path"], descriptor["snapshots_sha256"], f"snapshots {run_id}")
    _verify_file(descriptor["cycles_path"], descriptor["cycles_sha256"], f"cycles {run_id}")


def build_evaluation_input_plan(
    *,
    quality_ledger_path: str | Path,
    hypothesis_bank_path: str | Path,
    hypothesis_id: str,
    output_path: str | Path,
    created_at_utc: str | None = None,
    plan_stage: str = TRAIN_FEASIBILITY_STAGE,
    train_plan_path: str | Path | None = None,
    feasibility_path: str | Path | None = None,
) -> dict[str, Any]:
    if plan_stage not in PLAN_STAGES:
        raise ValueError(f"unsupported plan_stage: {plan_stage}")
    if plan_stage == TRAIN_FEASIBILITY_STAGE and (train_plan_path or feasibility_path):
        raise ValueError("train_feasibility plan must not bind upstream train or feasibility artifacts")
    if plan_stage == FULL_EVALUATION_STAGE and (not train_plan_path or not feasibility_path):
        raise ValueError("full_evaluation plan requires train_plan_path and feasibility_path")

    ledger_target = Path(quality_ledger_path).expanduser().resolve()
    bank_target = Path(hypothesis_bank_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite immutable input plan: {target}")
    bank, hypothesis = _load_hypothesis(bank_target, hypothesis_id)
    contract = hypothesis.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("banked hypothesis must contain a frozen contract")
    contract_validation = validate_hypothesis_contract(
        contract,
        expected_id=hypothesis_id,
        expected_data_type=str(hypothesis.get("required_data_type") or ""),
    )
    entries = _load_quality_ledger(ledger_target)
    matching: list[dict[str, Any]] = []
    accepted_by_date: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("hypothesis_id") != hypothesis_id:
            continue
        if entry.get("data_type") != contract_validation["required_data_type"]:
            continue
        if entry.get("hypothesis_contract_sha256") != contract_validation["contract_hash"]:
            raise ValueError("quality certification hypothesis contract hash mismatch")
        if not bool(entry.get("technical_quality_accepted")):
            continue
        scheduled_date = str(entry.get("scheduled_date") or "")
        try:
            date.fromisoformat(scheduled_date)
        except ValueError as exc:
            raise ValueError(f"invalid scheduled_date in quality ledger: {scheduled_date}") from exc
        if scheduled_date in accepted_by_date:
            raise ValueError(f"duplicate accepted certification date: {scheduled_date}")
        accepted_by_date[scheduled_date] = entry
        matching.append(entry)
    split = (
        split_train_feasibility_dates(accepted_by_date, contract)
        if plan_stage == TRAIN_FEASIBILITY_STAGE
        else split_quality_dates(accepted_by_date, contract)
    )
    selected_entries = [accepted_by_date[value] for value in split["selected_quality_dates"]]
    descriptors = [_certification_descriptor(entry) for entry in selected_entries]
    for descriptor in descriptors:
        _verify_certification_artifacts(descriptor)
    input_merkle_root = _json_hash(descriptors)

    upstream_train_feasibility: dict[str, Any] | None = None
    if plan_stage == FULL_EVALUATION_STAGE:
        train_target = Path(str(train_plan_path)).expanduser().resolve()
        train_plan = _read_json(train_target)
        train_validation = validate_evaluation_input_plan(train_target)
        if train_validation["plan_stage"] != TRAIN_FEASIBILITY_STAGE:
            raise ValueError("upstream plan must be a train_feasibility PlanOnly")
        train_sealed = train_plan["sealed_input"]
        if train_sealed["hypothesis_id"] != hypothesis_id:
            raise ValueError("upstream train plan hypothesis mismatch")
        if train_sealed["hypothesis_contract_sha256"] != contract_validation["contract_hash"]:
            raise ValueError("upstream train plan contract mismatch")
        train_descriptors = list(train_sealed["selected_certifications"])
        if descriptors[: len(train_descriptors)] != train_descriptors:
            raise ValueError("full_evaluation train window differs from frozen train plan")
        feasibility_target = Path(str(feasibility_path)).expanduser().resolve()
        feasibility = _validate_feasibility_artifact(
            feasibility_target,
            plan_validation=train_validation,
            sealed=train_sealed,
        )
        upstream_train_feasibility = {
            "train_plan": {
                "path": str(train_target),
                "file_sha256": sha256_file(train_target),
                "plan_hash": train_validation["plan_hash"],
                "input_merkle_root": train_validation["input_merkle_root"],
            },
            "feasibility": {
                "path": str(feasibility_target),
                "file_sha256": sha256_file(feasibility_target),
                "deterministic_result_hash": feasibility["deterministic_result_hash"],
                "verdict": feasibility["verdict"],
            },
        }

    evaluator_path = Path(__file__).resolve()
    feasibility_estimator_path = evaluator_path.with_name("feasibility_gate.py")
    cost_path = evaluator_path.with_name("costs.py")
    sealed_input = {
        "schema": INPUT_PLAN_SCHEMA,
        "plan_stage": plan_stage,
        "hypothesis_id": hypothesis_id,
        "data_type": contract_validation["required_data_type"],
        "hypothesis_contract": contract,
        "hypothesis_contract_sha256": contract_validation["contract_hash"],
        "cost_profile_sha256": str(contract["economics"]["cost_profile_sha256"]),
        "hypothesis_bank": {
            "path": str(bank_target),
            "sha256": sha256_file(bank_target),
            "version": str(bank.get("version") or ""),
        },
        "quality_ledger": {
            "path": str(ledger_target),
            "file_sha256_at_plan": sha256_file(ledger_target),
            "selected_entries_sha256": input_merkle_root,
        },
        "runtime_tools": {
            "membership_drift_evaluator": {
                "path": str(evaluator_path),
                "sha256": sha256_file(evaluator_path),
            },
            "feasibility_estimator": {
                "path": str(feasibility_estimator_path),
                "sha256": sha256_file(feasibility_estimator_path),
                "version_hash": estimator_version_hash(),
            },
            "costs_module": {"path": str(cost_path), "sha256": sha256_file(cost_path)},
        },
        "source_control": _repository_metadata(),
        "runtime_versions": _runtime_versions(),
        "selected_certifications": descriptors,
        "input_artifact_hashes": _input_artifact_hashes(descriptors),
        "input_merkle_root": input_merkle_root,
        "split": split,
        "upstream_train_feasibility": upstream_train_feasibility,
        "evaluation_protocol": {
            "deterministic_repeats": int(contract["validation_protocol"]["deterministic_repeats"]),
            "grid_search": False,
            "parameter_refit": False,
            "oos_tuning": False,
        },
    }
    plan_hash = _json_hash(sealed_input)
    next_allowed_command = _plan_next_command(
        target=target,
        plan_hash=plan_hash,
        plan_stage=plan_stage,
        sealed_input=sealed_input,
    )
    plan = {
        "schema": INPUT_PLAN_SCHEMA,
        "created_at_utc": created_at_utc or _utc_now(),
        "mode": "PlanOnly",
        "research_only": True,
        "plan_artifact_path": str(target),
        "plan_hash": plan_hash,
        "sealed_input_hash": plan_hash,
        "sealed_input": sealed_input,
        "input_merkle_root": input_merkle_root,
        "forward_market_rows_read": False,
        "oos_returns_read": False,
        "pnl_computed": False,
        "evaluation_allowed": False,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "grid_search": False,
        "retune": False,
        "next_allowed_action": (
            "run_train_only_feasibility"
            if plan_stage == TRAIN_FEASIBILITY_STAGE
            else "run_visible_owned_no_grid_oos"
        ),
        "next_allowed_command": next_allowed_command,
    }
    _write_json_immutable(target, plan)
    validation = validate_evaluation_input_plan(target, plan_hash)
    return {
        "schema": INPUT_PLAN_SCHEMA,
        "decision": (
            "READY_FOR_TRAIN_FEASIBILITY"
            if plan_stage == TRAIN_FEASIBILITY_STAGE
            else "READY_FOR_OOS_EVALUATION"
        ),
        "plan_stage": plan_stage,
        "plan_path": str(target),
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": plan_hash,
        "input_merkle_root": input_merkle_root,
        "train_dates": validation["train_dates"],
        "oos_dates": validation["oos_dates"],
        "forward_market_rows_read": False,
        "oos_returns_read": False,
        "pnl_computed": False,
        "next_allowed_action": plan["next_allowed_action"],
        "next_allowed_command": next_allowed_command,
    }


def validate_evaluation_input_plan(
    plan_path: str | Path,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    target = Path(plan_path).expanduser().resolve()
    plan = _read_json(target)
    if plan.get("schema") != INPUT_PLAN_SCHEMA or plan.get("mode") != "PlanOnly":
        raise ValueError(f"expected {INPUT_PLAN_SCHEMA} PlanOnly artifact")
    sealed = plan.get("sealed_input")
    if not isinstance(sealed, dict):
        raise ValueError("sealed_input is required")
    observed_plan_hash = _json_hash(sealed)
    plan_hash = str(plan.get("plan_hash") or "")
    if observed_plan_hash != plan_hash or plan.get("sealed_input_hash") != plan_hash:
        raise ValueError("input plan seal mismatch")
    if expected_plan_hash and plan_hash != expected_plan_hash:
        raise ValueError(f"input plan hash mismatch: expected={expected_plan_hash}, observed={plan_hash}")
    if Path(str(plan.get("plan_artifact_path") or "")).expanduser().resolve() != target:
        raise ValueError("input plan artifact path mismatch")
    plan_stage = str(sealed.get("plan_stage") or "")
    if plan_stage not in PLAN_STAGES:
        raise ValueError(f"unsupported sealed plan_stage: {plan_stage}")
    expected_next_action = (
        "run_train_only_feasibility"
        if plan_stage == TRAIN_FEASIBILITY_STAGE
        else "run_visible_owned_no_grid_oos"
    )
    if plan.get("next_allowed_action") != expected_next_action:
        raise ValueError("input plan next_allowed_action mismatch")
    expected_next_command = _plan_next_command(
        target=target,
        plan_hash=plan_hash,
        plan_stage=plan_stage,
        sealed_input=sealed,
    )
    if plan.get("next_allowed_command") != expected_next_command:
        raise ValueError("input plan next_allowed_command mismatch")
    for flag in (
        "forward_market_rows_read",
        "oos_returns_read",
        "pnl_computed",
        "evaluation_allowed",
        "strategy_accepted",
        "execution_probe_allowed",
        "paper_forward_allowed",
        "live_orders",
        "api_keys",
        "grid_search",
        "retune",
    ):
        if plan.get(flag) is not False:
            raise ValueError(f"{flag} must be false in input PlanOnly")
    hypothesis_id = str(sealed.get("hypothesis_id") or "")
    data_type = str(sealed.get("data_type") or "")
    contract = sealed.get("hypothesis_contract")
    if not isinstance(contract, dict):
        raise ValueError("sealed hypothesis contract is required")
    contract_validation = validate_hypothesis_contract(
        contract,
        expected_id=hypothesis_id,
        expected_data_type=data_type,
    )
    if sealed.get("hypothesis_contract_sha256") != contract_validation["contract_hash"]:
        raise ValueError("sealed hypothesis contract hash mismatch")
    if sealed.get("cost_profile_sha256") != contract["economics"]["cost_profile_sha256"]:
        raise ValueError("sealed cost profile hash mismatch")
    bank_info = sealed.get("hypothesis_bank") or {}
    bank_path = _verify_file(bank_info.get("path"), bank_info.get("sha256"), "hypothesis bank")
    _bank, current_hypothesis = _load_hypothesis(bank_path, hypothesis_id)
    if current_hypothesis.get("contract") != contract:
        raise ValueError("sealed contract differs from current hash-bound bank entry")
    tools = sealed.get("runtime_tools")
    if not isinstance(tools, dict):
        raise ValueError("sealed runtime tools are required")
    for name in ("membership_drift_evaluator", "feasibility_estimator", "costs_module"):
        tool = tools.get(name)
        if not isinstance(tool, dict):
            raise ValueError(f"sealed runtime tool is missing: {name}")
        _verify_file(tool.get("path"), tool.get("sha256"), f"runtime tool {name}")
    if (tools.get("feasibility_estimator") or {}).get("version_hash") != estimator_version_hash():
        raise ValueError("feasibility estimator version hash mismatch")
    if sealed.get("source_control") != _repository_metadata():
        raise ValueError("source control provenance differs from the sealed input plan")
    if sealed.get("runtime_versions") != _runtime_versions():
        raise ValueError("runtime provenance differs from the sealed input plan")
    ledger_info = sealed.get("quality_ledger") or {}
    ledger_path = Path(str(ledger_info.get("path") or "")).expanduser().resolve()
    entries = _load_quality_ledger(ledger_path)
    by_id = {str(entry["certification_id"]): entry for entry in entries}
    matching_accepted_dates: dict[str, str] = {}
    for entry in entries:
        if entry.get("hypothesis_id") != hypothesis_id or entry.get("data_type") != data_type:
            continue
        if not bool(entry.get("technical_quality_accepted")):
            continue
        scheduled_date = str(entry.get("scheduled_date") or "")
        prior = matching_accepted_dates.get(scheduled_date)
        if prior is not None and prior != str(entry["certification_id"]):
            raise ValueError(f"duplicate accepted certification date: {scheduled_date}")
        matching_accepted_dates[scheduled_date] = str(entry["certification_id"])
    accepted_dates: dict[str, str] = {}
    descriptors = sealed.get("selected_certifications")
    if not isinstance(descriptors, list):
        raise ValueError("selected_certifications must be a list")
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            raise ValueError("selected certification descriptor must be an object")
        certification_id = str(descriptor.get("certification_id") or "")
        entry = by_id.get(certification_id)
        if entry is None:
            raise ValueError(f"selected quality certification is missing from ledger: {certification_id}")
        if not bool(entry.get("technical_quality_accepted")):
            raise ValueError(f"selected quality certification is not accepted: {certification_id}")
        if entry.get("hypothesis_contract_sha256") != contract_validation["contract_hash"]:
            raise ValueError("selected certification contract hash mismatch")
        observed_descriptor = _certification_descriptor(entry)
        if descriptor != observed_descriptor:
            raise ValueError(f"selected certification descriptor mismatch: {certification_id}")
        scheduled_date = str(entry["scheduled_date"])
        prior = accepted_dates.get(scheduled_date)
        if prior is not None and prior != certification_id:
            raise ValueError(f"duplicate accepted certification date: {scheduled_date}")
        accepted_dates[scheduled_date] = certification_id
        _verify_certification_artifacts(descriptor)
    input_merkle_root = _json_hash(descriptors)
    if input_merkle_root != sealed.get("input_merkle_root") or input_merkle_root != ledger_info.get(
        "selected_entries_sha256"
    ):
        raise ValueError("input Merkle root mismatch")
    if sealed.get("input_artifact_hashes") != _input_artifact_hashes(descriptors):
        raise ValueError("sealed input artifact hashes mismatch")
    split = sealed.get("split")
    expected_split = (
        split_train_feasibility_dates(matching_accepted_dates, contract)
        if plan_stage == TRAIN_FEASIBILITY_STAGE
        else split_quality_dates(matching_accepted_dates, contract)
    )
    if not isinstance(split, dict) or split != expected_split:
        raise ValueError("sealed chronological split mismatch")
    selected_ids = [str(descriptor["certification_id"]) for descriptor in descriptors]
    expected_ids = [matching_accepted_dates[value] for value in split["selected_quality_dates"]]
    if selected_ids != expected_ids:
        raise ValueError("selected certifications are not the earliest frozen chronological window")

    upstream = sealed.get("upstream_train_feasibility")
    if plan_stage == TRAIN_FEASIBILITY_STAGE:
        if upstream is not None:
            raise ValueError("train_feasibility plan must not contain upstream OOS authorization")
    else:
        if not isinstance(upstream, dict):
            raise ValueError("full_evaluation plan requires sealed upstream train feasibility")
        train_info = upstream.get("train_plan")
        feasibility_info = upstream.get("feasibility")
        if not isinstance(train_info, dict) or not isinstance(feasibility_info, dict):
            raise ValueError("upstream train feasibility provenance is incomplete")
        train_target = _verify_file(
            train_info.get("path"), train_info.get("file_sha256"), "upstream train plan"
        )
        train_validation = validate_evaluation_input_plan(train_target, str(train_info.get("plan_hash") or ""))
        if train_validation["plan_stage"] != TRAIN_FEASIBILITY_STAGE:
            raise ValueError("upstream plan is not train_feasibility")
        if train_validation["input_merkle_root"] != train_info.get("input_merkle_root"):
            raise ValueError("upstream train input Merkle root mismatch")
        train_plan = _read_json(train_target)
        train_sealed = train_plan["sealed_input"]
        if train_sealed["hypothesis_contract_sha256"] != sealed["hypothesis_contract_sha256"]:
            raise ValueError("upstream train hypothesis contract mismatch")
        train_descriptors = list(train_sealed["selected_certifications"])
        if descriptors[: len(train_descriptors)] != train_descriptors:
            raise ValueError("full_evaluation train window differs from upstream train plan")
        feasibility_target = _verify_file(
            feasibility_info.get("path"),
            feasibility_info.get("file_sha256"),
            "upstream feasibility",
        )
        feasibility = _validate_feasibility_artifact(
            feasibility_target,
            plan_validation=train_validation,
            sealed=train_sealed,
        )
        if feasibility.get("deterministic_result_hash") != feasibility_info.get(
            "deterministic_result_hash"
        ):
            raise ValueError("upstream feasibility result hash mismatch")
        if feasibility_info.get("verdict") != "FEASIBLE_FOR_OOS":
            raise ValueError("upstream feasibility verdict is not FEASIBLE_FOR_OOS")
    return {
        "schema": INPUT_PLAN_SCHEMA,
        "verdict": "VALID",
        "plan_path": str(target),
        "plan_file_sha256": sha256_file(target),
        "plan_hash": plan_hash,
        "plan_stage": plan_stage,
        "input_merkle_root": input_merkle_root,
        "train_dates": len(split["train_dates"]),
        "oos_dates": len(split["oos_dates"]),
        "selected_certifications": len(descriptors),
    }


def _as_float(value: Any, *, label: str, allow_zero: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"{label} must be finite and {'non-negative' if allow_zero else 'positive'}")
    return number


def _optional_float(
    value: Any,
    *,
    label: str,
    allow_negative: bool = False,
) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric when present") from exc
    if not math.isfinite(number) or (not allow_negative and number < 0):
        raise ValueError(f"{label} must be finite")
    return number


def _load_segment_cycles(descriptor: dict[str, Any]) -> list[SnapshotCycle]:
    run_id = str(descriptor["segment_run_id"])
    cycles_path = Path(str(descriptor["cycles_path"])).expanduser().resolve()
    snapshots_path = Path(str(descriptor["snapshots_path"])).expanduser().resolve()
    cycle_rows: dict[int, dict[str, Any]] = {}
    for line_number, row in _iter_jsonl(cycles_path):
        try:
            cycle_number = int(row.get("cycle") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid cycle number at {cycles_path}:{line_number}") from exc
        if cycle_number <= 0 or cycle_number in cycle_rows:
            raise ValueError(f"duplicate or invalid cycle at {cycles_path}:{line_number}")
        if str(row.get("run_id") or "") != run_id:
            raise ValueError(f"cycle run_id mismatch at {cycles_path}:{line_number}")
        cycle_rows[cycle_number] = row
    markets_by_cycle: dict[int, dict[tuple[str, str], MarketSnapshot]] = defaultdict(dict)
    for line_number, row in _iter_jsonl(snapshots_path):
        try:
            cycle_number = int(row.get("cycle") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid snapshot cycle at {snapshots_path}:{line_number}") from exc
        if cycle_number not in cycle_rows:
            raise ValueError(f"snapshot references unknown cycle at {snapshots_path}:{line_number}")
        if str(row.get("run_id") or "") != run_id:
            raise ValueError(f"snapshot run_id mismatch at {snapshots_path}:{line_number}")
        exchange = str(row.get("exchange") or "").lower()
        base = str(row.get("base") or "").upper()
        if not exchange or not base:
            raise ValueError(f"snapshot exchange/base is missing at {snapshots_path}:{line_number}")
        key = (exchange, base)
        if key in markets_by_cycle[cycle_number]:
            raise ValueError(f"duplicate snapshot market at {snapshots_path}:{line_number}: {key}")
        observed = bool(row.get("observed_now") is not False and not bool(row.get("tombstone")))
        bid = _as_float(row.get("bid_price") or 0.0, label="bid_price")
        ask = _as_float(row.get("ask_price") or 0.0, label="ask_price")
        mid = _as_float(row.get("mid_price") or 0.0, label="mid_price")
        spread = _as_float(row.get("spread_bps") or 0.0, label="spread_bps")
        volume = _as_float(row.get("volume_24h_quote") or 0.0, label="volume_24h_quote")
        funding_interval_raw = row.get("funding_interval_sec")
        funding_interval = None
        if funding_interval_raw not in (None, ""):
            try:
                funding_interval = int(funding_interval_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("funding_interval_sec must be an integer when present") from exc
            if funding_interval <= 0:
                raise ValueError("funding_interval_sec must be positive when present")
        markets_by_cycle[cycle_number][key] = MarketSnapshot(
            exchange=exchange,
            base=base,
            symbol=str(row.get("symbol") or ""),
            observed=observed,
            bid=bid,
            ask=ask,
            mid=mid,
            spread_bps=spread,
            volume_24h_quote=volume,
            non_binance_spot=bool(
                row.get("eligible_non_binance_spot") is True and row.get("binance_spot_listed") is not True
            ),
            funding_rate=_optional_float(
                row.get("funding_rate"),
                label="funding_rate",
                allow_negative=True,
            ),
            funding_interval_sec=funding_interval,
            contract_multiplier=_optional_float(
                row.get("contract_multiplier"),
                label="contract_multiplier",
            ),
            minimum_order_size=_optional_float(
                row.get("minimum_order_size"),
                label="minimum_order_size",
            ),
            maximum_order_size=_optional_float(
                row.get("maximum_order_size"),
                label="maximum_order_size",
            ),
            mark_price=_optional_float(row.get("mark_price"), label="mark_price"),
            index_price=_optional_float(row.get("index_price"), label="index_price"),
            bid_size_contracts=_optional_float(
                row.get("bid_size_contracts"),
                label="bid_size_contracts",
            ),
            ask_size_contracts=_optional_float(
                row.get("ask_size_contracts"),
                label="ask_size_contracts",
            ),
        )
    output: list[SnapshotCycle] = []
    for cycle_number, row in sorted(cycle_rows.items()):
        timestamp_value = row.get("cycle_started_at_utc")
        try:
            timestamp = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid cycle timestamp in {cycles_path}: {timestamp_value}") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"cycle timestamp must be timezone-aware in {cycles_path}")
        successful = frozenset(str(value).lower() for value in (row.get("successful_exchanges") or []))
        output.append(
            SnapshotCycle(
                timestamp=timestamp,
                successful_exchanges=successful,
                markets=markets_by_cycle.get(cycle_number, {}),
            )
        )
    if not output:
        raise ValueError(f"segment contains no cycles: {cycles_path}")
    return output


def _load_cycle_groups(
    plan: dict[str, Any],
    selected_dates: Iterable[str],
) -> tuple[list[list[SnapshotCycle]], list[SnapshotCycle]]:
    sealed = plan["sealed_input"]
    by_date = {
        str(item["scheduled_date"]): item
        for item in sealed["selected_certifications"]
    }
    groups: list[list[SnapshotCycle]] = []
    flattened: list[SnapshotCycle] = []
    for scheduled_date in selected_dates:
        descriptor = by_date.get(str(scheduled_date))
        if descriptor is None:
            raise ValueError(f"selected date has no sealed certification: {scheduled_date}")
        group = _load_segment_cycles(descriptor)
        if flattened and group[0].timestamp <= flattened[-1].timestamp:
            raise ValueError("selected segment cycles must be strictly chronological")
        groups.append(group)
        flattened.extend(group)
    return groups, flattened


def detect_activation_events_by_segment(
    contract: dict[str, Any],
    groups: list[list[SnapshotCycle]],
) -> tuple[list[ActivationEvent], list[SnapshotCycle]]:
    events: list[ActivationEvent] = []
    flattened: list[SnapshotCycle] = []
    cooldown_days = int(contract["event_definition"]["dedup_cooldown_calendar_days"])
    last_event_date: dict[tuple[str, str], date] = {}
    offset = 0
    for group in groups:
        local_events = detect_activation_events(contract, group)
        for event in local_events:
            event_day = date.fromisoformat(event.event_date)
            dedup_key = (event.base, event.activation_venue)
            prior = last_event_date.get(dedup_key)
            if prior is not None and (event_day - prior).days < cooldown_days:
                continue
            last_event_date[dedup_key] = event_day
            events.append(
                replace(
                    event,
                    activation_cycle_index=event.activation_cycle_index + offset,
                    confirmation_cycle_index=event.confirmation_cycle_index + offset,
                    entry_cycle_index=event.entry_cycle_index + offset,
                    segment_end_cycle_index=(
                        event.segment_end_cycle_index + offset
                        if event.segment_end_cycle_index is not None
                        else None
                    ),
                )
            )
        flattened.extend(group)
        offset += len(group)
    return events, flattened


def _aggregate_daily_segment(
    contract: dict[str, Any],
    group: list[SnapshotCycle],
) -> SnapshotCycle:
    if not group:
        raise ValueError("daily segment cannot be empty")
    dates = {_local_date(cycle.timestamp) for cycle in group}
    if len(dates) != 1:
        raise ValueError("daily segment cycles must share one local date")
    confirmation = int(contract["observation_model"]["daily_state_confirmation_cycles"])
    if len(group) < confirmation:
        raise ValueError("daily segment has fewer cycles than the frozen confirmation count")
    window = group[-confirmation:]
    successful = set(window[0].successful_exchanges)
    for cycle in window[1:]:
        successful.intersection_update(cycle.successful_exchanges)
    stable_keys = set(window[0].markets)
    for cycle in window[1:]:
        stable_keys.intersection_update(cycle.markets)
    markets = {
        key: window[-1].markets[key]
        for key in stable_keys
        if all(_market(cycle, key[0], key[1]) is not None for cycle in window)
    }
    return SnapshotCycle(
        timestamp=window[-1].timestamp,
        successful_exchanges=frozenset(successful),
        markets=markets,
    )


def detect_activation_events_by_daily_segments(
    contract: dict[str, Any],
    groups: list[list[SnapshotCycle]],
) -> tuple[list[ActivationEvent], list[SnapshotCycle]]:
    validate_hypothesis_contract(contract)
    daily_cycles = [_aggregate_daily_segment(contract, group) for group in groups]
    if not daily_cycles:
        return [], []
    for previous, current in zip(daily_cycles, daily_cycles[1:]):
        if current.timestamp <= previous.timestamp:
            raise ValueError("daily segments must be strictly chronological")

    blocks: list[tuple[int, list[SnapshotCycle]]] = []
    block_start = 0
    block = [daily_cycles[0]]
    for index, cycle in enumerate(daily_cycles[1:], start=1):
        previous_date = date.fromisoformat(_local_date(daily_cycles[index - 1].timestamp))
        current_date = date.fromisoformat(_local_date(cycle.timestamp))
        if (current_date - previous_date).days != 1:
            blocks.append((block_start, block))
            block_start = index
            block = [cycle]
        else:
            block.append(cycle)
    blocks.append((block_start, block))

    events: list[ActivationEvent] = []
    cooldown_days = int(contract["event_definition"]["dedup_cooldown_calendar_days"])
    last_event_date: dict[tuple[str, str], date] = {}
    for offset, block_cycles in blocks:
        for event in detect_activation_events(contract, block_cycles):
            event_day = date.fromisoformat(event.event_date)
            key = (event.base, event.activation_venue)
            previous = last_event_date.get(key)
            if previous is not None and (event_day - previous).days < cooldown_days:
                continue
            last_event_date[key] = event_day
            events.append(
                replace(
                    event,
                    activation_cycle_index=event.activation_cycle_index + offset,
                    confirmation_cycle_index=event.confirmation_cycle_index + offset,
                    entry_cycle_index=event.entry_cycle_index + offset,
                    segment_end_cycle_index=offset + len(block_cycles) - 1,
                )
            )
    return events, daily_cycles


def _entry_rows(
    contract: dict[str, Any],
    event: ActivationEvent,
    cycles: list[SnapshotCycle],
    *,
    scenario: str,
) -> tuple[MarketSnapshot, MarketSnapshot] | None:
    delay = (
        int(contract["signal"]["entry_delay_cycles"])
        if scenario == "normal"
        else int(contract[scenario]["entry_delay_cycles"])
    )
    entry_index = event.confirmation_cycle_index + delay
    if event.segment_end_cycle_index is not None and entry_index > event.segment_end_cycle_index:
        return None
    if entry_index >= len(cycles):
        return None
    cycle = cycles[entry_index]
    venues = (event.activation_venue, event.reference_venue)
    if not _both_venues_succeeded(cycle, venues):
        return None
    first = _market(cycle, event.activation_venue, event.base)
    second = _market(cycle, event.reference_venue, event.base)
    max_spread = float(contract["signal"]["max_leg_spread_bps"])
    min_volume = float(contract["signal"]["minimum_volume_24h_quote_per_leg"])
    if not _valid_executable_row(first, max_spread, min_volume) or not _valid_executable_row(
        second, max_spread, min_volume
    ):
        return None
    assert first is not None and second is not None
    if _dislocation_bps(first, second) < float(contract["signal"]["minimum_gross_dislocation_bps"]):
        return None
    notional = float(contract["position"]["notional_quote_per_leg"])
    long_row, short_row = (first, second) if first.mid < second.mid else (second, first)
    if _contracts_for_notional(long_row, long_row.ask, notional) is None:
        return None
    if _contracts_for_notional(short_row, short_row.bid, notional) is None:
        return None
    if _entry_capacity_quote(long_row, short_row) < notional:
        return None
    return first, second


def _dual_venue_coverage(contract: dict[str, Any], cycles: list[SnapshotCycle]) -> float:
    if not cycles:
        return 0.0
    venues = tuple(str(value) for value in contract["universe"]["venues"])
    return sum(_both_venues_succeeded(cycle, venues) for cycle in cycles) / len(cycles)


def _wilson_lower_bound(successes: int, trials: int) -> float:
    if trials <= 0:
        return 0.0
    successes = max(0, min(int(successes), int(trials)))
    phat = successes / trials
    z2 = Z_90_ONE_SIDED * Z_90_ONE_SIDED
    denominator = 1.0 + z2 / trials
    centre = phat + z2 / (2.0 * trials)
    margin = Z_90_ONE_SIDED * math.sqrt(
        (phat * (1.0 - phat) + z2 / (4.0 * trials)) / trials
    )
    return max(0.0, (centre - margin) / denominator)


def _result_hash(payload: dict[str, Any], excluded: set[str] | None = None) -> str:
    ignored = {"created_at_utc", "elapsed_sec", "artifact_path"}
    if excluded:
        ignored.update(excluded)
    return _json_hash({key: value for key, value in payload.items() if key not in ignored})


def run_train_feasibility(
    plan_path: str | Path,
    *,
    expected_plan_hash: str,
    output_path: str | Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    validation = validate_evaluation_input_plan(plan_path, expected_plan_hash)
    if validation["plan_stage"] != TRAIN_FEASIBILITY_STAGE:
        raise ValueError("train feasibility requires a train_feasibility input plan")
    plan_target = Path(plan_path).expanduser().resolve()
    plan = _read_json(plan_target)
    sealed = plan["sealed_input"]
    contract = sealed["hypothesis_contract"]
    train_dates = list(sealed["split"]["train_dates"])
    groups, cycles = _load_cycle_groups(plan, train_dates)
    events, cycles = detect_activation_events_by_daily_segments(contract, groups)
    valid_events: list[ActivationEvent] = []
    capacities: list[float] = []
    for event in events:
        rows = _entry_rows(contract, event, cycles, scenario="normal")
        if rows is None:
            continue
        valid_events.append(event)
        long_row, short_row = (rows[0], rows[1]) if rows[0].mid < rows[1].mid else (rows[1], rows[0])
        capacities.append(_entry_capacity_quote(long_row, short_row))
    train_days = len(train_dates)
    oos_days = int(contract["sample_plan"]["oos_closed_days"])
    scale = oos_days / train_days if train_days else 0.0
    projected_candidates = int(math.floor(len(events) * scale))
    candidate_by_venue = {
        venue: sum(event.activation_venue == venue for event in events)
        for venue in contract["universe"]["venues"]
    }
    projected_by_venue = {
        venue: int(math.floor(count * scale))
        for venue, count in candidate_by_venue.items()
    }
    train_unique_dates = len({event.event_date for event in events})
    projected_unique_dates = min(oos_days, int(math.floor(train_unique_dates * scale)))
    lower_fill = _wilson_lower_bound(len(valid_events), len(events))
    lower_total = int(math.floor(projected_candidates * lower_fill))
    lower_by_venue = {
        venue: int(math.floor(count * lower_fill))
        for venue, count in projected_by_venue.items()
    }
    lower_unique_dates = int(math.floor(projected_unique_dates * lower_fill))
    coverage = _dual_venue_coverage(contract, cycles)
    capacity = min(capacities) if capacities else 0.0
    gates = contract["validation_protocol"]
    reasons: list[str] = []
    if not events:
        reasons.append("no_train_activation_events")
    if lower_total < int(gates["minimum_oos_portfolio_events_total"]):
        reasons.append("lower_bound_oos_portfolio_events_total_below_minimum")
    for venue in contract["universe"]["venues"]:
        if lower_by_venue[venue] < int(gates["minimum_oos_portfolio_events_per_venue"]):
            reasons.append(f"lower_bound_oos_portfolio_events_below_minimum:{venue}")
    if lower_unique_dates < int(gates["minimum_unique_oos_signal_dates"]):
        reasons.append("lower_bound_unique_oos_dates_below_minimum")
    if coverage < float(gates["minimum_dual_venue_coverage"]):
        reasons.append("train_dual_venue_coverage_below_minimum")
    if capacity < float(gates["minimum_capacity_quote_per_leg"]):
        reasons.append("train_executable_capacity_below_minimum")
    verdict = "FEASIBLE_FOR_OOS" if not reasons else "INFEASIBLE_ON_CURRENT_DATA"
    feasibility_target = Path(output_path).expanduser().resolve()
    artifact: dict[str, Any] = {
        "schema": FEASIBILITY_SCHEMA,
        "created_at_utc": created_at_utc or _utc_now(),
        "mode": "train_only_feasibility",
        "research_only": True,
        "hypothesis_id": sealed["hypothesis_id"],
        "plan_path": str(plan_target),
        "plan_hash": validation["plan_hash"],
        "plan_file_sha256": validation["plan_file_sha256"],
        "input_merkle_root": validation["input_merkle_root"],
        "hypothesis_contract_sha256": sealed["hypothesis_contract_sha256"],
        "cost_profile_sha256": sealed["cost_profile_sha256"],
        "evaluator_sha256": sealed["runtime_tools"]["membership_drift_evaluator"]["sha256"],
        "feasibility_estimator_version_hash": estimator_version_hash(),
        "git_head_sha256": sealed["source_control"]["git_head_sha256"],
        "git_ref": sealed["source_control"]["git_ref"],
        "runtime_versions": sealed["runtime_versions"],
        "fee_provenance": contract["economics"]["cost_profile"],
        "split": sealed["split"],
        "input_artifact_hashes": sealed["input_artifact_hashes"],
        "train_dates_read": train_days,
        "oos_dates_read": 0,
        "train_candidate_events": len(events),
        "train_valid_events": len(valid_events),
        "train_event_fill_rate": len(valid_events) / len(events) if events else 0.0,
        "wilson_90_lower_fill_rate": lower_fill,
        "projected_oos_candidate_events": projected_candidates,
        "conservative_90_lower_oos_event_count": lower_total,
        "projected_oos_candidate_events_by_activation_venue": projected_by_venue,
        "conservative_90_lower_oos_events_by_activation_venue": lower_by_venue,
        "projected_unique_oos_dates": projected_unique_dates,
        "conservative_90_lower_unique_oos_dates": lower_unique_dates,
        "train_dual_venue_coverage": coverage,
        "minimum_train_executable_capacity_quote_per_leg": capacity,
        "forward_market_rows_read": True,
        "returns_read": False,
        "pnl_computed": False,
        "oos_metrics_computed": False,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "verdict": verdict,
        "rejection_reasons": reasons,
        "next_allowed_action": (
            "build_oos_accrual_schedule_planonly"
            if verdict == "FEASIBLE_FOR_OOS"
            else "bank_hypothesis_with_data_requirements_do_not_run_oos"
        ),
        "next_allowed_command": _feasibility_next_command(
            verdict=verdict,
            plan_target=plan_target,
            feasibility_target=feasibility_target,
            sealed=sealed,
        ),
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "elapsed_sec": round(time.monotonic() - started, 6),
    }
    artifact["deterministic_result_hash"] = _result_hash(artifact)
    _write_json_immutable(output_path, artifact)
    return artifact


def _validate_feasibility_artifact(
    path: str | Path,
    *,
    plan_validation: dict[str, Any],
    sealed: dict[str, Any],
) -> dict[str, Any]:
    artifact = _read_json(path)
    if artifact.get("schema") != FEASIBILITY_SCHEMA:
        raise ValueError(f"expected {FEASIBILITY_SCHEMA} artifact")
    if artifact.get("verdict") != "FEASIBLE_FOR_OOS":
        raise ValueError("OOS is blocked because feasibility verdict is not FEASIBLE_FOR_OOS")
    bindings = {
        "plan_hash": plan_validation["plan_hash"],
        "input_merkle_root": plan_validation["input_merkle_root"],
        "hypothesis_contract_sha256": sealed["hypothesis_contract_sha256"],
        "evaluator_sha256": sealed["runtime_tools"]["membership_drift_evaluator"]["sha256"],
        "feasibility_estimator_version_hash": estimator_version_hash(),
    }
    for key, expected in bindings.items():
        if artifact.get(key) != expected:
            raise ValueError(f"feasibility binding mismatch for {key}")
    expected_hash = str(artifact.get("deterministic_result_hash") or "")
    observed_hash = _result_hash(artifact, {"deterministic_result_hash"})
    if expected_hash != observed_hash:
        raise ValueError("feasibility deterministic result hash mismatch")
    if artifact.get("oos_dates_read") != 0 or artifact.get("returns_read") is not False:
        raise ValueError("feasibility artifact violates OOS embargo")
    return artifact


def validate_train_feasibility_evidence(
    train_plan_path: str | Path,
    feasibility_path: str | Path,
) -> dict[str, Any]:
    """Validate the complete train-only authorization chain used before OOS accrual."""
    train_target = Path(train_plan_path).expanduser().resolve()
    feasibility_target = Path(feasibility_path).expanduser().resolve()
    validation = validate_evaluation_input_plan(train_target)
    if validation["plan_stage"] != TRAIN_FEASIBILITY_STAGE:
        raise ValueError("upstream collection evidence must use a train_feasibility input plan")
    train_plan = _read_json(train_target)
    sealed = train_plan["sealed_input"]
    artifact = _validate_feasibility_artifact(
        feasibility_target,
        plan_validation=validation,
        sealed=sealed,
    )
    return {
        "train_plan_path": str(train_target),
        "train_plan_file_sha256": sha256_file(train_target),
        "train_plan_hash": validation["plan_hash"],
        "train_input_merkle_root": validation["input_merkle_root"],
        "train_dates": validation["train_dates"],
        "hypothesis_id": sealed["hypothesis_id"],
        "data_type": sealed["data_type"],
        "hypothesis_contract_sha256": sealed["hypothesis_contract_sha256"],
        "feasibility_path": str(feasibility_target),
        "feasibility_file_sha256": sha256_file(feasibility_target),
        "feasibility_result_hash": artifact["deterministic_result_hash"],
        "verdict": artifact["verdict"],
        "oos_dates_read": artifact["oos_dates_read"],
        "returns_read": artifact["returns_read"],
    }


def _profit_factor(values: list[float]) -> float:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses > 0:
        return gains / losses
    return GATE_FAILURE_SENTINEL if gains > 0 else 0.0


def _percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return GATE_FAILURE_SENTINEL
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _positive_concentration(results: list[EventResult], key: str) -> float:
    positive = [result for result in results if result.net_price_pnl_quote > 0]
    total = sum(result.net_price_pnl_quote for result in positive)
    if total <= 0:
        return GATE_FAILURE_SENTINEL
    grouped: dict[str, float] = defaultdict(float)
    for result in positive:
        value = (
            f"{result.base}|{result.activation_venue}|{result.event_date}"
            if key == "event"
            else str(getattr(result, key))
        )
        grouped[value] += result.net_price_pnl_quote
    return max(grouped.values(), default=0.0) / total


def _max_drawdown_fraction(results: list[EventResult], allocated_collateral: float) -> float:
    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for result in sorted(
        results,
        key=lambda item: (item.exit_timestamp, item.event_date, item.base, item.activation_venue),
    ):
        cumulative += result.net_price_pnl_quote
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    return maximum_drawdown / allocated_collateral if allocated_collateral > 0 else GATE_FAILURE_SENTINEL


def _serialise_result(result: EventResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["entry_timestamp"] = result.entry_timestamp.isoformat()
    payload["exit_timestamp"] = result.exit_timestamp.isoformat()
    return payload


def _evaluate_oos_once(plan: dict[str, Any]) -> dict[str, Any]:
    sealed = plan["sealed_input"]
    contract = sealed["hypothesis_contract"]
    oos_dates = list(sealed["split"]["oos_dates"])
    groups, cycles = _load_cycle_groups(plan, oos_dates)
    candidate_events, cycles = detect_activation_events_by_daily_segments(contract, groups)
    normal_results: list[EventResult] = []
    robustness_results: list[EventResult] = []
    stress_results: list[EventResult] = []
    for event in candidate_events:
        normal = simulate_event(contract, event, cycles, scenario="normal")
        if normal is None:
            continue
        normal_results.append(normal)
        robustness = simulate_event(contract, event, cycles, scenario="robustness")
        stress = simulate_event(contract, event, cycles, scenario="stress")
        if robustness is not None:
            robustness_results.append(robustness)
        if stress is not None:
            stress_results.append(stress)
    normal_values = [result.net_price_pnl_quote for result in normal_results]
    normal_by_venue = {
        venue: [
            result.net_price_pnl_quote
            for result in normal_results
            if result.activation_venue == venue
        ]
        for venue in contract["universe"]["venues"]
    }
    fold_results: list[dict[str, Any]] = []
    positive_by_venue = {venue: 0 for venue in contract["universe"]["venues"]}
    positive_combined = 0
    for fold in sealed["split"]["walk_forward_folds"]:
        fold_dates = set(fold["test_dates"])
        selected = [result for result in normal_results if result.event_date in fold_dates]
        combined_pnl = sum(result.net_price_pnl_quote for result in selected)
        combined_positive = combined_pnl > 0
        positive_combined += int(combined_positive)
        by_venue: dict[str, dict[str, Any]] = {}
        for venue in contract["universe"]["venues"]:
            venue_results = [result for result in selected if result.activation_venue == venue]
            venue_pnl = sum(result.net_price_pnl_quote for result in venue_results)
            positive_by_venue[venue] += int(venue_pnl > 0)
            by_venue[venue] = {"events": len(venue_results), "net_pnl_quote": venue_pnl}
        fold_results.append(
            {
                "fold": int(fold["fold"]),
                "test_dates": list(fold["test_dates"]),
                "events": len(selected),
                "net_pnl_quote": combined_pnl,
                "positive": combined_positive,
                "by_activation_venue": by_venue,
                "refit": False,
            }
        )
    notional = float(contract["position"]["notional_quote_per_leg"])
    event_count = len(normal_results)
    metrics = {
        "oos_closed_days": len(oos_dates),
        "candidate_activation_events": len(candidate_events),
        "event_count": event_count,
        "event_count_by_activation_venue": {
            venue: len(normal_by_venue[venue]) for venue in contract["universe"]["venues"]
        },
        "unique_event_dates": len({result.event_date for result in normal_results}),
        "dual_venue_coverage": _dual_venue_coverage(contract, cycles),
        "net_expectancy_quote": sum(normal_values) / event_count if event_count else 0.0,
        "profit_factor": _profit_factor(normal_values),
        "positive_event_rate": sum(value > 0 for value in normal_values) / event_count if event_count else 0.0,
        "net_expectancy_by_activation_venue": {
            venue: (sum(values) / len(values) if values else 0.0)
            for venue, values in normal_by_venue.items()
        },
        "normal_net_pnl_quote": sum(normal_values),
        "robustness_net_pnl_quote": sum(result.net_price_pnl_quote for result in robustness_results),
        "stress_net_pnl_quote": sum(result.net_price_pnl_quote for result in stress_results),
        "robustness_event_count": len(robustness_results),
        "stress_event_count": len(stress_results),
        "scenario_event_coverage_complete": (
            len(robustness_results) == event_count and len(stress_results) == event_count
        ),
        "positive_combined_walk_forward_folds": positive_combined,
        "positive_walk_forward_folds_by_activation_venue": positive_by_venue,
        "max_drawdown_fraction": _max_drawdown_fraction(normal_results, notional * 2.0),
        "max_single_event_positive_pnl_share": _positive_concentration(normal_results, "event"),
        "max_single_base_positive_pnl_share": _positive_concentration(normal_results, "base"),
        "max_single_venue_positive_pnl_share": _positive_concentration(normal_results, "activation_venue"),
        "break_even_holding_days_p95": _percentile_nearest_rank(
            [result.break_even_holding_days for result in normal_results], 0.95
        ),
        "minimum_executable_capacity_quote_per_leg": min(
            (result.executable_capacity_quote_per_leg for result in normal_results),
            default=0.0,
        ),
        "funding_pnl_quote": 0.0,
        "funding_evidence_available": False,
        "funding_can_rescue_negative_price_only": False,
    }
    decision = decide_verdict(contract, metrics)
    return {
        "metrics": metrics,
        "walk_forward_folds": fold_results,
        "normal_events": [_serialise_result(result) for result in normal_results],
        "robustness_events": [_serialise_result(result) for result in robustness_results],
        "stress_events": [_serialise_result(result) for result in stress_results],
        "decision": decision,
    }


def run_oos_evaluation(
    plan_path: str | Path,
    *,
    expected_plan_hash: str,
    feasibility_path: str | Path,
    output_path: str | Path,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    validation = validate_evaluation_input_plan(plan_path, expected_plan_hash)
    if validation["plan_stage"] != FULL_EVALUATION_STAGE:
        raise ValueError("OOS evaluation requires a full_evaluation input plan")
    plan_target = Path(plan_path).expanduser().resolve()
    plan = _read_json(plan_target)
    sealed = plan["sealed_input"]
    upstream = sealed["upstream_train_feasibility"]
    train_info = upstream["train_plan"]
    feasibility_info = upstream["feasibility"]
    supplied_feasibility_target = Path(feasibility_path).expanduser().resolve()
    expected_feasibility_target = Path(str(feasibility_info["path"])).expanduser().resolve()
    if supplied_feasibility_target != expected_feasibility_target:
        raise ValueError("supplied feasibility path differs from the full_evaluation seal")
    if sha256_file(supplied_feasibility_target) != feasibility_info["file_sha256"]:
        raise ValueError("supplied feasibility file hash differs from the full_evaluation seal")
    train_target = Path(str(train_info["path"])).expanduser().resolve()
    train_validation = validate_evaluation_input_plan(train_target, str(train_info["plan_hash"]))
    train_sealed = _read_json(train_target)["sealed_input"]
    feasibility = _validate_feasibility_artifact(
        supplied_feasibility_target,
        plan_validation=train_validation,
        sealed=train_sealed,
    )
    if feasibility["deterministic_result_hash"] != feasibility_info["deterministic_result_hash"]:
        raise ValueError("supplied feasibility result differs from the full_evaluation seal")
    repeats = int(sealed["evaluation_protocol"]["deterministic_repeats"])
    evaluated = [_evaluate_oos_once(plan) for _ in range(repeats)]
    repeat_hashes = [_json_hash(result) for result in evaluated]
    if len(set(repeat_hashes)) != 1:
        raise RuntimeError(f"deterministic OOS repeats diverged: {repeat_hashes}")
    core = evaluated[0]
    decision = core["decision"]
    artifact: dict[str, Any] = {
        "schema": EVALUATION_SCHEMA,
        "created_at_utc": created_at_utc or _utc_now(),
        "mode": "visible_owned_no_grid_oos",
        "research_only": True,
        "hypothesis_id": sealed["hypothesis_id"],
        "plan_path": str(plan_target),
        "plan_hash": validation["plan_hash"],
        "plan_file_sha256": validation["plan_file_sha256"],
        "input_merkle_root": validation["input_merkle_root"],
        "hypothesis_contract_sha256": sealed["hypothesis_contract_sha256"],
        "cost_profile_sha256": sealed["cost_profile_sha256"],
        "evaluator_sha256": sealed["runtime_tools"]["membership_drift_evaluator"]["sha256"],
        "git_head_sha256": sealed["source_control"]["git_head_sha256"],
        "git_ref": sealed["source_control"]["git_ref"],
        "runtime_versions": sealed["runtime_versions"],
        "fee_provenance": sealed["hypothesis_contract"]["economics"]["cost_profile"],
        "split": sealed["split"],
        "input_artifact_hashes": sealed["input_artifact_hashes"],
        "train_plan_path": str(train_target),
        "train_plan_hash": train_validation["plan_hash"],
        "train_input_merkle_root": train_validation["input_merkle_root"],
        "feasibility_path": str(supplied_feasibility_target),
        "feasibility_file_sha256": sha256_file(supplied_feasibility_target),
        "feasibility_result_hash": feasibility["deterministic_result_hash"],
        "frozen_parameters_no_grid": True,
        "oos_tuning": False,
        "parameter_refit": False,
        "deterministic_repeats": repeats,
        "deterministic_repeat_hashes": repeat_hashes,
        "deterministic_repeats_match": True,
        **core,
        "verdict": decision["verdict"],
        "rejection_reasons": decision["reasons"],
        "next_allowed_action": decision["next_allowed_action"],
        "next_allowed_command": decision["next_allowed_command"],
        "execution_probe_allowed": decision["execution_probe_allowed"],
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "grid_search": False,
        "retune": False,
        "network_access": False,
        "elapsed_sec": round(time.monotonic() - started, 6),
    }
    artifact["deterministic_result_hash"] = _result_hash(artifact)
    _write_json_immutable(output_path, artifact)
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hash-bound no-grid PIT membership-drift evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Seal quality-certified inputs without reading market rows")
    plan.add_argument("--quality-ledger", required=True)
    plan.add_argument("--hypothesis-bank", required=True)
    plan.add_argument("--hypothesis-id", required=True)
    plan.add_argument("--plan-stage", choices=sorted(PLAN_STAGES), default=TRAIN_FEASIBILITY_STAGE)
    plan.add_argument("--train-plan")
    plan.add_argument("--feasibility")
    plan.add_argument("--output", required=True)
    validate = subparsers.add_parser("validate-plan", help="Validate the immutable input PlanOnly")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--expected-plan-hash", required=True)
    feasibility = subparsers.add_parser("feasibility", help="Read train dates only and gate OOS")
    feasibility.add_argument("--plan", required=True)
    feasibility.add_argument("--expected-plan-hash", required=True)
    feasibility.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate", help="Run deterministic frozen OOS after feasibility")
    evaluate.add_argument("--plan", required=True)
    evaluate.add_argument("--expected-plan-hash", required=True)
    evaluate.add_argument("--feasibility", required=True)
    evaluate.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        result = build_evaluation_input_plan(
            quality_ledger_path=args.quality_ledger,
            hypothesis_bank_path=args.hypothesis_bank,
            hypothesis_id=args.hypothesis_id,
            output_path=args.output,
            plan_stage=args.plan_stage,
            train_plan_path=args.train_plan,
            feasibility_path=args.feasibility,
        )
    elif args.command == "validate-plan":
        result = validate_evaluation_input_plan(args.plan, args.expected_plan_hash)
    elif args.command == "feasibility":
        result = run_train_feasibility(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
            output_path=args.output,
        )
    elif args.command == "evaluate":
        result = run_oos_evaluation(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
            feasibility_path=args.feasibility,
            output_path=args.output,
        )
    else:
        raise ValueError(f"unsupported command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
