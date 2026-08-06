from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dense_ws_execution_realization import (  # noqa: E402
    IMPLEMENTATION_STATUS,
    REALIZATION_SCHEMA,
    SyntheticFixtureIntegrityError,
    realize_synthetic_execution_fixture,
)
from dense_ws_signal_evaluator_freeze import (  # noqa: E402
    canonical_contract_hash,
)


CONTRACT_PATH = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "frozen"
    / "dense-ws-signal-evaluator-contract-20260802-v1.json"
)


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _snapshot(
    sample_ts: float,
    *,
    mexc_ask: float = 100.0,
    gate_bid: float = 101.0,
) -> dict:
    return {
        "fixture_only": True,
        "schema": "trading_mvp_dense_ws_execution_snapshot_v1",
        "sample_ts": sample_ts,
        "base": "HYPE",
        "regime_label": "DENSE_BOTH",
        "cross_venue_recv_ts_skew_ms": 0.0,
        "venues": {
            "mexc": {
                "recv_ts": sample_ts - 0.1,
                "quote_age_ms": 100.0,
                "bid_price": mexc_ask - 0.1,
                "bid_qty": 10.0,
                "ask_price": mexc_ask,
                "ask_qty": 10.0,
                "spread_bps": 10.0,
                "top_notional_quote": 999.0,
            },
            "gateio": {
                "recv_ts": sample_ts - 0.1,
                "quote_age_ms": 100.0,
                "bid_price": gate_bid,
                "bid_qty": 10.0,
                "ask_price": gate_bid + 0.1,
                "ask_qty": 10.0,
                "spread_bps": 10.0,
                "top_notional_quote": 1_010.0,
            },
        },
    }


def _bbo(
    recv_ts: float,
    venue: str,
    *,
    bid: float,
    ask: float,
    bid_qty: float = 10.0,
    ask_qty: float = 10.0,
) -> dict:
    return {
        "fixture_only": True,
        "recv_ts": recv_ts,
        "exchange": venue,
        "symbol": "HYPEUSDT" if venue == "mexc" else "HYPE_USDT",
        "event_kind": "bbo",
        "bid_price": bid,
        "bid_qty": bid_qty,
        "ask_price": ask,
        "ask_qty": ask_qty,
    }


class DenseWsExecutionRealizationTests(unittest.TestCase):
    def test_uses_latest_quote_not_after_each_execution_time(self) -> None:
        rows = [
            _bbo(1_000.20, "gateio", bid=100.90, ask=101.00),
            _bbo(1_000.20, "mexc", bid=100.00, ask=100.10),
            _bbo(1_000.30, "gateio", bid=90.00, ask=90.10),
            _bbo(1_000.30, "mexc", bid=110.00, ask=110.10),
            _bbo(1_000.90, "gateio", bid=100.60, ask=100.70),
            _bbo(1_000.90, "mexc", bid=100.30, ask=100.40),
        ]
        result = realize_synthetic_execution_fixture(
            contract=_contract(),
            snapshots=[_snapshot(1_000.0)],
            raw_bbo_events=rows,
        )

        self.assertEqual(result["schema"], REALIZATION_SCHEMA)
        self.assertEqual(result["status"], IMPLEMENTATION_STATUS)
        self.assertEqual(result["selected_event_count"], 1)
        event = result["events"][0]
        normal = event["outcomes"]["normal"]
        stress = event["outcomes"]["stress"]
        self.assertTrue(normal["paired_fill"])
        self.assertEqual(normal["buy_quote_recv_ts"], 1_000.20)
        self.assertEqual(normal["sell_quote_recv_ts"], 1_000.20)
        self.assertGreater(normal["net_edge_bps"], 0.0)
        self.assertTrue(stress["paired_fill"])
        self.assertEqual(stress["buy_quote_recv_ts"], 1_000.90)
        self.assertEqual(stress["sell_quote_recv_ts"], 1_000.90)
        self.assertLess(stress["net_edge_bps"], 0.0)

    def test_unfillable_event_remains_in_fill_rate_denominator(self) -> None:
        rows = [
            _bbo(2_000.20, "mexc", bid=100.0, ask=100.1),
            _bbo(
                2_000.20,
                "gateio",
                bid=100.9,
                ask=101.0,
                bid_qty=0.1,
            ),
        ]
        result = realize_synthetic_execution_fixture(
            contract=_contract(),
            snapshots=[_snapshot(2_000.0)],
            raw_bbo_events=rows,
        )

        self.assertEqual(result["selected_event_count"], 1)
        self.assertEqual(result["fill_rate_denominators"]["normal"], 1)
        normal = result["events"][0]["outcomes"]["normal"]
        self.assertFalse(normal["paired_fill"])
        self.assertEqual(normal["unfillable_reason"], "sell_capacity_shortfall")
        self.assertIsNone(normal["net_edge_bps"])

    def test_cooldown_is_separate_for_each_base_and_direction(self) -> None:
        snapshots = [
            _snapshot(3_000.0),
            _snapshot(3_010.0, mexc_ask=102.0, gate_bid=100.0),
            _snapshot(3_030.0),
            _snapshot(3_060.0),
        ]
        rows = []
        for ts in (3_000.2, 3_010.2, 3_030.2, 3_060.2):
            rows.extend(
                [
                    _bbo(ts, "gateio", bid=101.0, ask=101.1),
                    _bbo(ts, "mexc", bid=99.9, ask=100.0),
                ]
            )
        rows.sort(key=lambda row: (row["recv_ts"], row["exchange"]))
        result = realize_synthetic_execution_fixture(
            contract=_contract(),
            snapshots=snapshots,
            raw_bbo_events=rows,
        )

        directions = [event["direction"] for event in result["events"]]
        self.assertEqual(directions.count("buy_mexc_sell_gateio"), 2)
        self.assertEqual(directions.count("buy_gateio_sell_mexc"), 1)
        self.assertEqual(result["suppressed_by_cooldown"], 1)

    def test_rejects_any_input_without_fixture_only_marker(self) -> None:
        row = _bbo(4_000.2, "mexc", bid=100.0, ask=100.1)
        row.pop("fixture_only")

        with self.assertRaisesRegex(SyntheticFixtureIntegrityError, "fixture_only"):
            realize_synthetic_execution_fixture(
                contract=_contract(),
                snapshots=[_snapshot(4_000.0)],
                raw_bbo_events=[row],
            )

    def test_rejects_out_of_order_raw_stream(self) -> None:
        rows = [
            _bbo(5_000.3, "mexc", bid=100.0, ask=100.1),
            _bbo(5_000.2, "gateio", bid=100.9, ask=101.0),
        ]

        with self.assertRaisesRegex(SyntheticFixtureIntegrityError, "ordered"):
            realize_synthetic_execution_fixture(
                contract=_contract(),
                snapshots=[_snapshot(5_000.0)],
                raw_bbo_events=rows,
            )

    def test_rejects_tampered_frozen_contract(self) -> None:
        contract = copy.deepcopy(_contract())
        contract["execution_realization_contract"]["normal_latency_ms"] = 0
        contract["contract_hash"] = canonical_contract_hash(contract)

        with self.assertRaisesRegex(
            SyntheticFixtureIntegrityError,
            "normal_latency_ms",
        ):
            realize_synthetic_execution_fixture(
                contract=contract,
                snapshots=[_snapshot(6_000.0)],
                raw_bbo_events=[],
            )


if __name__ == "__main__":
    unittest.main()
