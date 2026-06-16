from __future__ import annotations

import itertools
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import RiskConfig, StrategyConfig
from ws_replay import EventDrivenReplayBacktester, ReplayConfig, load_normalized_events


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def parse_float_list(raw: str) -> list[float]:
    values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError(f"Пустой список float: {raw!r}")
    return values


def parse_int_list(raw: str) -> list[int]:
    values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError(f"Пустой список int: {raw!r}")
    return values


def parse_str_list(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError(f"Пустой список str: {raw!r}")
    return values


def _strategy_from_base(
    base: StrategyConfig,
    signal_type: str,
    entry_imbalance_abs: float,
    entry_signed_flow_notional: float,
    max_spread_bps: float,
    take_profit_bps: float,
    stop_loss_bps: float,
    max_hold_sec: int,
    breakout_bps: float,
    breakout_lookback_sec: float,
    breakout_min_samples: int,
) -> StrategyConfig:
    return replace(
        base,
        signal_type=signal_type,
        entry_imbalance_abs=entry_imbalance_abs,
        entry_signed_flow_notional=entry_signed_flow_notional,
        max_spread_bps=max_spread_bps,
        take_profit_bps=take_profit_bps,
        stop_loss_bps=stop_loss_bps,
        max_hold_sec=max_hold_sec,
        breakout_bps=breakout_bps,
        breakout_lookback_sec=breakout_lookback_sec,
        breakout_min_samples=breakout_min_samples,
    )


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    metrics = item["metrics"]
    profit_factor = metrics.get("profit_factor")
    return (
        bool(item.get("eligible")),
        float(metrics.get("net_pnl_quote") or 0.0),
        float(profit_factor) if profit_factor is not None else -1.0,
        float(metrics.get("expectancy_quote") or 0.0),
        float(metrics.get("win_rate") or 0.0),
        int(metrics.get("total_trades") or 0),
    )


def run_grid_search(
    events: list[dict[str, Any]],
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
    backtester_cls: type[EventDrivenReplayBacktester] = EventDrivenReplayBacktester,
) -> dict[str, Any]:
    signal_types = grid.get("signal_type", [base_strategy.signal_type])
    # breakout-измерения опциональны: если не заданы, берем значение из базы
    # (одно значение -> grid для не-breakout сигналов не разрастается).
    breakout_bps = grid.get("breakout_bps", [base_strategy.breakout_bps])
    breakout_lookback_sec = grid.get("breakout_lookback_sec", [base_strategy.breakout_lookback_sec])
    breakout_min_samples = grid.get("breakout_min_samples", [base_strategy.breakout_min_samples])
    combinations = list(
        itertools.product(
            signal_types,
            grid["entry_imbalance_abs"],
            grid["entry_signed_flow_notional"],
            grid["max_spread_bps"],
            grid["take_profit_bps"],
            grid["stop_loss_bps"],
            grid["max_hold_sec"],
            breakout_bps,
            breakout_lookback_sec,
            breakout_min_samples,
        )
    )
    results: list[dict[str, Any]] = []
    for combo in combinations:
        strategy = _strategy_from_base(base_strategy, *combo)
        replay = backtester_cls(strategy, risk_cfg, replay_cfg)
        payload = replay.run(events)
        metrics = payload["metrics"]
        eligible, eligibility_reasons = _eligible_metrics(
            metrics,
            min_trades=min_trades,
            min_win_rate=min_win_rate,
            min_expectancy_quote=min_expectancy_quote,
            min_net_pnl_quote=min_net_pnl_quote,
            min_profit_factor=min_profit_factor,
            max_drawdown_quote=max_drawdown_quote,
        )
        results.append(
            {
                "strategy_config": asdict(strategy),
                "replay_config": asdict(replay_cfg),
                "metrics": metrics,
                "events_by_kind": payload["events_by_kind"],
                "events_by_exchange": payload["events_by_exchange"],
                "skipped_signals": payload["skipped_signals"],
                "per_market": payload["per_market"],
                "eligible": eligible,
                "eligibility_reasons": eligibility_reasons,
            }
        )

    sorted_results = sorted(results, key=_sort_key, reverse=True)
    eligible_count = sum(1 for item in results if item["eligible"])
    top = sorted_results[:top_n]
    for index, item in enumerate(top, start=1):
        item["rank"] = index
    best_by_signal_type = _best_by_signal_type(sorted_results)

    return {
        "mode": "event_driven_replay_grid_search",
        "events": len(events),
        "grid": grid,
        "eligibility_filters": {
            "min_trades": min_trades,
            "min_win_rate": min_win_rate,
            "min_expectancy_quote": min_expectancy_quote,
            "min_net_pnl_quote": min_net_pnl_quote,
            "min_profit_factor": min_profit_factor,
            "max_drawdown_quote": max_drawdown_quote,
            "min_net_take_profit_bps": replay_cfg.min_net_take_profit_bps,
        },
        "top_n": top_n,
        "total_combinations": len(combinations),
        "eligible_combinations": eligible_count,
        "best_by_signal_type": best_by_signal_type,
        "top_results": top,
    }


def run_grid_search_file(
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
    backtester_cls: type[EventDrivenReplayBacktester] = EventDrivenReplayBacktester,
) -> dict[str, Any]:
    events = load_normalized_events(input_path)
    result = run_grid_search(
        events=events,
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
        backtester_cls=backtester_cls,
    )
    result["input"] = str(input_path)
    result["output"] = str(output_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def default_grid_path(backtest_dir: str | Path) -> Path:
    return Path(backtest_dir) / f"ws_grid_search_{utc_stamp()}.json"


def _eligible_metrics(
    metrics: dict[str, Any],
    min_trades: int,
    min_win_rate: float,
    min_expectancy_quote: float,
    min_net_pnl_quote: float,
    min_profit_factor: float,
    max_drawdown_quote: float,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    total_trades = int(metrics.get("total_trades") or 0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    expectancy = float(metrics.get("expectancy_quote") or 0.0)
    net_pnl = float(metrics.get("net_pnl_quote") or 0.0)
    profit_factor_raw = metrics.get("profit_factor")
    profit_factor = float(profit_factor_raw) if profit_factor_raw is not None else None
    drawdown = abs(float(metrics.get("max_drawdown_quote") or 0.0))

    if total_trades < min_trades:
        reasons.append("min_trades")
    if win_rate < min_win_rate:
        reasons.append("min_win_rate")
    if expectancy < min_expectancy_quote:
        reasons.append("min_expectancy_quote")
    if net_pnl < min_net_pnl_quote:
        reasons.append("min_net_pnl_quote")
    if min_profit_factor > 0 and (profit_factor is None or profit_factor < min_profit_factor):
        reasons.append("min_profit_factor")
    if max_drawdown_quote > 0 and drawdown > max_drawdown_quote:
        reasons.append("max_drawdown_quote")
    return not reasons, reasons


def _best_by_signal_type(sorted_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in sorted_results:
        signal_type = str(item.get("strategy_config", {}).get("signal_type") or "")
        if not signal_type or signal_type in out:
            continue
        best = dict(item)
        best.pop("rank", None)
        out[signal_type] = best
    return out
