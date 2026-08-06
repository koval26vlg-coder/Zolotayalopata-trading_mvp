from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from slow_liquidity_feature_normalizer import (
    INTERVAL_SECONDS,
    Candle,
    _average_true_range,
    _context_snapshot,
    _counter_dict,
    _is_contiguous,
    _parse_candle,
    _percentile_rank,
    _safe_div,
    load_json,
    load_jsonl,
)


@dataclass(frozen=True)
class EventCensusConfig:
    min_independent_events: int = 100
    min_event_bases: int = 8
    min_event_exchanges: int = 2
    max_single_base_event_fraction: float = 0.25
    cluster_window_sec: int = 12 * 3600
    min_target_geometry_bps: float = 300.0
    max_sample_events: int = 50


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_from_ts(ts: float | int | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _week_key(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _event_score(event: dict[str, Any]) -> float:
    return (
        max(0.0, _safe_float(event.get("setup_move_bps"))) / 300.0
        + max(0.0, _safe_float(event.get("volume_percentile")))
        + max(0.0, _safe_float(event.get("context_score")))
    )


def _target_geometry(entry_price: float, stop_price: float, min_target_bps: float) -> tuple[float, float]:
    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return 0.0, 0.0
    risk_bps = (entry_price - stop_price) / entry_price * 1e4
    target_bps = max(risk_bps * 2.0, min_target_bps)
    return risk_bps, target_bps


def _base_event(
    *,
    family: str,
    candle: Candle,
    entry_idx: int,
    one_hour: list[Candle],
    setup_move_bps: float,
    stop_price: float,
    volume_percentile: float,
    context: dict[str, Any] | None,
    cfg: EventCensusConfig,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if entry_idx >= len(one_hour):
        return None
    entry = one_hour[entry_idx]
    risk_bps, target_bps = _target_geometry(entry.open, stop_price, cfg.min_target_geometry_bps)
    if target_bps < cfg.min_target_geometry_bps:
        return None
    event = {
        "event_id": f"SLQ-CENSUS-{family}-{entry.base}-{entry.exchange}-{entry.ts}",
        "family": family,
        "exchange": entry.exchange,
        "symbol": entry.symbol,
        "base": entry.base,
        "quote": entry.quote,
        "event_ts": candle.ts,
        "event_iso": candle.iso,
        "entry_ts": entry.ts,
        "entry_iso": entry.iso,
        "entry_price": entry.open,
        "stop_price": stop_price,
        "risk_bps": risk_bps,
        "target_bps": target_bps,
        "minimum_target_geometry_bps": cfg.min_target_geometry_bps,
        "setup_move_bps": setup_move_bps,
        "volume_percentile": volume_percentile,
        "context_score": 0.0,
    }
    if context:
        event.update(
            {
                "context_ts": context.get("context_ts"),
                "context_iso": context.get("context_iso"),
                "context_close_vs_sma_bps": context.get("context_close_vs_sma_bps"),
                "context_close_vs_midpoint_bps": context.get("context_close_vs_midpoint_bps"),
                "context_pass": context.get("context_pass"),
                "context_score": max(0.0, _safe_float(context.get("context_close_vs_sma_bps"))) / 1000.0,
            }
        )
    if extra:
        event.update(extra)
    event["event_score"] = _event_score(event)
    return event


def _range_breakout_without_retest(
    one_hour: list[Candle],
    four_hour: list[Candle],
    cfg: EventCensusConfig,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    diagnostics: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    lookback = 72
    context_bars = 30
    max_range_atr = 1.8
    breakout_buffer_bps = 60.0
    volume_percentile_min = 0.65
    if len(one_hour) < lookback + 2 or len(four_hour) < context_bars:
        diagnostics["insufficient_rows"] += 1
        return events, diagnostics
    four_ts = [item.ts for item in four_hour]
    for idx in range(lookback, len(one_hour) - 1):
        diagnostics["bars_scanned"] += 1
        if not _is_contiguous(one_hour, idx - lookback, idx, INTERVAL_SECONDS["1h"]):
            diagnostics["prior_window_gap"] += 1
            continue
        context = _context_snapshot(
            candle_ts=one_hour[idx].ts,
            context_candles=four_hour,
            context_timestamps=four_ts,
            context_bars=context_bars,
        )
        if not context or not context["context_pass"]:
            diagnostics["context_failed"] += 1
            continue
        prior = one_hour[idx - lookback : idx]
        range_high = max(item.high for item in prior)
        range_low = min(item.low for item in prior)
        atr = _average_true_range(one_hour, idx - lookback, idx)
        if atr <= 0:
            diagnostics["atr_failed"] += 1
            continue
        range_width_atr = (range_high - range_low) / atr
        if range_width_atr > max_range_atr:
            diagnostics["compression_failed"] += 1
            continue
        breakout = one_hour[idx]
        breakout_bps = _safe_div(breakout.close - range_high, range_high) * 1e4
        if breakout_bps < breakout_buffer_bps:
            diagnostics["breakout_failed"] += 1
            continue
        volume_percentile = _percentile_rank((item.quote_volume for item in prior), breakout.quote_volume)
        if volume_percentile < volume_percentile_min:
            diagnostics["volume_failed"] += 1
            continue
        stop_price = min(range_low, breakout.close - atr * 1.2)
        event = _base_event(
            family="range_breakout_without_retest_v1",
            candle=breakout,
            entry_idx=idx + 1,
            one_hour=one_hour,
            setup_move_bps=breakout_bps,
            stop_price=stop_price,
            volume_percentile=volume_percentile,
            context=context,
            cfg=cfg,
            extra={"range_width_atr": range_width_atr, "range_high": range_high, "range_low": range_low},
        )
        if event:
            events.append(event)
            diagnostics["raw_events"] += 1
        else:
            diagnostics["geometry_failed"] += 1
    return events, diagnostics


def _volatility_expansion_continuation(
    one_hour: list[Candle],
    four_hour: list[Candle],
    cfg: EventCensusConfig,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    diagnostics: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    lookback = 48
    context_bars = 24
    min_body_bps = 120.0
    min_tr_atr = 2.0
    volume_percentile_min = 0.75
    if len(one_hour) < lookback + 2 or len(four_hour) < context_bars:
        diagnostics["insufficient_rows"] += 1
        return events, diagnostics
    four_ts = [item.ts for item in four_hour]
    for idx in range(lookback, len(one_hour) - 1):
        diagnostics["bars_scanned"] += 1
        if not _is_contiguous(one_hour, idx - lookback, idx, INTERVAL_SECONDS["1h"]):
            diagnostics["prior_window_gap"] += 1
            continue
        context = _context_snapshot(
            candle_ts=one_hour[idx].ts,
            context_candles=four_hour,
            context_timestamps=four_ts,
            context_bars=context_bars,
        )
        if not context or not context["context_pass"]:
            diagnostics["context_failed"] += 1
            continue
        candle = one_hour[idx]
        prior = one_hour[idx - lookback : idx]
        atr = _average_true_range(one_hour, idx - lookback, idx)
        if atr <= 0:
            diagnostics["atr_failed"] += 1
            continue
        body_bps = _safe_div(candle.close - candle.open, candle.open) * 1e4
        tr_atr = (candle.high - candle.low) / atr
        if body_bps < min_body_bps or tr_atr < min_tr_atr:
            diagnostics["expansion_failed"] += 1
            continue
        volume_percentile = _percentile_rank((item.quote_volume for item in prior), candle.quote_volume)
        if volume_percentile < volume_percentile_min:
            diagnostics["volume_failed"] += 1
            continue
        stop_price = min(candle.low, candle.close - atr * 1.5)
        event = _base_event(
            family="volatility_expansion_continuation_v1",
            candle=candle,
            entry_idx=idx + 1,
            one_hour=one_hour,
            setup_move_bps=body_bps,
            stop_price=stop_price,
            volume_percentile=volume_percentile,
            context=context,
            cfg=cfg,
            extra={"true_range_atr": tr_atr},
        )
        if event:
            events.append(event)
            diagnostics["raw_events"] += 1
        else:
            diagnostics["geometry_failed"] += 1
    return events, diagnostics


def _liquidity_shock_reclaim(
    one_hour: list[Candle],
    four_hour: list[Candle],
    cfg: EventCensusConfig,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    diagnostics: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    lookback = 48
    min_sell_body_bps = -250.0
    min_low_sweep_bps = -400.0
    volume_percentile_min = 0.75
    if len(one_hour) < lookback + 3:
        diagnostics["insufficient_rows"] += 1
        return events, diagnostics
    for idx in range(lookback, len(one_hour) - 2):
        diagnostics["bars_scanned"] += 1
        if not _is_contiguous(one_hour, idx - lookback, idx + 2, INTERVAL_SECONDS["1h"]):
            diagnostics["window_gap"] += 1
            continue
        shock = one_hour[idx]
        prior = one_hour[idx - lookback : idx]
        body_bps = _safe_div(shock.close - shock.open, shock.open) * 1e4
        low_sweep_bps = _safe_div(shock.low - shock.open, shock.open) * 1e4
        if body_bps > min_sell_body_bps and low_sweep_bps > min_low_sweep_bps:
            diagnostics["shock_failed"] += 1
            continue
        volume_percentile = _percentile_rank((item.quote_volume for item in prior), shock.quote_volume)
        if volume_percentile < volume_percentile_min:
            diagnostics["volume_failed"] += 1
            continue
        reclaim = one_hour[idx + 1]
        shock_midpoint = (shock.high + shock.low) / 2.0
        if reclaim.close < shock_midpoint:
            diagnostics["reclaim_failed"] += 1
            continue
        stop_price = shock.low * 0.995
        event = _base_event(
            family="liquidity_shock_reclaim_long_v1",
            candle=shock,
            entry_idx=idx + 2,
            one_hour=one_hour,
            setup_move_bps=abs(low_sweep_bps),
            stop_price=stop_price,
            volume_percentile=volume_percentile,
            context=None,
            cfg=cfg,
            extra={"shock_body_bps": body_bps, "low_sweep_bps": low_sweep_bps, "reclaim_close": reclaim.close},
        )
        if event:
            events.append(event)
            diagnostics["raw_events"] += 1
        else:
            diagnostics["geometry_failed"] += 1
    return events, diagnostics


def _four_hour_compression_breakout(
    one_hour: list[Candle],
    four_hour: list[Candle],
    cfg: EventCensusConfig,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    diagnostics: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    lookback = 18
    max_range_atr = 1.7
    breakout_buffer_bps = 80.0
    volume_percentile_min = 0.65
    if len(four_hour) < lookback + 2 or len(one_hour) < 2:
        diagnostics["insufficient_rows"] += 1
        return events, diagnostics
    one_hour_by_ts = {candle.ts: idx for idx, candle in enumerate(one_hour)}
    for idx in range(lookback, len(four_hour) - 1):
        diagnostics["bars_scanned"] += 1
        if not _is_contiguous(four_hour, idx - lookback, idx, INTERVAL_SECONDS["4h"]):
            diagnostics["prior_window_gap"] += 1
            continue
        prior = four_hour[idx - lookback : idx]
        range_high = max(item.high for item in prior)
        range_low = min(item.low for item in prior)
        atr = _average_true_range(four_hour, idx - lookback, idx)
        if atr <= 0:
            diagnostics["atr_failed"] += 1
            continue
        range_width_atr = (range_high - range_low) / atr
        if range_width_atr > max_range_atr:
            diagnostics["compression_failed"] += 1
            continue
        breakout = four_hour[idx]
        breakout_bps = _safe_div(breakout.close - range_high, range_high) * 1e4
        if breakout_bps < breakout_buffer_bps:
            diagnostics["breakout_failed"] += 1
            continue
        volume_percentile = _percentile_rank((item.quote_volume for item in prior), breakout.quote_volume)
        if volume_percentile < volume_percentile_min:
            diagnostics["volume_failed"] += 1
            continue
        entry_ts = breakout.ts + INTERVAL_SECONDS["4h"]
        entry_idx = one_hour_by_ts.get(entry_ts)
        if entry_idx is None:
            diagnostics["missing_entry_1h"] += 1
            continue
        stop_price = min(range_low, breakout.close - atr * 1.2)
        event = _base_event(
            family="four_hour_compression_breakout_v1",
            candle=breakout,
            entry_idx=entry_idx,
            one_hour=one_hour,
            setup_move_bps=breakout_bps,
            stop_price=stop_price,
            volume_percentile=volume_percentile,
            context={"context_pass": True, "context_close_vs_sma_bps": 0.0, "context_close_vs_midpoint_bps": 0.0},
            cfg=cfg,
            extra={"range_width_atr": range_width_atr, "range_high": range_high, "range_low": range_low},
        )
        if event:
            events.append(event)
            diagnostics["raw_events"] += 1
        else:
            diagnostics["geometry_failed"] += 1
    return events, diagnostics


def _cluster_events(events: list[dict[str, Any]], cfg: EventCensusConfig) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    by_family_base: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_family_base[(str(event["family"]), str(event["base"]))].append(event)

    for (family, base), group in sorted(by_family_base.items()):
        cluster: list[dict[str, Any]] = []
        cluster_start: int | None = None
        cluster_index = 0
        for event in sorted(group, key=lambda item: (int(item["entry_ts"]), -float(item["event_score"]))):
            entry_ts = int(event["entry_ts"])
            if cluster_start is None or entry_ts - cluster_start > cfg.cluster_window_sec:
                if cluster:
                    best = max(cluster, key=lambda item: (float(item["event_score"]), -int(item["entry_ts"])))
                    selected.append({**best, "independent_cluster_id": f"{family}-{base}-{cluster_index:04d}", "cluster_size": len(cluster)})
                    cluster_index += 1
                cluster = [event]
                cluster_start = entry_ts
            else:
                cluster.append(event)
        if cluster:
            best = max(cluster, key=lambda item: (float(item["event_score"]), -int(item["entry_ts"])))
            selected.append({**best, "independent_cluster_id": f"{family}-{base}-{cluster_index:04d}", "cluster_size": len(cluster)})
    return sorted(selected, key=lambda item: (int(item["entry_ts"]), str(item["family"]), str(item["base"]), str(item["exchange"])))


def _family_summary(events: list[dict[str, Any]], cfg: EventCensusConfig) -> dict[str, Any]:
    counts_by_base = Counter(str(event["base"]) for event in events)
    counts_by_exchange = Counter(str(event["exchange"]) for event in events)
    count = len(events)
    max_single_base_fraction = max(counts_by_base.values()) / count if count else 1.0
    reasons: list[str] = []
    if count < cfg.min_independent_events:
        reasons.append("min_independent_events")
    if len(counts_by_base) < cfg.min_event_bases:
        reasons.append("min_event_bases")
    if len(counts_by_exchange) < cfg.min_event_exchanges:
        reasons.append("min_event_exchanges")
    if max_single_base_fraction > cfg.max_single_base_event_fraction:
        reasons.append("max_single_base_event_fraction")
    return {
        "independent_events": count,
        "event_bases": len(counts_by_base),
        "event_exchanges": len(counts_by_exchange),
        "events_by_base": _counter_dict(counts_by_base),
        "events_by_exchange": _counter_dict(counts_by_exchange),
        "max_single_base_event_fraction": max_single_base_fraction,
        "accepted_for_fixed_v1_plan": not reasons,
        "reasons": reasons,
        "first_event_iso": events[0]["entry_iso"] if events else "",
        "last_event_iso": events[-1]["entry_iso"] if events else "",
    }


def run_slow_liquidity_event_census_planonly(
    *,
    history_jsonl_path: Path,
    history_manifest_path: Path,
    rescope_path: Path,
    quality_path: Path,
    output_path: Path | None = None,
    config: EventCensusConfig | None = None,
) -> dict[str, Any]:
    cfg = config or EventCensusConfig()
    manifest = load_json(history_manifest_path)
    rescope = load_json(rescope_path)
    quality = load_json(quality_path)
    clean_bases = set(str(base).upper() for base in ((rescope.get("v1_event_census_plan") or {}).get("clean_bases") or []))
    if not clean_bases:
        clean_bases = set(str(base).upper() for base in ((quality.get("clean_markets") or {}).get("two_exchange_full_coverage_1h4h_bases") or []))
    rows = load_jsonl(history_jsonl_path)

    status_counts: Counter[str] = Counter()
    candles_by_market_tf: dict[tuple[str, str, str, str], list[Candle]] = defaultdict(list)
    skipped_non_clean = 0
    skipped_timeframe = 0
    for row in rows:
        status_counts[str(row.get("data_status") or "unknown")] += 1
        base = str(row.get("base") or "").strip().upper()
        granularity = str(row.get("granularity") or "").strip()
        if base not in clean_bases:
            skipped_non_clean += 1
            continue
        if granularity not in {"1h", "4h"}:
            skipped_timeframe += 1
            continue
        candle = _parse_candle(row)
        if candle:
            candles_by_market_tf[(candle.exchange, candle.base, candle.symbol, candle.granularity)].append(candle)

    for candles in candles_by_market_tf.values():
        candles.sort(key=lambda item: item.ts)

    raw_events: list[dict[str, Any]] = []
    diagnostics_by_family: dict[str, Counter[str]] = defaultdict(Counter)
    diagnostics_by_market: list[dict[str, Any]] = []
    eligible_markets = 0
    for (exchange, base, symbol, granularity), one_hour in sorted(candles_by_market_tf.items()):
        if granularity != "1h":
            continue
        four_hour = candles_by_market_tf.get((exchange, base, symbol, "4h"), [])
        if not four_hour:
            continue
        eligible_markets += 1
        family_functions = (
            _range_breakout_without_retest,
            _volatility_expansion_continuation,
            _liquidity_shock_reclaim,
            _four_hour_compression_breakout,
        )
        market_diag: dict[str, dict[str, int]] = {}
        for fn in family_functions:
            events, diagnostics = fn(one_hour, four_hour, cfg)
            raw_events.extend(events)
            family_name = fn.__name__.lstrip("_")
            diagnostics_by_family[family_name].update(diagnostics)
            market_diag[family_name] = _counter_dict(diagnostics)
        diagnostics_by_market.append(
            {
                "market": f"{exchange}:{symbol}",
                "exchange": exchange,
                "base": base,
                "symbol": symbol,
                "diagnostics": market_diag,
            }
        )

    independent_events = _cluster_events(raw_events, cfg)
    events_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in independent_events:
        events_by_family[str(event["family"])].append(event)
    family_summaries = {
        family: _family_summary(events, cfg)
        for family, events in sorted(events_by_family.items())
    }
    accepted_families = [
        family for family, summary in family_summaries.items() if bool(summary["accepted_for_fixed_v1_plan"])
    ]
    top_family = ""
    if family_summaries:
        top_family = max(
            family_summaries,
            key=lambda family: (
                bool(family_summaries[family]["accepted_for_fixed_v1_plan"]),
                int(family_summaries[family]["independent_events"]),
                int(family_summaries[family]["event_bases"]),
                int(family_summaries[family]["event_exchanges"]),
            ),
        )

    total_summary = _family_summary(independent_events, cfg)
    accepted = bool(accepted_families)
    decision = (
        "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_READY_FOR_FIXED_V1_PLANONLY"
        if accepted
        else "SLOW_LIQUIDITY_EVENT_CENSUS_V1_REJECTED_INSUFFICIENT_EVENT_BASE_RATE"
    )
    result: dict[str, Any] = {
        "mode": "slow_liquidity_event_census_v1_planonly",
        "generated_at": utc_now_iso(),
        "decision": decision,
        "selected_branch": "slow_liquidity_regime_breakout_retest",
        "research_only": True,
        "would_start": False,
        "strategy_accepted": False,
        "replay_allowed_now": False,
        "grid_allowed_now": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "config": asdict(cfg),
        "inputs": {
            "history_jsonl_path": str(history_jsonl_path),
            "history_manifest_path": str(history_manifest_path),
            "rescope_path": str(rescope_path),
            "quality_path": str(quality_path),
            "history_run_id": manifest.get("run_id"),
        },
        "data_scope": {
            "source_rows": len(rows),
            "source_status_counts": _counter_dict(status_counts),
            "skipped_non_clean_rows": skipped_non_clean,
            "skipped_disabled_or_unrequired_timeframe_rows": skipped_timeframe,
            "clean_bases": sorted(clean_bases),
            "eligible_signal_markets": eligible_markets,
        },
        "event_census": {
            "raw_candidate_events": len(raw_events),
            "independent_events": len(independent_events),
            "accepted_families": accepted_families,
            "top_family": top_family,
            "total_summary": total_summary,
            "family_summaries": family_summaries,
            "sample_events": independent_events[: cfg.max_sample_events],
            "normalized_events": independent_events,
        },
        "diagnostics": {
            "by_family": {family: _counter_dict(counter) for family, counter in sorted(diagnostics_by_family.items())},
            "top_market_diagnostics": diagnostics_by_market[: cfg.max_sample_events],
        },
        "blocked_actions": [
            "grid_search",
            "replay_validation",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
            "paper_forward",
            "collect_larger_history_without_event_base_rate",
            "parameter_tuning_after_oos",
        ],
        "next_valid_moves": (
            [
                "Build a fixed v1 signal PlanOnly for the accepted event family; keep parameters frozen before replay.",
                "Only after fixed v1 PlanOnly exists, run one replay-validation PlanOnly with no grid/live/API/paper-forward.",
            ]
            if accepted
            else [
                "Reject slow_liquidity_regime_breakout_retest on this event-census evidence.",
                "Select a different structural branch PlanOnly or define a new event family before any new data collection.",
            ]
        ),
        "output_path": str(output_path) if output_path else "",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PlanOnly event-census for slow-liquidity v1 signal families.")
    parser.add_argument("--history-jsonl", required=True)
    parser.add_argument("--history-manifest", required=True)
    parser.add_argument("--rescope", required=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-independent-events", type=int, default=EventCensusConfig.min_independent_events)
    parser.add_argument("--min-event-bases", type=int, default=EventCensusConfig.min_event_bases)
    parser.add_argument("--min-event-exchanges", type=int, default=EventCensusConfig.min_event_exchanges)
    parser.add_argument("--max-single-base-event-fraction", type=float, default=EventCensusConfig.max_single_base_event_fraction)
    parser.add_argument("--cluster-window-sec", type=int, default=EventCensusConfig.cluster_window_sec)
    parser.add_argument("--min-target-geometry-bps", type=float, default=EventCensusConfig.min_target_geometry_bps)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = EventCensusConfig(
        min_independent_events=args.min_independent_events,
        min_event_bases=args.min_event_bases,
        min_event_exchanges=args.min_event_exchanges,
        max_single_base_event_fraction=args.max_single_base_event_fraction,
        cluster_window_sec=args.cluster_window_sec,
        min_target_geometry_bps=args.min_target_geometry_bps,
    )
    result = run_slow_liquidity_event_census_planonly(
        history_jsonl_path=Path(args.history_jsonl),
        history_manifest_path=Path(args.history_manifest),
        rescope_path=Path(args.rescope),
        quality_path=Path(args.quality),
        output_path=Path(args.output),
        config=cfg,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
