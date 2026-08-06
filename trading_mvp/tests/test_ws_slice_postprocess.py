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
from ws_slice_postprocess import run_ws_slice_postprocess  # noqa: E402


def _row(ts: float, exchange: str, symbol: str, kind: str) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "event_kind": kind,
    }


class WsSlicePostprocessTests(unittest.TestCase):
    def test_creates_guarded_postprocess_for_clean_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "normalized.jsonl"
            normalized = root / "slice.jsonl"
            manifest = root / "slice_manifest.json"
            quality = root / "quality.json"
            postprocess = root / "postprocess.json"
            rows = [
                _row(0.0, "mexc", "AAAUSDT", "bbo"),
                _row(1.0, "mexc", "AAAUSDT", "depth"),
                _row(2.0, "mexc", "AAAUSDT", "trade"),
                _row(10.0, "gateio", "AAA_USDT", "bbo"),
                _row(11.0, "gateio", "AAA_USDT", "depth"),
                _row(12.0, "gateio", "AAA_USDT", "trade"),
                _row(1000.0, "mexc", "AAAUSDT", "bbo"),
            ]
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            result = run_ws_slice_postprocess(
                src,
                start_ts=0.0,
                end_ts=100.0,
                normalized_output_path=normalized,
                manifest_output_path=manifest,
                quality_output_path=quality,
                postprocess_output_path=postprocess,
                quality_config=WsDataQualityConfig(
                    min_rows=6,
                    min_exchanges=2,
                    min_markets=2,
                    min_duration_ratio=0.01,
                    min_markets_with_required_kinds=2,
                    max_gap_sec=120.0,
                ),
            )

            self.assertTrue(result["replay_allowed"], result["data_quality"]["reasons"])
            self.assertEqual(result["normalization"]["rows_written"], 6)
            self.assertEqual(result["mode"], "ws_postprocess_guarded")
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["duration_sec"], 100.0)
            self.assertTrue(postprocess.exists())

    def test_rejects_slice_when_quality_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "normalized.jsonl"
            rows = [
                _row(0.0, "mexc", "AAAUSDT", "bbo"),
                _row(1000.0, "mexc", "AAAUSDT", "bbo"),
            ]
            src.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            result = run_ws_slice_postprocess(
                src,
                start_ts=0.0,
                end_ts=1001.0,
                normalized_output_path=root / "slice.jsonl",
                manifest_output_path=root / "slice_manifest.json",
                quality_output_path=root / "quality.json",
                postprocess_output_path=root / "postprocess.json",
                quality_config=WsDataQualityConfig(
                    min_rows=2,
                    min_exchanges=2,
                    min_markets=2,
                    max_gap_sec=300.0,
                ),
            )

            self.assertFalse(result["replay_allowed"])
            self.assertIn("min_exchanges", result["data_quality"]["reasons"])
            self.assertIn("max_gap_sec", result["data_quality"]["reasons"])


if __name__ == "__main__":
    unittest.main()
