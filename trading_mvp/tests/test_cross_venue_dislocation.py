from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cross_venue_dislocation import (  # noqa: E402
    CrossVenueDislocationConfig,
    build_cross_venue_dislocation_report,
    normalize_spot_symbol,
    run_cross_venue_dislocation_file,
)


def _bbo(
    *,
    recv_ts: float,
    exchange: str,
    symbol: str,
    bid_price: float,
    bid_qty: float,
    ask_price: float,
    ask_qty: float,
) -> dict[str, object]:
    return {
        "recv_ts": recv_ts,
        "exchange_ts": recv_ts,
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": "bbo",
        "channel": "spot.book_ticker",
        "bid_price": bid_price,
        "bid_qty": bid_qty,
        "ask_price": ask_price,
        "ask_qty": ask_qty,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class CrossVenueDislocationTests(unittest.TestCase):
    def test_symbol_mapping_supports_gate_and_mexc(self) -> None:
        self.assertEqual(normalize_spot_symbol("HYPE_USDT"), ("HYPE", "USDT"))
        self.assertEqual(normalize_spot_symbol("HYPEUSDT"), ("HYPE", "USDT"))
        self.assertEqual(normalize_spot_symbol("M_USDT"), ("M", "USDT"))
        self.assertIsNone(normalize_spot_symbol("HYPEBTC"))

    def test_detects_net_positive_cross_venue_dislocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.jsonl"
            _write_jsonl(
                path,
                [
                    _bbo(
                        recv_ts=1000.0,
                        exchange="mexc",
                        symbol="HYPEUSDT",
                        bid_price=98.0,
                        bid_qty=10.0,
                        ask_price=99.0,
                        ask_qty=10.0,
                    ),
                    _bbo(
                        recv_ts=1000.5,
                        exchange="gateio",
                        symbol="HYPE_USDT",
                        bid_price=100.0,
                        bid_qty=10.0,
                        ask_price=101.0,
                        ask_qty=10.0,
                    ),
                ],
            )
            report = build_cross_venue_dislocation_report(
                path,
                CrossVenueDislocationConfig(
                    round_trip_fee_bps=5.0,
                    slippage_bps=2.0,
                    inventory_rebalance_buffer_bps=3.0,
                    min_top_notional_quote=25.0,
                ),
            )

        self.assertEqual(report["summary"]["matched_bases"], 1)
        self.assertEqual(report["summary"]["candidate_events"], 1)
        self.assertEqual(report["summary"]["eligible_events"], 1)
        self.assertEqual(report["top_eligible"][0]["direction"], "buy_mexc_sell_gateio")
        self.assertGreater(report["top_eligible"][0]["net_edge_bps"], 0.0)
        self.assertFalse(report["accepted"])

    def test_base_tier_cost_gate_blocks_thin_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.jsonl"
            _write_jsonl(
                path,
                [
                    _bbo(
                        recv_ts=1000.0,
                        exchange="mexc",
                        symbol="HYPEUSDT",
                        bid_price=98.5,
                        bid_qty=10.0,
                        ask_price=99.5,
                        ask_qty=10.0,
                    ),
                    _bbo(
                        recv_ts=1000.5,
                        exchange="gateio",
                        symbol="HYPE_USDT",
                        bid_price=100.0,
                        bid_qty=10.0,
                        ask_price=101.0,
                        ask_qty=10.0,
                    ),
                ],
            )
            report = build_cross_venue_dislocation_report(path, CrossVenueDislocationConfig())

        self.assertEqual(report["summary"]["candidate_events"], 1)
        self.assertEqual(report["summary"]["eligible_events"], 0)
        self.assertEqual(report["decision"], "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES")

    def test_stale_quotes_do_not_create_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.jsonl"
            _write_jsonl(
                path,
                [
                    _bbo(
                        recv_ts=1000.0,
                        exchange="mexc",
                        symbol="HYPEUSDT",
                        bid_price=98.0,
                        bid_qty=10.0,
                        ask_price=99.0,
                        ask_qty=10.0,
                    ),
                    _bbo(
                        recv_ts=1010.0,
                        exchange="gateio",
                        symbol="HYPE_USDT",
                        bid_price=100.0,
                        bid_qty=10.0,
                        ask_price=101.0,
                        ask_qty=10.0,
                    ),
                ],
            )
            report = build_cross_venue_dislocation_report(
                path,
                CrossVenueDislocationConfig(stale_quote_sec=1.0, round_trip_fee_bps=0.0, slippage_bps=0.0, inventory_rebalance_buffer_bps=0.0),
            )

        self.assertEqual(report["summary"]["candidate_events"], 0)
        self.assertEqual(report["summary"]["stale_rejects"], 2)

    def test_run_file_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "sample.jsonl"
            output_path = Path(tmp) / "report.json"
            _write_jsonl(
                input_path,
                [
                    _bbo(
                        recv_ts=1000.0,
                        exchange="mexc",
                        symbol="HYPEUSDT",
                        bid_price=98.0,
                        bid_qty=10.0,
                        ask_price=99.0,
                        ask_qty=10.0,
                    )
                ],
            )
            report = run_cross_venue_dislocation_file(input_path, output_path, CrossVenueDislocationConfig())
            self.assertTrue(output_path.exists())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["mode"], report["mode"])


if __name__ == "__main__":
    unittest.main()
