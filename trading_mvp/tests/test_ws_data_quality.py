from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ws_data_quality import WsDataQualityConfig, run_ws_data_quality_file  # noqa: E402


def _event(ts: float, exchange: str, symbol: str, kind: str) -> dict[str, object]:
    row: dict[str, object] = {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": kind,
    }
    if kind == "bbo":
        row.update({"bid_price": 10.0, "ask_price": 10.1, "bid_qty": 2.0, "ask_qty": 3.0, "spread_bps": 99.5})
    elif kind == "depth":
        row.update({"bids": [[10.0, 2.0]], "asks": [[10.1, 3.0]]})
    elif kind == "trade":
        row.update({"price": 10.05, "qty": 1.0, "side": "buy"})
    return row


class WsDataQualityTests(unittest.TestCase):
    def test_accepts_complete_multi_exchange_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "normalized.jsonl"
            manifest_path = Path(tmp) / "manifest.json"
            output_path = Path(tmp) / "quality.json"
            rows = []
            for exchange, symbol in (("mexc", "AAAUSDT"), ("gateio", "AAA_USDT")):
                rows.extend(
                    [
                        _event(100.0, exchange, symbol, "bbo"),
                        _event(110.0, exchange, symbol, "depth"),
                        _event(120.0, exchange, symbol, "trade"),
                        _event(200.0, exchange, symbol, "bbo"),
                    ]
                )
            input_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            manifest_path.write_text(json.dumps({"duration_sec": 100, "total_events": len(rows)}), encoding="utf-8")

            result = run_ws_data_quality_file(
                input_path,
                output_path,
                manifest_path=manifest_path,
                config=WsDataQualityConfig(
                    min_rows=8,
                    min_exchanges=2,
                    min_markets=2,
                    min_span_hours=0.02,
                    min_duration_ratio=0.90,
                    min_markets_with_required_kinds=2,
                    max_gap_sec=120.0,
                ),
            )

            self.assertTrue(result["accepted"], result["reasons"])
            self.assertEqual(result["metrics"]["rows"], 8)
            self.assertEqual(result["metrics"]["exchanges"], 2)
            self.assertEqual(result["metrics"]["markets_with_required_kinds"], 2)
            self.assertEqual(result["metrics"]["manifest_duration_sec"], 100)
            self.assertTrue(output_path.exists())

    def test_rejects_missing_required_event_kinds_and_short_manifest_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "normalized.jsonl"
            manifest_path = Path(tmp) / "manifest.json"
            rows = [
                _event(100.0, "mexc", "AAAUSDT", "bbo"),
                _event(101.0, "mexc", "AAAUSDT", "bbo"),
                "{not json",
            ]
            input_path.write_text("\n".join(json.dumps(row) if isinstance(row, dict) else row for row in rows), encoding="utf-8")
            manifest_path.write_text(json.dumps({"duration_sec": 3600}), encoding="utf-8")

            result = run_ws_data_quality_file(
                input_path,
                manifest_path=manifest_path,
                config=WsDataQualityConfig(
                    min_rows=2,
                    min_exchanges=1,
                    min_markets=1,
                    min_duration_ratio=0.50,
                    min_markets_with_required_kinds=1,
                    max_parse_error_rate=0.01,
                ),
            )

            self.assertFalse(result["accepted"])
            self.assertIn("min_markets_with_required_kinds", result["reasons"])
            self.assertIn("min_duration_ratio", result["reasons"])
            self.assertIn("max_parse_error_rate", result["reasons"])

    def test_accepts_stitched_manifest_requested_duration_sec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "normalized.jsonl"
            manifest_path = Path(tmp) / "manifest.json"
            rows = [
                _event(100.0, "mexc", "AAAUSDT", "bbo"),
                _event(130.0, "mexc", "AAAUSDT", "depth"),
                _event(160.0, "mexc", "AAAUSDT", "trade"),
                _event(190.0, "mexc", "AAAUSDT", "bbo"),
            ]
            input_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "ws_collect_stitched_v1",
                        "requested_duration_sec": 100,
                        "actual_duration_sec": 99.8,
                        "total_events": len(rows),
                    }
                ),
                encoding="utf-8",
            )

            result = run_ws_data_quality_file(
                input_path,
                manifest_path=manifest_path,
                config=WsDataQualityConfig(
                    min_rows=4,
                    min_exchanges=1,
                    min_markets=1,
                    min_duration_ratio=0.85,
                    min_markets_with_required_kinds=1,
                ),
            )

            self.assertTrue(result["accepted"], result["reasons"])
            self.assertEqual(result["metrics"]["manifest_duration_sec"], 100)
            self.assertEqual(result["metrics"]["manifest_duration_source"], "requested_duration_sec")
            self.assertAlmostEqual(result["metrics"]["duration_ratio"], 0.9)


if __name__ == "__main__":
    unittest.main()
