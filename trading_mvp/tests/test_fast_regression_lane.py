from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import fast_regression_lane as lane  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


class FastRegressionLaneTests(unittest.TestCase):
    def test_lane_is_unique_bounded_and_excludes_heavy_or_market_runs(self) -> None:
        modules = lane.validate_fast_test_modules(lane.FAST_TEST_MODULES)
        self.assertEqual(len(modules), len(set(modules)))
        self.assertLessEqual(lane.MAX_RUNTIME_SEC, 300)
        rendered = "\n".join(modules).casefold()
        for forbidden in ("_collect", "_oos", "_grid", "_backtest", "_live_"):
            self.assertNotIn(forbidden, rendered)

    def test_lane_covers_autopilot_paper_security_and_economics(self) -> None:
        modules = set(lane.FAST_TEST_MODULES)
        required = {
            "trading_mvp.tests.test_autopilot_guard",
            "trading_mvp.tests.test_basis_paper_oms",
            "trading_mvp.tests.test_costs",
            "trading_mvp.tests.test_dense_ws_campaign_contract",
            "trading_mvp.tests.test_dense_ws_campaign_quality",
            "trading_mvp.tests.test_dense_ws_causal_materializer",
            "trading_mvp.tests.test_dense_ws_materialization_bound_plan",
            "trading_mvp.tests.test_dense_ws_signal_evaluator_contract",
            "trading_mvp.tests.test_dense_ws_acceptance_proposal",
            "trading_mvp.tests.test_dense_ws_signal_evaluator_freeze",
            "trading_mvp.tests.test_dense_ws_execution_realization",
            "trading_mvp.tests.test_dense_ws_postrun_orchestration",
            "trading_mvp.tests.test_execution_gate",
            "trading_mvp.tests.test_global_market_writer_claim",
            "trading_mvp.tests.test_paper_observer_runtime",
            "trading_mvp.tests.test_paper_runtime_fault_injection",
            "trading_mvp.tests.test_paper_log_redaction",
        }
        self.assertTrue(required.issubset(modules))

    def test_visible_wrapper_has_no_background_or_discovery(self) -> None:
        source = (
            REPO_ROOT / "tools" / "run_trading_mvp_fast_regression.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertNotIn("Start-Process", source)
        self.assertNotIn("discover", source)
        self.assertIn("MaxRuntimeSec", source)

    def test_validator_rejects_forbidden_or_duplicate_modules(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            lane.validate_fast_test_modules(
                ["trading_mvp.tests.test_market_collect"]
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            lane.validate_fast_test_modules(
                [
                    "trading_mvp.tests.test_costs",
                    "trading_mvp.tests.test_costs",
                ]
            )


if __name__ == "__main__":
    unittest.main()
