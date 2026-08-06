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

from funding_pressure_reversal import (  # noqa: E402
    Bar,
    HYPOTHESIS_ID,
    MarketSeries,
    PLAN_SCHEMA,
    PortfolioSignal,
    build_venue_signals,
    canonical_plan_hash,
    create_plan_from_sealed_source,
    decide_verdict,
    evaluate_plan,
    funding_pressure_score,
    infer_funding_interval_sec,
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
    symbol_count: int = 2,
    include_open_bar: bool = False,
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
    symbols = tuple(f"{chr(64 + index) * 3}_USDT" for index in range(1, symbol_count + 1))
    for exchange, interval_sec in (("mexc", 14_400), ("gateio", 28_800)):
        for symbol_index, symbol in enumerate(symbols, start=1):
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
                direction = 1.0 if symbol_index <= 2 else (-1.0 if symbol_index >= symbol_count - 1 else 0.0)
                open_price = 100.0 + symbol_index + direction * 0.1 * offset
                bars.append(
                    {
                        "ts": ts,
                        "open": open_price,
                        "high": open_price * 1.01,
                        "low": open_price * 0.99,
                        "close": open_price + direction * 0.08,
                        "volume_quote": 10_000_000.0,
                    }
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

            funding_rows = []
            start_ts = int(first_day.timestamp())
            end_ts = int((first_day + timedelta(days=199)).timestamp())
            for ts in range(start_ts, end_ts, interval_sec):
                funding_rows.append({"ts": ts, "funding_rate": 0.0001 * symbol_index})
            _write_json(
                dataset / exchange / "funding" / f"{symbol}.json",
                {"exchange": exchange, "symbol": symbol, "rows": funding_rows},
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
            "excluded_synthetic_proxy_bases": ["NVDAX"],
        },
    }
    source["plan_hash"] = _canonical_hash(source)
    source_path = root / "source_plan.json"
    _write_json(source_path, source)
    return source_path, source


class FundingPressureReversalPlanTests(unittest.TestCase):
    def test_planonly_wrapper_is_bounded_and_checks_active_gate(self) -> None:
        wrapper = Path(__file__).resolve().parents[2] / "tools" / "build_fast_first_v4_planonly.ps1"
        self.assertTrue(wrapper.exists())
        content = wrapper.read_text(encoding="utf-8")
        self.assertIn("[int]$MaxRuntimeSec = 1200", content)
        self.assertIn("check_active_run_gate.ps1", content)
        self.assertIn("funding_pressure_reversal.py", content)
        self.assertIn("-MaxRuntimeSec", content)
        self.assertIn("C:\\Program Files\\Python313\\python.exe", content)
        self.assertIn("current-run.json", content)
        self.assertIn("archived-gates", content)
        self.assertIn("PLAN_FROZEN_OOS_NOT_EVALUATED", content)
        self.assertIn("[switch]$RegisterExisting", content)
        self.assertIn("REGISTER_EXISTING_PLANONLY", content)
        self.assertIn("fast_first_v4_planonly_manifest_v1", content)
        self.assertIn("manifests", content)
        self.assertNotIn("Start-Process", content)

    def test_interval_inference_uses_median_positive_timestamp_delta(self) -> None:
        rows = [
            {"ts": 43_200},
            {"ts": 0},
            {"ts": 14_400},
            {"ts": 28_800},
            {"ts": 28_800},
        ]

        self.assertEqual(infer_funding_interval_sec(rows), 14_400)
        with self.assertRaisesRegex(ValueError, "at least two"):
            infer_funding_interval_sec([{"ts": 1}])

    def test_planonly_freezes_contract_without_reading_oos_performance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, source = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("# Frozen Fast-First v4 goal\n", encoding="utf-8")

            plan = create_plan_from_sealed_source(
                source_path,
                goal_path=goal_path,
                created_at_utc="2026-07-14T08:00:00+00:00",
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
            self.assertFalse(plan["data_access_audit"]["oos_returns_read"])
            self.assertFalse(plan["data_access_audit"]["signal_scores_computed"])
            self.assertFalse(plan["data_access_audit"]["pnl_computed"])
            self.assertEqual(plan["sealed_input"]["input_merkle_sha256"], source["sealed_input"]["input_merkle_sha256"])
            self.assertEqual(plan["source_plan"]["plan_hash"], source["plan_hash"])
            self.assertEqual(plan["signal"]["funding_normalization_target_sec"], 28_800)
            self.assertEqual(plan["signal"]["funding_score_lookback_complete_utc_days"], 3)
            self.assertEqual(plan["signal"]["entry"], "next daily open after closed signal day")
            self.assertEqual(plan["signal"]["exit"], "third fully closed daily bar close after entry")
            self.assertEqual(plan["signal"]["rebalance_anchor_date"], "2026-02-24")
            self.assertEqual(plan["signal"]["rebalance_every_days"], 3)
            self.assertEqual(plan["validation"]["chronological_split"]["train"]["calendar_days"], 139)
            self.assertEqual(plan["validation"]["chronological_split"]["oos"]["calendar_days"], 60)
            self.assertEqual(len(plan["validation"]["walk_forward"]["folds"]), 5)
            self.assertEqual(plan["runtime_policy"]["plan_max_runtime_sec"], 1_200)
            self.assertEqual(plan["runtime_policy"]["daytime_max_runtime_sec"], 10_800)
            self.assertEqual(plan["runtime_policy"]["night_window_max_runtime_sec"], 28_800)
            self.assertEqual(
                plan["runtime_policy"]["night_window"],
                {
                    "timezone": "Europe/Volgograd",
                    "start_local": "23:00",
                    "end_local": "07:00",
                    "must_finish_by_end_local": True,
                },
            )
            self.assertTrue(plan["runtime_policy"]["defer_runs_over_three_hours_to_night_window"])
            self.assertEqual(plan["next_allowed_action"], "implement_hash_bound_no_grid_evaluator")
            self.assertEqual(plan["plan_hash"], canonical_plan_hash(plan))

            availability = plan["data_availability"]
            self.assertEqual(availability["markets_total"], 4)
            self.assertEqual(availability["by_venue"]["mexc"]["markets"], 2)
            self.assertEqual(availability["by_venue"]["gateio"]["markets"], 2)
            self.assertEqual(availability["by_venue"]["mexc"]["inferred_funding_intervals_sec"], [14_400])
            self.assertEqual(availability["by_venue"]["gateio"]["inferred_funding_intervals_sec"], [28_800])
            self.assertEqual(
                plan["data_access_audit"]["market_fields_read"],
                ["exchange", "symbol", "base", "bar.ts", "funding.ts"],
            )

    def test_plan_hash_and_frozen_contract_reject_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            plan = create_plan_from_sealed_source(source_path, goal_path=goal_path)

            plan["signal"]["hold_days"] = 4
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
            tampered = root / "dataset" / "mexc" / "funding" / "AAA_USDT.json"
            tampered.write_text('{"rows":[]}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "sealed input hash mismatch"):
                create_plan_from_sealed_source(source_path, goal_path=goal_path)

    def test_write_plan_emits_valid_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")
            output_path = root / "plans" / "plan.json"

            result = write_plan_from_sealed_source(
                source_path,
                output_path,
                goal_path=goal_path,
                max_runtime_sec=1_200,
            )

            self.assertEqual(result["output_path"], str(output_path.resolve()))
            self.assertEqual(len(result["output_sha256"]), 64)
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            validate_plan(persisted)
            self.assertEqual(persisted["plan_hash"], result["plan_hash"])

    def test_write_plan_rejects_runtime_above_fast_first_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path, _ = _source_plan(root)
            goal_path = root / "goal.md"
            goal_path.write_text("goal", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "MaxRuntimeSec"):
                write_plan_from_sealed_source(
                    source_path,
                    root / "plan.json",
                    goal_path=goal_path,
                    max_runtime_sec=1_201,
                )


class FundingPressureReversalEvaluatorTests(unittest.TestCase):
    @staticmethod
    def _plan(root: Path, *, symbol_count: int = 8, include_open_bar: bool = False) -> dict:
        source_path, _ = _source_plan(
            root,
            symbol_count=symbol_count,
            include_open_bar=include_open_bar,
        )
        goal_path = root / "goal.md"
        goal_path.write_text("# Frozen evaluator fixture\n", encoding="utf-8")
        return create_plan_from_sealed_source(
            source_path,
            goal_path=goal_path,
            created_at_utc="2026-07-14T09:00:00+00:00",
        )

    @staticmethod
    def _day(value: str) -> int:
        return int(datetime.fromisoformat(f"{value}T00:00:00+00:00").timestamp() // 86_400)

    def test_funding_score_normalizes_interval_and_ignores_future_settlements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))
            signal_day = self._day("2026-05-14")
            signal_end = (signal_day + 1) * 86_400
            market = MarketSeries(exchange="mexc", symbol="AAA_USDT", base="AAA")
            market.funding = [
                (ts, 0.0001)
                for ts in range(signal_end - 3 * 86_400, signal_end, 14_400)
            ]

            original = funding_pressure_score(plan, market, signal_day)
            market.funding.extend(
                [
                    (signal_end + 14_400, 9.0),
                    (signal_end + 28_800, 9.0),
                ]
            )
            mutated = funding_pressure_score(plan, market, signal_day)

            self.assertIsNotNone(original)
            self.assertAlmostEqual(original, 0.0002, places=12)
            self.assertEqual(original, mutated)

    def test_market_loader_excludes_bar_after_frozen_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir), include_open_bar=True)

            markets, quality = load_markets(plan)

            cutoff = self._day("2026-07-12")
            self.assertTrue(markets)
            self.assertTrue(all(max(market.bars) <= cutoff for market in markets))
            self.assertEqual(
                quality["markets"]["mexc:AAA_USDT"]["excluded_incomplete_bars"],
                1,
            )

    def test_main_signal_is_deterministic_four_leg_and_three_day_nonoverlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))
            markets, _ = load_markets(plan)

            signals, diagnostics = build_venue_signals(
                plan,
                markets,
                "mexc",
                score_type="main",
            )

            anchor = self._day("2026-02-24")
            selected = next(signal for signal in signals if signal.signal_day == anchor)
            self.assertEqual(selected.long_symbols, ("AAA_USDT", "BBB_USDT"))
            self.assertEqual(selected.short_symbols, ("HHH_USDT", "GGG_USDT"))
            self.assertEqual(selected.entry_day, anchor + 1)
            self.assertEqual(selected.exit_day, anchor + 3)
            self.assertGreaterEqual(diagnostics["signal_count"], 1)
            for previous, current in zip(signals, signals[1:]):
                self.assertEqual(current.signal_day - previous.signal_day, 3)
                self.assertGreater(current.entry_day, previous.exit_day)

    def test_simulation_uses_next_open_third_close_exact_costs_and_stress_funding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))
            entry_day = self._day("2026-05-15")
            exit_day = entry_day + 2
            specs = {
                "AAA_USDT": (100.0, 110.0, 0.002),
                "BBB_USDT": (100.0, 105.0, -0.001),
                "HHH_USDT": (100.0, 90.0, 0.002),
                "GGG_USDT": (100.0, 95.0, -0.001),
            }
            markets = {}
            for symbol, (entry, exit_price, rate) in specs.items():
                market = MarketSeries(exchange="mexc", symbol=symbol, base=symbol[:3])
                market.bars[entry_day] = Bar(
                    day=entry_day,
                    ts=entry_day * 86_400,
                    open=entry,
                    high=entry,
                    close=entry,
                    quote_volume=10_000_000.0,
                )
                market.bars[exit_day] = Bar(
                    day=exit_day,
                    ts=exit_day * 86_400,
                    open=exit_price,
                    high=exit_price,
                    close=exit_price,
                    quote_volume=10_000_000.0,
                )
                market.funding = [(entry_day * 86_400 + 3_600, rate)]
                markets[symbol] = market
            signal = PortfolioSignal(
                exchange="mexc",
                score_type="main",
                signal_day=entry_day - 1,
                entry_day=entry_day,
                exit_day=exit_day,
                long_symbols=("AAA_USDT", "BBB_USDT"),
                long_bases=("AAA", "BBB"),
                short_symbols=("HHH_USDT", "GGG_USDT"),
                short_bases=("HHH", "GGG"),
                long_scores=(-0.002, -0.001),
                short_scores=(0.002, 0.001),
                eligible_markets=8,
                selected_quote_volumes=(10_000_000.0,) * 4,
            )

            event = simulate_signal(plan, signal, markets)

            self.assertAlmostEqual(event.price_pnl_quote, 150.0, places=8)
            self.assertAlmostEqual(event.normal_cost_quote, 6.5, places=8)
            self.assertAlmostEqual(event.stress_cost_quote, 8.4, places=8)
            self.assertAlmostEqual(event.funding_pnl_quote, 0.0, places=8)
            self.assertAlmostEqual(event.stress_funding_pnl_quote, -1.5, places=8)
            self.assertAlmostEqual(event.price_only_net_pnl_quote, 143.5, places=8)
            self.assertAlmostEqual(event.stress_price_only_net_pnl_quote, 141.6, places=8)
            self.assertAlmostEqual(event.stress_total_net_pnl_quote, 140.1, places=8)
            self.assertAlmostEqual(event.capacity_proxy_quote, 1_000.0, places=8)

    def test_verdict_orders_sufficiency_before_price_only_economics_and_funding_cannot_rescue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = self._plan(Path(temp_dir))
            by_venue = {
                venue: {
                    "event_count": 10,
                    "price_only_net_expectancy_quote": 5.0,
                    "price_only_net_pnl_quote": 50.0,
                }
                for venue in ("mexc", "gateio")
            }
            oos = {
                "event_count": 20,
                "unique_rebalance_dates": 10,
                "price_only_net_pnl_quote": 100.0,
                "price_only_net_expectancy_quote": 5.0,
                "price_only_profit_factor": 1.5,
                "price_only_positive_event_rate": 0.65,
                "stress_price_only_net_pnl_quote": 10.0,
                "total_net_pnl_quote": 200.0,
                "max_drawdown_fraction_of_peak_allocated_collateral": 0.05,
                "max_single_event_positive_pnl_share": 0.20,
                "max_single_base_positive_pnl_share": 0.20,
                "max_single_venue_positive_pnl_share": 0.50,
                "break_even_holding_days": 2.0,
                "minimum_capacity_proxy_quote": 500.0,
                "by_venue": by_venue,
            }
            metrics = {
                "data": {"input_hashes_match": True, "oos_closed_calendar_days": 60},
                "main": {
                    "oos": oos,
                    "walk_forward": {
                        "positive_combined_folds": 4,
                        "positive_folds_by_venue": {"mexc": 3, "gateio": 3},
                    },
                },
                "robustness": {"oos": {"price_only_net_pnl_quote": 10.0}},
            }

            insufficient = json.loads(json.dumps(metrics))
            insufficient["main"]["oos"]["event_count"] = 19
            self.assertEqual(decide_verdict(plan, insufficient)["verdict"], "INSUFFICIENT_DATA")

            rejected = json.loads(json.dumps(metrics))
            rejected["main"]["oos"]["price_only_net_pnl_quote"] = -1.0
            rejected["main"]["oos"]["price_only_net_expectancy_quote"] = -0.05
            rejected["main"]["oos"]["total_net_pnl_quote"] = 500.0
            decision = decide_verdict(plan, rejected)
            self.assertEqual(decision["verdict"], "REJECT")
            self.assertIn("price_only_oos_net_not_positive", decision["reasons"])

            self.assertEqual(
                decide_verdict(plan, metrics)["verdict"],
                "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
            )

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

    def test_full_synthetic_fixture_is_deterministic_and_no_grid(self) -> None:
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
            self.assertTrue(first["signals"]["robustness"])
            self.assertEqual(len(first["metrics"]["main"]["walk_forward"]["folds"]), 5)
            self.assertIn(first["verdict"], {"REJECT", "INSUFFICIENT_DATA", "ACCEPT_FOR_SHORT_EXECUTION_PROBE"})

    def test_readiness_is_hash_bound_and_explicitly_keeps_oos_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = self._plan(root)
            plan_path = root / "plan.json"
            _write_json(plan_path, plan)

            with self.assertRaisesRegex(ValueError, "Expected plan hash"):
                validate_evaluator_readiness(plan_path, expected_plan_hash="0" * 64)

            readiness = validate_evaluator_readiness(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
            )
            self.assertEqual(readiness["status"], "FAST_FIRST_V4_EVALUATOR_READY_OOS_NOT_RUN")
            self.assertTrue(readiness["input_hashes_match"])
            self.assertFalse(readiness["evaluation_started"])
            self.assertFalse(readiness["oos_metrics_read"])
            self.assertFalse(readiness["grid_search"])
            self.assertEqual(readiness["parameter_combinations"], 1)

    def test_project_cli_exposes_hash_bound_v4_validate_and_evaluate_commands(self) -> None:
        parser = build_project_parser()

        validate_args = parser.parse_args(
            [
                "fast-edge-v4-validate",
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "a" * 64,
            ]
        )
        evaluate_args = parser.parse_args(
            [
                "fast-edge-v4-evaluate",
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "a" * 64,
                "--output",
                "evaluation.json",
            ]
        )

        self.assertEqual(validate_args.command, "fast-edge-v4-validate")
        self.assertEqual(evaluate_args.command, "fast-edge-v4-evaluate")


if __name__ == "__main__":
    unittest.main()
