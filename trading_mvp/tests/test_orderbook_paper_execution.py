"""Unit tests for orderbook_paper_execution (simulated execution & session analytics)."""

import pytest

from trading_mvp.src.orderbook_engine import OrderBookSnapshot
from trading_mvp.src.orderbook_paper_execution import (
    PaperExecutionAnalytics,
    PaperOrder,
    SimulatedOrderBookExecutor,
)


def test_paper_execution_analytics():
    analytics = PaperExecutionAnalytics()

    order_win = PaperOrder(
        order_id="1",
        exchange_id="bybit",
        symbol="BTC/USDT",
        side="buy",
        limit_price=50000.0,
        amount_base=1.0,
        filled_base=1.0,
        cum_quote=50000.0,
        fee_quote=27.5,
        status="filled",
        created_mono=10.0,
        closed_mono=15.0,
        realized_delta_quote=150.0,
    )
    analytics.on_closed_order(order_win)

    assert analytics.closed_orders == 1
    assert analytics.closed_buy == 1
    assert analytics.win_rate == 1.0
    assert analytics.realized_quote == 150.0
    assert analytics.fees_quote == 27.5
    assert analytics.net_pnl_quote == 122.5
    assert analytics.avg_hold_seconds == 5.0


def test_simulated_order_book_executor_immediate_ioc():
    executor = SimulatedOrderBookExecutor()

    snap = OrderBookSnapshot(
        exchange_id="bybit",
        symbol="BTC/USDT",
        best_bid=50000.0,
        best_ask=50010.0,
        bids=((50000.0, 1.0), (49990.0, 2.0)),
        asks=((50010.0, 0.5), (50020.0, 1.0)),
    )

    # Submit IOC buy for 1.0 BTC with limit 50015 -> can only take 0.5 @ 50010, remaining 0.5 canceled
    order = executor.submit_order(
        exchange_id="bybit",
        symbol="BTC/USDT",
        side="buy",
        limit_price=50015.0,
        amount_base=1.0,
        time_in_force="IOC",
        current_book=snap,
        now_mono=10.0,
    )

    assert order.status == "filled"  # IOC with partial fill marked filled for filled portion
    assert order.filled_base == 0.5
    assert order.cum_quote == 25005.0
    assert order.fee_quote > 0.0


def test_simulated_order_book_executor_resting_limit_fill():
    executor = SimulatedOrderBookExecutor()

    # Initial book (bid 50000, ask 50010)
    snap1 = OrderBookSnapshot(
        exchange_id="bybit",
        symbol="BTC/USDT",
        best_bid=50000.0,
        best_ask=50010.0,
        bids=((50000.0, 1.0),),
        asks=((50010.0, 1.0),),
    )

    # Submit GTC buy limit at 50005 (resting between bid and ask)
    order = executor.submit_order(
        exchange_id="bybit",
        symbol="BTC/USDT",
        side="buy",
        limit_price=50005.0,
        amount_base=1.0,
        time_in_force="GTC",
        current_book=snap1,
        now_mono=10.0,
    )
    assert order.status == "open"
    assert order.filled_base == 0.0

    # Book moves down: ask becomes 50004
    snap2 = OrderBookSnapshot(
        exchange_id="bybit",
        symbol="BTC/USDT",
        best_bid=49995.0,
        best_ask=50004.0,
        bids=((49995.0, 1.0),),
        asks=((50004.0, 1.5),),
    )

    affected = executor.on_order_book_update(snap2, now_mono=12.0)
    assert len(affected) == 1
    assert order.status == "filled"
    assert order.filled_base == 1.0
    assert order.cum_quote == 50004.0
