from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing_event_replay import ReplayConfig, replay_listing_event_drift_reversal  # noqa: E402


def write_replay_inputs(root: Path, events: list[dict[str, object]]) -> Path:
    history = root / "ohlcv.jsonl"
    manifest = root / "manifest.json"
    normalizer = root / "normalizer.json"
    rows: list[dict[str, object]] = []
    for event in events:
        exchange = str(event.get("exchange", "mexc"))
        symbol = str(event.get("symbol", "TESTUSDT"))
        base = str(event.get("base", symbol.replace("USDT", "")))
        event_ts = int(event["event_ts"])
        prices = event["prices"]
        assert isinstance(prices, list)
        for offset_sec, close in prices:
            rows.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "base": base,
                    "quote": "USDT",
                    "event_id": f"{exchange}:{symbol}:listing",
                    "event_ts": event_ts,
                    "event_iso": "2033-05-18T04:33:20Z",
                    "window_start_ts": event_ts,
                    "window_end_ts": event_ts + 172800,
                    "granularity": "1h",
                    "candle_ts": event_ts + int(offset_sec),
                    "candle_iso": "2033-05-18T04:33:20Z",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100.0,
                    "quote_volume": 100.0,
                    "data_status": "ok",
                    "error": "",
                }
            )
    history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "run_id": "replay-test",
                "final": True,
                "ohlcv_rows": len(rows),
                "placeholder_rows": 0,
                "errors": 0,
            }
        ),
        encoding="utf-8",
    )
    normalizer.write_text(
        json.dumps(
            {
                "decision": "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY",
                "history_data": {
                    "jsonl_path": str(history),
                    "manifest_path": str(manifest),
                },
            }
        ),
        encoding="utf-8",
    )
    return normalizer


class ListingEventReplayTests(unittest.TestCase):
    def test_selloff_creates_long_trade_after_costs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalizer = write_replay_inputs(
                Path(tmp),
                [
                    {
                        "exchange": "mexc",
                        "symbol": "SELLUSDT",
                        "base": "SELL",
                        "event_ts": 2_000_000_000,
                        "prices": [(0, 1.00), (6 * 3600, 0.95), (30 * 3600, 1.05)],
                    }
                ],
            )

            result = replay_listing_event_drift_reversal(
                normalizer_path=normalizer,
                cfg=ReplayConfig(min_trades=2, min_oos_trades=1),
            )

            trade = result["trades"][0]
            self.assertEqual(result["coverage"]["executed_trades"], 1)
            self.assertEqual(trade["signal"], "long_after_initial_selloff")
            self.assertEqual(trade["side"], "long")
            self.assertEqual(trade["cost_bps"], 30.0)
            self.assertGreater(trade["net_pnl_quote"], 0)
            self.assertFalse(result["live_orders"])
            self.assertFalse(result["api_keys"])
            self.assertFalse(result["leverage_or_margin"])

    def test_initial_pump_is_blocked_short_and_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalizer = write_replay_inputs(
                Path(tmp),
                [
                    {
                        "exchange": "gateio",
                        "symbol": "PUMP_USDT",
                        "base": "PUMP",
                        "event_ts": 2_000_000_000,
                        "prices": [(0, 1.00), (6 * 3600, 1.05), (30 * 3600, 0.95)],
                    }
                ],
            )

            result = replay_listing_event_drift_reversal(normalizer_path=normalizer)

            self.assertEqual(result["coverage"]["executed_trades"], 0)
            self.assertEqual(result["coverage"]["signal_counts"]["blocked_short_after_initial_pump"], 1)
            self.assertEqual(result["summary"]["trades"], 0)
            self.assertFalse(result["paper_forward_allowed"])
            self.assertFalse(result["leverage_or_margin"])

    def test_missing_exit_horizon_does_not_reuse_last_available_candle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalizer = write_replay_inputs(
                Path(tmp),
                [
                    {
                        "exchange": "mexc",
                        "symbol": "SHORTUSDT",
                        "base": "SHORT",
                        "event_ts": 2_000_000_000,
                        "prices": [(0, 1.00), (6 * 3600, 0.95)],
                    }
                ],
            )

            result = replay_listing_event_drift_reversal(normalizer_path=normalizer)

        self.assertEqual(result["coverage"]["executed_trades"], 0)
        self.assertEqual(result["coverage"]["signal_counts"]["missing_candles"], 1)
        self.assertIsNone(result["events"][0].get("exit_candle_ts"))

    def test_rejects_when_min_trades_not_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalizer = write_replay_inputs(
                Path(tmp),
                [
                    {
                        "exchange": "mexc",
                        "symbol": "ONEUSDT",
                        "base": "ONE",
                        "event_ts": 2_000_000_000,
                        "prices": [(0, 1.00), (6 * 3600, 0.95), (30 * 3600, 1.05)],
                    }
                ],
            )

            result = replay_listing_event_drift_reversal(normalizer_path=normalizer, cfg=ReplayConfig(min_trades=10))

            self.assertEqual(result["decision"], "LISTING_EVENT_REPLAY_PLANONLY_REJECTED_INSUFFICIENT_TRADES")
            self.assertIn("min_trades_not_met", result["research_acceptance"]["reasons"])
            self.assertFalse(result["research_acceptance"]["robust_candidate"])
            self.assertFalse(result["replay_allowed_now"])

    def test_candidate_still_requires_independent_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            for index in range(10):
                exchange = ["mexc", "gateio", "bitget"][index % 3]
                symbol = f"EDGE{index}USDT" if exchange != "gateio" else f"EDGE{index}_USDT"
                events.append(
                    {
                        "exchange": exchange,
                        "symbol": symbol,
                        "base": f"EDGE{index}",
                        "event_ts": 2_000_000_000 + index * 100_000,
                        "prices": [(0, 1.00), (6 * 3600, 0.95), (30 * 3600, 1.05)],
                    }
                )
            normalizer = write_replay_inputs(Path(tmp), events)

            result = replay_listing_event_drift_reversal(normalizer_path=normalizer)

            self.assertEqual(result["decision"], "LISTING_EVENT_REPLAY_PLANONLY_CANDIDATE_REQUIRES_INDEPENDENT_VALIDATION")
            self.assertTrue(result["research_acceptance"]["robust_candidate"])
            self.assertFalse(result["strategy_accepted"])
            self.assertFalse(result["paper_forward_allowed"])
            self.assertEqual(result["oos"]["summary"]["trades"], 3)
            self.assertTrue(result["walk_forward"]["accepted"])
            self.assertGreater(result["stress"]["summary"]["expectancy_quote"], 0)


if __name__ == "__main__":
    unittest.main()
