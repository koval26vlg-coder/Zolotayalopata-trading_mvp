from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slow_liquidity_fixed_compression_v1_plan import (  # noqa: E402
    V1_DECISION,
    build_fixed_compression_v1_plan,
)
from slow_liquidity_provenance import canonical_plan_hash, sha256_file  # noqa: E402


class SlowLiquidityFixedCompressionV1PlanTests(unittest.TestCase):
    def test_plan_freezes_inherited_threshold_and_dimensional_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.jsonl"
            manifest = root / "manifest.json"
            fixed_v0 = root / "fixed_v0.json"
            quality = root / "quality.json"
            output = root / "fixed_v1.json"
            history.write_text(
                json.dumps(
                    {
                        "exchange": "mexc",
                        "symbol": "AAAUSDT",
                        "base": "AAA",
                        "quote": "USDT",
                        "granularity": "1h",
                        "candle_ts": 1,
                        "open": 100,
                        "high": 101,
                        "low": 99,
                        "close": 100,
                        "volume": 1,
                        "quote_volume": 100,
                        "data_status": "ok",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manifest.write_text(json.dumps({"final": True, "run_id": "fixture"}), encoding="utf-8")
            fixed_v0.write_text(
                json.dumps(
                    {
                        "decision": "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER",
                        "clean_slice": {"clean_bases": ["AAA"], "required_timeframes": ["1h", "4h"]},
                        "fixed_signal_v0": {
                            "name": "slow_liquidity_regime_breakout_retest_v0",
                            "lookback_1h_bars": 96,
                            "compression_range_width_max_atr": 1.2,
                        },
                        "base_fee_cost_model": {"minimum_target_after_cost_bps": 300.0},
                        "validation_contract": {"min_independent_events": 100},
                    }
                ),
                encoding="utf-8",
            )
            quality.write_text(json.dumps({"accepted": True}), encoding="utf-8")

            result = build_fixed_compression_v1_plan(
                history_jsonl_path=history,
                history_manifest_path=manifest,
                fixed_signal_path=fixed_v0,
                quality_path=quality,
                output_path=output,
            )
            self.assertTrue(output.exists())
            expected_parent_plan_hash = canonical_plan_hash(json.loads(fixed_v0.read_text(encoding="utf-8")))
            fixed_v0_file_sha = sha256_file(fixed_v0)

        self.assertEqual(result["decision"], V1_DECISION)
        self.assertEqual(result["fixed_signal_v1"]["compression_range_width_max_atr"], 1.2)
        self.assertEqual(result["fixed_signal_v1"]["compression_metric"], "range_width_over_atr_sqrt_lookback")
        self.assertEqual(len(result["plan_hash"]), 64)
        self.assertEqual(result["input_binding"]["plan_hash"], expected_parent_plan_hash)
        self.assertNotEqual(result["input_binding"]["plan_hash"], fixed_v0_file_sha)
        self.assertTrue(result["hypothesis_contract"]["no_data_driven_threshold_selection"])

    def test_wrapper_is_visible_gate_bound_and_non_live(self) -> None:
        wrapper = REPO_ROOT / "tools" / "trading_slow_liquidity_fixed_compression_v1_planonly.ps1"
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(wrapper)
        for needle in (
            "check_active_run_gate.ps1",
            "BLOCKED_BY_ACTIVE_RUN_GATE",
            "SLOW_LIQUIDITY_FIXED_V1_COMPRESSION_PLANONLY_READY_FOR_FEATURE_NORMALIZER",
            "strategy_branch_status",
            "grid_allowed",
            "paper_forward_allowed",
            "live_orders",
            "api_keys",
            "leverage_or_margin",
        ):
            self.assertIn(needle, text)

    def test_controller_requires_approval_before_new_structural_hypothesis(self) -> None:
        next_step = (REPO_ROOT / "tools" / "trading_next_goal_step.ps1").read_text(encoding="utf-8")
        goal_status = (REPO_ROOT / "tools" / "trading_goal_status.ps1").read_text(encoding="utf-8")
        self.assertIn("await_explicit_user_approval_for_new_structural_hypothesis", next_step)
        self.assertIn("$newStructuralHypothesisApprovalRequired", next_step)
        self.assertIn("slow_liquidity_new_structural_hypothesis_requires_user_approval", goal_status)


if __name__ == "__main__":
    unittest.main()
