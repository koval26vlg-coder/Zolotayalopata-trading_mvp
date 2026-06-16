from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import build_parser  # noqa: E402
from funding import FundingContract, FundingSnapshot  # noqa: E402
from perp_collector import (  # noqa: E402
    GatePerpRestClient,
    MexcPerpRestClient,
    PerpCollectConfig,
    _should_continue_collect,
    select_contracts,
)


def _snapshot(exchange: str, symbol: str) -> FundingSnapshot:
    return FundingSnapshot(
        exchange=exchange,
        symbol=symbol,
        base="HYPE",
        quote="USDT",
        ts=1_700_000_000.0,
        funding_rate=0.0001,
        next_funding_ts=1_700_028_800.0,
        funding_interval_sec=28_800,
        mark_price=100.5,
        index_price=100.0,
        perp_bid=100.0,
        perp_ask=101.0,
        open_interest=12345.0,
        volume_24h_quote=1_000_000.0,
    )


class PerpCollectorTests(unittest.TestCase):
    def test_mexc_depth_and_trades_are_normalized_with_contract_size(self) -> None:
        contract = FundingContract(
            exchange="mexc",
            symbol="HYPE_USDT",
            base="HYPE",
            quote="USDT",
            status="trading",
            raw={"contractSize": "0.1"},
        )
        depth = {
            "success": True,
            "data": {
                "bids": [[100.0, 20, 1]],
                "asks": [[101.0, 30, 1]],
                "timestamp": 1_700_000_001_000,
                "version": 42,
            },
        }
        trades = [{"p": 100.0, "v": 4, "T": 2, "t": 1_700_000_001_100, "i": "123"}]

        events = MexcPerpRestClient()._events_from_payloads(contract, _snapshot("mexc", contract.symbol), depth, trades)

        self.assertEqual([event["event_kind"] for event in events], ["bbo", "depth", "trade"])
        self.assertEqual(events[0]["bid_qty"], 2.0)
        self.assertEqual(events[0]["ask_qty"], 3.0)
        self.assertEqual(events[2]["qty"], 0.4)
        self.assertEqual(events[2]["side"], "sell")
        self.assertEqual(events[2]["funding_rate"], 0.0001)

    def test_gate_depth_and_signed_trade_size_are_normalized_with_multiplier(self) -> None:
        contract = FundingContract(
            exchange="gateio",
            symbol="HYPE_USDT",
            base="HYPE",
            quote="USDT",
            status="trading",
            raw={"quanto_multiplier": "0.01"},
        )
        depth = {
            "bids": [{"p": "100.0", "s": 50}],
            "asks": [{"p": "101.0", "s": 70}],
            "update": 1_700_000_001.0,
            "id": 7,
        }
        trades = [{"id": 456, "price": "101.0", "size": -25, "create_time_ms": 1_700_000_001.25}]

        events = GatePerpRestClient()._events_from_payloads(contract, _snapshot("gateio", contract.symbol), depth, trades)

        self.assertEqual([event["event_kind"] for event in events], ["bbo", "depth", "trade"])
        self.assertEqual(events[0]["bid_qty"], 0.5)
        self.assertAlmostEqual(events[0]["ask_qty"], 0.7)
        self.assertEqual(events[2]["qty"], 0.25)
        self.assertEqual(events[2]["side"], "sell")
        self.assertEqual(events[2]["mark_price"], 100.5)

    def test_select_contracts_filters_universe_quote_status_and_limit(self) -> None:
        contracts = [
            FundingContract("mexc", "HYPE_USDT", "HYPE", "USDT", "trading"),
            FundingContract("mexc", "CC_USDT", "CC", "USDT", "trading"),
            FundingContract("mexc", "BAD_USDT", "BAD", "USDT", "paused"),
            FundingContract("mexc", "HYPE_USDC", "HYPE", "USDC", "trading"),
        ]

        selected = select_contracts(contracts, universe_symbols={"HYPE", "CC", "BAD"}, quote="USDT", max_pairs=1)

        self.assertEqual([contract.symbol for contract in selected], ["HYPE_USDT"])

    def test_cli_accepts_perp_collect_command(self) -> None:
        args = build_parser().parse_args(
            [
                "perp-collect",
                "--exchanges",
                "mexc,gateio",
                "--cycles",
                "1",
                "--duration-sec",
                "3600",
                "--depth-limit",
                "5",
                "--trades-limit",
                "10",
            ]
        )

        self.assertEqual(args.command, "perp-collect")
        self.assertEqual(args.duration_sec, 3600)
        self.assertEqual(args.depth_limit, 5)
        self.assertEqual(args.trades_limit, 10)

    def test_collect_duration_guard_stops_after_wall_clock_limit(self) -> None:
        cfg = PerpCollectConfig(cycles=3, duration_sec=60)

        self.assertTrue(_should_continue_collect(cycle=0, started=1000.0, cfg=cfg, now=1059.9))
        self.assertTrue(_should_continue_collect(cycle=720, started=1000.0, cfg=cfg, now=1059.9))
        self.assertFalse(_should_continue_collect(cycle=0, started=1000.0, cfg=cfg, now=1060.0))

    def test_collect_cycle_guard_still_stops_when_no_duration(self) -> None:
        cfg = PerpCollectConfig(cycles=3, duration_sec=None)

        self.assertTrue(_should_continue_collect(cycle=2, started=1000.0, cfg=cfg, now=1001.0))
        self.assertFalse(_should_continue_collect(cycle=3, started=1000.0, cfg=cfg, now=1001.0))


if __name__ == "__main__":
    unittest.main()
