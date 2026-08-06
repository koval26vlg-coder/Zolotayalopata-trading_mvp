from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from funding import (  # noqa: E402
    GateFundingClient,
    MexcFundingClient,
    parse_gate_contract,
    parse_gate_snapshot,
    parse_mexc_contract,
    parse_mexc_snapshot,
)


class FundingParsingTests(unittest.TestCase):
    def test_funding_clients_ignore_proxy_environment(self) -> None:
        self.assertFalse(MexcFundingClient().session.trust_env)
        self.assertFalse(GateFundingClient().session.trust_env)

    def test_parse_mexc_contract_and_snapshot(self) -> None:
        contract = parse_mexc_contract(
            {
                "symbol": "HYPE_USDT",
                "baseCoin": "HYPE",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "state": 0,
                "apiAllowed": True,
                "makerFeeRate": 0,
                "takerFeeRate": 0.0002,
            }
        )
        self.assertIsNotNone(contract)
        assert contract is not None
        snapshot = parse_mexc_snapshot(
            contract,
            {
                "symbol": "HYPE_USDT",
                "bid1": 100.0,
                "ask1": 100.1,
                "amount24": 1_000_000,
                "holdVol": 10_000,
                "fairPrice": 100.03,
                "indexPrice": 100.02,
                "fundingRate": 0.00005,
                "timestamp": 1_700_000_000_000,
            },
            {
                "fundingRate": 0.00006,
                "collectCycle": 4,
                "nextSettleTime": 1_700_014_400_000,
                "idxPrice": 100.02,
                "fairPrice": 100.03,
            },
        )
        self.assertEqual(snapshot.exchange, "mexc")
        self.assertEqual(snapshot.base, "HYPE")
        self.assertEqual(snapshot.funding_rate, 0.00006)
        self.assertEqual(snapshot.funding_interval_sec, 14_400)
        self.assertEqual(snapshot.next_funding_ts, 1_700_014_400)
        self.assertEqual(snapshot.perp_bid, 100.0)
        self.assertEqual(snapshot.perp_ask, 100.1)

    def test_parse_gate_contract_and_snapshot(self) -> None:
        contract = parse_gate_contract(
            {
                "name": "HYPE_USDT",
                "status": "trading",
                "funding_interval": 14_400,
                "funding_rate": "0.00005",
                "funding_next_apply": 1_700_014_400,
                "mark_price": "100.03",
                "index_price": "100.02",
                "maker_fee_rate": "-0.0001",
                "taker_fee_rate": "0.00075",
            }
        )
        self.assertIsNotNone(contract)
        assert contract is not None
        snapshot = parse_gate_snapshot(
            contract,
            {
                "contract": "HYPE_USDT",
                "funding_rate": "0.00007",
                "mark_price": "100.04",
                "index_price": "100.02",
                "highest_bid": "100.0",
                "lowest_ask": "100.1",
                "volume_24h_quote": "500000",
                "total_size": "12345",
            },
            ts=123.0,
        )
        self.assertEqual(snapshot.exchange, "gateio")
        self.assertEqual(snapshot.base, "HYPE")
        self.assertEqual(snapshot.funding_rate, 0.00007)
        self.assertEqual(snapshot.funding_interval_sec, 14_400)
        self.assertEqual(snapshot.next_funding_ts, 1_700_014_400)
        self.assertEqual(snapshot.perp_bid, 100.0)
        self.assertEqual(snapshot.perp_ask, 100.1)

    def test_parse_filters_inactive_or_non_usdt_contracts(self) -> None:
        self.assertIsNone(parse_mexc_contract({"symbol": "ABC_USDT", "quoteCoin": "USDT", "settleCoin": "USDT", "state": 1}))
        self.assertIsNone(parse_gate_contract({"name": "ABC_USDT", "status": "delisted"}))

    def test_mexc_ticker_cache_uses_ttl(self) -> None:
        client = MexcFundingClient()
        calls: list[str] = []

        def fake_get(path: str, params: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(path)
            return {"success": True, "data": [{"symbol": "HYPE_USDT", "fairPrice": "100"}]}

        client._get = fake_get  # type: ignore[method-assign]
        with patch("funding.time.time", side_effect=[100.0, 101.0, 500.0]):
            self.assertIn("HYPE_USDT", client._ticker_map())
            self.assertIn("HYPE_USDT", client._ticker_map())
            self.assertIn("HYPE_USDT", client._ticker_map())

        self.assertEqual(calls, ["/api/v1/contract/ticker", "/api/v1/contract/ticker"])


if __name__ == "__main__":
    unittest.main()
