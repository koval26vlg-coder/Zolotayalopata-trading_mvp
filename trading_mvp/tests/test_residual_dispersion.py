from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from costs import RouteLeg, base_api_cost_profile  # noqa: E402
from residual_dispersion import (  # noqa: E402
    Bar,
    MarketSeries,
    PLAN_SCHEMA,
    Signal,
    build_venue_signals,
    canonical_plan_hash,
    decide_verdict,
    evaluate_plan,
    main,
    simulate_signal,
    validate_plan,
    _load_markets,
)


def _base_plan(root: Path) -> dict:
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"finished_at_utc": "2026-02-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    cost_profile = base_api_cost_profile()
    venue_cycle_costs = {
        exchange: {
            "normal": cost_profile.cycle_cost(
                [RouteLeg(exchange, "perp"), RouteLeg(exchange, "perp")]
            ),
            "stress": cost_profile.cycle_cost(
                [RouteLeg(exchange, "perp"), RouteLeg(exchange, "perp")],
                stress=True,
            ),
        }
        for exchange in ("mexc", "gateio")
    }
    plan = {
        "schema": PLAN_SCHEMA,
        "mode": "PLAN_ONLY",
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "hypothesis": {"id": "venue_local_perp_residual_dispersion_reversion_v1"},
        "sealed_input": {
            "dataset_root": str(root),
            "source_file_count": 1,
            "source_files": [
                {
                    "relative_path": "manifest.json",
                    "sha256": manifest_sha,
                    "size_bytes": manifest.stat().st_size,
                }
            ],
            "input_merkle_sha256": "unused-by-plan-validation",
            "universe": [],
        },
        "signal": {
            "venues": ["mexc", "gateio"],
            "beta_lookback_days": 3,
            "dispersion_history_days": 3,
            "min_dispersion_ratio_to_trailing_median": 1.5,
            "min_residual_tail_gap_bps": 150.0,
            "entry": "next_daily_open",
            "exit": "same_daily_close",
            "hold_days": 1,
            "parameter_selection_on_train": False,
            "parameter_selection_on_oos": False,
        },
        "eligibility": {
            "minimum_prior_history_days": 5,
            "liquidity_lookback_days": 3,
            "minimum_trailing_median_quote_volume": 1000.0,
            "minimum_eligible_markets_per_venue": 3,
            "minimum_finite_beta_observations": 3,
            "non_binance_baseline_required": True,
        },
        "economics": {
            "notional_quote_per_leg": 500.0,
            "cost_profile": cost_profile.as_dict(),
            "same_venue_two_perp_leg_cycle_costs": venue_cycle_costs,
            "funding_treatment": {
                "signal_use": "forbidden",
                "max_absolute_funding_share_of_positive_oos_pnl": 0.25,
                "price_only_net_after_cost_must_be_positive": True,
            },
            "capacity_proxy": {
                "minimum_quote_per_leg": 500.0,
            },
        },
        "validation": {
            "chronological_split": {
                "train": {"start": "2026-01-01", "end": "2026-01-20", "calendar_days": 20},
                "oos": {"start": "2026-01-21", "end": "2026-01-30", "calendar_days": 10},
            },
            "walk_forward": {
                "folds": [
                    {"fold": index, "test_start": f"2026-01-{15 + index:02d}", "test_end": f"2026-01-{15 + index:02d}"}
                    for index in range(1, 6)
                ]
            },
            "acceptance_gates": {
                "minimum_oos_calendar_days": 10,
                "minimum_oos_pair_events_total": 4,
                "minimum_oos_pair_events_per_venue": 2,
                "oos_net_expectancy_quote_gt": 0.0,
                "oos_profit_factor_gte": 1.2,
                "oos_positive_event_rate_gte": 0.6,
                "minimum_positive_walk_forward_folds": 4,
                "stress_net_pnl_quote_gte": 0.0,
                "both_venues_oos_net_expectancy_positive": True,
                "price_only_oos_net_after_cost_positive": True,
                "maximum_single_event_positive_pnl_share": 0.25,
                "maximum_single_base_positive_pnl_share": 0.25,
                "maximum_single_venue_positive_pnl_share": 0.75,
                "maximum_break_even_holding_days": 1.0,
                "minimum_capacity_proxy_quote_per_leg": 500.0,
                "input_hashes_must_match": True,
            },
            "verdicts": ["ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA"],
            "acceptance_ceiling": "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        },
        "runtime_policy": {
            "evaluation_max_runtime_sec": 60,
            "network_probe_max_runtime_sec": 1200,
            "absolute_run_max_runtime_sec": 28800,
            "visible_terminal_required_for_evaluation_or_probe": True,
        },
        "prohibited": ["grid_search", "API_keys", "live_orders"],
    }
    plan["plan_hash"] = canonical_plan_hash(plan)
    return plan


def _flat_market(symbol: str, base: str, *, exchange: str = "mexc", days: int = 12) -> MarketSeries:
    bars = {
        day: Bar(
            day=day,
            ts=day * 86_400,
            open=100.0,
            close=100.0,
            quote_volume=10_000_000.0,
        )
        for day in range(1, days + 1)
    }
    return MarketSeries(exchange=exchange, symbol=symbol, base=base, bars=bars, funding=[])


def _date_day(value: str) -> int:
    return int(datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc).timestamp() // 86_400)


def _write_evaluation_fixture(root: Path) -> tuple[Path, Path, Path]:
    plan = _base_plan(root)
    start_day = _date_day("2026-01-01")
    bases = ("AAA", "BBB", "CCC")
    shocks = {17, 20, 23, 26}
    universe = []
    source_paths = [root / "manifest.json"]
    for exchange in ("mexc", "gateio"):
        for base in bases:
            symbol = f"{base}_USDT"
            universe.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "base": base,
                    "volume_24h_quote_at_collect": 10_000_000.0,
                }
            )
            kline_path = root / exchange / "klines" / f"{symbol}.json"
            funding_path = root / exchange / "funding" / f"{symbol}.json"
            kline_path.parent.mkdir(parents=True, exist_ok=True)
            funding_path.parent.mkdir(parents=True, exist_ok=True)
            rows = []
            previous_close = 100.0
            for offset in range(30):
                day = start_day + offset
                open_price = previous_close
                close = 100.0
                if offset in shocks:
                    close = 90.0 if base == "AAA" else (110.0 if base == "CCC" else 100.0)
                rows.append(
                    {
                        "ts": day * 86_400,
                        "open": open_price,
                        "high": max(open_price, close),
                        "low": min(open_price, close),
                        "close": close,
                        "volume_quote": 10_000_000.0,
                    }
                )
                previous_close = close
            kline_path.write_text(
                json.dumps({"exchange": exchange, "symbol": symbol, "rows": rows}),
                encoding="utf-8",
            )
            funding_path.write_text(
                json.dumps({"exchange": exchange, "symbol": symbol, "rows": []}),
                encoding="utf-8",
            )
            source_paths.extend((kline_path, funding_path))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "fixture",
                "finished_at_utc": "2026-02-01T00:00:00+00:00",
                "universe": universe,
            }
        ),
        encoding="utf-8",
    )
    file_rows = []
    aggregate = hashlib.sha256()
    for path in sorted(source_paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_rows.append({"relative_path": relative, "sha256": digest, "size_bytes": path.stat().st_size})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    plan["sealed_input"].update(
        {
            "dataset_root": str(root),
            "source_file_count": len(file_rows),
            "source_files": file_rows,
            "input_merkle_sha256": aggregate.hexdigest(),
            "universe": universe,
        }
    )
    plan["plan_hash"] = canonical_plan_hash(plan)
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_path, root / "mexc" / "klines" / "AAA_USDT.json", root / "evaluation.json"


class ResidualDispersionModuleTests(unittest.TestCase):
    def test_evaluator_module_exists(self) -> None:
        self.assertEqual(PLAN_SCHEMA, "fast_first_residual_dispersion_plan_v1")

    def test_plan_hash_is_canonical_and_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))

            validate_plan(plan)
            expected = hashlib.sha256(
                json.dumps(
                    {key: value for key, value in plan.items() if key != "plan_hash"},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(canonical_plan_hash(plan), expected)

            plan["signal"]["min_residual_tail_gap_bps"] = 149.0
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_plan(plan)

    def test_plan_rejects_funding_signal_or_execution_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            plan["economics"]["funding_treatment"]["signal_use"] = "rank"
            plan["plan_hash"] = canonical_plan_hash(plan)
            with self.assertRaisesRegex(ValueError, "Funding cannot be used as a signal"):
                validate_plan(plan)

            plan = _base_plan(Path(temp_dir))
            plan["execution_probe_allowed"] = True
            plan["plan_hash"] = canonical_plan_hash(plan)
            with self.assertRaisesRegex(ValueError, "execution probe"):
                validate_plan(plan)

    def test_plan_cost_profile_must_match_unified_cost_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            validate_plan(plan)

            plan["economics"]["cost_profile"]["schedules"]["mexc"]["perp_taker_bps"] = 1.0
            plan["plan_hash"] = canonical_plan_hash(plan)

            with self.assertRaisesRegex(ValueError, "CostProfile"):
                validate_plan(plan)

    def test_incomplete_last_daily_bar_is_excluded_using_sealed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = _base_plan(root)
            (root / "manifest.json").write_text(
                json.dumps({"finished_at_utc": "2026-01-10T06:00:00+00:00"}),
                encoding="utf-8",
            )
            kline_dir = root / "mexc" / "klines"
            funding_dir = root / "mexc" / "funding"
            kline_dir.mkdir(parents=True)
            funding_dir.mkdir(parents=True)
            complete_day = _date_day("2026-01-09")
            incomplete_day = _date_day("2026-01-10")
            rows = [
                {
                    "ts": day * 86_400,
                    "open": 100.0,
                    "close": 101.0,
                    "volume_quote": 10_000_000.0,
                }
                for day in (complete_day, incomplete_day)
            ]
            (kline_dir / "AAA_USDT.json").write_text(
                json.dumps({"rows": rows}), encoding="utf-8"
            )
            (funding_dir / "AAA_USDT.json").write_text(
                json.dumps({"rows": []}), encoding="utf-8"
            )
            plan["sealed_input"]["universe"] = [
                {"exchange": "mexc", "symbol": "AAA_USDT", "base": "AAA"}
            ]

            markets, quality = _load_markets(plan)

            self.assertEqual(set(markets[0].bars), {complete_day})
            self.assertEqual(
                quality["markets"]["mexc:AAA_USDT"]["excluded_incomplete_bars"],
                1,
            )

    def test_signal_uses_only_information_available_at_signal_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            plan["signal"]["dispersion_history_days"] = 2
            plan["eligibility"]["minimum_prior_history_days"] = 3
            plan["eligibility"]["liquidity_lookback_days"] = 2
            plan["eligibility"]["minimum_finite_beta_observations"] = 2
            plan["signal"]["beta_lookback_days"] = 2
            plan["plan_hash"] = canonical_plan_hash(plan)

            markets = [
                _flat_market("AAA_USDT", "AAA"),
                _flat_market("BBB_USDT", "BBB"),
                _flat_market("CCC_USDT", "CCC"),
            ]
            markets[0].bars[8] = Bar(8, 8 * 86_400, 100.0, 90.0, 10_000_000.0)
            markets[1].bars[8] = Bar(8, 8 * 86_400, 100.0, 100.0, 10_000_000.0)
            markets[2].bars[8] = Bar(8, 8 * 86_400, 100.0, 110.0, 10_000_000.0)
            markets[0].bars[9] = Bar(9, 9 * 86_400, 90.0, 100.0, 10_000_000.0)
            markets[2].bars[9] = Bar(9, 9 * 86_400, 110.0, 100.0, 10_000_000.0)

            original, _ = build_venue_signals(plan, markets, "mexc")
            selected = next(signal for signal in original if signal.signal_day == 8)
            self.assertEqual((selected.long_symbol, selected.short_symbol), ("AAA_USDT", "CCC_USDT"))

            for market in markets:
                market.bars[11] = Bar(11, 11 * 86_400, 100.0, 1_000_000.0, 10_000_000.0)
                market.bars[12] = Bar(12, 12 * 86_400, 1_000_000.0, 0.01, 10_000_000.0)
            mutated, _ = build_venue_signals(plan, markets, "mexc")

            before_future = [signal for signal in original if signal.signal_day <= 9]
            after_future = [signal for signal in mutated if signal.signal_day <= 9]
            self.assertEqual(before_future, after_future)

    def test_execution_uses_next_open_and_full_four_order_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            long_market = _flat_market("AAA_USDT", "AAA")
            short_market = _flat_market("CCC_USDT", "CCC")
            long_market.bars[9] = Bar(9, 9 * 86_400, 90.0, 100.0, 10_000_000.0)
            short_market.bars[9] = Bar(9, 9 * 86_400, 110.0, 100.0, 20_000_000.0)
            signal = Signal(
                exchange="mexc",
                signal_day=8,
                entry_day=9,
                long_symbol="AAA_USDT",
                long_base="AAA",
                short_symbol="CCC_USDT",
                short_base="CCC",
                long_residual=-0.1,
                short_residual=0.1,
                residual_gap_bps=2000.0,
                dispersion=0.1,
                trailing_dispersion=0.01,
                eligible_markets=3,
                long_trailing_quote_volume=10_000_000.0,
                short_trailing_quote_volume=20_000_000.0,
            )

            event = simulate_signal(
                plan,
                signal,
                {"AAA_USDT": long_market, "CCC_USDT": short_market},
            )

            expected_price_pnl = 500.0 * ((100.0 / 90.0 - 1.0) - (100.0 / 110.0 - 1.0))
            self.assertAlmostEqual(event.price_pnl_quote, expected_price_pnl, places=8)
            self.assertAlmostEqual(event.normal_cost_quote, 500.0 * 65.0 / 10_000.0, places=8)
            self.assertAlmostEqual(event.stress_cost_quote, 500.0 * 84.0 / 10_000.0, places=8)
            self.assertAlmostEqual(event.normal_net_pnl_quote, expected_price_pnl - event.normal_cost_quote, places=8)
            self.assertEqual(event.capacity_proxy_quote, 1_000.0)

    def test_stress_keeps_adverse_funding_and_haircuts_favorable_funding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            long_market = _flat_market("AAA_USDT", "AAA")
            short_market = _flat_market("CCC_USDT", "CCC")
            long_market.funding = [(9 * 86_400 + 3600, 0.001)]
            short_market.funding = [(9 * 86_400 + 3600, -0.001)]
            signal = Signal(
                exchange="mexc",
                signal_day=8,
                entry_day=9,
                long_symbol="AAA_USDT",
                long_base="AAA",
                short_symbol="CCC_USDT",
                short_base="CCC",
                long_residual=-0.1,
                short_residual=0.1,
                residual_gap_bps=2000.0,
                dispersion=0.1,
                trailing_dispersion=0.01,
                eligible_markets=3,
                long_trailing_quote_volume=10_000_000.0,
                short_trailing_quote_volume=10_000_000.0,
            )

            adverse = simulate_signal(plan, signal, {"AAA_USDT": long_market, "CCC_USDT": short_market})
            self.assertAlmostEqual(adverse.funding_pnl_quote, -1.0)
            self.assertAlmostEqual(adverse.stress_funding_pnl_quote, -1.0)

            long_market.funding = [(9 * 86_400 + 3600, -0.001)]
            short_market.funding = [(9 * 86_400 + 3600, 0.001)]
            favorable = simulate_signal(plan, signal, {"AAA_USDT": long_market, "CCC_USDT": short_market})
            self.assertAlmostEqual(favorable.funding_pnl_quote, 1.0)
            self.assertAlmostEqual(favorable.stress_funding_pnl_quote, 0.5)

    def test_verdict_distinguishes_accept_reject_and_insufficient_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            passing = {
                "data": {"input_hashes_match": True, "oos_calendar_days": 10},
                "oos": {
                    "event_count": 4,
                    "net_expectancy_quote": 1.0,
                    "profit_factor": 1.5,
                    "positive_event_rate": 0.75,
                    "stress_net_pnl_quote": 1.0,
                    "price_only_net_pnl_quote": 1.0,
                    "max_single_event_positive_pnl_share": 0.20,
                    "max_single_base_positive_pnl_share": 0.20,
                    "max_single_venue_positive_pnl_share": 0.60,
                    "absolute_funding_share_of_positive_pnl": 0.10,
                    "break_even_holding_days": 0.5,
                    "minimum_capacity_proxy_quote": 600.0,
                    "by_venue": {
                        "mexc": {"event_count": 2, "net_expectancy_quote": 1.0},
                        "gateio": {"event_count": 2, "net_expectancy_quote": 1.0},
                    },
                },
                "walk_forward": {"positive_folds": 4},
            }

            accepted = decide_verdict(plan, passing)
            self.assertEqual(accepted["verdict"], "ACCEPT_FOR_SHORT_EXECUTION_PROBE")
            self.assertEqual(accepted["reasons"], [])

            insufficient = json.loads(json.dumps(passing))
            insufficient["oos"]["event_count"] = 3
            insufficient["oos"]["profit_factor"] = 0.1
            result = decide_verdict(plan, insufficient)
            self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
            self.assertIn("oos_pair_events_total_below_minimum", result["reasons"])

            rejected = json.loads(json.dumps(passing))
            rejected["oos"]["profit_factor"] = 1.0
            result = decide_verdict(plan, rejected)
            self.assertEqual(result["verdict"], "REJECT")
            self.assertIn("oos_profit_factor_below_minimum", result["reasons"])

    def test_verdict_rejects_funding_driven_or_single_venue_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            metrics = {
                "data": {"input_hashes_match": True, "oos_calendar_days": 10},
                "oos": {
                    "event_count": 4,
                    "net_expectancy_quote": 1.0,
                    "profit_factor": 2.0,
                    "positive_event_rate": 0.75,
                    "stress_net_pnl_quote": 1.0,
                    "price_only_net_pnl_quote": 1.0,
                    "max_single_event_positive_pnl_share": 0.20,
                    "max_single_base_positive_pnl_share": 0.20,
                    "max_single_venue_positive_pnl_share": 0.90,
                    "absolute_funding_share_of_positive_pnl": 0.50,
                    "break_even_holding_days": 0.5,
                    "minimum_capacity_proxy_quote": 600.0,
                    "by_venue": {
                        "mexc": {"event_count": 2, "net_expectancy_quote": 2.0},
                        "gateio": {"event_count": 2, "net_expectancy_quote": -0.1},
                    },
                },
                "walk_forward": {"positive_folds": 5},
            }

            result = decide_verdict(plan, metrics)

            self.assertEqual(result["verdict"], "REJECT")
            self.assertIn("funding_share_above_maximum", result["reasons"])
            self.assertIn("single_venue_positive_pnl_concentration_above_maximum", result["reasons"])
            self.assertIn("venue_oos_expectancy_not_positive:gateio", result["reasons"])

    def test_full_evaluation_is_deterministic_and_no_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, _, output_path = _write_evaluation_fixture(root)

            first = evaluate_plan(plan_path, output_path=output_path, progress=lambda _message: None)
            second = evaluate_plan(plan_path, output_path=root / "evaluation_repeat.json", progress=lambda _message: None)

            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first["metrics"], second["metrics"])
            self.assertIn(first["verdict"], ("ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA"))
            self.assertFalse(first["grid_search"])
            self.assertFalse(first["execution_probe_started"])
            self.assertEqual(first["plan_hash"], json.loads(plan_path.read_text(encoding="utf-8"))["plan_hash"])
            self.assertEqual(len(first["metrics"]["walk_forward"]["folds"]), 5)

    def test_changed_sealed_input_returns_insufficient_without_calculating_performance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, changed_path, output_path = _write_evaluation_fixture(root)
            changed_path.write_text(changed_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            result = evaluate_plan(plan_path, output_path=output_path, progress=lambda _message: None)

            self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
            self.assertIn("sealed_input_hash_mismatch_or_missing", result["rejection_reasons"])
            self.assertIsNone(result["metrics"].get("oos"))

    def test_cli_is_bound_to_expected_plan_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, _, output_path = _write_evaluation_fixture(root)
            plan_hash = json.loads(plan_path.read_text(encoding="utf-8"))["plan_hash"]

            with self.assertRaisesRegex(ValueError, "Expected plan hash"):
                main(
                    [
                        "evaluate",
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(output_path),
                        "--expected-plan-hash",
                        "0" * 64,
                    ]
                )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "evaluate",
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(output_path),
                        "--expected-plan-hash",
                        plan_hash,
                    ]
                )
            self.assertEqual(exit_code, 0)
            summary = json.loads(stdout.getvalue().splitlines()[-1])
            self.assertEqual(summary["plan_hash"], plan_hash)
            self.assertEqual(summary["artifact_path"], str(output_path.resolve()))


if __name__ == "__main__":
    unittest.main()
