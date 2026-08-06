from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

MAX_RUNTIME_SEC = 10_800
DEFAULT_RUNTIME_SEC = 1_200

MEXC_API_FUTURES_FEE_SOURCE = (
    "https://www.mexc.com/en-GB/announcements/article/"
    "updates-to-api-futures-trading-fees-jun-1-2026-17827791535742"
)
GATE_CONTRACT_FEE_SOURCE = "https://www.gate.com/docs/developers/apiv4/en/futures/"


def validate_runtime_sec(value: int | float, *, name: str = "max_runtime_sec") -> int:
    runtime = int(value)
    if runtime <= 0:
        raise ValueError(f"{name} must be > 0")
    if runtime > MAX_RUNTIME_SEC:
        raise ValueError(f"{name} must be <= {MAX_RUNTIME_SEC}")
    return runtime


@dataclass(frozen=True)
class VenueFeeSchedule:
    exchange: str
    spot_maker_bps: float
    spot_taker_bps: float
    perp_maker_bps: float
    perp_taker_bps: float
    source: str
    effective_at: str | None = None
    account_verified: bool = False
    conservative_floor_bps: float = 0.0

    def fee_bps(self, market_type: str, order_type: str) -> float:
        market = market_type.strip().lower()
        order = order_type.strip().lower()
        if market not in {"spot", "perp"}:
            raise ValueError(f"Unknown market_type: {market_type}")
        if order not in {"maker", "taker"}:
            raise ValueError(f"Unknown order_type: {order_type}")
        value = float(getattr(self, f"{market}_{order}_bps"))
        if not self.account_verified:
            value = max(value, float(self.conservative_floor_bps))
        return max(value, 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "spot_maker_bps": self.fee_bps("spot", "maker"),
            "spot_taker_bps": self.fee_bps("spot", "taker"),
            "perp_maker_bps": self.fee_bps("perp", "maker"),
            "perp_taker_bps": self.fee_bps("perp", "taker"),
            "source": self.source,
            "effective_at": self.effective_at,
            "account_verified": self.account_verified,
            "conservative_floor_bps": self.conservative_floor_bps,
        }


@dataclass(frozen=True)
class RouteLeg:
    exchange: str
    market_type: str
    spread_bps: float = 10.0
    impact_bps: float = 2.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "market_type": self.market_type,
            "spread_bps": float(self.spread_bps),
            "impact_bps": float(self.impact_bps),
        }


@dataclass(frozen=True)
class CostProfile:
    name: str = "base_api"
    schedules: dict[str, VenueFeeSchedule] = field(default_factory=dict)
    maker_fill_probability: float = 0.5
    slippage_bps_per_order: float = 1.0
    rebalance_buffer_bps: float = 10.0
    default_spread_bps: float = 10.0
    default_impact_bps: float = 2.0
    funding_haircut: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.maker_fill_probability <= 1.0:
            raise ValueError("maker_fill_probability must be in [0, 1]")
        for name in (
            "slippage_bps_per_order",
            "rebalance_buffer_bps",
            "default_spread_bps",
            "default_impact_bps",
        ):
            if float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be >= 0")
        if not 0.0 <= self.funding_haircut <= 1.0:
            raise ValueError("funding_haircut must be in [0, 1]")

    def schedule(self, exchange: str) -> VenueFeeSchedule:
        key = exchange.strip().lower()
        try:
            return self.schedules[key]
        except KeyError as exc:
            raise ValueError(f"Missing fee schedule for exchange: {exchange}") from exc

    def fee_bps(self, exchange: str, market_type: str, order_type: str) -> float:
        return self.schedule(exchange).fee_bps(market_type, order_type)

    def effective_entry_fee_bps(self, exchange: str, market_type: str) -> float:
        maker = self.fee_bps(exchange, market_type, "maker")
        taker = self.fee_bps(exchange, market_type, "taker")
        probability = self.maker_fill_probability
        return probability * maker + (1.0 - probability) * taker

    def cycle_cost(self, legs: Iterable[RouteLeg], *, stress: bool = False) -> dict[str, Any]:
        normalized = list(legs)
        if len(normalized) != 2:
            raise ValueError("A delta-neutral route must contain exactly two legs")

        profile = self.stress_profile() if stress else self
        fee_bps = 0.0
        spread_bps = 0.0
        impact_bps = 0.0
        slippage_bps = 0.0
        leg_rows: list[dict[str, Any]] = []
        for leg in normalized:
            entry_fee = profile.effective_entry_fee_bps(leg.exchange, leg.market_type)
            exit_fee = profile.fee_bps(leg.exchange, leg.market_type, "taker")
            # Maker entries cross no spread when filled. The unfilled share falls back to taker.
            entry_spread = max(float(leg.spread_bps), 0.0) / 2.0 * (
                1.0 - profile.maker_fill_probability
            )
            exit_spread = max(float(leg.spread_bps), 0.0) / 2.0
            entry_impact = max(float(leg.impact_bps), 0.0) * (
                1.0 - profile.maker_fill_probability
            )
            exit_impact = max(float(leg.impact_bps), 0.0)
            leg_slippage = profile.slippage_bps_per_order * 2.0
            fee_bps += entry_fee + exit_fee
            spread_bps += entry_spread + exit_spread
            impact_bps += entry_impact + exit_impact
            slippage_bps += leg_slippage
            leg_rows.append(
                {
                    **leg.as_dict(),
                    "entry_fee_bps": round(entry_fee, 6),
                    "exit_fee_bps": round(exit_fee, 6),
                    "entry_spread_bps": round(entry_spread, 6),
                    "exit_spread_bps": round(exit_spread, 6),
                    "entry_impact_bps": round(entry_impact, 6),
                    "exit_impact_bps": round(exit_impact, 6),
                }
            )
        total = fee_bps + spread_bps + impact_bps + slippage_bps + profile.rebalance_buffer_bps
        return {
            "profile": profile.name,
            "stress": stress,
            "maker_fill_probability": profile.maker_fill_probability,
            "fees_bps": round(fee_bps, 6),
            "spread_bps": round(spread_bps, 6),
            "impact_bps": round(impact_bps, 6),
            "slippage_bps": round(slippage_bps, 6),
            "rebalance_buffer_bps": round(profile.rebalance_buffer_bps, 6),
            "total_bps": round(total, 6),
            "legs": leg_rows,
        }

    def stress_profile(self) -> "CostProfile":
        schedules = {
            exchange: replace(
                schedule,
                spot_maker_bps=schedule.fee_bps("spot", "taker"),
                spot_taker_bps=schedule.fee_bps("spot", "taker"),
                perp_maker_bps=schedule.fee_bps("perp", "taker"),
                perp_taker_bps=schedule.fee_bps("perp", "taker"),
                account_verified=True,
                conservative_floor_bps=0.0,
            )
            for exchange, schedule in self.schedules.items()
        }
        return replace(
            self,
            name=f"{self.name}_stress",
            schedules=schedules,
            maker_fill_probability=0.0,
            rebalance_buffer_bps=self.rebalance_buffer_bps * 2.0,
            funding_haircut=self.funding_haircut * 0.5,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "maker_fill_probability": self.maker_fill_probability,
            "slippage_bps_per_order": self.slippage_bps_per_order,
            "rebalance_buffer_bps": self.rebalance_buffer_bps,
            "default_spread_bps": self.default_spread_bps,
            "default_impact_bps": self.default_impact_bps,
            "funding_haircut": self.funding_haircut,
            "schedules": {
                exchange: schedule.as_dict()
                for exchange, schedule in sorted(self.schedules.items())
            },
        }


def base_api_cost_profile() -> CostProfile:
    return CostProfile(
        schedules={
            "mexc": VenueFeeSchedule(
                exchange="mexc",
                spot_maker_bps=10.0,
                spot_taker_bps=10.0,
                perp_maker_bps=6.0,
                perp_taker_bps=8.0,
                source=MEXC_API_FUTURES_FEE_SOURCE,
                effective_at="2026-06-01T08:00:00Z",
                account_verified=True,
            ),
            "gateio": VenueFeeSchedule(
                exchange="gateio",
                spot_maker_bps=10.0,
                spot_taker_bps=10.0,
                perp_maker_bps=10.0,
                perp_taker_bps=10.0,
                source=GATE_CONTRACT_FEE_SOURCE,
                account_verified=False,
                conservative_floor_bps=10.0,
            ),
        }
    )


def route_legs(
    route: str,
    *,
    mexc_spread_bps: float | None = None,
    gate_spread_bps: float | None = None,
    spot_spread_bps: float | None = None,
    mexc_impact_bps: float | None = None,
    gate_impact_bps: float | None = None,
    spot_impact_bps: float | None = None,
    profile: CostProfile | None = None,
) -> list[RouteLeg]:
    cfg = profile or base_api_cost_profile()
    default_spread = cfg.default_spread_bps
    default_impact = cfg.default_impact_bps
    if route == "cross_venue_perp_perp":
        return [
            RouteLeg("mexc", "perp", mexc_spread_bps if mexc_spread_bps is not None else default_spread, mexc_impact_bps if mexc_impact_bps is not None else default_impact),
            RouteLeg("gateio", "perp", gate_spread_bps if gate_spread_bps is not None else default_spread, gate_impact_bps if gate_impact_bps is not None else default_impact),
        ]
    if route == "same_venue_mexc_spot_perp":
        return [
            RouteLeg("mexc", "spot", spot_spread_bps if spot_spread_bps is not None else default_spread, spot_impact_bps if spot_impact_bps is not None else default_impact),
            RouteLeg("mexc", "perp", mexc_spread_bps if mexc_spread_bps is not None else default_spread, mexc_impact_bps if mexc_impact_bps is not None else default_impact),
        ]
    if route == "same_venue_gateio_spot_perp":
        return [
            RouteLeg("gateio", "spot", spot_spread_bps if spot_spread_bps is not None else default_spread, spot_impact_bps if spot_impact_bps is not None else default_impact),
            RouteLeg("gateio", "perp", gate_spread_bps if gate_spread_bps is not None else default_spread, gate_impact_bps if gate_impact_bps is not None else default_impact),
        ]
    raise ValueError(f"Unknown route: {route}")
