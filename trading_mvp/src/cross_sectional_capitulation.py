from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLAN_SCHEMA = "cross_sectional_capitulation_plan_v1"
REPORT_SCHEMA = "cross_sectional_capitulation_report_v1"


@dataclass(frozen=True)
class Bar:
    base: str
    ts: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _parse_ts(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).timestamp())


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"plan schema mismatch: {plan.get('schema')!r}")
    if plan.get("research_only") is not True or plan.get("fixed_parameters_no_grid") is not True:
        raise ValueError("plan must be research-only with fixed_parameters_no_grid=true")
    if plan.get("strategy_accepted") is not False:
        raise ValueError("sealed plan must remain unaccepted")
    data = plan.get("data")
    signal = plan.get("signal")
    execution = plan.get("execution")
    validation = plan.get("validation")
    if not all(isinstance(value, dict) for value in (data, signal, execution, validation)):
        raise ValueError("plan data/signal/execution/validation sections are required")
    if data.get("exchange") != "gateio" or data.get("instrument") != "spot" or data.get("timeframe") != "4h":
        raise ValueError("v1 supports only Gate spot 4h history")
    if signal.get("direction") != "long_only_spot":
        raise ValueError("v1 supports only long_only_spot")
    if signal.get("same_timestamp_priority") != "most_negative_residual_first":
        raise ValueError("unsupported candidate priority")
    for name in (
        "lookback_bars",
        "min_peer_count",
        "volume_lookback_bars",
        "hold_bars",
        "cooldown_bars",
        "max_concurrent_positions",
    ):
        if int(signal.get(name, 0)) <= 0:
            raise ValueError(f"invalid signal.{name}")
    for name in (
        "min_current_quote_volume",
        "min_trailing_median_quote_volume",
        "min_volume_ratio",
        "close_location_min",
    ):
        value = float(signal.get(name, 0))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid signal.{name}")
    if not -10000 < float(signal.get("base_return_max_bps", 0)) < 0:
        raise ValueError("base_return_max_bps must be negative")
    if not -10000 < float(signal.get("residual_vs_peer_median_max_bps", 0)) < 0:
        raise ValueError("residual_vs_peer_median_max_bps must be negative")
    normal_cost = float(execution.get("normal_round_trip_fee_bps", 0)) + float(
        execution.get("normal_spread_slippage_buffer_bps", 0)
    )
    if not math.isclose(normal_cost, float(execution.get("normal_total_cost_bps", -1)), abs_tol=1e-9):
        raise ValueError("normal_total_cost_bps does not equal fee plus execution buffer")
    if float(execution.get("stress_total_cost_bps", 0)) <= normal_cost:
        raise ValueError("stress_total_cost_bps must exceed normal cost")
    if float(execution.get("notional_quote", 0)) <= 0:
        raise ValueError("notional_quote must be positive")
    train_fraction = float(validation.get("train_fraction", 0))
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between zero and one")


def load_plan(path: str | Path, expected_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    plan_path = Path(path)
    observed = _sha256(plan_path)
    if expected_sha256 and observed.lower() != expected_sha256.lower():
        raise ValueError(f"plan sha256 mismatch: expected={expected_sha256}, observed={observed}")
    plan = _load_json(plan_path)
    validate_plan(plan)
    return plan, observed


def _verify_evidence(plan: dict[str, Any]) -> dict[str, Any]:
    data = plan["data"]
    results: dict[str, Any] = {}
    for prefix, path_name, hash_name in (
        ("history", "history_jsonl_path", "history_jsonl_sha256"),
        ("history_manifest", "history_manifest_path", "history_manifest_sha256"),
        ("universe", "universe_path", "universe_sha256"),
    ):
        path = Path(str(data[path_name]))
        if not path.is_file():
            raise FileNotFoundError(f"sealed evidence missing: {path}")
        observed = _sha256(path)
        expected = str(data[hash_name]).lower()
        if observed.lower() != expected:
            raise ValueError(f"{prefix} sha256 mismatch: expected={expected}, observed={observed}")
        results[prefix] = {"path": str(path), "sha256": observed, "size_bytes": path.stat().st_size}
    manifest = _load_json(Path(str(data["history_manifest_path"])))
    if manifest.get("final") is not True or int(manifest.get("errors", 1)) < 0:
        raise ValueError("history manifest is not final or has invalid error count")
    return results


def _load_universe(path: Path, max_rank: int) -> tuple[set[str], dict[str, Any]]:
    selected: set[str] = set()
    raw_rows = 0
    duplicate_symbols = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            raw_rows += 1
            try:
                rank = int(row.get("rank") or 0)
            except ValueError:
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or rank <= 0 or rank > max_rank:
                continue
            if symbol in selected:
                duplicate_symbols += 1
            selected.add(symbol)
    if not selected:
        raise ValueError("sealed non-Binance universe selected no symbols")
    return selected, {
        "raw_rows": raw_rows,
        "max_rank": max_rank,
        "selected_unique_bases": len(selected),
        "duplicate_symbols_within_rank": duplicate_symbols,
        "bases": sorted(selected),
    }


def _bar_from_row(row: dict[str, Any]) -> Bar | None:
    try:
        base = str(row["base"]).strip().upper()
        values = [float(row[name]) for name in ("open", "high", "low", "close", "quote_volume")]
        ts = int(row["candle_ts"])
    except (KeyError, TypeError, ValueError):
        return None
    if not base or not all(math.isfinite(value) for value in values):
        return None
    open_price, high, low, close, quote_volume = values
    if min(open_price, high, low, close) <= 0 or high < max(open_price, close, low) or low > min(open_price, close, high):
        return None
    if quote_volume < 0:
        return None
    return Bar(base, ts, open_price, high, low, close, quote_volume)


def _load_history(path: Path, universe: set[str], plan: dict[str, Any]) -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    data = plan["data"]
    exchange = str(data["exchange"])
    timeframe = str(data["timeframe"])
    required_status = str(data["require_source_status"])
    bars: dict[str, list[Bar]] = defaultdict(list)
    requested_bases: set[str] = set()
    ok_bases: set[str] = set()
    total_rows = 0
    slot_rows = 0
    api_error_rows = 0
    invalid_rows = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            total_rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid_rows += 1
                continue
            base = str(row.get("base") or "").strip().upper()
            if base not in universe or row.get("exchange") != exchange or row.get("granularity") != timeframe:
                continue
            slot_rows += 1
            requested_bases.add(base)
            if row.get("data_status") != required_status:
                api_error_rows += 1
                continue
            bar = _bar_from_row(row)
            if bar is None:
                invalid_rows += 1
                continue
            bars[base].append(bar)
            ok_bases.add(base)

    duplicate_bars = 0
    out_of_order_bases: list[str] = []
    gap_count = 0
    bar_sec = int(data["bar_sec"])
    for base, rows in bars.items():
        original_ts = [bar.ts for bar in rows]
        if any(right < left for left, right in zip(original_ts, original_ts[1:])):
            out_of_order_bases.append(base)
        rows.sort(key=lambda bar: bar.ts)
        deduped: list[Bar] = []
        for bar in rows:
            if deduped and bar.ts == deduped[-1].ts:
                duplicate_bars += 1
                continue
            if deduped and bar.ts - deduped[-1].ts != bar_sec:
                gap_count += 1
            deduped.append(bar)
        bars[base] = deduped
    return dict(bars), {
        "total_source_rows": total_rows,
        "selected_slot_rows": slot_rows,
        "requested_bases": sorted(requested_bases),
        "requested_base_count": len(requested_bases),
        "ok_bases": sorted(ok_bases),
        "ok_base_count": len(ok_bases),
        "api_error_rows": api_error_rows,
        "invalid_rows": invalid_rows,
        "duplicate_bars": duplicate_bars,
        "out_of_order_bases_before_sort": sorted(out_of_order_bases),
        "gap_count": gap_count,
        "bars_by_base": {base: len(rows) for base, rows in sorted(bars.items())},
    }


def _is_contiguous(rows: list[Bar], start: int, end: int, bar_sec: int) -> bool:
    if start < 0 or end >= len(rows) or start > end:
        return False
    return all(rows[index].ts - rows[index - 1].ts == bar_sec for index in range(start + 1, end + 1))


def _build_candidates(bars_by_base: dict[str, list[Bar]], plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    data = plan["data"]
    signal = plan["signal"]
    bar_sec = int(data["bar_sec"])
    lookback = int(signal["lookback_bars"])
    volume_lookback = int(signal["volume_lookback_bars"])
    hold = int(signal["hold_bars"])
    analysis_start = _parse_ts(data["analysis_start"])
    returns_by_ts: dict[int, dict[str, float]] = defaultdict(dict)
    index_by_base_ts: dict[tuple[str, int], int] = {}

    for base, rows in bars_by_base.items():
        for index, bar in enumerate(rows):
            index_by_base_ts[(base, bar.ts)] = index
            if index < lookback or not _is_contiguous(rows, index - lookback, index, bar_sec):
                continue
            returns_by_ts[bar.ts][base] = (bar.close / rows[index - lookback].close - 1.0) * 10000.0

    counters: dict[str, int] = defaultdict(int)
    candidates: list[dict[str, Any]] = []
    for ts in sorted(returns_by_ts):
        if ts < analysis_start:
            continue
        returns = returns_by_ts[ts]
        for base, base_return in returns.items():
            counters["return_observations"] += 1
            peers = [value for peer, value in returns.items() if peer != base]
            if len(peers) < int(signal["min_peer_count"]):
                counters["peer_count"] += 1
                continue
            peer_median = statistics.median(peers)
            residual = base_return - peer_median
            if base_return > float(signal["base_return_max_bps"]):
                counters["base_return"] += 1
                continue
            if residual > float(signal["residual_vs_peer_median_max_bps"]):
                counters["residual"] += 1
                continue
            rows = bars_by_base[base]
            index = index_by_base_ts[(base, ts)]
            history_start = index - volume_lookback
            if not _is_contiguous(rows, history_start, index, bar_sec):
                counters["volume_history"] += 1
                continue
            trailing_volume = statistics.median(bar.quote_volume for bar in rows[history_start:index])
            current = rows[index]
            if current.quote_volume < float(signal["min_current_quote_volume"]):
                counters["current_quote_volume"] += 1
                continue
            if trailing_volume < float(signal["min_trailing_median_quote_volume"]):
                counters["trailing_quote_volume"] += 1
                continue
            volume_ratio = current.quote_volume / trailing_volume if trailing_volume > 0 else math.inf
            if volume_ratio < float(signal["min_volume_ratio"]):
                counters["volume_ratio"] += 1
                continue
            candle_range = current.high - current.low
            close_location = (current.close - current.low) / candle_range if candle_range > 0 else 0.0
            if close_location < float(signal["close_location_min"]):
                counters["close_location"] += 1
                continue
            exit_index = index + hold
            if not _is_contiguous(rows, index, exit_index, bar_sec):
                counters["missing_execution_bars"] += 1
                continue
            entry_bar = rows[index + 1]
            exit_bar = rows[exit_index]
            candidates.append(
                {
                    "base": base,
                    # The candle timestamp is its open; the signal becomes
                    # observable only when that 4h candle closes.
                    "signal_ts": ts + bar_sec,
                    "entry_ts": entry_bar.ts,
                    "exit_ts": exit_bar.ts + bar_sec,
                    "entry_price": entry_bar.open,
                    "exit_price": exit_bar.close,
                    "base_return_bps": base_return,
                    "peer_median_return_bps": peer_median,
                    "residual_bps": residual,
                    "close_location": close_location,
                    "current_quote_volume": current.quote_volume,
                    "trailing_median_quote_volume": trailing_volume,
                    "volume_ratio": volume_ratio,
                    "peer_count": len(peers),
                }
            )
            counters["fixed_signal_candidates"] += 1
    return candidates, dict(counters)


def _execute_candidates(candidates: list[dict[str, Any]], plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    signal = plan["signal"]
    execution = plan["execution"]
    bar_sec = int(plan["data"]["bar_sec"])
    cooldown_sec = int(signal["cooldown_bars"]) * bar_sec
    max_positions = int(signal["max_concurrent_positions"])
    last_signal_by_base: dict[str, int] = {}
    active_exit_times: list[int] = []
    skipped: dict[str, int] = defaultdict(int)
    trades: list[dict[str, Any]] = []

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[int(candidate["signal_ts"])].append(candidate)
    for signal_ts in sorted(grouped):
        rows = sorted(grouped[signal_ts], key=lambda row: (float(row["residual_bps"]), str(row["base"])))
        for candidate in rows:
            base = str(candidate["base"])
            entry_ts = int(candidate["entry_ts"])
            active_exit_times = [value for value in active_exit_times if value > entry_ts]
            if signal_ts - last_signal_by_base.get(base, -10**18) < cooldown_sec:
                skipped["cooldown"] += 1
                continue
            if len(active_exit_times) >= max_positions:
                skipped["max_concurrent_positions"] += 1
                continue
            gross_bps = (float(candidate["exit_price"]) / float(candidate["entry_price"]) - 1.0) * 10000.0
            normal_net_bps = gross_bps - float(execution["normal_total_cost_bps"])
            stress_net_bps = gross_bps - float(execution["stress_total_cost_bps"])
            notional = float(execution["notional_quote"])
            trade = dict(candidate) | {
                "trade_id": f"{base}-{signal_ts}",
                "gross_pnl_bps": gross_bps,
                "normal_net_pnl_bps": normal_net_bps,
                "stress_net_pnl_bps": stress_net_bps,
                "normal_net_pnl_quote": normal_net_bps / 10000.0 * notional,
                "stress_net_pnl_quote": stress_net_bps / 10000.0 * notional,
                "notional_quote": notional,
            }
            trades.append(trade)
            active_exit_times.append(int(candidate["exit_ts"]))
            last_signal_by_base[base] = signal_ts
    return trades, dict(skipped)


def _metrics(trades: list[dict[str, Any]], *, stress: bool = False) -> dict[str, Any]:
    bps_key = "stress_net_pnl_bps" if stress else "normal_net_pnl_bps"
    quote_key = "stress_net_pnl_quote" if stress else "normal_net_pnl_quote"
    ordered = sorted(trades, key=lambda row: (int(row["signal_ts"]), str(row["trade_id"])))
    values_bps = [float(row[bps_key]) for row in ordered]
    values_quote = [float(row[quote_key]) for row in ordered]
    wins = [value for value in values_quote if value > 0]
    losses = [value for value in values_quote if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = max_drawdown = 0.0
    positive_by_base: dict[str, float] = defaultdict(float)
    net_by_base: dict[str, float] = defaultdict(float)
    for trade, value in zip(ordered, values_quote):
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        base = str(trade["base"])
        net_by_base[base] += value
        if value > 0:
            positive_by_base[base] += value
    total_positive = sum(positive_by_base.values())
    concentration = max(positive_by_base.values()) / total_positive if total_positive > 0 else 1.0
    return {
        "trades": len(ordered),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(ordered) - len(wins) - len(losses),
        "win_rate": len(wins) / len(ordered) if ordered else 0.0,
        "gross_pnl_bps": sum(float(row["gross_pnl_bps"]) for row in ordered),
        "net_pnl_bps": sum(values_bps),
        "net_pnl_quote": sum(values_quote),
        "expectancy_bps": sum(values_bps) / len(values_bps) if values_bps else None,
        "expectancy_quote": sum(values_quote) / len(values_quote) if values_quote else None,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "profit_factor_infinite": bool(gross_loss == 0 and gross_profit > 0),
        "max_drawdown_quote": max_drawdown,
        "distinct_bases": len(net_by_base),
        "top_base_positive_contribution": concentration,
        "per_base_net_pnl_quote": dict(sorted(net_by_base.items())),
    }


def _pf(metrics: dict[str, Any]) -> float:
    if metrics["profit_factor_infinite"]:
        return math.inf
    return float(metrics["profit_factor"] or 0.0)


def _validation(trades: list[dict[str, Any]], plan: dict[str, Any], min_ts: int, max_ts: int, coverage_gate: bool) -> dict[str, Any]:
    config = plan["validation"]
    boundary = min_ts + (max_ts - min_ts) * float(config["train_fraction"])
    train = [trade for trade in trades if int(trade["signal_ts"]) < boundary]
    oos = [trade for trade in trades if int(trade["signal_ts"]) >= boundary]
    all_metrics = _metrics(trades)
    train_metrics = _metrics(train)
    oos_metrics = _metrics(oos)
    stress_oos = _metrics(oos, stress=True)
    folds = int(config["walk_forward_folds"])
    span = max(max_ts - min_ts, 1)
    fold_rows = []
    eligible_folds = positive_folds = 0
    for index in range(folds):
        start = min_ts + span * index / folds
        end = min_ts + span * (index + 1) / folds
        selected = [
            trade
            for trade in trades
            if int(trade["signal_ts"]) >= start
            and (int(trade["signal_ts"]) < end or index == folds - 1)
        ]
        metrics = _metrics(selected)
        eligible = metrics["trades"] >= int(config["min_trades_per_fold"])
        positive = eligible and metrics["expectancy_bps"] is not None and float(metrics["expectancy_bps"]) > 0
        eligible_folds += int(eligible)
        positive_folds += int(positive)
        fold_rows.append({"fold": index + 1, "start_ts": start, "end_ts": end, "eligible": eligible, "positive": positive, "metrics": metrics})
    positive_ratio = positive_folds / eligible_folds if eligible_folds else 0.0
    required_positive_folds = math.ceil(folds * float(config["min_positive_fold_ratio"]))
    gates = {
        "point_in_time_and_negative_outcome_coverage": coverage_gate,
        "sample_size": len(trades) >= int(config["min_total_trades"]),
        "oos_sample_size": len(oos) >= int(config["min_oos_trades"]),
        "all_net_expectancy": all_metrics["expectancy_bps"] is not None and float(all_metrics["expectancy_bps"]) > 0,
        "oos_net_expectancy": oos_metrics["expectancy_bps"] is not None and float(oos_metrics["expectancy_bps"]) > float(config["min_oos_expectancy_bps"]),
        "oos_profit_factor": _pf(oos_metrics) >= float(config["min_oos_profit_factor"]),
        "oos_market_diversity": oos_metrics["distinct_bases"] >= int(config["min_distinct_oos_bases"]),
        "concentration": float(oos_metrics["top_base_positive_contribution"]) <= float(config["max_top_base_positive_contribution"]),
        "walk_forward_coverage": eligible_folds >= required_positive_folds,
        "walk_forward": positive_folds >= required_positive_folds and positive_ratio >= float(config["min_positive_fold_ratio"]),
        "stress_oos_expectancy": stress_oos["expectancy_bps"] is not None and float(stress_oos["expectancy_bps"]) >= float(config["min_stress_expectancy_bps"]),
        "drawdown": float(all_metrics["max_drawdown_quote"]) <= float(config["max_drawdown_quote"]),
    }
    return {
        "split_boundary_ts": boundary,
        "all": all_metrics,
        "train": train_metrics,
        "oos": oos_metrics,
        "stress_oos": stress_oos,
        "walk_forward": {"folds": fold_rows, "eligible_folds": eligible_folds, "positive_folds": positive_folds, "positive_fold_ratio": positive_ratio},
        "gates": gates,
        "all_gates_passed": all(gates.values()),
    }


def _decision(signals: int, validation: dict[str, Any]) -> tuple[str, list[str]]:
    gates = validation["gates"]
    if signals == 0:
        return "CROSS_SECTIONAL_CAPITULATION_REJECTED_NO_FIXED_SIGNALS", ["no_fixed_signals"]
    if not gates["point_in_time_and_negative_outcome_coverage"]:
        return "CROSS_SECTIONAL_CAPITULATION_REJECTED_BIAS_CONTROL", ["point_in_time_and_negative_outcome_coverage"]
    if not gates["sample_size"] or not gates["oos_sample_size"]:
        return "CROSS_SECTIONAL_CAPITULATION_INCONCLUSIVE_INSUFFICIENT_SAMPLE", [name for name in ("sample_size", "oos_sample_size") if not gates[name]]
    if not gates["all_net_expectancy"] or not gates["oos_net_expectancy"] or not gates["oos_profit_factor"]:
        return "CROSS_SECTIONAL_CAPITULATION_REJECTED_OOS_ECONOMICS", [name for name in ("all_net_expectancy", "oos_net_expectancy", "oos_profit_factor") if not gates[name]]
    if not gates["oos_market_diversity"] or not gates["concentration"]:
        return "CROSS_SECTIONAL_CAPITULATION_REJECTED_CONCENTRATION", [name for name in ("oos_market_diversity", "concentration") if not gates[name]]
    if not gates["walk_forward_coverage"] or not gates["walk_forward"]:
        return "CROSS_SECTIONAL_CAPITULATION_REJECTED_WALK_FORWARD", [name for name in ("walk_forward_coverage", "walk_forward") if not gates[name]]
    if not gates["stress_oos_expectancy"] or not gates["drawdown"]:
        return "CROSS_SECTIONAL_CAPITULATION_REJECTED_STRESS_RISK", [name for name in ("stress_oos_expectancy", "drawdown") if not gates[name]]
    return "CROSS_SECTIONAL_CAPITULATION_CANDIDATE_READY_FOR_INDEPENDENT_AUDIT_PLANONLY", ["research_candidate_not_strategy_acceptance"]


def build_report(plan_path: str | Path, *, expected_plan_sha256: str | None = None) -> dict[str, Any]:
    plan_file = Path(plan_path)
    plan, plan_hash = load_plan(plan_file, expected_plan_sha256)
    evidence = _verify_evidence(plan)
    data = plan["data"]
    universe, universe_report = _load_universe(Path(str(data["universe_path"])), int(data["max_universe_rank"]))
    bars_by_base, history_report = _load_history(Path(str(data["history_jsonl_path"])), universe, plan)
    requested = set(history_report["requested_bases"])
    analysis_start = _parse_ts(data["analysis_start"])
    universe_asof = _parse_ts(data["universe_asof"])
    coverage_gate = requested == universe and analysis_start > universe_asof
    candidates, filter_counts = _build_candidates(bars_by_base, plan)
    trades, execution_skips = _execute_candidates(candidates, plan)
    all_ts = [bar.ts for rows in bars_by_base.values() for bar in rows if bar.ts >= analysis_start]
    min_ts = min(all_ts) if all_ts else analysis_start
    max_ts = max(all_ts) if all_ts else analysis_start
    validation = _validation(trades, plan, min_ts, max_ts, coverage_gate)
    decision, reasons = _decision(len(candidates), validation)
    candidate = decision.endswith("CANDIDATE_READY_FOR_INDEPENDENT_AUDIT_PLANONLY")
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": _utc_now(),
        "mode": "cross_sectional_capitulation_fixed_research",
        "decision": decision,
        "decision_reasons": reasons,
        "branch": plan["branch"],
        "research_only": True,
        "strategy_accepted": False,
        "research_candidate": candidate,
        "paper_forward_ready": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "grid_search": False,
        "collect": False,
        "plan_path": str(plan_file),
        "plan_sha256": plan_hash,
        "sealed_plan": plan,
        "evidence": evidence,
        "universe": universe_report | {"requested_bases_in_history": sorted(requested), "coverage_gate": coverage_gate},
        "history": history_report,
        "filters": filter_counts,
        "execution_skips": execution_skips,
        "summary": {
            "fixed_signal_candidates": len(candidates),
            "executed_trades": len(trades),
            "analysis_start_ts": analysis_start,
            "analysis_min_ts": min_ts,
            "analysis_max_ts": max_ts,
            "analysis_span_days": (max_ts - min_ts) / 86400.0 if max_ts >= min_ts else 0.0,
        },
        "validation": validation,
        "trades": sorted(trades, key=lambda row: (int(row["signal_ts"]), str(row["trade_id"]))),
        "next_step": "Run a fail-closed independent artifact audit; do not tune the sample." if candidate else "Close or mark the fixed branch according to decision_reasons; do not grid-tune this sample.",
    }


def run_report(plan_path: str | Path, output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    report = build_report(plan_path, **kwargs)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(target)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fixed 4h cross-sectional capitulation rebound replay.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_report(args.plan, args.output, expected_plan_sha256=args.expected_plan_sha256)
    print(json.dumps({"output": args.output, "decision": report["decision"], "summary": report["summary"], "gates": report["validation"]["gates"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
