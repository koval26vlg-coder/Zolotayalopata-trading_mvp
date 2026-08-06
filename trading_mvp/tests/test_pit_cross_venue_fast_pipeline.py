from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_cross_venue_fast_pipeline import FastGateConfig, evaluate_observations  # noqa: E402


def _row(cycle: int, base: str, *, net: float, direction: str = "buy_a_sell_b") -> dict:
    return {
        "cycle": cycle,
        "base": base,
        "direction": direction,
        "fully_valid": True,
        "net_bps": net,
    }


class FastPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = FastGateConfig(
            min_attempt_cycles=20,
            min_fully_valid_observations=20,
            min_fixed_cost_positive_observations=6,
            independence_gap_cycles=3,
            min_independent_episodes=6,
            min_event_bases=3,
            max_top1_episode_concentration=0.50,
            max_top3_episode_concentration=1.0,
            time_block_count=4,
            min_active_time_blocks=2,
            min_second_half_rate_ratio=0.25,
            max_short_probe_bases=3,
            min_candidate_episodes=2,
        )

    def test_diverse_fixed_cost_episodes_pass_short_probe_gate(self) -> None:
        observations = [_row(cycle, "BASE", net=-1.0) for cycle in range(1, 25)]
        observations.extend(
            [
                _row(2, "AAA", net=2.0),
                _row(6, "AAA", net=3.0),
                _row(10, "BBB", net=2.0),
                _row(14, "BBB", net=4.0),
                _row(18, "CCC", net=2.0),
                _row(22, "CCC", net=5.0),
            ]
        )

        result = evaluate_observations(observations, attempt_cycles=24, failed_cycles=2, config=self.config)

        self.assertTrue(result["eligible_for_short_probe"])
        self.assertEqual(result["independent_episodes"], 6)
        self.assertEqual(set(result["candidate_bases"]), {"AAA", "BBB", "CCC"})

    def test_no_fixed_cost_positive_edge_is_rejected(self) -> None:
        observations = [_row(cycle, "AAA", net=-1.0) for cycle in range(1, 25)]

        result = evaluate_observations(observations, attempt_cycles=24, failed_cycles=0, config=self.config)

        self.assertFalse(result["eligible_for_short_probe"])
        self.assertEqual(result["fixed_cost_positive_observations"], 0)
        self.assertIn("insufficient_fixed_cost_positive_observations", result["eligibility_reasons"])

    def test_single_base_concentration_is_rejected(self) -> None:
        observations = [_row(cycle, "BASE", net=-1.0) for cycle in range(1, 25)]
        observations.extend(_row(cycle, "AAA", net=2.0) for cycle in (2, 5, 8, 11, 14, 17, 20))

        result = evaluate_observations(observations, attempt_cycles=24, failed_cycles=0, config=self.config)

        self.assertFalse(result["eligible_for_short_probe"])
        self.assertEqual(result["top1_episode_concentration"], 1.0)
        self.assertIn("top1_episode_concentration_above_cap", result["eligibility_reasons"])


if __name__ == "__main__":
    unittest.main()
