"""Realistic paper execution engine and analytics simulator based on L2 Order Book depth.

Ported and enhanced from Ekskavator for ZolotyayLopata trading_mvp research & proof pipeline.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from trading_mvp.src.orderbook_engine import (
    OrderBookSnapshot,
    immediate_limit_buy_fill,
    immediate_limit_sell_fill,
    vwap_buy_base,
    vwap_sell_base,
)

log = logging.getLogger(__name__)


@dataclass
class PaperOrder:
    """Simulated order tracking for paper trading and backtest replay."""

    order_id: str
    exchange_id: str
    symbol: str
    side: Literal["buy", "sell"]
    amount_base: float
    order_type: Literal["limit", "market"] = "limit"
    limit_price: float = 0.0
    time_in_force: Literal["GTC", "IOC", "FOK"] = "GTC"
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 5.5

    filled_base: float = 0.0
    cum_quote: float = 0.0
    fee_quote: float = 0.0
    status: Literal["open", "partially_filled", "filled", "canceled", "rejected"] = "open"
    created_mono: float = field(default_factory=time.monotonic)
    updated_mono: float = field(default_factory=time.monotonic)
    closed_mono: float | None = None
    realized_delta_quote: float = 0.0

    @property
    def remaining_base(self) -> float:
        return max(0.0, self.amount_base - self.filled_base)

    @property
    def avg_fill_price(self) -> float:
        if self.filled_base <= 0:
            return 0.0
        return self.cum_quote / self.filled_base

    @property
    def is_active(self) -> bool:
        return self.status in ("open", "partially_filled")


class PaperExecutionAnalytics:
    """Session-level analytics tracking for simulated fills, fees, and execution efficiency."""

    def __init__(self) -> None:
        self.closed_orders = 0
        self.closed_buy = 0
        self.closed_sell = 0
        self.realized_events = 0
        self.realized_pos = 0
        self.realized_neg = 0
        self.realized_zero = 0
        self.realized_quote = 0.0
        self.fees_quote = 0.0
        self.hold_seconds_sum = 0.0
        self.total_turnover_quote = 0.0
        self.total_filled_base = 0.0

        self.reject_risk = 0
        self.reject_capital = 0
        self.reject_spread = 0

        self._by_symbol: dict[tuple[str, str], dict[str, float]] = {}

    def on_reject(self, category: Literal["risk", "capital", "spread"]) -> None:
        if category == "risk":
            self.reject_risk += 1
        elif category == "capital":
            self.reject_capital += 1
        elif category == "spread":
            self.reject_spread += 1

    def on_closed_order(self, order: PaperOrder) -> None:
        self.closed_orders += 1
        if order.side == "buy":
            self.closed_buy += 1
        else:
            self.closed_sell += 1

        self.realized_quote += order.realized_delta_quote
        self.fees_quote += order.fee_quote
        self.total_turnover_quote += order.cum_quote
        self.total_filled_base += order.filled_base

        if abs(order.realized_delta_quote) < 1e-12:
            self.realized_zero += 1
        elif order.realized_delta_quote > 0:
            self.realized_events += 1
            self.realized_pos += 1
        else:
            self.realized_events += 1
            self.realized_neg += 1

        if order.closed_mono is not None and order.created_mono > 0:
            hold = max(0.0, order.closed_mono - order.created_mono)
            self.hold_seconds_sum += hold

        key = (order.exchange_id, order.symbol)
        s = self._by_symbol.setdefault(
            key,
            {
                "closed_orders": 0.0,
                "realized_quote": 0.0,
                "fees_quote": 0.0,
                "turnover_quote": 0.0,
            },
        )
        s["closed_orders"] += 1.0
        s["realized_quote"] += order.realized_delta_quote
        s["fees_quote"] += order.fee_quote
        s["turnover_quote"] += order.cum_quote

    @property
    def avg_hold_seconds(self) -> float:
        if self.closed_orders <= 0:
            return 0.0
        return self.hold_seconds_sum / self.closed_orders

    @property
    def net_pnl_quote(self) -> float:
        return self.realized_quote - self.fees_quote

    @property
    def win_rate(self) -> float:
        if self.realized_events <= 0:
            return 0.0
        return self.realized_pos / self.realized_events

    def summary(self) -> dict[str, Any]:
        return {
            "closed_orders": self.closed_orders,
            "closed_buy": self.closed_buy,
            "closed_sell": self.closed_sell,
            "realized_quote": round(self.realized_quote, 4),
            "fees_quote": round(self.fees_quote, 4),
            "net_pnl_quote": round(self.net_pnl_quote, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_hold_seconds": round(self.avg_hold_seconds, 2),
            "total_turnover_quote": round(self.total_turnover_quote, 2),
            "rejections": {
                "risk": self.reject_risk,
                "capital": self.reject_capital,
                "spread": self.reject_spread,
            },
        }


class SimulatedOrderBookExecutor:
    """Manages simulated limit & IOC order execution against L2 order book feeds."""

    def __init__(self, analytics: PaperExecutionAnalytics | None = None) -> None:
        self.analytics = analytics or PaperExecutionAnalytics()
        self.orders: dict[str, PaperOrder] = {}

    def submit_order(
        self,
        exchange_id: str,
        symbol: str,
        side: Literal["buy", "sell"],
        amount_base: float,
        order_type: Literal["limit", "market"] = "limit",
        limit_price: float = 0.0,
        time_in_force: Literal["GTC", "IOC", "FOK"] = "GTC",
        current_book: OrderBookSnapshot | None = None,
        now_mono: float | None = None,
    ) -> PaperOrder:
        """Submit paper order and attempt immediate match if book is available."""
        now = now_mono if now_mono is not None else time.monotonic()
        order_id = str(uuid.uuid4())[:8]
        order = PaperOrder(
            order_id=order_id,
            exchange_id=exchange_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            limit_price=limit_price,
            amount_base=amount_base,
            time_in_force=time_in_force,
            created_mono=now,
            updated_mono=now,
        )
        self.orders[order_id] = order

        if current_book is not None:
            self._match_order(order, current_book, now_mono=now, is_maker=False)

        if (order.time_in_force == "IOC" or order.order_type == "market") and order.is_active:
            # Cancel unfilled remainder for IOC / market
            order.status = "filled" if order.filled_base > 0 else "canceled"
            order.closed_mono = now
            self.analytics.on_closed_order(order)

        return order

    def on_order_book_update(
        self,
        snapshot: OrderBookSnapshot,
        now_mono: float | None = None,
    ) -> list[PaperOrder]:
        """Process incoming L2 book update against all open orders for symbol."""
        now = now_mono if now_mono is not None else time.monotonic()
        affected: list[PaperOrder] = []
        for order in list(self.orders.values()):
            if not order.is_active:
                continue
            if order.exchange_id != snapshot.exchange_id or order.symbol != snapshot.symbol:
                continue
            prev_filled = order.filled_base
            self._match_order(order, snapshot, now_mono=now, is_maker=True)
            if order.filled_base > prev_filled or not order.is_active:
                affected.append(order)
        return affected

    def _match_order(
        self,
        order: PaperOrder,
        snapshot: OrderBookSnapshot,
        now_mono: float,
        is_maker: bool = False,
    ) -> None:
        rem = order.remaining_base
        if rem <= 1e-12:
            return

        if order.side == "buy":
            if order.order_type == "market":
                spent, _, filled, _ = vwap_buy_base(asks=snapshot.asks, base_amount=rem)
            else:
                filled, spent, _ = immediate_limit_buy_fill(
                    limit_price=order.limit_price,
                    amount_base=rem,
                    asks=snapshot.asks,
                )
        else:
            if order.order_type == "market":
                spent, _, filled, _ = vwap_sell_base(bids=snapshot.bids, base_amount=rem)
            else:
                filled, spent, _ = immediate_limit_sell_fill(
                    limit_price=order.limit_price,
                    amount_base=rem,
                    bids=snapshot.bids,
                )

        if filled > 0:
            order.filled_base += filled
            order.cum_quote += spent
            # Fee calculation: taker fee if crossed spread, maker if resting
            fee_bps = order.maker_fee_bps if is_maker else order.taker_fee_bps
            order.fee_quote += spent * (fee_bps / 10_000.0)
            order.updated_mono = now_mono

            if order.remaining_base <= 1e-12:
                order.status = "filled"
                order.closed_mono = now_mono
                self.analytics.on_closed_order(order)
            else:
                order.status = "partially_filled"

    def cancel_order(self, order_id: str, now_mono: float | None = None) -> PaperOrder | None:
        order = self.orders.get(order_id)
        if not order or not order.is_active:
            return None
        now = now_mono if now_mono is not None else time.monotonic()
        order.status = "canceled"
        order.closed_mono = now
        order.updated_mono = now
        self.analytics.on_closed_order(order)
        return order
