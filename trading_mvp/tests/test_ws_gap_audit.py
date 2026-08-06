from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ws_gap_audit import run_ws_gap_audit_file  # noqa: E402


def _row(ts: float, exchange: str, symbol: str, kind: str) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": kind,
    }


class WsGapAuditTests(unittest.TestCase):
    def test_reports_market_and_market_kind_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "audit.json"
            rows = [
                _row(0.0, "mexc", "AAAUSDT", "bbo"),
                _row(10.0, "mexc", "AAAUSDT", "depth"),
                _row(20.0, "mexc", "AAAUSDT", "trade"),
                _row(400.0, "mexc", "AAAUSDT", "bbo"),
                _row(410.0, "mexc", "AAAUSDT", "depth"),
                _row(420.0, "mexc", "AAAUSDT", "trade"),
            ]
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            result = run_ws_gap_audit_file(
                src,
                out,
                gap_threshold_sec=300.0,
                bin_sec=60.0,
                top_n=10,
                min_bbo_markets=1,
                min_depth_markets=1,
                min_trade_markets=1,
                progress=False,
            )

            self.assertTrue(out.exists())
            self.assertEqual(result["summary"]["rows"], 6)
            self.assertEqual(result["summary"]["market_gap_over_threshold"], 1)
            self.assertGreaterEqual(result["summary"]["market_kind_gap_over_threshold"], 1)
            self.assertEqual(result["top_market_gaps"][0]["key"], "mexc:AAAUSDT")
            self.assertAlmostEqual(result["top_market_gaps"][0]["max_gap_sec"], 380.0)

    def test_clean_windows_require_market_counts_by_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "audit.json"
            rows = []
            for base_ts in (0.0, 60.0, 120.0):
                for symbol in ("AAAUSDT", "BBBUSDT"):
                    rows.append(_row(base_ts + 1, "mexc", symbol, "bbo"))
                    rows.append(_row(base_ts + 2, "mexc", symbol, "depth"))
                    rows.append(_row(base_ts + 3, "mexc", symbol, "trade"))
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            result = run_ws_gap_audit_file(
                src,
                out,
                gap_threshold_sec=300.0,
                bin_sec=60.0,
                top_n=5,
                min_bbo_markets=2,
                min_depth_markets=2,
                min_trade_markets=2,
                progress=False,
            )

            self.assertEqual(result["summary"]["clean_window_count"], 1)
            self.assertAlmostEqual(result["clean_windows"][0]["duration_sec"], 180.0)
            self.assertEqual(result["clean_windows"][0]["min_markets_by_kind"]["trade"], 2)


if __name__ == "__main__":
    unittest.main()
