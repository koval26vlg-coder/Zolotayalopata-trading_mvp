"""Unit tests for orderflow_engine (TapeStore sliding window and book pressure)."""

import pytest

from trading_mvp.src.orderbook_engine import Quote
from trading_mvp.src.orderflow_engine import (
    OrderflowConfig,
    OrderflowSignalEvaluator,
    OrderflowTapeStore,
    TapeWindowStats,
    depth_pressure,
)


def test_tape_window_stats():
    st = TapeWindowStats(buy_quote=700.0, sell_quote=300.0, t_span_sec=2.5)
    assert st.total == 1000.0
    assert pytest.approx(st.buy_share, 1e-4) == 0.70


def test_orderflow_tape_store_sliding_window():
    store = OrderflowTapeStore(window_seconds=2.0, max_events=100)

    # Push buy trade at t=10.0
    store.push("bybit", "BTC/USDT", {"side": "buy", "price": 50000.0, "amount": 0.1}, timestamp_mono=10.0)
    # Push sell trade at t=10.5
    store.push("bybit", "BTC/USDT", {"side": "sell", "price": 50000.0, "amount": 0.05}, timestamp_mono=10.5)

    # Query at t=11.0 (both inside window [9.0, 11.0])
    stats = store.window_stats("bybit", "BTC/USDT", now_mono=11.0)
    assert stats is not None
    assert stats.buy_quote == 5000.0
    assert stats.sell_quote == 2500.0
    assert stats.total == 7500.0

    # Query at t=12.2 (t=10.0 buy is outside window [10.2, 12.2])
    stats_later = store.window_stats("bybit", "BTC/USDT", now_mono=12.2)
    assert stats_later is not None
    assert stats_later.buy_quote == 0.0
    assert stats_later.sell_quote == 2500.0


def test_depth_pressure():
    ob = {
        "bids": [[100.0, 10.0], [99.0, 20.0]],  # 1000 + 1980 = 2980
        "asks": [[101.0, 5.0], [102.0, 5.0]],    # 505 + 510 = 1015
    }
    pr = depth_pressure(ob, levels=2)
    assert pr is not None
    bq, aq = pr
    assert bq == 2980.0
    assert aq == 1015.0


def test_orderflow_signal_evaluator():
    store = OrderflowTapeStore(window_seconds=5.0)
    cfg = OrderflowConfig(
        max_spread_bps=20.0,
        tape_min_total_quote=1000.0,
        tape_long_share=0.65,
        book_min_side_quote=500.0,
        book_ratio_long=1.5,
        cooldown_seconds=1.0,
        signal_mode="both",
    )
    evaluator = OrderflowSignalEvaluator(config=cfg, tape_store=store)

    # 1. Fill tape with 80% buy at t=10.0
    store.push("bybit", "ETH/USDT", {"side": "buy", "price": 3000.0, "amount": 1.0}, timestamp_mono=10.0)
    store.push("bybit", "ETH/USDT", {"side": "sell", "price": 3000.0, "amount": 0.2}, timestamp_mono=10.1)

    # 2. Book with strong bid pressure (bid/ask ratio = 2.0x)
    ob = {
        "bids": [[3000.0, 2.0]],  # 6000
        "asks": [[3001.0, 1.0]],  # 3001
    }
    q = Quote(exchange_id="bybit", symbol="ETH/USDT", bid=3000.0, ask=3001.0)

    # Evaluate at t=10.2
    sig = evaluator.evaluate_quote(q, order_book=ob, now_mono=10.2)
    assert sig is not None
    assert sig.side == "buy"
    assert "LONG" in sig.detail
    assert sig.impulse_bps >= 5.0

    # Cooldown check at t=10.5 (within cooldown 1.0s) -> None
    sig_cd = evaluator.evaluate_quote(q, order_book=ob, now_mono=10.5)
    assert sig_cd is None
