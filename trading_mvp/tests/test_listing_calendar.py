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

from listing_calendar import (  # noqa: E402
    build_listing_event_calendar_file,
    rows_from_bitget_symbols,
    rows_from_gate_currency_pairs,
    rows_from_mexc_exchange_info,
    summarize_calendar,
)


MEXC_FIXTURE = {
    "symbols": [
        {
            "symbol": "HYPEUSDT",
            "status": "1",
            "baseAsset": "HYPE",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": True,
            "firstOpenTime": 1710000000000,
            "fullName": "Hyperliquid",
        },
        {
            "symbol": "OLDUSDT",
            "status": "0",
            "baseAsset": "OLD",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": False,
        },
        {
            "symbol": "BTCUSDT",
            "status": "1",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": True,
            "firstOpenTime": 1600000000000,
        },
    ]
}

GATE_FIXTURE = [
    {
        "id": "HYPE_USDT",
        "base": "HYPE",
        "base_name": "Hyperliquid",
        "quote": "USDT",
        "trade_status": "tradable",
        "type": "normal",
        "buy_start": 1710000100,
        "sell_start": 1710000000,
    },
    {
        "id": "OLD_USDT",
        "base": "OLD",
        "base_name": "Old Token",
        "quote": "USDT",
        "trade_status": "delisted",
        "type": "normal",
        "buy_start": 1700000000,
        "sell_start": 1700000000,
    },
    {
        "id": "BTC_USDT",
        "base": "BTC",
        "quote": "USDT",
        "trade_status": "tradable",
        "buy_start": 0,
        "sell_start": 0,
    },
]

BITGET_FIXTURE = {
    "code": "00000",
    "msg": "success",
    "data": [
        {
            "symbol": "HYPEUSDT",
            "baseCoin": "HYPE",
            "quoteCoin": "USDT",
            "status": "online",
            "openTime": "1710000000000",
            "offTime": "",
        },
        {
            "symbol": "OLDUSDT",
            "baseCoin": "OLD",
            "quoteCoin": "USDT",
            "status": "offline",
            "openTime": "1700000000000",
            "offTime": "1710000000000",
        },
        {
            "symbol": "BTCUSDT",
            "baseCoin": "BTC",
            "quoteCoin": "USDT",
            "status": "online",
            "openTime": "1600000000000",
            "offTime": "",
        },
    ],
}


class ListingCalendarTests(unittest.TestCase):
    def test_mexc_rows_use_first_open_time_and_universe_filter(self) -> None:
        rows = rows_from_mexc_exchange_info(MEXC_FIXTURE, universe_symbols={"HYPE", "OLD"})

        self.assertEqual([row["base"] for row in rows], ["HYPE", "OLD"])
        hype = rows[0]
        old = rows[1]
        self.assertEqual(hype["exchange"], "mexc")
        self.assertEqual(hype["listed_at_utc"], "2024-03-09T16:00:00Z")
        self.assertEqual(hype["listing_timestamp_source"], "firstOpenTime")
        self.assertEqual(hype["survivorship_status"], "current_active_snapshot")
        self.assertEqual(old["is_delisted"], "true")
        self.assertIn("missing_listing_timestamp", old["bias_flags"])

    def test_gate_rows_use_min_nonzero_buy_sell_start(self) -> None:
        rows = rows_from_gate_currency_pairs(GATE_FIXTURE, universe_symbols={"HYPE", "OLD"})

        self.assertEqual([row["base"] for row in rows], ["HYPE", "OLD"])
        hype = rows[0]
        old = rows[1]
        self.assertEqual(hype["exchange"], "gateio")
        self.assertEqual(hype["listed_at_utc"], "2024-03-09T16:00:00Z")
        self.assertEqual(hype["listing_timestamp_source"], "min_nonzero_buy_start_sell_start")
        self.assertEqual(old["is_delisted"], "true")
        self.assertEqual(old["survivorship_status"], "current_non_tradable_snapshot")

    def test_bitget_rows_use_open_time_and_off_time(self) -> None:
        rows = rows_from_bitget_symbols(BITGET_FIXTURE, universe_symbols={"HYPE", "OLD"})

        self.assertEqual([row["base"] for row in rows], ["HYPE", "OLD"])
        hype = rows[0]
        old = rows[1]
        self.assertEqual(hype["exchange"], "bitget")
        self.assertEqual(hype["listed_at_utc"], "2024-03-09T16:00:00Z")
        self.assertEqual(hype["listing_timestamp_source"], "openTime")
        self.assertEqual(hype["survivorship_status"], "current_active_snapshot")
        self.assertEqual(old["is_delisted"], "true")
        self.assertEqual(old["delisted_at_utc"], "2024-03-09T16:00:00Z")
        self.assertIn("non_tradable_current_status", old["bias_flags"])

    def test_summary_blocks_current_snapshot_without_delisted_coverage(self) -> None:
        rows = rows_from_mexc_exchange_info(MEXC_FIXTURE, universe_symbols={"HYPE"})
        rows.extend(rows_from_gate_currency_pairs(GATE_FIXTURE, universe_symbols={"HYPE"}))

        summary = summarize_calendar(rows, universe_size=1, quote="USDT")

        self.assertFalse(summary["bias_control_pass"])
        self.assertEqual(summary["decision"], "LISTING_EVENT_CALENDAR_PARTIAL_NEEDS_DELISTED_OR_NONTRADABLE_COVERAGE")
        self.assertIn("missing_delisted_or_nontradable_outcomes", summary["coverage_warnings"])
        self.assertEqual(summary["required_next_step"], "add_delisted_frozen_no_trade_event_source_before_backtest")

    def test_build_file_writes_csv_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe = root / "universe.csv"
            universe.write_text("symbol\nHYPE\nOLD\n", encoding="utf-8")
            output = root / "calendar.csv"
            summary_path = root / "calendar.summary.json"

            summary = build_listing_event_calendar_file(
                output_path=output,
                summary_path=summary_path,
                universe_path=universe,
                mexc_payload=MEXC_FIXTURE,
                gate_payload=GATE_FIXTURE,
                bitget_payload=BITGET_FIXTURE,
            )

            self.assertTrue(output.exists())
            self.assertTrue(summary_path.exists())
            self.assertEqual(summary["rows"], 6)
            self.assertFalse(summary["live_orders"])
            self.assertFalse(summary["api_keys"])
            persisted = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["output_path"], str(output))
            with output.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 6)
            self.assertIn("survivorship_status", rows[0])


if __name__ == "__main__":
    unittest.main()
