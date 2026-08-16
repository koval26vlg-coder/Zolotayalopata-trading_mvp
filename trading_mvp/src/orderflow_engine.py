"""Order-flow analytics: sliding-window trade tape & L2 book depth pressure.

Ported and enhanced from Ekskavator for ZolotyayLopata trading_mvp research & proof pipeline.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from trading_mvp.src.orderbook_engine import Quote


@dataclass(frozen=True)
class TapeWindowStats:
    """Aggregated buy/sell volume over a sliding monotonic time window."""

    buy_quote: float
    sell_quote: float
    t_span_sec: float

    @property
    def total(self) -> float:
        return self.buy_quote + self.sell_quote

    @property
    def buy_share(self) -> float:
        t = self.total
        if t <= 0:
            return 0.5
        return self.buy_quote / t


class OrderflowTapeStore:
    """Thread-safe ring buffer for trade stream with sliding time window."""

    def __init__(self, window_seconds: float = 3.0, max_events: int = 1000) -> None:
        self._window = max(0.05, float(window_seconds))
        self._max = max(16, int(max_events))
        self._lock = threading.Lock()
        self._deques: dict[tuple[str, str], deque[tuple[float, str, float]]] = defaultdict(deque)

    def push(
        self,
        exchange_id: str,
        symbol: str,
        trade: dict[str, Any],
        timestamp_mono: float | None = None,
    ) -> None:
        """Record trade event: trade format with side ('buy'/'sell'), price, amount."""
        side = str(trade.get("side") or "").strip().lower()
        if side not in ("buy", "sell"):
            return
        try:
            amount = float(trade.get("amount") or 0.0)
            price = float(trade.get("price") or 0.0)
        except (TypeError, ValueError):
            return
        if amount <= 0 or price <= 0:
            return
        cost = trade.get("cost")
        try:
            quote_vol = float(cost) if cost is not None else amount * price
        except (TypeError, ValueError):
            quote_vol = amount * price
        if quote_vol <= 0:
            return

        key = (exchange_id, symbol)
        now = timestamp_mono if timestamp_mono is not None else time.monotonic()
        with self._lock:
            dq = self._deques[key]
            dq.append((now, side, quote_vol))
            while len(dq) > self._max:
                dq.popleft()

    def window_stats(
        self,
        exchange_id: str,
        symbol: str,
        now_mono: float | None = None,
    ) -> TapeWindowStats | None:
        """Calculate buy/sell aggregated stats within window."""
        now = now_mono if now_mono is not None else time.monotonic()
        t0 = now - self._window
        with self._lock:
            dq = self._deques.get((exchange_id, symbol))
            if not dq:
                return None
            buy = 0.0
            sell = 0.0
            oldest: float | None = None
            for ts, side, qv in dq:
                if ts < t0:
                    continue
                if oldest is None:
                    oldest = ts
                if side == "buy":
                    buy += qv
                else:
                    sell += qv
        if oldest is None:
            return None
        span = max(0.0, now - oldest)
        return TapeWindowStats(buy_quote=buy, sell_quote=sell, t_span_sec=span)


def depth_pressure(
    order_book: dict[str, Any] | None,
    levels: int = 5,
) -> tuple[float, float] | None:
    """Calculate (bid_notional, ask_notional) across top-N orderbook depth levels."""
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
    return bq, aq


@dataclass
class OrderflowSignal:
    """Orderflow / microstructural imbalance signal."""

    side: Literal["buy", "sell"]
    detail: str
    impulse_bps: float


@dataclass
class OrderflowConfig:
    """Settings for order-flow and depth imbalance evaluation."""

    max_spread_bps: float = 15.0
    cooldown_seconds: float = 2.0
    tape_min_total_quote: float = 1000.0
    tape_long_share: float = 0.70
    tape_short_share: float = 0.30
    book_levels: int = 5
    book_min_side_quote: float = 500.0
    book_ratio_long: float = 1.8
    book_ratio_short: float = 0.55
    signal_mode: Literal["both", "either"] = "both"


class OrderflowSignalEvaluator:
    """Evaluates microstructural order flow signals by fusing tape store and book pressure."""

    def __init__(
        self,
        config: OrderflowConfig | None = None,
        tape_store: OrderflowTapeStore | None = None,
    ) -> None:
        self.config = config or OrderflowConfig()
        self.tape_store = tape_store
        self._last_signal_mono: dict[tuple[str, str], float] = {}

    def _tape_leg_long(self, st: TapeWindowStats | None) -> tuple[bool, str]:
        cfg = self.config
        if st is None or st.total + 1e-12 < cfg.tape_min_total_quote:
            return False, "tape_insufficient"
        sh = st.buy_share
        if sh >= cfg.tape_long_share:
            return True, f"tape_buy_{sh*100:.0f}%"
        return False, f"tape_buy_{sh*100:.0f}%"

    def _tape_leg_short(self, st: TapeWindowStats | None) -> tuple[bool, str]:
        cfg = self.config
        if st is None or st.total + 1e-12 < cfg.tape_min_total_quote:
            return False, "tape_insufficient"
        sh = st.buy_share
        if sh <= cfg.tape_short_share:
            return True, f"tape_buy_{sh*100:.0f}%"
        return False, f"tape_buy_{sh*100:.0f}%"

    def _book_leg_long(self, ob: dict[str, Any] | None) -> tuple[bool, str]:
        cfg = self.config
        pr = depth_pressure(ob, cfg.book_levels)
        if pr is None:
            return False, "book_empty"
        bq, aq = pr
        if bq < cfg.book_min_side_quote or aq < cfg.book_min_side_quote:
            return False, f"book_thin_{bq:.0f}_{aq:.0f}"
        ratio = bq / aq
        if ratio >= cfg.book_ratio_long:
            return True, f"bid_ask_ratio_{ratio:.2f}x"
        return False, f"bid_ask_ratio_{ratio:.2f}x"

    def _book_leg_short(self, ob: dict[str, Any] | None) -> tuple[bool, str]:
        cfg = self.config
        pr = depth_pressure(ob, cfg.book_levels)
        if pr is None:
            return False, "book_empty"
        bq, aq = pr
        if bq < cfg.book_min_side_quote or aq < cfg.book_min_side_quote:
            return False, f"book_thin_{bq:.0f}_{aq:.0f}"
        ratio = bq / aq
        if ratio <= cfg.book_ratio_short:
            return True, f"bid_ask_ratio_{ratio:.2f}x"
        return False, f"bid_ask_ratio_{ratio:.2f}x"

    def _combine(self, tape_ok: bool, book_ok: bool) -> bool:
        if self.config.signal_mode == "either":
            return tape_ok or book_ok
        return tape_ok and book_ok

    def _impulse_bps(
        self,
        side: Literal["buy", "sell"],
        st: TapeWindowStats | None,
        ob: dict[str, Any] | None,
    ) -> float:
        dev = 0.0
        if st is not None and st.total > 0:
            dev = abs(st.buy_share - 0.5) * 2.0
        br_excess = 0.0
        pr = depth_pressure(ob, self.config.book_levels)
        if pr is not None:
            bq, aq = pr
            r = bq / aq
            if side == "buy":
                br_excess = max(0.0, min(2.0, r - 1.0)) / 2.0
            else:
                br_excess = max(0.0, min(2.0, 1.0 / max(r, 1e-12) - 1.0)) / 2.0
        raw = 6.0 + dev * 28.0 + br_excess * 22.0
        return max(5.0, min(55.0, raw))

    def evaluate_quote(
        self,
        quote: Quote,
        order_book: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> OrderflowSignal | None:
        """Evaluate incoming quote and depth for orderflow trigger."""
        cfg = self.config
        if quote.spread_bps > cfg.max_spread_bps:
            return None

        key = (quote.exchange_id, quote.symbol)
        now = now_mono if now_mono is not None else time.monotonic()
        if cfg.cooldown_seconds > 0:
            last = self._last_signal_mono.get(key, 0.0)
            if now - last < cfg.cooldown_seconds:
                return None

        st = self.tape_store.window_stats(quote.exchange_id, quote.symbol, now_mono=now) if self.tape_store else None

        t_long, t_long_d = self._tape_leg_long(st)
        t_short, t_short_d = self._tape_leg_short(st)
        b_long, b_long_d = self._book_leg_long(order_book)
        b_short, b_short_d = self._book_leg_short(order_book)

        long_ok = self._combine(t_long, b_long)
        short_ok = self._combine(t_short, b_short)

        if long_ok and short_ok:
            return None
        if long_ok:
            self._last_signal_mono[key] = now
            return OrderflowSignal(
                side="buy",
                detail=f"orderflow LONG: {t_long_d} | {b_long_d}",
                impulse_bps=self._impulse_bps("buy", st, order_book),
            )
        if short_ok:
            self._last_signal_mono[key] = now
            return OrderflowSignal(
                side="sell",
                detail=f"orderflow SHORT: {t_short_d} | {b_short_d}",
                impulse_bps=self._impulse_bps("sell", st, order_book),
            )
        return None
