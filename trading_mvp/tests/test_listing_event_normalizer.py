from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing_event_normalizer import (  # noqa: E402
    accepted_markets_from_manifest,
    normalize_listing_history_events_planonly,
    normalize_listing_events_planonly,
    parse_symbol,
)


def write_calendar(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "event_id",
        "exchange",
        "base",
        "quote",
        "symbol",
        "listed_at_utc",
        "announcement_at_utc",
        "source_url",
        "source_type",
        "delisted_at_utc",
        "is_delisted",
        "first_trade_ts_utc",
        "survivorship_status",
        "listed_ts",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


class ListingEventNormalizerTests(unittest.TestCase):
    def test_parse_symbol_handles_mexc_and_gate(self) -> None:
        self.assertEqual(parse_symbol("mexc", "HYPEUSDT"), ("HYPE", "USDT"))
        self.assertEqual(parse_symbol("gateio", "HYPE_USDT"), ("HYPE", "USDT"))

    def test_accepted_markets_from_manifest_parses_exchange_symbols(self) -> None:
        manifest = {
            "accepted_markets": [
                "mexc:HYPEUSDT",
                "gateio:HYPE_USDT",
            ]
        }

        markets = accepted_markets_from_manifest(manifest)

        self.assertEqual([market.key for market in markets], ["gateio:HYPE_USDT", "mexc:HYPEUSDT"])
        self.assertEqual({market.base_key for market in markets}, {"gateio:HYPE:USDT", "mexc:HYPE:USDT"})

    def test_normalizer_rejects_when_listing_events_do_not_overlap_ws_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            summary = root / "calendar.summary.json"
            manifest = root / "manifest.json"
            output = root / "out.json"
            write_calendar(
                calendar,
                [
                    {
                        "event_id": "mexc:HYPEUSDT:listing",
                        "exchange": "mexc",
                        "base": "HYPE",
                        "quote": "USDT",
                        "symbol": "HYPEUSDT",
                        "listed_ts": "1710000000",
                        "listed_at_utc": "2024-03-09T16:00:00Z",
                        "is_delisted": "false",
                        "survivorship_status": "current_active_snapshot",
                    }
                ],
            )
            summary.write_text(json.dumps({"bias_control_pass": True}), encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "actual_first_ts": 1783144700,
                        "actual_last_ts": 1783317080,
                        "accepted_markets": ["mexc:HYPEUSDT"],
                    }
                ),
                encoding="utf-8",
            )

            result = normalize_listing_events_planonly(
                calendar_path=calendar,
                calendar_summary_path=summary,
                market_manifest_path=manifest,
                output_path=output,
                min_overlap_events=1,
                min_overlap_bases=1,
                min_overlap_exchanges=1,
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_NORMALIZER_PLANONLY_INSUFFICIENT_OVERLAP_NEEDS_EVENT_OHLCV_HISTORY")
            self.assertEqual(result["overlap"]["matched_current_market_events"], 1)
            self.assertEqual(result["overlap"]["matched_time_overlap_events"], 0)
            self.assertFalse(result["replay_allowed_now"])
            self.assertTrue(output.exists())

    def test_normalizer_allows_next_planonly_when_overlap_is_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            summary = root / "calendar.summary.json"
            manifest = root / "manifest.json"
            start = 2_000_000_000
            write_calendar(
                calendar,
                [
                    {
                        "event_id": "mexc:HYPEUSDT:listing",
                        "exchange": "mexc",
                        "base": "HYPE",
                        "quote": "USDT",
                        "symbol": "HYPEUSDT",
                        "listed_ts": str(start + 3600),
                        "listed_at_utc": "2033-05-18T04:33:20Z",
                        "is_delisted": "false",
                        "survivorship_status": "current_active_snapshot",
                    },
                    {
                        "event_id": "gateio:OLD_USDT:listing",
                        "exchange": "gateio",
                        "base": "OLD",
                        "quote": "USDT",
                        "symbol": "OLD_USDT",
                        "listed_ts": str(start + 7200),
                        "listed_at_utc": "2033-05-18T05:33:20Z",
                        "is_delisted": "true",
                        "survivorship_status": "current_non_tradable_snapshot",
                    },
                ],
            )
            summary.write_text(json.dumps({"bias_control_pass": True}), encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "actual_first_ts": start,
                        "actual_last_ts": start + 500_000,
                        "accepted_markets": ["mexc:HYPEUSDT", "gateio:OLD_USDT"],
                    }
                ),
                encoding="utf-8",
            )

            result = normalize_listing_events_planonly(
                calendar_path=calendar,
                calendar_summary_path=summary,
                market_manifest_path=manifest,
                min_overlap_events=2,
                min_overlap_bases=2,
                min_overlap_exchanges=2,
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY")
            self.assertEqual(result["overlap"]["matched_time_overlap_events"], 2)
            self.assertEqual(result["overlap"]["delisted_or_nontradable_overlap_events"], 1)
            self.assertTrue(result["replay_allowed_now"])

    def test_history_normalizer_allows_planonly_replay_from_accepted_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "ohlcv.jsonl"
            manifest = root / "manifest.json"
            output = root / "history_normalized.json"
            rows = []
            for exchange, symbol, base, event_ts in [
                ("mexc", "HYPEUSDT", "HYPE", 2_000_000_000),
                ("gateio", "OLD_USDT", "OLD", 2_000_010_000),
                ("bitget", "NEWUSDT", "NEW", 2_000_020_000),
            ]:
                for offset in (-3600, 0, 3600, 7200):
                    rows.append(
                        {
                            "exchange": exchange,
                            "symbol": symbol,
                            "base": base,
                            "quote": "USDT",
                            "event_id": f"{exchange}:{symbol}:listing",
                            "event_ts": event_ts,
                            "event_iso": "2033-05-18T04:33:20Z",
                            "window_start_ts": event_ts - 3600,
                            "window_end_ts": event_ts + 259200,
                            "granularity": "1h",
                            "candle_ts": event_ts + offset,
                            "candle_iso": "2033-05-18T04:33:20Z",
                            "open": 1.0,
                            "high": 1.1,
                            "low": 0.9,
                            "close": 1.0,
                            "volume": 10.0,
                            "quote_volume": 10.0,
                            "data_status": "ok",
                            "error": "",
                        }
                    )
            history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "run_id": "history-test",
                        "final": True,
                        "planned_event_granularity_requests": 3,
                        "completed_event_granularity_requests": 3,
                        "ohlcv_rows": len(rows),
                        "placeholder_rows": 0,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )

            result = normalize_listing_history_events_planonly(
                history_jsonl_path=history,
                history_manifest_path=manifest,
                output_path=output,
                min_history_events=3,
                min_history_bases=3,
                min_history_exchanges=3,
                max_single_exchange_event_fraction=0.34,
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY")
            self.assertEqual(result["source"], "listing_event_history")
            self.assertEqual(result["history_coverage"]["ok_events"], 3)
            self.assertEqual(result["history_coverage"]["ok_exchange_count"], 3)
            self.assertTrue(result["replay_allowed_now"])
            self.assertFalse(result["grid_allowed_now"])
            self.assertFalse(result["live_orders"])
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
