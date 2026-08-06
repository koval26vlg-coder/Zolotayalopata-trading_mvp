from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


@dataclass(frozen=True)
class SlowLiquidityHistoryQualityConfig:
    min_ok_rows: int = 100_000
    min_ok_bases: int = 20
    min_ok_exchanges: int = 2
    min_ok_market_granularity_slots: int = 150
    min_ok_slot_fraction: float = 0.35
    max_api_error_slot_rate: float = 0.70
    min_two_exchange_bases: int = 15
    min_two_exchange_full_coverage_1h4h_bases: int = 8
    min_full_coverage_ratio: float = 0.80
    require_manifest_final: bool = True
    require_completed_requests: bool = True
    require_line_count_match_manifest: bool = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "source": "slow_liquidity_history",
                        "exchange": "",
                        "base": "",
                        "symbol": "",
                        "granularity": "",
                        "job_key": f"parse_error:{line_no}",
                        "data_status": "parse_error",
                        "error": str(exc),
                    }
                )
    return rows


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _counter_to_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


def _expected_candle_count(row: dict[str, Any]) -> int:
    granularity = str(row.get("granularity") or "")
    interval = INTERVAL_SECONDS.get(granularity)
    if not interval:
        return 0
    try:
        start_ts = int(row.get("history_start_ts"))
        end_ts = int(row.get("history_end_ts"))
    except (TypeError, ValueError):
        return 0
    if end_ts < start_ts:
        return 0
    return math.floor((end_ts - start_ts) / interval) + 1


def _sorted_strings(values: Iterable[str]) -> list[str]:
    return sorted(str(value) for value in values if str(value))


def evaluate_slow_liquidity_history_quality(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    config: SlowLiquidityHistoryQualityConfig | None = None,
) -> dict[str, Any]:
    cfg = config or SlowLiquidityHistoryQualityConfig()

    status_counts: Counter[str] = Counter()
    rows_by_exchange: Counter[str] = Counter()
    ok_rows_by_exchange: Counter[str] = Counter()
    rows_by_granularity: Counter[str] = Counter()
    ok_rows_by_granularity: Counter[str] = Counter()
    error_rows_by_exchange: Counter[str] = Counter()
    placeholder_rows_by_exchange: Counter[str] = Counter()
    ok_rows_by_market: Counter[str] = Counter()

    observed_slots: set[tuple[str, str, str]] = set()
    ok_slots: set[tuple[str, str, str]] = set()
    error_slots: set[tuple[str, str, str]] = set()
    observed_bases: set[str] = set()
    ok_bases: set[str] = set()
    observed_exchanges: set[str] = set()
    ok_exchanges: set[str] = set()
    ok_exchanges_by_base: dict[str, set[str]] = defaultdict(set)
    ok_granularities_by_base_exchange: dict[tuple[str, str], set[str]] = defaultdict(set)
    candle_ts_by_slot: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    slot_meta: dict[tuple[str, str, str], dict[str, Any]] = {}
    duplicate_candles = 0

    for row in rows:
        status = str(row.get("data_status") or "unknown")
        exchange = str(row.get("exchange") or "")
        base = str(row.get("base") or "")
        symbol = str(row.get("symbol") or "")
        granularity = str(row.get("granularity") or "")
        slot = (exchange, base, granularity)
        market_key = f"{exchange}:{symbol or base}"

        status_counts[status] += 1
        if exchange:
            rows_by_exchange[exchange] += 1
            observed_exchanges.add(exchange)
        if granularity:
            rows_by_granularity[granularity] += 1
        if base:
            observed_bases.add(base)
        if exchange and base and granularity:
            observed_slots.add(slot)
            slot_meta.setdefault(slot, row)

        if status == "ok":
            ok_bases.add(base)
            ok_exchanges.add(exchange)
            ok_slots.add(slot)
            ok_exchanges_by_base[base].add(exchange)
            ok_granularities_by_base_exchange[(base, exchange)].add(granularity)
            ok_rows_by_exchange[exchange] += 1
            ok_rows_by_granularity[granularity] += 1
            ok_rows_by_market[market_key] += 1
            candle_ts = row.get("candle_ts")
            if candle_ts is not None and exchange and base and granularity:
                try:
                    ts = int(candle_ts)
                except (TypeError, ValueError):
                    ts = -1
                if ts in candle_ts_by_slot[slot]:
                    duplicate_candles += 1
                candle_ts_by_slot[slot].add(ts)
        elif status == "api_error":
            error_rows_by_exchange[exchange] += 1
            if exchange and base and granularity:
                error_slots.add(slot)
        else:
            placeholder_rows_by_exchange[exchange] += 1

    planned_requests = int(manifest.get("planned_market_granularity_requests") or len(observed_slots))
    completed_requests = int(manifest.get("completed_market_granularity_requests") or 0)
    selected_bases = int(len(manifest.get("selected_bases") or []) or len(observed_bases))
    manifest_ohlcv_rows = int(manifest.get("ohlcv_rows") or 0)
    manifest_placeholder_rows = int(manifest.get("placeholder_rows") or 0)
    manifest_errors = int(manifest.get("errors") or 0)
    expected_line_count = manifest_ohlcv_rows + manifest_placeholder_rows
    line_count = len(rows)
    ok_rows = int(status_counts.get("ok", 0))
    api_error_rows = int(status_counts.get("api_error", 0))

    ok_slot_count = len(ok_slots)
    ok_slot_fraction = _safe_div(ok_slot_count, planned_requests)
    api_error_slot_count = len(error_slots) if error_slots else api_error_rows
    api_error_slot_rate = _safe_div(api_error_slot_count, planned_requests)
    two_exchange_bases = _sorted_strings(base for base, exchanges in ok_exchanges_by_base.items() if len(exchanges) >= 2)
    three_exchange_bases = _sorted_strings(base for base, exchanges in ok_exchanges_by_base.items() if len(exchanges) >= 3)

    coverage_by_slot: dict[str, dict[str, Any]] = {}
    full_coverage_slots: set[tuple[str, str, str]] = set()
    partial_coverage_slots: set[tuple[str, str, str]] = set()
    for slot, timestamps in candle_ts_by_slot.items():
        expected = _expected_candle_count(slot_meta.get(slot, {}))
        actual = len(timestamps)
        coverage_ratio = _safe_div(actual, expected)
        slot_key = ":".join(slot)
        coverage_by_slot[slot_key] = {
            "actual_candles": actual,
            "expected_candles": expected,
            "coverage_ratio": coverage_ratio,
        }
        if expected > 0 and coverage_ratio >= cfg.min_full_coverage_ratio:
            full_coverage_slots.add(slot)
        else:
            partial_coverage_slots.add(slot)

    def base_has_exchange_timeframe_coverage(base: str, exchange: str, granularities: tuple[str, ...]) -> bool:
        return all((exchange, base, granularity) in full_coverage_slots for granularity in granularities)

    two_exchange_full_coverage_1h4h_bases: list[str] = []
    three_exchange_full_coverage_1h4h_bases: list[str] = []
    two_exchange_full_coverage_all_timeframe_bases: list[str] = []
    for base, exchanges in ok_exchanges_by_base.items():
        covered_1h4h = [
            exchange
            for exchange in exchanges
            if base_has_exchange_timeframe_coverage(base, exchange, ("1h", "4h"))
        ]
        covered_all = [
            exchange
            for exchange in exchanges
            if base_has_exchange_timeframe_coverage(base, exchange, ("15m", "1h", "4h"))
        ]
        if len(covered_1h4h) >= 2:
            two_exchange_full_coverage_1h4h_bases.append(base)
        if len(covered_1h4h) >= 3:
            three_exchange_full_coverage_1h4h_bases.append(base)
        if len(covered_all) >= 2:
            two_exchange_full_coverage_all_timeframe_bases.append(base)

    two_exchange_full_coverage_1h4h_bases = _sorted_strings(two_exchange_full_coverage_1h4h_bases)
    three_exchange_full_coverage_1h4h_bases = _sorted_strings(three_exchange_full_coverage_1h4h_bases)
    two_exchange_full_coverage_all_timeframe_bases = _sorted_strings(two_exchange_full_coverage_all_timeframe_bases)

    reasons: list[str] = []
    warnings: list[str] = []
    if cfg.require_manifest_final and manifest.get("final") is not True:
        reasons.append("manifest_not_final")
    if cfg.require_completed_requests and completed_requests < planned_requests:
        reasons.append("incomplete_market_granularity_requests")
    if cfg.require_line_count_match_manifest and line_count != expected_line_count:
        reasons.append("line_count_mismatch_manifest")
    if ok_rows < cfg.min_ok_rows:
        reasons.append("min_ok_rows")
    if len(ok_bases) < cfg.min_ok_bases:
        reasons.append("min_ok_bases")
    if len({exchange for exchange in ok_exchanges if exchange}) < cfg.min_ok_exchanges:
        reasons.append("min_ok_exchanges")
    if ok_slot_count < cfg.min_ok_market_granularity_slots:
        reasons.append("min_ok_market_granularity_slots")
    if ok_slot_fraction < cfg.min_ok_slot_fraction:
        reasons.append("min_ok_slot_fraction")
    if api_error_slot_rate > cfg.max_api_error_slot_rate:
        reasons.append("max_api_error_slot_rate")
    if len(two_exchange_bases) < cfg.min_two_exchange_bases:
        reasons.append("min_two_exchange_bases")
    if len(two_exchange_full_coverage_1h4h_bases) < cfg.min_two_exchange_full_coverage_1h4h_bases:
        reasons.append("min_two_exchange_full_coverage_1h4h_bases")
    if not two_exchange_full_coverage_all_timeframe_bases:
        warnings.append("15m_two_exchange_full_coverage_absent_use_1h4h_only")
    if api_error_slot_rate > 0.50:
        warnings.append("high_universe_unavailable_slot_rate")
    if partial_coverage_slots:
        warnings.append("partial_candle_coverage_slots_present")

    accepted = not reasons
    decision = (
        "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY"
        if accepted
        else "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE"
    )

    coverage_values = [entry["coverage_ratio"] for entry in coverage_by_slot.values()]
    coverage_values_sorted = sorted(coverage_values)
    median_coverage = coverage_values_sorted[len(coverage_values_sorted) // 2] if coverage_values_sorted else 0.0

    return {
        "mode": "slow_liquidity_history_data_quality",
        "generated_at": utc_now_iso(),
        "decision": decision,
        "accepted": accepted,
        "fixed_signal_plan_allowed": accepted,
        "normalizer_allowed": accepted,
        "replay_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "reasons": reasons,
        "warnings": warnings,
        "config": asdict(cfg),
        "metrics": {
            "selected_bases": selected_bases,
            "planned_market_granularity_requests": planned_requests,
            "completed_market_granularity_requests": completed_requests,
            "line_count": line_count,
            "expected_line_count_from_manifest": expected_line_count,
            "line_count_matches_manifest": line_count == expected_line_count,
            "manifest_ohlcv_rows": manifest_ohlcv_rows,
            "manifest_placeholder_rows": manifest_placeholder_rows,
            "manifest_errors": manifest_errors,
            "ok_rows": ok_rows,
            "api_error_rows": api_error_rows,
            "placeholder_rows": line_count - ok_rows,
            "unique_bases_observed": len(observed_bases),
            "unique_exchanges_observed": len({exchange for exchange in observed_exchanges if exchange}),
            "observed_market_granularity_slots": len(observed_slots),
            "ok_bases": len(ok_bases),
            "ok_exchanges": len({exchange for exchange in ok_exchanges if exchange}),
            "ok_market_granularity_slots": ok_slot_count,
            "ok_slot_fraction": ok_slot_fraction,
            "api_error_slot_count": api_error_slot_count,
            "api_error_slot_rate": api_error_slot_rate,
            "two_exchange_bases": len(two_exchange_bases),
            "three_exchange_bases": len(three_exchange_bases),
            "two_exchange_full_coverage_1h4h_bases": len(two_exchange_full_coverage_1h4h_bases),
            "three_exchange_full_coverage_1h4h_bases": len(three_exchange_full_coverage_1h4h_bases),
            "two_exchange_full_coverage_all_timeframe_bases": len(two_exchange_full_coverage_all_timeframe_bases),
            "full_coverage_slots": len(full_coverage_slots),
            "partial_coverage_slots": len(partial_coverage_slots),
            "coverage_ratio_min": min(coverage_values) if coverage_values else 0.0,
            "coverage_ratio_median": median_coverage,
            "coverage_ratio_max": max(coverage_values) if coverage_values else 0.0,
            "duplicate_candles": duplicate_candles,
        },
        "counts": {
            "status": _counter_to_dict(status_counts),
            "rows_by_exchange": _counter_to_dict(rows_by_exchange),
            "ok_rows_by_exchange": _counter_to_dict(ok_rows_by_exchange),
            "error_rows_by_exchange": _counter_to_dict(error_rows_by_exchange),
            "placeholder_rows_by_exchange": _counter_to_dict(placeholder_rows_by_exchange),
            "rows_by_granularity": _counter_to_dict(rows_by_granularity),
            "ok_rows_by_granularity": _counter_to_dict(ok_rows_by_granularity),
        },
        "clean_markets": {
            "two_exchange_bases": two_exchange_bases,
            "three_exchange_bases": three_exchange_bases,
            "two_exchange_full_coverage_1h4h_bases": two_exchange_full_coverage_1h4h_bases,
            "three_exchange_full_coverage_1h4h_bases": three_exchange_full_coverage_1h4h_bases,
            "two_exchange_full_coverage_all_timeframe_bases": two_exchange_full_coverage_all_timeframe_bases,
        },
        "top_ok_markets": [
            {"market": market, "ok_rows": int(count)}
            for market, count in ok_rows_by_market.most_common(30)
        ],
        "coverage_worst_slots": [
            {"slot": slot_key, **values}
            for slot_key, values in sorted(
                coverage_by_slot.items(),
                key=lambda item: (float(item[1]["coverage_ratio"]), item[0]),
            )[:30]
        ],
        "next_step_after_ready": (
            "Run fixed-signal PlanOnly for slow_liquidity_regime_breakout_retest on clean 1h/4h two-venue slice. Keep replay/grid/live/API/paper-forward blocked until fixed-signal gate passes."
            if accepted
            else "Do not replay/grid. Recollect or rescope slow-liquidity history to enough two-venue 1h/4h coverage before signal design."
        ),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate slow-liquidity OHLCV history data quality.")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-ok-rows", type=int, default=SlowLiquidityHistoryQualityConfig.min_ok_rows)
    parser.add_argument("--min-ok-bases", type=int, default=SlowLiquidityHistoryQualityConfig.min_ok_bases)
    parser.add_argument("--min-ok-exchanges", type=int, default=SlowLiquidityHistoryQualityConfig.min_ok_exchanges)
    parser.add_argument(
        "--min-ok-market-granularity-slots",
        type=int,
        default=SlowLiquidityHistoryQualityConfig.min_ok_market_granularity_slots,
    )
    parser.add_argument("--min-ok-slot-fraction", type=float, default=SlowLiquidityHistoryQualityConfig.min_ok_slot_fraction)
    parser.add_argument("--max-api-error-slot-rate", type=float, default=SlowLiquidityHistoryQualityConfig.max_api_error_slot_rate)
    parser.add_argument("--min-two-exchange-bases", type=int, default=SlowLiquidityHistoryQualityConfig.min_two_exchange_bases)
    parser.add_argument(
        "--min-two-exchange-full-coverage-1h4h-bases",
        type=int,
        default=SlowLiquidityHistoryQualityConfig.min_two_exchange_full_coverage_1h4h_bases,
    )
    parser.add_argument("--min-full-coverage-ratio", type=float, default=SlowLiquidityHistoryQualityConfig.min_full_coverage_ratio)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = SlowLiquidityHistoryQualityConfig(
        min_ok_rows=args.min_ok_rows,
        min_ok_bases=args.min_ok_bases,
        min_ok_exchanges=args.min_ok_exchanges,
        min_ok_market_granularity_slots=args.min_ok_market_granularity_slots,
        min_ok_slot_fraction=args.min_ok_slot_fraction,
        max_api_error_slot_rate=args.max_api_error_slot_rate,
        min_two_exchange_bases=args.min_two_exchange_bases,
        min_two_exchange_full_coverage_1h4h_bases=args.min_two_exchange_full_coverage_1h4h_bases,
        min_full_coverage_ratio=args.min_full_coverage_ratio,
    )
    input_path = Path(args.input_jsonl)
    manifest_path = Path(args.manifest)
    output_path = Path(args.output)
    result = evaluate_slow_liquidity_history_quality(load_jsonl(input_path), load_json(manifest_path), cfg)
    result["input_jsonl"] = str(input_path)
    result["manifest_path"] = str(manifest_path)
    result["output_path"] = str(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
