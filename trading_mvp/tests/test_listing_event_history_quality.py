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

from listing_event_history_quality import (  # noqa: E402
    ListingEventHistoryQualityConfig,
    evaluate_listing_event_history_quality,
)


def ok_row(exchange: str, symbol: str, base: str, event_idx: int, granularity: str = "5m") -> dict[str, object]:
    return {
        "exchange": exchange,
        "symbol": symbol,
        "base": base,
        "quote": "USDT",
        "event_id": f"{exchange}:{symbol}:listing:{event_idx}",
        "event_ts": 1700000000,
        "event_iso": "2023-11-14T22:13:20Z",
        "window_start_ts": 1699996400,
        "window_end_ts": 1700259200,
        "granularity": granularity,
        "candle_ts": 1700000000,
        "candle_iso": "2023-11-14T22:13:20Z",
        "open": 1.0,
        "high": 1.2,
        "low": 0.9,
        "close": 1.1,
        "volume": 100.0,
        "quote_volume": 110.0,
        "trade_count_if_available": 10,
        "data_status": "ok",
        "error": "",
    }


def placeholder_row(exchange: str, symbol: str, base: str, event_idx: int, granularity: str = "1h") -> dict[str, object]:
    return {
        "exchange": exchange,
        "symbol": symbol,
        "base": base,
        "quote": "USDT",
        "event_id": f"{exchange}:{symbol}:listing:{event_idx}",
        "event_ts": 1700000000,
        "event_iso": "2023-11-14T22:13:20Z",
        "window_start_ts": 1699996400,
        "window_end_ts": 1700259200,
        "granularity": granularity,
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


class ListingEventHistoryQualityTests(unittest.TestCase):
    def test_quality_accepts_two_exchange_coverage_with_relaxed_fixture_thresholds(self) -> None:
        rows = [
            ok_row("mexc", "AAAUSDT", "AAA", 1),
            ok_row("mexc", "BBBUSDT", "BBB", 2),
            ok_row("gateio", "CCC_USDT", "CCC", 3),
            ok_row("gateio", "DDD_USDT", "DDD", 4),
        ]
        manifest = {
            "final": True,
            "selected_events": 4,
            "planned_event_granularity_requests": 4,
            "completed_event_granularity_requests": 4,
            "ohlcv_rows": 4,
            "placeholder_rows": 0,
            "errors": 0,
        }
        result = evaluate_listing_event_history_quality(
            rows,
            manifest,
            ListingEventHistoryQualityConfig(
                min_ok_rows=4,
                min_ok_events=4,
                min_ok_bases=4,
                min_ok_exchanges=2,
                min_ok_event_granularity_slots=4,
                min_ok_event_fraction=1.0,
                min_ok_slot_fraction=1.0,
                max_api_error_slot_rate=0.0,
                max_single_exchange_ok_event_fraction=0.60,
            ),
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(result["decision"], "LISTING_EVENT_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_NORMALIZER")
        self.assertFalse(result["replay_allowed"])
        self.assertTrue(result["normalizer_allowed"])

    def test_quality_rejects_single_exchange_and_high_api_error_rate(self) -> None:
        rows = [
            ok_row("mexc", "AAAUSDT", "AAA", 1),
            ok_row("mexc", "BBBUSDT", "BBB", 2),
            placeholder_row("gateio", "CCC_USDT", "CCC", 3),
            placeholder_row("gateio", "DDD_USDT", "DDD", 4),
        ]
        manifest = {
            "final": True,
            "selected_events": 4,
            "planned_event_granularity_requests": 4,
            "completed_event_granularity_requests": 4,
            "ohlcv_rows": 2,
            "placeholder_rows": 2,
            "errors": 2,
        }
        result = evaluate_listing_event_history_quality(
            rows,
            manifest,
            ListingEventHistoryQualityConfig(
                min_ok_rows=2,
                min_ok_events=2,
                min_ok_bases=2,
                min_ok_exchanges=2,
                min_ok_event_granularity_slots=2,
                min_ok_event_fraction=0.50,
                min_ok_slot_fraction=0.50,
                max_api_error_slot_rate=0.25,
                max_single_exchange_ok_event_fraction=0.70,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("min_ok_exchanges", result["reasons"])
        self.assertIn("max_api_error_slot_rate", result["reasons"])
        self.assertIn("max_single_exchange_ok_event_fraction", result["reasons"])

    def test_quality_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "ohlcv.jsonl"
            manifest_path = root / "manifest.json"
            output_path = root / "quality.json"
            rows = [
                ok_row("mexc", "AAAUSDT", "AAA", 1),
                placeholder_row("gateio", "CCC_USDT", "CCC", 2),
            ]
            rows_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "final": True,
                        "selected_events": 2,
                        "planned_event_granularity_requests": 2,
                        "completed_event_granularity_requests": 2,
                        "ohlcv_rows": 1,
                        "placeholder_rows": 1,
                        "errors": 1,
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "listing_event_history_quality.py"),
                    "--input-jsonl",
                    str(rows_path),
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                    "--min-ok-rows",
                    "1",
                    "--min-ok-events",
                    "1",
                    "--min-ok-bases",
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
            self.assertEqual(payload["metrics"]["line_count"], 2)
            self.assertFalse(payload["replay_allowed"])


if __name__ == "__main__":
    unittest.main()
