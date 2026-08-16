"""Unit tests for orderbook_engine (VWAP, slippage, liquidity, and limit fills)."""

import pytest

from trading_mvp.src.orderbook_engine import (
    OrderBookSnapshot,
    Quote,
    immediate_limit_buy_fill,
    immediate_limit_sell_fill,
    quote_from_order_book,
    simulated_slippage_bps_buy,
    simulated_slippage_bps_sell,
    snapshot_from_order_book,
    spread_bps,
    symmetric_liquidity_quote,
    vwap_buy_base,
    vwap_buy_with_quote,
    vwap_sell_base,
)


def test_quote_properties():
    q = Quote(exchange_id="bybit", symbol="BTC/USDT", bid=50000.0, ask=50010.0)
    assert q.mid == 50005.0
    assert pytest.approx(q.spread_bps, 0.01) == (10.0 / 50005.0) * 10000.0


def test_quote_from_order_book():
    raw = {
        "bids": [[50000.0, 1.5], [49990.0, 2.0]],
        "asks": [[50010.0, 1.2], [50020.0, 3.0]],
    }
    q = quote_from_order_book("binance", "BTC/USDT", raw)
    assert q is not None
    assert q.bid == 50000.0
    assert q.ask == 50010.0

    # Inverted / invalid book returns None
    invalid = {"bids": [[50050.0, 1.0]], "asks": [[50000.0, 1.0]]}
    assert quote_from_order_book("binance", "BTC/USDT", invalid) is None

    # Empty book returns None
    assert quote_from_order_book("binance", "BTC/USDT", {}) is None


def test_snapshot_from_order_book():
    raw = {
        "bids": [[100.0, 10.0], [99.0, 20.0], [98.0, 30.0]],
        "asks": [[101.0, 15.0], [102.0, 25.0]],
    }
    snap = snapshot_from_order_book("bybit", "SOL/USDT", raw, depth_levels=2)
    assert snap is not None
    assert snap.best_bid == 100.0
    assert snap.best_ask == 101.0
    assert len(snap.bids) == 2
    assert len(snap.asks) == 2
    assert snap.bids == ((100.0, 10.0), (99.0, 20.0))


def test_symmetric_liquidity_quote():
    raw = {
        "bids": [[100.0, 10.0], [99.0, 10.0]],  # 1000 + 990 = 1990
        "asks": [[101.0, 5.0], [102.0, 10.0]],   # 505 + 1020 = 1525
    }
    liq = symmetric_liquidity_quote(raw, levels=2)
    assert liq == 1525.0


def test_vwap_buy_with_quote():
    # Asks: 10 SOL @ $100 (= $1000), 10 SOL @ $110 (= $1100)
    asks = [[100.0, 10.0], [110.0, 10.0]]

    # 1. Spend $500 -> fills 5 SOL @ $100 -> VWAP = 100
    base, vwap, spent, complete = vwap_buy_with_quote(asks, quote_budget=500.0)
    assert complete is True
    assert base == 5.0
    assert spent == 500.0
    assert vwap == 100.0

    # 2. Spend $1550 -> fills 10 SOL @ 100 ($1000) + 5 SOL @ 110 ($550) -> VWAP = 1550 / 15 = 103.333
    base, vwap, spent, complete = vwap_buy_with_quote(asks, quote_budget=1550.0)
    assert complete is True
    assert pytest.approx(base, 1e-6) == 15.0
    assert spent == 1550.0
    assert pytest.approx(vwap, 1e-4) == 1550.0 / 15.0

    # 3. Oversized budget ($5000) exceeds depth -> partial complete = False
    base, vwap, spent, complete = vwap_buy_with_quote(asks, quote_budget=5000.0)
    assert complete is False
    assert base == 20.0
    assert spent == 2100.0


def test_vwap_buy_base_and_sell_base():
    asks = [[100.0, 5.0], [102.0, 5.0]]
    spent, vwap, bought, complete = vwap_buy_base(asks, base_amount=8.0)
    # 5 @ 100 = 500, 3 @ 102 = 306 -> spent = 806 -> vwap = 806 / 8 = 100.75
    assert complete is True
    assert bought == 8.0
    assert spent == 806.0
    assert vwap == 100.75

    bids = [[100.0, 5.0], [98.0, 5.0]]
    recv, vwap_s, sold, complete_s = vwap_sell_base(bids, base_amount=7.0)
    # 5 @ 100 = 500, 2 @ 98 = 196 -> recv = 696 -> vwap = 696 / 7 = 99.42857
    assert complete_s is True
    assert sold == 7.0
    assert recv == 696.0
    assert pytest.approx(vwap_s, 1e-4) == 696.0 / 7.0


def test_simulated_slippage():
    # best_ask = 100, vwap = 101, mid = 100 -> slip = 1 / 100 * 10000 = 100 bps
    slip_buy = simulated_slippage_bps_buy(best_ask=100.0, vwap=101.0, mid=100.0)
    assert pytest.approx(slip_buy, 1e-6) == 100.0

    # best_bid = 100, vwap = 99, mid = 100 -> slip = 1 / 100 * 10000 = 100 bps
    slip_sell = simulated_slippage_bps_sell(best_bid=100.0, vwap=99.0, mid=100.0)
    assert pytest.approx(slip_sell, 1e-6) == 100.0


def test_immediate_limit_fills():
    asks = [[100.0, 2.0], [101.0, 3.0], [105.0, 5.0]]
    # Limit buy price 102.0, amount 4.0 -> fills 2 @ 100 + 2 @ 101 = 4.0 -> spent = 200 + 202 = 402
    filled, spent, avg = immediate_limit_buy_fill(limit_price=102.0, amount_base=4.0, asks=asks)
    assert filled == 4.0
    assert spent == 402.0
    assert avg == 100.5

    # Limit buy price 99.0 (below best ask 100) -> 0 fills
    filled_0, spent_0, avg_0 = immediate_limit_buy_fill(limit_price=99.0, amount_base=4.0, asks=asks)
    assert filled_0 == 0.0
    assert spent_0 == 0.0

    bids = [[100.0, 2.0], [98.0, 3.0], [90.0, 5.0]]
    # Limit sell price 95.0, amount 4.0 -> fills 2 @ 100 + 2 @ 98 = 4.0 -> recv = 200 + 196 = 396
    filled_s, recv_s, avg_s = immediate_limit_sell_fill(limit_price=95.0, amount_base=4.0, bids=bids)
    assert filled_s == 4.0
    assert recv_s == 396.0
    assert avg_s == 99.0
