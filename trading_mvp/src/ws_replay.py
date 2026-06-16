from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import RiskConfig, StrategyConfig


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_ts(event: dict[str, Any]) -> float:
    value = _as_float(event.get("exchange_ts")) or _as_float(event.get("recv_ts"))
    if value is None:
        raise ValueError("event has no exchange_ts/recv_ts")
    return value


def _market_key(event: dict[str, Any]) -> str:
    return f"{event.get('exchange')}:{event.get('symbol')}"


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 1e4


@dataclass(frozen=True)
class ReplayConfig:
    notional_quote: float = 25.0
    execution_mode: str = "taker"
    taker_fee_bps: float = 10.0
    maker_fee_bps: float = 0.0
    slippage_bps: float = 1.0
    latency_ms: int = 250
    flow_window_sec: float = 5.0
    allow_short: bool = False
    max_open_positions: int = 1
    maker_queue_ahead_qty: float = 0.0
    maker_queue_model: str = "fixed"
    maker_queue_ahead_fraction: float = 1.0
    maker_order_ttl_sec: float = 5.0
    quality_filter_enabled: bool = False
    quality_window_sec: float = 60.0
    quality_min_trade_count: int = 0
    quality_min_trade_notional: float = 0.0
    quality_max_avg_spread_bps: float = 0.0
    quality_min_quote_updates: int = 0
    quality_min_top_qty: float = 0.0
    min_net_take_profit_bps: float = -1e9


@dataclass
class ReplayPosition:
    exchange: str
    symbol: str
    side: int
    qty: float
    entry_price: float
    entry_ts: float
    entry_fee_quote: float
    entry_notional_quote: float


@dataclass
class PendingOrder:
    market: str
    action: str
    side: int
    requested_ts: float
    execute_after_ts: float
    reason: str
    limit_price: float | None = None
    qty: float | None = None
    placed_ts: float | None = None
    queue_remaining_qty: float = 0.0


@dataclass
class ReplayTrade:
    exchange: str
    symbol: str
    side: str
    entry_ts: float
    exit_ts: float
    hold_sec: float
    qty: float
    entry_price: float
    exit_price: float
    entry_fee_quote: float
    exit_fee_quote: float
    gross_pnl_quote: float
    net_pnl_quote: float
    pnl_bps: float
    exit_reason: str


class MarketState:
    def __init__(self, exchange: str, symbol: str) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.bid: float | None = None
        self.ask: float | None = None
        self.bid_qty: float | None = None
        self.ask_qty: float | None = None
        self.last_ts: float | None = None
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.signed_flow: deque[tuple[float, float]] = deque()
        self.trade_flow: deque[tuple[float, float]] = deque()
        self.spread_samples: deque[tuple[float, float]] = deque()
        self.bbo_history: deque[tuple[float, float, float, float, float]] = deque()
        self.trade_events: deque[tuple[float, str, float, float]] = deque()
        # Отдельная история (ts, bid, ask) для расчета экстремумов окна пробоя:
        # не пересекается с прунингом bbo_history внутри recent_sweep_candidate.
        self.breakout_history: deque[tuple[float, float, float]] = deque()

    def update(self, event: dict[str, Any]) -> None:
        kind = event.get("event_kind")
        ts = _event_ts(event)
        self.last_ts = ts
        if kind == "bbo":
            self.bid = _as_float(event.get("bid_price"))
            self.ask = _as_float(event.get("ask_price"))
            self.bid_qty = _as_float(event.get("bid_qty"))
            self.ask_qty = _as_float(event.get("ask_qty"))
            self._record_bbo_sample(ts)
            self._record_spread_sample(ts)
            return
        if kind == "depth":
            self._apply_depth(event)
            self._record_bbo_sample(ts)
            self._record_spread_sample(ts)
            return
        if kind == "trade":
            self._apply_trade(event, ts)

    def _apply_depth(self, event: dict[str, Any]) -> None:
        depth_type = event.get("depth_type")
        bids = [[_as_float(price), _as_float(qty)] for price, qty in event.get("bids", [])]
        asks = [[_as_float(price), _as_float(qty)] for price, qty in event.get("asks", [])]
        if depth_type == "snapshot":
            self.bids = {price: qty for price, qty in bids if price is not None and qty is not None and qty > 0}
            self.asks = {price: qty for price, qty in asks if price is not None and qty is not None and qty > 0}
        else:
            self._apply_delta(self.bids, bids)
            self._apply_delta(self.asks, asks)
        if self.bid is None or self.ask is None:
            self._infer_bbo_from_book()

    def _apply_delta(self, book: dict[float, float], levels: list[list[float | None]]) -> None:
        for price, qty in levels:
            if price is None or qty is None:
                continue
            if qty <= 0:
                book.pop(price, None)
            else:
                book[price] = qty

    def _infer_bbo_from_book(self) -> None:
        if self.bids:
            bid = max(self.bids)
            self.bid = bid
            self.bid_qty = self.bids[bid]
        if self.asks:
            ask = min(self.asks)
            self.ask = ask
            self.ask_qty = self.asks[ask]

    def _apply_trade(self, event: dict[str, Any], ts: float) -> None:
        price = _as_float(event.get("price"))
        qty = _as_float(event.get("qty"))
        if price is None or qty is None:
            return
        side = str(event.get("side") or "").lower()
        sign = 1.0 if side == "buy" else -1.0 if side == "sell" else 0.0
        notional = price * qty
        self.signed_flow.append((ts, sign * notional))
        self.trade_flow.append((ts, abs(notional)))
        if side in {"buy", "sell"}:
            self.trade_events.append((ts, side, price, abs(notional)))

    def _record_bbo_sample(self, ts: float) -> None:
        if self.bid is None or self.ask is None:
            return
        self.bbo_history.append(
            (
                ts,
                self.bid,
                self.ask,
                self.bid_qty or 0.0,
                self.ask_qty or 0.0,
            )
        )
        self.breakout_history.append((ts, self.bid, self.ask))

    def recent_extremes(
        self,
        now_ts: float,
        window_sec: float,
        exclude_last: bool = True,
    ) -> tuple[float, float, int] | None:
        """(min_bid, max_ask, count) по окну, опционально без последней котировки.

        exclude_last нужен, чтобы сравнивать текущую котировку с предыдущим
        экстремумом окна, а не с самой собой.
        """
        while self.breakout_history and now_ts - self.breakout_history[0][0] > window_sec:
            self.breakout_history.popleft()
        samples = list(self.breakout_history)
        if exclude_last and samples:
            samples = samples[:-1]
        if not samples:
            return None
        min_bid = min(item[1] for item in samples)
        max_ask = max(item[2] for item in samples)
        return min_bid, max_ask, len(samples)

    def _record_spread_sample(self, ts: float) -> None:
        spread = self.spread_bps()
        if spread is not None:
            self.spread_samples.append((ts, spread))

    def ready(self) -> bool:
        return self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0

    def spread_bps(self) -> float | None:
        return _spread_bps(self.bid, self.ask)

    def imbalance(self) -> float:
        bid_qty = self.bid_qty or 0.0
        ask_qty = self.ask_qty or 0.0
        denom = bid_qty + ask_qty
        return (bid_qty - ask_qty) / denom if denom else 0.0

    def signed_flow_notional(self, now_ts: float, window_sec: float) -> float:
        while self.signed_flow and now_ts - self.signed_flow[0][0] > window_sec:
            self.signed_flow.popleft()
        return sum(item[1] for item in self.signed_flow)

    def trade_count(self, now_ts: float, window_sec: float) -> int:
        self._prune_trade_flow(now_ts, window_sec)
        return len(self.trade_flow)

    def abs_trade_notional(self, now_ts: float, window_sec: float) -> float:
        self._prune_trade_flow(now_ts, window_sec)
        return sum(item[1] for item in self.trade_flow)

    def quote_update_count(self, now_ts: float, window_sec: float) -> int:
        self._prune_spread_samples(now_ts, window_sec)
        return len(self.spread_samples)

    def avg_spread_bps(self, now_ts: float, window_sec: float) -> float | None:
        self._prune_spread_samples(now_ts, window_sec)
        if not self.spread_samples:
            return None
        return sum(item[1] for item in self.spread_samples) / len(self.spread_samples)

    def min_top_qty(self) -> float:
        return min(self.bid_qty or 0.0, self.ask_qty or 0.0)

    def _prune_trade_flow(self, now_ts: float, window_sec: float) -> None:
        while self.trade_flow and now_ts - self.trade_flow[0][0] > window_sec:
            self.trade_flow.popleft()

    def _prune_spread_samples(self, now_ts: float, window_sec: float) -> None:
        while self.spread_samples and now_ts - self.spread_samples[0][0] > window_sec:
            self.spread_samples.popleft()

    def recent_sweep_candidate(
        self,
        now_ts: float,
        window_sec: float,
        min_trade_notional: float,
    ) -> dict[str, Any] | None:
        self._prune_bbo_history(now_ts, window_sec)
        self._prune_trade_events(now_ts, window_sec)
        min_bid_before: float | None = None
        max_ask_before: float | None = None
        last_bid_before: float | None = None
        last_ask_before: float | None = None
        bbo_index = 0
        bbo_history = list(self.bbo_history)
        candidates: list[dict[str, Any]] = []
        for trade_ts, side, price, notional in self.trade_events:
            if notional < min_trade_notional:
                continue
            while bbo_index < len(bbo_history) and bbo_history[bbo_index][0] < trade_ts:
                _sample_ts, bid, ask, _bid_qty, _ask_qty = bbo_history[bbo_index]
                min_bid_before = bid if min_bid_before is None else min(min_bid_before, bid)
                max_ask_before = ask if max_ask_before is None else max(max_ask_before, ask)
                last_bid_before = bid
                last_ask_before = ask
                bbo_index += 1
            if min_bid_before is None or max_ask_before is None or last_bid_before is None or last_ask_before is None:
                continue
            if side == "sell":
                sweep_level = min_bid_before
                if price < sweep_level:
                    intensity_bps = (sweep_level - price) / sweep_level * 1e4 if sweep_level > 0 else 0.0
                    candidates.append(
                        {
                            "id": f"sell:{trade_ts}:{price}",
                            "side": "sell",
                            "ts": trade_ts,
                            "price": price,
                            "level": sweep_level,
                            "notional": notional,
                            "intensity_bps": intensity_bps,
                            "pre_spread_bps": _spread_bps(last_bid_before, last_ask_before),
                        }
                    )
            elif side == "buy":
                sweep_level = max_ask_before
                if price > sweep_level:
                    intensity_bps = (price - sweep_level) / sweep_level * 1e4 if sweep_level > 0 else 0.0
                    candidates.append(
                        {
                            "id": f"buy:{trade_ts}:{price}",
                            "side": "buy",
                            "ts": trade_ts,
                            "price": price,
                            "level": sweep_level,
                            "notional": notional,
                            "intensity_bps": intensity_bps,
                            "pre_spread_bps": _spread_bps(last_bid_before, last_ask_before),
                        }
                    )
        return max(candidates, key=lambda item: float(item["ts"])) if candidates else None

    def _prune_bbo_history(self, now_ts: float, window_sec: float) -> None:
        while self.bbo_history and now_ts - self.bbo_history[0][0] > window_sec:
            self.bbo_history.popleft()

    def _prune_trade_events(self, now_ts: float, window_sec: float) -> None:
        while self.trade_events and now_ts - self.trade_events[0][0] > window_sec:
            self.trade_events.popleft()


class ReplayRisk:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self.trades_opened = 0
        self.daily_realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.kill_switch = False

    def can_open(
        self,
        qty: float,
        price: float,
        open_positions: int,
        max_open_positions: int,
        market_open_positions: int = 0,
        max_open_positions_per_market: int = 1,
    ) -> tuple[bool, str]:
        if self.kill_switch:
            return False, "kill_switch_active"
        if open_positions >= max_open_positions:
            return False, "max_open_positions"
        if market_open_positions >= max_open_positions_per_market:
            return False, "max_open_positions_per_market"
        if self.trades_opened >= self.cfg.max_trades_per_day:
            return False, "max_trades_per_day"
        if qty > self.cfg.max_position_qty:
            return False, "max_position_qty"
        if qty * price > self.cfg.max_notional_per_trade:
            return False, "max_notional_per_trade"
        return True, "ok"

    def register_open(self) -> None:
        self.trades_opened += 1

    def register_close(self, net_pnl_quote: float) -> None:
        self.daily_realized_pnl += net_pnl_quote
        self._check_equity_kill_switch()

    def mark_unrealized(self, unrealized_quote: float) -> None:
        """Учет нереализованного PnL открытых позиций для kill-switch.

        Без этого дневной лимит убытка проверяется только при закрытии, и
        позиция может уйти глубоко в минус внутри сделки, не остановив торговлю.
        """
        self.unrealized_pnl = unrealized_quote
        self._check_equity_kill_switch()

    def _check_equity_kill_switch(self) -> None:
        equity = self.daily_realized_pnl + self.unrealized_pnl
        if equity <= -abs(self.cfg.daily_loss_limit_quote):
            self.kill_switch = True


class EventDrivenReplayBacktester:
    def __init__(
        self,
        strategy_cfg: StrategyConfig,
        risk_cfg: RiskConfig,
        replay_cfg: ReplayConfig,
    ) -> None:
        self.strategy_cfg = strategy_cfg
        self.risk = ReplayRisk(risk_cfg)
        self.replay_cfg = replay_cfg
        self.states: dict[str, MarketState] = {}
        self.positions: dict[str, ReplayPosition] = {}
        self.pending: dict[str, PendingOrder] = {}
        self.trades: list[ReplayTrade] = []
        self.events_by_kind: Counter[str] = Counter()
        self.events_by_exchange: Counter[str] = Counter()
        self.skipped_signals: Counter[str] = Counter()
        self.equity_curve: list[dict[str, float]] = []
        self.consumed_sweeps: set[str] = set()
        self.last_sweep_v2_signal_ts: dict[str, float] = {}

    def run(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(events, key=_event_ts)
        for event in ordered:
            self._on_event(event)
        if ordered:
            self._force_close_all(_event_ts(ordered[-1]))
        return self._result(len(ordered))

    def _state_for(self, event: dict[str, Any]) -> MarketState:
        key = _market_key(event)
        state = self.states.get(key)
        if state is None:
            state = MarketState(str(event.get("exchange")), str(event.get("symbol")))
            self.states[key] = state
        return state

    def _on_event(self, event: dict[str, Any]) -> None:
        key = _market_key(event)
        kind = str(event.get("event_kind"))
        self.events_by_kind[kind] += 1
        self.events_by_exchange[str(event.get("exchange"))] += 1
        state = self._state_for(event)
        state.update(event)
        ts = _event_ts(event)
        self._try_execute_pending(key, state, ts, event)
        if self.positions:
            self.risk.mark_unrealized(self._unrealized_pnl_quote())
        if not state.ready():
            return
        if key in self.positions and key not in self.pending:
            self._maybe_schedule_exit(key, state, ts)
        if key not in self.positions and key not in self.pending:
            self._maybe_schedule_entry(key, state, ts)

    def _try_execute_pending(self, key: str, state: MarketState, ts: float, event: dict[str, Any]) -> None:
        order = self.pending.get(key)
        if order is None or ts < order.execute_after_ts or not state.ready():
            return
        if self.replay_cfg.execution_mode == "maker" and order.reason != "force_end":
            if order.limit_price is None:
                self._place_maker_order(order, state, ts)
                return
            if self._maker_order_expired(order, ts):
                self.skipped_signals[f"maker_{order.action}_expired"] += 1
                self.pending.pop(key, None)
                return
            if self._try_fill_maker_order(order, state, ts, event):
                self.pending.pop(key, None)
            return

        if order.action == "entry":
            self._execute_taker_entry(order, state, ts)
        elif order.action == "exit":
            self._execute_taker_exit(order, state, ts)
        self.pending.pop(key, None)

    def _maybe_schedule_entry(self, key: str, state: MarketState, ts: float) -> None:
        side = self._signal(state, ts)
        if side == 0:
            return
        if side < 0 and not self.replay_cfg.allow_short:
            self.skipped_signals["short_disabled"] += 1
            return
        entry_price = self._entry_price(state, side)
        if entry_price is None:
            return
        qty = self.replay_cfg.notional_quote / entry_price
        ok, reason = self.risk.can_open(
            qty=qty,
            price=entry_price,
            open_positions=len(self.positions),
            max_open_positions=self.replay_cfg.max_open_positions,
            market_open_positions=1 if key in self.positions else 0,
            max_open_positions_per_market=self.risk.cfg.max_open_positions_per_market,
        )
        if not ok:
            self.skipped_signals[reason] += 1
            return
        self.pending[key] = PendingOrder(
            market=key,
            action="entry",
            side=side,
            requested_ts=ts,
            execute_after_ts=ts + self.replay_cfg.latency_ms / 1000.0,
            reason="signal",
        )
        if self.replay_cfg.execution_mode == "maker" and self.pending[key].execute_after_ts <= ts:
            self._place_maker_order(self.pending[key], state, ts)

    def _maybe_schedule_exit(self, key: str, state: MarketState, ts: float) -> None:
        position = self.positions[key]
        exit_price = self._exit_price(state, position.side)
        if exit_price is None:
            return
        pnl_bps = self._pnl_bps(position, exit_price)
        hold_sec = ts - position.entry_ts
        reason = ""
        if pnl_bps >= self.strategy_cfg.take_profit_bps:
            reason = "take_profit"
        elif pnl_bps <= -abs(self.strategy_cfg.stop_loss_bps):
            reason = "stop_loss"
        elif hold_sec >= self.strategy_cfg.max_hold_sec:
            reason = "timeout"
        if not reason:
            return
        self.pending[key] = PendingOrder(
            market=key,
            action="exit",
            side=position.side,
            requested_ts=ts,
            execute_after_ts=ts + self.replay_cfg.latency_ms / 1000.0,
            reason=reason,
        )
        if self.replay_cfg.execution_mode == "maker" and self.pending[key].execute_after_ts <= ts:
            self._place_maker_order(self.pending[key], state, ts)

    def _signal(self, state: MarketState, ts: float) -> int:
        spread = state.spread_bps()
        if spread is None or spread > self.strategy_cfg.max_spread_bps:
            return 0
        imbalance = state.imbalance()
        flow = state.signed_flow_notional(ts, self.replay_cfg.flow_window_sec)
        signal_type = (self.strategy_cfg.signal_type or "flow_continue").strip().lower()
        if signal_type == "flow_continue":
            side = self._flow_continue_signal(imbalance, flow)
        elif signal_type == "fade_exhaustion":
            side = self._fade_exhaustion_signal(imbalance, flow)
        elif signal_type == "liquidity_sweep_reversal":
            side = self._liquidity_sweep_reversal_signal(state, ts, imbalance, flow)
        elif signal_type == "liquidity_sweep_reversal_v2":
            side = self._liquidity_sweep_reversal_v2_signal(state, ts)
        elif signal_type == "large_move_breakout":
            side = self._large_move_breakout_signal(state, ts)
        else:
            raise ValueError(f"Unknown signal_type: {self.strategy_cfg.signal_type}")
        if side == 0:
            return 0
        passed, reason = self._passes_quality_filter(state, ts)
        if not passed:
            self.skipped_signals[reason] += 1
            return 0
        if not self._passes_entry_edge_filter():
            self.skipped_signals["min_net_take_profit_bps"] += 1
            return 0
        return side

    def _flow_continue_signal(self, imbalance: float, flow: float) -> int:
        if (
            imbalance >= self.strategy_cfg.entry_imbalance_abs
            and flow >= self.strategy_cfg.entry_signed_flow_notional
        ):
            return 1
        if (
            imbalance <= -self.strategy_cfg.entry_imbalance_abs
            and flow <= -self.strategy_cfg.entry_signed_flow_notional
        ):
            return -1
        return 0

    def _fade_exhaustion_signal(self, imbalance: float, flow: float) -> int:
        if (
            imbalance >= self.strategy_cfg.entry_imbalance_abs
            and flow <= -self.strategy_cfg.entry_signed_flow_notional
        ):
            return 1
        if (
            imbalance <= -self.strategy_cfg.entry_imbalance_abs
            and flow >= self.strategy_cfg.entry_signed_flow_notional
        ):
            return -1
        return 0

    def _large_move_breakout_signal(self, state: MarketState, ts: float) -> int:
        """Momentum-пробой: вход по направлению пробоя экстремума окна с
        подтверждением signed-flow. Рассчитан на крупный TP (>> round-trip fee),
        чтобы не быть съеденным комиссиями, как scalp на 6 bps.
        """
        window = float(self.strategy_cfg.breakout_lookback_sec or 0.0)
        if window <= 0:
            return 0
        extremes = state.recent_extremes(ts, window, exclude_last=True)
        if extremes is None:
            return 0
        min_bid_prev, max_ask_prev, count = extremes
        if count < int(self.strategy_cfg.breakout_min_samples or 0):
            return 0
        flow = state.signed_flow_notional(ts, self.replay_cfg.flow_window_sec)
        min_flow = abs(self.strategy_cfg.entry_signed_flow_notional)
        bps = float(self.strategy_cfg.breakout_bps or 0.0)
        if (
            state.ask is not None
            and max_ask_prev > 0
            and state.ask >= max_ask_prev * (1.0 + bps / 1e4)
            and flow >= min_flow
        ):
            return 1
        if (
            state.bid is not None
            and min_bid_prev > 0
            and state.bid <= min_bid_prev * (1.0 - bps / 1e4)
            and flow <= -min_flow
        ):
            return -1
        return 0

    def _liquidity_sweep_reversal_signal(
        self,
        state: MarketState,
        ts: float,
        imbalance: float,
        flow: float,
    ) -> int:
        min_flow = abs(self.strategy_cfg.entry_signed_flow_notional)
        candidate = state.recent_sweep_candidate(
            now_ts=ts,
            window_sec=self.replay_cfg.flow_window_sec,
            min_trade_notional=min_flow,
        )
        if candidate is None:
            return 0
        candidate_id = str(candidate["id"])
        if candidate_id in self.consumed_sweeps:
            return 0
        level = float(candidate["level"])
        side = str(candidate["side"])
        if (
            side == "sell"
            and flow <= -min_flow
            and state.bid is not None
            and state.bid >= level
            and imbalance >= self.strategy_cfg.entry_imbalance_abs
        ):
            self.consumed_sweeps.add(candidate_id)
            return 1
        if (
            side == "buy"
            and flow >= min_flow
            and state.ask is not None
            and state.ask <= level
            and imbalance <= -self.strategy_cfg.entry_imbalance_abs
        ):
            self.consumed_sweeps.add(candidate_id)
            return -1
        return 0

    def _liquidity_sweep_reversal_v2_signal(self, state: MarketState, ts: float) -> int:
        min_notional = max(
            abs(self.strategy_cfg.entry_signed_flow_notional),
            float(self.strategy_cfg.sweep_v2_min_trade_notional_quote or 0.0),
        )
        candidate = state.recent_sweep_candidate(
            now_ts=ts,
            window_sec=self.replay_cfg.flow_window_sec,
            min_trade_notional=min_notional,
        )
        if candidate is None:
            return 0
        candidate_id = str(candidate["id"])
        if candidate_id in self.consumed_sweeps:
            return 0
        if not self._sweep_v2_market_allowed(state):
            self.skipped_signals["sweep_v2_allowed_markets"] += 1
            return 0

        sweep_side = str(candidate["side"])
        expected_side = "LONG" if sweep_side == "sell" else "SHORT"
        requested_side = (self.strategy_cfg.sweep_v2_side or "").strip().upper()
        if requested_side and requested_side != expected_side:
            self.skipped_signals["sweep_v2_side"] += 1
            return 0

        cooldown = float(self.strategy_cfg.sweep_v2_event_cooldown_sec or 0.0)
        cooldown_key = f"{state.exchange}:{state.symbol}:{expected_side}"
        last_ts = self.last_sweep_v2_signal_ts.get(cooldown_key)
        if cooldown > 0 and last_ts is not None and ts - last_ts < cooldown:
            self.skipped_signals["sweep_v2_event_cooldown_sec"] += 1
            return 0

        min_intensity = float(self.strategy_cfg.sweep_v2_min_intensity_bps or 0.0)
        if min_intensity > 0 and float(candidate.get("intensity_bps") or 0.0) < min_intensity:
            self.skipped_signals["sweep_v2_min_intensity_bps"] += 1
            return 0

        max_pre_spread = float(self.strategy_cfg.sweep_v2_max_pre_spread_bps or 0.0)
        pre_spread = _as_float(candidate.get("pre_spread_bps"))
        if max_pre_spread > 0 and (pre_spread is None or pre_spread > max_pre_spread):
            self.skipped_signals["sweep_v2_max_pre_spread_bps"] += 1
            return 0

        max_reclaim_sec = float(self.strategy_cfg.sweep_v2_max_reclaim_sec or 0.0)
        if max_reclaim_sec > 0 and ts - float(candidate["ts"]) > max_reclaim_sec:
            self.skipped_signals["sweep_v2_max_reclaim_sec"] += 1
            return 0

        level = float(candidate["level"])
        if sweep_side == "sell" and state.bid is not None and state.bid >= level:
            self.consumed_sweeps.add(candidate_id)
            self.last_sweep_v2_signal_ts[cooldown_key] = ts
            return 1
        if sweep_side == "buy" and state.ask is not None and state.ask <= level:
            self.consumed_sweeps.add(candidate_id)
            self.last_sweep_v2_signal_ts[cooldown_key] = ts
            return -1
        return 0

    def _sweep_v2_market_allowed(self, state: MarketState) -> bool:
        raw = (self.strategy_cfg.sweep_v2_allowed_markets or "").strip()
        if not raw:
            return True
        allowed = {item.strip().lower() for item in raw.split(",") if item.strip()}
        market = f"{state.exchange}:{state.symbol}".lower()
        symbol = str(state.symbol).lower()
        return market in allowed or symbol in allowed

    def _passes_entry_edge_filter(self) -> bool:
        # Эффективный порог = строжайший из replay-флага и risk-уровня (config.json).
        # CLI может только ужесточить cost-gate, но не отключить заданный в risk.
        risk_floor = getattr(self.risk.cfg, "min_net_take_profit_bps", -1e9)
        min_edge = max(self.replay_cfg.min_net_take_profit_bps, risk_floor)
        if min_edge <= -1e8:
            return True
        return self._net_take_profit_bps() >= min_edge

    def _net_take_profit_bps(self) -> float:
        return float(self.strategy_cfg.take_profit_bps) - self._round_trip_fee_bps()

    def _round_trip_fee_bps(self) -> float:
        if self.replay_cfg.execution_mode == "maker":
            return 2.0 * self.replay_cfg.maker_fee_bps
        return 2.0 * self.replay_cfg.taker_fee_bps

    def _passes_quality_filter(self, state: MarketState, ts: float) -> tuple[bool, str]:
        cfg = self.replay_cfg
        if not cfg.quality_filter_enabled:
            return True, "ok"
        window = max(0.001, cfg.quality_window_sec)
        if cfg.quality_min_trade_count > 0 and state.trade_count(ts, window) < cfg.quality_min_trade_count:
            return False, "quality_min_trade_count"
        if (
            cfg.quality_min_trade_notional > 0
            and state.abs_trade_notional(ts, window) < cfg.quality_min_trade_notional
        ):
            return False, "quality_min_trade_notional"
        if (
            cfg.quality_min_quote_updates > 0
            and state.quote_update_count(ts, window) < cfg.quality_min_quote_updates
        ):
            return False, "quality_min_quote_updates"
        if cfg.quality_min_top_qty > 0 and state.min_top_qty() < cfg.quality_min_top_qty:
            return False, "quality_min_top_qty"
        if cfg.quality_max_avg_spread_bps > 0:
            avg_spread = state.avg_spread_bps(ts, window)
            if avg_spread is None or avg_spread > cfg.quality_max_avg_spread_bps:
                return False, "quality_max_avg_spread_bps"
        return True, "ok"

    def _entry_price(self, state: MarketState, side: int) -> float | None:
        if side > 0 and state.ask is not None:
            return state.ask * (1.0 + self.replay_cfg.slippage_bps / 1e4)
        if side < 0 and state.bid is not None:
            return state.bid * (1.0 - self.replay_cfg.slippage_bps / 1e4)
        return None

    def _exit_price(self, state: MarketState, side: int) -> float | None:
        if side > 0 and state.bid is not None:
            return state.bid * (1.0 - self.replay_cfg.slippage_bps / 1e4)
        if side < 0 and state.ask is not None:
            return state.ask * (1.0 + self.replay_cfg.slippage_bps / 1e4)
        return None

    def _passive_price(self, state: MarketState, order_direction: int) -> float | None:
        if order_direction > 0:
            return state.bid
        return state.ask

    def _order_direction(self, order: PendingOrder) -> int:
        if order.action == "entry":
            return order.side
        return -order.side

    def _fee(self, notional: float, fee_bps: float) -> float:
        return abs(notional) * fee_bps / 1e4

    def _taker_fee(self, notional: float) -> float:
        return self._fee(notional, self.replay_cfg.taker_fee_bps)

    def _maker_fee(self, notional: float) -> float:
        return self._fee(notional, self.replay_cfg.maker_fee_bps)

    def _execute_taker_entry(self, order: PendingOrder, state: MarketState, ts: float) -> None:
        price = self._entry_price(state, order.side)
        if price is None:
            return
        qty = self.replay_cfg.notional_quote / price
        ok, reason = self.risk.can_open(
            qty=qty,
            price=price,
            open_positions=len(self.positions),
            max_open_positions=self.replay_cfg.max_open_positions,
            market_open_positions=1 if order.market in self.positions else 0,
            max_open_positions_per_market=self.risk.cfg.max_open_positions_per_market,
        )
        if not ok:
            self.skipped_signals[reason] += 1
            return
        notional = qty * price
        self.positions[order.market] = ReplayPosition(
            exchange=state.exchange,
            symbol=state.symbol,
            side=order.side,
            qty=qty,
            entry_price=price,
            entry_ts=ts,
            entry_fee_quote=self._taker_fee(notional),
            entry_notional_quote=notional,
        )
        self.risk.register_open()

    def _execute_taker_exit(self, order: PendingOrder, state: MarketState, ts: float) -> None:
        position = self.positions.get(order.market)
        if position is None:
            return
        price = self._exit_price(state, position.side)
        if price is None:
            return
        gross = (price - position.entry_price) * position.qty * position.side
        exit_notional = position.qty * price
        exit_fee = self._taker_fee(exit_notional)
        self._record_close(order, position, ts, price, gross, exit_fee)

    def _place_maker_order(self, order: PendingOrder, state: MarketState, ts: float) -> None:
        direction = self._order_direction(order)
        price = self._passive_price(state, direction)
        if price is None or price <= 0:
            return
        qty = self.replay_cfg.notional_quote / price
        if order.action == "exit":
            position = self.positions.get(order.market)
            if position is None:
                return
            qty = position.qty
        order.limit_price = price
        order.qty = qty
        order.placed_ts = ts
        order.queue_remaining_qty = self._maker_queue_ahead_qty(state, direction)

    def _maker_queue_ahead_qty(self, state: MarketState, direction: int) -> float:
        fixed = max(0.0, self.replay_cfg.maker_queue_ahead_qty)
        if self.replay_cfg.maker_queue_model == "fixed":
            return fixed
        if self.replay_cfg.maker_queue_model != "top_qty_fraction":
            raise ValueError(f"Unknown maker_queue_model: {self.replay_cfg.maker_queue_model}")
        top_qty = state.bid_qty if direction > 0 else state.ask_qty
        visible = max(0.0, top_qty or 0.0) * max(0.0, self.replay_cfg.maker_queue_ahead_fraction)
        return fixed + visible

    def _maker_order_expired(self, order: PendingOrder, ts: float) -> bool:
        if order.placed_ts is None:
            return False
        return ts - order.placed_ts >= self.replay_cfg.maker_order_ttl_sec

    def _try_fill_maker_order(
        self,
        order: PendingOrder,
        state: MarketState,
        ts: float,
        event: dict[str, Any],
    ) -> bool:
        if event.get("event_kind") != "trade" or order.limit_price is None or order.qty is None:
            return False
        if order.placed_ts is not None and ts <= order.placed_ts:
            return False
        trade_price = _as_float(event.get("price"))
        trade_qty = _as_float(event.get("qty"))
        trade_side = str(event.get("side") or "").lower()
        if trade_price is None or trade_qty is None or trade_qty <= 0:
            return False

        direction = self._order_direction(order)
        if direction > 0:
            qualifies = trade_side == "sell" and trade_price <= order.limit_price
        else:
            qualifies = trade_side == "buy" and trade_price >= order.limit_price
        if not qualifies:
            return False

        order.queue_remaining_qty -= trade_qty
        if order.queue_remaining_qty > 0:
            return False

        if order.action == "entry":
            self._fill_maker_entry(order, state, ts)
        else:
            self._fill_maker_exit(order, state, ts)
        return True

    def _fill_maker_entry(self, order: PendingOrder, state: MarketState, ts: float) -> None:
        if order.limit_price is None or order.qty is None:
            return
        ok, reason = self.risk.can_open(
            qty=order.qty,
            price=order.limit_price,
            open_positions=len(self.positions),
            max_open_positions=self.replay_cfg.max_open_positions,
            market_open_positions=1 if order.market in self.positions else 0,
            max_open_positions_per_market=self.risk.cfg.max_open_positions_per_market,
        )
        if not ok:
            self.skipped_signals[reason] += 1
            return
        notional = order.qty * order.limit_price
        self.positions[order.market] = ReplayPosition(
            exchange=state.exchange,
            symbol=state.symbol,
            side=order.side,
            qty=order.qty,
            entry_price=order.limit_price,
            entry_ts=ts,
            entry_fee_quote=self._maker_fee(notional),
            entry_notional_quote=notional,
        )
        self.risk.register_open()

    def _fill_maker_exit(self, order: PendingOrder, state: MarketState, ts: float) -> None:
        position = self.positions.get(order.market)
        if position is None or order.limit_price is None:
            return
        gross = (order.limit_price - position.entry_price) * position.qty * position.side
        exit_notional = position.qty * order.limit_price
        exit_fee = self._maker_fee(exit_notional)
        self._record_close(order, position, ts, order.limit_price, gross, exit_fee)

    def _record_close(
        self,
        order: PendingOrder,
        position: ReplayPosition,
        ts: float,
        price: float,
        gross: float,
        exit_fee: float,
    ) -> None:
        net = gross - position.entry_fee_quote - exit_fee
        trade = ReplayTrade(
            exchange=position.exchange,
            symbol=position.symbol,
            side="LONG" if position.side > 0 else "SHORT",
            entry_ts=position.entry_ts,
            exit_ts=ts,
            hold_sec=ts - position.entry_ts,
            qty=position.qty,
            entry_price=position.entry_price,
            exit_price=price,
            entry_fee_quote=position.entry_fee_quote,
            exit_fee_quote=exit_fee,
            gross_pnl_quote=gross,
            net_pnl_quote=net,
            pnl_bps=self._pnl_bps(position, price),
            exit_reason=order.reason,
        )
        self.trades.append(trade)
        self.risk.register_close(net)
        self.positions.pop(order.market, None)
        self._record_equity(ts)

    def _pnl_bps(self, position: ReplayPosition, exit_price: float) -> float:
        if position.side > 0:
            return ((exit_price - position.entry_price) / position.entry_price) * 1e4
        return ((position.entry_price - exit_price) / position.entry_price) * 1e4

    def _unrealized_pnl_quote(self) -> float:
        """Консервативный net unrealized PnL открытых позиций по текущим ценам."""
        maker = self.replay_cfg.execution_mode == "maker"
        total = 0.0
        for key, position in self.positions.items():
            state = self.states.get(key)
            if state is None or not state.ready():
                continue
            exit_price = self._exit_price(state, position.side)
            if exit_price is None:
                continue
            gross = (exit_price - position.entry_price) * position.qty * position.side
            exit_notional = position.qty * exit_price
            exit_fee = self._maker_fee(exit_notional) if maker else self._taker_fee(exit_notional)
            total += gross - position.entry_fee_quote - exit_fee
        return total

    def _force_close_all(self, ts: float) -> None:
        for key, position in list(self.positions.items()):
            state = self.states.get(key)
            if state is None or not state.ready():
                continue
            order = PendingOrder(
                market=key,
                action="exit",
                side=position.side,
                requested_ts=ts,
                execute_after_ts=ts,
                reason="force_end",
            )
            self._execute_taker_exit(order, state, ts)
        self.pending.clear()

    def _record_equity(self, ts: float) -> None:
        self.equity_curve.append({"ts": ts, "equity_quote": self.risk.daily_realized_pnl})

    def _result(self, event_count: int) -> dict[str, Any]:
        total = len(self.trades)
        wins = sum(1 for trade in self.trades if trade.net_pnl_quote > 0)
        losses = total - wins
        gross = sum(trade.gross_pnl_quote for trade in self.trades)
        fees = sum(trade.entry_fee_quote + trade.exit_fee_quote for trade in self.trades)
        net = sum(trade.net_pnl_quote for trade in self.trades)
        gross_wins = sum(trade.net_pnl_quote for trade in self.trades if trade.net_pnl_quote > 0)
        gross_losses = abs(sum(trade.net_pnl_quote for trade in self.trades if trade.net_pnl_quote < 0))
        max_drawdown = self._max_drawdown()
        metrics = {
            "events": event_count,
            "markets": len(self.states),
            "round_trip_fee_bps": self._round_trip_fee_bps(),
            "net_take_profit_bps": self._net_take_profit_bps(),
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total else 0.0,
            "gross_pnl_quote": gross,
            "fees_quote": fees,
            "net_pnl_quote": net,
            "expectancy_quote": net / total if total else 0.0,
            "profit_factor": (gross_wins / gross_losses) if gross_losses else None,
            "max_drawdown_quote": max_drawdown,
            "daily_realized_pnl_quote": self.risk.daily_realized_pnl,
            "kill_switch_triggered": self.risk.kill_switch,
        }
        return {
            "mode": "event_driven_replay",
            "replay_config": self.replay_cfg.__dict__,
            "metrics": metrics,
            "events_by_kind": dict(self.events_by_kind),
            "events_by_exchange": dict(self.events_by_exchange),
            "skipped_signals": dict(self.skipped_signals),
            "trades": [trade.__dict__ for trade in self.trades],
            "per_market": self._per_market(),
            "equity_curve": self.equity_curve,
        }

    def _per_market(self) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[ReplayTrade]] = defaultdict(list)
        for trade in self.trades:
            grouped[f"{trade.exchange}:{trade.symbol}"].append(trade)
        out: dict[str, dict[str, Any]] = {}
        for market, trades in grouped.items():
            total = len(trades)
            wins = sum(1 for trade in trades if trade.net_pnl_quote > 0)
            out[market] = {
                "trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": wins / total if total else 0.0,
                "gross_pnl_quote": sum(trade.gross_pnl_quote for trade in trades),
                "fees_quote": sum(trade.entry_fee_quote + trade.exit_fee_quote for trade in trades),
                "net_pnl_quote": sum(trade.net_pnl_quote for trade in trades),
            }
        return out

    def _max_drawdown(self) -> float:
        peak = 0.0
        max_dd = 0.0
        for point in self.equity_curve:
            equity = point["equity_quote"]
            peak = max(peak, equity)
            max_dd = min(max_dd, equity - peak)
        return max_dd


def load_normalized_events(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=_event_ts)
    return rows


def save_replay_result(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_replay_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"ws_replay_{utc_stamp()}.json"
