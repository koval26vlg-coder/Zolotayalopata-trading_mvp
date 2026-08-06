from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import RiskConfig, StrategyConfig
from ws_grid_search import run_grid_search_file as _run_grid_search_file
from ws_replay import (
    EventDrivenReplayBacktester,
    MarketState,
    PendingOrder,
    ReplayConfig,
    ReplayPosition,
    ReplayTrade,
    load_normalized_events,
    save_replay_result,
)


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


class PerpMarketState(MarketState):
    def __init__(self, exchange: str, symbol: str) -> None:
        super().__init__(exchange, symbol)
        self.mark_price: float | None = None
        self.index_price: float | None = None
        self.funding_rate: float | None = None
        self.next_funding_ts: float | None = None
        self.funding_interval_sec: int | None = None
        self.open_interest: float | None = None
        self.volume_24h_quote: float | None = None

    def update(self, event: dict[str, Any]) -> None:
        super().update(event)
        mark_price = _as_float(event.get("mark_price"))
        if mark_price is not None:
            self.mark_price = mark_price
        index_price = _as_float(event.get("index_price"))
        if index_price is not None:
            self.index_price = index_price
        funding_rate = _as_float(event.get("funding_rate"))
        if funding_rate is not None:
            self.funding_rate = funding_rate
        next_funding_ts = _as_float(event.get("next_funding_ts"))
        if next_funding_ts is not None:
            self.next_funding_ts = next_funding_ts
        interval = _as_float(event.get("funding_interval_sec"))
        if interval is not None and interval > 0:
            self.funding_interval_sec = int(interval)
        open_interest = _as_float(event.get("open_interest"))
        if open_interest is not None:
            self.open_interest = open_interest
        volume_24h_quote = _as_float(event.get("volume_24h_quote"))
        if volume_24h_quote is not None:
            self.volume_24h_quote = volume_24h_quote

    def effective_price(self) -> float | None:
        if self.mark_price is not None and self.mark_price > 0:
            return self.mark_price
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            mid = (self.bid + self.ask) / 2.0
            return mid if mid > 0 else None
        if self.bid is not None and self.bid > 0:
            return self.bid
        if self.ask is not None and self.ask > 0:
            return self.ask
        return None


@dataclass
class PerpPosition(ReplayPosition):
    funding_pnl_quote: float = 0.0
    last_funding_ts: float = 0.0
    last_funding_rate: float = 0.0
    funding_interval_sec: float = 28_800.0
    next_funding_ts: float | None = None
    funding_settlements: int = 0
    entry_mark_price: float | None = None
    entry_index_price: float | None = None
    entry_funding_rate: float | None = None


@dataclass
class PerpTrade(ReplayTrade):
    funding_pnl_quote: float = 0.0
    entry_mark_price: float | None = None
    exit_mark_price: float | None = None
    entry_index_price: float | None = None
    exit_index_price: float | None = None
    entry_funding_rate: float | None = None
    exit_funding_rate: float | None = None
    funding_settlements: int = 0


class PerpReplayBacktester(EventDrivenReplayBacktester):
    def __init__(
        self,
        strategy_cfg: StrategyConfig,
        risk_cfg: RiskConfig,
        replay_cfg: ReplayConfig,
    ) -> None:
        replay_cfg = replace(replay_cfg, allow_short=True)
        super().__init__(strategy_cfg, risk_cfg, replay_cfg)
        self.states: dict[str, PerpMarketState] = {}
        self.positions: dict[str, PerpPosition] = {}
        self.trades: list[PerpTrade] = []

    def _state_for(self, event: dict[str, Any]) -> PerpMarketState:
        key = _market_key(event)
        state = self.states.get(key)
        if state is None:
            state = PerpMarketState(str(event.get("exchange")), str(event.get("symbol")))
            self.states[key] = state
        return state

    def _on_event(self, event: dict[str, Any]) -> None:
        key = _market_key(event)
        kind = str(event.get("event_kind"))
        self.events_by_kind[kind] += 1
        self.events_by_exchange[str(event.get("exchange"))] += 1
        state = self._state_for(event)
        ts = _event_ts(event)
        self.risk.advance_time(ts)
        self._settle_funding(key, state, ts)
        state.update(event)
        self._sync_funding_schedule(key, state, ts)
        self._try_execute_pending(key, state, ts, event)
        if self.risk.mark_unrealized(self._unrealized_pnl_quote(), ts=ts):
            self._record_equity(ts)
        if not state.ready():
            return
        if key in self.positions and key not in self.pending:
            self._maybe_schedule_exit(key, state, ts)
        if key not in self.positions and key not in self.pending:
            self._maybe_schedule_entry(key, state, ts)

    def _settle_funding(self, key: str, state: PerpMarketState, ts: float) -> None:
        position = self.positions.get(key)
        if position is None:
            return
        next_funding_ts = position.next_funding_ts
        if next_funding_ts is None or ts < next_funding_ts:
            return
        rate = position.last_funding_rate
        interval = float(position.funding_interval_sec or 28_800.0)
        if interval <= 0:
            interval = 28_800.0
        effective_price = state.effective_price() or position.entry_price
        if effective_price is None:
            return
        notional = position.qty * effective_price
        while next_funding_ts <= ts:
            position.funding_pnl_quote += -position.side * notional * rate
            position.last_funding_ts = next_funding_ts
            position.funding_settlements += 1
            next_funding_ts += interval
        position.next_funding_ts = next_funding_ts

    def _sync_funding_schedule(self, key: str, state: PerpMarketState, ts: float) -> None:
        position = self.positions.get(key)
        if position is None:
            return
        if state.funding_rate is not None:
            position.last_funding_rate = state.funding_rate
        if state.funding_interval_sec is not None and state.funding_interval_sec > 0:
            position.funding_interval_sec = float(state.funding_interval_sec)
        if position.next_funding_ts is None and state.next_funding_ts is not None and state.next_funding_ts > ts:
            position.next_funding_ts = state.next_funding_ts

    def _execute_taker_entry(self, order: PendingOrder, state: PerpMarketState, ts: float) -> None:
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
            ts=ts,
        )
        if not ok:
            self.skipped_signals[reason] += 1
            return
        notional = qty * price
        self.positions[order.market] = PerpPosition(
            exchange=state.exchange,
            symbol=state.symbol,
            side=order.side,
            qty=qty,
            entry_price=price,
            entry_ts=ts,
            entry_fee_quote=self._taker_fee(notional, state.exchange),
            entry_notional_quote=notional,
            funding_pnl_quote=0.0,
            last_funding_ts=ts,
            last_funding_rate=float(state.funding_rate or 0.0),
            funding_interval_sec=float(state.funding_interval_sec or 28_800.0),
            next_funding_ts=state.next_funding_ts if state.next_funding_ts is not None and state.next_funding_ts > ts else None,
            funding_settlements=0,
            entry_mark_price=state.effective_price(),
            entry_index_price=state.index_price,
            entry_funding_rate=state.funding_rate,
        )
        self.risk.register_open(ts=ts)

    def _execute_taker_exit(self, order: PendingOrder, state: PerpMarketState, ts: float) -> None:
        position = self.positions.get(order.market)
        if position is None:
            return
        price = self._exit_price(state, position.side)
        if price is None:
            return
        gross = (price - position.entry_price) * position.qty * position.side
        exit_notional = position.qty * price
        exit_fee = self._taker_fee(exit_notional, state.exchange)
        self._record_close(order, position, state, ts, price, gross, exit_fee)

    def _fill_maker_entry(
        self,
        order: PendingOrder,
        state: PerpMarketState,
        ts: float,
        fill_qty: float,
    ) -> bool:
        if order.limit_price is None or order.qty is None:
            return False
        position = self.positions.get(order.market)
        if position is None:
            ok, reason = self.risk.can_open(
                qty=order.qty,
                price=order.limit_price,
                open_positions=len(self.positions),
                max_open_positions=self.replay_cfg.max_open_positions,
                market_open_positions=0,
                max_open_positions_per_market=self.risk.cfg.max_open_positions_per_market,
                ts=ts,
            )
            if not ok:
                self.skipped_signals[reason] += 1
                return False
            notional = fill_qty * order.limit_price
            self.positions[order.market] = PerpPosition(
                exchange=state.exchange,
                symbol=state.symbol,
                side=order.side,
                qty=fill_qty,
                entry_price=order.limit_price,
                entry_ts=ts,
                entry_fee_quote=self._maker_fee(notional, state.exchange),
                entry_notional_quote=notional,
                funding_pnl_quote=0.0,
                last_funding_ts=ts,
                last_funding_rate=float(state.funding_rate or 0.0),
                funding_interval_sec=float(state.funding_interval_sec or 28_800.0),
                next_funding_ts=(
                    state.next_funding_ts
                    if state.next_funding_ts is not None and state.next_funding_ts > ts
                    else None
                ),
                funding_settlements=0,
                entry_mark_price=state.effective_price(),
                entry_index_price=state.index_price,
                entry_funding_rate=state.funding_rate,
            )
            self.risk.register_open(ts=ts)
            return True
        notional = fill_qty * order.limit_price
        position.qty += fill_qty
        position.entry_notional_quote += notional
        position.entry_fee_quote += self._maker_fee(notional, state.exchange)
        return True

    def _fill_maker_exit(
        self,
        order: PendingOrder,
        state: PerpMarketState,
        ts: float,
        fill_qty: float,
    ) -> bool:
        position = self.positions.get(order.market)
        if position is None or order.limit_price is None:
            return False
        close_qty = min(position.qty, fill_qty)
        gross = (order.limit_price - position.entry_price) * close_qty * position.side
        exit_notional = close_qty * order.limit_price
        exit_fee = self._maker_fee(exit_notional, state.exchange)
        self._record_close(
            order,
            position,
            state,
            ts,
            order.limit_price,
            gross,
            exit_fee,
            close_qty=close_qty,
        )
        return True

    def _record_close(
        self,
        order: PendingOrder,
        position: PerpPosition,
        state: PerpMarketState,
        ts: float,
        price: float,
        gross: float,
        exit_fee: float,
        close_qty: float | None = None,
    ) -> None:
        position_qty_before = position.qty
        qty = position_qty_before if close_qty is None else min(position_qty_before, max(0.0, close_qty))
        if qty <= 0:
            return
        allocation = qty / position_qty_before
        funding = position.funding_pnl_quote * allocation
        entry_fee = position.entry_fee_quote * allocation
        entry_notional = position.entry_notional_quote * allocation
        settlements = position.funding_settlements
        net = gross + funding - entry_fee - exit_fee
        trade = PerpTrade(
            exchange=position.exchange,
            symbol=position.symbol,
            side="LONG" if position.side > 0 else "SHORT",
            entry_ts=position.entry_ts,
            exit_ts=ts,
            hold_sec=ts - position.entry_ts,
            qty=qty,
            entry_price=position.entry_price,
            exit_price=price,
            entry_fee_quote=entry_fee,
            exit_fee_quote=exit_fee,
            gross_pnl_quote=gross,
            net_pnl_quote=net,
            pnl_bps=self._pnl_bps(position, price),
            exit_reason=order.reason,
            funding_pnl_quote=funding,
            entry_mark_price=position.entry_mark_price,
            exit_mark_price=state.effective_price(),
            entry_index_price=position.entry_index_price,
            exit_index_price=state.index_price,
            entry_funding_rate=position.entry_funding_rate,
            exit_funding_rate=state.funding_rate,
            funding_settlements=settlements,
        )
        self.trades.append(trade)
        self.risk.register_close(net, ts=ts)
        position.qty -= qty
        position.entry_fee_quote -= entry_fee
        position.entry_notional_quote -= entry_notional
        position.funding_pnl_quote -= funding
        if position.qty <= 1e-12:
            self.positions.pop(order.market, None)
        self.risk.mark_unrealized(self._unrealized_pnl_quote(), ts=ts)
        self._record_equity(ts)

    def _per_market(self) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[PerpTrade]] = defaultdict(list)
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
                "funding_pnl_quote": sum(trade.funding_pnl_quote for trade in trades),
                "fees_quote": sum(trade.entry_fee_quote + trade.exit_fee_quote for trade in trades),
                "net_pnl_quote": sum(trade.net_pnl_quote for trade in trades),
            }
        return out

    def _result(self, event_count: int) -> dict[str, Any]:
        payload = super()._result(event_count)
        payload["mode"] = "perp_event_driven_replay"
        payload["metrics"]["funding_pnl_quote"] = sum(trade.funding_pnl_quote for trade in self.trades)
        payload["per_market"] = self._per_market()
        return payload


def run_perp_replay(
    events: list[dict[str, Any]],
    strategy_cfg: StrategyConfig,
    risk_cfg: RiskConfig,
    replay_cfg: ReplayConfig,
) -> dict[str, Any]:
    backtester = PerpReplayBacktester(strategy_cfg, risk_cfg, replace(replay_cfg, allow_short=True))
    return backtester.run(events)


def run_perp_replay_file(
    input_path: str | Path,
    output_path: str | Path,
    strategy_cfg: StrategyConfig,
    risk_cfg: RiskConfig,
    replay_cfg: ReplayConfig,
) -> dict[str, Any]:
    events = load_normalized_events(input_path)
    payload = run_perp_replay(events, strategy_cfg, risk_cfg, replay_cfg)
    payload["input"] = str(input_path)
    payload["output"] = str(output_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_perp_grid_search_file(
    input_path: str | Path,
    output_path: str | Path,
    base_strategy: StrategyConfig,
    risk_cfg: RiskConfig,
    replay_cfg: ReplayConfig,
    grid: dict[str, list[str] | list[float] | list[int]],
    min_trades: int = 1,
    top_n: int = 20,
    min_win_rate: float = 0.0,
    min_expectancy_quote: float = -1e9,
    min_net_pnl_quote: float = -1e9,
    min_profit_factor: float = 0.0,
    max_drawdown_quote: float = 0.0,
    max_combinations: int = 10_000,
) -> dict[str, Any]:
    replay_cfg = replace(replay_cfg, allow_short=True)
    result = _run_grid_search_file(
        input_path=input_path,
        output_path=output_path,
        base_strategy=base_strategy,
        risk_cfg=risk_cfg,
        replay_cfg=replay_cfg,
        grid=grid,
        min_trades=min_trades,
        top_n=top_n,
        min_win_rate=min_win_rate,
        min_expectancy_quote=min_expectancy_quote,
        min_net_pnl_quote=min_net_pnl_quote,
        min_profit_factor=min_profit_factor,
        max_drawdown_quote=max_drawdown_quote,
        max_combinations=max_combinations,
        backtester_cls=PerpReplayBacktester,
    )
    result["mode"] = "perp_event_driven_replay_grid_search"
    target = Path(output_path)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def default_perp_replay_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"perp_replay_{utc_stamp()}.json"


def default_perp_grid_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"perp_grid_search_{utc_stamp()}.json"
