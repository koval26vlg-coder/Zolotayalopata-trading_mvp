from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import listing_momentum_exchange_expansion as expansion  # noqa: E402


BINANCE_FIXTURE = {
    "symbols": [
        {
            "symbol": "HYPEUSDT",
            "status": "TRADING",
            "baseAsset": "HYPE",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": True,
        },
        {
            "symbol": "OLDUSDT",
            "status": "BREAK",
            "baseAsset": "OLD",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": False,
        },
    ]
}

BYBIT_FIXTURE = {
    "retCode": 0,
    "result": {
        "category": "spot",
        "list": [
            {
                "symbol": "HYPEUSDT",
                "baseCoin": "HYPE",
                "quoteCoin": "USDT",
                "status": "Trading",
            },
            {
                "symbol": "OLDUSDT",
                "baseCoin": "OLD",
                "quoteCoin": "USDT",
                "status": "PreLaunch",
            },
        ],
    },
}

OKX_FIXTURE = {
    "code": "0",
    "data": [
        {
            "instType": "SPOT",
            "instId": "HYPE-USDT",
            "baseCcy": "HYPE",
            "quoteCcy": "USDT",
            "state": "live",
            "listTime": "1710000000000",
        },
        {
            "instType": "SPOT",
            "instId": "OLD-USDT",
            "baseCcy": "OLD",
            "quoteCcy": "USDT",
            "state": "suspend",
            "listTime": "1700000000000",
        },
    ],
}

BITGET_FIXTURE = {
    "code": "00000",
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
    ],
}


class ExpansionParserTests(unittest.TestCase):
    def test_binance_snapshot_uses_spot_permission_and_explicit_proxy_gap(self) -> None:
        rows = expansion.parse_binance_snapshot(BINANCE_FIXTURE)
        self.assertEqual([row["base"] for row in rows], ["HYPE", "OLD"])
        self.assertFalse(rows[0]["is_delisted"])
        self.assertTrue(rows[1]["is_delisted"])
        self.assertIsNone(rows[0]["listed_ts"])
        self.assertEqual(rows[0]["timestamp_quality"], "proxy_required")

    def test_bybit_spot_parser_is_fail_closed_for_missing_launch_time(self) -> None:
        rows = expansion.parse_bybit_snapshot(BYBIT_FIXTURE)
        self.assertEqual(rows[0]["symbol"], "HYPEUSDT")
        self.assertFalse(rows[0]["is_delisted"])
        self.assertIsNone(rows[0]["listed_ts"])
        self.assertTrue(rows[1]["is_delisted"])

    def test_okx_parser_uses_list_time_and_state(self) -> None:
        rows = expansion.parse_okx_snapshot(OKX_FIXTURE)
        self.assertEqual(rows[0]["listed_at_utc"], "2024-03-09T16:00:00Z")
        self.assertEqual(rows[0]["listing_timestamp_source"], "listTime_ms")
        self.assertFalse(rows[0]["is_delisted"])
        self.assertTrue(rows[1]["is_delisted"])

    def test_bitget_parser_marks_open_time_as_deprecated(self) -> None:
        rows = expansion.parse_bitget_snapshot(BITGET_FIXTURE)
        self.assertEqual(rows[0]["listed_at_utc"], "2024-03-09T16:00:00Z")
        self.assertEqual(rows[0]["listing_timestamp_source"], "openTime_ms_deprecated")
        self.assertTrue(rows[1]["is_delisted"])


class ExpansionOhlcvTests(unittest.TestCase):
    def test_all_supported_ohlcv_shapes_are_normalized(self) -> None:
        fixtures = {
            "binance": [[1710000000000, "1", "2", "0.5", "1.5", "10", 0, "20"]],
            "bybit": {"result": {"list": [["1710000000000", "1", "2", "0.5", "1.5", "10", "20"]]}},
            "okx": {"data": [["1710000000000", "1", "2", "0.5", "1.5", "10", "20"]]},
            "bitget": {"data": [["1710000000000", "1", "2", "0.5", "1.5", "10", "20"]]},
        }
        for venue, payload in fixtures.items():
            with self.subTest(venue=venue):
                rows = expansion._parse_ohlcv_rows(venue, payload)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["ts"], 1710000000)
                self.assertEqual(rows[0]["close"], 1.5)


class ExpansionReceiptTests(unittest.TestCase):
    def test_receipt_hash_round_trip(self) -> None:
        payload = {
            "schema": expansion.SCHEMA,
            "preflight_id": expansion.PREFLIGHT_ID,
            "contract": {"supported_venues": list(expansion.SUPPORTED_VENUES)},
            "venues": [],
            "status": "PASS",
        }
        payload["receipt_hash"] = expansion.canonical_hash(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "receipt.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = expansion.load_preflight(path)
        self.assertEqual(loaded["receipt_hash"], payload["receipt_hash"])

    def test_supported_venue_contract_is_exact(self) -> None:
        self.assertEqual(
            tuple(expansion.VENUE_CONFIGS),
            ("binance", "bybit", "okx", "bitget"),
        )
        self.assertEqual(expansion.MAX_REQUESTS, 8)
        self.assertEqual(expansion.QUOTE, "USDT")


if __name__ == "__main__":
    unittest.main()
