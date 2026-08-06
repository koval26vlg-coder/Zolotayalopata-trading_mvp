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
from ws_postprocess import run_ws_postprocess_file  # noqa: E402


def _gate_raw_row(ts: float, channel: str, result: dict[str, object]) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange": "gateio",
        "channel": channel,
        "symbol": "HYPE_USDT",
        "payload": {
            "encoding": "json",
            "data": {
                "time_ms": int(ts * 1000),
                "channel": channel,
                "event": "update",
                "result": result,
            },
        },
    }


class WsPostprocessTests(unittest.TestCase):
    def test_normalizes_and_runs_data_quality_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw = tmp_path / "ws_gateio.jsonl"
            manifest = tmp_path / "ws_collect.json"
            normalized = tmp_path / "normalized.jsonl"
            quality = tmp_path / "quality.json"
            report = tmp_path / "postprocess.json"

            rows = [
                _gate_raw_row(100.0, "spot.book_ticker", {"s": "HYPE_USDT", "b": "10", "B": "1", "a": "10.1", "A": "2", "u": 1}),
                _gate_raw_row(105.0, "spot.order_book_update", {"s": "HYPE_USDT", "b": [["10", "1"]], "a": [["10.1", "2"]], "U": 1, "u": 2}),
                _gate_raw_row(110.0, "spot.trades", {"currency_pair": "HYPE_USDT", "id": 1, "create_time_ms": "110000", "price": "10.05", "amount": "1.5", "side": "buy"}),
            ]
            raw.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "duration_sec": 10,
                        "results": [{"exchange": "gateio", "output": str(raw), "events": len(rows), "errors": []}],
                        "total_events": len(rows),
                    }
                ),
                encoding="utf-8",
            )

            result = run_ws_postprocess_file(
                manifest,
                normalized_output_path=normalized,
                quality_output_path=quality,
                report_output_path=report,
                quality_config=WsDataQualityConfig(
                    min_rows=3,
                    min_exchanges=1,
                    min_markets=1,
                    min_duration_ratio=0.9,
                    min_markets_with_required_kinds=1,
                ),
            )

            self.assertTrue(result["data_quality"]["accepted"], result["data_quality"]["reasons"])
            self.assertTrue(result["replay_allowed"])
            self.assertTrue(normalized.exists())
            self.assertTrue(quality.exists())
            self.assertTrue(report.exists())
            self.assertEqual(result["normalization"]["normalized_rows"], 3)
            self.assertEqual(result["data_quality"]["metrics"]["markets_with_required_kinds"], 1)
            self.assertIn("ws-replay", result["next_steps"][0])

    def test_blocks_replay_when_quality_rejects_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw = tmp_path / "ws_gateio.jsonl"
            manifest = tmp_path / "ws_collect.json"
            normalized = tmp_path / "normalized.jsonl"
            quality = tmp_path / "quality.json"
            report = tmp_path / "postprocess.json"

            row = _gate_raw_row(100.0, "spot.book_ticker", {"s": "HYPE_USDT", "b": "10", "B": "1", "a": "10.1", "A": "2", "u": 1})
            raw.write_text(json.dumps(row), encoding="utf-8")
            manifest.write_text(json.dumps({"duration_sec": 3600, "results": [{"output": str(raw), "events": 1}]}), encoding="utf-8")

            result = run_ws_postprocess_file(
                manifest,
                normalized_output_path=normalized,
                quality_output_path=quality,
                report_output_path=report,
                quality_config=WsDataQualityConfig(
                    min_rows=1,
                    min_exchanges=1,
                    min_markets=1,
                    min_duration_ratio=0.5,
                    min_markets_with_required_kinds=1,
                ),
            )

            self.assertFalse(result["data_quality"]["accepted"])
            self.assertFalse(result["replay_allowed"])
            self.assertIn("min_duration_ratio", result["data_quality"]["reasons"])
            self.assertIn("min_markets_with_required_kinds", result["data_quality"]["reasons"])
            self.assertIn("Do not run ws-replay", result["next_steps"][0])


if __name__ == "__main__":
    unittest.main()
