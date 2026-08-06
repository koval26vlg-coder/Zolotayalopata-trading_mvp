from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slow_liquidity_history_quality import (  # noqa: E402
    SlowLiquidityHistoryQualityConfig,
    evaluate_slow_liquidity_history_quality,
)


def ok_rows(exchange: str, base: str, granularity: str, *, start_ts: int = 0, count: int = 3) -> list[dict[str, object]]:
    interval = {"15m": 900, "1h": 3600, "4h": 14400}[granularity]
    end_ts = start_ts + interval * (count - 1)
    return [
        {
            "source": "slow_liquidity_history",
            "exchange": exchange,
            "symbol": f"{base}_USDT" if exchange == "gateio" else f"{base}USDT",
            "base": base,
            "quote": "USDT",
            "granularity": granularity,
            "job_key": f"{exchange}:{base}:{granularity}",
            "history_start_ts": start_ts,
            "history_start_iso": "1970-01-01T00:00:00Z",
            "history_end_ts": end_ts,
            "history_end_iso": "1970-01-01T00:00:00Z",
            "candle_ts": start_ts + interval * idx,
            "candle_iso": "1970-01-01T00:00:00Z",
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


def api_error_row(exchange: str, base: str, granularity: str) -> dict[str, object]:
    return {
        "source": "slow_liquidity_history",
        "exchange": exchange,
        "symbol": f"{base}_USDT" if exchange == "gateio" else f"{base}USDT",
        "base": base,
        "quote": "USDT",
        "granularity": granularity,
        "job_key": f"{exchange}:{base}:{granularity}",
        "history_start_ts": 0,
        "history_start_iso": "1970-01-01T00:00:00Z",
        "history_end_ts": 7200,
        "history_end_iso": "1970-01-01T02:00:00Z",
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


class SlowLiquidityHistoryQualityTests(unittest.TestCase):
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
                capture_output=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["metrics"]["line_count"], len(rows))
            self.assertFalse(payload["replay_allowed"])


if __name__ == "__main__":
    unittest.main()
