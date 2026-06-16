from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from event_labeler import EventQualityConfig, build_event_quality_report, run_event_quality_report_file  # noqa: E402
from cli import build_parser  # noqa: E402


def _bbo(ts: float, bid: float, ask: float, bid_qty: float = 10.0, ask_qty: float = 10.0) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": "gateio",
        "symbol": "HYPE_USDT",
        "event_kind": "bbo",
        "bid_price": bid,
        "bid_qty": bid_qty,
        "ask_price": ask,
        "ask_qty": ask_qty,
        "mark_price": (bid + ask) / 2.0,
        "index_price": (bid + ask) / 2.0,
        "funding_rate": 0.0001,
    }


def _trade(ts: float, side: str, price: float, qty: float = 20.0) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": "gateio",
        "symbol": "HYPE_USDT",
        "event_kind": "trade",
        "trade_id": int(ts * 1000),
        "side": side,
        "price": price,
        "qty": qty,
        "mark_price": price,
        "index_price": price,
        "funding_rate": 0.0001,
    }


class EventLabelerTests(unittest.TestCase):
    def test_sell_sweep_reclaim_labels_long_target_before_stop(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.1),
            _trade(2.0, "sell", 99.8),
            _bbo(3.0, 100.0, 100.1),
            _bbo(4.0, 100.2, 100.3),
        ]

        report = build_event_quality_report(
            _write_events(events),
            EventQualityConfig(lookback_sec=10, horizon_sec=10, min_sweep_notional_quote=1000, target_bps=5, stop_bps=5),
        )

        self.assertEqual(report["total_sweeps"], 1)
        label = report["events"][0]
        self.assertEqual(label["sweep_side"], "sell")
        self.assertEqual(label["expected_side"], "LONG")
        self.assertTrue(label["reclaimed"])
        self.assertEqual(label["first_hit"], "target")
        self.assertEqual(label["outcome"], "target_before_stop")
        self.assertGreater(label["favorable_excursion_bps"], 5)

    def test_buy_sweep_reclaim_labels_short_stop_before_target(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.1),
            _trade(2.0, "buy", 100.4),
            _bbo(3.0, 100.0, 100.1),
            _bbo(4.0, 100.3, 100.4),
        ]

        report = build_event_quality_report(
            _write_events(events),
            EventQualityConfig(lookback_sec=10, horizon_sec=10, min_sweep_notional_quote=1000, target_bps=5, stop_bps=5),
        )

        self.assertEqual(report["total_sweeps"], 1)
        label = report["events"][0]
        self.assertEqual(label["sweep_side"], "buy")
        self.assertEqual(label["expected_side"], "SHORT")
        self.assertTrue(label["reclaimed"])
        self.assertEqual(label["first_hit"], "stop")
        self.assertEqual(label["outcome"], "stop_before_target")
        self.assertLess(label["adverse_excursion_bps"], -5)

    def test_no_reclaim_is_counted_as_false_sweep(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.1),
            _trade(2.0, "sell", 99.8),
            _bbo(3.0, 99.7, 99.8),
        ]

        report = build_event_quality_report(
            _write_events(events),
            EventQualityConfig(lookback_sec=10, horizon_sec=10, min_sweep_notional_quote=1000),
        )

        self.assertEqual(report["summary"]["total_sweeps"], 1)
        self.assertEqual(report["summary"]["reclaimed"], 0)
        self.assertEqual(report["summary"]["false_sweep_rate"], 1.0)
        self.assertEqual(report["events"][0]["outcome"], "no_reclaim")

    def test_report_file_and_cli_parser(self) -> None:
        events = [_bbo(1.0, 100.0, 100.1), _trade(2.0, "sell", 99.8), _bbo(3.0, 100.0, 100.1)]
        parser = build_parser()
        self.assertEqual(parser.parse_args(["event-quality-report"]).command, "event-quality-report")

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "events.jsonl"
            out = Path(tmp) / "report.json"
            src.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            report = run_event_quality_report_file(
                src,
                out,
                EventQualityConfig(lookback_sec=10, horizon_sec=10, min_sweep_notional_quote=1000),
            )

            self.assertTrue(out.exists())
            self.assertEqual(report["output"], str(out))
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["mode"], "event_quality_report")


def _write_events(events: list[dict[str, object]]) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".jsonl")
    with tmp:
        tmp.write("\n".join(json.dumps(event) for event in events))
    return Path(tmp.name)


if __name__ == "__main__":
    unittest.main()
