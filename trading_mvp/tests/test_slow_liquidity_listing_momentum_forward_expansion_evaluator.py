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


def _state(complete: int, *, monitor: str = "") -> dict:
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
    return {
        "monitor": monitor or "slow_liquidity_listing_momentum_forward_expansion_20260825_v8",
        "windows": windows,
        "ticks": [],
    }


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

    def test_legacy_tokenized_and_unclassified_windows_are_descriptive_only(self):
        state = _state(30)
        for index, window in enumerate(state["windows"]):
            if index % 3 == 0:
                window.update(
                    {
                        "asset_class": "tokenized_equity",
                        "asset_class_source": "declared_spot_asset_registry_v1",
                        "asset_class_acceptance_eligible": False,
                    }
                )
            elif index % 3 == 1:
                window.update(
                    {
                        "asset_class": "unclassified",
                        "asset_class_source": "unclassified_no_positive_identity",
                        "asset_class_acceptance_eligible": False,
                    }
                )

        result = expansion.evaluate_expansion_state(state)

        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE_NO_METRICS")
        self.assertEqual(result["complete_windows"], 0)
        self.assertEqual(result["descriptive_only_window_count"], 30)
        self.assertEqual(result["crypto_acceptance_window_count"], 0)
        self.assertEqual(result["acceptance_decision"], "NONE")
        self.assertNotIn("metrics", result)

    def test_only_positive_crypto_identity_can_enter_expansion_metrics(self):
        state = _state(30)
        for window in state["windows"]:
            window.update(
                {
                    "asset_class": "crypto_token",
                    "asset_class_source": "declared_spot_asset_registry_v1",
                    "asset_class_acceptance_eligible": True,
                }
            )

        result = expansion.evaluate_expansion_state(state)

        self.assertEqual(result["status"], "EVALUATED_DESCRIPTIVE")
        self.assertEqual(result["complete_windows"], 30)
        self.assertEqual(result["crypto_acceptance_window_count"], 30)
        self.assertEqual(result["descriptive_only_window_count"], 0)

    def test_unbound_crypto_label_cannot_self_promote_into_acceptance(self):
        state = _state(30)
        for window in state["windows"]:
            window.update(
                {
                    "asset_class": "crypto_token",
                    "asset_class_source": "arbitrary_unbound_label",
                    "asset_class_acceptance_eligible": True,
                }
            )

        result = expansion.evaluate_expansion_state(state)

        self.assertEqual(result["complete_windows"], 0)
        self.assertEqual(result["crypto_acceptance_window_count"], 0)
        self.assertEqual(result["descriptive_only_window_count"], 30)
        self.assertNotIn("metrics", result)

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
                {"plan_id": "slow_liquidity_listing_momentum_forward_expansion_20260825_v8"},
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

    def test_evaluator_plan_has_a_new_immutable_identity_and_supersedes_v1(self):
        import json

        plan = json.loads(expansion.PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            plan["plan_id"],
            "slow_liquidity_listing_momentum_forward_expansion_evaluator_20260825_v4",
        )
        self.assertEqual(
            plan["supersedes"]["plan_hash"],
            "0136c144f4a9027dedd59af5c3811ef56afb5eb48e251ca981a314655c266851",
        )
        self.assertEqual(
            plan["source_bindings"]["expansion_monitor_plan"]["plan_id"],
            "slow_liquidity_listing_momentum_forward_expansion_20260825_v8",
        )

    def test_asset_classifier_is_hash_bound_and_cannot_be_removed(self):
        import copy
        import json

        plan = json.loads(expansion.PLAN_PATH.read_text(encoding="utf-8"))
        roles = {row["role"] for row in plan["implementation"]["files"]}
        self.assertIn("spot_asset_classifier", roles)
        tampered = copy.deepcopy(plan)
        tampered["implementation"]["files"] = [
            row
            for row in tampered["implementation"]["files"]
            if row["role"] != "spot_asset_classifier"
        ]
        tampered["plan_hash"] = expansion._canonical_hash_without(
            tampered, "plan_hash"
        )
        with self.assertRaisesRegex(Exception, "implementation roles"):
            expansion.validate_plan(tampered)

    def test_legacy_mixed_sample_is_explicitly_descriptive_only(self):
        import json

        plan = json.loads(expansion.PLAN_PATH.read_text(encoding="utf-8"))
        contract = plan["asset_class_contract"]
        self.assertEqual(contract["acceptance_asset_class"], "crypto_token")
        self.assertFalse(contract["legacy_mixed_sample_acceptance_eligible"])


if __name__ == "__main__":
    unittest.main()
