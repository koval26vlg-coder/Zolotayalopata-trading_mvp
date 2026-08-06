from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, datetime, time as datetime_time, timezone
from io import StringIO
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from costs import RouteLeg, base_api_cost_profile  # noqa: E402
from lottery_max_evaluator import (  # noqa: E402
    PLAN_SCHEMA,
    Bar,
    MarketSeries,
    PortfolioSignal,
    _load_markets,
    build_venue_signals,
    canonical_plan_hash,
    decide_verdict,
    evaluate_plan,
    main,
    simulate_signal,
    validate_plan,
)


def _day(value: str) -> int:
    return int(
        datetime.combine(
            date.fromisoformat(value), datetime_time.min, tzinfo=timezone.utc
        ).timestamp()
        // 86_400
    )


def _iso(day: int) -> str:
    return datetime.fromtimestamp(day * 86_400, tz=timezone.utc).date().isoformat()


def _four_leg_costs(notional: float = 500.0) -> dict:
    profile = base_api_cost_profile()
    result = {}
    for exchange in ("mexc", "gateio"):
        venue = {}
        for label, stress in (("normal", False), ("stress", True)):
            pair = profile.cycle_cost(
                [RouteLeg(exchange, "perp"), RouteLeg(exchange, "perp")],
                stress=stress,
            )
            total_quote = 2.0 * notional * float(pair["total_bps"]) / 10_000.0
            gross = 4.0 * notional
            venue[label] = {
                "entry_orders": 4,
                "exit_orders": 4,
                "gross_notional_quote": gross,
                "legs_total": 4,
                "notional_quote_per_leg": notional,
                "orders_total": 8,
                "pair_count": 2,
                "pair_cycle": pair,
                "total_cost_bps_on_gross_notional": total_quote / gross * 10_000.0,
                "total_cost_bps_on_single_leg_notional": total_quote / notional * 10_000.0,
                "total_cost_quote": total_quote,
            }
        result[exchange] = venue
    return result


def _base_plan(root: Path) -> dict:
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "lottery-fixture",
                "finished_at_utc": "2026-07-13T06:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    aggregate = hashlib.sha256()
    aggregate.update(b"manifest.json\0")
    aggregate.update(manifest_sha.encode("ascii"))
    aggregate.update(b"\n")
    plan = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_parameters_no_grid": True,
        "strategy_accepted": False,
        "execution_probe_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "api_keys": False,
        "leverage_or_margin": False,
        "hypothesis": {"id": "venue_local_lottery_max_factor_v1"},
        "sealed_input": {
            "dataset_root": str(root),
            "last_closed_daily_bar_date": "2026-07-12",
            "open_or_partial_bars_after_date_must_be_excluded": True,
            "source_file_count": 1,
            "source_files": [
                {
                    "relative_path": "manifest.json",
                    "sha256": manifest_sha,
                    "size_bytes": manifest.stat().st_size,
                }
            ],
            "input_merkle_sha256": aggregate.hexdigest(),
            "universe": [],
        },
        "signal": {
            "venues": ["mexc", "gateio"],
            "timeframe": "1d",
            "return_definition": "log(close_d / close_d-1)",
            "main_score": "MAX20 = maximum daily close-to-close log return over the 20 completed days ending at t",
            "main_score_uses_cumulative_return_rank": False,
            "robustness_score": "same-date OLS residual of MAX20 on cumulative_return20 and log(trailing_30d_median_quote_volume), computed only from the eligible cross-section known at t",
            "selection": "long two lowest MAX20 and short two highest MAX20; deterministic normalized-base tie-break",
            "entry": "next closed-session daily open t+1",
            "exit": "close of fifth daily bar after entry",
            "hold_days": 5,
            "rebalance_anchor_date": "2026-02-24",
            "rebalance_every_days": 5,
            "overlapping_positions": False,
            "max_concurrent_portfolios_per_venue": 1,
            "parameter_selection_on_train": False,
            "parameter_selection_on_oos": False,
        },
        "eligibility": {
            "instrument": "USDT linear perpetual",
            "minimum_prior_closed_days": 60,
            "max_return_lookback_days": 20,
            "liquidity_lookback_days": 30,
            "candidate_pool_max_markets": 12,
            "minimum_candidate_pool_markets": 8,
            "minimum_selected_leg_trailing_median_quote_volume": 5_000_000.0,
            "minimum_selected_leg_capacity_quote": 500.0,
            "selected_leg_capacity_proxy": "0.0001 * trailing_30d_median_quote_volume",
            "selected_long_markets": 2,
            "selected_short_markets": 2,
            "require_contiguous_feature_history": True,
            "no_future_membership_or_volume_data": True,
            "non_binance_baseline_required": True,
            "venues": ["mexc", "gateio"],
            "excluded_synthetic_proxy_bases": ["CRCLX", "NVDAX", "QQQX"],
        },
        "economics": {
            "notional_quote_per_leg": 500.0,
            "gross_notional_quote_per_venue": 2_000.0,
            "legs_per_portfolio": 4,
            "cost_profile": base_api_cost_profile().as_dict(),
            "same_venue_four_perp_portfolio_cycle_costs": _four_leg_costs(),
            "funding_treatment": {
                "signal_use": "forbidden",
                "normal_pnl": "actual settlements on all four legs between entry and exit; long pays positive, short receives positive",
                "stress_pnl": "retain 100% adverse funding and only 50% favorable funding",
                "price_only_net_after_cost_must_be_positive": True,
                "max_absolute_funding_share_of_positive_oos_pnl": 0.25,
            },
        },
        "validation": {
            "chronological_split": {
                "method": "fixed_common_closed_calendar_139_60",
                "train": {
                    "start": "2025-12-26",
                    "end": "2026-05-13",
                    "calendar_days": 139,
                },
                "oos": {
                    "start": "2026-05-14",
                    "end": "2026-07-12",
                    "calendar_days": 60,
                },
            },
            "walk_forward": {
                "method": "anchored_expanding_no_refit",
                "initial_train": {
                    "start": "2025-12-26",
                    "end": "2026-04-03",
                    "calendar_days": 99,
                },
                "folds": [
                    {"fold": 1, "test_start": "2026-04-04", "test_end": "2026-04-23", "calendar_days": 20},
                    {"fold": 2, "test_start": "2026-04-24", "test_end": "2026-05-13", "calendar_days": 20},
                    {"fold": 3, "test_start": "2026-05-14", "test_end": "2026-06-02", "calendar_days": 20},
                    {"fold": 4, "test_start": "2026-06-03", "test_end": "2026-06-22", "calendar_days": 20},
                    {"fold": 5, "test_start": "2026-06-23", "test_end": "2026-07-12", "calendar_days": 20},
                ],
            },
            "acceptance_gates": {
                "input_hashes_must_match": True,
                "minimum_oos_closed_calendar_days": 60,
                "minimum_oos_portfolio_events_total": 20,
                "minimum_oos_portfolio_events_per_venue": 10,
                "minimum_unique_oos_rebalance_dates": 10,
                "oos_net_expectancy_quote_gt": 0.0,
                "oos_profit_factor_gte": 1.2,
                "oos_positive_portfolio_event_rate_gte": 0.6,
                "minimum_positive_combined_walk_forward_folds": 4,
                "minimum_positive_walk_forward_folds_per_venue": 3,
                "stress_net_pnl_quote_gte": 0.0,
                "both_venues_oos_net_expectancy_positive": True,
                "price_only_oos_net_after_cost_positive": True,
                "residualized_score_oos_net_after_cost_positive": True,
                "maximum_absolute_funding_share_of_positive_oos_pnl": 0.25,
                "maximum_oos_drawdown_fraction_of_peak_allocated_collateral": 0.1,
                "maximum_single_event_positive_pnl_share": 0.25,
                "maximum_single_base_positive_pnl_share": 0.25,
                "maximum_single_venue_positive_pnl_share": 0.75,
                "maximum_break_even_holding_days": 5.0,
                "minimum_capacity_proxy_quote_per_selected_leg": 500.0,
            },
            "verdicts": [
                "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
                "REJECT",
                "INSUFFICIENT_DATA",
            ],
            "acceptance_ceiling": "ACCEPT_FOR_SHORT_EXECUTION_PROBE",
        },
        "runtime_policy": {
            "evaluation_max_runtime_sec": 60,
            "network_probe_max_runtime_sec": 1_200,
            "absolute_run_max_runtime_sec": 10_800,
            "visible_terminal_required_for_evaluation_or_probe": True,
            "network_collection_required_for_plan": False,
        },
        "prohibited": ["grid search", "API keys", "live orders"],
    }
    plan["plan_hash"] = canonical_plan_hash(plan)
    return plan


def _market(
    symbol: str,
    score_rank: int,
    *,
    exchange: str = "mexc",
    first_day: int | None = None,
    days: int = 80,
) -> MarketSeries:
    start = first_day if first_day is not None else _day("2025-12-26")
    bars = {}
    close = 100.0
    for offset in range(days):
        day = start + offset
        daily_return = 0.0001 * score_rank
        if offset % 20 == 10:
            daily_return = 0.001 * score_rank
        open_price = close
        close *= math.exp(daily_return)
        bars[day] = Bar(
            day=day,
            ts=day * 86_400,
            open=open_price,
            close=close,
            quote_volume=10_000_000.0 + score_rank * 100_000.0,
        )
    return MarketSeries(
        exchange=exchange,
        symbol=symbol,
        base=symbol.removesuffix("_USDT"),
        bars=bars,
        funding=[],
    )


def _passing_metrics() -> dict:
    venue = {
        "event_count": 10,
        "net_pnl_quote": 50.0,
        "net_expectancy_quote": 5.0,
        "profit_factor": 2.0,
        "positive_event_rate": 0.7,
    }
    return {
        "data": {
            "input_hashes_match": True,
            "oos_closed_calendar_days": 60,
        },
        "main": {
            "oos": {
                "event_count": 20,
                "unique_rebalance_dates": 10,
                "net_pnl_quote": 100.0,
                "net_expectancy_quote": 5.0,
                "profit_factor": 2.0,
                "positive_event_rate": 0.7,
                "stress_net_pnl_quote": 10.0,
                "price_only_net_pnl_quote": 80.0,
                "absolute_funding_share_of_positive_pnl": 0.1,
                "max_drawdown_fraction_of_peak_allocated_collateral": 0.02,
                "max_single_event_positive_pnl_share": 0.2,
                "max_single_base_positive_pnl_share": 0.2,
                "max_single_venue_positive_pnl_share": 0.5,
                "break_even_holding_days": 2.0,
                "minimum_capacity_proxy_quote": 1_000.0,
                "by_venue": {"mexc": deepcopy(venue), "gateio": deepcopy(venue)},
            },
            "walk_forward": {
                "positive_combined_folds": 4,
                "positive_folds_by_venue": {"mexc": 3, "gateio": 3},
            },
        },
        "robustness": {"oos": {"net_pnl_quote": 1.0}},
    }


def _write_full_fixture(root: Path) -> tuple[Path, Path]:
    plan = _base_plan(root)
    first_day = _day("2025-12-26")
    last_day = _day("2026-07-12")
    universe = []
    source_paths = [root / "manifest.json"]
    for exchange in ("mexc", "gateio"):
        for rank, letter in enumerate("ABCDEFGH", start=1):
            symbol = f"{letter}_USDT"
            universe.append(
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "base": letter,
                    "volume_24h_quote_at_collect": 10_000_000.0 + rank * 100_000.0,
                }
            )
            kline = root / exchange / "klines" / f"{symbol}.json"
            funding = root / exchange / "funding" / f"{symbol}.json"
            kline.parent.mkdir(parents=True, exist_ok=True)
            funding.parent.mkdir(parents=True, exist_ok=True)
            close = 100.0
            rows = []
            for day in range(first_day, last_day + 1):
                open_price = close
                offset = day - first_day
                log_return = rank * 0.0001
                if offset % 20 == 10:
                    log_return = rank * 0.001
                close *= math.exp(log_return)
                rows.append(
                    {
                        "ts": day * 86_400,
                        "open": open_price,
                        "close": close,
                        "volume_quote": 10_000_000.0 + rank * 100_000.0,
                    }
                )
            kline.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            funding.write_text(json.dumps({"rows": []}), encoding="utf-8")
            source_paths.extend((kline, funding))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "lottery-full-fixture",
                "finished_at_utc": "2026-07-13T06:00:00+00:00",
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
        file_rows.append(
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
    plan["sealed_input"].update(
        {
            "source_file_count": len(file_rows),
            "source_files": file_rows,
            "input_merkle_sha256": aggregate.hexdigest(),
            "universe": universe,
        }
    )
    plan["plan_hash"] = canonical_plan_hash(plan)
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_path, root / "evaluation.json"


class LotteryMaxEvaluatorTests(unittest.TestCase):
    def test_plan_hash_binding_rejects_tampering_and_grid_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            validate_plan(plan)

            plan["signal"]["hold_days"] = 6
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_plan(plan)

            plan = _base_plan(Path(temp_dir))
            plan["frozen_parameters_no_grid"] = False
            plan["plan_hash"] = canonical_plan_hash(plan)
            with self.assertRaisesRegex(ValueError, "no-grid"):
                validate_plan(plan)

    def test_plan_requires_exact_unified_four_leg_costs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            validate_plan(plan)
            self.assertAlmostEqual(
                plan["economics"]["same_venue_four_perp_portfolio_cycle_costs"]["mexc"]["normal"]["total_cost_quote"],
                6.5,
            )
            self.assertAlmostEqual(
                plan["economics"]["same_venue_four_perp_portfolio_cycle_costs"]["gateio"]["stress"]["total_cost_quote"],
                9.2,
            )

            plan["economics"]["same_venue_four_perp_portfolio_cycle_costs"]["mexc"]["normal"]["total_cost_quote"] = 0.0
            plan["plan_hash"] = canonical_plan_hash(plan)
            with self.assertRaisesRegex(ValueError, "four-leg costs"):
                validate_plan(plan)

    def test_loader_excludes_any_bar_after_frozen_last_closed_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = _base_plan(root)
            kline = root / "mexc" / "klines" / "AAA_USDT.json"
            funding = root / "mexc" / "funding" / "AAA_USDT.json"
            kline.parent.mkdir(parents=True)
            funding.parent.mkdir(parents=True)
            kline.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"ts": _day("2026-07-12") * 86_400, "open": 1, "close": 1, "volume_quote": 10_000_000},
                            {"ts": _day("2026-07-13") * 86_400, "open": 1, "close": 99, "volume_quote": 10_000_000},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            funding.write_text(json.dumps({"rows": []}), encoding="utf-8")
            plan["sealed_input"]["universe"] = [
                {"exchange": "mexc", "symbol": "AAA_USDT", "base": "AAA"}
            ]

            markets, quality = _load_markets(plan)

            self.assertEqual(set(markets[0].bars), {_day("2026-07-12")})
            self.assertEqual(quality["markets"]["mexc:AAA_USDT"]["excluded_incomplete_bars"], 1)

    def test_main_signal_is_backward_only_and_selects_two_low_two_high(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            signal_day = _day("2026-02-24")
            first_day = signal_day - 60
            markets = [
                _market(f"{letter}_USDT", rank, first_day=first_day, days=70)
                for rank, letter in enumerate("ABCDEFGH", start=1)
            ]

            original, _ = build_venue_signals(plan, markets, "mexc", score_type="main")
            selected = next(row for row in original if row.signal_day == signal_day)
            self.assertEqual(selected.long_symbols, ("A_USDT", "B_USDT"))
            self.assertEqual(selected.short_symbols, ("H_USDT", "G_USDT"))
            self.assertEqual(selected.entry_day, signal_day + 1)
            self.assertEqual(selected.exit_day, signal_day + 5)

            for market in markets:
                future = signal_day + 7
                market.bars[future] = Bar(future, future * 86_400, 1.0, 1_000_000.0, 99_000_000.0)
            mutated, _ = build_venue_signals(plan, markets, "mexc", score_type="main")
            before = [row for row in original if row.signal_day <= signal_day]
            after = [row for row in mutated if row.signal_day <= signal_day]
            self.assertEqual(before, after)

    def test_signal_schedule_is_five_day_non_overlapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            anchor = _day("2026-02-24")
            markets = [
                _market(f"{letter}_USDT", rank, first_day=anchor - 60, days=90)
                for rank, letter in enumerate("ABCDEFGH", start=1)
            ]

            signals, _ = build_venue_signals(plan, markets, "mexc", score_type="main")

            self.assertGreaterEqual(len(signals), 4)
            for previous, current in zip(signals, signals[1:]):
                self.assertEqual(current.signal_day - previous.signal_day, 5)
                self.assertGreater(current.entry_day, previous.exit_day)

    def test_four_leg_execution_uses_next_open_fifth_close_and_legwise_funding_stress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            entry_day = _day("2026-05-14")
            exit_day = entry_day + 4
            markets = {}
            specs = {
                "A_USDT": (100.0, 110.0, 0.002),
                "B_USDT": (100.0, 105.0, 0.001),
                "G_USDT": (100.0, 90.0, 0.002),
                "H_USDT": (100.0, 95.0, -0.001),
            }
            for symbol, (entry, exit_price, funding_rate) in specs.items():
                market = MarketSeries(exchange="mexc", symbol=symbol, base=symbol[0])
                market.bars[entry_day] = Bar(entry_day, entry_day * 86_400, entry, entry, 10_000_000)
                market.bars[exit_day] = Bar(exit_day, exit_day * 86_400, exit_price, exit_price, 10_000_000)
                market.funding = [(entry_day * 86_400 + 3_600, funding_rate)]
                markets[symbol] = market
            signal = PortfolioSignal(
                exchange="mexc",
                score_type="main",
                signal_day=entry_day - 1,
                entry_day=entry_day,
                exit_day=exit_day,
                long_symbols=("A_USDT", "B_USDT"),
                long_bases=("A", "B"),
                short_symbols=("H_USDT", "G_USDT"),
                short_bases=("H", "G"),
                long_scores=(0.01, 0.02),
                short_scores=(0.08, 0.07),
                eligible_markets=8,
                selected_quote_volumes=(10_000_000.0,) * 4,
            )

            event = simulate_signal(plan, signal, markets)

            expected_price = 500.0 * (0.10 + 0.05 + 0.05 + 0.10)
            self.assertAlmostEqual(event.price_pnl_quote, expected_price, places=8)
            self.assertAlmostEqual(event.normal_cost_quote, 6.5, places=8)
            self.assertAlmostEqual(event.stress_cost_quote, 8.4, places=8)
            self.assertAlmostEqual(event.funding_pnl_quote, -1.0, places=8)
            self.assertAlmostEqual(event.stress_funding_pnl_quote, -1.5, places=8)
            self.assertAlmostEqual(event.normal_net_pnl_quote, expected_price - 1.0 - 6.5, places=8)

    def test_verdict_is_insufficient_before_performance_gates_then_rejects_then_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = _base_plan(Path(temp_dir))
            metrics = _passing_metrics()
            metrics["main"]["oos"]["event_count"] = 19
            decision = decide_verdict(plan, metrics)
            self.assertEqual(decision["verdict"], "INSUFFICIENT_DATA")

            metrics = _passing_metrics()
            metrics["main"]["oos"]["net_expectancy_quote"] = -0.01
            decision = decide_verdict(plan, metrics)
            self.assertEqual(decision["verdict"], "REJECT")
            self.assertIn("oos_net_expectancy_not_positive", decision["reasons"])

            decision = decide_verdict(plan, _passing_metrics())
            self.assertEqual(decision["verdict"], "ACCEPT_FOR_SHORT_EXECUTION_PROBE")

    def test_hash_mismatch_stops_evaluation_before_oos_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = _base_plan(root)
            plan["sealed_input"]["input_merkle_sha256"] = "0" * 64
            plan["plan_hash"] = canonical_plan_hash(plan)
            plan_path = root / "plan.json"
            output_path = root / "evaluation.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            report = evaluate_plan(plan_path, output_path=output_path, progress=None)

            self.assertEqual(report["verdict"], "INSUFFICIENT_DATA")
            self.assertIsNone(report["metrics"]["main"]["oos"])
            self.assertFalse(report["grid_search"])
            self.assertFalse(report["execution_probe_started"])
            self.assertFalse(report["paper_forward_started"])
            self.assertFalse(report["live_orders"])

    def test_full_fixture_is_deterministic_and_evaluates_one_frozen_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, output_path = _write_full_fixture(root)

            first = evaluate_plan(plan_path, output_path=output_path, progress=None)
            second = evaluate_plan(
                plan_path, output_path=root / "evaluation-repeat.json", progress=None
            )

            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first["parameter_combinations_evaluated"], 1)
            self.assertFalse(first["grid_search"])
            self.assertTrue(first["signals"]["main"])
            self.assertTrue(first["signals"]["robustness"])
            self.assertEqual(len(first["metrics"]["main"]["walk_forward"]["folds"]), 5)
            self.assertIn(
                first["verdict"],
                {"ACCEPT_FOR_SHORT_EXECUTION_PROBE", "REJECT", "INSUFFICIENT_DATA"},
            )

    def test_cli_is_bound_to_expected_plan_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = _base_plan(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Expected plan hash"):
                main(
                    [
                        "validate-seal",
                        "--plan",
                        str(plan_path),
                        "--expected-plan-hash",
                        "0" * 64,
                    ]
                )

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "validate-seal",
                        "--plan",
                        str(plan_path),
                        "--expected-plan-hash",
                        plan["plan_hash"],
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue().splitlines()[-1])
            self.assertEqual(payload["plan_hash"], plan["plan_hash"])
            self.assertEqual(payload["mode"], "validation_only")


if __name__ == "__main__":
    unittest.main()
