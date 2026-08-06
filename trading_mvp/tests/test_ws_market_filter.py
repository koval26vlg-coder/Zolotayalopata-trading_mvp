from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ws_data_quality import WsDataQualityConfig  # noqa: E402
from ws_market_filter import WsMarketFilterConfig, run_ws_market_filter  # noqa: E402


def _row(ts: float, exchange: str, symbol: str, kind: str) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": kind,
    }


class WsMarketFilterTests(unittest.TestCase):
    def test_filters_bad_markets_and_allows_clean_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "slice.jsonl"
            manifest = root / "source_manifest.json"
            normalized = root / "market_filtered.jsonl"
            market_manifest = root / "market_manifest.json"
            report = root / "market_report.json"
            quality = root / "quality.json"
            postprocess = root / "postprocess.json"

            rows = [
                _row(0.0, "mexc", "GOODUSDT", "bbo"),
                _row(1.0, "mexc", "GOODUSDT", "depth"),
                _row(2.0, "mexc", "GOODUSDT", "trade"),
                _row(100.0, "mexc", "GOODUSDT", "bbo"),
                _row(0.0, "gateio", "GAP_USDT", "bbo"),
                _row(1.0, "gateio", "GAP_USDT", "depth"),
                _row(2.0, "gateio", "GAP_USDT", "trade"),
                _row(500.0, "gateio", "GAP_USDT", "bbo"),
                _row(0.0, "gateio", "MISS_USDT", "bbo"),
                _row(1.0, "gateio", "MISS_USDT", "depth"),
            ]
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            manifest.write_text(json.dumps({"duration_sec": 100.0}), encoding="utf-8")

            result = run_ws_market_filter(
                src,
                normalized_output_path=normalized,
                manifest_output_path=market_manifest,
                report_output_path=report,
                quality_output_path=quality,
                postprocess_output_path=postprocess,
                source_manifest_path=manifest,
                filter_config=WsMarketFilterConfig(
                    max_gap_sec=120.0,
                    min_rows_per_market=4,
                    min_market_duration_ratio=0.90,
                    min_accepted_markets=1,
                    min_accepted_exchanges=1,
                    min_total_rows=4,
                ),
                quality_config=WsDataQualityConfig(
                    min_rows=4,
                    min_exchanges=1,
                    min_markets=1,
                    min_duration_ratio=0.90,
                    min_markets_with_required_kinds=1,
                    max_gap_sec=120.0,
                ),
            )

            self.assertTrue(result["replay_allowed"], result["data_quality"]["reasons"])
            self.assertEqual(result["market_filter"]["metrics"]["accepted_markets"], 1)
            self.assertEqual(result["market_filter"]["metrics"]["rejected_markets"], 2)
            self.assertEqual(result["market_filter"]["metrics"]["output_rows"], 4)
            self.assertEqual(normalized.read_text(encoding="utf-8").count("\n"), 4)
            rejected = json.loads(report.read_text(encoding="utf-8"))["markets"]
            reasons = {item["market"]: item["reasons"] for item in rejected}
            self.assertIn("max_gap_sec", reasons["gateio:GAP_USDT"])
            self.assertIn("required_event_kinds", reasons["gateio:MISS_USDT"])

    def test_blocks_replay_when_no_markets_survive_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "slice.jsonl"
            rows = [
                _row(0.0, "mexc", "BADUSDT", "bbo"),
                _row(500.0, "mexc", "BADUSDT", "bbo"),
            ]
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            result = run_ws_market_filter(
                src,
                normalized_output_path=root / "market_filtered.jsonl",
                manifest_output_path=root / "market_manifest.json",
                report_output_path=root / "market_report.json",
                quality_output_path=root / "quality.json",
                postprocess_output_path=root / "postprocess.json",
                filter_config=WsMarketFilterConfig(
                    max_gap_sec=120.0,
                    min_accepted_markets=1,
                    min_accepted_exchanges=1,
                    min_total_rows=1,
                ),
                quality_config=WsDataQualityConfig(
                    min_rows=1,
                    min_exchanges=1,
                    min_markets=1,
                    min_markets_with_required_kinds=1,
                    max_gap_sec=120.0,
                ),
            )

            self.assertFalse(result["replay_allowed"])
            self.assertIn("min_accepted_markets", result["market_filter"]["reasons"])
            self.assertIn("min_rows", result["data_quality"]["reasons"])


if __name__ == "__main__":
    unittest.main()
