from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import RiskConfig, StrategyConfig


@dataclass
class Position:
    side: int
    qty: float
    entry_price: float
    entry_ts: float


@dataclass
class TradeResult:
    side: str
    entry_price: float
    exit_price: float
    qty: float
    entry_ts: float
    exit_ts: float
    hold_sec: float
    pnl_quote: float
    pnl_bps: float
    exit_reason: str


class RiskEngine:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self.daily_realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.trades_opened = 0
        self.kill_switch = False

    def can_open(self, qty: float, price: float) -> tuple[bool, str]:
        if self.kill_switch:
            return False, "kill_switch_active"
        if self.trades_opened >= self.cfg.max_trades_per_day:
            return False, "max_trades_per_day"
        if qty > self.cfg.max_position_qty:
            return False, "max_position_qty"
        if qty * price > self.cfg.max_notional_per_trade:
            return False, "max_notional_per_trade"
        return True, "ok"

    def register_open(self) -> None:
        self.trades_opened += 1

    def register_close(self, realized_pnl_quote: float) -> None:
        self.daily_realized_pnl += realized_pnl_quote
        self._check_equity_kill_switch()

    def mark_unrealized(self, unrealized_pnl_quote: float) -> None:
        """Учет нереализованного PnL открытой позиции для дневного kill-switch."""
        self.unrealized_pnl = unrealized_pnl_quote
        self._check_equity_kill_switch()

    def _check_equity_kill_switch(self) -> None:
        if self.daily_realized_pnl + self.unrealized_pnl <= -abs(self.cfg.daily_loss_limit_quote):
            self.kill_switch = True


class MicrostructureStrategy:
    def __init__(self, cfg: StrategyConfig) -> None:
        self.cfg = cfg

    def signal(self, snapshot: dict[str, Any]) -> int:
        spread_bps = float(snapshot["spread_bps"])
        imbalance = float(snapshot["imbalance"])
        signed_flow_notional = float(snapshot.get("signed_flow_notional", 0.0))
        if spread_bps > self.cfg.max_spread_bps:
            return 0
        if (
            imbalance >= self.cfg.entry_imbalance_abs
            and signed_flow_notional >= self.cfg.entry_signed_flow_notional
        ):
            return 1
        if (
            imbalance <= -self.cfg.entry_imbalance_abs
            and signed_flow_notional <= -self.cfg.entry_signed_flow_notional
        ):
            return -1
        return 0

    def should_exit(self, position: Position, snapshot: dict[str, Any]) -> tuple[bool, str, float, float]:
        bid = float(snapshot["bid"])
        ask = float(snapshot["ask"])
        ts = float(snapshot["ts"])
        hold_sec = ts - position.entry_ts
        if position.side > 0:
            exit_price = bid
            pnl_bps = ((exit_price - position.entry_price) / position.entry_price) * 1e4
        else:
            exit_price = ask
            pnl_bps = ((position.entry_price - exit_price) / position.entry_price) * 1e4

        if pnl_bps >= self.cfg.take_profit_bps:
            return True, "take_profit", exit_price, pnl_bps
        if pnl_bps <= -self.cfg.stop_loss_bps:
            return True, "stop_loss", exit_price, pnl_bps
        if hold_sec >= self.cfg.max_hold_sec:
            return True, "timeout", exit_price, pnl_bps
        return False, "", exit_price, pnl_bps


class Backtester:
    def __init__(self, strategy_cfg: StrategyConfig, risk_cfg: RiskConfig) -> None:
        self.strategy = MicrostructureStrategy(strategy_cfg)
        self.risk = RiskEngine(risk_cfg)
        self.position: Position | None = None
        self.trades: list[TradeResult] = []

    def _open_position(self, snapshot: dict[str, Any], side: int, qty: float) -> bool:
        entry_price = float(snapshot["ask"]) if side > 0 else float(snapshot["bid"])
        ok, reason = self.risk.can_open(qty=qty, price=entry_price)
        if not ok:
            return False
        self.position = Position(
            side=side,
            qty=qty,
            entry_price=entry_price,
            entry_ts=float(snapshot["ts"]),
        )
        self.risk.register_open()
        return True

    def _close_position(self, snapshot: dict[str, Any], reason: str) -> None:
        assert self.position is not None
        should_exit, _, exit_price, pnl_bps = self.strategy.should_exit(self.position, snapshot)
        if not should_exit and reason == "force_end":
            bid = float(snapshot["bid"])
            ask = float(snapshot["ask"])
            exit_price = bid if self.position.side > 0 else ask
            pnl_bps = (
                ((exit_price - self.position.entry_price) / self.position.entry_price) * 1e4
                if self.position.side > 0
                else ((self.position.entry_price - exit_price) / self.position.entry_price) * 1e4
            )
        pnl_quote = (exit_price - self.position.entry_price) * self.position.qty * self.position.side
        result = TradeResult(
            side="LONG" if self.position.side > 0 else "SHORT",
            entry_price=self.position.entry_price,
            exit_price=exit_price,
            qty=self.position.qty,
            entry_ts=self.position.entry_ts,
            exit_ts=float(snapshot["ts"]),
            hold_sec=float(snapshot["ts"]) - self.position.entry_ts,
            pnl_quote=pnl_quote,
            pnl_bps=pnl_bps,
            exit_reason=reason,
        )
        self.trades.append(result)
        self.risk.register_close(pnl_quote)
        self.position = None

    def run(self, snapshots: list[dict[str, Any]], qty: float) -> dict[str, Any]:
        if not snapshots:
            return {
                "trades": [],
                "metrics": {
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "gross_pnl_quote": 0.0,
                    "expectancy_quote": 0.0,
                    "kill_switch_triggered": self.risk.kill_switch,
                },
            }

        for snap in snapshots:
            if self.position is not None:
                should_exit, reason, exit_price, _ = self.strategy.should_exit(self.position, snap)
                if should_exit:
                    self._close_position(snap, reason)
                else:
                    unrealized = (
                        (exit_price - self.position.entry_price)
                        * self.position.qty
                        * self.position.side
                    )
                    self.risk.mark_unrealized(unrealized)

            if self.position is None and not self.risk.kill_switch:
                side = self.strategy.signal(snap)
                if side != 0:
                    self._open_position(snap, side=side, qty=qty)

        if self.position is not None:
            self._close_position(snapshots[-1], "force_end")

        gross_pnl = sum(t.pnl_quote for t in self.trades)
        wins = sum(1 for t in self.trades if t.pnl_quote > 0)
        total = len(self.trades)
        expectancy = gross_pnl / total if total else 0.0
        metrics = {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": (wins / total) if total else 0.0,
            "gross_pnl_quote": gross_pnl,
            "expectancy_quote": expectancy,
            "daily_realized_pnl_quote": self.risk.daily_realized_pnl,
            "kill_switch_triggered": self.risk.kill_switch,
        }
        trades_json = [t.__dict__ for t in self.trades]
        return {"trades": trades_json, "metrics": metrics}


def load_snapshots(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=lambda x: float(x["ts"]))
    return rows


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
