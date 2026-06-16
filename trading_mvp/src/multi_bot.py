from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import RiskConfig, StrategyConfig
from exchanges import MarketPair, MarketSnapshot, PublicSpotClient, build_clients
from trading import MicrostructureStrategy, Position, TradeResult, utc_stamp


@dataclass
class PaperState:
    strategy: MicrostructureStrategy
    risk_cfg: RiskConfig
    position: Position | None = None
    trades: list[TradeResult] = field(default_factory=list)
    trades_opened: int = 0
    daily_realized_pnl: float = 0.0
    kill_switch: bool = False


def load_universe_symbols(path: Path, max_symbols: int | None = None) -> list[str]:
    symbols: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            symbols.append(symbol)
            if max_symbols and len(symbols) >= max_symbols:
                break
    return symbols


def select_pairs(
    exchange_pairs: list[MarketPair],
    universe_symbols: list[str],
    max_pairs: int,
) -> list[MarketPair]:
    pairs_by_base = {pair.base.upper(): pair for pair in exchange_pairs}
    selected: list[MarketPair] = []
    seen: set[str] = set()
    for symbol in universe_symbols:
        if symbol in seen:
            continue
        pair = pairs_by_base.get(symbol)
        if pair is None:
            continue
        selected.append(pair)
        seen.add(symbol)
        if len(selected) >= max_pairs:
            break
    return selected


class MultiExchangePaperBot:
    def __init__(
        self,
        clients: dict[str, PublicSpotClient],
        pairs_by_exchange: dict[str, list[MarketPair]],
        strategy_cfg: StrategyConfig,
        risk_cfg: RiskConfig,
        paper_notional_quote: float,
        depth_limit: int,
        trades_limit: int,
        poll_interval_sec: float,
    ) -> None:
        self.clients = clients
        self.pairs_by_exchange = pairs_by_exchange
        self.strategy_cfg = strategy_cfg
        self.risk_cfg = risk_cfg
        self.paper_notional_quote = paper_notional_quote
        self.depth_limit = depth_limit
        self.trades_limit = trades_limit
        self.poll_interval_sec = poll_interval_sec
        self.states: dict[str, PaperState] = {}
        self.snapshots: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def run(self, cycles: int | None = None, duration_sec: int | None = None) -> dict[str, Any]:
        started = time.time()
        completed_cycles = 0
        while True:
            if cycles is not None and completed_cycles >= cycles:
                break
            if duration_sec is not None and time.time() - started >= duration_sec:
                break
            for exchange_id, pairs in self.pairs_by_exchange.items():
                client = self.clients[exchange_id]
                for pair in pairs:
                    key = self._key(pair)
                    try:
                        snapshot = client.fetch_snapshot(
                            pair,
                            depth_limit=self.depth_limit,
                            trades_limit=self.trades_limit,
                        )
                    except Exception as exc:  # noqa: BLE001
                        self.errors.append(
                            {
                                "exchange": exchange_id,
                                "symbol": pair.symbol,
                                "error": str(exc)[:300],
                            }
                        )
                        continue
                    self.snapshots.append(snapshot.as_dict())
                    state = self.states.setdefault(
                        key,
                        PaperState(
                            strategy=MicrostructureStrategy(self.strategy_cfg),
                            risk_cfg=self.risk_cfg,
                        ),
                    )
                    self._step(pair, snapshot, state)
            completed_cycles += 1
            time.sleep(self.poll_interval_sec)

        for exchange_id, pairs in self.pairs_by_exchange.items():
            for pair in pairs:
                key = self._key(pair)
                state = self.states.get(key)
                if state and state.position is not None:
                    latest = self._latest_snapshot(exchange_id, pair.symbol)
                    if latest:
                        self._close(pair, MarketSnapshot(**latest), state, "force_end")

        result = self._result()
        result["runtime"] = {
            "duration_sec": time.time() - started,
            "completed_cycles": completed_cycles,
            "requested_cycles": cycles,
            "requested_duration_sec": duration_sec,
        }
        return result

    def _step(self, pair: MarketPair, snapshot: MarketSnapshot, state: PaperState) -> None:
        snap = snapshot.as_dict()
        if state.position is not None:
            should_exit, reason, _, _ = state.strategy.should_exit(state.position, snap)
            if should_exit:
                self._close(pair, snapshot, state, reason)

        if state.position is not None or state.kill_switch:
            return
        side = state.strategy.signal(snap)
        if side == 0:
            return
        self._open(pair, snapshot, state, side)

    def _open(self, pair: MarketPair, snapshot: MarketSnapshot, state: PaperState, side: int) -> None:
        if state.trades_opened >= state.risk_cfg.max_trades_per_day:
            return
        entry_price = snapshot.ask if side > 0 else snapshot.bid
        notional = min(self.paper_notional_quote, state.risk_cfg.max_notional_per_trade)
        qty = notional / entry_price if entry_price > 0 else 0.0
        if qty <= 0:
            return
        if qty > state.risk_cfg.max_position_qty:
            qty = state.risk_cfg.max_position_qty
        if qty * entry_price <= 0:
            return
        state.position = Position(
            side=side,
            qty=qty,
            entry_price=entry_price,
            entry_ts=snapshot.ts,
        )
        state.trades_opened += 1

    def _close(self, pair: MarketPair, snapshot: MarketSnapshot, state: PaperState, reason: str) -> None:
        if state.position is None:
            return
        should_exit, _, exit_price, pnl_bps = state.strategy.should_exit(
            state.position,
            snapshot.as_dict(),
        )
        if not should_exit and reason == "force_end":
            exit_price = snapshot.bid if state.position.side > 0 else snapshot.ask
            pnl_bps = (
                ((exit_price - state.position.entry_price) / state.position.entry_price) * 1e4
                if state.position.side > 0
                else ((state.position.entry_price - exit_price) / state.position.entry_price) * 1e4
            )
        pnl_quote = (exit_price - state.position.entry_price) * state.position.qty * state.position.side
        state.trades.append(
            TradeResult(
                side="LONG" if state.position.side > 0 else "SHORT",
                entry_price=state.position.entry_price,
                exit_price=exit_price,
                qty=state.position.qty,
                entry_ts=state.position.entry_ts,
                exit_ts=snapshot.ts,
                hold_sec=snapshot.ts - state.position.entry_ts,
                pnl_quote=pnl_quote,
                pnl_bps=pnl_bps,
                exit_reason=reason,
            )
        )
        state.daily_realized_pnl += pnl_quote
        if state.daily_realized_pnl <= -abs(state.risk_cfg.daily_loss_limit_quote):
            state.kill_switch = True
        state.position = None

    def _latest_snapshot(self, exchange: str, symbol: str) -> dict[str, Any] | None:
        for snapshot in reversed(self.snapshots):
            if snapshot["exchange"] == exchange and snapshot["symbol"] == symbol:
                return snapshot
        return None

    def _result(self) -> dict[str, Any]:
        per_market: dict[str, Any] = {}
        all_trades: list[dict[str, Any]] = []
        for key, state in self.states.items():
            trades = [trade.__dict__ for trade in state.trades]
            gross_pnl = sum(trade["pnl_quote"] for trade in trades)
            wins = sum(1 for trade in trades if trade["pnl_quote"] > 0)
            total = len(trades)
            per_market[key] = {
                "total_trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": wins / total if total else 0.0,
                "gross_pnl_quote": gross_pnl,
                "daily_realized_pnl_quote": state.daily_realized_pnl,
                "kill_switch_triggered": state.kill_switch,
                "trades": trades,
            }
            for trade in trades:
                trade["market"] = key
                all_trades.append(trade)

        gross_pnl = sum(trade["pnl_quote"] for trade in all_trades)
        wins = sum(1 for trade in all_trades if trade["pnl_quote"] > 0)
        total = len(all_trades)
        return {
            "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "metrics": {
                "markets": len(self.states),
                "snapshots": len(self.snapshots),
                "errors": len(self.errors),
                "total_trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": wins / total if total else 0.0,
                "gross_pnl_quote": gross_pnl,
            },
            "per_market": per_market,
            "trades": all_trades,
            "errors": self.errors,
        }

    def _key(self, pair: MarketPair) -> str:
        return f"{pair.exchange}:{pair.symbol}"


def build_pairs_for_universe(
    exchange_ids: list[str],
    universe_csv: Path,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    timeout_sec: int,
) -> tuple[dict[str, PublicSpotClient], dict[str, list[MarketPair]], dict[str, Any]]:
    clients = build_clients(exchange_ids, timeout_sec=timeout_sec)
    universe_symbols = load_universe_symbols(universe_csv, max_symbols=max_symbols)
    pairs_by_exchange: dict[str, list[MarketPair]] = {}
    discovery: dict[str, Any] = {}
    for exchange_id, client in clients.items():
        try:
            pairs = client.fetch_pairs(quote=quote)
        except Exception as exc:  # noqa: BLE001
            pairs_by_exchange[exchange_id] = []
            discovery[exchange_id] = {
                "available_pairs": 0,
                "selected_pairs": 0,
                "symbols": [],
                "error": str(exc)[:300],
            }
            continue
        selected = select_pairs(pairs, universe_symbols, max_pairs=max_pairs_per_exchange)
        pairs_by_exchange[exchange_id] = selected
        discovery[exchange_id] = {
            "available_pairs": len(pairs),
            "selected_pairs": len(selected),
            "symbols": [pair.symbol for pair in selected],
        }
    return clients, pairs_by_exchange, discovery


def save_multi_run(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def multi_run_output_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / f"multi_run_{utc_stamp()}.json"
