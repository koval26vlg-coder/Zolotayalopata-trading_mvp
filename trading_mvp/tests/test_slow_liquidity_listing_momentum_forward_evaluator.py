from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import slow_liquidity_listing_momentum_forward_evaluator as ev  # noqa: E402


def synthetic_state(complete: int, in_progress: int = 1) -> dict:
    windows = []
    for index in range(complete):
        windows.append(
            {
                "exchange": "mexc" if index % 2 == 0 else "gateio",
                "base": f"B{index:03d}",
                "flags": [],
                "window_complete": True,
                "stats": {
                    "n_bars": 72,
                    "ret_24h": 0.10 + 0.001 * index,
                    "ret_72h": 0.20 + 0.002 * index,
                    "max_runup": 0.50,
                    "max_drawdown": -0.10,
                },
            }
        )
    for _ in range(in_progress):
        windows.append(
            {
                "exchange": "mexc",
                "base": "INPROG",
                "flags": ["window_in_progress"],
                "window_complete": False,
                "stats": {"n_bars": 6, "ret_72h": None},
            }
        )
    return {"windows": windows}


class ForwardEvaluatorPlanTests(unittest.TestCase):
    def test_plan_preregisters_thresholds_and_guards(self) -> None:
        plan = ev.build_plan("2026-08-16T23:50:00Z")
        pre = plan["preregistration"]
        self.assertEqual(pre["first_read_min_complete_windows"], 30)
        self.assertEqual(pre["terminal_min_complete_windows"], 100)
        self.assertEqual(
            pre["strategy_proxy_frozen"]["normal_cost_bps"], 120.0
        )
        self.assertEqual(plan["status"], "PREREGISTERED_AWAITING_SAMPLE")
        self.assertEqual(plan["acceptance_decision"] if "acceptance_decision" in plan else "NONE", "NONE")

    def test_checked_in_plan_matches_generator(self) -> None:
        if not ev.PLAN_PATH.is_file():
            self.skipTest("plan not yet frozen")
        checked_in = json.loads(ev.PLAN_PATH.read_text(encoding="utf-8"))
        rebuilt = ev.build_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, rebuilt)


class ForwardEvaluatorTests(unittest.TestCase):
    def test_peeking_guard_below_minimum(self) -> None:
        result = ev.evaluate_forward_state(synthetic_state(29))
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE_NO_METRICS")
        self.assertNotIn("metrics", result)
        self.assertEqual(result["complete_windows"], 29)

    def test_metrics_computed_at_minimum(self) -> None:
        result = ev.evaluate_forward_state(synthetic_state(30))
        self.assertEqual(result["status"], "EVALUATED_DESCRIPTIVE")
        self.assertFalse(result["sample_sufficient_for_terminal"])
        metrics = result["metrics"]
        self.assertEqual(metrics["ret_72h"]["count"], 30)
        # net after 120bps cost = ret72 - 0.012
        self.assertAlmostEqual(
            metrics["net_ret_72h_after_normal_cost"]["median"],
            round(metrics["ret_72h"]["median"] - 0.012, 6),
            places=6,
        )
        self.assertEqual(result["windows_by_venue"], {"gateio": 15, "mexc": 15})
        self.assertEqual(result["acceptance_decision"], "NONE")

    def test_in_progress_windows_never_counted(self) -> None:
        result = ev.evaluate_forward_state(synthetic_state(0, in_progress=5))
        self.assertEqual(result["complete_windows"], 0)
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE_NO_METRICS")

    def test_terminal_threshold_flag(self) -> None:
        result = ev.evaluate_forward_state(synthetic_state(100))
        self.assertTrue(result["sample_sufficient_for_terminal"])

    def test_real_state_if_present(self) -> None:
        if not ev.FORWARD_STATE_PATH.is_file():
            self.skipTest("forward state not present")
        state = json.loads(ev.FORWARD_STATE_PATH.read_text(encoding="utf-8"))
        result = ev.evaluate_forward_state(state)
        self.assertIn(result["status"], (
            "INSUFFICIENT_SAMPLE_NO_METRICS",
            "EVALUATED_DESCRIPTIVE",
        ))
        self.assertEqual(
            result["complete_windows"],
            state.get("complete_window_count", 0),
        )

    def test_evaluate_recomputes_when_same_window_count_has_new_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            evaluation_path = root / "evaluation.json"
            ticks_root = root / "ticks"
            tick_dir = ticks_root / "tick_a"
            tick_dir.mkdir(parents=True)
            (tick_dir / "manifest.json").write_text(
                json.dumps({"tick_id": "tick_a", "status": "COMPLETED"}),
                encoding="utf-8",
            )

            def write_state(ret_72h: float) -> None:
                state = synthetic_state(30, in_progress=0)
                state["ticks"] = [{"tick_id": "tick_a", "status": "COMPLETED"}]
                for window in state["windows"]:
                    window["stats"]["ret_72h"] = ret_72h
                state["state_hash"] = ev._canonical_hash_without(state, "state_hash")
                state_path.write_text(json.dumps(state), encoding="utf-8")

            with mock.patch.object(ev, "FORWARD_STATE_PATH", state_path), mock.patch.object(
                ev, "EVALUATION_PATH", evaluation_path
            ), mock.patch.object(ev, "FORWARD_TICKS_ROOT", ticks_root):
                write_state(0.2)
                self.assertEqual(ev.main(["--evaluate"]), 0)
                first = json.loads(evaluation_path.read_text(encoding="utf-8"))

                tampered = dict(first)
                tampered["metrics"] = dict(first["metrics"])
                tampered["metrics"]["ret_72h"] = dict(first["metrics"]["ret_72h"])
                tampered["metrics"]["ret_72h"]["median"] = 999.0
                tampered["evaluation_hash"] = ev._evaluation_hash(tampered)
                evaluation_path.write_text(
                    json.dumps(tampered), encoding="utf-8"
                )
                self.assertEqual(ev.main(["--evaluate"]), 0)
                repaired = json.loads(evaluation_path.read_text(encoding="utf-8"))
                self.assertEqual(repaired, first)

                write_state(0.9)
                self.assertEqual(ev.main(["--evaluate"]), 0)
                second = json.loads(evaluation_path.read_text(encoding="utf-8"))

            self.assertEqual(first["complete_windows"], second["complete_windows"])
            self.assertEqual(first["metrics"]["ret_72h"]["median"], 0.2)
            self.assertEqual(second["metrics"]["ret_72h"]["median"], 0.9)
            self.assertNotEqual(
                first["input_binding"]["state_hash"],
                second["input_binding"]["state_hash"],
            )
            self.assertNotEqual(
                first["input_binding"]["input_manifest_hash"],
                second["input_binding"]["input_manifest_hash"],
            )
            self.assertNotEqual(first["evaluation_hash"], second["evaluation_hash"])


if __name__ == "__main__":
    unittest.main()
