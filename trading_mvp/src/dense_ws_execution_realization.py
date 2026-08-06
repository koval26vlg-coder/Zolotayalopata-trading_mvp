from __future__ import annotations

import bisect
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

try:
    import dense_ws_signal_evaluator_freeze as freeze
except ModuleNotFoundError:  # pragma: no cover - package import path
    from . import dense_ws_signal_evaluator_freeze as freeze


REALIZATION_SCHEMA = "trading_mvp_dense_ws_synthetic_execution_realization_v1"
IMPLEMENTATION_STATUS = "IMPLEMENTATION_ONLY_EVALUATOR_NOT_AUTHORIZED"
SNAPSHOT_SCHEMA = "trading_mvp_dense_ws_execution_snapshot_v1"
VENUES = ("mexc", "gateio")


class SyntheticFixtureIntegrityError(ValueError):
    """Synthetic-only input or the frozen execution rules are invalid."""


@dataclass(frozen=True)
class Quote:
    recv_ts: float
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float


def _expect(actual: Any, expected: Any, *, label: str) -> None:
    if actual != expected:
        raise SyntheticFixtureIntegrityError(
            f"{label} mismatch: expected {expected!r}, observed {actual!r}"
        )


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SyntheticFixtureIntegrityError(f"{label} must be an object")
    return value


def _finite(value: Any, *, label: str, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SyntheticFixtureIntegrityError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise SyntheticFixtureIntegrityError(f"{label} must be finite")
    if positive and number <= 0.0:
        raise SyntheticFixtureIntegrityError(f"{label} must be positive")
    return number


def _base_symbol(value: Any) -> str:
    token = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if token.endswith("USDT"):
        token = token[:-4]
    if not token:
        raise SyntheticFixtureIntegrityError("base/symbol is empty")
    return token


def _fixture_marker(row: Mapping[str, Any], *, label: str) -> None:
    if row.get("fixture_only") is not True:
        raise SyntheticFixtureIntegrityError(
            f"{label}.fixture_only must be true; real data is refused"
        )


def _quote(row: Mapping[str, Any], *, label: str) -> Quote:
    quote = Quote(
        recv_ts=_finite(row.get("recv_ts"), label=f"{label}.recv_ts"),
        bid_price=_finite(
            row.get("bid_price"), label=f"{label}.bid_price", positive=True
        ),
        bid_qty=_finite(
            row.get("bid_qty"), label=f"{label}.bid_qty", positive=True
        ),
        ask_price=_finite(
            row.get("ask_price"), label=f"{label}.ask_price", positive=True
        ),
        ask_qty=_finite(
            row.get("ask_qty"), label=f"{label}.ask_qty", positive=True
        ),
    )
    if quote.ask_price < quote.bid_price:
        raise SyntheticFixtureIntegrityError(f"{label} has crossed own-venue BBO")
    return quote


def _validate_contract(
    contract: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    _expect(contract.get("schema"), freeze.CONTRACT_SCHEMA, label="contract.schema")
    _expect(contract.get("status"), freeze.CONTRACT_STATUS, label="contract.status")
    _expect(
        freeze.canonical_contract_hash(contract),
        contract.get("contract_hash"),
        label="contract hash",
    )
    authorization = _mapping(contract.get("authorization"), label="authorization")
    _expect(
        authorization.get("evaluation_authorized"),
        False,
        label="evaluation_authorized",
    )
    _expect(
        authorization.get("returns_pnl_oos_allowed"),
        False,
        label="returns_pnl_oos_allowed",
    )
    signal = _mapping(contract.get("signal_contract"), label="signal_contract")
    expected_signal = {
        "eligible_regime": "DENSE_BOTH",
        "directions": ["buy_mexc_sell_gateio", "buy_gateio_sell_mexc"],
        "trigger_when_displayed_normal_net_edge_bps_gt": 0.0,
        "minimum_displayed_capacity_quote": 50.0,
        "cooldown_sec_per_base_and_direction": 60,
        "one_event_per_base_direction_per_cooldown": True,
        "event_selected_before_outcome_quotes": True,
        "threshold_learned_from_returns_pnl_or_oos": False,
        "parameter_combinations": 1,
    }
    for key, expected in expected_signal.items():
        _expect(signal.get(key), expected, label=f"signal_contract.{key}")
    execution = _mapping(
        contract.get("execution_realization_contract"),
        label="execution_realization_contract",
    )
    expected_execution = {
        "normal_latency_ms": 250,
        "stress_latency_ms": 1000,
        "outcome_quote_selection": (
            "latest raw BBO with recv_ts <= execution_ts; no future quote"
        ),
        "future_rows_allowed_for_signal": False,
        "future_rows_allowed_only_for_outcome_measurement": True,
        "max_quote_age_ms": {"mexc": 6000, "gateio": 5000},
        "max_cross_venue_recv_ts_skew_ms": 2000,
        "minimum_execution_capacity_quote_each_leg": 50.0,
        "both_legs_required": True,
        "unfillable_events_remain_in_fill_rate_denominator": True,
        "normal_total_cost_bps": 69.0,
        "stress_total_cost_bps": 89.0,
        "maker_fill_or_queue_assumption": False,
        "one_leg_fill_profit_credited": False,
    }
    for key, expected in expected_execution.items():
        _expect(execution.get(key), expected, label=f"execution_contract.{key}")
    _expect(contract.get("safety"), {
        "network_access": False,
        "returns_read": False,
        "pnl_computed": False,
        "oos_read": False,
        "grid_or_retune": False,
        "paper_forward": False,
        "live_orders": False,
        "private_api_keys": False,
        "real_capital": False,
        "leverage_or_margin": False,
    }, label="contract.safety")
    return signal, execution


def _snapshot_quotes(
    snapshot: Mapping[str, Any],
    *,
    max_quote_age_ms: Mapping[str, Any],
    max_skew_ms: float,
) -> tuple[float, str, dict[str, Quote]]:
    _fixture_marker(snapshot, label="snapshot")
    _expect(snapshot.get("schema"), SNAPSHOT_SCHEMA, label="snapshot.schema")
    _expect(snapshot.get("regime_label"), "DENSE_BOTH", label="regime_label")
    sample_ts = _finite(snapshot.get("sample_ts"), label="sample_ts")
    base = _base_symbol(snapshot.get("base"))
    venues = _mapping(snapshot.get("venues"), label="snapshot.venues")
    _expect(set(venues), set(VENUES), label="snapshot venue set")
    quotes: dict[str, Quote] = {}
    for venue in VENUES:
        quote = _quote(_mapping(venues[venue], label=venue), label=venue)
        age_ms = (sample_ts - quote.recv_ts) * 1_000.0
        if age_ms < 0.0:
            raise SyntheticFixtureIntegrityError(
                f"snapshot {venue} quote is from the future"
            )
        if age_ms > float(max_quote_age_ms[venue]):
            raise SyntheticFixtureIntegrityError(f"snapshot {venue} quote is stale")
        quotes[venue] = quote
    skew_ms = abs(quotes["mexc"].recv_ts - quotes["gateio"].recv_ts) * 1_000.0
    if skew_ms > max_skew_ms:
        raise SyntheticFixtureIntegrityError("snapshot cross-venue skew is too large")
    return sample_ts, base, quotes


def _raw_quote_index(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[list[float], list[Quote]]]:
    staged: dict[tuple[str, str], list[Quote]] = defaultdict(list)
    prior_ts: float | None = None
    for index, row in enumerate(rows):
        item = _mapping(row, label=f"raw_bbo_events[{index}]")
        _fixture_marker(item, label=f"raw_bbo_events[{index}]")
        _expect(item.get("event_kind"), "bbo", label="raw event_kind")
        venue = str(item.get("exchange") or "").strip().lower()
        if venue not in VENUES:
            raise SyntheticFixtureIntegrityError(f"unsupported raw venue: {venue}")
        base = _base_symbol(item.get("symbol"))
        quote = _quote(item, label=f"raw_bbo_events[{index}]")
        if prior_ts is not None and quote.recv_ts < prior_ts:
            raise SyntheticFixtureIntegrityError(
                "raw BBO stream is not globally ordered by recv_ts"
            )
        prior_ts = quote.recv_ts
        staged[(base, venue)].append(quote)
    return {
        key: ([quote.recv_ts for quote in values], values)
        for key, values in staged.items()
    }


def _latest_quote(
    index: Mapping[tuple[str, str], tuple[Sequence[float], Sequence[Quote]]],
    *,
    base: str,
    venue: str,
    execution_ts: float,
) -> Quote | None:
    series = index.get((base, venue))
    if series is None:
        return None
    times, quotes = series
    position = bisect.bisect_right(times, execution_ts) - 1
    return quotes[position] if position >= 0 else None


def _direction_venues(direction: str) -> tuple[str, str]:
    if direction == "buy_mexc_sell_gateio":
        return "mexc", "gateio"
    if direction == "buy_gateio_sell_mexc":
        return "gateio", "mexc"
    raise SyntheticFixtureIntegrityError(f"unsupported direction: {direction}")


def _edge_and_capacity(
    *,
    direction: str,
    quotes: Mapping[str, Quote],
) -> tuple[float, float]:
    buy_venue, sell_venue = _direction_venues(direction)
    buy = quotes[buy_venue]
    sell = quotes[sell_venue]
    gross_edge_bps = (sell.bid_price / buy.ask_price - 1.0) * 10_000.0
    capacity_quote = min(
        buy.ask_price * buy.ask_qty,
        sell.bid_price * sell.bid_qty,
    )
    return gross_edge_bps, capacity_quote


def _unfillable(
    *,
    scenario: str,
    latency_ms: int,
    cost_bps: float,
    execution_ts: float,
    reason: str,
    buy: Quote | None,
    sell: Quote | None,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "latency_ms": latency_ms,
        "cost_bps": cost_bps,
        "execution_ts": execution_ts,
        "paired_fill": False,
        "unfillable_reason": reason,
        "buy_quote_recv_ts": buy.recv_ts if buy is not None else None,
        "sell_quote_recv_ts": sell.recv_ts if sell is not None else None,
        "gross_edge_bps": None,
        "net_edge_bps": None,
        "capacity_quote": None,
    }


def _realize_outcome(
    *,
    scenario: str,
    base: str,
    direction: str,
    sample_ts: float,
    latency_ms: int,
    cost_bps: float,
    minimum_capacity: float,
    max_quote_age_ms: Mapping[str, Any],
    max_skew_ms: float,
    quote_index: Mapping[
        tuple[str, str], tuple[Sequence[float], Sequence[Quote]]
    ],
) -> dict[str, Any]:
    execution_ts = sample_ts + latency_ms / 1_000.0
    buy_venue, sell_venue = _direction_venues(direction)
    buy = _latest_quote(
        quote_index,
        base=base,
        venue=buy_venue,
        execution_ts=execution_ts,
    )
    sell = _latest_quote(
        quote_index,
        base=base,
        venue=sell_venue,
        execution_ts=execution_ts,
    )
    common = {
        "scenario": scenario,
        "latency_ms": latency_ms,
        "cost_bps": cost_bps,
        "execution_ts": execution_ts,
        "buy": buy,
        "sell": sell,
    }
    if buy is None:
        return _unfillable(reason="missing_buy_quote", **common)
    if sell is None:
        return _unfillable(reason="missing_sell_quote", **common)
    buy_age_ms = (execution_ts - buy.recv_ts) * 1_000.0
    sell_age_ms = (execution_ts - sell.recv_ts) * 1_000.0
    if buy_age_ms > float(max_quote_age_ms[buy_venue]):
        return _unfillable(reason="stale_buy_quote", **common)
    if sell_age_ms > float(max_quote_age_ms[sell_venue]):
        return _unfillable(reason="stale_sell_quote", **common)
    if abs(buy.recv_ts - sell.recv_ts) * 1_000.0 > max_skew_ms:
        return _unfillable(reason="cross_venue_skew", **common)
    buy_capacity = buy.ask_price * buy.ask_qty
    sell_capacity = sell.bid_price * sell.bid_qty
    if buy_capacity < minimum_capacity:
        return _unfillable(reason="buy_capacity_shortfall", **common)
    if sell_capacity < minimum_capacity:
        return _unfillable(reason="sell_capacity_shortfall", **common)
    gross_edge_bps = (sell.bid_price / buy.ask_price - 1.0) * 10_000.0
    return {
        "scenario": scenario,
        "latency_ms": latency_ms,
        "cost_bps": cost_bps,
        "execution_ts": execution_ts,
        "paired_fill": True,
        "unfillable_reason": None,
        "buy_quote_recv_ts": buy.recv_ts,
        "sell_quote_recv_ts": sell.recv_ts,
        "buy_quote_age_ms": buy_age_ms,
        "sell_quote_age_ms": sell_age_ms,
        "gross_edge_bps": gross_edge_bps,
        "net_edge_bps": gross_edge_bps - cost_bps,
        "capacity_quote": min(buy_capacity, sell_capacity),
    }


def realize_synthetic_execution_fixture(
    *,
    contract: Mapping[str, Any],
    snapshots: Iterable[Mapping[str, Any]],
    raw_bbo_events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Exercise frozen execution rules on rows explicitly marked as synthetic."""
    signal, execution = _validate_contract(contract)
    max_quote_age_ms = _mapping(
        execution["max_quote_age_ms"], label="max_quote_age_ms"
    )
    max_skew_ms = float(execution["max_cross_venue_recv_ts_skew_ms"])
    minimum_displayed = float(signal["minimum_displayed_capacity_quote"])
    minimum_execution = float(
        execution["minimum_execution_capacity_quote_each_leg"]
    )
    cooldown_sec = float(signal["cooldown_sec_per_base_and_direction"])
    normal_cost = float(execution["normal_total_cost_bps"])
    quote_index = _raw_quote_index(raw_bbo_events)

    events: list[dict[str, Any]] = []
    suppressed_by_cooldown = 0
    last_selected: dict[tuple[str, str], float] = {}
    seen_snapshots: set[tuple[str, float]] = set()
    prior_sample_ts: float | None = None
    direction_counts: Counter[str] = Counter()

    for index, row in enumerate(snapshots):
        snapshot = _mapping(row, label=f"snapshots[{index}]")
        sample_ts, base, quotes = _snapshot_quotes(
            snapshot,
            max_quote_age_ms=max_quote_age_ms,
            max_skew_ms=max_skew_ms,
        )
        if prior_sample_ts is not None and sample_ts < prior_sample_ts:
            raise SyntheticFixtureIntegrityError(
                "snapshot stream is not ordered by sample_ts"
            )
        prior_sample_ts = sample_ts
        snapshot_key = (base, sample_ts)
        if snapshot_key in seen_snapshots:
            raise SyntheticFixtureIntegrityError(
                "duplicate base/sample_ts execution snapshot"
            )
        seen_snapshots.add(snapshot_key)
        for direction in signal["directions"]:
            displayed_gross, displayed_capacity = _edge_and_capacity(
                direction=direction,
                quotes=quotes,
            )
            displayed_net = displayed_gross - normal_cost
            if displayed_net <= float(
                signal["trigger_when_displayed_normal_net_edge_bps_gt"]
            ):
                continue
            if displayed_capacity < minimum_displayed:
                continue
            key = (base, direction)
            prior = last_selected.get(key)
            if prior is not None and sample_ts - prior < cooldown_sec:
                suppressed_by_cooldown += 1
                continue
            last_selected[key] = sample_ts
            outcomes = {
                "normal": _realize_outcome(
                    scenario="normal",
                    base=base,
                    direction=direction,
                    sample_ts=sample_ts,
                    latency_ms=int(execution["normal_latency_ms"]),
                    cost_bps=normal_cost,
                    minimum_capacity=minimum_execution,
                    max_quote_age_ms=max_quote_age_ms,
                    max_skew_ms=max_skew_ms,
                    quote_index=quote_index,
                ),
                "stress": _realize_outcome(
                    scenario="stress",
                    base=base,
                    direction=direction,
                    sample_ts=sample_ts,
                    latency_ms=int(execution["stress_latency_ms"]),
                    cost_bps=float(execution["stress_total_cost_bps"]),
                    minimum_capacity=minimum_execution,
                    max_quote_age_ms=max_quote_age_ms,
                    max_skew_ms=max_skew_ms,
                    quote_index=quote_index,
                ),
            }
            events.append(
                {
                    "base": base,
                    "direction": direction,
                    "signal_sample_ts": sample_ts,
                    "displayed_gross_edge_bps": displayed_gross,
                    "displayed_normal_net_edge_bps": displayed_net,
                    "displayed_capacity_quote": displayed_capacity,
                    "outcomes": outcomes,
                }
            )
            direction_counts[direction] += 1

    fill_numerators = {
        scenario: sum(
            1
            for event in events
            if event["outcomes"][scenario]["paired_fill"]
        )
        for scenario in ("normal", "stress")
    }
    denominator = len(events)
    return {
        "schema": REALIZATION_SCHEMA,
        "status": IMPLEMENTATION_STATUS,
        "synthetic_fixture_only": True,
        "contract_hash": contract["contract_hash"],
        "snapshot_count": len(seen_snapshots),
        "selected_event_count": denominator,
        "suppressed_by_cooldown": suppressed_by_cooldown,
        "direction_counts": dict(sorted(direction_counts.items())),
        "fill_rate_denominators": {
            "normal": denominator,
            "stress": denominator,
        },
        "paired_fill_numerators": fill_numerators,
        "events": events,
        "authorization": {
            "synthetic_fixture_execution_authorized": True,
            "actual_evaluator_authorized": False,
            "actual_market_data_allowed": False,
        },
        "safety": {
            "network_access": False,
            "actual_market_data_read": False,
            "returns_read": False,
            "pnl_computed": False,
            "oos_read": False,
            "grid_or_retune": False,
            "paper_forward": False,
            "live_orders": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
        },
        "next_allowed_action": (
            "KEEP_IMPLEMENTATION_REVIEW_ONLY_UNTIL_EXACT_EVALUATOR_APPROVAL"
        ),
    }
