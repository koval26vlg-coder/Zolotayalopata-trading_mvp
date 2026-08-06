from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slow_liquidity_feature_normalizer import _counter_dict, _parse_candle, load_json, load_jsonl


DEFAULT_NOTIONAL_QUOTE = 100.0


@dataclass(frozen=True)
class ReplayV1Config:
    notional_quote: float = DEFAULT_NOTIONAL_QUOTE
    train_fraction: float = 0.70
    walk_forward_windows: int = 4
    simultaneous_hit_policy: str = "stop_first"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return None if gains == 0 else 999.0
    return gains / losses


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return max_dd


def _summarize(trades: list[dict[str, Any]], *, pnl_key: str = "net_pnl_quote") -> dict[str, Any]:
    values = [_safe_float(trade.get(pnl_key)) for trade in trades]
    bps_key = "net_bps" if pnl_key == "net_pnl_quote" else "stress_net_bps"
    bps_values = [_safe_float(trade.get(bps_key)) for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    total = sum(values)
    count = len(values)
    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / count if count else 0.0,
        "total_net_pnl_quote": total,
        "expectancy_quote": total / count if count else 0.0,
        "avg_net_bps": sum(bps_values) / count if count else 0.0,
        "profit_factor": _profit_factor(values),
        "max_drawdown_quote": _max_drawdown(values),
    }


def _chronological_split(trades: list[dict[str, Any]], fraction: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not trades:
        return [], []
    split = int(math.floor(len(trades) * max(0.0, min(1.0, fraction))))
    if len(trades) > 1:
        split = min(max(split, 1), len(trades) - 1)
    return trades[:split], trades[split:]


def _walk_forward(trades: list[dict[str, Any]], cfg: ReplayV1Config) -> dict[str, Any]:
    if not trades:
        return {
            "accepted": False,
            "windows": [],
            "accepted_windows": 0,
            "accepted_ratio": 0.0,
        }
    windows_count = max(1, cfg.walk_forward_windows)
    size = max(1, math.ceil(len(trades) / windows_count))
    windows: list[dict[str, Any]] = []
    for idx in range(windows_count):
        chunk = trades[idx * size : (idx + 1) * size]
        if not chunk:
            continue
        summary = _summarize(chunk)
        accepted = summary["trades"] > 0 and summary["expectancy_quote"] > 0 and summary["total_net_pnl_quote"] > 0
        windows.append(
            {
                "index": idx,
                "accepted": accepted,
                "start_event_iso": chunk[0].get("entry_iso"),
                "end_event_iso": chunk[-1].get("entry_iso"),
                "summary": summary,
            }
        )
    accepted_windows = sum(1 for item in windows if item["accepted"])
    accepted_ratio = accepted_windows / len(windows) if windows else 0.0
    return {
        "accepted": bool(windows) and accepted_ratio >= 0.60,
        "windows": windows,
        "accepted_windows": accepted_windows,
        "accepted_ratio": accepted_ratio,
    }


def _concentration(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnl_by_base: defaultdict[str, float] = defaultdict(float)
    pnl_by_exchange: defaultdict[str, float] = defaultdict(float)
    for trade in trades:
        pnl = _safe_float(trade.get("net_pnl_quote"))
        pnl_by_base[str(trade.get("base") or "")] += pnl
        pnl_by_exchange[str(trade.get("exchange") or "")] += pnl
    total_abs = sum(abs(value) for value in pnl_by_base.values())
    max_base_share = max((abs(value) / total_abs for value in pnl_by_base.values()), default=1.0) if total_abs else 1.0
    return {
        "net_pnl_by_base": dict(sorted(pnl_by_base.items())),
        "net_pnl_by_exchange": dict(sorted(pnl_by_exchange.items())),
        "max_single_base_net_pnl_abs_share": max_base_share,
    }


def _build_candle_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[Any]]:
    candles_by_market: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in rows:
        if str(row.get("granularity") or "") != "1h":
            continue
        candle = _parse_candle(row)
        if candle:
            candles_by_market[(candle.exchange, candle.symbol)].append(candle)
    for candles in candles_by_market.values():
        candles.sort(key=lambda candle: candle.ts)
    return candles_by_market


def _simulate_trade(
    *,
    event: dict[str, Any],
    candles: list[Any],
    normal_cost_bps: float,
    stress_cost_bps: float,
    max_hold_bars: int,
    notional_quote: float,
) -> dict[str, Any]:
    entry_ts = int(_safe_float(event.get("entry_ts")))
    entry_price = _safe_float(event.get("entry_price"))
    stop_price = _safe_float(event.get("stop_price"))
    target_bps = _safe_float(event.get("target_bps"))
    target_price = entry_price * (1.0 + target_bps / 1e4)
    if entry_ts <= 0 or entry_price <= 0 or stop_price <= 0 or target_price <= entry_price:
        return {**event, "executed": False, "exit_reason": "invalid_event_geometry"}

    start_idx = next((idx for idx, candle in enumerate(candles) if candle.ts >= entry_ts), None)
    if start_idx is None:
        return {**event, "executed": False, "exit_reason": "missing_entry_candle"}

    exit_reason = "time_stop"
    exit_price = candles[min(start_idx + max_hold_bars, len(candles) - 1)].close
    exit_ts = candles[min(start_idx + max_hold_bars, len(candles) - 1)].ts
    exit_iso = candles[min(start_idx + max_hold_bars, len(candles) - 1)].iso
    latest_idx = min(start_idx + max_hold_bars, len(candles) - 1)
    for candle in candles[start_idx : latest_idx + 1]:
        hit_stop = candle.low <= stop_price
        hit_target = candle.high >= target_price
        if hit_stop and hit_target:
            exit_reason = "both_hit_stop_first"
            exit_price = stop_price
            exit_ts = candle.ts
            exit_iso = candle.iso
            break
        if hit_stop:
            exit_reason = "stop"
            exit_price = stop_price
            exit_ts = candle.ts
            exit_iso = candle.iso
            break
        if hit_target:
            exit_reason = "take_profit"
            exit_price = target_price
            exit_ts = candle.ts
            exit_iso = candle.iso
            break

    gross_bps = (exit_price / entry_price - 1.0) * 1e4
    net_bps = gross_bps - normal_cost_bps
    stress_net_bps = gross_bps - stress_cost_bps
    return {
        **event,
        "executed": True,
        "side": "long",
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "exit_ts": exit_ts,
        "exit_iso": exit_iso,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_bps": gross_bps,
        "normal_cost_bps": normal_cost_bps,
        "net_bps": net_bps,
        "net_pnl_quote": notional_quote * net_bps / 1e4,
        "stress_cost_bps": stress_cost_bps,
        "stress_net_bps": stress_net_bps,
        "stress_net_pnl_quote": notional_quote * stress_net_bps / 1e4,
    }


def replay_slow_liquidity_v1_planonly(
    *,
    fixed_v1_path: Path,
    output_path: Path | None = None,
    cfg: ReplayV1Config = ReplayV1Config(),
) -> dict[str, Any]:
    fixed = load_json(fixed_v1_path)
    census_path = Path(str(fixed.get("event_census_path") or ""))
    if not census_path.exists():
        raise ValueError("fixed v1 artifact does not reference an existing event-census artifact")
    census = load_json(census_path)
    history_path = Path(str((census.get("inputs") or {}).get("history_jsonl_path") or ""))
    manifest_path = Path(str((census.get("inputs") or {}).get("history_manifest_path") or ""))
    if not history_path.exists() or not manifest_path.exists():
        raise ValueError("event-census artifact does not reference existing history jsonl/manifest")
    history_rows = load_jsonl(history_path)
    manifest = load_json(manifest_path)
    candles_by_market = _build_candle_index(history_rows)
    signal = fixed.get("fixed_signal_v1") or {}
    family = str(signal.get("family") or "")
    events = [
        event
        for event in ((census.get("event_census") or {}).get("normalized_events") or [])
        if str(event.get("family") or "") == family
    ]
    events.sort(key=lambda event: (int(_safe_float(event.get("entry_ts"))), str(event.get("base")), str(event.get("exchange"))))
    cost_model = fixed.get("cost_model") or {}
    normal_cost_bps = _safe_float(cost_model.get("normal_total_cost_bps"), 120.0)
    stress_cost_bps = _safe_float(cost_model.get("stress_total_cost_bps"), 245.0)
    max_hold_bars = int((signal.get("max_hold_bars") or 72))
    results: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for event in events:
        key = (str(event.get("exchange") or ""), str(event.get("symbol") or ""))
        candles = candles_by_market.get(key, [])
        if not candles:
            skipped["missing_market_candles"] += 1
            results.append({**event, "executed": False, "exit_reason": "missing_market_candles"})
            continue
        trade = _simulate_trade(
            event=event,
            candles=candles,
            normal_cost_bps=normal_cost_bps,
            stress_cost_bps=stress_cost_bps,
            max_hold_bars=max_hold_bars,
            notional_quote=cfg.notional_quote,
        )
        if not trade.get("executed"):
            skipped[str(trade.get("exit_reason") or "not_executed")] += 1
        results.append(trade)

    trades = [trade for trade in results if bool(trade.get("executed"))]
    train, oos = _chronological_split(trades, cfg.train_fraction)
    summary = _summarize(trades)
    train_summary = _summarize(train)
    oos_summary = _summarize(oos)
    stress_summary = _summarize(trades, pnl_key="stress_net_pnl_quote")
    walk_forward = _walk_forward(trades, cfg)
    concentration = _concentration(trades)
    exit_counts = Counter(str(trade.get("exit_reason")) for trade in trades)
    base_counts = Counter(str(trade.get("base")) for trade in trades)
    exchange_counts = Counter(str(trade.get("exchange")) for trade in trades)
    validation = fixed.get("validation_contract") or {}
    min_trades = int(validation.get("min_trades") or 100)
    min_oos_trades = int(validation.get("min_oos_trades") or 20)
    min_bases = int(validation.get("min_event_bases") or 8)
    min_exchanges = int(validation.get("min_event_exchanges") or 2)
    max_base_share = _safe_float(validation.get("max_single_base_net_pnl_share"), 0.25)
    min_pf = _safe_float(validation.get("min_profit_factor"), 1.2)
    min_wf = _safe_float(validation.get("min_walk_forward_positive_ratio"), 0.60)

    reasons: list[str] = []
    if summary["trades"] < min_trades:
        reasons.append("min_trades")
    if oos_summary["trades"] < min_oos_trades:
        reasons.append("min_oos_trades")
    if len(base_counts) < min_bases:
        reasons.append("min_event_bases")
    if len(exchange_counts) < min_exchanges:
        reasons.append("min_event_exchanges")
    if concentration["max_single_base_net_pnl_abs_share"] > max_base_share:
        reasons.append("max_single_base_net_pnl_share")
    if summary["expectancy_quote"] <= 0 or summary["total_net_pnl_quote"] <= 0:
        reasons.append("all_events_net_expectancy")
    if oos_summary["expectancy_quote"] <= 0 or oos_summary["total_net_pnl_quote"] <= 0:
        reasons.append("oos_net_expectancy")
    if oos_summary["profit_factor"] is None or float(oos_summary["profit_factor"]) < min_pf:
        reasons.append("oos_profit_factor")
    if float(walk_forward["accepted_ratio"]) < min_wf:
        reasons.append("walk_forward_positive_ratio")
    if stress_summary["expectancy_quote"] < 0 or stress_summary["total_net_pnl_quote"] < 0:
        reasons.append("stress_net_expectancy")

    candidate = not reasons
    decision = (
        "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW"
        if candidate
        else "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE"
    )
    result: dict[str, Any] = {
        "mode": "slow_liquidity_fixed_v1_replay_planonly",
        "generated_at": utc_now_iso(),
        "decision": decision,
        "research_only": True,
        "strategy_accepted": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "collect_allowed_now": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "fixed_v1_path": str(fixed_v1_path),
        "event_census_path": str(census_path),
        "history_jsonl_path": str(history_path),
        "history_manifest_path": str(manifest_path),
        "history_manifest": {
            "run_id": manifest.get("run_id"),
            "final": bool(manifest.get("final")),
            "rows": int(manifest.get("rows") or 0),
            "ohlcv_rows": int(manifest.get("ohlcv_rows") or 0),
            "errors": int(manifest.get("errors") or 0),
        },
        "strategy_config": {
            "signal": signal,
            "cost_model": cost_model,
            "replay": asdict(cfg),
            "simultaneous_hit_policy": cfg.simultaneous_hit_policy,
        },
        "coverage": {
            "family": family,
            "events_from_census": len(events),
            "executed_trades": len(trades),
            "skipped": _counter_dict(skipped),
            "trades_by_base": _counter_dict(base_counts),
            "trades_by_exchange": _counter_dict(exchange_counts),
            "exit_counts": _counter_dict(exit_counts),
        },
        "summary": summary,
        "train": {"fraction": cfg.train_fraction, "summary": train_summary},
        "oos": {"fraction": 1.0 - cfg.train_fraction, "summary": oos_summary},
        "walk_forward": walk_forward,
        "stress": {
            "cost_bps": stress_cost_bps,
            "summary": stress_summary,
        },
        "concentration": concentration,
        "research_acceptance": {
            "robust_candidate": candidate,
            "reasons": reasons,
            "acceptance_requires_before_paper_forward": [
                "independent review of this fixed replay artifact",
                "no parameter changes after seeing replay",
                "separate paper-forward plan if independent review accepts",
                "execution/fill/liquidity validation before any live discussion",
            ],
        },
        "events": results,
        "trades": trades,
        "next_valid_moves": (
            [
                "Send this fixed replay artifact to independent review; do not start paper-forward yet.",
                "If review accepts, build a visible paper-forward plan with no live orders/API keys.",
            ]
            if candidate
            else [
                "Reject this fixed slow-liquidity v1 branch on current evidence.",
                "Select a different structural branch PlanOnly or define a new event family before any new collection.",
            ]
        ),
        "output_path": str(output_path) if output_path else "",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NoGrid replay-validation PlanOnly for fixed slow-liquidity v1 contract.")
    parser.add_argument("--fixed-v1", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--notional-quote", type=float, default=DEFAULT_NOTIONAL_QUOTE)
    parser.add_argument("--train-fraction", type=float, default=ReplayV1Config.train_fraction)
    parser.add_argument("--walk-forward-windows", type=int, default=ReplayV1Config.walk_forward_windows)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = ReplayV1Config(
        notional_quote=args.notional_quote,
        train_fraction=args.train_fraction,
        walk_forward_windows=args.walk_forward_windows,
    )
    result = replay_slow_liquidity_v1_planonly(
        fixed_v1_path=Path(args.fixed_v1),
        output_path=Path(args.output),
        cfg=cfg,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
