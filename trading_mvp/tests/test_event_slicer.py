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
from event_slicer import EventSliceConfig, build_event_slice_report, run_event_slice_optimizer_file  # noqa: E402


def _event(
    *,
    market: str = "gateio:HYPE_USDT",
    side: str = "LONG",
    outcome: str = "target_before_stop",
    intensity: float = 5.0,
    reclaim_sec: float | None = 20.0,
    spread: float = 0.5,
    basis: float = 2.0,
    notional: float = 5000.0,
    adverse: float | None = -3.0,
    favorable: float | None = 8.0,
) -> dict[str, object]:
    reclaimed = outcome != "no_reclaim"
    return {
        "market": market,
        "exchange": market.split(":", 1)[0],
        "symbol": market.split(":", 1)[1],
        "sweep_side": "sell" if side == "LONG" else "buy",
        "expected_side": side,
        "sweep_ts": 1000.0,
        "sweep_price": 99.0,
        "sweep_level": 100.0,
        "sweep_intensity_bps": intensity,
        "trade_notional_quote": notional,
        "pre_spread_bps": spread,
        "mark_index_basis_bps": basis,
        "reclaimed": reclaimed,
        "time_to_reclaim_sec": reclaim_sec if reclaimed else None,
        "favorable_excursion_bps": favorable if reclaimed else None,
        "adverse_excursion_bps": adverse if reclaimed else None,
        "outcome": outcome,
    }


class EventSlicerTests(unittest.TestCase):
    def test_optimizer_finds_eligible_high_quality_slice(self) -> None:
        events = [
            *[_event(outcome="target_before_stop") for _ in range(4)],
            _event(outcome="stop_before_target", adverse=-2.0, favorable=4.0),
            _event(market="mexc:HYPE_USDT", side="SHORT", outcome="stop_before_target", adverse=-12.0, favorable=3.0),
        ]
        report = build_event_slice_report(
            {"mode": "event_quality_report", "input": "fixture.json", "events": events, "summary": {}},
            EventSliceConfig(
                min_events=5,
                min_reclaimed=5,
                min_target_before_stop_rate=0.7,
                min_target_rate_all=0.7,
                max_avg_adverse_bps=5,
                min_sweep_intensity_bps=(0,),
                max_time_to_reclaim_sec=(0, 30),
                max_pre_spread_bps=(0, 1),
                max_abs_basis_bps=(0, 5),
                min_trade_notional_quote=(0, 1000),
                top_n=50,
            ),
        )

        self.assertGreaterEqual(report["eligible_slices"], 1)
        matching = [
            item
            for item in report["top_slices"]
            if item["eligible"] and item["market"] == "gateio:HYPE_USDT" and item["expected_side"] == "LONG"
        ]
        self.assertTrue(matching)
        self.assertEqual(matching[0]["target_before_stop_rate"], 0.8)

    def test_optimizer_reports_rejection_reasons_for_weak_slice(self) -> None:
        events = [
            _event(outcome="target_before_stop"),
            _event(outcome="stop_before_target", adverse=-20.0),
            _event(outcome="stop_before_target", adverse=-20.0),
        ]
        report = build_event_slice_report(
            {"mode": "event_quality_report", "events": events, "summary": {}},
            EventSliceConfig(
                min_events=5,
                min_reclaimed=5,
                min_target_before_stop_rate=0.7,
                min_target_rate_all=0.5,
                max_avg_adverse_bps=5,
                min_sweep_intensity_bps=(0,),
                max_time_to_reclaim_sec=(0,),
                max_pre_spread_bps=(0,),
                max_abs_basis_bps=(0,),
                min_trade_notional_quote=(0,),
                top_n=3,
            ),
        )

        self.assertEqual(report["eligible_slices"], 0)
        reasons = set(report["top_slices"][0]["eligibility_reasons"])
        self.assertIn("min_events", reasons)
        self.assertIn("min_target_before_stop_rate", reasons)
        self.assertIn("max_avg_adverse_bps", reasons)

    def test_report_file_and_cli_parser(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["event-slice-optimizer"]).command, "event-slice-optimizer")

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "event_quality.json"
            out = Path(tmp) / "slices.json"
            src.write_text(
                json.dumps({"mode": "event_quality_report", "events": [_event()], "summary": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = run_event_slice_optimizer_file(
                src,
                out,
                EventSliceConfig(
                    min_events=1,
                    min_reclaimed=1,
                    min_sweep_intensity_bps=(0,),
                    max_time_to_reclaim_sec=(0,),
                    max_pre_spread_bps=(0,),
                    max_abs_basis_bps=(0,),
                    min_trade_notional_quote=(0,),
                ),
            )

            self.assertTrue(out.exists())
            self.assertEqual(result["output"], str(out))
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["mode"], "event_slice_optimizer")


if __name__ == "__main__":
    unittest.main()
