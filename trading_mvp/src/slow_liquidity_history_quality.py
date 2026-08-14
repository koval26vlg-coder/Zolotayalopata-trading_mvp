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

ALLOWED_DATA_STATUSES = frozenset({"ok", "api_error", "no_data_or_unmatched"})
EXACT_QUALITY_CONTRACT_VERSION = "slow_liquidity_history_exact_v2"
OHLC_FIELDS = ("open", "high", "low", "close")
VOLUME_FIELDS = ("volume", "quote_volume")
PLACEHOLDER_MARKET_FIELDS = (
    "candle_ts",
    "candle_iso",
    *OHLC_FIELDS,
    *VOLUME_FIELDS,
    "trade_count_if_available",
)


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
    max_duplicate_candles: int = 0
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


def _strict_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _canonical_iso(timestamp: int) -> str | None:
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return None


def _expected_symbol(exchange: str, base: str, quote: str) -> str:
    if not (exchange and base and quote):
        return ""
    return f"{base}_{quote}" if exchange == "gateio" else f"{base}{quote}"


def _aligned_history_range(
    row: dict[str, Any],
) -> tuple[int, int, int, int] | None:
    granularity = str(row.get("granularity") or "")
    interval = INTERVAL_SECONDS.get(granularity)
    if not interval:
        return None
    start_ts = _strict_int(row.get("history_start_ts"))
    end_ts = _strict_int(row.get("history_end_ts"))
    if start_ts is None or end_ts is None:
        return None
    if end_ts < start_ts:
        return None
    if start_ts % interval != 0 or end_ts % interval != 0:
        return None
    first_ts = -(-start_ts // interval) * interval
    last_ts = (end_ts // interval) * interval
    expected = 0 if last_ts < first_ts else ((last_ts - first_ts) // interval) + 1
    return first_ts, last_ts, interval, expected


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
    status_counts_by_slot: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    slot_meta: dict[tuple[str, str, str], dict[str, Any]] = {}
    aligned_range_by_slot: dict[tuple[str, str, str], tuple[int, int, int, int]] = {}
    invalid_history_slots: set[tuple[str, str, str]] = set()
    duplicate_candles = 0
    missing_candle_timestamps = 0
    invalid_candle_timestamps = 0
    off_grid_candles = 0
    out_of_range_candles = 0
    invalid_history_ranges = 0
    inconsistent_slot_history_ranges = 0
    history_window_mismatch_slots: set[tuple[str, str, str]] = set()
    history_anchor_range_mismatch_slots: set[tuple[str, str, str]] = set()
    timestamp_iso_mismatches = 0
    invalid_ohlcv_values = 0
    non_positive_prices = 0
    negative_volumes = 0
    inconsistent_ohlc_rows = 0
    invalid_trade_counts = 0
    unexpected_ok_errors = 0
    placeholder_with_market_data = 0
    valid_ok_rows = 0
    expected_bases = {
        str(value) for value in (manifest.get("selected_bases") or []) if str(value)
    }
    expected_exchanges = {
        str(value) for value in (manifest.get("exchanges") or []) if str(value)
    }
    expected_granularities = {
        str(value) for value in (manifest.get("granularities") or []) if str(value)
    }
    expected_quote = str(manifest.get("quote") or "USDT")
    quality_contract_version = str(manifest.get("quality_contract_version") or "")
    exact_quality_contract = (
        quality_contract_version == EXACT_QUALITY_CONTRACT_VERSION
    )
    unexpected_quality_contract_version = bool(quality_contract_version) and not exact_quality_contract
    manifest_history_days_raw = manifest.get("history_days")
    manifest_history_days = (
        _strict_int(manifest_history_days_raw)
        if manifest_history_days_raw is not None
        else None
    )
    invalid_manifest_history_days = (
        manifest_history_days_raw is not None
        and (manifest_history_days is None or manifest_history_days <= 0)
    )
    manifest_history_anchor_ts = _strict_int(manifest.get("history_anchor_ts"))
    manifest_history_anchor_iso = str(manifest.get("history_anchor_iso") or "")
    invalid_manifest_history_anchor = exact_quality_contract and (
        manifest_history_anchor_ts is None
        or _canonical_iso(manifest_history_anchor_ts) != manifest_history_anchor_iso
    )
    expected_range_by_granularity: dict[str, tuple[int, int]] = {}
    if (
        exact_quality_contract
        and manifest_history_anchor_ts is not None
        and manifest_history_days is not None
        and manifest_history_days > 0
    ):
        raw_start_ts = manifest_history_anchor_ts - manifest_history_days * 86_400
        for granularity in expected_granularities:
            interval = INTERVAL_SECONDS.get(granularity)
            if interval is None:
                continue
            expected_range_by_granularity[granularity] = (
                ((raw_start_ts + interval - 1) // interval) * interval,
                (manifest_history_anchor_ts // interval) * interval,
            )
    expected_slots = {
        (exchange, base, granularity)
        for exchange in expected_exchanges
        for base in expected_bases
        for granularity in expected_granularities
    }
    unexpected_bases: set[str] = set()
    unexpected_exchanges: set[str] = set()
    unexpected_granularities: set[str] = set()
    unexpected_sources: set[str] = set()
    unexpected_quotes: set[str] = set()
    unexpected_symbols: set[str] = set()
    unexpected_job_keys: set[str] = set()
    unexpected_data_statuses: set[str] = set()

    for row in rows:
        status = str(row.get("data_status") or "unknown")
        source = str(row.get("source") or "")
        exchange = str(row.get("exchange") or "")
        base = str(row.get("base") or "")
        quote = str(row.get("quote") or "")
        symbol = str(row.get("symbol") or "")
        granularity = str(row.get("granularity") or "")
        job_key = str(row.get("job_key") or "")
        slot = (exchange, base, granularity)
        market_key = f"{exchange}:{symbol or base}"
        expected_symbol = _expected_symbol(exchange, base, expected_quote)
        expected_job_key = (
            f"{exchange}:{expected_symbol}:{granularity}"
            if exchange and expected_symbol and granularity
            else ""
        )
        scope_valid = True

        if source != "slow_liquidity_history":
            unexpected_sources.add(source or "<missing>")
            scope_valid = False
        if expected_bases and base not in expected_bases:
            unexpected_bases.add(base or "<missing>")
            scope_valid = False
        if expected_exchanges and exchange not in expected_exchanges:
            unexpected_exchanges.add(exchange or "<missing>")
            scope_valid = False
        if expected_granularities and granularity not in expected_granularities:
            unexpected_granularities.add(granularity or "<missing>")
            scope_valid = False
        if quote != expected_quote:
            unexpected_quotes.add(quote or "<missing>")
            scope_valid = False
        if symbol != expected_symbol:
            unexpected_symbols.add(symbol or "<missing>")
            scope_valid = False
        if job_key != expected_job_key:
            unexpected_job_keys.add(job_key or "<missing>")
            scope_valid = False
        if status not in ALLOWED_DATA_STATUSES:
            unexpected_data_statuses.add(status)
            scope_valid = False

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
            status_counts_by_slot[slot][status] += 1

        if exact_quality_contract:
            for timestamp_field, iso_field in (
                ("history_start_ts", "history_start_iso"),
                ("history_end_ts", "history_end_iso"),
            ):
                timestamp = _strict_int(row.get(timestamp_field))
                if timestamp is None or _canonical_iso(timestamp) != row.get(iso_field):
                    timestamp_iso_mismatches += 1
            candle_timestamp = row.get("candle_ts")
            if candle_timestamp is None:
                if row.get("candle_iso") is not None:
                    timestamp_iso_mismatches += 1
            else:
                parsed_candle_timestamp = _strict_int(candle_timestamp)
                if (
                    parsed_candle_timestamp is None
                    or _canonical_iso(parsed_candle_timestamp) != row.get("candle_iso")
                ):
                    timestamp_iso_mismatches += 1

        aligned_range = _aligned_history_range(row)
        history_range_valid = aligned_range is not None
        if not history_range_valid:
            invalid_history_ranges += 1
            if exchange and base and granularity:
                invalid_history_slots.add(slot)
        elif scope_valid:
            if exact_quality_contract:
                expected_range = expected_range_by_granularity.get(granularity)
                if expected_range is None or aligned_range[:2] != expected_range:
                    history_anchor_range_mismatch_slots.add(slot)
                    invalid_history_slots.add(slot)
                    history_range_valid = False
            if manifest_history_days is not None and manifest_history_days > 0:
                interval = aligned_range[2]
                expected_candles = aligned_range[3]
                minimum_candles = (manifest_history_days * 86_400) // interval
                if expected_candles not in (minimum_candles, minimum_candles + 1):
                    history_window_mismatch_slots.add(slot)
                    invalid_history_slots.add(slot)
                    history_range_valid = False
            if slot in aligned_range_by_slot:
                if aligned_range_by_slot[slot] != aligned_range:
                    inconsistent_slot_history_ranges += 1
                    invalid_history_slots.add(slot)
                    history_range_valid = False
            else:
                aligned_range_by_slot[slot] = aligned_range
                slot_meta[slot] = row

        if status == "ok":
            row_contract_valid = True
            if row.get("error") not in (None, ""):
                unexpected_ok_errors += 1
                row_contract_valid = False

            numbers: dict[str, float] = {}
            for field in (*OHLC_FIELDS, *VOLUME_FIELDS):
                number = _finite_number(row.get(field))
                if number is None:
                    invalid_ohlcv_values += 1
                    row_contract_valid = False
                else:
                    numbers[field] = number

            if all(field in numbers for field in OHLC_FIELDS):
                for field in OHLC_FIELDS:
                    if numbers[field] <= 0:
                        non_positive_prices += 1
                        row_contract_valid = False
                if not (
                    numbers["low"] <= numbers["open"] <= numbers["high"]
                    and numbers["low"] <= numbers["close"] <= numbers["high"]
                    and numbers["low"] <= numbers["high"]
                ):
                    inconsistent_ohlc_rows += 1
                    row_contract_valid = False

            for field in VOLUME_FIELDS:
                if field in numbers and numbers[field] < 0:
                    negative_volumes += 1
                    row_contract_valid = False

            trade_count = row.get("trade_count_if_available")
            if trade_count is not None:
                parsed_trade_count = _strict_int(trade_count)
                if parsed_trade_count is None or parsed_trade_count < 0:
                    invalid_trade_counts += 1
                    row_contract_valid = False

            if not (scope_valid and history_range_valid and row_contract_valid):
                continue
            assert aligned_range is not None

            candle_ts = row.get("candle_ts")
            if candle_ts is None:
                missing_candle_timestamps += 1
                continue
            ts = _strict_int(candle_ts)
            if ts is None:
                invalid_candle_timestamps += 1
                continue
            first_ts, last_ts, interval, _ = aligned_range
            if ts % interval != 0:
                off_grid_candles += 1
                continue
            if ts < first_ts or ts > last_ts:
                out_of_range_candles += 1
                continue

            valid_ok_rows += 1
            ok_bases.add(base)
            ok_exchanges.add(exchange)
            ok_slots.add(slot)
            ok_exchanges_by_base[base].add(exchange)
            ok_granularities_by_base_exchange[(base, exchange)].add(granularity)
            ok_rows_by_exchange[exchange] += 1
            ok_rows_by_granularity[granularity] += 1
            ok_rows_by_market[market_key] += 1
            if ts in candle_ts_by_slot[slot]:
                duplicate_candles += 1
            candle_ts_by_slot[slot].add(ts)
        else:
            placeholder_rows_by_exchange[exchange] += 1
            if any(row.get(field) is not None for field in PLACEHOLDER_MARKET_FIELDS):
                placeholder_with_market_data += 1
                continue
            if not (scope_valid and history_range_valid):
                continue
            if status == "api_error":
                error_rows_by_exchange[exchange] += 1
                error_slots.add(slot)

    missing_expected_slots = expected_slots - observed_slots if exact_quality_contract else set()
    mixed_slot_statuses = {
        slot
        for slot, counts in status_counts_by_slot.items()
        if counts.get("ok", 0) > 0
        and sum(count for status, count in counts.items() if status != "ok") > 0
    }
    duplicate_placeholder_slots = {
        slot
        for slot, counts in status_counts_by_slot.items()
        if counts.get("ok", 0) == 0 and sum(counts.values()) > 1
    }

    invalid_manifest_count_fields: list[str] = []

    def manifest_count(name: str, default: int = 0) -> int:
        raw_value = manifest.get(name)
        if exact_quality_contract:
            parsed = _strict_int(raw_value)
            if parsed is None or parsed < 0:
                invalid_manifest_count_fields.append(name)
                return default
            return parsed
        try:
            return int(raw_value or default)
        except (TypeError, ValueError):
            return default

    planned_requests = manifest_count(
        "planned_market_granularity_requests", len(observed_slots)
    )
    completed_requests = manifest_count("completed_market_granularity_requests")
    selected_bases = int(len(manifest.get("selected_bases") or []) or len(observed_bases))
    manifest_rows = manifest_count("rows")
    manifest_ohlcv_rows = manifest_count("ohlcv_rows")
    manifest_placeholder_rows = manifest_count("placeholder_rows")
    manifest_errors = manifest_count("errors")
    expected_line_count = manifest_ohlcv_rows + manifest_placeholder_rows
    line_count = len(rows)
    raw_ok_rows = int(status_counts.get("ok", 0))
    ok_rows = valid_ok_rows
    api_error_rows = int(status_counts.get("api_error", 0))
    actual_placeholder_rows = line_count - raw_ok_rows
    manifest_status_counts_valid = True
    manifest_status_counts: dict[str, int] = {}
    raw_manifest_status_counts = manifest.get("data_status_counts")
    if exact_quality_contract:
        if not isinstance(raw_manifest_status_counts, dict):
            manifest_status_counts_valid = False
        else:
            for key, value in raw_manifest_status_counts.items():
                parsed = _strict_int(value)
                if not isinstance(key, str) or parsed is None or parsed < 0:
                    manifest_status_counts_valid = False
                    break
                if parsed:
                    manifest_status_counts[key] = parsed
    actual_status_counts = {
        key: int(value) for key, value in status_counts.items() if int(value)
    }

    ok_slot_count = len(ok_slots)
    ok_slot_fraction = _safe_div(ok_slot_count, planned_requests)
    api_error_slot_count = len(error_slots) if error_slots else api_error_rows
    api_error_slot_rate = _safe_div(api_error_slot_count, planned_requests)
    two_exchange_bases = _sorted_strings(base for base, exchanges in ok_exchanges_by_base.items() if len(exchanges) >= 2)
    three_exchange_bases = _sorted_strings(base for base, exchanges in ok_exchanges_by_base.items() if len(exchanges) >= 3)

    coverage_by_slot: dict[str, dict[str, Any]] = {}
    full_coverage_slots: set[tuple[str, str, str]] = set()
    partial_coverage_slots: set[tuple[str, str, str]] = set()
    coverage_slots = set(candle_ts_by_slot) | set(aligned_range_by_slot)
    for slot in coverage_slots:
        timestamps = candle_ts_by_slot.get(slot, set())
        aligned_range = aligned_range_by_slot.get(slot)
        expected = aligned_range[3] if aligned_range is not None else 0
        actual = len(timestamps)
        coverage_ratio = _safe_div(actual, expected)
        slot_key = ":".join(slot)
        coverage_by_slot[slot_key] = {
            "actual_candles": actual,
            "expected_candles": expected,
            "coverage_ratio": coverage_ratio,
        }
        if (
            slot not in invalid_history_slots
            and expected > 0
            and coverage_ratio >= cfg.min_full_coverage_ratio
        ):
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
    if unexpected_quality_contract_version:
        reasons.append("unexpected_quality_contract_version")
    if cfg.require_manifest_final and manifest.get("final") is not True:
        reasons.append("manifest_not_final")
    if cfg.require_completed_requests and completed_requests < planned_requests:
        reasons.append("incomplete_market_granularity_requests")
    if cfg.require_line_count_match_manifest and line_count != expected_line_count:
        reasons.append("line_count_mismatch_manifest")
    if exact_quality_contract:
        if invalid_manifest_count_fields:
            reasons.append("invalid_manifest_count_fields")
        if planned_requests != len(expected_slots):
            reasons.append("manifest_planned_requests_mismatch")
        if completed_requests != planned_requests:
            reasons.append("manifest_completed_requests_mismatch")
        if manifest_rows != line_count:
            reasons.append("manifest_rows_mismatch")
        if manifest_ohlcv_rows != raw_ok_rows:
            reasons.append("manifest_ohlcv_rows_mismatch")
        if manifest_placeholder_rows != actual_placeholder_rows:
            reasons.append("manifest_placeholder_rows_mismatch")
        if manifest_errors != api_error_rows:
            reasons.append("manifest_errors_mismatch")
        if not manifest_status_counts_valid:
            reasons.append("invalid_manifest_status_counts")
        elif manifest_status_counts != actual_status_counts:
            reasons.append("manifest_status_counts_mismatch")
        if invalid_manifest_history_anchor:
            reasons.append("invalid_manifest_history_anchor")
        if missing_expected_slots:
            reasons.append("missing_expected_slots")
        if mixed_slot_statuses:
            reasons.append("mixed_slot_statuses")
        if duplicate_placeholder_slots:
            reasons.append("duplicate_placeholder_slots")
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
    if duplicate_candles > cfg.max_duplicate_candles:
        reasons.append("max_duplicate_candles")
    if missing_candle_timestamps:
        reasons.append("missing_candle_timestamps")
    if invalid_candle_timestamps:
        reasons.append("invalid_candle_timestamps")
    if off_grid_candles:
        reasons.append("off_grid_candles")
    if out_of_range_candles:
        reasons.append("out_of_range_candles")
    if invalid_history_ranges:
        reasons.append("invalid_history_ranges")
    if inconsistent_slot_history_ranges:
        reasons.append("inconsistent_slot_history_ranges")
    if invalid_manifest_history_days:
        reasons.append("invalid_manifest_history_days")
    if history_window_mismatch_slots:
        reasons.append("history_window_mismatch")
    if history_anchor_range_mismatch_slots:
        reasons.append("history_anchor_range_mismatch")
    if timestamp_iso_mismatches:
        reasons.append("timestamp_iso_mismatches")
    if unexpected_bases:
        reasons.append("unexpected_bases")
    if unexpected_exchanges:
        reasons.append("unexpected_exchanges")
    if unexpected_granularities:
        reasons.append("unexpected_granularities")
    if unexpected_sources:
        reasons.append("unexpected_sources")
    if unexpected_quotes:
        reasons.append("unexpected_quotes")
    if unexpected_symbols:
        reasons.append("unexpected_symbols")
    if unexpected_job_keys:
        reasons.append("unexpected_job_keys")
    if unexpected_data_statuses:
        reasons.append("unexpected_data_statuses")
    if invalid_ohlcv_values:
        reasons.append("invalid_ohlcv_values")
    if non_positive_prices:
        reasons.append("non_positive_prices")
    if negative_volumes:
        reasons.append("negative_volumes")
    if inconsistent_ohlc_rows:
        reasons.append("inconsistent_ohlc_rows")
    if invalid_trade_counts:
        reasons.append("invalid_trade_counts")
    if unexpected_ok_errors:
        reasons.append("unexpected_ok_errors")
    if placeholder_with_market_data:
        reasons.append("placeholder_with_market_data")
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
            "quality_contract_version": quality_contract_version,
            "exact_quality_contract": exact_quality_contract,
            "selected_bases": selected_bases,
            "planned_market_granularity_requests": planned_requests,
            "completed_market_granularity_requests": completed_requests,
            "line_count": line_count,
            "expected_line_count_from_manifest": expected_line_count,
            "line_count_matches_manifest": line_count == expected_line_count,
            "manifest_rows": manifest_rows,
            "manifest_ohlcv_rows": manifest_ohlcv_rows,
            "manifest_placeholder_rows": manifest_placeholder_rows,
            "manifest_errors": manifest_errors,
            "raw_ok_rows": raw_ok_rows,
            "ok_rows": ok_rows,
            "invalid_ok_rows": raw_ok_rows - ok_rows,
            "api_error_rows": api_error_rows,
            "placeholder_rows": actual_placeholder_rows,
            "manifest_status_counts_match": (
                manifest_status_counts_valid
                and manifest_status_counts == actual_status_counts
            ),
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
            "missing_candle_timestamps": missing_candle_timestamps,
            "invalid_candle_timestamps": invalid_candle_timestamps,
            "off_grid_candles": off_grid_candles,
            "out_of_range_candles": out_of_range_candles,
            "invalid_history_ranges": invalid_history_ranges,
            "inconsistent_slot_history_ranges": inconsistent_slot_history_ranges,
            "manifest_history_days": manifest_history_days,
            "history_window_mismatch_slots": len(history_window_mismatch_slots),
            "manifest_history_anchor_ts": manifest_history_anchor_ts,
            "history_anchor_range_mismatch_slots": len(
                history_anchor_range_mismatch_slots
            ),
            "timestamp_iso_mismatches": timestamp_iso_mismatches,
            "expected_slots": len(expected_slots),
            "missing_expected_slots": len(missing_expected_slots),
            "mixed_slot_statuses": len(mixed_slot_statuses),
            "duplicate_placeholder_slots": len(duplicate_placeholder_slots),
            "unexpected_bases": len(unexpected_bases),
            "unexpected_exchanges": len(unexpected_exchanges),
            "unexpected_granularities": len(unexpected_granularities),
            "unexpected_sources": len(unexpected_sources),
            "unexpected_quotes": len(unexpected_quotes),
            "unexpected_symbols": len(unexpected_symbols),
            "unexpected_job_keys": len(unexpected_job_keys),
            "unexpected_data_statuses": len(unexpected_data_statuses),
            "invalid_ohlcv_values": invalid_ohlcv_values,
            "non_positive_prices": non_positive_prices,
            "negative_volumes": negative_volumes,
            "inconsistent_ohlc_rows": inconsistent_ohlc_rows,
            "invalid_trade_counts": invalid_trade_counts,
            "unexpected_ok_errors": unexpected_ok_errors,
            "placeholder_with_market_data": placeholder_with_market_data,
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
        "scope_validation": {
            "expected_bases": sorted(expected_bases),
            "expected_exchanges": sorted(expected_exchanges),
            "expected_granularities": sorted(expected_granularities),
            "expected_quote": expected_quote,
            "expected_source": "slow_liquidity_history",
            "unexpected_bases": sorted(unexpected_bases),
            "unexpected_exchanges": sorted(unexpected_exchanges),
            "unexpected_granularities": sorted(unexpected_granularities),
            "unexpected_sources": sorted(unexpected_sources),
            "unexpected_quotes": sorted(unexpected_quotes),
            "unexpected_symbols": sorted(unexpected_symbols),
            "unexpected_job_keys": sorted(unexpected_job_keys),
            "unexpected_data_statuses": sorted(unexpected_data_statuses),
        },
        "row_integrity": {
            "allowed_data_statuses": sorted(ALLOWED_DATA_STATUSES),
            "required_finite_ohlcv_fields": [*OHLC_FIELDS, *VOLUME_FIELDS],
            "positive_price_fields": [*OHLC_FIELDS],
            "nonnegative_volume_fields": [*VOLUME_FIELDS],
            "trade_count_optional_nonnegative_integer": True,
            "ok_error_must_be_empty": True,
            "placeholder_market_fields_must_be_null": [*PLACEHOLDER_MARKET_FIELDS],
            "history_window_matches_manifest_days": True,
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
    parser.add_argument("--max-duplicate-candles", type=int, default=SlowLiquidityHistoryQualityConfig.max_duplicate_candles)
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
        max_duplicate_candles=args.max_duplicate_candles,
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
