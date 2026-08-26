from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slow_liquidity_history_quality import (  # noqa: E402
    SlowLiquidityHistoryQualityConfig,
    evaluate_slow_liquidity_history_quality,
)
from listing_event_history_collector import Candle  # noqa: E402
from slow_liquidity_history_collector import (  # noqa: E402
    INTERVAL_SECONDS,
    UniverseAsset,
    build_initial_manifest,
    build_jobs,
    output_row,
)

PLAN_PATH = (
    ROOT.parents[1]
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
)

EXACT_QUALITY_CONTRACT_VERSION = "slow_liquidity_history_exact_v2"
FROZEN_HISTORY_ANCHOR_TS = int(
    datetime(2026, 8, 13, 0, 2, 3, tzinfo=timezone.utc).timestamp()
)


def canonical_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def fixture_symbol(exchange: str, base: str, quote: str = "USDT") -> str:
    return f"{base}_{quote}" if exchange == "gateio" else f"{base}{quote}"


def ok_rows(exchange: str, base: str, granularity: str, *, start_ts: int = 0, count: int = 3) -> list[dict[str, object]]:
    interval = {"15m": 900, "1h": 3600, "4h": 14400}[granularity]
    end_ts = start_ts + interval * (count - 1)
    return [
        {
            "source": "slow_liquidity_history",
            "exchange": exchange,
            "symbol": fixture_symbol(exchange, base),
            "base": base,
            "quote": "USDT",
            "granularity": granularity,
            "job_key": f"{exchange}:{fixture_symbol(exchange, base)}:{granularity}",
            "history_start_ts": start_ts,
            "history_start_iso": canonical_iso(start_ts),
            "history_end_ts": end_ts,
            "history_end_iso": canonical_iso(end_ts),
            "candle_ts": start_ts + interval * idx,
            "candle_iso": canonical_iso(start_ts + interval * idx),
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 100.0,
            "quote_volume": 100.0,
            "trade_count_if_available": None,
            "data_status": "ok",
            "error": "",
        }
        for idx in range(count)
    ]


def api_error_row(
    exchange: str,
    base: str,
    granularity: str,
    *,
    start_ts: int = 0,
    count: int = 3,
) -> dict[str, object]:
    interval = {"15m": 900, "1h": 3600, "4h": 14400}[granularity]
    end_ts = start_ts + interval * (count - 1)
    return {
        "source": "slow_liquidity_history",
        "exchange": exchange,
        "symbol": fixture_symbol(exchange, base),
        "base": base,
        "quote": "USDT",
        "granularity": granularity,
        "job_key": f"{exchange}:{fixture_symbol(exchange, base)}:{granularity}",
        "history_start_ts": start_ts,
        "history_start_iso": canonical_iso(start_ts),
        "history_end_ts": end_ts,
        "history_end_iso": canonical_iso(end_ts),
        "candle_ts": None,
        "candle_iso": None,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
        "quote_volume": None,
        "trade_count_if_available": None,
        "data_status": "api_error",
        "error": "fixture",
    }


def frozen_quality_contract() -> tuple[tuple[str, ...], SlowLiquidityHistoryQualityConfig]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    thresholds = plan["data_quality_after_success"]["thresholds"]
    return (
        tuple(plan["universe"]["bases"]),
        SlowLiquidityHistoryQualityConfig(
            min_ok_rows=int(thresholds["min_ok_rows"]),
            min_ok_bases=int(thresholds["min_ok_bases"]),
            min_ok_exchanges=int(thresholds["min_ok_exchanges"]),
            min_ok_market_granularity_slots=int(
                thresholds["min_ok_market_granularity_slots"]
            ),
            min_ok_slot_fraction=float(thresholds["min_ok_slot_fraction"]),
            max_api_error_slot_rate=float(thresholds["max_api_error_slot_rate"]),
            min_two_exchange_bases=int(thresholds["min_two_exchange_bases"]),
            min_two_exchange_full_coverage_1h4h_bases=int(
                thresholds["min_two_exchange_full_coverage_1h4h_bases"]
            ),
            min_full_coverage_ratio=float(thresholds["min_full_coverage_ratio"]),
            max_duplicate_candles=int(thresholds["duplicate_candles"]),
        ),
    )


def frozen_scope_fixture(
    bases: tuple[str, ...],
    *,
    missing_gate_bases: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    error_rows = 0
    candle_counts = {"1h": 56 * 24, "4h": 56 * 6}
    for base in bases:
        for exchange in ("mexc", "gateio"):
            for granularity, count in candle_counts.items():
                interval = {"1h": 3600, "4h": 14400}[granularity]
                raw_start = FROZEN_HISTORY_ANCHOR_TS - 56 * 86_400
                start_ts = ((raw_start + interval - 1) // interval) * interval
                if exchange == "gateio" and base in missing_gate_bases:
                    rows.append(
                        api_error_row(
                            exchange,
                            base,
                            granularity,
                            start_ts=start_ts,
                            count=count,
                        )
                    )
                    error_rows += 1
                else:
                    rows.extend(
                        ok_rows(
                            exchange,
                            base,
                            granularity,
                            start_ts=start_ts,
                            count=count,
                        )
                    )
    planned_slots = len(bases) * 2 * len(candle_counts)
    return rows, {
        "quality_contract_version": EXACT_QUALITY_CONTRACT_VERSION,
        "final": True,
        "selected_bases": list(bases),
        "exchanges": ["mexc", "gateio"],
        "granularities": ["1h", "4h"],
        "quote": "USDT",
        "history_days": 56,
        "history_anchor_ts": FROZEN_HISTORY_ANCHOR_TS,
        "history_anchor_iso": canonical_iso(FROZEN_HISTORY_ANCHOR_TS),
        "planned_market_granularity_requests": planned_slots,
        "completed_market_granularity_requests": planned_slots,
        "rows": len(rows),
        "ohlcv_rows": len(rows) - error_rows,
        "placeholder_rows": error_rows,
        "errors": error_rows,
        "data_status_counts": {
            "ok": len(rows) - error_rows,
            **({"api_error": error_rows} if error_rows else {}),
        },
    }


def relaxed_two_venue_fixture() -> tuple[
    list[dict[str, object]],
    dict[str, object],
    SlowLiquidityHistoryQualityConfig,
]:
    rows: list[dict[str, object]] = []
    for exchange in ("mexc", "gateio"):
        for granularity in ("1h", "4h"):
            rows.extend(ok_rows(exchange, "AAA", granularity))
    manifest: dict[str, object] = {
        "final": True,
        "selected_bases": ["AAA"],
        "exchanges": ["mexc", "gateio"],
        "granularities": ["1h", "4h"],
        "quote": "USDT",
        "planned_market_granularity_requests": 4,
        "completed_market_granularity_requests": 4,
        "ohlcv_rows": len(rows),
        "placeholder_rows": 0,
        "errors": 0,
    }
    config = SlowLiquidityHistoryQualityConfig(
        min_ok_rows=12,
        min_ok_bases=1,
        min_ok_exchanges=2,
        min_ok_market_granularity_slots=4,
        min_ok_slot_fraction=1.0,
        max_api_error_slot_rate=0.0,
        min_two_exchange_bases=1,
        min_two_exchange_full_coverage_1h4h_bases=1,
        min_full_coverage_ratio=1.0,
    )
    return rows, manifest, config


class SlowLiquidityHistoryQualityTests(unittest.TestCase):
    def test_collector_wall_clock_range_is_quality_compatible(self) -> None:
        history_days = 56
        raw_start = 1_800_123
        raw_end = raw_start + history_days * 86_400
        jobs = build_jobs(
            [UniverseAsset(rank=1, name="Edge", base="EDGE", coin_id="edge")],
            exchanges=["mexc", "gateio"],
            granularities=["1h", "4h"],
            quote="USDT",
            start_ts=raw_start,
            end_ts=raw_end,
        )
        rows: list[dict[str, object]] = []
        for job in jobs:
            interval = INTERVAL_SECONDS[job.granularity]
            for timestamp in range(job.start_ts, job.end_ts + 1, interval):
                rows.append(
                    output_row(
                        job,
                        candle=Candle(
                            ts=timestamp,
                            open=1.0,
                            high=1.1,
                            low=0.9,
                            close=1.0,
                            volume=100.0,
                            quote_volume=100.0,
                            trade_count=1,
                        ),
                        data_status="ok",
                    )
                )
        manifest = build_initial_manifest(
            run_id="synthetic",
            universe_path=Path("universe.csv"),
            output_jsonl=Path("ohlcv.jsonl"),
            manifest_path=Path("manifest.json"),
            assets=[UniverseAsset(rank=1, name="Edge", base="EDGE", coin_id="edge")],
            jobs=jobs,
            exchanges=["mexc", "gateio"],
            granularities=["1h", "4h"],
            history_days=history_days,
            history_anchor_ts=raw_end,
            candles_per_request=1000,
            approval_text="synthetic",
            resumed_existing_stats={},
        )
        manifest.update(
            {
                "final": True,
                "completed_market_granularity_requests": 4,
                "rows": len(rows),
                "ohlcv_rows": len(rows),
                "placeholder_rows": 0,
                "errors": 0,
                "data_status_counts": {"ok": len(rows)},
            }
        )
        config = SlowLiquidityHistoryQualityConfig(
            min_ok_rows=len(rows),
            min_ok_bases=1,
            min_ok_exchanges=2,
            min_ok_market_granularity_slots=4,
            min_ok_slot_fraction=1.0,
            max_api_error_slot_rate=0.0,
            min_two_exchange_bases=1,
            min_two_exchange_full_coverage_1h4h_bases=1,
            min_full_coverage_ratio=1.0,
        )

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertTrue(result["accepted"], result["reasons"])
        self.assertEqual(result["metrics"]["history_window_mismatch_slots"], 0)

    def test_rejects_shortened_range_that_claims_56_day_history(self) -> None:
        rows: list[dict[str, object]] = []
        shortened_days = 47
        for exchange in ("mexc", "gateio"):
            for granularity in ("1h", "4h"):
                count = shortened_days * (24 if granularity == "1h" else 6)
                rows.extend(ok_rows(exchange, "AAA", granularity, count=count))
        manifest = {
            "final": True,
            "selected_bases": ["AAA"],
            "exchanges": ["mexc", "gateio"],
            "granularities": ["1h", "4h"],
            "quote": "USDT",
            "history_days": 56,
            "planned_market_granularity_requests": 4,
            "completed_market_granularity_requests": 4,
            "ohlcv_rows": len(rows),
            "placeholder_rows": 0,
            "errors": 0,
        }
        config = SlowLiquidityHistoryQualityConfig(
            min_ok_rows=1,
            min_ok_bases=1,
            min_ok_exchanges=2,
            min_ok_market_granularity_slots=4,
            min_ok_slot_fraction=1.0,
            max_api_error_slot_rate=0.0,
            min_two_exchange_bases=1,
            min_two_exchange_full_coverage_1h4h_bases=1,
            min_full_coverage_ratio=1.0,
        )

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("history_window_mismatch", result["reasons"])
        self.assertEqual(result["metrics"]["history_window_mismatch_slots"], 4)
        self.assertEqual(result["metrics"]["ok_rows"], 0)

    def test_frozen_scope_rejects_any_foreign_row_dimensions(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        rows[0]["base"] = "FOREIGN"
        rows[0]["symbol"] = "FOREIGNUSDT"
        rows[0]["job_key"] = "mexc:FOREIGNUSDT:1h"
        rows[1]["exchange"] = "bitget"
        rows[1]["job_key"] = f"bitget:{bases[0]}USDT:1h"
        rows[2]["granularity"] = "15m"
        rows[2]["job_key"] = f"mexc:{bases[0]}USDT:15m"
        rows[3]["source"] = "foreign_history"

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("unexpected_bases", result["reasons"])
        self.assertIn("unexpected_exchanges", result["reasons"])
        self.assertIn("unexpected_granularities", result["reasons"])
        self.assertIn("unexpected_sources", result["reasons"])

    def test_rejects_quote_symbol_and_job_key_mismatches(self) -> None:
        cases = (
            ("quote", "USDC", "unexpected_quotes"),
            ("symbol", "WRONGUSDT", "unexpected_symbols"),
            ("job_key", "mexc:WRONGUSDT:1h", "unexpected_job_keys"),
        )
        for field, value, reason in cases:
            with self.subTest(reason=reason):
                rows, manifest, config = relaxed_two_venue_fixture()
                rows[0][field] = value

                result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

                self.assertFalse(result["accepted"])
                self.assertIn(reason, result["reasons"])
                self.assertEqual(result["metrics"][reason], 1)
                self.assertEqual(result["metrics"]["ok_rows"], 11)

    def test_rejects_non_finite_or_non_numeric_ohlcv(self) -> None:
        cases = (
            ("open", float("nan")),
            ("high", float("inf")),
            ("low", "0.9"),
            ("close", None),
            ("volume", True),
            ("quote_volume", float("-inf")),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                rows, manifest, config = relaxed_two_venue_fixture()
                rows[0][field] = value

                result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

                self.assertFalse(result["accepted"])
                self.assertIn("invalid_ohlcv_values", result["reasons"])
                self.assertEqual(result["metrics"]["invalid_ohlcv_values"], 1)
                self.assertEqual(result["metrics"]["ok_rows"], 11)

    def test_rejects_nonpositive_prices_negative_volumes_and_impossible_ohlc(self) -> None:
        cases = (
            ("open", 0.0, "non_positive_prices"),
            ("volume", -1.0, "negative_volumes"),
            ("quote_volume", -1.0, "negative_volumes"),
            ("high", 0.8, "inconsistent_ohlc_rows"),
            ("low", 1.2, "inconsistent_ohlc_rows"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field, reason=reason):
                rows, manifest, config = relaxed_two_venue_fixture()
                rows[0][field] = value

                result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

                self.assertFalse(result["accepted"])
                self.assertIn(reason, result["reasons"])
                self.assertGreaterEqual(result["metrics"][reason], 1)
                self.assertEqual(result["metrics"]["ok_rows"], 11)

    def test_rejects_invalid_trade_count_and_nonempty_ok_error(self) -> None:
        cases = (
            ("trade_count_if_available", -1, "invalid_trade_counts"),
            ("trade_count_if_available", 1.5, "invalid_trade_counts"),
            ("error", "unexpected", "unexpected_ok_errors"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field, value=value):
                rows, manifest, config = relaxed_two_venue_fixture()
                rows[0][field] = value

                result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

                self.assertFalse(result["accepted"])
                self.assertIn(reason, result["reasons"])
                self.assertEqual(result["metrics"][reason], 1)

    def test_rejects_unknown_status_and_placeholder_with_market_data(self) -> None:
        rows, manifest, config = relaxed_two_venue_fixture()
        rows[0]["data_status"] = "unknown"
        rows[0]["error"] = "fixture"
        manifest["ohlcv_rows"] = 11
        manifest["placeholder_rows"] = 1
        manifest["errors"] = 1

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("unexpected_data_statuses", result["reasons"])
        self.assertIn("placeholder_with_market_data", result["reasons"])
        self.assertEqual(result["metrics"]["unexpected_data_statuses"], 1)
        self.assertEqual(result["metrics"]["placeholder_with_market_data"], 1)

    def test_frozen_production_thresholds_accept_clean_nine_base_scope(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["metrics"]["ok_rows"], 30_240)
        self.assertEqual(result["metrics"]["ok_market_granularity_slots"], 36)
        self.assertEqual(result["metrics"]["two_exchange_bases"], 9)
        self.assertEqual(
            result["metrics"]["two_exchange_full_coverage_1h4h_bases"], 9
        )

    def test_exact_contract_rejects_stale_full_length_history(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        manifest["history_anchor_ts"] = FROZEN_HISTORY_ANCHOR_TS + 7 * 86_400
        manifest["history_anchor_iso"] = canonical_iso(
            int(manifest["history_anchor_ts"])
        )

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("history_anchor_range_mismatch", result["reasons"])
        self.assertEqual(result["metrics"]["history_anchor_range_mismatch_slots"], 36)

    def test_exact_contract_rejects_manifest_status_count_swap(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        manifest["ohlcv_rows"] = int(manifest["ohlcv_rows"]) - 1
        manifest["placeholder_rows"] = int(manifest["placeholder_rows"]) + 1

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("manifest_ohlcv_rows_mismatch", result["reasons"])
        self.assertIn("manifest_placeholder_rows_mismatch", result["reasons"])

    def test_exact_contract_rejects_missing_completed_slot(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        rows = [
            row
            for row in rows
            if not (
                row["exchange"] == "gateio"
                and row["base"] == bases[0]
                and row["granularity"] == "4h"
            )
        ]
        manifest["rows"] = len(rows)
        manifest["ohlcv_rows"] = len(rows)
        manifest["data_status_counts"] = {"ok": len(rows)}

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("missing_expected_slots", result["reasons"])
        self.assertEqual(result["metrics"]["missing_expected_slots"], 1)

    def test_exact_contract_rejects_mixed_ok_and_placeholder_slot(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        first_row = rows[0]
        rows.append(
            api_error_row(
                str(first_row["exchange"]),
                str(first_row["base"]),
                str(first_row["granularity"]),
                start_ts=int(first_row["history_start_ts"]),
                count=56 * 24,
            )
        )
        manifest["rows"] = len(rows)
        manifest["placeholder_rows"] = 1
        manifest["errors"] = 1
        manifest["data_status_counts"] = {
            "ok": len(rows) - 1,
            "api_error": 1,
        }

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("mixed_slot_statuses", result["reasons"])
        self.assertEqual(result["metrics"]["mixed_slot_statuses"], 1)

    def test_exact_contract_rejects_timestamp_iso_substitution(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        mutated = copy.deepcopy(rows)
        mutated[0]["candle_iso"] = "2026-01-01T00:00:00Z"

        result = evaluate_slow_liquidity_history_quality(mutated, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("timestamp_iso_mismatches", result["reasons"])
        self.assertEqual(result["metrics"]["timestamp_iso_mismatches"], 1)

    def test_frozen_production_thresholds_allow_one_unavailable_base(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(
            bases, missing_gate_bases=frozenset({bases[-1]})
        )

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["metrics"]["two_exchange_bases"], 8)
        self.assertEqual(
            result["metrics"]["two_exchange_full_coverage_1h4h_bases"], 8
        )

    def test_frozen_production_thresholds_reject_two_unavailable_bases(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(
            bases, missing_gate_bases=frozenset(bases[-2:])
        )

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertEqual(result["metrics"]["two_exchange_bases"], 7)
        self.assertIn("min_two_exchange_bases", result["reasons"])
        self.assertIn(
            "min_two_exchange_full_coverage_1h4h_bases", result["reasons"]
        )

    def test_frozen_scope_rejects_complete_but_off_grid_timestamps(self) -> None:
        bases, config = frozen_quality_contract()
        rows, manifest = frozen_scope_fixture(bases)
        for row in rows:
            if row["data_status"] != "ok":
                continue
            row["candle_ts"] = int(row["candle_ts"]) + 123

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("off_grid_candles", result["reasons"])
        self.assertEqual(result["metrics"]["raw_ok_rows"], 30_240)
        self.assertEqual(result["metrics"]["ok_rows"], 0)
        self.assertEqual(result["metrics"]["off_grid_candles"], 30_240)
        self.assertEqual(
            result["metrics"]["two_exchange_full_coverage_1h4h_bases"], 0
        )

    def test_rejects_off_grid_history_range(self) -> None:
        rows, manifest, config = relaxed_two_venue_fixture()
        rows[0]["history_start_ts"] = 123

        result = evaluate_slow_liquidity_history_quality(rows, manifest, config)

        self.assertFalse(result["accepted"])
        self.assertIn("invalid_history_ranges", result["reasons"])
        self.assertEqual(result["metrics"]["invalid_history_ranges"], 1)

    def test_rejects_missing_invalid_and_out_of_range_candle_timestamps(self) -> None:
        cases = (
            (None, "missing_candle_timestamps"),
            ("3600", "invalid_candle_timestamps"),
            (10_800, "out_of_range_candles"),
        )
        for candle_ts, reason in cases:
            with self.subTest(reason=reason):
                rows: list[dict[str, object]] = []
                for exchange in ("mexc", "gateio"):
                    for granularity in ("1h", "4h"):
                        rows.extend(ok_rows(exchange, "AAA", granularity))
                rows[0]["candle_ts"] = candle_ts
                manifest = {
                    "final": True,
                    "selected_bases": ["AAA"],
                    "exchanges": ["mexc", "gateio"],
                    "granularities": ["1h", "4h"],
                    "planned_market_granularity_requests": 4,
                    "completed_market_granularity_requests": 4,
                    "ohlcv_rows": len(rows),
                    "placeholder_rows": 0,
                    "errors": 0,
                }

                result = evaluate_slow_liquidity_history_quality(
                    rows,
                    manifest,
                    SlowLiquidityHistoryQualityConfig(
                        min_ok_rows=11,
                        min_ok_bases=1,
                        min_ok_exchanges=2,
                        min_ok_market_granularity_slots=4,
                        min_ok_slot_fraction=1.0,
                        max_api_error_slot_rate=0.0,
                        min_two_exchange_bases=1,
                        min_two_exchange_full_coverage_1h4h_bases=1,
                    ),
                )

                self.assertFalse(result["accepted"])
                self.assertIn(reason, result["reasons"])
                self.assertEqual(result["metrics"][reason], 1)

    def test_rejects_inconsistent_history_range_within_slot(self) -> None:
        rows: list[dict[str, object]] = []
        for exchange in ("mexc", "gateio"):
            for granularity in ("1h", "4h"):
                rows.extend(ok_rows(exchange, "AAA", granularity))
        rows[1]["history_end_ts"] = int(rows[1]["history_end_ts"]) + 3600
        manifest = {
            "final": True,
            "selected_bases": ["AAA"],
            "exchanges": ["mexc", "gateio"],
            "granularities": ["1h", "4h"],
            "planned_market_granularity_requests": 4,
            "completed_market_granularity_requests": 4,
            "ohlcv_rows": len(rows),
            "placeholder_rows": 0,
            "errors": 0,
        }

        result = evaluate_slow_liquidity_history_quality(
            rows,
            manifest,
            SlowLiquidityHistoryQualityConfig(
                min_ok_rows=11,
                min_ok_bases=1,
                min_ok_exchanges=2,
                min_ok_market_granularity_slots=4,
                min_ok_slot_fraction=1.0,
                max_api_error_slot_rate=0.0,
                min_two_exchange_bases=1,
                min_two_exchange_full_coverage_1h4h_bases=1,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("inconsistent_slot_history_ranges", result["reasons"])
        self.assertEqual(
            result["metrics"]["inconsistent_slot_history_ranges"], 1
        )

    def test_accepts_clean_two_venue_1h4h_coverage_with_relaxed_thresholds(self) -> None:
        rows: list[dict[str, object]] = []
        for base in ("AAA", "BBB"):
            for exchange in ("mexc", "gateio"):
                for granularity in ("1h", "4h"):
                    rows.extend(ok_rows(exchange, base, granularity))
        rows.append(api_error_row("bitget", "AAA", "15m"))
        manifest = {
            "final": True,
            "selected_bases": ["AAA", "BBB"],
            "planned_market_granularity_requests": 9,
            "completed_market_granularity_requests": 9,
            "ohlcv_rows": len(rows) - 1,
            "placeholder_rows": 1,
            "errors": 1,
        }

        result = evaluate_slow_liquidity_history_quality(
            rows,
            manifest,
            SlowLiquidityHistoryQualityConfig(
                min_ok_rows=12,
                min_ok_bases=2,
                min_ok_exchanges=2,
                min_ok_market_granularity_slots=4,
                min_ok_slot_fraction=0.4,
                max_api_error_slot_rate=0.5,
                min_two_exchange_bases=2,
                min_two_exchange_full_coverage_1h4h_bases=2,
            ),
        )

        self.assertTrue(result["accepted"])
        self.assertTrue(result["fixed_signal_plan_allowed"])
        self.assertFalse(result["replay_allowed"])
        self.assertIn("15m_two_exchange_full_coverage_absent_use_1h4h_only", result["warnings"])

    def test_rejects_single_venue_coverage(self) -> None:
        rows: list[dict[str, object]] = []
        for base in ("AAA", "BBB"):
            for granularity in ("1h", "4h"):
                rows.extend(ok_rows("mexc", base, granularity))
        manifest = {
            "final": True,
            "selected_bases": ["AAA", "BBB"],
            "planned_market_granularity_requests": 4,
            "completed_market_granularity_requests": 4,
            "ohlcv_rows": len(rows),
            "placeholder_rows": 0,
            "errors": 0,
        }

        result = evaluate_slow_liquidity_history_quality(
            rows,
            manifest,
            SlowLiquidityHistoryQualityConfig(
                min_ok_rows=12,
                min_ok_bases=2,
                min_ok_exchanges=2,
                min_ok_market_granularity_slots=4,
                min_ok_slot_fraction=1.0,
                max_api_error_slot_rate=0.0,
                min_two_exchange_bases=1,
                min_two_exchange_full_coverage_1h4h_bases=1,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("min_ok_exchanges", result["reasons"])
        self.assertIn("min_two_exchange_bases", result["reasons"])

    def test_rejects_duplicate_candles(self) -> None:
        rows: list[dict[str, object]] = []
        for exchange in ("mexc", "gateio"):
            for granularity in ("1h", "4h"):
                rows.extend(ok_rows(exchange, "AAA", granularity))
        rows.append(dict(rows[0]))
        manifest = {
            "final": True,
            "selected_bases": ["AAA"],
            "planned_market_granularity_requests": 4,
            "completed_market_granularity_requests": 4,
            "ohlcv_rows": len(rows),
            "placeholder_rows": 0,
            "errors": 0,
        }

        result = evaluate_slow_liquidity_history_quality(
            rows,
            manifest,
            SlowLiquidityHistoryQualityConfig(
                min_ok_rows=12,
                min_ok_bases=1,
                min_ok_exchanges=2,
                min_ok_market_granularity_slots=4,
                min_ok_slot_fraction=1.0,
                max_api_error_slot_rate=0.0,
                min_two_exchange_bases=1,
                min_two_exchange_full_coverage_1h4h_bases=1,
                max_duplicate_candles=0,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("max_duplicate_candles", result["reasons"])
        self.assertEqual(result["metrics"]["duplicate_candles"], 1)

    def test_quality_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "ohlcv.jsonl"
            manifest_path = root / "manifest.json"
            output_path = root / "quality.json"
            rows: list[dict[str, object]] = []
            for exchange in ("mexc", "gateio"):
                for granularity in ("1h", "4h"):
                    rows.extend(ok_rows(exchange, "AAA", granularity))
            rows_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "final": True,
                        "selected_bases": ["AAA"],
                        "planned_market_granularity_requests": 4,
                        "completed_market_granularity_requests": 4,
                        "ohlcv_rows": len(rows),
                        "placeholder_rows": 0,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "slow_liquidity_history_quality.py"),
                    "--input-jsonl",
                    str(rows_path),
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                    "--min-ok-rows",
                    "12",
                    "--min-ok-bases",
                    "1",
                    "--min-ok-exchanges",
                    "2",
                    "--min-ok-market-granularity-slots",
                    "4",
                    "--min-ok-slot-fraction",
                    "1.0",
                    "--max-api-error-slot-rate",
                    "0.0",
                    "--min-two-exchange-bases",
                    "1",
                    "--min-two-exchange-full-coverage-1h4h-bases",
                    "1",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["metrics"]["line_count"], len(rows))
            self.assertFalse(payload["replay_allowed"])

    def test_wrapper_keeps_fixed_signal_blocked_until_official_identity(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "ohlcv.jsonl"
            manifest_path = root / "manifest.json"
            output_path = root / "quality.json"
            rows: list[dict[str, object]] = []
            for exchange in ("mexc", "gateio"):
                for granularity in ("1h", "4h"):
                    rows.extend(ok_rows(exchange, "AAA", granularity))
            rows_path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "final": True,
                        "selected_bases": ["AAA"],
                        "planned_market_granularity_requests": 4,
                        "completed_market_granularity_requests": 4,
                        "ohlcv_rows": len(rows),
                        "placeholder_rows": 0,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )

            wrapper = (
                ROOT.parents[1]
                / "tools"
                / "trading_slow_liquidity_history_data_quality.ps1"
            )
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(wrapper),
                    "-InputJsonl",
                    str(rows_path),
                    "-ManifestPath",
                    str(manifest_path),
                    "-OutputPath",
                    str(output_path),
                    "-MinOkRows",
                    "12",
                    "-MinOkBases",
                    "1",
                    "-MinOkExchanges",
                    "2",
                    "-MinOkMarketGranularitySlots",
                    "4",
                    "-MinOkSlotFraction",
                    "1.0",
                    "-MaxApiErrorSlotRate",
                    "0.0",
                    "-MinTwoExchangeBases",
                    "1",
                    "-MinTwoExchangeFullCoverage1h4hBases",
                    "1",
                    "-MinFullCoverageRatio",
                    "1.0",
                    "-MaxDuplicateCandles",
                    "0",
                    "-RequireOfficialIdentityAfterQuality",
                    "-Json",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            for value in (payload, persisted):
                self.assertTrue(value["accepted"])
                self.assertFalse(value["fixed_signal_plan_allowed"])
                self.assertFalse(value["normalizer_allowed"])
                self.assertTrue(value["identity_verification_required"])
                self.assertEqual(
                    value["decision"],
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
                )


if __name__ == "__main__":
    unittest.main()
