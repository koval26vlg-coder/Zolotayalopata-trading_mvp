from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from historical_basis_edge import (  # noqa: E402
    DATA_TYPE,
    HYPOTHESIS_ID,
    BasisBar,
    TradeResult,
    _trade_metrics,
    build_historical_basis_plan,
    calculate_trade,
    detect_entries,
    evaluate_historical_basis,
    historical_verdict,
    sha256_file,
    validate_historical_basis_plan,
)


def _asset(
    base: str,
    *,
    rank: int,
    age_days: int = 400,
    binance_spot: bool = False,
    categories: list[str] | None = None,
) -> dict[str, object]:
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": age_days,
        "binance_spot": binance_spot,
        "categories": categories or [],
        "liquidity_rank": rank,
    }


def _bar(
    ts: int,
    *,
    mexc_mark: float,
    mexc_index: float = 100.0,
    gate_mark: float,
    gate_index: float = 100.0,
    mexc_open: float = 100.0,
    gate_open: float = 100.0,
    mexc_funding: float | None = None,
    gate_funding: float | None = None,
    base: str = "AAA",
) -> BasisBar:
    return BasisBar(
        ts=ts,
        base=base,
        mexc_trade_open=mexc_open,
        mexc_trade_close=mexc_open,
        mexc_mark_close=mexc_mark,
        mexc_index_close=mexc_index,
        mexc_volume_quote=2_000_000.0,
        gateio_trade_open=gate_open,
        gateio_trade_close=gate_open,
        gateio_mark_close=gate_mark,
        gateio_index_close=gate_index,
        gateio_volume_quote=2_000_000.0,
        mexc_funding_rate=mexc_funding,
        gateio_funding_rate=gate_funding,
    )


def _trade(
    *,
    base: str,
    signal_ts: int,
    entry_ts: int,
    exit_ts: int,
    pnl: float,
) -> TradeResult:
    return TradeResult(
        base=base,
        signal_ts=signal_ts,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        long_venue="mexc",
        short_venue="gateio",
        exit_reason="convergence",
        price_pnl_quote=pnl + 1.0,
        funding_pnl_quote=0.0,
        cost_quote=1.0,
        price_only_net_pnl_quote=pnl,
        net_pnl_quote=pnl,
        holding_sec=exit_ts - entry_ts,
    )


class HistoricalBasisPlanTests(unittest.TestCase):
    def test_plan_binds_universe_source_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe_path = root / "universe.json"
            universe_path.write_text(json.dumps({"assets": [_asset(f"A{i}", rank=i) for i in range(8)]}), encoding="utf-8")
            plan_path = root / "plan.json"
            build_historical_basis_plan(
                [_asset(f"A{i}", rank=i) for i in range(8)],
                plan_path,
                universe_provenance={
                    "path": str(universe_path),
                    "file_sha256": sha256_file(universe_path),
                    "schema": "fixture_universe_v1",
                },
            )
            validate_historical_basis_plan(plan_path)
            universe_path.write_text('{"tampered":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "universe source artifact hash mismatch"):
                validate_historical_basis_plan(plan_path)

    def test_plan_freezes_non_binance_universe_and_cost_hurdle(self) -> None:
        assets = [_asset(f"A{i:02d}", rank=i) for i in range(22)]
        assets.extend(
            [
                _asset("BIN", rank=23, binance_spot=True),
                _asset("NEW", rank=24, age_days=100),
                _asset("LEV3L", rank=25, categories=["leveraged"]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            plan = build_historical_basis_plan(
                assets,
                plan_path,
                frozen_at_utc="2026-07-15T00:00:00+00:00",
            )
            validated = validate_historical_basis_plan(plan_path, plan["plan_hash"])

        self.assertEqual(plan["hypothesis"]["id"], HYPOTHESIS_ID)
        self.assertEqual(plan["hypothesis"]["required_data_type"], DATA_TYPE)
        self.assertEqual(plan["sample_plan"]["warmup_days"], 20)
        self.assertEqual(plan["sample_plan"]["train_days"], 100)
        self.assertEqual(plan["sample_plan"]["oos_days"], 100)
        self.assertEqual(plan["sample_plan"]["walk_forward_folds"], 5)
        self.assertEqual(len(plan["universe"]["candidates"]), 20)
        self.assertNotIn("BIN", [row["base"] for row in plan["universe"]["candidates"]])
        self.assertNotIn("NEW", [row["base"] for row in plan["universe"]["candidates"]])
        self.assertEqual(plan["economics"]["maker_fill_probability"], 0.0)
        expected_threshold = (
            plan["economics"]["stress_cycle_cost"]["total_bps"]
            + plan["strategy"]["exit_threshold_bps"]
            + plan["strategy"]["safety_margin_bps"]
        )
        self.assertEqual(plan["strategy"]["entry_threshold_bps"], expected_threshold)
        self.assertEqual(validated["plan_hash"], plan["plan_hash"])

    def test_plan_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            plan = build_historical_basis_plan(
                [_asset(f"A{i}", rank=i) for i in range(8)],
                plan_path,
                frozen_at_utc="2026-07-15T00:00:00+00:00",
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["strategy"]["maximum_holding_hours"] = 96
            plan_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                validate_historical_basis_plan(plan_path, plan["plan_hash"])

    def test_plan_excludes_ambiguous_ticker_collisions(self) -> None:
        assets = [_asset(f"A{i}", rank=i + 10) for i in range(8)]
        collision_a = _asset("COL", rank=1)
        collision_b = {**_asset("COL", rank=2), "canonical_asset_id": "asset:other-col"}
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_historical_basis_plan(
                [collision_a, collision_b, *assets],
                Path(tmp) / "plan.json",
                frozen_at_utc="2026-07-15T00:00:00+00:00",
            )
        self.assertNotIn("COL", [row["base"] for row in plan["universe"]["candidates"]])


class HistoricalBasisSignalTests(unittest.TestCase):
    def test_signal_uses_closed_bar_and_enters_on_next_bar(self) -> None:
        bars = [
            _bar(0, mexc_mark=98.0, gate_mark=102.0),
            _bar(300, mexc_mark=99.0, gate_mark=101.0, mexc_open=98.5, gate_open=101.5),
        ]
        entries = detect_entries(bars, entry_threshold_bps=300.0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].signal_ts, 0)
        self.assertEqual(entries[0].entry_ts, 300)
        self.assertEqual(entries[0].long_venue, "mexc")
        self.assertEqual(entries[0].short_venue, "gateio")
        self.assertEqual(entries[0].long_entry_price, 98.5)
        self.assertEqual(entries[0].short_entry_price, 101.5)

    def test_gap_blocks_next_bar_entry(self) -> None:
        bars = [
            _bar(0, mexc_mark=98.0, gate_mark=102.0),
            _bar(600, mexc_mark=99.0, gate_mark=101.0),
        ]
        self.assertEqual(detect_entries(bars, entry_threshold_bps=300.0), [])

    def test_trade_accounts_for_price_funding_and_four_operation_cost(self) -> None:
        bars = [
            _bar(0, mexc_mark=98.0, gate_mark=102.0),
            _bar(300, mexc_mark=98.5, gate_mark=101.5, mexc_open=98.0, gate_open=102.0),
            _bar(
                600,
                mexc_mark=100.0,
                gate_mark=100.1,
                mexc_open=100.0,
                gate_open=100.0,
                mexc_funding=0.0001,
                gate_funding=0.0002,
            ),
            _bar(900, mexc_mark=100.0, gate_mark=100.0, mexc_open=100.0, gate_open=100.0),
        ]
        entry = detect_entries(bars, entry_threshold_bps=300.0)[0]
        trade = calculate_trade(
            bars,
            entry,
            exit_threshold_bps=20.0,
            maximum_holding_hours=72,
            notional_quote_per_leg=500.0,
            cycle_cost_bps=36.0,
            favorable_funding_haircut=1.0,
        )
        self.assertEqual(trade.exit_ts, 900)
        self.assertGreater(trade.price_pnl_quote, 0.0)
        self.assertAlmostEqual(trade.funding_pnl_quote, 0.05)
        self.assertAlmostEqual(trade.cost_quote, 1.8)
        self.assertAlmostEqual(
            trade.net_pnl_quote,
            trade.price_pnl_quote + trade.funding_pnl_quote - trade.cost_quote,
        )

    def test_trade_never_calculates_pnl_across_price_gap(self) -> None:
        bars = [
            _bar(0, mexc_mark=98.0, gate_mark=102.0),
            _bar(300, mexc_mark=98.5, gate_mark=101.5, mexc_open=98.0, gate_open=102.0),
            _bar(1800, mexc_mark=100.0, gate_mark=100.0, mexc_open=100.0, gate_open=100.0),
        ]
        entry = detect_entries(bars, entry_threshold_bps=300.0)[0]
        with self.assertRaisesRegex(ValueError, "gap"):
            calculate_trade(
                bars,
                entry,
                exit_threshold_bps=20.0,
                maximum_holding_hours=72,
                notional_quote_per_leg=500.0,
                cycle_cost_bps=36.0,
                favorable_funding_haircut=1.0,
            )

    def test_right_censored_trade_is_not_force_closed_at_dataset_end(self) -> None:
        bars = [
            _bar(0, mexc_mark=98.0, gate_mark=102.0),
            _bar(300, mexc_mark=98.0, gate_mark=102.0, mexc_open=98.0, gate_open=102.0),
            _bar(600, mexc_mark=98.0, gate_mark=102.0, mexc_open=98.0, gate_open=102.0),
        ]
        entry = detect_entries(bars, entry_threshold_bps=300.0)[0]
        with self.assertRaisesRegex(ValueError, "right-censored"):
            calculate_trade(
                bars,
                entry,
                exit_threshold_bps=20.0,
                maximum_holding_hours=72,
                notional_quote_per_leg=500.0,
                cycle_cost_bps=36.0,
                favorable_funding_haircut=1.0,
            )

    def test_max_hold_exits_exactly_at_configured_bar_open(self) -> None:
        bars = [_bar(0, mexc_mark=98.0, gate_mark=102.0)]
        bars.extend(
            _bar(ts, mexc_mark=98.0, gate_mark=102.0, mexc_open=98.0, gate_open=102.0)
            for ts in range(300, 4500, 300)
        )
        entry = detect_entries(bars, entry_threshold_bps=300.0)[0]
        trade = calculate_trade(
            bars,
            entry,
            exit_threshold_bps=20.0,
            maximum_holding_hours=1,
            notional_quote_per_leg=500.0,
            cycle_cost_bps=36.0,
            favorable_funding_haircut=1.0,
        )
        self.assertEqual(trade.exit_reason, "max_hold")
        self.assertEqual(trade.exit_ts, entry.entry_ts + 3600)


class HistoricalBasisEvaluationTests(unittest.TestCase):
    def test_metrics_report_cluster_effective_sample_and_peak_collateral(self) -> None:
        day = 86_400
        trades = [
            _trade(base="AAA", signal_ts=day, entry_ts=day + 300, exit_ts=day + 3_600, pnl=4.0),
            _trade(base="BBB", signal_ts=day + 600, entry_ts=day + 900, exit_ts=day + 4_000, pnl=3.0),
            _trade(base="CCC", signal_ts=2 * day, entry_ts=2 * day + 300, exit_ts=2 * day + 600, pnl=2.0),
        ]
        metrics = _trade_metrics(trades, trades, oos_start_ts=0, plan_hash="fixture")
        self.assertEqual(metrics["independent_episode_count"], 3)
        self.assertAlmostEqual(metrics["effective_sample_size_dates"], 1.8)
        self.assertEqual(metrics["peak_concurrent_positions"], 2)
        self.assertEqual(metrics["secured_collateral_quote"], 2_000.0)
        self.assertAlmostEqual(metrics["max_concentration_share_by_dimension"]["date"], 7.0 / 9.0)
        self.assertAlmostEqual(metrics["max_concentration_share_by_dimension"]["episode"], 4.0 / 9.0)

    def test_oos_is_blocked_when_train_feasibility_fails(self) -> None:
        plan = {
            "plan_hash": "fixture",
            "sample_plan": {"warmup_days": 20, "train_days": 100, "oos_days": 100},
            "strategy": {"entry_threshold_bps": 300.0},
            "acceptance_gates": {"minimum_train_events": 20, "minimum_train_dates": 10},
        }
        result = evaluate_historical_basis(plan, [], stage="full_evaluation")
        self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
        self.assertFalse(result["oos_read"])
        self.assertIn("train_events", result["rejection_reasons"])

    def test_historical_verdict_requires_all_robustness_gates(self) -> None:
        passing = {
            "trade_count": 45,
            "unique_dates": 25,
            "base_count": 8,
            "price_only_expectancy_quote": 1.0,
            "net_expectancy_quote": 1.1,
            "profit_factor": 1.4,
            "positive_folds": 4,
            "stress_net_pnl_quote": 0.1,
            "cluster_bootstrap_lower_95_quote": 0.01,
            "direction_net_pnl_quote": {"mexc_long": 1.0, "gateio_long": 1.0},
            "max_concentration_share": 0.2,
            "max_drawdown_fraction": 0.05,
        }
        self.assertEqual(historical_verdict(passing)[0], "ACCEPT_FOR_EXECUTION_PROBE")
        failing = {**passing, "stress_net_pnl_quote": -0.01}
        verdict, reasons = historical_verdict(failing)
        self.assertEqual(verdict, "REJECT")
        self.assertIn("stress_net_pnl", reasons)


if __name__ == "__main__":
    unittest.main()
