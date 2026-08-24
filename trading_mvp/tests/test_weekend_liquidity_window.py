from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weekend_liquidity_window import (  # noqa: E402
    HYPOTHESIS_ID,
    PLAN_SCHEMA,
    build_venue_signals,
    canonical_plan_hash,
    create_plan_from_sealed_source,
    evaluate_plan,
    load_markets,
    simulate_signal,
    validate_evaluator_readiness,
    validate_plan,
    write_plan_from_sealed_source,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _canonical_hash(payload: dict) -> str:
    content = {key: value for key, value in payload.items() if key != "plan_hash"}
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _source_plan(root: Path, *, symbol_count: int = 4) -> tuple[Path, dict]:
    dataset = root / "dataset"
    _write_json(dataset / "manifest.json", {"schema": "daily_collect_v1", "final": True})
    universe: list[dict] = []
    first_day = datetime(2025, 12, 26, tzinfo=timezone.utc)
    for exchange in ("mexc", "gateio"):
        for symbol_index in range(1, symbol_count + 1):
            symbol = f"{chr(64 + symbol_index) * 3}_USDT"
            universe.append({"exchange": exchange, "symbol": symbol, "base": symbol.removesuffix("_USDT")})
            rows = [
                {
                    "ts": int((first_day + timedelta(days=offset)).timestamp()),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume_quote": 10_000_000.0,
                }
                for offset in range(199)
            ]
            _write_json(dataset / exchange / "klines" / f"{symbol}.json", {"rows": rows})

    source_files = []
    aggregate = hashlib.sha256()
    for path in sorted(dataset.rglob("*.json"), key=lambda value: value.relative_to(dataset).as_posix()):
        relative = path.relative_to(dataset).as_posix()
        digest = _sha256(path)
        source_files.append({"relative_path": relative, "sha256": digest, "size_bytes": path.stat().st_size})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")

    source = {
        "schema": "fixture_sealed_plan_v1",
        "mode": "PlanOnly",
        "sealed_input": {
            "dataset_root": str(dataset),
            "last_closed_daily_bar_date": "2026-07-12",
            "source_file_count": len(source_files),
            "source_files": source_files,
            "input_merkle_sha256": aggregate.hexdigest(),
            "universe": universe,
        },
    }
    source["plan_hash"] = _canonical_hash(source)
    source_path = root / "source_plan.json"
    _write_json(source_path, source)
    return source_path, source


class WeekendLiquidityWindowPlanTests(unittest.TestCase):
    def test_planonly_freezes_final_independent_calendar_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, source = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("# goal\n", encoding="utf-8")

            plan = create_plan_from_sealed_source(source_path, goal_path=goal_path, created_at_utc="2026-07-14T11:00:00+00:00")

            validate_plan(plan)
            self.assertEqual(plan["schema"], PLAN_SCHEMA)
            self.assertEqual(plan["hypothesis"]["id"], HYPOTHESIS_ID)
            self.assertEqual(plan["mode"], "PlanOnly")
            self.assertFalse(plan["evaluation_allowed"])
            self.assertFalse(plan["strategy_accepted"])
            self.assertFalse(plan["execution_probe_allowed"])
            self.assertFalse(plan["paper_forward_allowed"])
            self.assertFalse(plan["live_orders"])
            self.assertFalse(plan["api_keys"])
            self.assertFalse(plan["leverage_or_margin"])
            self.assertEqual(plan["oos_metrics"], {})
            self.assertEqual(plan["observed_performance"], {})
            self.assertEqual(plan["sealed_input"]["input_merkle_sha256"], source["sealed_input"]["input_merkle_sha256"])
            self.assertTrue(plan["hypothesis"]["not_funding_carry"])
            self.assertTrue(plan["hypothesis"]["not_wick_rejection_branch"])
            self.assertTrue(plan["hypothesis"]["not_momentum_or_breakout_branch"])
            self.assertFalse(plan["data_access_audit"]["ohlc_values_read"])
            self.assertFalse(plan["data_access_audit"]["volume_values_read_for_signal"])
            self.assertFalse(plan["data_access_audit"]["oos_returns_read"])
            self.assertEqual(plan["signal"]["hold_days"], 2)
            self.assertEqual(plan["signal"]["rebalance_every_days"], 7)
            self.assertEqual(plan["validation"]["chronological_split"]["oos"]["calendar_days"], 60)
            self.assertEqual(plan["plan_hash"], canonical_plan_hash(plan))

    def test_plan_hash_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan = create_plan_from_sealed_source(source_path, goal_path=goal_path)

            plan["signal"]["hold_days"] = 1
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_plan(plan)

            plan["plan_hash"] = canonical_plan_hash(plan)
            with self.assertRaisesRegex(ValueError, "hold_days"):
                validate_plan(plan)

    def test_source_file_hash_mismatch_fails_before_plan_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            tampered = root / "dataset" / "mexc" / "klines" / "AAA_USDT.json"
            tampered.write_text('{"rows":[]}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Sealed input hash mismatch"):
                create_plan_from_sealed_source(source_path, goal_path=goal_path)

    def test_write_plan_emits_valid_artifact_and_rejects_runtime_above_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            output = root / "plans" / "plan.json"

            result = write_plan_from_sealed_source(source_path, output, goal_path=goal_path, max_runtime_sec=1_200)

            self.assertEqual(result["output_path"], str(output.resolve()))
            persisted = json.loads(output.read_text(encoding="utf-8"))
            validate_plan(persisted)
            self.assertEqual(persisted["plan_hash"], result["plan_hash"])
            self.assertGreaterEqual(result["candidate_weekend_entry_days"], 1)

            with self.assertRaisesRegex(ValueError, "MaxRuntimeSec"):
                write_plan_from_sealed_source(source_path, root / "bad.json", goal_path=goal_path, max_runtime_sec=1_201)

    def test_evaluator_readiness_is_hash_bound_and_does_not_read_oos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root, symbol_count=8)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan_from_sealed_source(source_path, plan_path, goal_path=goal_path)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

            readiness = validate_evaluator_readiness(plan_path, expected_plan_hash=plan["plan_hash"])

            self.assertEqual(readiness["status"], "FAST_FIRST_V6_EVALUATOR_READY_OOS_NOT_RUN")
            self.assertTrue(readiness["input_hashes_match"])
            self.assertFalse(readiness["evaluation_started"])
            self.assertFalse(readiness["oos_metrics_read"])
            self.assertFalse(readiness["grid_search"])
            self.assertFalse(readiness["execution_probe_started"])

            with self.assertRaisesRegex(ValueError, "Expected plan hash"):
                validate_evaluator_readiness(plan_path, expected_plan_hash="0" * 64)

    def test_weekend_signal_selection_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root, symbol_count=8)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan_from_sealed_source(source_path, plan_path, goal_path=goal_path)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            markets, _ = load_markets(plan)

            signals, diagnostics = build_venue_signals(plan, markets, "mexc")

            self.assertGreaterEqual(diagnostics["signal_count"], 1)
            self.assertGreaterEqual(len(signals), 1)
            first = signals[0]
            self.assertEqual(first.exchange, "mexc")
            self.assertEqual(first.symbols, ("AAA_USDT", "BBB_USDT", "CCC_USDT", "DDD_USDT"))
            self.assertEqual(datetime.fromtimestamp(first.entry_day * 86_400, tz=timezone.utc).weekday(), 5)
            self.assertEqual(first.exit_day - first.entry_day, 2)

    def test_simulation_accounts_for_four_leg_costs_on_flat_prices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root, symbol_count=8)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan_from_sealed_source(source_path, plan_path, goal_path=goal_path)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            markets, _ = load_markets(plan)
            signals, _ = build_venue_signals(plan, markets, "mexc")
            markets_by_symbol = {market.symbol: market for market in markets if market.exchange == "mexc"}

            event = simulate_signal(plan, signals[0], markets_by_symbol)

            self.assertEqual(event.gross_price_pnl_quote, 0.0)
            self.assertGreater(event.normal_cost_quote, 0.0)
            self.assertGreater(event.stress_cost_quote, event.normal_cost_quote)
            self.assertAlmostEqual(event.net_pnl_quote, -event.normal_cost_quote)
            self.assertAlmostEqual(event.stress_net_pnl_quote, -event.stress_cost_quote)
            self.assertEqual(len(event.leg_contributions_quote), 4)

    def test_no_grid_evaluation_is_deterministic_and_rejects_flat_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root, symbol_count=8)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan_from_sealed_source(source_path, plan_path, goal_path=goal_path)
            output_1 = root / "evaluation_1.json"
            output_2 = root / "evaluation_2.json"

            first = evaluate_plan(plan_path, output_path=output_1, progress=None)
            second = evaluate_plan(plan_path, output_path=output_2, progress=None)

            self.assertEqual(first["schema"], "fast_first_weekend_liquidity_window_evaluation_v1")
            self.assertEqual(first["verdict"], "REJECT")
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first["parameter_combinations_evaluated"], 1)
            self.assertFalse(first["grid_search"])
            self.assertFalse(first["execution_probe_started"])
            self.assertFalse(first["paper_forward_started"])
            self.assertFalse(first["live_orders"])
            self.assertLess(first["metrics"]["main"]["oos"]["net_pnl_quote"], 0.0)

    def test_wrapper_is_bounded_visible_and_checks_active_gate(self) -> None:
        wrapper = Path(__file__).resolve().parents[2] / "tools" / "build_fast_first_v6_planonly.ps1"
        self.assertTrue(wrapper.exists())
        content = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(wrapper)
        self.assertIn("[int]$MaxRuntimeSec = 1200", content)
        self.assertIn("check_active_run_gate.ps1", content)
        self.assertIn("weekend_liquidity_window.py", content)
        self.assertIn("fast-edge-v6", content)
        self.assertIn("PLAN_FROZEN_OOS_NOT_EVALUATED", content)
        self.assertIn("fast_first_v6_planonly_manifest_v1", content)
        self.assertNotIn("Start-Process", content)


if __name__ == "__main__":
    unittest.main()
