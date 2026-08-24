import pytest
from trading_mvp.src.orderbook_engine import (
    vwap_buy_base,
    vwap_sell_base,
    vwap_buy_with_quote,
    immediate_limit_buy_fill,
    immediate_limit_sell_fill,
)

def test_vwap_buy_edge_cases():
    # Empty asks
    assert vwap_buy_base([], 1.0) == (0.0, 0.0, 0.0, False)
    assert vwap_buy_base(None, 1.0) == (0.0, 0.0, 0.0, False)
    
    # Broken rows
    asks = [
        [],
        ["100.0"],
        ["invalid", "invalid"],
        [100.0, -1.0],
        [-100.0, 1.0],
        [100.0, 5.0],
    ]
    spent, vwap, bought, complete = vwap_buy_base(asks, 2.0)
    assert complete is True
    assert bought == 2.0
    assert spent == 200.0
    assert vwap == 100.0

def test_vwap_sell_edge_cases():
    bids = [
        [],
        ["100.0"],
        ["invalid", "invalid"],
        [100.0, -1.0],
        [-100.0, 1.0],
        [100.0, 5.0],
    ]
    recv, vwap, sold, complete = vwap_sell_base(bids, 2.0)
    assert complete is True
    assert sold == 2.0
    assert recv == 200.0
    assert vwap == 100.0
    
def test_immediate_limit_fills_edge_cases():
    asks = [
        ["invalid", "invalid"],
        [100.0, 10.0]
    ]
    filled, spent, avg = immediate_limit_buy_fill(100.0, 5.0, asks)
    assert filled == 5.0
    assert spent == 500.0
    assert avg == 100.0
