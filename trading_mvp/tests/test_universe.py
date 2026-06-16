from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from universe import (  # noqa: E402
    UniverseRow,
    binance_assets_from_exchange_info,
    is_focus_candidate,
    no_binance_rows,
)


class UniverseTests(unittest.TestCase):
    def test_binance_assets_include_base_and_quote(self) -> None:
        exchange_info = {
            "symbols": [
                {"status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT"},
                {"status": "BREAK", "baseAsset": "OLD", "quoteAsset": "USDT"},
            ]
        }
        self.assertEqual(
            binance_assets_from_exchange_info(exchange_info),
            {"BTC", "USDT"},
        )

    def test_no_binance_rows_excludes_symbols_present_on_binance(self) -> None:
        tickers = [
            {"rank": 1, "symbol": "BTC", "name": "Bitcoin", "id": "btc-bitcoin"},
            {
                "rank": 2,
                "symbol": "HYPE",
                "name": "Hyperliquid",
                "id": "hype-hyperliquid",
                "quotes": {"USD": {"market_cap": 10, "price": 1}},
            },
        ]
        rows = no_binance_rows(tickers, {"BTC"})
        self.assertEqual([row.symbol for row in rows], ["HYPE"])

    def test_focus_candidate_filters_stables_and_derivatives(self) -> None:
        self.assertTrue(
            is_focus_candidate(
                UniverseRow(9, "HYPE", "Hyperliquid", "hype-hyperliquid", 10, 1)
            )
        )
        self.assertFalse(
            is_focus_candidate(
                UniverseRow(10, "RETH", "Rocket Pool ETH", "reth-rocket-pool-eth", 10, 1)
            )
        )
        self.assertFalse(
            is_focus_candidate(
                UniverseRow(11, "USDD", "USDD", "usdd-usdd", 10, 1)
            )
        )


if __name__ == "__main__":
    unittest.main()
