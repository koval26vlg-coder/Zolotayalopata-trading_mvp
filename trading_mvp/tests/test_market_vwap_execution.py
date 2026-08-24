import pytest

from trading_mvp.src.orderbook_engine import OrderBookSnapshot
from trading_mvp.src.orderbook_paper_execution import (
    SimulatedOrderBookExecutor,
)

def test_market_order_vwap_execution():
    executor = SimulatedOrderBookExecutor()
    
    book1 = OrderBookSnapshot(
        exchange_id="test",
        symbol="BTC/USDT",
        best_bid=100.0,
        best_ask=102.0,
        bids=((100.0, 5.0), (99.0, 5.0), (95.0, 5.0)),
        asks=((102.0, 5.0), (105.0, 5.0), (110.0, 5.0))
    )
    
    # MARKET BUY: Sweeps the asks
    # We want to buy 8.0 base. 
    # 5.0 from 102.0 = 510.0 quote
    # 3.0 from 105.0 = 315.0 quote
    # Total quote spent = 825.0
    # VWAP = 825.0 / 8.0 = 103.125
    order_buy = executor.submit_order(
        exchange_id="test",
        symbol="BTC/USDT",
        side="buy",
        amount_base=8.0,
        order_type="market",
        current_book=book1
    )
    assert order_buy.status == "filled"
    assert order_buy.filled_base == 8.0
    assert order_buy.cum_quote == 825.0
    # Market orders are always takers
    assert order_buy.fee_quote == 825.0 * (5.5 / 10000.0)

    # MARKET SELL: Sweeps the bids
    # We want to sell 12.0 base.
    # 5.0 from 100.0 = 500.0 quote
    # 5.0 from 99.0 = 495.0 quote
    # 2.0 from 95.0 = 190.0 quote
    # Total quote recv = 1185.0
    order_sell = executor.submit_order(
        exchange_id="test",
        symbol="BTC/USDT",
        side="sell",
        amount_base=12.0,
        order_type="market",
        current_book=book1
    )
    assert order_sell.status == "filled"
    assert order_sell.filled_base == 12.0
    assert order_sell.cum_quote == 1185.0
    assert order_sell.fee_quote == 1185.0 * (5.5 / 10000.0)

    # MARKET BUY: Exceeds the orderbook depth
    # Total depth is 15.0 base. We try to buy 20.0 base.
    # It should fill 15.0 and cancel the rest!
    order_huge = executor.submit_order(
        exchange_id="test",
        symbol="BTC/USDT",
        side="buy",
        amount_base=20.0,
        order_type="market",
        current_book=book1
    )
    assert order_huge.status == "filled" # IOC style cancellation turns remainder status to filled if > 0
    assert order_huge.filled_base == 15.0
    
