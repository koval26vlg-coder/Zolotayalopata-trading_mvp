from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class SlowLiquidityFixedSignalPlanTests(unittest.TestCase):
    def test_fixed_signal_plan_script_is_guarded_and_non_starting(self) -> None:
        script = REPO_ROOT / "tools" / "trading_slow_liquidity_fixed_signal_planonly.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        for needle in (
            "trading_slow_liquidity_fixed_signal_planonly",
            "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER",
            "slow_liquidity_regime_breakout_retest",
            "base/VIP0/no-volume",
            "1h",
            "4h",
            "15m_signal_until_clean_15m_gate_passes",
            "grid_search",
            "live_orders",
            "api_keys",
            "paper_forward",
            "parameter_tuning_after_seeing_oos",
        ):
            self.assertIn(needle, text)

    def test_fixed_signal_plan_cli_writes_plan_from_quality_fixture(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        script = REPO_ROOT / "tools" / "trading_slow_liquidity_fixed_signal_planonly.ps1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path = root / "quality.json"
            output_path = root / "fixed_signal.json"
            quality_path.write_text(
                json.dumps(
                    {
                        "decision": "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY",
                        "accepted": True,
                        "warnings": ["15m_two_exchange_full_coverage_absent_use_1h4h_only"],
                        "clean_markets": {
                            "two_exchange_bases": ["AAA", "BBB"],
                            "two_exchange_full_coverage_1h4h_bases": ["AAA", "BBB"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-QualityPath",
                    str(quality_path),
                    "-OutputPath",
                    str(output_path),
                    "-Json",
                ],
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=90,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(output_path.exists())

        if payload["decision"] == "BLOCKED_BY_ACTIVE_RUN_GATE":
            self.assertFalse(payload["replay_allowed_now"])
            self.skipTest("active run gate blocks fixed signal PlanOnly")

        self.assertEqual(payload["decision"], "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER")
        self.assertFalse(payload["would_start"])
        self.assertFalse(payload["replay_allowed_now"])
        self.assertFalse(payload["grid_allowed_now"])
        self.assertFalse(payload["paper_forward_allowed"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["api_keys"])
        self.assertEqual(payload["clean_slice"]["required_timeframes"], ["1h", "4h"])
        self.assertIn("15m", payload["clean_slice"]["disabled_timeframes"])


if __name__ == "__main__":
    unittest.main()
