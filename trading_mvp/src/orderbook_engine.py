"""Order book depth processing, VWAP calculations, and liquidity analytics.

Ported and enhanced from Ekskavator for ZolotyayLopata trading_mvp research & proof pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class Quote:
    """Best bid and ask quote for an exchange symbol."""

    exchange_id: str
    symbol: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        if self.mid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.mid * 10_000.0


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Top-of-book and bounded L2 depth snapshot."""

    exchange_id: str
    symbol: str
    best_bid: float
    best_ask: float
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float:
        if self.mid <= 0:
            return float("inf")
        return (self.best_ask - self.best_bid) / self.mid * 10_000.0


def _levels(raw: Sequence[Sequence[Any]] | None, max_levels: int) -> tuple[tuple[float, float], ...]:
    if not raw:
        return ()
    out: list[tuple[float, float]] = []
    for row in raw[:max_levels]:
        if len(row) < 2:
            continue
        try:
            p = float(row[0])
            q = float(row[1])
            if p > 0 and q > 0:
                out.append((p, q))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def quote_from_order_book(exchange_id: str, symbol: str, ob: dict[str, Any]) -> Quote | None:
    """Extract Quote (best bid / best ask) from a raw order book dictionary."""
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    if not bids or not asks:
        return None
    try:
        bid = float(bids[0][0])
        ask = float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return Quote(exchange_id=exchange_id, symbol=symbol, bid=bid, ask=ask)


def snapshot_from_order_book(
    exchange_id: str,
    symbol: str,
    ob: dict[str, Any],
    depth_levels: int = 20,
) -> OrderBookSnapshot | None:
    """Build immutable OrderBookSnapshot with depth up to depth_levels."""
    q = quote_from_order_book(exchange_id, symbol, ob)
    if q is None:
        return None
    bids = _levels(ob.get("bids"), depth_levels)
    asks = _levels(ob.get("asks"), depth_levels)
    return OrderBookSnapshot(
        exchange_id=exchange_id,
        symbol=symbol,
        best_bid=q.bid,
        best_ask=q.ask,
        bids=bids,
        asks=asks,
    )


def spread_bps(bid: float, ask: float) -> float:
    """Calculate spread in basis points (1 bp = 0.01%)."""
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return float("inf")
    return (ask - bid) / mid * 10_000.0


def symmetric_liquidity_quote(order_book: dict[str, Any] | None, levels: int = 10) -> float | None:
    """Calculate min(bid_notional, ask_notional) across top-N depth levels."""
    if not order_book:
        return None
    bids = order_book.get("bids") or []
    asks = order_book.get("asks") or []
    if not bids or not asks:
        return None
    n = max(1, int(levels))
    bq = 0.0
    aq = 0.0
    for row in bids[:n]:
        if len(row) >= 2:
            try:
                bq += float(row[0]) * float(row[1])
            except (TypeError, ValueError):
                continue
    for row in asks[:n]:
        if len(row) >= 2:
            try:
                aq += float(row[0]) * float(row[1])
            except (TypeError, ValueError):
                continue
    if bq <= 0 or aq <= 0:
        return None
    return min(bq, aq)


def vwap_buy_with_quote(
    asks: Sequence[Sequence[Any]] | None,
    quote_budget: float,
) -> tuple[float, float, float, bool]:
    """Simulate market/taker buy with quote budget: (total_base, vwap, spent_quote, complete)."""
    if not asks or quote_budget <= 0:
        return 0.0, 0.0, 0.0, False
    remaining = float(quote_budget)
    total_base = 0.0
    spent = 0.0
    for row in asks:
        if remaining <= 0:
            break
        if len(row) < 2:
            continue
        try:
            price = float(row[0])
            qty = float(row[1])
        except (TypeError, ValueError):
            continue
        if price <= 0 or qty <= 0:
            continue
        max_spend = qty * price
        take_spend = min(remaining, max_spend)
        take_base = take_spend / price
        total_base += take_base
        spent += take_spend
        remaining -= take_spend
    if total_base <= 0:
        return 0.0, 0.0, 0.0, False
    complete = remaining <= max(1e-9, quote_budget * 1e-12)
    vwap = spent / total_base
    return total_base, vwap, spent, complete


def vwap_buy_base(
    asks: Sequence[Sequence[Any]] | None,
    base_amount: float,
) -> tuple[float, float, float, bool]:
    """Simulate market/taker buy for target base amount: (spent_quote, vwap, bought_base, complete)."""
    if not asks or base_amount <= 0:
        return 0.0, 0.0, 0.0, False
    remaining = float(base_amount)
    spent = 0.0
    bought = 0.0
    for row in asks:
        if remaining <= 0:
            break
        if len(row) < 2:
            continue
        try:
            price = float(row[0])
            qty = float(row[1])
        except (TypeError, ValueError):
            continue
        if price <= 0 or qty <= 0:
            continue
        take_base = min(remaining, qty)
        spent += take_base * price
        bought += take_base
        remaining -= take_base
    if bought <= 0:
        return 0.0, 0.0, 0.0, False
    complete = remaining <= max(1e-12, base_amount * 1e-12)
    vwap = spent / bought
    return spent, vwap, bought, complete


def vwap_sell_base(
    bids: Sequence[Sequence[Any]] | None,
    base_amount: float,
) -> tuple[float, float, float, bool]:
    """Simulate market/taker sell for target base amount: (received_quote, vwap, sold_base, complete)."""
    if not bids or base_amount <= 0:
        return 0.0, 0.0, 0.0, False
    remaining = float(base_amount)
    total_quote = 0.0
    sold_base = 0.0
    for row in bids:
        if remaining <= 0:
            break
        if len(row) < 2:
            continue
        try:
            price = float(row[0])
            qty = float(row[1])
        except (TypeError, ValueError):
            continue
        if price <= 0 or qty <= 0:
            continue
        take_base = min(remaining, qty)
        total_quote += take_base * price
        sold_base += take_base
        remaining -= take_base
    if sold_base <= 0:
        return 0.0, 0.0, 0.0, False
    complete = remaining <= max(1e-12, base_amount * 1e-12)
    vwap = total_quote / sold_base
    return total_quote, vwap, sold_base, complete


def simulated_slippage_bps_buy(best_ask: float, vwap: float, mid: float) -> float:
    """Calculate buyer slippage relative to best ask (in bps of mid)."""
    if mid <= 0 or best_ask <= 0:
        return float("inf")
    return max(0.0, (vwap - best_ask) / mid * 10_000.0)


def simulated_slippage_bps_sell(best_bid: float, vwap: float, mid: float) -> float:
    """Calculate seller slippage relative to best bid (in bps of mid)."""
    if mid <= 0 or best_bid <= 0:
        return float("inf")
    return max(0.0, (best_bid - vwap) / mid * 10_000.0)


def immediate_limit_buy_fill(
    limit_price: float,
    amount_base: float,
    asks: Sequence[Sequence[Any]] | None,
) -> tuple[float, float, float]:
    """Simulate IOC limit buy matching against asks <= limit_price.
    
    Returns: (filled_base, spent_quote, avg_price).
    """
    if not asks or amount_base <= 0 or limit_price <= 0:
        return 0.0, 0.0, 0.0
    rem = float(amount_base)
    spent = 0.0
    filled = 0.0
    for row in asks:
        if rem <= 1e-18:
            break
        if len(row) < 2:
            continue
        try:
            p = float(row[0])
            q = float(row[1])
        except (TypeError, ValueError):
            continue
        if p <= 0 or q <= 0:
            continue
        if p > limit_price + 1e-12:
            break
        take = min(rem, q)
        filled += take
        spent += take * p
        rem -= take
    avg = spent / filled if filled > 0 else 0.0
    return filled, spent, avg


def immediate_limit_sell_fill(
    limit_price: float,
    amount_base: float,
    bids: Sequence[Sequence[Any]] | None,
) -> tuple[float, float, float]:
    """Simulate IOC limit sell matching against bids >= limit_price.
    
    Returns: (filled_base, received_quote, avg_price).
    """
    if not bids or amount_base <= 0 or limit_price <= 0:
        return 0.0, 0.0, 0.0
    rem = float(amount_base)
    recv = 0.0
    filled = 0.0
    for row in bids:
        if rem <= 1e-18:
            break
        if len(row) < 2:
            continue
        try:
            p = float(row[0])
            q = float(row[1])
        except (TypeError, ValueError):
            continue
        if p <= 0 or q <= 0:
            continue
        if p < limit_price - 1e-12:
            break
        take = min(rem, q)
        filled += take
        recv += take * p
        rem -= take
    avg = recv / filled if filled > 0 else 0.0
    return filled, recv, avg
