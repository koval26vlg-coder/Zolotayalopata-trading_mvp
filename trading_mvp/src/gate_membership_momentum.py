from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable


DAY_SEC = 86_400
GATE_FEE_SOURCE = "https://www.gate.com/docs/developers/apiv4/en/futures/"


@dataclass
class MarketSeries:
    exchange: str
    symbol: str
    base: str
    canonical_asset_id: str
    opens: dict[int, float] = field(default_factory=dict)
    closes: dict[int, float] = field(default_factory=dict)
    quote_volumes: dict[int, float] = field(default_factory=dict)
    funding: list[tuple[int, float]] = field(default_factory=list)

    def rolling_median_quote_volume(self, signal_day: int, window_days: int) -> float:
        values = [
            float(self.quote_volumes[day])
            for day in range(signal_day - window_days + 1, signal_day + 1)
            if float(self.quote_volumes.get(day, 0.0)) > 0.0
        ]
        if len(values) != window_days:
            return 0.0
        return float(statistics.median(values))

    def funding_sum(self, entry_day: int, exit_day: int) -> float:
        entry_ts = int(entry_day) * DAY_SEC
        exit_ts = int(exit_day) * DAY_SEC
        return sum(float(rate) for timestamp, rate in self.funding if entry_ts < int(timestamp) <= exit_ts)


@dataclass(frozen=True)
class FrozenMomentumConfig:
    lookback_days: int = 30
    hold_days: int = 7
    rebalance_every_days: int = 7
    min_per_side: int = 5
    minimum_scored_markets: int = 20
    liquidity_lookback_days: int = 7
    minimum_median_quote_volume: float = 1_000_000.0

    def __post_init__(self) -> None:
        for name in (
            "lookback_days",
            "hold_days",
            "rebalance_every_days",
            "min_per_side",
            "minimum_scored_markets",
            "liquidity_lookback_days",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.minimum_scored_markets < self.min_per_side * 4:
            raise ValueError("minimum_scored_markets must be at least four times min_per_side")
        if not math.isfinite(float(self.minimum_median_quote_volume)) or self.minimum_median_quote_volume < 0:
            raise ValueError("minimum_median_quote_volume must be finite and non-negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "lookback_days": self.lookback_days,
            "hold_days": self.hold_days,
            "rebalance_every_days": self.rebalance_every_days,
            "min_per_side": self.min_per_side,
            "minimum_scored_markets": self.minimum_scored_markets,
            "bucket_rule": "max(min_per_side,floor(scored_markets/10))",
            "liquidity_lookback_days": self.liquidity_lookback_days,
            "minimum_median_quote_volume": self.minimum_median_quote_volume,
            "signal_price": "closed_daily_close",
            "entry_price": "next_closed_daily_open",
            "exit_price": "daily_open_after_hold_days",
            "parameter_selection": "forbidden",
        }


@dataclass(frozen=True)
class RebalanceEvent:
    signal_day: int
    entry_day: int
    exit_day: int
    long_bases: tuple[str, ...]
    short_bases: tuple[str, ...]
    price_return: float
    funding_return: float
    base_price_contributions: dict[str, float]
    base_funding_contributions: dict[str, float]

    @property
    def position_count(self) -> int:
        return len(self.long_bases) + len(self.short_bases)


def cost_contract() -> dict[str, Any]:
    normal = {
        "fee_bps": 20.0,
        "spread_bps": 10.0,
        "impact_bps": 4.0,
        "slippage_bps": 2.0,
        "rebalance_buffer_bps": 10.0,
    }
    stress = {
        "fee_bps": 20.0,
        "spread_bps": 20.0,
        "impact_bps": 8.0,
        "slippage_bps": 4.0,
        "rebalance_buffer_bps": 20.0,
    }
    normal["total_bps"] = sum(normal.values())
    stress["total_bps"] = sum(stress.values())
    return {
        "name": "gate_perp_cross_sectional_base_vip0_ohlcv_conservative_v1",
        "exchange": "gateio",
        "market_type": "usdt_linear_perpetual",
        "maker_fill_probability": 0.0,
        "fee_provenance": {
            "per_operation_taker_bps": 10.0,
            "source": GATE_FEE_SOURCE,
            "account_specific_verified": False,
            "rebates_allowed": False,
        },
        "normal": normal,
        "stress": stress,
        "stress_funding_policy": "zero_favorable_preserve_adverse",
    }


def _finite_positive(value: float | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) and result > 0.0 else None


def evaluate_rebalance(
    markets: Iterable[MarketSeries],
    *,
    signal_day: int,
    config: FrozenMomentumConfig,
) -> RebalanceEvent | None:
    signal = int(signal_day)
    entry_day = signal + 1
    exit_day = entry_day + config.hold_days
    scored: list[tuple[float, MarketSeries]] = []
    for market in markets:
        current = _finite_positive(market.closes.get(signal))
        previous = _finite_positive(market.closes.get(signal - config.lookback_days))
        entry = _finite_positive(market.opens.get(entry_day))
        exit_price = _finite_positive(market.opens.get(exit_day))
        if None in (current, previous, entry, exit_price):
            continue
        if (
            market.rolling_median_quote_volume(signal, config.liquidity_lookback_days)
            < config.minimum_median_quote_volume
        ):
            continue
        assert current is not None and previous is not None
        scored.append((current / previous - 1.0, market))
    if len(scored) < config.minimum_scored_markets:
        return None
    scored.sort(key=lambda item: (item[0], item[1].canonical_asset_id, item[1].symbol))
    bucket = max(config.min_per_side, len(scored) // 10)
    shorts = scored[:bucket]
    longs = scored[-bucket:]
    if {market.canonical_asset_id for _, market in shorts} & {
        market.canonical_asset_id for _, market in longs
    }:
        raise ValueError("long and short momentum buckets overlap")

    base_price: dict[str, float] = {}
    base_funding: dict[str, float] = {}

    def apply_leg(items: list[tuple[float, MarketSeries]], sign: int) -> tuple[float, float]:
        leg_price = 0.0
        leg_funding = 0.0
        weight = 0.5 / len(items)
        for _, market in items:
            entry = float(market.opens[entry_day])
            exit_price = float(market.opens[exit_day])
            raw_return = exit_price / entry - 1.0
            price_component = weight * sign * raw_return
            funding_component = weight * (-sign) * market.funding_sum(entry_day, exit_day)
            base_price[market.base] = base_price.get(market.base, 0.0) + price_component
            base_funding[market.base] = base_funding.get(market.base, 0.0) + funding_component
            leg_price += price_component
            leg_funding += funding_component
        return leg_price, leg_funding

    long_price, long_funding = apply_leg(longs, +1)
    short_price, short_funding = apply_leg(shorts, -1)
    return RebalanceEvent(
        signal_day=signal,
        entry_day=entry_day,
        exit_day=exit_day,
        long_bases=tuple(market.base for _, market in longs),
        short_bases=tuple(market.base for _, market in shorts),
        price_return=long_price + short_price,
        funding_return=long_funding + short_funding,
        base_price_contributions=base_price,
        base_funding_contributions=base_funding,
    )


def _adjust_funding(value: float, favorable_multiplier: float) -> float:
    return value if value <= 0.0 else value * favorable_multiplier


def adjusted_event_funding(event: RebalanceEvent, favorable_multiplier: float) -> float:
    if not 0.0 <= favorable_multiplier <= 1.0:
        raise ValueError("favorable_multiplier must be in [0, 1]")
    if event.base_funding_contributions:
        return sum(
            _adjust_funding(value, favorable_multiplier)
            for value in event.base_funding_contributions.values()
        )
    return _adjust_funding(event.funding_return, favorable_multiplier)


def portfolio_metrics(
    events: list[RebalanceEvent],
    *,
    cost_bps: float,
    favorable_funding_multiplier: float,
) -> dict[str, Any]:
    if not 0.0 <= favorable_funding_multiplier <= 1.0:
        raise ValueError("favorable_funding_multiplier must be in [0, 1]")
    cost = float(cost_bps) / 10_000.0
    if not events:
        return {
            "independent_rebalances": 0,
            "unique_rebalance_dates": 0,
            "unique_assets_traded": 0,
        }
    price_nets: list[float] = []
    funding_values: list[float] = []
    total_nets: list[float] = []
    base_contributions: dict[str, float] = {}
    assets: set[str] = set()
    for event in events:
        adjusted_funding = adjusted_event_funding(event, favorable_funding_multiplier)
        price_nets.append(event.price_return - cost)
        funding_values.append(adjusted_funding)
        total_nets.append(event.price_return + adjusted_funding - cost)
        assets.update(event.long_bases)
        assets.update(event.short_bases)
        per_position_cost = cost / max(1, event.position_count)
        for base in set(event.base_price_contributions) | set(event.base_funding_contributions):
            contribution = event.base_price_contributions.get(base, 0.0)
            contribution += _adjust_funding(
                event.base_funding_contributions.get(base, 0.0),
                favorable_funding_multiplier,
            )
            base_contributions[base] = base_contributions.get(base, 0.0) + contribution - per_position_cost
    gains = sum(value for value in total_nets if value > 0.0)
    losses = -sum(value for value in total_nets if value < 0.0)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in total_nets:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    positive_base_total = sum(value for value in base_contributions.values() if value > 0.0)
    top_base = None
    top_base_share = 0.0
    if positive_base_total > 0.0:
        top_base, top_value = max(base_contributions.items(), key=lambda item: item[1])
        top_base_share = max(0.0, top_value) / positive_base_total
    total_positive_pnl = sum(value for value in total_nets if value > 0.0)
    funding_sum = sum(funding_values)
    return {
        "independent_rebalances": len(events),
        "unique_rebalance_dates": len({event.signal_day for event in events}),
        "unique_assets_traded": len(assets),
        "price_only_net_expectancy_bps": round(statistics.fmean(price_nets) * 10_000.0, 8),
        "funding_expectancy_bps": round(statistics.fmean(funding_values) * 10_000.0, 8),
        "total_net_expectancy_bps": round(statistics.fmean(total_nets) * 10_000.0, 8),
        "price_only_net_pnl_pct": round(sum(price_nets) * 100.0, 8),
        "funding_pnl_pct": round(funding_sum * 100.0, 8),
        "total_net_pnl_pct": round(sum(total_nets) * 100.0, 8),
        "profit_factor": round(gains / losses, 8) if losses > 0.0 else None,
        "positive_rebalance_rate": round(sum(value > 0.0 for value in total_nets) / len(total_nets), 8),
        "max_drawdown_pct": round(max_drawdown * 100.0, 8),
        "top_base": top_base,
        "top_base_positive_share": round(top_base_share, 8),
        "absolute_funding_share_of_positive_pnl": round(
            abs(funding_sum) / total_positive_pnl if total_positive_pnl > 0.0 else 1.0,
            8,
        ),
        "cost_bps_per_rebalance": float(cost_bps),
    }
