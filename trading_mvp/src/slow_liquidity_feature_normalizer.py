from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


INTERVAL_SECONDS = {
    "1h": 3600,
    "4h": 14400,
}


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
class SlowLiquidityFeatureConfig:
    min_independent_events: int = 100
    min_event_bases: int = 8
    min_event_exchanges: int = 2
    max_single_base_event_fraction: float = 0.25
    cluster_window_sec: int = 12 * 3600
    train_fraction: float = 0.70
    max_sample_events: int = 50


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_from_ts(ts: float | int | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    text = str(value)
    return [text] if text else []


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


def _percentile_rank(prior_values: Iterable[float], value: float) -> float:
    values = [v for v in prior_values if math.isfinite(v)]
    if not values:
        return 0.0
    return sum(1 for item in values if item <= value) / len(values)


def _week_key(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _parse_candle(row: dict[str, Any]) -> Candle | None:
    if str(row.get("data_status") or "").lower() != "ok":
        return None
    ts = _to_int(row.get("candle_ts"))
    open_ = _to_float(row.get("open"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    close = _to_float(row.get("close"))
    volume = _to_float(row.get("volume")) or 0.0
    quote_volume = _to_float(row.get("quote_volume")) or 0.0
    if ts is None or open_ is None or high is None or low is None or close is None:
        return None
    if open_ <= 0 or high <= 0 or low <= 0 or close <= 0 or high < low:
        return None
    exchange = str(row.get("exchange") or "").strip().lower()
    symbol = str(row.get("symbol") or "").strip().upper()
    base = str(row.get("base") or "").strip().upper()
    quote = str(row.get("quote") or "USDT").strip().upper()
    granularity = str(row.get("granularity") or "").strip()
    if not exchange or not symbol or not base or granularity not in INTERVAL_SECONDS:
        return None
    return Candle(
        exchange=exchange,
        symbol=symbol,
        base=base,
        quote=quote,
        granularity=granularity,
        ts=ts,
        iso=str(row.get("candle_iso") or iso_from_ts(ts)),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        quote_volume=quote_volume,
    )


def _is_contiguous(candles: list[Candle], start_idx: int, end_idx_inclusive: int, interval_sec: int) -> bool:
    if start_idx < 0 or end_idx_inclusive >= len(candles) or start_idx > end_idx_inclusive:
        return False
    for idx in range(start_idx + 1, end_idx_inclusive + 1):
        if candles[idx].ts - candles[idx - 1].ts != interval_sec:
            return False
    return True


def _true_range(candle: Candle, previous_close: float | None) -> float:
    if previous_close is None:
        return candle.high - candle.low
    return max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close))


def _average_true_range(candles: list[Candle], start_idx: int, end_idx_exclusive: int) -> float:
    ranges: list[float] = []
    for idx in range(start_idx, end_idx_exclusive):
        previous_close = candles[idx - 1].close if idx > 0 else None
        ranges.append(_true_range(candles[idx], previous_close))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _context_snapshot(
    *,
    candle_ts: int,
    context_candles: list[Candle],
    context_timestamps: list[int],
    context_bars: int,
) -> dict[str, Any] | None:
    # A 1h bar with open T is closed at T+1h. A 4h bar with open S is fully
    # known only when S+4h <= T+1h, therefore S <= T-3h.
    cutoff_ts = candle_ts - (INTERVAL_SECONDS["4h"] - INTERVAL_SECONDS["1h"])
    idx = bisect.bisect_right(context_timestamps, cutoff_ts) - 1
    if idx < context_bars - 1:
        return None
    window = context_candles[idx - context_bars + 1 : idx + 1]
    if not _is_contiguous(context_candles, idx - context_bars + 1, idx, INTERVAL_SECONDS["4h"]):
        return None
    close = context_candles[idx].close
    sma = sum(item.close for item in window) / len(window)
    midpoint = (max(item.high for item in window) + min(item.low for item in window)) / 2.0
    pass_context = close >= sma or close >= midpoint
    return {
        "context_ts": context_candles[idx].ts,
        "context_iso": context_candles[idx].iso,
        "context_close": close,
        "context_sma": sma,
        "context_midpoint": midpoint,
        "context_close_vs_sma_bps": _safe_div(close - sma, sma) * 1e4,
        "context_close_vs_midpoint_bps": _safe_div(close - midpoint, midpoint) * 1e4,
        "context_pass": pass_context,
    }


def _event_score(event: dict[str, Any]) -> float:
    compression_score = max(0.0, 1.0 - float(event["range_width_atr"]) / max(float(event["compression_threshold_atr"]), 1e-12))
    context_score = max(0.0, float(event["context_close_vs_sma_bps"])) / 1000.0
    return float(event["volume_percentile"]) + compression_score + min(context_score, 1.0)


def _candidate_events_for_market(
    *,
    one_hour: list[Candle],
    four_hour: list[Candle],
    signal: dict[str, Any],
    cost_model: dict[str, Any],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    diagnostics: Counter[str] = Counter()
    lookback = int(signal.get("lookback_1h_bars") or 96)
    context_bars = int(signal.get("context_4h_bars") or 42)
    compression_threshold = float(signal.get("compression_range_width_max_atr") or 1.20)
    breakout_buffer_bps = float(signal.get("breakout_close_buffer_bps") or 60.0)
    volume_percentile_min = float(signal.get("volume_percentile_min") or 0.70)
    retest_window_bars = int(signal.get("retest_window_bars") or 12)
    retest_tolerance_atr = float(signal.get("retest_tolerance_atr") or 0.35)
    entry_delay_bars = int(signal.get("entry_delay_bars") or 1)
    stop_atr_multiple = float(signal.get("stop_atr_multiple") or 1.20)
    min_stop_bps = float(signal.get("min_stop_bps") or 120.0)
    target_r_multiple = float(signal.get("target_r_multiple") or 2.20)
    min_target_bps = float(signal.get("min_target_bps") or 300.0)
    minimum_target_after_cost_bps = float(cost_model.get("minimum_target_after_cost_bps") or min_target_bps)
    max_hold_bars = int(signal.get("max_hold_bars") or 72)

    if len(one_hour) < lookback + retest_window_bars + entry_delay_bars + 1:
        diagnostics["insufficient_1h_rows"] += 1
        return [], diagnostics
    if len(four_hour) < context_bars:
        diagnostics["insufficient_4h_rows"] += 1
        return [], diagnostics

    four_hour_ts = [candle.ts for candle in four_hour]
    events: list[dict[str, Any]] = []
    latest_breakout_idx = len(one_hour) - retest_window_bars - entry_delay_bars - 1

    for idx in range(lookback, latest_breakout_idx + 1):
        diagnostics["bars_scanned"] += 1
        if not _is_contiguous(one_hour, idx - lookback, idx, INTERVAL_SECONDS["1h"]):
            diagnostics["prior_window_gap"] += 1
            continue
        breakout = one_hour[idx]
        context = _context_snapshot(
            candle_ts=breakout.ts,
            context_candles=four_hour,
            context_timestamps=four_hour_ts,
            context_bars=context_bars,
        )
        if not context or not context["context_pass"]:
            diagnostics["context_failed"] += 1
            continue

        prior = one_hour[idx - lookback : idx]
        range_high = max(item.high for item in prior)
        range_low = min(item.low for item in prior)
        range_midpoint = (range_high + range_low) / 2.0
        atr = _average_true_range(one_hour, idx - lookback, idx)
        if atr <= 0:
            continue
        range_width = range_high - range_low
        range_width_atr = range_width / atr
        if range_width_atr > compression_threshold:
            diagnostics["compression_failed"] += 1
            continue

        breakout_level = range_high * (1.0 + breakout_buffer_bps / 1e4)
        if breakout.close <= breakout_level:
            diagnostics["breakout_failed"] += 1
            continue
        volume_percentile = _percentile_rank((item.quote_volume for item in prior), breakout.quote_volume)
        if volume_percentile < volume_percentile_min:
            diagnostics["volume_failed"] += 1
            continue

        retest_upper = range_high + atr * retest_tolerance_atr
        found_event = False
        for retest_idx in range(idx + 1, min(idx + retest_window_bars + 1, len(one_hour) - entry_delay_bars)):
            if not _is_contiguous(one_hour, idx, retest_idx + entry_delay_bars, INTERVAL_SECONDS["1h"]):
                diagnostics["retest_window_gap"] += 1
                break
            retest = one_hour[retest_idx]
            if retest.low > retest_upper or retest.close < range_high:
                continue
            entry_idx = retest_idx + entry_delay_bars
            entry = one_hour[entry_idx]
            entry_price = entry.open
            atr_stop_price = retest.low - atr * stop_atr_multiple
            min_stop_price = entry_price * (1.0 - min_stop_bps / 1e4)
            stop_price = min(atr_stop_price, min_stop_price)
            if stop_price <= 0 or stop_price >= entry_price:
                diagnostics["risk_geometry_failed"] += 1
                continue
            risk_bps = (entry_price - stop_price) / entry_price * 1e4
            target_bps = max(risk_bps * target_r_multiple, min_target_bps)
            if target_bps < minimum_target_after_cost_bps:
                diagnostics["target_cost_hurdle_failed"] += 1
                continue
            target_price = entry_price * (1.0 + target_bps / 1e4)
            event = {
                "event_id": f"SLQ-{breakout.base}-{breakout.exchange}-{entry.ts}",
                "exchange": breakout.exchange,
                "symbol": breakout.symbol,
                "base": breakout.base,
                "quote": breakout.quote,
                "signal_name": str(signal.get("name") or "slow_liquidity_regime_breakout_retest_v0"),
                "direction": str(signal.get("direction") or "long_only_spot"),
                "breakout_ts": breakout.ts,
                "breakout_iso": breakout.iso,
                "retest_ts": retest.ts,
                "retest_iso": retest.iso,
                "entry_ts": entry.ts,
                "entry_iso": entry.iso,
                "max_exit_ts": entry.ts + max_hold_bars * INTERVAL_SECONDS["1h"],
                "max_exit_iso": iso_from_ts(entry.ts + max_hold_bars * INTERVAL_SECONDS["1h"]),
                "entry_price": entry_price,
                "range_high": range_high,
                "range_low": range_low,
                "range_midpoint": range_midpoint,
                "range_width_bps": _safe_div(range_width, range_midpoint) * 1e4,
                "range_width_atr": range_width_atr,
                "compression_threshold_atr": compression_threshold,
                "atr_1h": atr,
                "breakout_close": breakout.close,
                "breakout_buffer_bps": breakout_buffer_bps,
                "breakout_close_over_range_high_bps": _safe_div(breakout.close - range_high, range_high) * 1e4,
                "breakout_quote_volume": breakout.quote_volume,
                "volume_percentile": volume_percentile,
                "retest_low": retest.low,
                "retest_close": retest.close,
                "retest_tolerance_price": retest_upper,
                "stop_price": stop_price,
                "target_price": target_price,
                "risk_bps": risk_bps,
                "target_bps": target_bps,
                "target_r_multiple": target_r_multiple,
                "minimum_target_after_cost_bps": minimum_target_after_cost_bps,
                "max_hold_bars": max_hold_bars,
                **context,
            }
            event["event_score"] = _event_score(event)
            events.append(event)
            diagnostics["raw_events"] += 1
            found_event = True
            break
        if not found_event:
            diagnostics["retest_failed"] += 1
    return events, diagnostics


def _cluster_and_throttle_events(raw_events: list[dict[str, Any]], signal: dict[str, Any], cfg: SlowLiquidityFeatureConfig) -> list[dict[str, Any]]:
    cooldown_sec = int(signal.get("cooldown_bars_after_exit") or 24) * INTERVAL_SECONDS["1h"]
    max_events_per_base_per_week = int(signal.get("max_events_per_base_per_week") or 3)
    selected: list[dict[str, Any]] = []
    week_counts: Counter[str] = Counter()
    last_selected_ts_by_base: dict[str, int] = {}

    by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in raw_events:
        by_base[str(event["base"])].append(event)

    representatives: list[dict[str, Any]] = []
    for base, events in by_base.items():
        events_sorted = sorted(events, key=lambda item: (int(item["entry_ts"]), -float(item["event_score"])))
        cluster: list[dict[str, Any]] = []
        cluster_start: int | None = None
        cluster_index = 0
        for event in events_sorted:
            entry_ts = int(event["entry_ts"])
            if cluster_start is None or entry_ts - cluster_start > cfg.cluster_window_sec:
                if cluster:
                    best = max(cluster, key=lambda item: (float(item["event_score"]), -int(item["entry_ts"])))
                    best = {**best, "independent_cluster_id": f"{base}-{cluster_index:04d}", "cluster_size": len(cluster)}
                    representatives.append(best)
                    cluster_index += 1
                cluster = [event]
                cluster_start = entry_ts
            else:
                cluster.append(event)
        if cluster:
            best = max(cluster, key=lambda item: (float(item["event_score"]), -int(item["entry_ts"])))
            best = {**best, "independent_cluster_id": f"{base}-{cluster_index:04d}", "cluster_size": len(cluster)}
            representatives.append(best)

    for event in sorted(representatives, key=lambda item: (int(item["entry_ts"]), str(item["base"]), -float(item["event_score"]))):
        base = str(event["base"])
        entry_ts = int(event["entry_ts"])
        if base in last_selected_ts_by_base and entry_ts - last_selected_ts_by_base[base] < cooldown_sec:
            continue
        week_key = f"{base}:{_week_key(entry_ts)}"
        if week_counts[week_key] >= max_events_per_base_per_week:
            continue
        selected.append(event)
        week_counts[week_key] += 1
        last_selected_ts_by_base[base] = entry_ts
    return selected


def normalize_slow_liquidity_features_planonly(
    *,
    history_jsonl_path: Path,
    history_manifest_path: Path,
    fixed_signal_path: Path,
    quality_path: Path,
    output_path: Path | None = None,
    config: SlowLiquidityFeatureConfig | None = None,
) -> dict[str, Any]:
    cfg = config or SlowLiquidityFeatureConfig()
    manifest = load_json(history_manifest_path)
    fixed_plan = load_json(fixed_signal_path)
    quality = load_json(quality_path)
    clean_bases = set(_as_list((fixed_plan.get("clean_slice") or {}).get("clean_bases")))
    required_timeframes = set(_as_list((fixed_plan.get("clean_slice") or {}).get("required_timeframes")) or ["1h", "4h"])
    signal = fixed_plan.get("fixed_signal_v0") or {}
    cost_model = fixed_plan.get("base_fee_cost_model") or {}

    rows = load_jsonl(history_jsonl_path)
    status_counts: Counter[str] = Counter()
    rows_by_granularity: Counter[str] = Counter()
    rows_by_exchange: Counter[str] = Counter()
    skipped_non_clean = 0
    skipped_timeframe = 0
    parsed_candles = 0
    candles_by_market_tf: dict[tuple[str, str, str, str], list[Candle]] = defaultdict(list)

    for row in rows:
        status_counts[str(row.get("data_status") or "unknown")] += 1
        base = str(row.get("base") or "").strip().upper()
        granularity = str(row.get("granularity") or "").strip()
        if base not in clean_bases:
            skipped_non_clean += 1
            continue
        if granularity not in required_timeframes:
            skipped_timeframe += 1
            continue
        candle = _parse_candle(row)
        if candle is None:
            continue
        parsed_candles += 1
        rows_by_granularity[candle.granularity] += 1
        rows_by_exchange[candle.exchange] += 1
        candles_by_market_tf[(candle.exchange, candle.base, candle.symbol, candle.granularity)].append(candle)

    for candles in candles_by_market_tf.values():
        candles.sort(key=lambda candle: candle.ts)

    markets_by_base: dict[str, list[tuple[str, str]]] = defaultdict(list)
    market_summaries: list[dict[str, Any]] = []
    diagnostics_by_market: list[dict[str, Any]] = []
    diagnostic_totals: Counter[str] = Counter()
    raw_events: list[dict[str, Any]] = []
    for (exchange, base, symbol, granularity), one_hour in sorted(candles_by_market_tf.items()):
        if granularity != "1h":
            continue
        four_hour = candles_by_market_tf.get((exchange, base, symbol, "4h"), [])
        market_key = f"{exchange}:{symbol}"
        eligible = bool(one_hour and four_hour)
        market_diagnostics: Counter[str] = Counter()
        if eligible:
            markets_by_base[base].append((exchange, symbol))
            market_events, market_diagnostics = _candidate_events_for_market(
                one_hour=one_hour,
                four_hour=four_hour,
                signal=signal,
                cost_model=cost_model,
            )
            raw_events.extend(market_events)
            diagnostic_totals.update(market_diagnostics)
        diagnostics_by_market.append(
            {
                "market": market_key,
                "exchange": exchange,
                "base": base,
                "symbol": symbol,
                "diagnostics": _counter_dict(market_diagnostics),
            }
        )
        market_summaries.append(
            {
                "market": market_key,
                "exchange": exchange,
                "base": base,
                "symbol": symbol,
                "eligible_timeframes": ["1h", "4h"] if eligible else ["1h"],
                "one_hour_rows": len(one_hour),
                "four_hour_rows": len(four_hour),
                "first_1h_iso": one_hour[0].iso if one_hour else "",
                "last_1h_iso": one_hour[-1].iso if one_hour else "",
                "eligible_for_signal": eligible,
            }
        )

    eligible_bases = sorted(base for base, markets in markets_by_base.items() if len(markets) >= 2)
    raw_events = [event for event in raw_events if str(event["base"]) in set(eligible_bases)]
    accepted_events = _cluster_and_throttle_events(raw_events, signal, cfg)

    events_by_base = Counter(str(event["base"]) for event in accepted_events)
    events_by_exchange = Counter(str(event["exchange"]) for event in accepted_events)
    independent_event_count = len(accepted_events)
    event_bases = len(events_by_base)
    event_exchanges = len(events_by_exchange)
    max_single_base_fraction = (
        max(events_by_base.values()) / independent_event_count if independent_event_count else 1.0
    )
    split_idx = int(math.floor(independent_event_count * cfg.train_fraction))
    train_events = accepted_events[:split_idx]
    oos_events = accepted_events[split_idx:]

    reasons: list[str] = []
    warnings: list[str] = []
    if manifest.get("final") is not True:
        reasons.append("history_manifest_not_final")
    if fixed_plan.get("decision") != "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER":
        reasons.append("fixed_signal_plan_not_ready_for_feature_normalizer")
    if quality.get("accepted") is not True:
        reasons.append("history_quality_not_accepted")
    if not clean_bases:
        reasons.append("missing_clean_bases")
    if required_timeframes != {"1h", "4h"}:
        reasons.append("unexpected_required_timeframes")
    if len(eligible_bases) < int((fixed_plan.get("clean_slice") or {}).get("min_clean_bases_required") or 8):
        reasons.append("min_clean_bases_with_two_eligible_venues")
    if independent_event_count < cfg.min_independent_events:
        reasons.append("min_independent_events")
    if event_bases < cfg.min_event_bases:
        reasons.append("min_event_bases")
    if event_exchanges < cfg.min_event_exchanges:
        reasons.append("min_event_exchanges")
    if max_single_base_fraction > cfg.max_single_base_event_fraction:
        reasons.append("max_single_base_event_fraction")
    if "15m" in _as_list((fixed_plan.get("clean_slice") or {}).get("disabled_timeframes")):
        warnings.append("15m_disabled_by_quality_gate")
    if raw_events and not accepted_events:
        warnings.append("raw_events_removed_by_dedup_cooldown_or_weekly_cap")

    ready = not reasons
    decision = (
        "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_READY_FOR_FIXED_REPLAY_VALIDATION"
        if ready
        else "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS"
    )
    required_next_step = (
        "run_fixed_slow_liquidity_replay_validation_planonly_no_grid_no_live"
        if ready
        else "reject_or_rescope_slow_liquidity_fixed_v0_or_collect_larger_independent_history_sample"
    )

    result: dict[str, Any] = {
        "mode": "slow_liquidity_feature_normalizer_planonly",
        "generated_at": utc_now_iso(),
        "decision": decision,
        "required_next_step": required_next_step,
        "selected_branch": "slow_liquidity_regime_breakout_retest",
        "research_only": True,
        "would_start": False,
        "strategy_accepted": False,
        "replay_allowed_now": ready,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "reasons": reasons,
        "warnings": warnings,
        "config": asdict(cfg),
        "inputs": {
            "history_jsonl_path": str(history_jsonl_path),
            "history_manifest_path": str(history_manifest_path),
            "fixed_signal_path": str(fixed_signal_path),
            "quality_path": str(quality_path),
            "history_run_id": manifest.get("run_id"),
        },
        "fixed_contract": {
            "signal": signal,
            "cost_model": cost_model,
            "validation_contract": fixed_plan.get("validation_contract") or {},
            "clean_bases": sorted(clean_bases),
            "required_timeframes": sorted(required_timeframes),
            "disabled_timeframes": _as_list((fixed_plan.get("clean_slice") or {}).get("disabled_timeframes")),
        },
        "data_scope": {
            "source_rows": len(rows),
            "source_status_counts": _counter_dict(status_counts),
            "skipped_non_clean_rows": skipped_non_clean,
            "skipped_disabled_or_unrequired_timeframe_rows": skipped_timeframe,
            "parsed_clean_candles": parsed_candles,
            "rows_by_granularity": _counter_dict(rows_by_granularity),
            "rows_by_exchange": _counter_dict(rows_by_exchange),
            "eligible_signal_markets": sum(1 for item in market_summaries if item["eligible_for_signal"]),
            "eligible_two_venue_bases": len(eligible_bases),
            "eligible_bases": eligible_bases,
            "market_summaries": market_summaries,
        },
        "feature_diagnostics": {
            "stage_totals": _counter_dict(diagnostic_totals),
            "markets_with_raw_events": sum(
                1 for item in diagnostics_by_market if int((item["diagnostics"] or {}).get("raw_events", 0)) > 0
            ),
            "top_market_diagnostics": sorted(
                diagnostics_by_market,
                key=lambda item: int((item["diagnostics"] or {}).get("raw_events", 0)),
                reverse=True,
            )[: cfg.max_sample_events],
        },
        "event_set": {
            "raw_candidate_events": len(raw_events),
            "independent_events": independent_event_count,
            "event_bases": event_bases,
            "event_exchanges": event_exchanges,
            "events_by_base": _counter_dict(events_by_base),
            "events_by_exchange": _counter_dict(events_by_exchange),
            "max_single_base_event_fraction": max_single_base_fraction,
            "chronological_train_fraction": cfg.train_fraction,
            "train_events": len(train_events),
            "oos_events": len(oos_events),
            "first_event_iso": accepted_events[0]["entry_iso"] if accepted_events else "",
            "last_event_iso": accepted_events[-1]["entry_iso"] if accepted_events else "",
            "sample_events": accepted_events[: cfg.max_sample_events],
            "normalized_events": accepted_events,
        },
        "blocked_actions": [
            "grid_search",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
            "parameter_tuning_after_seeing_oos",
            "15m_signal_until_clean_15m_gate_passes",
        ],
        "next_valid_moves": (
            [
                "Run a single fixed-parameter slow-liquidity replay-validation PlanOnly.",
                "Keep grid/live/API/paper-forward blocked until OOS, walk-forward, stress and economics gates pass.",
            ]
            if ready
            else [
                "Do not run replay/grid/live/API/paper-forward from this insufficient fixed-event set.",
                "Reject or rescope the fixed v0 branch, or collect a larger independent 1h/4h history sample before testing again.",
            ]
        ),
        "output_path": str(output_path) if output_path else "",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PlanOnly feature normalizer for slow-liquidity fixed v0 signal.")
    parser.add_argument("--history-jsonl", required=True)
    parser.add_argument("--history-manifest", required=True)
    parser.add_argument("--fixed-signal", required=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-independent-events", type=int, default=SlowLiquidityFeatureConfig.min_independent_events)
    parser.add_argument("--min-event-bases", type=int, default=SlowLiquidityFeatureConfig.min_event_bases)
    parser.add_argument("--min-event-exchanges", type=int, default=SlowLiquidityFeatureConfig.min_event_exchanges)
    parser.add_argument(
        "--max-single-base-event-fraction",
        type=float,
        default=SlowLiquidityFeatureConfig.max_single_base_event_fraction,
    )
    parser.add_argument("--cluster-window-sec", type=int, default=SlowLiquidityFeatureConfig.cluster_window_sec)
    parser.add_argument("--train-fraction", type=float, default=SlowLiquidityFeatureConfig.train_fraction)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = SlowLiquidityFeatureConfig(
        min_independent_events=args.min_independent_events,
        min_event_bases=args.min_event_bases,
        min_event_exchanges=args.min_event_exchanges,
        max_single_base_event_fraction=args.max_single_base_event_fraction,
        cluster_window_sec=args.cluster_window_sec,
        train_fraction=args.train_fraction,
    )
    result = normalize_slow_liquidity_features_planonly(
        history_jsonl_path=Path(args.history_jsonl),
        history_manifest_path=Path(args.history_manifest),
        fixed_signal_path=Path(args.fixed_signal),
        quality_path=Path(args.quality),
        output_path=Path(args.output),
        config=cfg,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
