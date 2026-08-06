from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from spot_perp_basis_history_v2_train import (  # noqa: E402
    compute_episode_metrics,
    simulate_asset_train,
)


def row(ts: int, *, spot_close: float, mark_close: float, spot_open: float | None = None, perp_open: float | None = None) -> dict:
    spot_open_value = spot_close if spot_open is None else spot_open
    perp_open_value = mark_close if perp_open is None else perp_open
    return {
        "ts": ts,
        "canonical_asset_id": "coingecko:test",
        "base": "TEST",
        "spot": {"open": spot_open_value, "high": max(spot_open_value, spot_close), "low": min(spot_open_value, spot_close), "close": spot_close},
        "perp": {"open": perp_open_value, "high": max(perp_open_value, mark_close), "low": min(perp_open_value, mark_close), "close": mark_close},
        "mark": {"open": mark_close, "high": mark_close, "low": mark_close, "close": mark_close},
    }


class GateSpotPerpTrainEvaluatorTests(unittest.TestCase):
    def test_signal_enters_next_open_and_exits_after_closed_convergence_hour(self) -> None:
        rows = [
            row(0, spot_close=100.0, mark_close=102.0),
            row(3600, spot_close=100.0, mark_close=101.5, spot_open=101.0, perp_open=103.0),
            row(7200, spot_close=101.0, mark_close=101.1, spot_open=102.0, perp_open=101.0),
            row(10800, spot_close=101.0, mark_close=101.1, spot_open=102.0, perp_open=101.0),
        ]
        episodes, diagnostics = simulate_asset_train(
            base="TEST",
            canonical_asset_id="coingecko:test",
            rows=rows,
            funding_rows=[],
            signal_start_sec=0,
            train_end_sec=14400,
            entry_threshold_bps=132.0,
            exit_threshold_bps=20.0,
            max_hold_hours=72,
            adverse_funding_entry_floor=-0.0003,
            normal_cycle_cost_bps=82.0,
            stress_cycle_cost_bps=92.0,
            notional_per_leg_quote=500.0,
        )

        self.assertEqual(diagnostics["signals"], 1)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["signal_ts"], 0)
        self.assertEqual(episodes[0]["entry_ts"], 3600)
        self.assertEqual(episodes[0]["exit_ts"], 10800)
        self.assertEqual(episodes[0]["exit_reason"], "basis_converged")
        self.assertGreater(episodes[0]["price_gross_bps"], 0)

    def test_adverse_latest_funding_blocks_entry(self) -> None:
        rows = [row(index * 3600, spot_close=100.0, mark_close=102.0) for index in range(75)]
        episodes, diagnostics = simulate_asset_train(
            base="TEST",
            canonical_asset_id="coingecko:test",
            rows=rows,
            funding_rows=[{"ts": 0, "funding_rate": -0.001}],
            signal_start_sec=0,
            train_end_sec=75 * 3600,
            entry_threshold_bps=132.0,
            exit_threshold_bps=20.0,
            max_hold_hours=72,
            adverse_funding_entry_floor=-0.0003,
            normal_cycle_cost_bps=82.0,
            stress_cycle_cost_bps=92.0,
            notional_per_leg_quote=500.0,
        )
        self.assertEqual(episodes, [])
        self.assertGreater(diagnostics["blocked_adverse_funding"], 0)

    def test_metrics_apply_costs_and_do_not_allow_funding_to_rescue_price_gate(self) -> None:
        episodes = [
            {"base": "A", "entry_ts": 0, "exit_ts": 3600, "price_normal_net_quote": -1.0, "price_stress_net_quote": -2.0, "funding_quote": 10.0},
            {"base": "B", "entry_ts": 86400, "exit_ts": 90000, "price_normal_net_quote": 3.0, "price_stress_net_quote": 2.0, "funding_quote": 0.0},
        ]
        metrics = compute_episode_metrics(episodes)
        self.assertEqual(metrics["episode_count"], 2)
        self.assertEqual(metrics["price_normal_net_quote"], 2.0)
        self.assertEqual(metrics["total_normal_net_quote"], 12.0)
        self.assertGreater(metrics["price_profit_factor"], 1.0)


if __name__ == "__main__":
    unittest.main()
