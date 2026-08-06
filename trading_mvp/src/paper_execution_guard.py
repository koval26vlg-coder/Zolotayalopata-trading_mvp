from __future__ import annotations

import math
from typing import Any, Mapping

from historical_basis_probe import depth_execution_metrics


def _blocked(reason: str, *, action: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "allowed": False,
        "reason": reason,
        "action": action,
        "details": dict(details or {}),
    }


def evaluate_depth_execution_guard(
    plan: Mapping[str, Any],
    _state: Mapping[str, Any],
    observation: Mapping[str, Any],
    transition: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a simulated two-leg taker transition against synchronized depth."""

    action = str(transition.get("action") or "").strip().lower()
    if action not in {"open", "close"}:
        raise ValueError("paper execution transition action must be open or close")
    guard = plan.get("execution_guard")
    if not isinstance(guard, Mapping) or guard.get("required_for_position_transition") is not True:
        raise ValueError("paper execution guard is missing from the frozen plan")
    books = observation.get("execution_books")
    if not isinstance(books, Mapping):
        return _blocked("missing_execution_books", action=action)

    observation_ts_ms = float(observation["ts"]) * 1_000.0
    venue_books: dict[str, Mapping[str, Any]] = {}
    observed_ts: dict[str, float] = {}
    for venue in ("mexc", "gateio"):
        book = books.get(venue)
        if not isinstance(book, Mapping):
            return _blocked("missing_execution_books", action=action, details={"venue": venue})
        try:
            timestamp = float(book["observed_ts_ms"])
        except (KeyError, TypeError, ValueError):
            return _blocked("invalid_quote_timestamp", action=action, details={"venue": venue})
        if not math.isfinite(timestamp):
            return _blocked("invalid_quote_timestamp", action=action, details={"venue": venue})
        venue_books[venue] = book
        observed_ts[venue] = timestamp

    maximum_age_ms = float(guard["maximum_quote_age_ms"])
    ages = {venue: observation_ts_ms - timestamp for venue, timestamp in observed_ts.items()}
    if any(age < 0.0 for age in ages.values()):
        return _blocked("future_quote", action=action, details={"quote_age_ms": ages})
    if any(age > maximum_age_ms for age in ages.values()):
        return _blocked("stale_quote", action=action, details={"quote_age_ms": ages})
    skew_ms = abs(observed_ts["mexc"] - observed_ts["gateio"])
    if skew_ms > float(guard["maximum_timestamp_skew_ms"]):
        return _blocked("timestamp_skew", action=action, details={"timestamp_skew_ms": skew_ms})

    long_venue = str(transition["long_venue"])
    short_venue = str(transition["short_venue"])
    if {long_venue, short_venue} != {"mexc", "gateio"}:
        raise ValueError("paper execution transition must contain MEXC and Gate legs")
    side_by_venue = (
        {long_venue: "buy", short_venue: "sell"}
        if action == "open"
        else {long_venue: "sell", short_venue: "buy"}
    )
    notional = float(guard["notional_quote_per_leg"])
    maximum_impact = float(guard["maximum_impact_bps"])
    minimum_capacity = float(guard["minimum_capacity_quote_per_leg"])
    metrics: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for venue, side in side_by_venue.items():
        levels_key = "asks" if side == "buy" else "bids"
        levels = venue_books[venue].get(levels_key)
        if not isinstance(levels, (list, tuple)):
            return _blocked(
                "missing_depth_levels",
                action=action,
                details={"venue": venue, "side": side},
            )
        leg_metrics = depth_execution_metrics(
            levels,
            side=side,
            notional_quote=notional,
            max_impact_bps=maximum_impact,
        )
        metrics[venue] = {"side": side, **leg_metrics}
        capacity = float(leg_metrics["capacity_quote_at_max_impact"])
        impact = float(leg_metrics["impact_bps"])
        if capacity < minimum_capacity:
            reasons.append("insufficient_capacity")
        elif not leg_metrics["filled"]:
            reasons.append("insufficient_depth")
        elif not math.isfinite(impact) or impact > maximum_impact:
            reasons.append("excessive_impact")
    if reasons:
        reason = next(
            candidate
            for candidate in ("insufficient_capacity", "insufficient_depth", "excessive_impact")
            if candidate in reasons
        )
        return _blocked(
            reason,
            action=action,
            details={"timestamp_skew_ms": skew_ms, "legs": metrics},
        )

    trade_prices = {
        venue: float(leg_metrics["average_price"])
        for venue, leg_metrics in metrics.items()
    }
    return {
        "allowed": True,
        "reason": None,
        "action": action,
        "trade_prices": trade_prices,
        "details": {
            "timestamp_skew_ms": skew_ms,
            "quote_age_ms": ages,
            "legs": metrics,
        },
    }
