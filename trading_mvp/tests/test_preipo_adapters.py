from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_adapters import (  # noqa: E402
    BitmexPreIPOAdapter,
    GatePreIPOAdapter,
    KrakenPreIPOAdapter,
    OkxPreIPOAdapter,
    normalize_gate_contract,
    normalize_market_snapshot,
    normalize_okx_contract,
    parse_official_announcement,
)


class PreIPOAdapterTests(unittest.TestCase):
    def test_bitmex_l2_rows_are_reduced_to_executable_bbo(self) -> None:
        events = normalize_market_snapshot(
            "bitmex",
            "SPCXUSDT",
            {
                "table": "orderBookL2_25",
                "data": [
                    {"id": 101, "side": "Buy", "size": 4, "price": 10.0, "timestamp": "2026-06-01T04:00:00.000Z"},
                    {"id": 102, "side": "Buy", "size": 2, "price": 9.9, "timestamp": "2026-06-01T04:00:00.000Z"},
                    {"id": 201, "side": "Sell", "size": 3, "price": 10.1, "timestamp": "2026-06-01T04:00:00.000Z"},
                    {"id": 202, "side": "Sell", "size": 5, "price": 10.2, "timestamp": "2026-06-01T04:00:00.000Z"},
                ],
            },
            received_ts=1_780_000_130.0,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_kind"], "bbo")
        self.assertEqual(events[0]["bid"], 10.0)
        self.assertEqual(events[0]["bid_qty"], 4.0)
        self.assertEqual(events[0]["ask"], 10.1)
        self.assertEqual(events[0]["ask_qty"], 3.0)
        self.assertNotIn("sequence", events[0])

    def test_bitmex_trade_rows_keep_each_trade_and_exchange_timestamp(self) -> None:
        events = normalize_market_snapshot(
            "bitmex",
            "SPCXUSDT",
            {
                "table": "trade",
                "data": [
                    {
                        "trdMatchID": "trade-1",
                        "timestamp": "2026-06-01T04:00:01.000Z",
                        "side": "Buy",
                        "price": 10.2,
                        "size": 7,
                    }
                ],
            },
            received_ts=1_780_000_131.0,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_kind"], "trade")
        self.assertEqual(events[0]["last"], 10.2)
        self.assertEqual(events[0]["qty"], 7.0)
        self.assertEqual(events[0]["side"], "buy")
        self.assertEqual(events[0]["trade_id"], "trade-1")
        self.assertNotIn("sequence", events[0])
        self.assertNotEqual(events[0]["exchange_ts"], events[0]["received_ts"])

    def test_kraken_rest_book_and_ws_trade_are_normalized(self) -> None:
        book = normalize_market_snapshot(
            "kraken",
            "PF_SPACEXUSD",
            {
                "feed": "book_snapshot",
                "data": {
                    "orderBook": {
                        "bids": [{"price": "20.0", "qty": "4"}],
                        "asks": [{"price": "20.2", "qty": "5"}],
                    },
                    "serverTime": "2026-06-15T08:00:01.000Z",
                },
            },
            received_ts=1_780_000_140.0,
        )
        trades = normalize_market_snapshot(
            "kraken",
            "PF_SPACEXUSD",
            {
                "feed": "trade_snapshot",
                "product_id": "PF_SPACEXUSD",
                "trades": [
                    {"uid": 11, "time": 1_780_000_100_000, "side": "sell", "price": 20.1, "qty": 2}
                ],
            },
            received_ts=1_780_000_141.0,
        )

        self.assertEqual(book[0]["event_kind"], "bbo")
        self.assertEqual((book[0]["bid"], book[0]["ask"]), (20.0, 20.2))
        self.assertEqual(trades[0]["event_kind"], "trade")
        self.assertEqual(trades[0]["trade_id"], 11)
        self.assertEqual(trades[0]["side"], "sell")

    def test_kraken_ticker_response_does_not_relabel_other_contracts(self) -> None:
        events = normalize_market_snapshot(
            "kraken",
            "PF_SPACEXUSD",
            {
                "feed": "ticker",
                "data": {
                    "tickers": [
                        {"symbol": "PF_OTHERUSD", "last": 99.0},
                        {"symbol": "PF_SPACEXUSD", "last": 20.5},
                    ]
                },
            },
            received_ts=1_780_000_142.0,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["contract_id"], "PF_SPACEXUSD")
        self.assertEqual(events[0]["last"], 20.5)

    def test_gate_order_book_is_bbo_not_a_generic_ticker(self) -> None:
        events = normalize_market_snapshot(
            "gate",
            "UNITREE_USDT",
            {
                "channel": "futures.order_book",
                "result": {
                    "id": 17,
                    "current": 1_780_000_200_000,
                    "bids": [{"p": "11.0", "s": "6"}],
                    "asks": [{"p": "11.2", "s": "7"}],
                },
            },
            received_ts=1_780_000_201.0,
        )

        self.assertEqual(events[0]["event_kind"], "bbo")
        self.assertEqual(events[0]["bid"], 11.0)
        self.assertEqual(events[0]["ask"], 11.2)
        self.assertEqual(events[0]["sequence"], 17)

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

    def test_rest_clients_refuse_http_and_unlisted_hosts_before_network(self) -> None:
        class FailIfCalledSession:
            trust_env = True

            def get(self, *args, **kwargs):
                raise AssertionError("network must not be reached")

        for adapter_cls in (
            OkxPreIPOAdapter,
            GatePreIPOAdapter,
            BitmexPreIPOAdapter,
            KrakenPreIPOAdapter,
        ):
            adapter = adapter_cls(session=FailIfCalledSession())
            with self.subTest(adapter=adapter_cls.__name__, case="http"):
                with self.assertRaises(ValueError):
                    adapter._get("http://" + adapter.base_url.split("//", 1)[1] + "/public")
            with self.subTest(adapter=adapter_cls.__name__, case="foreign_host"):
                with self.assertRaises(ValueError):
                    adapter._get("https://example.test/public")


if __name__ == "__main__":
    unittest.main()
