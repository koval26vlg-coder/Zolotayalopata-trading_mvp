from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_NOTIONAL_QUOTE = 100.0
DEFAULT_ENTRY_DELAY_HOURS = 6.0
DEFAULT_HOLD_HOURS = 24.0
DEFAULT_TRIGGER_BPS = 200.0
DEFAULT_FEE_BPS_PER_SIDE = 10.0
DEFAULT_SLIPPAGE_BPS_PER_SIDE = 5.0
DEFAULT_STRESS_FEE_MULTIPLIER = 1.5
DEFAULT_STRESS_SLIPPAGE_MULTIPLIER = 2.0
DEFAULT_STRESS_HAIRCUT_BPS = 50.0
DEFAULT_MIN_TRADES = 10
DEFAULT_MIN_OOS_TRADES = 3
DEFAULT_MIN_PROFIT_FACTOR = 1.2
DEFAULT_MIN_WALK_FORWARD_PASS_RATIO = 0.60
DEFAULT_WALK_FORWARD_WINDOWS = 4
DEFAULT_TRAIN_FRACTION = 0.70


@dataclass(frozen=True)
class ReplayConfig:
    notional_quote: float = DEFAULT_NOTIONAL_QUOTE
    entry_delay_hours: float = DEFAULT_ENTRY_DELAY_HOURS
    hold_hours: float = DEFAULT_HOLD_HOURS
    trigger_bps: float = DEFAULT_TRIGGER_BPS
    fee_bps_per_side: float = DEFAULT_FEE_BPS_PER_SIDE
    slippage_bps_per_side: float = DEFAULT_SLIPPAGE_BPS_PER_SIDE
    stress_fee_multiplier: float = DEFAULT_STRESS_FEE_MULTIPLIER
    stress_slippage_multiplier: float = DEFAULT_STRESS_SLIPPAGE_MULTIPLIER
    stress_haircut_bps: float = DEFAULT_STRESS_HAIRCUT_BPS
    min_trades: int = DEFAULT_MIN_TRADES
    min_oos_trades: int = DEFAULT_MIN_OOS_TRADES
    min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR
    min_walk_forward_pass_ratio: float = DEFAULT_MIN_WALK_FORWARD_PASS_RATIO
    walk_forward_windows: int = DEFAULT_WALK_FORWARD_WINDOWS
    train_fraction: float = DEFAULT_TRAIN_FRACTION


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _profit_factor(net_values: list[float]) -> float | None:
    gains = sum(value for value in net_values if value > 0)
    losses = abs(sum(value for value in net_values if value < 0))
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


def summarize_trades(trades: list[dict[str, Any]], *, net_key: str = "net_pnl_quote") -> dict[str, Any]:
    net_values = [_float(trade.get(net_key)) for trade in trades]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    total = sum(net_values)
    count = len(net_values)
    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / count) if count else 0.0,
        "total_net_pnl_quote": total,
        "expectancy_quote": (total / count) if count else 0.0,
        "avg_net_bps": (sum(_float(trade.get("net_bps")) for trade in trades) / count) if count else 0.0,
        "profit_factor": _profit_factor(net_values),
        "max_drawdown_quote": _max_drawdown(net_values),
    }


def _chronological_split(trades: list[dict[str, Any]], fraction: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not trades:
        return [], []
    split = int(len(trades) * max(0.0, min(1.0, fraction)))
    split = min(max(split, 1), len(trades) - 1) if len(trades) > 1 else len(trades)
    return trades[:split], trades[split:]


def _walk_forward(trades: list[dict[str, Any]], cfg: ReplayConfig) -> dict[str, Any]:
    if not trades:
        return {
            "accepted": False,
            "windows": [],
            "accepted_windows": 0,
            "accepted_ratio": 0.0,
            "min_pass_ratio": cfg.min_walk_forward_pass_ratio,
        }
    windows_count = max(1, cfg.walk_forward_windows)
    size = max(1, (len(trades) + windows_count - 1) // windows_count)
    windows: list[dict[str, Any]] = []
    for index in range(windows_count):
        chunk = trades[index * size : (index + 1) * size]
        if not chunk:
            continue
        summary = summarize_trades(chunk)
        accepted = summary["trades"] > 0 and summary["expectancy_quote"] > 0 and summary["total_net_pnl_quote"] > 0
        windows.append(
            {
                "index": index,
                "accepted": accepted,
                "start_event_iso": chunk[0].get("event_iso"),
                "end_event_iso": chunk[-1].get("event_iso"),
                "summary": summary,
            }
        )
    accepted_windows = sum(1 for window in windows if window["accepted"])
    accepted_ratio = accepted_windows / len(windows) if windows else 0.0
    return {
        "accepted": bool(windows) and accepted_ratio >= cfg.min_walk_forward_pass_ratio,
        "windows": windows,
        "accepted_windows": accepted_windows,
        "accepted_ratio": accepted_ratio,
        "min_pass_ratio": cfg.min_walk_forward_pass_ratio,
    }


def _first_candle_at_or_after(candles: list[dict[str, Any]], target_ts: float) -> dict[str, Any] | None:
    for candle in candles:
        if _float(candle.get("candle_ts")) >= target_ts:
            return candle
    return None


def _group_ok_candles(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("data_status") or "").lower() != "ok":
            continue
        event_id = str(row.get("event_id") or "")
        if not event_id:
            continue
        grouped.setdefault(event_id, []).append(row)
    for event_id in list(grouped):
        grouped[event_id].sort(key=lambda item: _float(item.get("candle_ts")))
    return grouped


def _event_meta_from_rows(candles_by_event: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event_id, candles in candles_by_event.items():
        if not candles:
            continue
        first = candles[0]
        events.append(
            {
                "event_id": event_id,
                "exchange": first.get("exchange"),
                "symbol": first.get("symbol"),
                "base": first.get("base"),
                "quote": first.get("quote"),
                "event_ts": _float(first.get("event_ts")),
                "event_iso": first.get("event_iso"),
                "rows": len(candles),
            }
        )
    return sorted(events, key=lambda item: (_float(item.get("event_ts")), str(item.get("exchange")), str(item.get("symbol"))))


def _build_trade(event: dict[str, Any], candles: list[dict[str, Any]], cfg: ReplayConfig) -> dict[str, Any]:
    event_ts = _float(event.get("event_ts"))
    first = _first_candle_at_or_after(candles, event_ts)
    entry_target = event_ts + cfg.entry_delay_hours * 3600.0
    entry = _first_candle_at_or_after(candles, entry_target)
    exit_target = entry_target + cfg.hold_hours * 3600.0
    exit_candle = _first_candle_at_or_after(candles, exit_target)
    if first is None or entry is None or exit_candle is None:
        return {**event, "signal": "missing_candles", "executed": False}

    first_close = _float(first.get("close"))
    entry_close = _float(entry.get("close"))
    exit_close = _float(exit_candle.get("close"))
    if first_close <= 0 or entry_close <= 0 or exit_close <= 0:
        return {**event, "signal": "invalid_price", "executed": False}

    initial_return_bps = ((entry_close / first_close) - 1.0) * 10000.0
    if initial_return_bps <= -cfg.trigger_bps:
        signal = "long_after_initial_selloff"
        executed = True
    elif initial_return_bps >= cfg.trigger_bps:
        signal = "blocked_short_after_initial_pump"
        executed = False
    else:
        signal = "no_signal"
        executed = False

    gross_bps = ((exit_close / entry_close) - 1.0) * 10000.0
    cost_bps = 2.0 * (cfg.fee_bps_per_side + cfg.slippage_bps_per_side)
    net_bps = gross_bps - cost_bps
    stress_cost_bps = 2.0 * (
        cfg.fee_bps_per_side * cfg.stress_fee_multiplier
        + cfg.slippage_bps_per_side * cfg.stress_slippage_multiplier
    ) + cfg.stress_haircut_bps
    stress_net_bps = gross_bps - stress_cost_bps
    return {
        **event,
        "signal": signal,
        "executed": executed,
        "side": "long" if executed else None,
        "first_candle_ts": first.get("candle_ts"),
        "entry_candle_ts": entry.get("candle_ts"),
        "exit_candle_ts": exit_candle.get("candle_ts"),
        "first_close": first_close,
        "entry_close": entry_close,
        "exit_close": exit_close,
        "initial_return_bps": initial_return_bps,
        "gross_bps": gross_bps,
        "cost_bps": cost_bps,
        "net_bps": net_bps,
        "net_pnl_quote": cfg.notional_quote * net_bps / 10000.0,
        "stress_cost_bps": stress_cost_bps,
        "stress_net_bps": stress_net_bps,
        "stress_net_pnl_quote": cfg.notional_quote * stress_net_bps / 10000.0,
    }


def replay_listing_event_drift_reversal(
    *,
    normalizer_path: Path,
    output_path: Path | None = None,
    cfg: ReplayConfig = ReplayConfig(),
) -> dict[str, Any]:
    normalizer = load_json(normalizer_path)
    history = normalizer.get("history_data") or {}
    history_jsonl = Path(str(history.get("jsonl_path") or ""))
    history_manifest = Path(str(history.get("manifest_path") or ""))
    if not history_jsonl.exists() or not history_manifest.exists():
        raise ValueError("normalizer artifact does not reference existing listing history jsonl/manifest")
    rows = load_jsonl(history_jsonl)
    manifest = load_json(history_manifest)
    candles_by_event = _group_ok_candles(rows)
    events = _event_meta_from_rows(candles_by_event)
    event_results = [_build_trade(event, candles_by_event[event["event_id"]], cfg) for event in events]
    trades = [event for event in event_results if event.get("executed")]
    trades.sort(key=lambda item: (_float(item.get("event_ts")), str(item.get("exchange")), str(item.get("symbol"))))
    train, test = _chronological_split(trades, cfg.train_fraction)
    summary = summarize_trades(trades)
    train_summary = summarize_trades(train)
    test_summary = summarize_trades(test)
    stress_summary = summarize_trades(trades, net_key="stress_net_pnl_quote")
    walk_forward = _walk_forward(trades, cfg)
    signal_counts = Counter(str(event.get("signal")) for event in event_results)
    exchange_counts = Counter(str(trade.get("exchange")) for trade in trades)

    reasons: list[str] = []
    if summary["trades"] < cfg.min_trades:
        reasons.append("min_trades_not_met")
    if summary["expectancy_quote"] <= 0 or summary["total_net_pnl_quote"] <= 0:
        reasons.append("net_expectancy_not_positive")
    if summary["profit_factor"] is None or float(summary["profit_factor"]) < cfg.min_profit_factor:
        reasons.append("profit_factor_below_threshold")
    if test_summary["trades"] < cfg.min_oos_trades:
        reasons.append("oos_min_trades_not_met")
    if test_summary["expectancy_quote"] <= 0 or test_summary["total_net_pnl_quote"] <= 0:
        reasons.append("oos_net_expectancy_not_positive")
    if not walk_forward["accepted"]:
        reasons.append("walk_forward_rejected")
    if stress_summary["expectancy_quote"] <= 0 or stress_summary["total_net_pnl_quote"] <= 0:
        reasons.append("stress_net_expectancy_not_positive")

    robust_candidate = not reasons
    if summary["trades"] < cfg.min_trades:
        decision = "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_INSUFFICIENT_TRADES"
    elif robust_candidate:
        decision = "LISTING_EVENT_REPLAY_PLANONLY_CANDIDATE_REQUIRES_INDEPENDENT_VALIDATION"
    else:
        decision = "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE"

    result: dict[str, Any] = {
        "mode": "listing_event_drift_reversal_replay_planonly",
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
        "normalizer_path": str(normalizer_path),
        "history_jsonl_path": str(history_jsonl),
        "history_manifest_path": str(history_manifest),
        "history_manifest": {
            "run_id": manifest.get("run_id"),
            "final": bool(manifest.get("final")),
            "ohlcv_rows": int(manifest.get("ohlcv_rows") or 0),
            "placeholder_rows": int(manifest.get("placeholder_rows") or 0),
            "errors": int(manifest.get("errors") or 0),
        },
        "strategy_config": cfg.__dict__,
        "signal_policy": {
            "name": "listing_event_drift_reversal",
            "spot_execution": "long_only",
            "entry_rule": "enter long after initial selloff crosses trigger_bps",
            "blocked_rule": "initial pump reversal would require short/margin and is counted but not traded",
            "exit_rule": "exit after fixed hold_hours",
        },
        "coverage": {
            "events": len(events),
            "rows": len(rows),
            "executed_trades": len(trades),
            "signal_counts": dict(signal_counts),
            "executed_trades_by_exchange": dict(exchange_counts),
        },
        "summary": summary,
        "train": {"fraction": cfg.train_fraction, "summary": train_summary},
        "oos": {"fraction": 1.0 - cfg.train_fraction, "summary": test_summary},
        "walk_forward": walk_forward,
        "stress": {
            "fee_multiplier": cfg.stress_fee_multiplier,
            "slippage_multiplier": cfg.stress_slippage_multiplier,
            "haircut_bps": cfg.stress_haircut_bps,
            "summary": stress_summary,
        },
        "research_acceptance": {
            "robust_candidate": robust_candidate,
            "reasons": reasons,
            "acceptance_requires_before_paper_forward": [
                "independent event sample or longer listing history",
                "positive net expectancy after base fees/slippage/spread buffers",
                "chronological OOS with enough trades",
                "walk-forward stability",
                "stress pass under wider costs and delist/freeze haircut",
            ],
        },
        "events": event_results,
        "trades": trades,
        "next_valid_moves": (
            [
                "Build independent validation/OOS packet for this fixed config; no grid/live/API/paper-forward.",
                "Do not claim a working edge until independent validation and paper-forward gates pass.",
            ]
            if robust_candidate
            else [
                "Reject this fixed listing-event drift-reversal setup on the current sample.",
                "Either define a new non-HFT branch or collect a larger independent listing-event sample before retesting.",
            ]
        ),
        "output_path": str(output_path) if output_path else "",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def default_output_path(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return root / "exports" / "trading-mvp" / "backtests" / f"listing_event_replay_planonly_{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only listing-event drift/reversal replay PlanOnly.")
    parser.add_argument("--normalizer", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--notional-quote", type=float, default=DEFAULT_NOTIONAL_QUOTE)
    parser.add_argument("--entry-delay-hours", type=float, default=DEFAULT_ENTRY_DELAY_HOURS)
    parser.add_argument("--hold-hours", type=float, default=DEFAULT_HOLD_HOURS)
    parser.add_argument("--trigger-bps", type=float, default=DEFAULT_TRIGGER_BPS)
    parser.add_argument("--fee-bps-per-side", type=float, default=DEFAULT_FEE_BPS_PER_SIDE)
    parser.add_argument("--slippage-bps-per-side", type=float, default=DEFAULT_SLIPPAGE_BPS_PER_SIDE)
    parser.add_argument("--stress-fee-multiplier", type=float, default=DEFAULT_STRESS_FEE_MULTIPLIER)
    parser.add_argument("--stress-slippage-multiplier", type=float, default=DEFAULT_STRESS_SLIPPAGE_MULTIPLIER)
    parser.add_argument("--stress-haircut-bps", type=float, default=DEFAULT_STRESS_HAIRCUT_BPS)
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--min-oos-trades", type=int, default=DEFAULT_MIN_OOS_TRADES)
    parser.add_argument("--min-profit-factor", type=float, default=DEFAULT_MIN_PROFIT_FACTOR)
    parser.add_argument("--min-walk-forward-pass-ratio", type=float, default=DEFAULT_MIN_WALK_FORWARD_PASS_RATIO)
    parser.add_argument("--walk-forward-windows", type=int, default=DEFAULT_WALK_FORWARD_WINDOWS)
    parser.add_argument("--train-fraction", type=float, default=DEFAULT_TRAIN_FRACTION)
    args = parser.parse_args(argv)

    root = Path.cwd()
    output = Path(args.output) if args.output else default_output_path(root)
    cfg = ReplayConfig(
        notional_quote=args.notional_quote,
        entry_delay_hours=args.entry_delay_hours,
        hold_hours=args.hold_hours,
        trigger_bps=args.trigger_bps,
        fee_bps_per_side=args.fee_bps_per_side,
        slippage_bps_per_side=args.slippage_bps_per_side,
        stress_fee_multiplier=args.stress_fee_multiplier,
        stress_slippage_multiplier=args.stress_slippage_multiplier,
        stress_haircut_bps=args.stress_haircut_bps,
        min_trades=args.min_trades,
        min_oos_trades=args.min_oos_trades,
        min_profit_factor=args.min_profit_factor,
        min_walk_forward_pass_ratio=args.min_walk_forward_pass_ratio,
        walk_forward_windows=args.walk_forward_windows,
        train_fraction=args.train_fraction,
    )
    result = replay_listing_event_drift_reversal(
        normalizer_path=Path(args.normalizer),
        output_path=output,
        cfg=cfg,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
