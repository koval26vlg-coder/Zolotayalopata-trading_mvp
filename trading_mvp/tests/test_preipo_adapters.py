from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_adapters import (  # noqa: E402
    GatePreIPOAdapter,
    OkxPreIPOAdapter,
    normalize_gate_contract,
    normalize_market_snapshot,
    normalize_okx_contract,
    parse_official_announcement,
)


class PreIPOAdapterTests(unittest.TestCase):
    def test_okx_preipo_contract_is_normalized_without_crypto_listing_fields(self) -> None:
        contract = normalize_okx_contract(
            {
                "instType": "SWAP",
                "instId": "SPCX-USDT-SWAP",
                "uly": "SPCX-USDT",
                "baseCcy": "SPCX",
                "quoteCcy": "USDT",
                "state": "live",
                "ruleType": "pre_market",
                "isPreMarket": True,
                "listTime": "1780000000000",
                "preMktSwTime": "1780003600000",
                "ctVal": "1",
                "lever": "5",
            }
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.asset_class, "preipo_equity")
        self.assertEqual(contract.lifecycle_status, "preipo_continuous")
        self.assertEqual(contract.underlying_symbol, "SPCX")
        self.assertIsNone(contract.rebase_ts)
        self.assertEqual(contract.official_conversion_ts, 1_780_003_600.0)
        self.assertNotIn("official_spot_listing_ts", contract.to_dict())

    def test_gate_preipo_contract_requires_explicit_equity_marker(self) -> None:
        ordinary = normalize_gate_contract(
            {"name": "ABC_USDT", "status": "prelaunch", "base": "ABC", "quote": "USDT"}
        )
        self.assertIsNone(ordinary)

        contract = normalize_gate_contract(
            {
                "name": "UNITREE_USDT",
                "status": "prelaunch",
                "base": "UNITREE",
                "quote": "USDT",
                "preipo": True,
                "launch_time": 1_780_000_000,
                "rebase_time": 1_780_003_600,
                "maintenance_rate": "0.01",
                "taker_fee_rate": "0.00075",
            }
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.lifecycle_status, "scheduled")
        self.assertEqual(contract.rebase_ts, 1_780_003_600.0)
        self.assertIsNone(contract.official_conversion_ts)
        self.assertEqual(contract.taker_fee_bps, 7.5)

    def test_okx_snapshot_keeps_exchange_and_received_timestamps_and_sequence(self) -> None:
        events = normalize_market_snapshot(
            "okx",
            "SPCX-USDT-SWAP",
            {
                "arg": {"channel": "books", "instId": "SPCX-USDT-SWAP"},
                "data": [
                    {
                        "ts": "1780000123456",
                        "bids": [["10", "4"]],
                        "asks": [["10.1", "3"]],
                        "seqId": 12,
                    }
                ],
            },
            received_ts=1_780_000_130.0,
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_kind"], "bbo")
        self.assertEqual(event["exchange_ts"], 1_780_000_123.456)
        self.assertEqual(event["received_ts"], 1_780_000_130.0)
        self.assertEqual(event["bid"], 10.0)
        self.assertEqual(event["ask"], 10.1)
        self.assertEqual(event["sequence"], 12)

    def test_gate_ticker_snapshot_normalizes_mark_index_and_funding(self) -> None:
        events = normalize_market_snapshot(
            "gate",
            "UNITREE_USDT",
            {
                "channel": "futures.tickers",
                "result": {
                    "time": 1780000200,
                    "last": "11.0",
                    "highest_bid": "10.9",
                    "lowest_ask": "11.1",
                    "mark_price": "11.02",
                    "index_price": "10.98",
                    "funding_rate": "0.0001",
                    "open_interest": "120",
                },
            },
            received_ts=1_780_000_201.0,
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_kind"], "ticker")
        self.assertEqual(event["mark_price"], 11.02)
        self.assertEqual(event["index_price"], 10.98)
        self.assertEqual(event["funding_rate"], 0.0001)
        self.assertEqual(event["open_interest"], 120.0)

    def test_official_announcement_parser_delegates_to_preipo_event_contract(self) -> None:
        event = parse_official_announcement(
            {
                "venue": "gate",
                "source_url": "https://www.gate.com/announcements/article/101203",
                "contract_id": "UNITREE_USDT",
                "underlying_symbol": "UNITREE",
                "quote": "USDT",
                "official_first_trade_ts": 1_780_010_000,
            }
        )

        self.assertEqual(event.venue, "gate")
        self.assertTrue(event.acceptance_eligible)

    def test_adapter_endpoints_are_public_and_separate(self) -> None:
        self.assertEqual(OkxPreIPOAdapter.base_url, "https://www.okx.com")
        self.assertEqual(GatePreIPOAdapter.base_url, "https://api.gateio.ws/api/v4")
        self.assertIn("public", OkxPreIPOAdapter.ws_url)
        self.assertIn("ws", GatePreIPOAdapter.ws_url)


if __name__ == "__main__":
    unittest.main()
