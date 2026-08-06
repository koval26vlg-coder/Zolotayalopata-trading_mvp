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
from event_validation import EventValidationConfig, build_event_validation_report, run_event_validation_file  # noqa: E402


def _event(
    idx: int,
    *,
    outcome: str = "target_before_stop",
    market: str = "gateio:HYPE_USDT",
    side: str = "LONG",
    intensity: float = 8.0,
    reclaim_sec: float | None = 10.0,
    spread: float = 0.5,
    basis: float = 1.0,
    notional: float = 5000.0,
    favorable: float | None = 10.0,
    adverse: float | None = -2.0,
) -> dict[str, object]:
    reclaimed = outcome != "no_reclaim"
    return {
        "market": market,
        "exchange": market.split(":", 1)[0],
        "symbol": market.split(":", 1)[1],
        "sweep_side": "sell" if side == "LONG" else "buy",
        "expected_side": side,
        "sweep_ts": float(idx),
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


def _report(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "mode": "event_quality_report",
        "input": "fixture.jsonl",
        "summary": {},
        "events": events,
    }


class EventValidationTests(unittest.TestCase):
    def test_accepts_stable_slice_across_oos_walk_forward_and_stress(self) -> None:
        events = [_event(idx) for idx in range(12)]

        report = build_event_validation_report(
            _report(events),
            EventValidationConfig(
                train_fraction=0.5,
                walk_forward_windows=3,
                walk_forward_min_pass_ratio=1.0,
                min_events=2,
                min_reclaimed=2,
                min_target_before_stop_rate=0.80,
                min_target_rate_all=0.80,
                max_false_sweep_rate=0.25,
                max_avg_adverse_bps=3.0,
                min_favorable_to_adverse=2.0,
                min_sweep_intensity_bps=(0.0,),
                max_time_to_reclaim_sec=(0.0, 30.0),
                max_pre_spread_bps=(0.0, 1.0),
                max_abs_basis_bps=(0.0, 5.0),
                min_trade_notional_quote=(0.0, 1000.0),
                stress_favorable_haircut_bps=1.0,
                stress_adverse_widen_bps=0.5,
                stress_target_bps=6.0,
                stress_stop_bps=3.0,
            ),
        )

        self.assertTrue(report["accepted"])
        self.assertTrue(report["oos"]["accepted"])
        self.assertTrue(report["walk_forward"]["accepted"])
        self.assertTrue(report["stress"]["accepted"])
        self.assertEqual(report["selected_slice"]["selection_basis"], "train_eligible")

    def test_rejects_train_fit_that_fails_oos(self) -> None:
        events = [
            *[_event(idx) for idx in range(6)],
            *[_event(idx, outcome="stop_before_target", favorable=4.0, adverse=-8.0) for idx in range(6, 12)],
        ]

        report = build_event_validation_report(
            _report(events),
            EventValidationConfig(
                train_fraction=0.5,
                walk_forward_windows=2,
                min_events=2,
                min_reclaimed=2,
                min_target_before_stop_rate=0.75,
                min_target_rate_all=0.75,
                max_false_sweep_rate=0.30,
                max_avg_adverse_bps=5.0,
                min_favorable_to_adverse=1.0,
                min_sweep_intensity_bps=(0.0,),
                max_time_to_reclaim_sec=(0.0,),
                max_pre_spread_bps=(0.0,),
                max_abs_basis_bps=(0.0,),
                min_trade_notional_quote=(0.0,),
            ),
        )

        self.assertFalse(report["accepted"])
        self.assertTrue(report["train"]["selected"]["accepted"])
        self.assertFalse(report["oos"]["accepted"])
        self.assertIn("oos_rejected", report["rejection_reasons"])

    def test_file_write_and_cli_parser(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["event-validation-report"]).command, "event-validation-report")

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "event_quality.json"
            out = Path(tmp) / "validation.json"
            src.write_text(json.dumps(_report([_event(idx) for idx in range(4)]), ensure_ascii=False), encoding="utf-8")

            result = run_event_validation_file(
                src,
                out,
                EventValidationConfig(
                    train_fraction=0.5,
                    walk_forward_windows=2,
                    min_events=1,
                    min_reclaimed=1,
                    min_sweep_intensity_bps=(0.0,),
                    max_time_to_reclaim_sec=(0.0,),
                    max_pre_spread_bps=(0.0,),
                    max_abs_basis_bps=(0.0,),
                    min_trade_notional_quote=(0.0,),
                ),
            )

            self.assertTrue(out.exists())
            self.assertEqual(result["output"], str(out))
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["mode"], "event_validation_report")


if __name__ == "__main__":
    unittest.main()
