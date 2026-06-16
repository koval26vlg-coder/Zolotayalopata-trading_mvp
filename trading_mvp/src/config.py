from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class ExchangeConfig:
    name: str = "binance-spot-reference"
    base_url: str = "https://api.binance.com"
    symbol: str = "BTCUSDT"
    depth_limit: int = 20
    trades_limit: int = 100
    poll_interval_sec: float = 0.5
    timeout_sec: int = 10


@dataclass(frozen=True)
class StrategyConfig:
    signal_type: str = "flow_continue"
    entry_imbalance_abs: float = 0.25
    entry_signed_flow_notional: float = 5000.0
    max_spread_bps: float = 3.0
    take_profit_bps: float = 6.0
    stop_loss_bps: float = 6.0
    max_hold_sec: int = 25
    sweep_v2_allowed_markets: str = ""
    sweep_v2_side: str = ""
    sweep_v2_min_trade_notional_quote: float = 0.0
    sweep_v2_min_intensity_bps: float = 0.0
    sweep_v2_max_pre_spread_bps: float = 0.0
    sweep_v2_max_reclaim_sec: float = 0.0
    sweep_v2_event_cooldown_sec: float = 0.0
    # large_move_breakout: вход на подтвержденном пробое экстремума окна
    breakout_lookback_sec: float = 30.0
    breakout_bps: float = 5.0
    breakout_min_samples: int = 5


@dataclass(frozen=True)
class RiskConfig:
    max_notional_per_trade: float = 50.0
    max_position_qty: float = 1_000_000.0
    max_trades_per_day: int = 200
    daily_loss_limit_quote: float = 20.0
    # Cost gate: минимальный net take-profit (bps) после round-trip комиссий.
    # Dataclass default -1e9 = выключено (обратная совместимость и тесты).
    # В config.json значение поднимается до рабочего (>=1), что включает гейт
    # для всех replay/grid, даже если CLI передал более мягкий порог.
    min_net_take_profit_bps: float = -1e9
    # Лимит одновременных позиций на один рынок (exchange:symbol).
    max_open_positions_per_market: int = 1


@dataclass(frozen=True)
class PathsConfig:
    raw_dir: str = "exports/trading-mvp/raw"
    normalized_dir: str = "exports/trading-mvp/normalized"
    backtest_dir: str = "exports/trading-mvp/backtests"
    run_dir: str = "exports/trading-mvp/run"
    universe_dir: str = "exports/trading-mvp/universe"
    funding_dir: str = "exports/trading-mvp/funding"
    experiment_dir: str = "exports/trading-mvp/experiments"


@dataclass(frozen=True)
class AppConfig:
    exchange: ExchangeConfig
    strategy: StrategyConfig
    risk: RiskConfig
    paths: PathsConfig


DEFAULT_CONFIG: dict[str, Any] = {
    "exchange": ExchangeConfig().__dict__,
    "strategy": StrategyConfig().__dict__,
    "risk": RiskConfig().__dict__,
    "paths": PathsConfig().__dict__,
}


def load_config(path: str | Path) -> AppConfig:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Не найден конфиг: {cfg_path}")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    merged = _merge_dict(DEFAULT_CONFIG, data)
    return AppConfig(
        exchange=ExchangeConfig(**merged["exchange"]),
        strategy=StrategyConfig(**merged["strategy"]),
        risk=RiskConfig(**merged["risk"]),
        paths=PathsConfig(**merged["paths"]),
    )
