import pytest

from trading_mvp.src.orderbook_engine import OrderBookSnapshot
from trading_mvp.src.orderbook_paper_execution import (
    PaperExecutionAnalytics,
    PaperOrder,
    SimulatedOrderBookExecutor,
)

def test_maker_vs_taker_fees():
    executor = SimulatedOrderBookExecutor()
    
    book1 = OrderBookSnapshot(
        exchange_id="test",
        symbol="BTC/USDT",
        best_bid=100.0,
        best_ask=102.0,
        bids=((100.0, 10.0),),
        asks=((102.0, 10.0),)
    )
    
    # TAKER BUY: limit_price >= best_ask
    order_taker = executor.submit_order(
        exchange_id="test",
        symbol="BTC/USDT",
        side="buy",
        limit_price=105.0,
        amount_base=5.0,
        current_book=book1
    )
    # 5.0 * 102.0 = 510.0 quote spent.
    # taker fee is 5.5 bps by default.
    assert order_taker.fee_quote == 510.0 * (5.5 / 10000.0)
    assert order_taker.status == "filled"

    # MAKER BUY: limit_price < best_ask. Gets placed in the book.
    order_maker = executor.submit_order(
        exchange_id="test",
        symbol="BTC/USDT",
        side="buy",
        limit_price=101.0,
        amount_base=5.0,
        current_book=book1
    )
    assert order_maker.status == "open"
    assert order_maker.fee_quote == 0.0

    # Book updates such that ask crosses our maker bid
    book2 = OrderBookSnapshot(
        exchange_id="test",
        symbol="BTC/USDT",
        best_bid=99.0,
        best_ask=100.0,
        bids=((99.0, 10.0),),
        asks=((100.0, 10.0),) # ask dropped to 100, which is <= 101.
    )
    affected = executor.on_order_book_update(book2)
    
    assert len(affected) == 1
    assert affected[0].order_id == order_maker.order_id
    assert order_maker.status == "filled"
    # It filled 5.0 against the new book's ask of 100.0. Spent = 500.0.
    # Maker fee is 2.0 bps by default.
    assert order_maker.fee_quote == 500.0 * (2.0 / 10000.0)

