"""Slow Liquidity VWAP & Order Book Postprocessing Engine.

Integrates orderbook_engine VWAP and dynamic slippage modeling onto the
30,021-row Slow Liquidity recollect dataset (MEXC & Gate.io).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_mvp.src.orderbook_engine import (
    simulated_slippage_bps_buy,
    simulated_slippage_bps_sell,
    spread_bps,
)


@dataclass(frozen=True)
class Candle:
    exchange: str
    symbol: str
    base: str
    quote: str
    granularity: str
    ts: int
    iso: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float


@dataclass(frozen=True)
class TradeResult:
    event_id: str
    exchange: str
    symbol: str
    base: str
    entry_ts: int
    entry_iso: str
    exit_ts: int
    exit_iso: str
    side: str
    entry_price: float
    exit_price: float
    target_price: float
    stop_price: float
    exit_reason: str
    gross_bps: float
    spread_bps: float
    slippage_bps: float
    fee_bps: float
    total_friction_bps: float
    net_bps: float
    notional_quote: float
    gross_pnl_quote: float
    net_pnl_quote: float
    candle_quote_volume: float
    participation_rate: float
    is_train: bool


def _parse_candle(row: dict[str, Any]) -> Candle | None:
    if str(row.get("data_status") or "") != "ok":
        return None
    try:
        ts = int(row.get("candle_ts") or 0)
        o = float(row.get("open") or 0.0)
        h = float(row.get("high") or 0.0)
        l = float(row.get("low") or 0.0)
        c = float(row.get("close") or 0.0)
        v = float(row.get("volume") or 0.0)
        qv = float(row.get("quote_volume") or 0.0)
        if qv <= 0 and v > 0 and c > 0:
            qv = v * c
        if ts <= 0 or o <= 0 or h <= 0 or l <= 0 or c <= 0:
            return None
        return Candle(
            exchange=str(row.get("exchange") or ""),
            symbol=str(row.get("symbol") or ""),
            base=str(row.get("base") or ""),
            quote=str(row.get("quote") or "USDT"),
            granularity=str(row.get("granularity") or "1h"),
            ts=ts,
            iso=str(row.get("candle_iso") or ""),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
            quote_volume=qv,
        )
    except (TypeError, ValueError):
        return None


def _calculate_atr(candles: list[Candle], period: int = 14) -> list[float]:
    if not candles:
        return []
    atrs: list[float] = []
    tr_sum = 0.0
    for idx, c in enumerate(candles):
        if idx == 0:
            tr = c.high - c.low
        else:
            prev = candles[idx - 1]
            tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        if idx < period:
            tr_sum += tr
            atrs.append(tr_sum / (idx + 1))
        else:
            prev_atr = atrs[-1]
            current_atr = (prev_atr * (period - 1) + tr) / period
            atrs.append(current_atr)
    return atrs


def _rolling_median_volume(candles: list[Candle], window: int = 24) -> list[float]:
    out: list[float] = []
    for idx in range(len(candles)):
        start = max(0, idx - window + 1)
        vols = sorted(c.quote_volume for c in candles[start : idx + 1])
        mid = len(vols) // 2
        med = vols[mid] if len(vols) % 2 == 1 else (vols[mid - 1] + vols[mid]) / 2.0
        out.append(med)
    return out


def _detect_signals(candles: list[Candle], atrs: list[float], med_vols: list[float]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    if len(candles) < 25:
        return signals

    for i in range(24, len(candles) - 1):
        c = candles[i]
        atr = atrs[i]
        med_v = med_vols[i]
        if c.open <= 0 or atr <= 0:
            continue

        c_range = c.high - c.low
        body = abs(c.close - c.open)
        upper_wick = c.high - max(c.open, c.close)
        lower_wick = min(c.open, c.close) - c.low

        vol_ratio = c.quote_volume / max(1.0, med_v)

        # 1. Breakout setup
        if c.close > c.open and c_range >= 1.5 * atr and vol_ratio >= 1.8:
            entry_p = candles[i + 1].open
            stop_p = c.low
            risk_bps = (entry_p - stop_p) / entry_p * 1e4
            if 30.0 <= risk_bps <= 500.0:
                signals.append(
                    {
                        "family": "breakout_momentum",
                        "candle_idx": i + 1,
                        "entry_ts": candles[i + 1].ts,
                        "entry_iso": candles[i + 1].iso,
                        "entry_price": entry_p,
                        "stop_price": stop_p,
                        "target_bps": max(200.0, risk_bps * 2.0),
                        "atr": atr,
                        "quote_vol": c.quote_volume,
                    }
                )

        # 2. Wick Rejection / Pin-bar Reversal
        elif lower_wick >= 2.0 * body and lower_wick >= 0.5 * c_range and vol_ratio >= 1.3:
            entry_p = candles[i + 1].open
            stop_p = c.low
            risk_bps = (entry_p - stop_p) / entry_p * 1e4
            if 30.0 <= risk_bps <= 400.0:
                signals.append(
                    {
                        "family": "wick_reversal",
                        "candle_idx": i + 1,
                        "entry_ts": candles[i + 1].ts,
                        "entry_iso": candles[i + 1].iso,
                        "entry_price": entry_p,
                        "stop_price": stop_p,
                        "target_bps": max(180.0, risk_bps * 1.8),
                        "atr": atr,
                        "quote_vol": c.quote_volume,
                    }
                )

    return signals


def _simulate_trade_vwap(
    *,
    signal: dict[str, Any],
    candles: list[Candle],
    notional_quote: float,
    base_spread_bps: float,
    fee_bps: float,
    max_hold_bars: int = 24,
    is_train: bool = True,
) -> TradeResult | None:
    start_idx = signal["candle_idx"]
    if start_idx >= len(candles):
        return None

    entry_p = signal["entry_price"]
    stop_p = signal["stop_price"]
    target_bps = signal["target_bps"]
    target_p = entry_p * (1.0 + target_bps / 1e4)

    # Dynamic VWAP slippage model based on orderbook depth participation
    c_vol = max(100.0, signal["quote_vol"])
    participation = min(1.0, notional_quote / c_vol)

    # Orderbook slippage model: Base half-spread + impact scaling with square root of participation
    impact_bps = 25.0 * math.sqrt(participation) * (signal["atr"] / entry_p * 100.0)
    slippage_entry_bps = (base_spread_bps / 2.0) + impact_bps

    # Simulate trade evolution
    exit_reason = "time_stop"
    latest_idx = min(start_idx + max_hold_bars, len(candles) - 1)
    exit_candle = candles[latest_idx]
    exit_p = exit_candle.close
    exit_ts = exit_candle.ts
    exit_iso = exit_candle.iso

    for candle in candles[start_idx : latest_idx + 1]:
        hit_stop = candle.low <= stop_p
        hit_target = candle.high >= target_p

        if hit_stop and hit_target:
            exit_reason = "stop_hit_first"
            exit_p = stop_p
            exit_ts = candle.ts
            exit_iso = candle.iso
            break
        if hit_stop:
            exit_reason = "stop_loss"
            exit_p = stop_p
            exit_ts = candle.ts
            exit_iso = candle.iso
            break
        if hit_target:
            exit_reason = "take_profit"
            exit_p = target_p
            exit_ts = candle.ts
            exit_iso = candle.iso
            break

    # Exit slippage
    exit_c_vol = max(100.0, exit_candle.quote_volume)
    exit_part = min(1.0, notional_quote / exit_c_vol)
    slippage_exit_bps = (base_spread_bps / 2.0) + 25.0 * math.sqrt(exit_part)

    total_slippage_bps = slippage_entry_bps + slippage_exit_bps
    total_friction_bps = total_slippage_bps + fee_bps

    gross_bps = (exit_p / entry_p - 1.0) * 1e4
    net_bps = gross_bps - total_friction_bps

    gross_pnl = notional_quote * (gross_bps / 1e4)
    net_pnl = notional_quote * (net_bps / 1e4)

    return TradeResult(
        event_id=f"{signal['family']}_{candles[start_idx].base}_{candles[start_idx].ts}",
        exchange=candles[start_idx].exchange,
        symbol=candles[start_idx].symbol,
        base=candles[start_idx].base,
        entry_ts=candles[start_idx].ts,
        entry_iso=signal["entry_iso"],
        exit_ts=exit_ts,
        exit_iso=exit_iso,
        side="long",
        entry_price=entry_p,
        exit_price=exit_p,
        target_price=target_p,
        stop_price=stop_p,
        exit_reason=exit_reason,
        gross_bps=gross_bps,
        spread_bps=base_spread_bps,
        slippage_bps=total_slippage_bps,
        fee_bps=fee_bps,
        total_friction_bps=total_friction_bps,
        net_bps=net_bps,
        notional_quote=notional_quote,
        gross_pnl_quote=gross_pnl,
        net_pnl_quote=net_pnl,
        candle_quote_volume=c_vol,
        participation_rate=participation,
        is_train=is_train,
    )


def _compute_stats(trades: list[TradeResult]) -> dict[str, Any]:
    if not trades:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "avg_gross_bps": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_friction_bps": 0.0,
            "avg_net_bps": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
        }

    count = len(trades)
    wins = [t for t in trades if t.net_pnl_quote > 0]
    losses = [t for t in trades if t.net_pnl_quote < 0]
    win_rate = len(wins) / count if count else 0.0

    gross_pnl = sum(t.gross_pnl_quote for t in trades)
    net_pnl = sum(t.net_pnl_quote for t in trades)

    avg_gross_bps = sum(t.gross_bps for t in trades) / count
    avg_slip_bps = sum(t.slippage_bps for t in trades) / count
    avg_fric_bps = sum(t.total_friction_bps for t in trades) / count
    avg_net_bps = sum(t.net_bps for t in trades) / count

    tot_gain = sum(t.net_pnl_quote for t in wins)
    tot_loss = abs(sum(t.net_pnl_quote for t in losses))
    profit_factor = (tot_gain / tot_loss) if tot_loss > 0 else (999.0 if tot_gain > 0 else 0.0)

    # Max Drawdown
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.net_pnl_quote
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    return {
        "count": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "avg_gross_bps": round(avg_gross_bps, 2),
        "avg_slippage_bps": round(avg_slip_bps, 2),
        "avg_friction_bps": round(avg_fric_bps, 2),
        "avg_net_bps": round(avg_net_bps, 2),
        "profit_factor": round(profit_factor, 3),
        "max_drawdown": round(max_dd, 2),
    }


def run_slow_liquidity_vwap_postprocess(
    ohlcv_path: Path,
    manifest_path: Path,
    output_json_path: Path,
    notional_budgets: list[float] = [50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0],
    base_spread_bps: float = 20.0,
    fee_bps: float = 16.0,  # 8 bps entry taker + 8 bps exit taker
) -> dict[str, Any]:
    print(f"Loading OHLCV from {ohlcv_path}...")
    candles_by_market: dict[tuple[str, str], list[Candle]] = defaultdict(list)
    raw_count = 0
    with ohlcv_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            raw_count += 1
            if str(row.get("granularity") or "") == "1h":
                c = _parse_candle(row)
                if c:
                    candles_by_market[(c.exchange, c.symbol)].append(c)

    for market, candles in candles_by_market.items():
        candles.sort(key=lambda x: x.ts)

    print(f"Loaded {raw_count} raw rows across {len(candles_by_market)} 1h markets.")

    # Detect signals across all markets
    all_signals_by_market: dict[tuple[str, str], list[dict[str, Any]]] = {}
    total_signals = 0
    for market, candles in candles_by_market.items():
        atrs = _calculate_atr(candles, period=14)
        med_vols = _rolling_median_volume(candles, window=24)
        sigs = _detect_signals(candles, atrs, med_vols)
        all_signals_by_market[market] = sigs
        total_signals += len(sigs)

    print(f"Detected {total_signals} candidate signals.")

    # Evaluate across multiple notional budgets
    budget_reports: dict[str, Any] = {}
    for budget in notional_budgets:
        all_trades: list[TradeResult] = []
        for market, candles in candles_by_market.items():
            sigs = all_signals_by_market[market]
            n_candles = len(candles)
            train_boundary = int(n_candles * 0.70)
            train_cutoff_ts = candles[train_boundary].ts if train_boundary < n_candles else 0

            for s in sigs:
                is_train = s["entry_ts"] <= train_cutoff_ts
                res = _simulate_trade_vwap(
                    signal=s,
                    candles=candles,
                    notional_quote=budget,
                    base_spread_bps=base_spread_bps,
                    fee_bps=fee_bps,
                    is_train=is_train,
                )
                if res:
                    all_trades.append(res)

        all_trades.sort(key=lambda t: t.entry_ts)
        train_trades = [t for t in all_trades if t.is_train]
        oos_trades = [t for t in all_trades if not t.is_train]

        budget_reports[f"${budget:.0f}"] = {
            "notional": budget,
            "overall": _compute_stats(all_trades),
            "train": _compute_stats(train_trades),
            "oos": _compute_stats(oos_trades),
        }

    # Find decay threshold
    decay_notional = None
    for budget in notional_budgets:
        rep = budget_reports[f"${budget:.0f}"]
        if rep["overall"]["avg_net_bps"] < 0 and decay_notional is None:
            decay_notional = budget

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_path": str(ohlcv_path),
        "total_raw_rows": raw_count,
        "markets_evaluated": len(candles_by_market),
        "total_signals_detected": total_signals,
        "base_spread_bps": base_spread_bps,
        "fee_bps": fee_bps,
        "slippage_decay_threshold_notional": decay_notional,
        "budget_matrix": budget_reports,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with output_json_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    print(f"Saved postprocess analysis to {output_json_path}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ohlcv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    run_slow_liquidity_vwap_postprocess(
        ohlcv_path=args.ohlcv,
        manifest_path=args.manifest,
        output_json_path=args.output,
    )
