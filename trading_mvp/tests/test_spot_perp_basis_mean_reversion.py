from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spot_perp_basis_mean_reversion import (  # noqa: E402
    SpotPerpBasisPlanConfig,
    basis_bps,
    build_planonly_report,
    classify_basis_signal,
    round_trip_cost_hurdle_bps,
)


class SpotPerpBasisMathTests(unittest.TestCase):
    def test_basis_bps_uses_spot_as_denominator(self) -> None:
        self.assertAlmostEqual(basis_bps(100.0, 101.0), 100.0)

    def test_round_trip_hurdle_includes_both_legs_open_close_and_buffer(self) -> None:
        cfg = SpotPerpBasisPlanConfig(
            spot_fee_bps_per_side=10,
            perp_fee_bps_per_side=8,
            spot_slippage_bps_per_side=2,
            perp_slippage_bps_per_side=3,
            adverse_basis_buffer_bps=15,
        )
        self.assertAlmostEqual(round_trip_cost_hurdle_bps(cfg), 61.0)

    def test_positive_basis_above_hurdle_allows_long_spot_short_perp(self) -> None:
        cfg = SpotPerpBasisPlanConfig(adverse_basis_buffer_bps=0)
        result = classify_basis_signal(
            spot_mid=100.0,
            perp_mid=101.0,
            spot_spread_bps=5.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            cfg=cfg,
        )
        self.assertEqual(result["signal"], "long_spot_short_perp")
        self.assertTrue(result["allowed"])
        self.assertGreater(result["basis_bps"], result["cost_hurdle_bps"])

    def test_negative_basis_is_blocked_without_spot_short(self) -> None:
        cfg = SpotPerpBasisPlanConfig(adverse_basis_buffer_bps=0, allow_spot_short=False)
        result = classify_basis_signal(
            spot_mid=100.0,
            perp_mid=99.0,
            spot_spread_bps=5.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            cfg=cfg,
        )
        self.assertEqual(result["signal"], "short_spot_long_perp")
        self.assertFalse(result["allowed"])
        self.assertIn("negative_basis_requires_spot_short", result["reasons"])

    def test_wide_spread_blocks_even_large_basis(self) -> None:
        cfg = SpotPerpBasisPlanConfig(adverse_basis_buffer_bps=0, max_spot_spread_bps=10)
        result = classify_basis_signal(
            spot_mid=100.0,
            perp_mid=102.0,
            spot_spread_bps=20.0,
            perp_spread_bps=5.0,
            funding_rate=0.0001,
            cfg=cfg,
        )
        self.assertFalse(result["allowed"])
        self.assertIn("spot_spread_too_wide", result["reasons"])


class SpotPerpBasisPlanOnlyTests(unittest.TestCase):
    def test_planonly_report_blocks_collect_replay_grid_and_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run = repo / "exports" / "trading-mvp" / "daily" / "daily_test"
            run.mkdir(parents=True)
            (run / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "daily_test",
                        "klines_rows_total": 10,
                        "funding_rows_total": 20,
                        "universe": [
                            {
                                "exchange": "mexc",
                                "symbol": "HYPE_USDT",
                                "base": "HYPE",
                                "non_binance_baseline": True,
                            },
                            {
                                "exchange": "gateio",
                                "symbol": "HYPE_USDT",
                                "base": "HYPE",
                                "non_binance_baseline": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = build_planonly_report(repo_root=repo)

        self.assertEqual(
            report["decision"],
            "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_READY_FOR_AVAILABILITY_PREFLIGHT",
        )
        self.assertFalse(report["collect_allowed_now"])
        self.assertFalse(report["replay_allowed_now"])
        self.assertFalse(report["grid_allowed_now"])
        self.assertFalse(report["live_orders"])
        self.assertFalse(report["api_keys"])
        self.assertFalse(report["leverage_or_margin"])
        self.assertFalse(report["strategy_accepted"])
        self.assertTrue(report["availability_snapshot"]["perp_history_hint"])
        self.assertFalse(report["availability_snapshot"]["paired_spot_perp_history_ready"])


if __name__ == "__main__":
    unittest.main()
