"""The expansion first read must stay descriptive, guarded, and correctly bound.

Three properties are worth pinning, because each of them is the difference between a
read and a claim:

  * the peeking guard still refuses metrics below the pre-registered minimum, even
    though the core is now shared between two tracks;
  * the shared core still emits exactly what the forward evaluator always emitted, so
    parameterising it did not quietly change the older track's output;
  * a state collected under one plan cannot be evaluated against a different one.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import slow_liquidity_listing_momentum_forward_evaluator as forward  # noqa: E402
import slow_liquidity_listing_momentum_forward_expansion_evaluator as expansion  # noqa: E402


def _state(complete: int, *, monitor: str = expansion.PLAN_ID) -> dict:
    windows = [
        {
            "exchange": "okx",
            "base": f"T{i}",
            "window_complete": True,
            "stats": {
                "ret_24h": 0.10,
                "ret_72h": 0.20,
                "max_runup": 0.5,
                "max_drawdown": -0.1,
            },
        }
        for i in range(complete)
    ]
    return {"monitor": monitor, "windows": windows, "ticks": []}


class PeekingGuardTests(unittest.TestCase):
    def test_metrics_are_frozen_below_the_preregistered_minimum(self):
        result = forward.evaluate_forward_state(
            _state(forward.FIRST_READ_MIN_COMPLETE_WINDOWS - 1),
            evaluation_class=expansion.EVALUATION_CLASS,
            schema=expansion.EVALUATION_SCHEMA,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE_NO_METRICS")
        self.assertNotIn("metrics", result)
        self.assertEqual(result["acceptance_decision"], "NONE")

    def test_metrics_appear_exactly_at_the_minimum(self):
        result = forward.evaluate_forward_state(
            _state(forward.FIRST_READ_MIN_COMPLETE_WINDOWS),
            evaluation_class=expansion.EVALUATION_CLASS,
            schema=expansion.EVALUATION_SCHEMA,
        )
        self.assertIn("metrics", result)
        self.assertEqual(result["complete_windows"], 30)
        # A first read describes; it never accepts.
        self.assertEqual(result["acceptance_decision"], "NONE")


class SharedCoreTests(unittest.TestCase):
    def test_the_forward_track_still_emits_its_own_class_and_schema(self):
        # Parameterising the core must not have moved the older track's output.
        result = forward.evaluate_forward_state(_state(30))
        self.assertEqual(result["evaluation_class"], forward.EVALUATION_CLASS)
        self.assertEqual(
            result["schema"],
            "trading_mvp_slow_liquidity_listing_momentum_forward_evaluation_v1",
        )

    def test_the_expansion_track_is_distinguishable_in_its_output(self):
        result = forward.evaluate_forward_state(
            _state(30),
            evaluation_class=expansion.EVALUATION_CLASS,
            schema=expansion.EVALUATION_SCHEMA,
        )
        self.assertNotEqual(result["evaluation_class"], forward.EVALUATION_CLASS)
        self.assertEqual(result["evaluation_class"], expansion.EVALUATION_CLASS)


class BindingTests(unittest.TestCase):
    def test_a_state_from_another_plan_is_refused(self):
        with self.assertRaisesRegex(Exception, "but this evaluation binds"):
            expansion._require_state_matches_bound_plan(
                _state(30, monitor="some_other_plan_v1"),
                {"plan_id": "slow_liquidity_listing_momentum_forward_expansion_20260825_v5"},
            )

    def test_a_matching_state_is_accepted(self):
        expansion._require_state_matches_bound_plan(
            _state(30, monitor="plan_x"), {"plan_id": "plan_x"}
        )


class AuthorityTests(unittest.TestCase):
    def test_no_read_of_any_kind_can_authorize(self):
        import json

        plan = json.loads(expansion.PLAN_PATH.read_text(encoding="utf-8"))
        acceptance = plan["acceptance_policy"]
        for key in (
            "first_read_authorizes",
            "terminal_read_authorizes",
            "live_trading_authorized",
        ):
            with self.subTest(key=key):
                self.assertIs(acceptance[key], False)

    def test_the_issued_plan_validates(self):
        import json

        expansion.validate_plan(
            json.loads(expansion.PLAN_PATH.read_text(encoding="utf-8"))
        )


if __name__ == "__main__":
    unittest.main()
