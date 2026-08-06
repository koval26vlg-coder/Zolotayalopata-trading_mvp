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

from wick_rejection_reversal import (  # noqa: E402
    HYPOTHESIS_ID,
    PLAN_SCHEMA,
    build_venue_signals,
    canonical_plan_hash,
    create_plan_from_sealed_source,
    decide_verdict,
    evaluate_plan,
    load_markets,
    simulate_signal,
    validate_evaluator_readiness,
    validate_plan,
    write_plan_from_sealed_source,
)
from cli import build_parser as build_project_parser  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _canonical_hash(payload: dict) -> str:
    content = {key: value for key, value in payload.items() if key != "plan_hash"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _source_plan(
    root: Path,
    *,
    include_open_bar: bool = False,
    symbol_count: int = 4,
    wick_setup: bool = False,
) -> tuple[Path, dict]:
    dataset = root / "dataset"
    _write_json(
        dataset / "manifest.json",
        {
            "schema": "daily_collect_v1",
            "run_id": "fixture_daily_history",
            "final": True,
            "error_count": 0,
        },
    )
    universe: list[dict] = []
    first_day = datetime(2025, 12, 26, tzinfo=timezone.utc)
    for exchange in ("mexc", "gateio"):
        for symbol_index in range(1, symbol_count + 1):
            symbol = f"{chr(64 + symbol_index) * 3}_USDT"
            universe.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "base": symbol.removesuffix("_USDT"),
                    "volume_24h_quote_at_collect": 8_000_000.0,
                }
            )
            bars = []
            for offset in range(199):
                ts = int((first_day + timedelta(days=offset)).timestamp())
                open_price = 100.0 + symbol_index
                if wick_setup and symbol_index <= symbol_count // 2:
                    row = {
                        "ts": ts,
                        "open": 100.0,
                        "high": 105.0,
                        "low": 80.0,
                        "close": 103.0,
                        "volume_quote": 10_000_000.0,
                    }
                elif wick_setup:
                    row = {
                        "ts": ts,
                        "open": 100.0,
                        "high": 120.0,
                        "low": 95.0,
                        "close": 97.0,
                        "volume_quote": 10_000_000.0,
                    }
                else:
                    row = {
                        "ts": ts,
                        "open": open_price,
                        "high": open_price * 1.05,
                        "low": open_price * 0.95,
                        "close": open_price,
                        "volume_quote": 10_000_000.0,
                    }
                bars.append(
                    row
                )
            if include_open_bar:
                bars.append(
                    {
                        "ts": int((first_day + timedelta(days=199)).timestamp()),
                        "open": 100.0,
                        "high": 999.0,
                        "low": 1.0,
                        "close": 999.0,
                        "volume_quote": 999_000_000.0,
                    }
                )
            _write_json(
                dataset / exchange / "klines" / f"{symbol}.json",
                {"exchange": exchange, "symbol": symbol, "interval": "1d", "rows": bars},
            )

    source_files = []
    aggregate = hashlib.sha256()
    for path in sorted(dataset.rglob("*.json"), key=lambda value: value.relative_to(dataset).as_posix()):
        relative = path.relative_to(dataset).as_posix()
        digest = _sha256(path)
        source_files.append(
            {
                "relative_path": relative,
                "sha256": digest,
                "size_bytes": path.stat().st_size,
            }
        )
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")

    source = {
        "schema": "fixture_sealed_plan_v1",
        "mode": "PlanOnly",
        "sealed_input": {
            "dataset_root": str(dataset),
            "collector_run_id": "fixture_daily_history",
            "last_closed_daily_bar_date": "2026-07-12",
            "open_or_partial_bars_after_date_must_be_excluded": True,
            "source_file_count": len(source_files),
            "source_files": source_files,
            "input_merkle_sha256": aggregate.hexdigest(),
            "input_hash_method": "sha256(sorted(relative_path + NUL + file_sha256 + LF))",
            "universe": universe,
        },
    }
    source["plan_hash"] = _canonical_hash(source)
    source_path = root / "source_plan.json"
    _write_json(source_path, source)
    return source_path, source


class WickRejectionReversalPlanTests(unittest.TestCase):
    def test_planonly_freezes_new_independent_hypothesis_without_oos_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, source = _source_plan(root, include_open_bar=True)
            goal_path = root / "goal.md"
            goal_path.write_text("# Fast-First v5 goal\n", encoding="utf-8")

            plan = create_plan_from_sealed_source(
                source_path,
                goal_path=goal_path,
                created_at_utc="2026-07-14T10:00:00+00:00",
            )

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
            self.assertEqual(plan["source_plan"]["plan_hash"], source["plan_hash"])
            self.assertEqual(plan["signal"]["hold_days"], 1)
            self.assertEqual(plan["signal"]["rebalance_every_days"], 1)
            self.assertEqual(
                plan["signal"]["long_condition"],
                "lower_wick_pct_of_range >= 0.60 and close_position_in_range >= 0.70",
            )
            self.assertEqual(
                plan["signal"]["short_condition"],
                "upper_wick_pct_of_range >= 0.60 and close_position_in_range <= 0.30",
            )
            self.assertTrue(plan["hypothesis"]["not_funding_carry"])
            self.assertTrue(plan["hypothesis"]["not_cross_venue"])
            self.assertTrue(plan["hypothesis"]["not_hft_or_orderbook"])
            self.assertTrue(plan["hypothesis"]["not_listing_event"])
            self.assertFalse(plan["data_access_audit"]["ohlc_values_read"])
            self.assertFalse(plan["data_access_audit"]["oos_returns_read"])
            self.assertFalse(plan["data_access_audit"]["signal_scores_computed"])
            self.assertFalse(plan["data_access_audit"]["pnl_computed"])
            self.assertFalse(plan["data_access_audit"]["funding_rates_read_for_signal"])
            self.assertEqual(plan["data_availability"]["markets_total"], 8)
            self.assertEqual(plan["data_availability"]["by_venue"]["mexc"]["markets"], 4)
            self.assertEqual(plan["data_availability"]["by_venue"]["gateio"]["markets"], 4)
            self.assertEqual(plan["validation"]["chronological_split"]["oos"]["calendar_days"], 60)
            self.assertEqual(len(plan["validation"]["walk_forward"]["folds"]), 5)
            self.assertEqual(plan["runtime_policy"]["evaluation_max_runtime_sec"], 1_800)
            self.assertTrue(plan["runtime_policy"]["explicit_confirmation_not_required_for_short_owned_no_grid_evaluation"])
            self.assertEqual(plan["next_allowed_action"], "implement_hash_bound_no_grid_evaluator")
            self.assertEqual(plan["plan_hash"], canonical_plan_hash(plan))

    def test_plan_hash_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan = create_plan_from_sealed_source(source_path, goal_path=goal_path)

            plan["signal"]["hold_days"] = 3
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

            result = write_plan_from_sealed_source(
                source_path,
                output,
                goal_path=goal_path,
                max_runtime_sec=1_200,
            )

            self.assertEqual(result["output_path"], str(output.resolve()))
            self.assertEqual(len(result["output_sha256"]), 64)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            validate_plan(persisted)
            self.assertEqual(persisted["plan_hash"], result["plan_hash"])

            with self.assertRaisesRegex(ValueError, "MaxRuntimeSec"):
                write_plan_from_sealed_source(
                    source_path,
                    root / "bad.json",
                    goal_path=goal_path,
                    max_runtime_sec=1_201,
                )

    def test_wrapper_is_bounded_visible_and_checks_active_gate(self) -> None:
        wrapper = Path(__file__).resolve().parents[2] / "tools" / "build_fast_first_v5_planonly.ps1"
        self.assertTrue(wrapper.exists())
        content = wrapper.read_text(encoding="utf-8")
        self.assertIn("[int]$MaxRuntimeSec = 1200", content)
        self.assertIn("check_active_run_gate.ps1", content)
        self.assertIn("wick_rejection_reversal.py", content)
        self.assertIn("fast-edge-v5", content)
        self.assertIn("PLAN_FROZEN_OOS_NOT_EVALUATED", content)
        self.assertIn("fast_first_v5_planonly_manifest_v1", content)
        self.assertNotIn("Start-Process", content)

    def test_project_cli_exposes_v5_validate_and_evaluate_commands(self) -> None:
        parser = build_project_parser()
        validate_args = parser.parse_args(
            [
                "fast-edge-v5-validate",
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "a" * 64,
            ]
        )
        evaluate_args = parser.parse_args(
            [
                "fast-edge-v5-evaluate",
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "a" * 64,
                "--output",
                "evaluation.json",
            ]
        )
        self.assertEqual(validate_args.command, "fast-edge-v5-validate")
        self.assertEqual(evaluate_args.command, "fast-edge-v5-evaluate")


class WickRejectionReversalEvaluatorTests(unittest.TestCase):
    @staticmethod
    def _plan(root: Path, *, symbol_count: int = 8, wick_setup: bool = True) -> dict:
        source_path, _ = _source_plan(root, symbol_count=symbol_count, wick_setup=wick_setup)
        goal_path = root / "goal.md"
        goal_path.write_text("# v5 evaluator fixture\n", encoding="utf-8")
        return create_plan_from_sealed_source(
            source_path,
            goal_path=goal_path,
            created_at_utc="2026-07-14T11:00:00+00:00",
        )

    @staticmethod
    def _day(value: str) -> int:
        return int(datetime.fromisoformat(f"{value}T00:00:00+00:00").timestamp() // 86_400)

    def test_signal_selection_is_deterministic_and_uses_closed_wick_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            markets, quality = load_markets(plan)

            signals, diagnostics = build_venue_signals(plan, markets, "mexc")

            self.assertEqual(quality["market_count"], 16)
            self.assertGreaterEqual(diagnostics["signal_count"], 1)
            anchor = self._day("2026-02-24")
            selected = next(signal for signal in signals if signal.signal_day == anchor)
            self.assertEqual(selected.long_symbols, ("AAA_USDT", "BBB_USDT"))
            self.assertEqual(selected.short_symbols, ("EEE_USDT", "FFF_USDT"))
            self.assertEqual(selected.entry_day, anchor + 1)
            self.assertEqual(selected.exit_day, anchor + 1)
            for previous, current in zip(signals, signals[1:]):
                self.assertGreater(current.entry_day, previous.exit_day)

    def test_simulation_uses_next_open_next_close_exact_costs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            markets, _ = load_markets(plan)
            signals, _ = build_venue_signals(plan, markets, "mexc")
            signal = next(signal for signal in signals if signal.signal_day == self._day("2026-02-24"))
            venue_markets = {market.symbol: market for market in markets if market.exchange == "mexc"}

            event = simulate_signal(plan, signal, venue_markets)

            self.assertAlmostEqual(event.gross_price_pnl_quote, 60.0, places=8)
            self.assertAlmostEqual(event.normal_cost_quote, 6.5, places=8)
            self.assertAlmostEqual(event.stress_cost_quote, 8.4, places=8)
            self.assertAlmostEqual(event.net_pnl_quote, 53.5, places=8)
            self.assertAlmostEqual(event.stress_net_pnl_quote, 51.6, places=8)
            self.assertFalse(event.live_orders if hasattr(event, "live_orders") else False)

    def test_readiness_is_hash_bound_and_does_not_read_oos_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            plan_path = root / "plan.json"
            _write_json(plan_path, plan)

            with self.assertRaisesRegex(ValueError, "Expected plan hash"):
                validate_evaluator_readiness(plan_path, expected_plan_hash="0" * 64)

            readiness = validate_evaluator_readiness(plan_path, expected_plan_hash=plan["plan_hash"])
            self.assertEqual(readiness["status"], "FAST_FIRST_V5_EVALUATOR_READY_OOS_NOT_RUN")
            self.assertTrue(readiness["input_hashes_match"])
            self.assertFalse(readiness["evaluation_started"])
            self.assertFalse(readiness["oos_metrics_read"])
            self.assertFalse(readiness["grid_search"])
            self.assertEqual(readiness["parameter_combinations"], 1)

    def test_hash_mismatch_fails_closed_before_market_or_oos_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            plan["sealed_input"]["input_merkle_sha256"] = "0" * 64
            plan["sealed_input_verification"]["input_merkle_sha256"] = "0" * 64
            plan["plan_hash"] = canonical_plan_hash(plan)
            plan_path = root / "plan.json"
            output_path = root / "evaluation.json"
            _write_json(plan_path, plan)

            report = evaluate_plan(plan_path, output_path=output_path, progress=None)

            self.assertEqual(report["verdict"], "INSUFFICIENT_DATA")
            self.assertIsNone(report["metrics"]["main"]["oos"])
            self.assertFalse(report["market_data_loaded"])
            self.assertFalse(report["grid_search"])
            self.assertFalse(report["execution_probe_started"])
            self.assertFalse(report["paper_forward_started"])
            self.assertFalse(report["live_orders"])

    def test_full_fixture_is_deterministic_no_grid_and_has_single_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            plan_path = root / "plan.json"
            _write_json(plan_path, plan)

            first = evaluate_plan(plan_path, output_path=root / "evaluation.json", progress=None)
            second = evaluate_plan(plan_path, output_path=root / "repeat.json", progress=None)

            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first["parameter_combinations_evaluated"], 1)
            self.assertFalse(first["grid_search"])
            self.assertTrue(first["signals"]["main"])
            self.assertTrue(first["events"]["main"])
            self.assertEqual(len(first["metrics"]["main"]["walk_forward"]["folds"]), 5)
            self.assertIn(first["verdict"], {"REJECT", "INSUFFICIENT_DATA", "ACCEPT_FOR_SHORT_EXECUTION_PROBE"})

    def test_verdict_orders_sufficiency_before_economics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))
            by_venue = {
                venue: {"event_count": 15, "net_pnl_quote": 10.0, "net_expectancy_quote": 1.0}
                for venue in ("mexc", "gateio")
            }
            oos = {
                "event_count": 30,
                "unique_signal_dates": 20,
                "net_pnl_quote": 100.0,
                "net_expectancy_quote": 3.3,
                "profit_factor": 1.5,
                "positive_event_rate": 0.6,
                "stress_net_pnl_quote": 1.0,
                "max_single_event_positive_pnl_share": 0.2,
                "max_single_base_positive_pnl_share": 0.2,
                "minimum_capacity_proxy_quote": 500.0,
                "by_venue": by_venue,
            }
            metrics = {
                "data": {"input_hashes_match": True, "oos_closed_calendar_days": 60},
                "main": {
                    "oos": oos,
                    "walk_forward": {"positive_combined_folds": 4},
                },
            }

            insufficient = json.loads(json.dumps(metrics))
            insufficient["main"]["oos"]["event_count"] = 29
            self.assertEqual(decide_verdict(plan, insufficient)["verdict"], "INSUFFICIENT_DATA")

            rejected = json.loads(json.dumps(metrics))
            rejected["main"]["oos"]["net_pnl_quote"] = -1.0
            decision = decide_verdict(plan, rejected)
            self.assertEqual(decision["verdict"], "REJECT")
            self.assertIn("oos_net_not_positive", decision["reasons"])

            self.assertEqual(decide_verdict(plan, metrics)["verdict"], "ACCEPT_FOR_SHORT_EXECUTION_PROBE")


if __name__ == "__main__":
    unittest.main()
