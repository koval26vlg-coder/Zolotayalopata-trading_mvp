from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import build_parser  # noqa: E402
from perp_report import build_perp_report, run_perp_report_file  # noqa: E402


class PerpReportTests(unittest.TestCase):
    def test_build_perp_report_summarizes_market_and_field_coverage(self) -> None:
        rows = [
            {
                "exchange": "mexc",
                "symbol": "HYPE_USDT",
                "event_kind": "bbo",
                "exchange_ts": 10.0,
                "bid_price": 100.0,
                "ask_price": 100.1,
                "spread_bps": 9.995,
                "mark_price": 100.0,
                "index_price": 99.9,
                "funding_rate": 0.0001,
                "funding_interval_sec": 28800,
                "cycle": 1,
            },
            {
                "exchange": "mexc",
                "symbol": "HYPE_USDT",
                "event_kind": "trade",
                "exchange_ts": 11.0,
                "price": 100.0,
                "qty": 2.0,
                "mark_price": 100.0,
                "index_price": 99.9,
                "funding_rate": 0.0001,
                "funding_interval_sec": 28800,
                "cycle": 1,
            },
            {
                "exchange": "gateio",
                "symbol": "CC_USDT",
                "event_kind": "bbo",
                "exchange_ts": 12.0,
                "spread_bps": 5.0,
                "mark_price": 1.0,
                "index_price": 1.0,
                "funding_rate": -0.0002,
                "funding_interval_sec": 28800,
                "cycle": 2,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "perp.jsonl"
            out = Path(tmp) / "report.json"
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            report = run_perp_report_file(src, out)

            self.assertTrue(out.exists())
            self.assertEqual(report["rows"], 3)
            self.assertEqual(report["market_count"], 2)
            self.assertEqual(report["cycles_seen"], 2)
            self.assertEqual(report["field_coverage"]["funding_rate"], 3)
            self.assertEqual(report["events_by_kind"]["bbo"], 2)
            hype = report["markets"]["mexc:HYPE_USDT"]
            self.assertEqual(hype["trade_count"], 1)
            self.assertEqual(hype["trade_notional_quote_sum"], 200.0)
            self.assertEqual(hype["funding_rate_last"], 0.0001)
            self.assertIn("gateio:CC_USDT:no_trades", report["warnings"])

    def test_empty_report_warns_no_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "empty.jsonl"
            src.write_text("", encoding="utf-8")

            report = build_perp_report(src)

            self.assertEqual(report["rows"], 0)
            self.assertEqual(report["warnings"], ["no_rows"])

    def test_report_tolerates_malformed_trailing_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "partial.jsonl"
            src.write_text(
                json.dumps(
                    {
                        "exchange": "mexc",
                        "symbol": "HYPE_USDT",
                        "event_kind": "bbo",
                        "exchange_ts": 1.0,
                    }
                )
                + "\n{",
                encoding="utf-8",
            )

            report = build_perp_report(src)

            self.assertEqual(report["rows"], 1)
            self.assertEqual(report["malformed_rows"], 1)
            self.assertIn("malformed_rows", report["warnings"])

    def test_cli_accepts_perp_report_command(self) -> None:
        args = build_parser().parse_args(["perp-report", "--input", "x.jsonl", "--output", "r.json"])

        self.assertEqual(args.command, "perp-report")
        self.assertEqual(args.input, "x.jsonl")
        self.assertEqual(args.output, "r.json")


if __name__ == "__main__":
    unittest.main()
