from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fast_edge import (  # noqa: E402
    build_fast_edge_report,
    create_plan,
    evaluate_plan,
    record_paper_segment,
    run_execution_probe,
    select_shortlist,
    summarize_execution_rows,
)


class FastEdgeFixture:
    def __init__(self, root: Path, *, reverse_oos: bool = False) -> None:
        self.dataset = root / "daily_fixture"
        self.dataset.mkdir(parents=True)
        universe = []
        for exchange in ("mexc", "gateio"):
            universe.append(
                {
                    "exchange": exchange,
                    "symbol": "AAA_USDT",
                    "base": "AAA",
                    "volume_24h_quote": 1_000_000.0,
                    "non_binance_baseline": True,
                }
            )
            universe.append(
                {
                    "exchange": exchange,
                    "symbol": "BINANCE_USDT",
                    "base": "BINANCE",
                    "volume_24h_quote": 2_000_000.0,
                    "non_binance_baseline": False,
                }
            )
        manifest = {
            "schema": "daily_collect_v1",
            "run_id": "fixture_200d",
            "duration_sec": 1.0,
            "universe": universe,
        }
        (self.dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for exchange in ("mexc", "gateio"):
            funding_dir = self.dataset / exchange / "funding"
            kline_dir = self.dataset / exchange / "klines"
            funding_dir.mkdir(parents=True)
            kline_dir.mkdir(parents=True)
            rows = []
            klines = []
            for day in range(1, 201):
                gate_rate = -0.001 if reverse_oos and day > 140 else 0.001
                rate = gate_rate if exchange == "gateio" else 0.0
                rows.append({"ts": day * 86400 + 3600, "funding_rate": rate})
                klines.append({"ts": day * 86400, "close": 100.0})
            (funding_dir / "AAA_USDT.json").write_text(
                json.dumps({"exchange": exchange, "symbol": "AAA_USDT", "rows": rows}),
                encoding="utf-8",
            )
            (kline_dir / "AAA_USDT.json").write_text(
                json.dumps({"exchange": exchange, "symbol": "AAA_USDT", "rows": klines}),
                encoding="utf-8",
            )


class FastEdgeTests(unittest.TestCase):
    def test_shortlist_requires_non_binance_on_both_venues(self) -> None:
        manifest = {
            "universe": [
                {"exchange": "mexc", "symbol": "AAA_USDT", "base": "AAA", "volume_24h_quote": 10, "non_binance_baseline": True},
                {"exchange": "gateio", "symbol": "AAA_USDT", "base": "AAA", "volume_24h_quote": 20, "non_binance_baseline": True},
                {"exchange": "mexc", "symbol": "BBB_USDT", "base": "BBB", "volume_24h_quote": 30, "non_binance_baseline": True},
                {"exchange": "gateio", "symbol": "BBB_USDT", "base": "BBB", "volume_24h_quote": 40, "non_binance_baseline": False},
            ]
        }
        self.assertEqual([row["symbol"] for row in select_shortlist(manifest, 20)], ["AAA_USDT"])

    def test_plan_evaluate_is_deterministic_and_passes_strong_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = FastEdgeFixture(root)
            plan_path = root / "plan.json"
            eval_path_a = root / "eval_a.json"
            eval_path_b = root / "eval_b.json"
            plan = create_plan(fixture.dataset, output_path=plan_path, max_runtime_sec=60)

            first = evaluate_plan(plan_path, output_path=eval_path_a)
            second = evaluate_plan(plan_path, output_path=eval_path_b)

            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first["plan_hash"], plan["plan_hash"])
            self.assertEqual(first["summary"]["historical_pass_count"], 1)
            candidate = next(row for row in first["candidates"] if row["route"] == "cross_venue_perp_perp")
            self.assertEqual(candidate["status"], "HISTORICAL_PASS_PENDING_EXECUTION")
            self.assertEqual(candidate["oos"]["aligned_days"], 60)
            self.assertEqual(candidate["oos"]["settlement_count"], 60)
            self.assertEqual(candidate["walk_forward"]["positive_folds"], 5)
            self.assertGreaterEqual(candidate["stress"]["net_pnl_quote"], 0.0)
            self.assertLessEqual(candidate["break_even_holding_days"], 14.0)

    def test_direction_is_frozen_on_train_and_bad_oos_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = FastEdgeFixture(root, reverse_oos=True)
            plan_path = root / "plan.json"
            evaluation_path = root / "evaluation.json"
            create_plan(fixture.dataset, output_path=plan_path, max_runtime_sec=60)

            result = evaluate_plan(plan_path, output_path=evaluation_path)

            candidate = next(row for row in result["candidates"] if row["route"] == "cross_venue_perp_perp")
            self.assertEqual(candidate["direction"], "long_mexc_perp_short_gate_perp")
            self.assertEqual(candidate["status"], "REJECT")
            self.assertLess(candidate["oos"]["net_pnl_quote"], 0.0)
            self.assertIn("oos_net_expectancy_not_positive", candidate["rejection_reasons"])

    def test_reuses_frozen_rejected_fallbacks_without_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = FastEdgeFixture(root, reverse_oos=True)
            backtests = root / "backtests"
            backtests.mkdir()
            for filename, decision in (
                ("listing_event_replay_planonly_fixture.json", "LISTING_REJECT"),
                ("slow_liquidity_fixed_v1_replay_planonly_fixture.json", "SLOW_REJECT"),
            ):
                (backtests / filename).write_text(
                    json.dumps(
                        {
                            "decision": decision,
                            "strategy_accepted": False,
                            "research_only": True,
                            "grid_search": False,
                            "summary": {"total_net_pnl_quote": -1.0, "profit_factor": 0.5},
                            "research_acceptance": {"reasons": ["net_expectancy_not_positive"]},
                        }
                    ),
                    encoding="utf-8",
                )
            plan_path = root / "plan.json"
            evaluation_path = root / "evaluation.json"
            plan = create_plan(fixture.dataset, output_path=plan_path, max_runtime_sec=60)

            result = evaluate_plan(plan_path, output_path=evaluation_path)

            self.assertEqual(len(plan["fixed_branch_evidence"]), 2)
            self.assertEqual(result["summary"]["fallback_rejected_count"], 2)
            self.assertEqual(result["summary"]["decision"], "NO_FAST_EDGE_FOUND")
            self.assertTrue(
                all(
                    row["evaluation_mode"] == "reuse_frozen_fixed_test_no_rerun_no_retuning"
                    for row in result["fallback_branches"]
                )
            )

    def test_probe_cache_report_and_paper_state_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = FastEdgeFixture(root)
            plan_path = root / "plan.json"
            evaluation_path = root / "evaluation.json"
            probe_path = root / "probe.jsonl"
            create_plan(fixture.dataset, output_path=plan_path, max_runtime_sec=60)
            evaluation = evaluate_plan(plan_path, output_path=evaluation_path)

            def fake_fetcher(symbol: str, route: str, _mexc: dict, _gate: dict) -> dict:
                return {
                    "symbol": symbol,
                    "route": route,
                    "dual_leg_valid": True,
                    "max_leg_impact_bps": 2.0,
                    "max_leg_spread_bps": 3.0,
                    "min_leg_capacity_usd": 1_000.0,
                    "errors": [],
                }

            probe = run_execution_probe(
                plan_path,
                evaluation_path,
                output_path=probe_path,
                duration_sec=1,
                interval_sec=1.0,
                max_runtime_sec=1,
                snapshot_fetcher=fake_fetcher,
            )
            cached = run_execution_probe(
                plan_path,
                evaluation_path,
                output_path=probe_path,
                duration_sec=1,
                interval_sec=1.0,
                max_runtime_sec=1,
                snapshot_fetcher=fake_fetcher,
            )
            self.assertTrue(probe["final"])
            self.assertTrue(cached["cache_hit"])

            insufficient = build_fast_edge_report(plan_path, evaluation_path, output_path=root / "insufficient.json")
            self.assertEqual(insufficient["verdict"], "INSUFFICIENT_DATA")

            candidate = next(
                row for row in evaluation["candidates"]
                if row["status"] == "HISTORICAL_PASS_PENDING_EXECUTION"
            )
            accepted_probe_path = root / "accepted_probe.json"
            accepted_probe_path.write_text(
                json.dumps(
                    {
                        "final": True,
                        "config_hash": "fixture",
                        "summary": {
                            "candidates": [
                                {
                                    "symbol": candidate["symbol"],
                                    "route": candidate["route"],
                                    "snapshots": 180,
                                    "valid_dual_leg_snapshots": 180,
                                    "dual_leg_coverage": 1.0,
                                    "p95_impact_bps_at_500": 5.0,
                                    "p95_spread_bps": 4.0,
                                    "p05_capacity_at_10bps_usd": 1_000.0,
                                    "errors": 0,
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            report_path = root / "report.json"
            report = build_fast_edge_report(
                plan_path,
                evaluation_path,
                execution_probe_path=accepted_probe_path,
                output_path=report_path,
            )
            self.assertEqual(report["verdict"], "ACCEPT_FOR_PAPER")

            state_path = root / "paper_state.json"
            for index in range(1, 16):
                observation_path = root / f"observation_{index}.json"
                observation_path.write_text(
                    json.dumps(
                        {
                            "settlement_id": f"s{index}",
                            "symbol": candidate["symbol"],
                            "route": candidate["route"],
                            "net_pnl_quote": 1.0,
                            "execution_divergence_bps": 1.0,
                            "window_duration_sec": 1200.0,
                        }
                    ),
                    encoding="utf-8",
                )
                state = record_paper_segment(report_path, observation_path, state_path=state_path)
                if index == 3:
                    self.assertEqual(state["status"], "PAPER_READY")
            self.assertEqual(state["status"], "LIVE_REVIEW_ELIGIBLE")
            self.assertFalse(state["live_orders_allowed"])

    def test_execution_summary_uses_p95_and_p05(self) -> None:
        rows = []
        for value in range(1, 101):
            rows.append(
                {
                    "symbol": "AAA_USDT",
                    "route": "cross_venue_perp_perp",
                    "dual_leg_valid": True,
                    "max_leg_impact_bps": float(value),
                    "max_leg_spread_bps": float(value) / 2,
                    "min_leg_capacity_usd": float(value * 10),
                    "errors": [],
                }
            )
        summary = summarize_execution_rows(rows)["candidates"][0]
        self.assertAlmostEqual(summary["p95_impact_bps_at_500"], 95.05, places=2)
        self.assertAlmostEqual(summary["p05_capacity_at_10bps_usd"], 59.5, places=1)

    def test_probe_metadata_network_failure_is_resumable_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = FastEdgeFixture(root)
            plan_path = root / "plan.json"
            evaluation_path = root / "evaluation.json"
            output_path = root / "probe.jsonl"
            create_plan(fixture.dataset, output_path=plan_path, max_runtime_sec=60)
            evaluate_plan(plan_path, output_path=evaluation_path)

            with patch("fast_edge.fetch_contract_sizes", side_effect=OSError("network down")):
                result = run_execution_probe(
                    plan_path,
                    evaluation_path,
                    output_path=output_path,
                    duration_sec=1,
                    interval_sec=1.0,
                    max_runtime_sec=1,
                )

            self.assertFalse(result["final"])
            self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
            manifest = json.loads(output_path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["resume_supported"])
            self.assertIn("network down", manifest["failure"])


if __name__ == "__main__":
    unittest.main()
