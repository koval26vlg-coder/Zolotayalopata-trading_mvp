from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from basis import (  # noqa: E402
    BasisScanConfig,
    FundingAcceptanceConfig,
    FundingBacktestConfig,
    FundingDataQualityConfig,
    FundingOosConfig,
    FundingRankConfig,
    FundingSensitivityConfig,
    FundingStressConfig,
    FundingWalkForwardConfig,
    collect_funding_file,
    create_funding_paper_forward_plan_file,
    evaluate_funding_backtest_metrics,
    funding_collect_diagnostics_file,
    funding_decision_report,
    funding_frontier_report,
    funding_goal_audit,
    funding_paper_decision_report,
    funding_universe_coverage,
    funding_gate_report,
    funding_progress_report,
    funding_regime_report,
    stress_funding_backtest_metrics,
    load_funding_rows,
    match_contract_for_spot,
    opportunity_from_snapshots,
    rank_funding_file,
    rank_funding_rows,
    reprice_funding_rows_for_costs,
    run_funding_backtest,
    run_funding_oos_backtest,
    run_funding_paper_forward_file,
    run_funding_postprocess_file,
    run_funding_final_review_file,
    run_funding_research_finalize_file,
    run_funding_sensitivity,
    run_funding_walk_forward_backtest,
    select_pairs_with_contracts,
    wait_funding_ready,
    write_funding_matched_universe_csv,
    write_funding_quality_universe_csv,
)
from cli import (  # noqa: E402
    AUTO_FUNDING_OOS_OUTPUT,
    AUTO_FUNDING_WALK_FORWARD_OUTPUT,
    build_parser,
    cmd_funding_collect,
    main,
    _apply_funding_strict_research_preset,
)
from config import AppConfig, ExchangeConfig, PathsConfig, RiskConfig, StrategyConfig  # noqa: E402
from exchanges import MarketPair, MarketSnapshot  # noqa: E402
from funding import FundingContract, FundingSnapshot  # noqa: E402
from multi_bot import load_universe_symbols  # noqa: E402


def _spot(
    ts: float = 1.0,
    bid: float = 100.0,
    ask: float = 100.1,
    bid_qty: float = 10.0,
    ask_qty: float = 10.0,
) -> MarketSnapshot:
    mid = (bid + ask) / 2
    return MarketSnapshot(
        exchange="gateio",
        symbol="HYPE_USDT",
        ts=ts,
        bid=bid,
        ask=ask,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        spread_bps=((ask - bid) / mid) * 1e4,
        imbalance=0.0,
        signed_flow_notional=0.0,
        new_trade_count=0,
        last_trade_price=None,
    )


def _funding(
    ts: float = 1.0,
    rate: float = 0.0001,
    bid: float = 100.2,
    ask: float = 100.3,
    mark: float = 100.25,
    volume_quote: float = 1_000_000,
) -> FundingSnapshot:
    return FundingSnapshot(
        exchange="gateio",
        symbol="HYPE_USDT",
        base="HYPE",
        quote="USDT",
        ts=ts,
        funding_rate=rate,
        next_funding_ts=ts + 14_400,
        funding_interval_sec=14_400,
        mark_price=mark,
        index_price=100.2,
        perp_bid=bid,
        perp_ask=ask,
        volume_24h_quote=volume_quote,
    )


def _accepted_research_acceptance() -> dict:
    return {
        "accepted": True,
        "full_backtest_accepted": True,
        "oos_required_passed": True,
        "oos_accepted": True,
        "walk_forward_required_passed": True,
        "walk_forward_accepted": True,
        "stress_required_passed": True,
        "stress_assumptions_passed": True,
        "stress_accepted": True,
        "reasons": [],
    }


def _accepted_source_data_quality(first_ts: float = 0.0, last_ts: float = 0.5) -> dict:
    span_sec = max(0.0, last_ts - first_ts)
    return {
        "accepted": True,
        "reasons": [],
        "metrics": {
            "rows": 10,
            "markets": 2,
            "completed_cycles": 10,
            "errors": 0,
            "attempts": 10,
            "error_rate": 0.0,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "span_sec": span_sec,
            "span_hours": span_sec / 3600.0,
        },
    }


def _accepted_source_time_range(first_ts: float = 0.0, last_ts: float = 0.5) -> dict:
    span_sec = max(0.0, last_ts - first_ts)
    return {
        "first_ts": first_ts,
        "last_ts": last_ts,
        "span_sec": span_sec,
        "span_hours": span_sec / 3600.0,
    }


def _accepted_plan_decision_fields(path: str = "decision.json") -> dict:
    return {
        "source_decision_report": path,
        "decision_summary": {
            "accepted": True,
            "reasons": [],
            "verdict": "paper_forward_candidate",
            "next_action": "run_funding_paper_plan",
        },
    }


def _paper_forward_summary_fixture(
    plan: Path,
    source_input: Path,
    *,
    forward_input: Path | None = None,
    output: Path | None = None,
    frozen_config: dict | None = None,
) -> dict:
    metrics = {
        "total_trades": 10,
        "win_rate": 0.7,
        "expectancy_quote": 0.1,
        "net_pnl_quote": 1.0,
        "max_drawdown_quote": 0.0,
        "profit_factor": 2.0,
        "funding_pnl_quote": 1.5,
        "basis_pnl_quote": 0.2,
        "fees_quote": 0.5,
        "slippage_quote": 0.2,
    }
    coverage = {
        "duration_accepted": True,
        "rows_accepted": True,
        "markets_accepted": True,
    }
    return {
        "mode": "funding_paper_forward",
        "ok": True,
        "status": "completed",
        "plan": str(plan),
        "input": str(forward_input or source_input.with_name("paper_forward_input.jsonl")),
        "output": str(output or source_input.with_name("paper_forward_output.jsonl")),
        "source_input": str(source_input),
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "metrics": metrics,
        "paper_acceptance": {"accepted": True, "reasons": []},
        "coverage": coverage,
        "frozen_config": frozen_config or {},
    }


def _paper_decision_report_fixture(summary: Path, plan: Path) -> dict:
    summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    metrics = summary_payload.get("metrics") or {}
    paper_acceptance = summary_payload.get("paper_acceptance") or {}
    coverage = summary_payload.get("coverage") or {}
    return {
        "mode": "funding_paper_decision_report",
        "research_only": True,
        "live_orders": False,
        "api_keys_required": False,
        "leverage_enabled": False,
        "margin_execution": False,
        "summary_path": str(summary),
        "plan_path": str(plan),
        "summary": {
            "accepted": True,
            "reasons": [],
            "verdict": "continue_paper_forward",
            "next_action": "extend_paper_forward_dataset",
            "status": summary_payload.get("status"),
            "paper_acceptance_accepted": paper_acceptance.get("accepted"),
            "total_trades": metrics.get("total_trades"),
            "win_rate": metrics.get("win_rate"),
            "expectancy_quote": metrics.get("expectancy_quote"),
            "net_pnl_quote": metrics.get("net_pnl_quote"),
            "max_drawdown_quote": metrics.get("max_drawdown_quote"),
            "profit_factor": metrics.get("profit_factor"),
            "funding_pnl_quote": metrics.get("funding_pnl_quote"),
            "basis_pnl_quote": metrics.get("basis_pnl_quote"),
            "fees_quote": metrics.get("fees_quote"),
            "slippage_quote": metrics.get("slippage_quote"),
            "coverage": coverage,
        },
        "metrics": metrics,
        "paper_acceptance": paper_acceptance,
        "coverage": coverage,
        "frozen_config": summary_payload.get("frozen_config") or {},
    }


class BasisTests(unittest.TestCase):
    def test_symbol_mapping_matches_base_quote(self) -> None:
        pair = MarketPair("gateio", "HYPE_USDT", "HYPE", "USDT")
        contracts = [
            FundingContract("gateio", "OKB_USDT", "OKB", "USDT", "trading"),
            FundingContract("gateio", "HYPE_USDT", "HYPE", "USDT", "trading"),
        ]
        self.assertEqual(match_contract_for_spot(pair, contracts).symbol, "HYPE_USDT")  # type: ignore[union-attr]
        self.assertIsNone(match_contract_for_spot(MarketPair("gateio", "CC_USDT", "CC", "USDT"), contracts))

    def test_select_pairs_with_contracts_skips_spot_without_perp_before_limit(self) -> None:
        pairs = [
            MarketPair("mexc", "ONLYSPOTUSDT", "ONLYSPOT", "USDT"),
            MarketPair("mexc", "HYPEUSDT", "HYPE", "USDT"),
            MarketPair("mexc", "XMRUSDT", "XMR", "USDT"),
        ]
        contracts = [
            FundingContract("mexc", "HYPE_USDT", "HYPE", "USDT", "trading"),
            FundingContract("mexc", "XMR_USDT", "XMR", "USDT", "trading"),
        ]

        selected, stats = select_pairs_with_contracts(
            pairs,
            contracts,
            ["ONLYSPOT", "HYPE", "XMR"],
            max_pairs=2,
        )

        self.assertEqual([pair.base for pair in selected], ["HYPE", "XMR"])
        self.assertEqual(stats["skipped_no_perp"], 1)
        self.assertEqual(stats["spot_and_perp"], 2)

    def test_funding_universe_coverage_classifies_spot_perp_availability(self) -> None:
        class SpotClient:
            def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
                return [
                    MarketPair("mexc", "HYPEUSDT", "HYPE", quote),
                    MarketPair("mexc", "ONLYSPOTUSDT", "ONLYSPOT", quote),
                ]

        class FundingClient:
            def fetch_contracts(self) -> list[FundingContract]:
                return [
                    FundingContract("mexc", "HYPE_USDT", "HYPE", "USDT", "trading"),
                    FundingContract("mexc", "ONLYPERP_USDT", "ONLYPERP", "USDT", "trading"),
                ]

        report = funding_universe_coverage(
            spot_clients={"mexc": SpotClient()},  # type: ignore[dict-item]
            funding_clients={"mexc": FundingClient()},  # type: ignore[dict-item]
            universe_symbols=["HYPE", "ONLYSPOT", "ONLYPERP", "MISSING", "HYPE"],
        )

        self.assertEqual(report["summary"]["universe_symbols"], 4)
        self.assertEqual(report["summary"]["spot_and_perp_slots"], 1)
        self.assertEqual(report["summary"]["unique_spot_and_perp_symbols"], 1)
        self.assertEqual(report["summary"]["unique_missing_spot_and_perp_symbols"], 3)
        self.assertEqual(report["summary"]["best_exchange"], "mexc")
        self.assertEqual(report["symbols_with_spot_and_perp"], ["HYPE"])
        self.assertEqual(report["symbols_without_spot_and_perp"], ["ONLYSPOT", "ONLYPERP", "MISSING"])
        mexc = report["per_exchange"]["mexc"]
        self.assertEqual(mexc["spot_available"], 2)
        self.assertEqual(mexc["perp_available"], 2)
        self.assertEqual(mexc["spot_and_perp"], 1)
        self.assertEqual(mexc["spot_only"], 1)
        self.assertEqual(mexc["perp_only"], 1)
        self.assertEqual(mexc["missing_both"], 1)
        statuses = {(row["base"], row["status"]) for row in report["rows"]}
        self.assertIn(("HYPE", "spot_and_perp"), statuses)
        self.assertIn(("ONLYSPOT", "spot_only"), statuses)
        self.assertIn(("ONLYPERP", "perp_only"), statuses)
        self.assertIn(("MISSING", "missing_both"), statuses)

    def test_write_funding_matched_universe_csv_is_collect_compatible(self) -> None:
        coverage = {
            "rows": [
                {
                    "exchange": "mexc",
                    "base": "HYPE",
                    "universe_rank": 2,
                    "status": "spot_and_perp",
                    "spot_symbol": "HYPEUSDT",
                    "perp_symbol": "HYPE_USDT",
                },
                {
                    "exchange": "gateio",
                    "base": "HYPE",
                    "universe_rank": 2,
                    "status": "spot_and_perp",
                    "spot_symbol": "HYPE_USDT",
                    "perp_symbol": "HYPE_USDT",
                },
                {
                    "exchange": "mexc",
                    "base": "EDGE",
                    "universe_rank": 1,
                    "status": "spot_and_perp",
                    "spot_symbol": "EDGEUSDT",
                    "perp_symbol": "EDGE_USDT",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "matched.csv"
            result = write_funding_matched_universe_csv(coverage, output)

            self.assertEqual(result["symbols"], 2)
            self.assertEqual(result["exchange_symbol_slots"], 3)
            self.assertEqual(load_universe_symbols(output), ["HYPE", "EDGE"])
            content = output.read_text(encoding="utf-8-sig")
            self.assertIn("symbol,universe_rank,exchange_count,exchanges", content)
            self.assertIn("gateio,mexc", content)

    def test_write_funding_quality_universe_csv_prioritizes_liquidity(self) -> None:
        liquid = opportunity_from_snapshots(
            _spot(ts=1.0, bid_qty=20.0, ask_qty=20.0),
            _funding(ts=1.0, rate=0.001, volume_quote=10_000_000),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        thin = opportunity_from_snapshots(
            _spot(ts=1.0, bid_qty=0.1, ask_qty=0.1),
            _funding(ts=1.0, rate=0.001, volume_quote=100_000),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        assert liquid is not None
        assert thin is not None
        liquid.update({"base": "LIQ", "spot_symbol": "LIQ_USDT", "perp_symbol": "LIQ_USDT"})
        thin.update({"base": "THIN", "spot_symbol": "THIN_USDT", "perp_symbol": "THIN_USDT"})

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "quality.csv"
            result = write_funding_quality_universe_csv(
                [thin, liquid],  # type: ignore[list-item]
                output,
                cfg=FundingRankConfig(min_expected_net_carry_bps=0.0),
            )

            self.assertEqual(result["symbols"], 2)
            self.assertEqual(load_universe_symbols(output), ["LIQ", "THIN"])
            content = output.read_text(encoding="utf-8-sig")
            self.assertIn("symbol,quality_rank,exchange_count", content)
            self.assertIn("max_regime_spot_top_min_notional_avg_quote", content)

    def test_opportunity_scores_basis_and_execution(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig(max_spot_spread_bps=20, max_perp_spread_bps=20))
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["base"], "HYPE")
        self.assertGreater(row["basis_bps"], 0)
        self.assertGreater(row["carry_score"], 0)
        self.assertTrue(row["eligible"])
        self.assertIn("expected_net_carry_bps", row)
        self.assertIn("break_even_funding_intervals", row)
        self.assertEqual(row["spot_bid_notional_quote"], 1000.0)
        self.assertEqual(row["spot_ask_notional_quote"], 1001.0)
        self.assertEqual(row["spot_top_min_notional_quote"], 1000.0)

    def test_opportunity_can_filter_thin_spot_top_liquidity(self) -> None:
        row = opportunity_from_snapshots(
            _spot(bid_qty=0.5, ask_qty=0.4),
            _funding(),
            BasisScanConfig(min_spot_top_notional_quote=100.0),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertLess(row["spot_top_min_notional_quote"], 100.0)
        self.assertIn("spot_top_liquidity_low", row["reasons"])
        self.assertFalse(row["eligible"])

    def test_opportunity_can_filter_negative_basis_for_short_perp_carry(self) -> None:
        row = opportunity_from_snapshots(
            _spot(bid=100.0, ask=100.1),
            _funding(mark=99.0, bid=98.9, ask=99.1),
            BasisScanConfig(min_basis_bps=0.0),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertLess(row["basis_bps"], 0)
        self.assertIn("basis_below_min", row["reasons"])
        self.assertFalse(row["eligible"])

    def test_opportunity_allows_zero_basis_when_min_basis_is_zero(self) -> None:
        row = opportunity_from_snapshots(
            _spot(bid=100.0, ask=100.1),
            _funding(mark=100.05, bid=100.0, ask=100.1),
            BasisScanConfig(min_basis_bps=0.0),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["basis_bps"], 0.0)
        self.assertNotIn("basis_below_min", row["reasons"])
        self.assertTrue(row["eligible"])

    def test_opportunity_can_filter_unprofitable_expected_carry(self) -> None:
        row = opportunity_from_snapshots(
            _spot(),
            _funding(rate=0.00005),
            BasisScanConfig(
                spot_fee_bps=10.0,
                perp_fee_bps=7.5,
                slippage_bps=1.0,
                target_hold_intervals=1.0,
                min_expected_net_carry_bps=0.0,
            ),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["round_trip_cost_bps"], 39.0)
        self.assertLess(row["expected_net_carry_bps"], 0)
        self.assertIn("expected_edge_below_min", row["reasons"])
        self.assertFalse(row["eligible"])

    def test_opportunity_can_filter_negative_risk_adjusted_edge(self) -> None:
        row = opportunity_from_snapshots(
            _spot(),
            _funding(rate=0.001),
            BasisScanConfig(
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                target_hold_intervals=1.0,
                min_expected_net_carry_bps=0.0,
                min_risk_adjusted_edge_bps=1.0,
                spread_risk_multiplier=1.0,
            ),
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertGreater(row["expected_net_carry_bps"], 0.0)
        self.assertIn("risk_adjusted_edge_bps", row)
        self.assertLess(row["risk_adjusted_edge_bps"], 1.0)
        self.assertIn("risk_adjusted_edge_below_min", row["reasons"])
        self.assertFalse(row["eligible"])

    def test_opportunity_can_filter_long_break_even_horizon(self) -> None:
        row = opportunity_from_snapshots(
            _spot(),
            _funding(rate=0.0001),
            BasisScanConfig(max_break_even_hours=24.0),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertGreater(row["break_even_hours"], 24.0)
        self.assertIn("break_even_horizon_too_long", row["reasons"])
        self.assertFalse(row["eligible"])

    def test_backtest_accrues_positive_funding_for_short_perp(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=14_401.0), _funding(ts=14_401.0), BasisScanConfig()),
                "total_score": 1.0,
            },
        ]
        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
        )
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertGreater(result["metrics"]["funding_pnl_quote"], 0)

    def test_backtest_does_not_prorate_funding_before_next_settlement(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=7_201.0), _funding(ts=7_201.0), BasisScanConfig()),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
        )

        self.assertEqual(result["metrics"]["funding_pnl_quote"], 0.0)
        self.assertEqual(result["trades"][0]["funding_pnl_quote"], 0.0)

    def test_backtest_uses_base_tier_costs_for_each_exchange(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=14_401.0), _funding(ts=14_401.0), BasisScanConfig()),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=10.0,
                perp_fee_bps=7.5,
                slippage_bps=1.0,
                spot_fee_bps_by_exchange={"gateio": 5.0},
                perp_fee_bps_by_exchange={"gateio": 2.5},
                slippage_bps_by_exchange={"gateio": 0.5},
                min_total_score=0.0,
            ),
        )

        trade = result["trades"][0]
        self.assertAlmostEqual(trade["fees_quote"], 0.15)
        self.assertAlmostEqual(trade["slippage_quote"], 0.02)

    def test_backtest_reports_equity_curve_and_drawdown(self) -> None:
        profitable_entry = {
            **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig()),
            "total_score": 1.0,
        }
        profitable_exit = {
            **opportunity_from_snapshots(
                _spot(ts=2.0, bid=101.0, ask=101.1),
                _funding(ts=2.0, bid=99.8, ask=99.9),
                BasisScanConfig(),
            ),
            "total_score": 1.0,
        }
        losing_entry = {
            **opportunity_from_snapshots(
                _spot(ts=1.5, bid=100.0, ask=100.1),
                _funding(ts=1.5),
                BasisScanConfig(),
            ),
            "base": "LOSS",
            "spot_symbol": "LOSS_USDT",
            "perp_symbol": "LOSS_USDT",
            "total_score": 1.0,
        }
        losing_exit = {
            **opportunity_from_snapshots(
                _spot(ts=3.0, bid=99.0, ask=99.1),
                _funding(ts=3.0, bid=100.9, ask=101.0),
                BasisScanConfig(),
            ),
            "base": "LOSS",
            "spot_symbol": "LOSS_USDT",
            "perp_symbol": "LOSS_USDT",
            "total_score": 1.0,
        }

        result = run_funding_backtest(
            [profitable_entry, profitable_exit, losing_entry, losing_exit],  # type: ignore[list-item]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 2)
        self.assertIn("max_drawdown_quote", result["metrics"])
        self.assertGreater(result["metrics"]["max_drawdown_quote"], 0)
        self.assertEqual(len(result["equity_curve"]), 2)
        self.assertEqual([point["trade_index"] for point in result["equity_curve"]], [1, 2])
        self.assertEqual(result["equity_curve"][0]["exit_ts"], 2.0)
        self.assertEqual(result["equity_curve"][1]["exit_ts"], 3.0)
        self.assertAlmostEqual(result["metrics"]["ending_equity_quote"], result["metrics"]["net_pnl_quote"])

    def test_evaluate_funding_backtest_metrics_accepts_and_rejects_by_gates(self) -> None:
        passing = evaluate_funding_backtest_metrics(
            {
                "markets": 3,
                "total_trades": 30,
                "total_notional_quote": 3000.0,
                "win_rate": 0.7,
                "expectancy_quote": 0.05,
                "net_pnl_quote": 1.5,
                "max_drawdown_quote": 0.5,
                "profit_factor": 1.6,
            },
            FundingAcceptanceConfig(
                min_trades=20,
                min_win_rate=0.6,
                min_expectancy_quote=0.0,
                min_net_pnl_quote=0.0,
                max_drawdown_quote=1.0,
                min_profit_factor=1.2,
            ),
        )
        self.assertTrue(passing["accepted"])
        self.assertEqual(passing["reasons"], [])

        failing = evaluate_funding_backtest_metrics(
            {
                "markets": 1,
                "total_trades": 3,
                "total_notional_quote": 300.0,
                "win_rate": 0.25,
                "expectancy_quote": -0.1,
                "net_pnl_quote": -1.0,
                "max_drawdown_quote": 5.0,
                "profit_factor": 0.8,
            },
            FundingAcceptanceConfig(
                min_trades=20,
                min_win_rate=0.6,
                min_expectancy_quote=0.0,
                min_net_pnl_quote=0.0,
                max_drawdown_quote=1.0,
                min_profit_factor=1.2,
            ),
        )
        self.assertFalse(failing["accepted"])
        self.assertIn("min_trades", failing["reasons"])
        self.assertIn("min_win_rate", failing["reasons"])
        self.assertIn("min_expectancy_quote", failing["reasons"])
        self.assertIn("min_net_pnl_quote", failing["reasons"])
        self.assertIn("max_drawdown_quote", failing["reasons"])
        self.assertIn("min_profit_factor", failing["reasons"])

    def test_acceptance_rejects_market_concentration(self) -> None:
        result = evaluate_funding_backtest_metrics(
            {
                "markets": 1,
                "market_trade_counts": {"gateio:HYPE_USDT": 10},
                "max_market_trade_share": 1.0,
                "total_trades": 10,
                "total_notional_quote": 1000.0,
                "win_rate": 0.8,
                "expectancy_quote": 0.1,
                "net_pnl_quote": 1.0,
                "max_drawdown_quote": 0.5,
                "profit_factor": 2.0,
            },
            FundingAcceptanceConfig(
                min_trades=5,
                min_win_rate=0.6,
                min_expectancy_quote=0.0,
                min_net_pnl_quote=0.0,
                max_drawdown_quote=1.0,
                min_profit_factor=1.2,
                min_markets=2,
                max_market_trade_share=0.6,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("min_markets", result["reasons"])
        self.assertIn("max_market_trade_share", result["reasons"])
        self.assertEqual(result["metrics"]["markets"], 1)
        self.assertEqual(result["metrics"]["max_market_trade_share"], 1.0)

    def test_acceptance_rejects_exchange_concentration(self) -> None:
        result = evaluate_funding_backtest_metrics(
            {
                "markets": 3,
                "traded_markets": 3,
                "traded_exchanges": 1,
                "exchange_trade_counts": {"gateio": 10},
                "max_exchange_trade_share": 1.0,
                "total_trades": 10,
                "total_notional_quote": 1000.0,
                "win_rate": 0.8,
                "expectancy_quote": 0.1,
                "net_pnl_quote": 1.0,
                "max_drawdown_quote": 0.5,
                "profit_factor": 2.0,
            },
            FundingAcceptanceConfig(
                min_trades=5,
                min_win_rate=0.6,
                min_expectancy_quote=0.0,
                min_net_pnl_quote=0.0,
                max_drawdown_quote=1.0,
                min_profit_factor=1.2,
                min_markets=2,
                max_market_trade_share=1.0,
                min_exchanges=2,
                max_exchange_trade_share=0.75,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("min_exchanges", result["reasons"])
        self.assertIn("max_exchange_trade_share", result["reasons"])
        self.assertEqual(result["metrics"]["traded_exchanges"], 1)
        self.assertEqual(result["metrics"]["max_exchange_trade_share"], 1.0)

    def test_acceptance_rejects_window_pnl_concentration(self) -> None:
        result = evaluate_funding_backtest_metrics(
            {
                "markets": 3,
                "traded_markets": 3,
                "active_windows": 1,
                "profitable_windows": 1,
                "max_window_pnl_share": 1.0,
                "total_trades": 12,
                "total_notional_quote": 1200.0,
                "win_rate": 0.75,
                "expectancy_quote": 0.1,
                "net_pnl_quote": 1.2,
                "max_drawdown_quote": 0.5,
                "profit_factor": 2.0,
            },
            FundingAcceptanceConfig(
                min_trades=10,
                min_win_rate=0.6,
                min_expectancy_quote=0.0,
                min_net_pnl_quote=0.0,
                max_drawdown_quote=1.0,
                min_profit_factor=1.2,
                min_markets=2,
                max_market_trade_share=0.6,
                min_profitable_windows=2,
                max_window_pnl_share=0.6,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("min_profitable_windows", result["reasons"])
        self.assertIn("max_window_pnl_share", result["reasons"])
        self.assertEqual(result["metrics"]["profitable_windows"], 1)
        self.assertEqual(result["metrics"]["max_window_pnl_share"], 1.0)

    def test_backtest_reports_hourly_window_metrics(self) -> None:
        def _as_market(row: dict, base: str, exchange: str = "gateio") -> dict:
            updated = dict(row)
            updated["exchange"] = exchange
            updated["base"] = base
            updated["spot_symbol"] = f"{base}_USDT"
            updated["perp_symbol"] = f"{base}_USDT"
            return updated

        row1 = opportunity_from_snapshots(
            _spot(ts=1.0, bid=100.0, ask=100.01),
            _funding(ts=1.0, rate=0.01, bid=100.0, ask=100.01, mark=100.005),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        row2 = opportunity_from_snapshots(
            _spot(ts=1801.0, bid=100.0, ask=100.01),
            _funding(ts=1801.0, rate=0.01, bid=100.0, ask=100.01, mark=100.005),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        row3 = opportunity_from_snapshots(
            _spot(ts=3601.0, bid=100.0, ask=100.01),
            _funding(ts=3601.0, rate=0.01, bid=100.0, ask=100.01, mark=100.005),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        row4 = opportunity_from_snapshots(
            _spot(ts=5401.0, bid=100.0, ask=100.01),
            _funding(ts=5401.0, rate=0.01, bid=100.0, ask=100.01, mark=100.005),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        assert row1 is not None
        assert row2 is not None
        assert row3 is not None
        assert row4 is not None
        row1["next_funding_ts"] = 1801.0
        row3["next_funding_ts"] = 5401.0

        result = run_funding_backtest(
            [
                _as_market(row1, "HYPE"),
                _as_market(row2, "HYPE"),
                _as_market(row3, "ABC", "mexc"),
                _as_market(row4, "ABC", "mexc"),
            ],
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=-1000.0,
            ),
        )

        metrics = result["metrics"]
        self.assertEqual(metrics["total_trades"], 2)
        self.assertEqual(metrics["active_windows"], 2)
        self.assertEqual(metrics["profitable_windows"], 2)
        self.assertAlmostEqual(metrics["max_window_pnl_share"], 0.5)
        self.assertEqual(sum(metrics["window_trade_counts"].values()), 2)
        self.assertEqual(metrics["traded_exchanges"], 2)
        self.assertEqual(metrics["exchange_trade_counts"], {"gateio": 1, "mexc": 1})
        self.assertEqual(metrics["max_exchange_trade_share"], 0.5)

    def test_stress_funding_backtest_metrics_penalizes_basis_spread_and_funding_flip(self) -> None:
        stress = stress_funding_backtest_metrics(
            {
                "total_trades": 10,
                "total_notional_quote": 1000.0,
                "net_pnl_quote": 5.0,
                "max_drawdown_quote": 1.0,
            },
            FundingStressConfig(
                enabled=True,
                adverse_basis_bps=10.0,
                spread_widen_bps=5.0,
                funding_flip_bps=2.0,
            ),
        )

        self.assertEqual(stress["stress_cost_bps"], 22.0)
        self.assertAlmostEqual(stress["stress_cost_quote"], 2.2)
        self.assertAlmostEqual(stress["stress_net_pnl_quote"], 2.8)
        self.assertAlmostEqual(stress["stress_max_drawdown_quote"], 3.2)

    def test_acceptance_rejects_when_stress_adjusted_result_fails(self) -> None:
        result = evaluate_funding_backtest_metrics(
            {
                "total_trades": 30,
                "total_notional_quote": 3000.0,
                "win_rate": 0.7,
                "expectancy_quote": 0.2,
                "net_pnl_quote": 6.0,
                "max_drawdown_quote": 1.0,
                "profit_factor": 1.8,
            },
            FundingAcceptanceConfig(
                min_trades=20,
                min_win_rate=0.6,
                min_expectancy_quote=0.0,
                min_net_pnl_quote=0.0,
                max_drawdown_quote=5.0,
                min_profit_factor=1.2,
            ),
            FundingStressConfig(
                enabled=True,
                adverse_basis_bps=15.0,
                spread_widen_bps=5.0,
                funding_flip_bps=0.0,
                min_stress_net_pnl_quote=0.0,
                max_stress_drawdown_quote=5.0,
            ),
        )

        self.assertFalse(result["accepted"])
        self.assertIn("stress_min_net_pnl_quote", result["reasons"])
        self.assertIn("stress_max_drawdown_quote", result["reasons"])
        self.assertLess(result["stress"]["stress_net_pnl_quote"], 0)

    def test_backtest_uses_rolling_persistence_without_lookahead(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0, rate=0.0001), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=0.0001), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=3.0), _funding(ts=3.0, rate=-0.0001), BasisScanConfig()),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_funding_observations=2,
                min_funding_positive_ratio=0.9,
                min_funding_persistence_score=0.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["entry_ts"], 2.0)
        self.assertEqual(result["trades"][0]["exit_reason"], "funding_not_positive")

    def test_backtest_blocks_entry_until_rolling_persistence_passes(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0, rate=0.0001), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=0.0001), BasisScanConfig()),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_funding_observations=3,
                min_funding_positive_ratio=1.0,
                min_funding_persistence_score=0.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_backtest_blocks_entry_when_rolling_volume_regime_fails(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(
                    _spot(ts=1.0),
                    _funding(ts=1.0, volume_quote=100_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=2.0),
                    _funding(ts=2.0, volume_quote=100_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_regime_observations=2,
                min_perp_volume_24h_quote=1_000_000,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_backtest_blocks_entry_when_spot_top_liquidity_regime_fails(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(
                    _spot(ts=1.0, bid_qty=0.2, ask_qty=0.2),
                    _funding(ts=1.0, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=2.0, bid_qty=0.2, ask_qty=0.2),
                    _funding(ts=2.0, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_regime_observations=2,
                min_spot_top_notional_quote=100.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_backtest_blocks_entry_when_basis_below_min(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(
                    _spot(ts=1.0, bid=100.0, ask=100.1),
                    _funding(ts=1.0, mark=99.0, bid=98.9, ask=99.1, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=2.0, bid=100.0, ask=100.1),
                    _funding(ts=2.0, mark=99.0, bid=98.9, ask=99.1, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_basis_bps=0.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_backtest_allows_entry_when_basis_equals_min_basis(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(
                    _spot(ts=1.0, bid=100.0, ask=100.1),
                    _funding(ts=1.0, mark=100.05, bid=100.0, ask=100.1, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=14_401.0, bid=100.0, ask=100.1),
                    _funding(ts=14_401.0, mark=100.05, bid=100.0, ask=100.1, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_basis_bps=0.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 1)

    def test_backtest_blocks_entry_when_break_even_horizon_too_long(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0, volume_quote=2_000_000), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=14_401.0),
                    _funding(ts=14_401.0, volume_quote=2_000_000),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                max_break_even_hours=24.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_reprice_funding_rows_updates_expected_carry_and_break_even(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(rate=0.001), BasisScanConfig())
        assert row is not None

        repriced = reprice_funding_rows_for_costs(
            [row],
            spot_fee_bps=0.0,
            perp_fee_bps=0.0,
            slippage_bps=0.0,
            target_hold_intervals=3.0,
            min_expected_net_carry_bps=0.0,
            max_break_even_hours=24.0,
        )

        self.assertEqual(len(repriced), 1)
        self.assertEqual(repriced[0]["round_trip_cost_bps"], 0.0)
        self.assertEqual(repriced[0]["target_hold_intervals"], 3.0)
        self.assertGreater(repriced[0]["expected_net_carry_bps"], 0.0)
        self.assertEqual(repriced[0]["break_even_hours"], 0.0)
        self.assertTrue(repriced[0]["eligible"])

    def test_funding_sensitivity_sorts_more_viable_execution_scenarios_first(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_sensitivity(
            rows,
            sensitivity_cfg=FundingSensitivityConfig(
                spot_fee_bps_values=(0.0, 10.0),
                perp_fee_bps_values=(0.0,),
                slippage_bps_values=(0.0,),
                target_hold_intervals_values=(1.0,),
                max_break_even_hours_values=(24.0,),
                top_n=5,
            ),
            backtest_cfg=FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_expected_net_carry_bps=0.0,
                max_break_even_hours=24.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.0,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
        )

        self.assertEqual(result["summary"]["scenarios"], 2)
        self.assertEqual(result["scenarios"][0]["scenario"]["spot_fee_bps"], 0.0)
        self.assertGreaterEqual(
            result["scenarios"][0]["metrics"]["net_pnl_quote"],
            result["scenarios"][1]["metrics"]["net_pnl_quote"],
        )

    def test_funding_sensitivity_requires_stress_for_research_acceptance(self) -> None:
        row = opportunity_from_snapshots(
            _spot(ts=1.0),
            _funding(ts=1.0, rate=0.002),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        assert row is not None
        row["total_score"] = 1.0

        result = run_funding_sensitivity(
            [row],
            sensitivity_cfg=FundingSensitivityConfig(
                spot_fee_bps_values=(0.0,),
                perp_fee_bps_values=(0.0,),
                slippage_bps_values=(0.0,),
                target_hold_intervals_values=(1.0,),
                max_break_even_hours_values=(24.0,),
            ),
            backtest_cfg=FundingBacktestConfig(
                notional_quote=100.0,
                min_total_score=0.0,
                min_expected_net_carry_bps=0.0,
                max_break_even_hours=24.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.0,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
        )

        scenario = result["scenarios"][0]
        self.assertEqual(result["summary"]["accepted_scenarios"], 0)
        self.assertFalse(result["summary"]["stress_enabled"])
        self.assertIsNone(result["summary"]["stress_accepted_scenarios"])
        self.assertFalse(scenario["research_acceptance"]["accepted"])
        self.assertIn("oos_required", scenario["research_acceptance"]["reasons"])
        self.assertIn("walk_forward_required", scenario["research_acceptance"]["reasons"])
        self.assertIn("stress_required", scenario["research_acceptance"]["reasons"])
        self.assertFalse(scenario["research_acceptance"]["oos_required_passed"])
        self.assertFalse(scenario["research_acceptance"]["walk_forward_required_passed"])
        self.assertFalse(scenario["research_acceptance"]["stress_required_passed"])

    def test_funding_sensitivity_oos_gate_rejects_bad_out_of_sample(self) -> None:
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        rows = []
        for spot, funding, symbol in [
            (_spot(ts=1.0), _funding(ts=1.0, rate=0.002), "HYPE_USDT"),
            (_spot(ts=14_401.0), _funding(ts=14_401.0, rate=0.002), "HYPE_USDT"),
            (_spot(ts=28_801.0), _funding(ts=28_801.0, rate=0.002), "BAD_USDT"),
            (_spot(ts=43_201.0, bid=80.0, ask=80.1), _funding(ts=43_201.0, rate=0.002, bid=129.9, ask=130.0, mark=130.0), "BAD_USDT"),
        ]:
            row = opportunity_from_snapshots(spot, funding, scan_cfg)
            assert row is not None
            row["base"] = symbol.split("_", 1)[0]
            row["spot_symbol"] = symbol
            row["perp_symbol"] = symbol
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_sensitivity(
            rows,
            sensitivity_cfg=FundingSensitivityConfig(
                spot_fee_bps_values=(0.0,),
                perp_fee_bps_values=(0.0,),
                slippage_bps_values=(0.0,),
                target_hold_intervals_values=(1.0,),
                max_break_even_hours_values=(24.0,),
                top_n=5,
            ),
            backtest_cfg=FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_expected_net_carry_bps=0.0,
                max_break_even_hours=24.0,
                max_abs_basis_bps=500.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.5,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
            oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=2, min_oos_rows=2),
        )

        scenario = result["scenarios"][0]
        self.assertTrue(result["summary"]["oos_enabled"])
        self.assertEqual(result["summary"]["oos_accepted_scenarios"], 0)
        self.assertTrue(scenario["acceptance"]["accepted"])
        self.assertFalse(scenario["research_acceptance"]["accepted"])
        self.assertFalse(scenario["research_acceptance"]["oos_accepted"])
        self.assertIn("oos_rejected", scenario["research_acceptance"]["reasons"])
        self.assertEqual(scenario["oos"]["out_of_sample_metrics"]["win_rate"], 0.0)

    def test_funding_sensitivity_walk_forward_gate_rejects_bad_rolling_window(self) -> None:
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        rows = []
        for spot, funding, symbol in [
            (_spot(ts=1.0), _funding(ts=1.0, rate=0.002), "HYPE_USDT"),
            (_spot(ts=14_401.0), _funding(ts=14_401.0, rate=0.002), "HYPE_USDT"),
            (_spot(ts=28_801.0), _funding(ts=28_801.0, rate=0.002), "BAD_USDT"),
            (_spot(ts=43_201.0, bid=80.0, ask=80.1), _funding(ts=43_201.0, rate=0.002, bid=129.9, ask=130.0, mark=130.0), "BAD_USDT"),
        ]:
            row = opportunity_from_snapshots(spot, funding, scan_cfg)
            assert row is not None
            row["base"] = symbol.split("_", 1)[0]
            row["spot_symbol"] = symbol
            row["perp_symbol"] = symbol
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_sensitivity(
            rows,
            sensitivity_cfg=FundingSensitivityConfig(
                spot_fee_bps_values=(0.0,),
                perp_fee_bps_values=(0.0,),
                slippage_bps_values=(0.0,),
                target_hold_intervals_values=(1.0,),
                max_break_even_hours_values=(24.0,),
                top_n=5,
            ),
            backtest_cfg=FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_expected_net_carry_bps=0.0,
                max_break_even_hours=24.0,
                max_abs_basis_bps=500.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.5,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
            walk_forward_cfg=FundingWalkForwardConfig(
                train_rows=2,
                test_rows=2,
                step_rows=2,
                min_windows=1,
                min_accepted_windows=1,
                min_accepted_ratio=1.0,
            ),
        )

        scenario = result["scenarios"][0]
        self.assertTrue(result["summary"]["walk_forward_enabled"])
        self.assertEqual(result["summary"]["walk_forward_accepted_scenarios"], 0)
        self.assertTrue(scenario["acceptance"]["accepted"])
        self.assertFalse(scenario["research_acceptance"]["accepted"])
        self.assertFalse(scenario["research_acceptance"]["walk_forward_accepted"])
        self.assertIn("walk_forward_rejected", scenario["research_acceptance"]["reasons"])
        self.assertEqual(scenario["walk_forward"]["summary"]["accepted_windows"], 0)

    def test_backtest_blocks_entry_when_basis_regime_is_unstable(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(
                    _spot(ts=1.0),
                    _funding(ts=1.0, mark=100.2),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=2.0),
                    _funding(ts=2.0, mark=104.0),
                    BasisScanConfig(),
                ),
                "total_score": 1.0,
            },
        ]

        result = run_funding_backtest(
            rows,  # type: ignore[arg-type]
            FundingBacktestConfig(
                notional_quote=100.0,
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
                min_regime_observations=2,
                max_basis_std_bps=1.0,
            ),
        )

        self.assertEqual(result["metrics"]["total_trades"], 0)

    def test_oos_backtest_requires_in_sample_and_out_of_sample_acceptance(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_oos_backtest(
            rows,
            backtest_cfg=FundingBacktestConfig(
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.0,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
            oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=2, min_oos_rows=2),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["split"]["train_rows"], 2)
        self.assertEqual(result["split"]["oos_rows"], 2)
        self.assertEqual(result["in_sample"]["metrics"]["total_trades"], 1)
        self.assertEqual(result["out_of_sample"]["metrics"]["total_trades"], 1)
        self.assertTrue(result["accepted"])

    def test_oos_backtest_rejects_insufficient_oos_rows(self) -> None:
        row = opportunity_from_snapshots(
            _spot(ts=1.0),
            _funding(ts=1.0),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        assert row is not None

        result = run_funding_oos_backtest(
            [row],
            backtest_cfg=FundingBacktestConfig(),
            acceptance_cfg=FundingAcceptanceConfig(),
            oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=1, min_oos_rows=1),
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["status"], "insufficient_rows")

    def test_oos_backtest_rejects_short_train_and_oos_span(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 2.0, 3.0, 4.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.01), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_oos_backtest(
            rows,
            backtest_cfg=FundingBacktestConfig(
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.0,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
            oos_cfg=FundingOosConfig(
                train_fraction=0.5,
                min_train_rows=2,
                min_oos_rows=2,
                min_train_span_hours=1.0,
                min_oos_span_hours=1.0,
            ),
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["coverage_acceptance"]["accepted"])
        self.assertIn("min_train_span_hours", result["coverage_acceptance"]["reasons"])
        self.assertIn("min_oos_span_hours", result["coverage_acceptance"]["reasons"])
        self.assertLess(result["coverage"]["train_span_hours"], 1.0)
        self.assertLess(result["coverage"]["oos_span_hours"], 1.0)

    def test_walk_forward_accepts_multiple_passing_oos_windows(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0, 57_601.0, 72_001.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_walk_forward_backtest(
            rows,
            backtest_cfg=FundingBacktestConfig(
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.0,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
            walk_cfg=FundingWalkForwardConfig(
                train_rows=2,
                test_rows=2,
                step_rows=2,
                min_windows=2,
                min_accepted_windows=2,
                min_accepted_ratio=1.0,
            ),
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["summary"]["windows"], 2)
        self.assertEqual(result["summary"]["accepted_windows"], 2)
        self.assertEqual(result["windows"][0]["test"]["metrics"]["total_trades"], 1)

    def test_walk_forward_rejects_when_too_few_windows_pass(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)

        result = run_funding_walk_forward_backtest(
            rows,
            backtest_cfg=FundingBacktestConfig(
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_total_score=0.0,
            ),
            acceptance_cfg=FundingAcceptanceConfig(
                min_trades=1,
                min_win_rate=0.0,
                min_expectancy_quote=-1e9,
                min_net_pnl_quote=-1e9,
                max_drawdown_quote=1e9,
                min_profit_factor=0.0,
            ),
            walk_cfg=FundingWalkForwardConfig(
                train_rows=2,
                test_rows=2,
                step_rows=2,
                min_windows=2,
                min_accepted_windows=2,
                min_accepted_ratio=1.0,
            ),
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["summary"]["windows"], 1)
        self.assertEqual(result["summary"]["accepted_windows"], 1)
        self.assertIn("min_windows", result["reasons"])

    def test_rank_and_load_funding_rows_from_json_and_jsonl(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            scan = Path(tmp) / "scan.json"
            rank = Path(tmp) / "rank.json"
            scan.write_text(json.dumps({"rows": [row]}, ensure_ascii=False), encoding="utf-8")
            payload = rank_funding_file(scan, output_path=rank, top_n=1)
            self.assertEqual(payload["summary"]["ranked_rows"], 1)
            self.assertEqual(json.loads(rank.read_text(encoding="utf-8"))["rows"][0]["rank"], 1)

            jsonl = Path(tmp) / "collect.jsonl"
            jsonl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(len(load_funding_rows(jsonl)), 1)

    def test_rank_adds_funding_persistence_metrics(self) -> None:
        stable_rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0, rate=0.0002), BasisScanConfig()),
                "total_score": 10.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=0.00015), BasisScanConfig()),
                "total_score": 10.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=3.0), _funding(ts=3.0, rate=0.00018), BasisScanConfig()),
                "total_score": 10.0,
            },
        ]
        spike_rows = [
            {
                **opportunity_from_snapshots(
                    _spot(ts=1.0, bid=90.0, ask=90.1),
                    _funding(ts=1.0, rate=-0.0001, bid=90.2, ask=90.3),
                    BasisScanConfig(),
                ),
                "exchange": "gateio",
                "base": "SPIKE",
                "spot_symbol": "SPIKE_USDT",
                "perp_symbol": "SPIKE_USDT",
                "total_score": 9.0,
            },
            {
                **opportunity_from_snapshots(
                    _spot(ts=3.0, bid=90.0, ask=90.1),
                    _funding(ts=3.0, rate=0.0009, bid=90.2, ask=90.3),
                    BasisScanConfig(),
                ),
                "exchange": "gateio",
                "base": "SPIKE",
                "spot_symbol": "SPIKE_USDT",
                "perp_symbol": "SPIKE_USDT",
                "total_score": 19.0,
            },
        ]
        rows = [*stable_rows, *spike_rows]

        ranked = rank_funding_rows(
            rows,  # type: ignore[arg-type]
            top_n=2,
            cfg=FundingRankConfig(
                min_funding_observations=2,
                min_funding_positive_ratio=0.75,
            ),
        )

        self.assertEqual(ranked[0]["spot_symbol"], "HYPE_USDT")
        self.assertEqual(ranked[0]["funding_observations"], 3)
        self.assertEqual(ranked[0]["funding_positive_ratio"], 1.0)
        self.assertGreater(ranked[0]["funding_persistence_score"], 0)
        self.assertTrue(ranked[0]["persistence_eligible"])
        self.assertIn("funding_positive_ratio_below_min", ranked[1]["persistence_reasons"])
        self.assertFalse(ranked[1]["persistence_eligible"])

    def test_rank_file_accepts_persistence_filters(self) -> None:
        row_a = {
            **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0, rate=0.0001), BasisScanConfig()),
            "total_score": 5.0,
        }
        row_b = {
            **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=0.0001), BasisScanConfig()),
            "total_score": 6.0,
        }
        assert row_a is not None
        assert row_b is not None
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            out = Path(tmp) / "rank.json"
            src.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in [row_a, row_b]) + "\n",
                encoding="utf-8",
            )
            payload = rank_funding_file(
                src,
                output_path=out,
                top_n=5,
                cfg=FundingRankConfig(min_funding_observations=2, min_funding_positive_ratio=1.0),
            )
            self.assertEqual(payload["summary"]["markets_analyzed"], 1)
            self.assertEqual(payload["summary"]["persistence_eligible"], 1)
            self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["rows"][0]["persistence_eligible"])

    def test_rank_marks_basis_below_min_ineligible(self) -> None:
        good = {
            **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0, mark=100.25), BasisScanConfig()),
            "base": "GOOD",
            "spot_symbol": "GOOD_USDT",
            "perp_symbol": "GOOD_USDT",
            "total_score": 1.0,
        }
        bad = {
            **opportunity_from_snapshots(
                _spot(ts=2.0, bid=100.0, ask=100.1),
                _funding(ts=2.0, mark=99.0, bid=98.9, ask=99.1),
                BasisScanConfig(),
            ),
            "base": "BAD",
            "spot_symbol": "BAD_USDT",
            "perp_symbol": "BAD_USDT",
            "total_score": 100.0,
        }
        assert good is not None
        assert bad is not None

        ranked = rank_funding_rows(
            [bad, good],  # type: ignore[list-item]
            top_n=2,
            cfg=FundingRankConfig(min_basis_bps=0.0),
        )

        self.assertEqual(ranked[0]["base"], "GOOD")
        self.assertTrue(ranked[0]["rank_eligible"])
        self.assertEqual(ranked[1]["base"], "BAD")
        self.assertFalse(ranked[1]["rank_eligible"])
        self.assertIn("basis_below_min", ranked[1]["rank_reasons"])

    def test_rank_marks_expected_carry_below_min_ineligible(self) -> None:
        good = {
            **opportunity_from_snapshots(
                _spot(ts=1.0),
                _funding(ts=1.0, rate=0.01, mark=100.25),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "GOOD",
            "spot_symbol": "GOOD_USDT",
            "perp_symbol": "GOOD_USDT",
            "total_score": 1.0,
        }
        bad = {
            **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=0.0001, mark=100.25), BasisScanConfig()),
            "base": "BAD",
            "spot_symbol": "BAD_USDT",
            "perp_symbol": "BAD_USDT",
            "total_score": 100.0,
        }
        assert good is not None
        assert bad is not None
        self.assertGreater(good["expected_net_carry_bps"], 0.0)
        self.assertLess(bad["expected_net_carry_bps"], 0.0)

        ranked = rank_funding_rows(
            [bad, good],  # type: ignore[list-item]
            top_n=2,
            cfg=FundingRankConfig(min_expected_net_carry_bps=0.0),
        )

        self.assertEqual(ranked[0]["base"], "GOOD")
        self.assertTrue(ranked[0]["rank_eligible"])
        self.assertEqual(ranked[1]["base"], "BAD")
        self.assertFalse(ranked[1]["rank_eligible"])
        self.assertIn("expected_edge_below_min", ranked[1]["rank_reasons"])

    def test_rank_and_backtest_can_filter_risk_adjusted_edge_below_min(self) -> None:
        good = {
            **opportunity_from_snapshots(
                _spot(ts=1.0, ask=100.01),
                _funding(ts=1.0, rate=0.002, bid=100.2, ask=100.21, mark=100.2),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "GOOD",
            "spot_symbol": "GOOD_USDT",
            "perp_symbol": "GOOD_USDT",
            "total_score": 1.0,
        }
        bad = {
            **opportunity_from_snapshots(
                _spot(ts=2.0),
                _funding(ts=2.0, rate=0.001, mark=100.25),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "BAD",
            "spot_symbol": "BAD_USDT",
            "perp_symbol": "BAD_USDT",
            "total_score": 100.0,
        }
        assert good is not None
        assert bad is not None

        cfg = FundingRankConfig(
            min_expected_net_carry_bps=0.0,
            min_risk_adjusted_edge_bps=1.0,
            basis_risk_multiplier=0.0,
            spread_risk_multiplier=1.0,
        )
        ranked = rank_funding_rows([bad, good], top_n=2, cfg=cfg)  # type: ignore[list-item]

        self.assertEqual(ranked[0]["base"], "GOOD")
        self.assertTrue(ranked[0]["rank_eligible"])
        self.assertGreater(ranked[0]["risk_adjusted_edge_bps"], 1.0)
        self.assertEqual(ranked[1]["base"], "BAD")
        self.assertFalse(ranked[1]["rank_eligible"])
        self.assertLess(ranked[1]["risk_adjusted_edge_bps"], 1.0)
        self.assertIn("risk_adjusted_edge_below_min", ranked[1]["rank_reasons"])

        backtest = run_funding_backtest(
            [bad],  # type: ignore[list-item]
            FundingBacktestConfig(
                spot_fee_bps=0.0,
                perp_fee_bps=0.0,
                slippage_bps=0.0,
                min_expected_net_carry_bps=0.0,
                min_risk_adjusted_edge_bps=1.0,
                basis_risk_multiplier=0.0,
                spread_risk_multiplier=1.0,
            ),
        )
        self.assertEqual(backtest["metrics"]["total_trades"], 0)

    def test_funding_gate_report_summarizes_rejection_reasons_and_distributions(self) -> None:
        good = {
            **opportunity_from_snapshots(
                _spot(ts=1.0, ask=100.01),
                _funding(ts=1.0, rate=0.002, bid=100.2, ask=100.21, mark=100.2),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "GOOD",
            "spot_symbol": "GOOD_USDT",
            "perp_symbol": "GOOD_USDT",
            "total_score": 1.0,
        }
        bad = {
            **opportunity_from_snapshots(
                _spot(ts=2.0),
                _funding(ts=2.0, rate=0.001, mark=100.25),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "BAD",
            "spot_symbol": "BAD_USDT",
            "perp_symbol": "BAD_USDT",
            "total_score": 100.0,
        }
        assert good is not None
        assert bad is not None

        report = funding_gate_report(
            [bad, good],  # type: ignore[list-item]
            top_n=2,
            cfg=FundingRankConfig(
                min_expected_net_carry_bps=0.0,
                min_risk_adjusted_edge_bps=1.0,
                basis_risk_multiplier=0.0,
                spread_risk_multiplier=1.0,
            ),
        )

        self.assertEqual(report["summary"]["markets_analyzed"], 2)
        self.assertEqual(report["summary"]["rank_eligible"], 1)
        self.assertEqual(report["summary"]["reason_counts"]["risk_adjusted_edge_below_min"], 1)
        self.assertEqual(report["summary"]["pass_counts"]["risk_adjusted_edge_pass"], 1)
        self.assertEqual(report["summary"]["pass_counts"]["funding_gap_pass"], 1)
        self.assertEqual(report["distributions"]["risk_adjusted_edge_bps"]["count"], 2)
        self.assertEqual(report["distributions"]["funding_gap_bps_per_interval_for_risk_edge"]["count"], 2)
        self.assertEqual(report["top_by_risk_adjusted_edge"][0]["base"], "GOOD")
        self.assertIn("required_funding_bps_per_interval_for_risk_edge", report["top_by_risk_adjusted_edge"][0])
        self.assertGreater(report["top_by_risk_adjusted_edge"][0]["funding_gap_bps_per_interval_for_risk_edge"], 0.0)
        self.assertEqual(report["top_by_expected_net_carry"][0]["base"], "GOOD")
        self.assertEqual(report["top_by_funding_gap"][0]["base"], "GOOD")
        self.assertIn("required_hold_hours_for_risk_edge", report["top_by_funding_gap"][0])

    def test_funding_regime_report_exposes_volume_and_regime_blockers(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 2.0]:
            row = opportunity_from_snapshots(
                _spot(ts=ts, ask=100.01),
                _funding(ts=ts, rate=0.001, bid=100.2, ask=100.21, mark=100.2, volume_quote=100.0),
                scan_cfg,
            )
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)

        report = funding_regime_report(
            rows,
            top_n=1,
            cfg=FundingRankConfig(
                min_funding_observations=2,
                min_funding_positive_ratio=1.0,
                min_regime_observations=3,
                min_perp_volume_24h_quote=1_000.0,
                min_expected_net_carry_bps=0.0,
            ),
        )

        self.assertEqual(report["summary"]["markets"], 1)
        self.assertEqual(report["summary"]["eligible_markets"], 0)
        market = report["top_markets"][0]
        self.assertFalse(market["regime_pass"])
        self.assertTrue(market["persistence_pass"])
        self.assertEqual(market["observations"], 2)
        self.assertIn("regime_observations_below_min", market["regime_reasons"])
        self.assertIn("perp_volume_low", market["regime_reasons"])
        self.assertIn("perp_volume_regime_low", market["regime_reasons"])
        self.assertEqual(report["summary"]["reason_counts"]["regime_observations_below_min"], 1)

    def test_funding_frontier_report_shows_liquidity_relaxed_near_miss(self) -> None:
        low_liquidity = {
            **opportunity_from_snapshots(
                _spot(ts=1.0, bid_qty=1.0, ask_qty=1.0, ask=100.01),
                _funding(ts=1.0, rate=0.002, bid=100.2, ask=100.21, mark=100.2),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "LOWLIQ",
            "spot_symbol": "LOWLIQ_USDT",
            "perp_symbol": "LOWLIQ_USDT",
            "total_score": 1.0,
        }
        assert low_liquidity is not None

        report = funding_frontier_report(
            [low_liquidity],  # type: ignore[list-item]
            top_n=1,
            cfg=FundingRankConfig(
                min_expected_net_carry_bps=0.0,
                min_risk_adjusted_edge_bps=0.0,
                basis_risk_multiplier=0.0,
                spread_risk_multiplier=0.0,
                max_break_even_hours=24.0,
                min_spot_top_notional_quote=500.0,
            ),
        )

        self.assertEqual(report["summary"]["strict_rank_eligible"], 0)
        self.assertEqual(report["summary"]["liquidity_relaxed_rank_eligible"], 1)
        self.assertEqual(report["summary"]["economics_relaxed_rank_eligible"], 0)
        self.assertEqual(report["summary"]["primary_blocker_counts"]["liquidity"], 1)
        self.assertEqual(report["top_frontier"][0]["primary_blocker"], "liquidity")
        self.assertGreater(report["top_frontier"][0]["spot_top_liquidity_gap_quote"], 0.0)
        self.assertGreater(report["top_frontier"][0]["funding_gap_bps_per_interval_for_risk_edge"], 0.0)

    def test_funding_decision_report_waits_until_collector_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": False, "cycles": 2, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertFalse(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "wait_for_final_dataset")
        self.assertIn("collector_not_ready", report["summary"]["reasons"])

    def test_funding_decision_report_accepts_only_full_metric_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )
            postprocess = base / "postprocess.json"
            postprocess.write_text(
                json.dumps({"ok": True, "research_acceptance": {"accepted": True, "reasons": []}}),
                encoding="utf-8",
            )
            gate = base / "gate.json"
            gate.write_text(json.dumps({"summary": {"rank_eligible": 1}}), encoding="utf-8")
            regime = base / "regime.json"
            regime.write_text(
                json.dumps(
                    {
                        "summary": {
                            "eligible_markets": 1,
                            "source_pass": 1,
                            "persistence_pass": 1,
                            "regime_pass": 1,
                            "liquidity_pass": 1,
                            "economics_pass": 1,
                            "reason_counts": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            frontier = base / "frontier.json"
            frontier.write_text(json.dumps({"summary": {"strict_rank_eligible": 1, "funding_gap_pass": 1}}), encoding="utf-8")
            sensitivity = base / "sensitivity.json"
            sensitivity.write_text(
                json.dumps(
                    {
                        "summary": {
                            "accepted_scenarios": 1,
                            "oos_enabled": True,
                            "oos_accepted_scenarios": 1,
                            "walk_forward_enabled": True,
                            "walk_forward_accepted_scenarios": 1,
                            "stress_enabled": True,
                            "stress_assumptions_passed": True,
                            "stress_accepted_scenarios": 1,
                            "best_net_pnl_quote": 10.0,
                            "best_oos_net_pnl_quote": 5.0,
                            "best_walk_forward_avg_test_net_pnl_quote": 2.0,
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                postprocess_report_path=postprocess,
                gate_report_path=gate,
                regime_report_path=regime,
                frontier_report_path=frontier,
                sensitivity_report_path=sensitivity,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertTrue(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "paper_forward_candidate")
        self.assertEqual(report["summary"]["next_action"], "run_funding_paper_plan")
        self.assertEqual(report["summary"]["regime_eligible_markets"], 1)
        self.assertEqual(report["summary"]["regime_liquidity_pass"], 1)
        self.assertEqual(report["summary"]["regime_economics_pass"], 1)
        self.assertEqual(report["summary"]["sensitivity_stress_accepted_scenarios"], 1)

    def test_funding_decision_report_rejects_missing_regime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )
            postprocess = base / "postprocess.json"
            postprocess.write_text(
                json.dumps({"ok": True, "research_acceptance": {"accepted": True, "reasons": []}}),
                encoding="utf-8",
            )
            gate = base / "gate.json"
            gate.write_text(json.dumps({"summary": {"rank_eligible": 1}}), encoding="utf-8")
            frontier = base / "frontier.json"
            frontier.write_text(json.dumps({"summary": {"strict_rank_eligible": 1, "funding_gap_pass": 1}}), encoding="utf-8")
            sensitivity = base / "sensitivity.json"
            sensitivity.write_text(
                json.dumps(
                    {
                        "summary": {
                            "accepted_scenarios": 1,
                            "oos_enabled": True,
                            "oos_accepted_scenarios": 1,
                            "walk_forward_enabled": True,
                            "walk_forward_accepted_scenarios": 1,
                            "stress_enabled": True,
                            "stress_assumptions_passed": True,
                            "stress_accepted_scenarios": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                postprocess_report_path=postprocess,
                gate_report_path=gate,
                frontier_report_path=frontier,
                sensitivity_report_path=sensitivity,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertFalse(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "research_rework_required")
        self.assertIn("missing:regime_report", report["summary"]["reasons"])
        self.assertIn("regime_eligible_markets_zero", report["summary"]["reasons"])

    def test_funding_decision_report_rejects_missing_postprocess_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )
            gate = base / "gate.json"
            gate.write_text(json.dumps({"summary": {"rank_eligible": 1}}), encoding="utf-8")
            frontier = base / "frontier.json"
            frontier.write_text(json.dumps({"summary": {"strict_rank_eligible": 1, "funding_gap_pass": 1}}), encoding="utf-8")
            sensitivity = base / "sensitivity.json"
            sensitivity.write_text(
                json.dumps(
                    {
                        "summary": {
                            "accepted_scenarios": 1,
                            "oos_enabled": True,
                            "oos_accepted_scenarios": 1,
                            "walk_forward_enabled": True,
                            "walk_forward_accepted_scenarios": 1,
                            "stress_enabled": True,
                            "stress_assumptions_passed": True,
                            "stress_accepted_scenarios": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                gate_report_path=gate,
                frontier_report_path=frontier,
                sensitivity_report_path=sensitivity,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertFalse(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "research_rework_required")
        self.assertIn("missing:postprocess_report", report["summary"]["reasons"])

    def test_funding_decision_report_rejects_sensitivity_without_stress_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )
            postprocess = base / "postprocess.json"
            postprocess.write_text(
                json.dumps({"ok": True, "research_acceptance": {"accepted": True, "reasons": []}}),
                encoding="utf-8",
            )
            gate = base / "gate.json"
            gate.write_text(json.dumps({"summary": {"rank_eligible": 1}}), encoding="utf-8")
            frontier = base / "frontier.json"
            frontier.write_text(json.dumps({"summary": {"strict_rank_eligible": 1, "funding_gap_pass": 1}}), encoding="utf-8")
            sensitivity = base / "sensitivity.json"
            sensitivity.write_text(
                json.dumps(
                    {
                        "summary": {
                            "accepted_scenarios": 1,
                            "oos_enabled": True,
                            "oos_accepted_scenarios": 1,
                            "walk_forward_enabled": True,
                            "walk_forward_accepted_scenarios": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                postprocess_report_path=postprocess,
                gate_report_path=gate,
                frontier_report_path=frontier,
                sensitivity_report_path=sensitivity,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertFalse(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "research_rework_required")
        self.assertIn("sensitivity_stress_not_enabled", report["summary"]["reasons"])

    def test_funding_decision_report_rejects_sensitivity_without_oos_walk_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )
            postprocess = base / "postprocess.json"
            postprocess.write_text(
                json.dumps({"ok": True, "research_acceptance": {"accepted": True, "reasons": []}}),
                encoding="utf-8",
            )
            gate = base / "gate.json"
            gate.write_text(json.dumps({"summary": {"rank_eligible": 1}}), encoding="utf-8")
            frontier = base / "frontier.json"
            frontier.write_text(json.dumps({"summary": {"strict_rank_eligible": 1, "funding_gap_pass": 1}}), encoding="utf-8")
            sensitivity = base / "sensitivity.json"
            sensitivity.write_text(
                json.dumps(
                    {
                        "summary": {
                            "accepted_scenarios": 1,
                            "stress_enabled": True,
                            "stress_assumptions_passed": True,
                            "stress_accepted_scenarios": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                postprocess_report_path=postprocess,
                gate_report_path=gate,
                frontier_report_path=frontier,
                sensitivity_report_path=sensitivity,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertFalse(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "research_rework_required")
        self.assertIn("sensitivity_oos_not_enabled", report["summary"]["reasons"])
        self.assertIn("sensitivity_walk_forward_not_enabled", report["summary"]["reasons"])

    def test_funding_decision_report_rejects_failed_postprocess_research_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rows = base / "collect.jsonl"
            rows.write_text(
                json.dumps({"exchange": "gateio", "base": "HYPE", "cycle": 1, "ts": 1.0}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest = base / "collect.manifest.json"
            manifest.write_text(
                json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1, "errors": 0}),
                encoding="utf-8",
            )
            postprocess = base / "postprocess.json"
            postprocess.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "research_acceptance": {
                            "accepted": False,
                            "reasons": ["full_backtest_rejected"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            gate = base / "gate.json"
            gate.write_text(json.dumps({"summary": {"rank_eligible": 1}}), encoding="utf-8")
            frontier = base / "frontier.json"
            frontier.write_text(json.dumps({"summary": {"strict_rank_eligible": 1, "funding_gap_pass": 1}}), encoding="utf-8")
            sensitivity = base / "sensitivity.json"
            sensitivity.write_text(
                json.dumps(
                    {
                        "summary": {
                            "accepted_scenarios": 1,
                            "oos_enabled": True,
                            "oos_accepted_scenarios": 1,
                            "walk_forward_enabled": True,
                            "walk_forward_accepted_scenarios": 1,
                            "stress_enabled": True,
                            "stress_assumptions_passed": True,
                            "stress_accepted_scenarios": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = funding_decision_report(
                rows,
                manifest_path=manifest,
                postprocess_report_path=postprocess,
                gate_report_path=gate,
                frontier_report_path=frontier,
                sensitivity_report_path=sensitivity,
                data_quality_cfg=FundingDataQualityConfig(min_rows=1, min_markets=1, min_completed_cycles=1),
            )

        self.assertFalse(report["summary"]["accepted"])
        self.assertEqual(report["summary"]["verdict"], "research_rework_required")
        self.assertIn("postprocess_research_not_accepted", report["summary"]["reasons"])
        self.assertIn("postprocess:full_backtest_rejected", report["summary"]["reasons"])

    def test_funding_progress_report_summarizes_cycle_trend(self) -> None:
        first = opportunity_from_snapshots(
            _spot(ts=1.0, bid_qty=1.0, ask_qty=1.0),
            _funding(ts=1.0, rate=0.001, volume_quote=100_000),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        latest = opportunity_from_snapshots(
            _spot(ts=2.0, bid_qty=10.0, ask_qty=10.0),
            _funding(ts=2.0, rate=0.002, volume_quote=1_000_000),
            BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
        )
        assert first is not None
        assert latest is not None
        first.update({"base": "AAA", "cycle": 1})
        latest.update({"base": "AAA", "cycle": 2})

        report = funding_progress_report(
            [first, latest],  # type: ignore[list-item]
            manifest={
                "final": False,
                "completed_cycles": 2,
                "errors": 1,
                "cycle_summaries": [
                    {"cycle": 1, "rows": 1, "eligible": 1, "errors": 1},
                    {"cycle": 2, "rows": 1, "eligible": 1, "errors": 0},
                ],
            },
            cfg=FundingRankConfig(min_expected_net_carry_bps=0.0),
        )

        self.assertEqual(report["summary"]["cycles"], 2)
        self.assertEqual(report["summary"]["latest_cycle"], 2)
        self.assertEqual(report["summary"]["manifest_completed_cycles"], 2)
        self.assertGreater(report["summary"]["best_gap_delta_bps"], 0.0)
        self.assertGreater(report["summary"]["avg_spot_top_notional_delta_quote"], 0.0)
        self.assertEqual(report["cycles"][0]["manifest_errors"], 1)
        self.assertEqual(report["cycles"][1]["manifest_errors"], 0)
        self.assertEqual(report["cycles"][1]["best_base"], "AAA")

    def test_rank_marks_long_break_even_horizon_ineligible(self) -> None:
        good = {
            **opportunity_from_snapshots(
                _spot(ts=1.0),
                _funding(ts=1.0, rate=0.01, mark=100.25),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            ),
            "base": "GOOD",
            "spot_symbol": "GOOD_USDT",
            "perp_symbol": "GOOD_USDT",
            "total_score": 1.0,
        }
        bad = {
            **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=0.0001, mark=100.25), BasisScanConfig()),
            "base": "BAD",
            "spot_symbol": "BAD_USDT",
            "perp_symbol": "BAD_USDT",
            "total_score": 100.0,
        }
        assert good is not None
        assert bad is not None
        self.assertGreater(bad["break_even_hours"], 24.0)

        ranked = rank_funding_rows(
            [bad, good],  # type: ignore[list-item]
            top_n=2,
            cfg=FundingRankConfig(max_break_even_hours=24.0),
        )

        self.assertEqual(ranked[0]["base"], "GOOD")
        self.assertTrue(ranked[0]["rank_eligible"])
        self.assertEqual(ranked[1]["base"], "BAD")
        self.assertFalse(ranked[1]["rank_eligible"])
        self.assertIn("break_even_horizon_too_long", ranked[1]["rank_reasons"])

    def test_rank_marks_thin_spot_top_liquidity_ineligible(self) -> None:
        good = {
            **opportunity_from_snapshots(_spot(ts=1.0, bid_qty=10.0, ask_qty=10.0), _funding(ts=1.0), BasisScanConfig()),
            "base": "GOOD",
            "spot_symbol": "GOOD_USDT",
            "perp_symbol": "GOOD_USDT",
            "total_score": 1.0,
        }
        bad = {
            **opportunity_from_snapshots(_spot(ts=2.0, bid_qty=0.01, ask_qty=0.01), _funding(ts=2.0), BasisScanConfig()),
            "base": "BAD",
            "spot_symbol": "BAD_USDT",
            "perp_symbol": "BAD_USDT",
            "total_score": 100.0,
        }
        assert good is not None
        assert bad is not None

        ranked = rank_funding_rows(
            [bad, good],  # type: ignore[list-item]
            top_n=2,
            cfg=FundingRankConfig(min_spot_top_notional_quote=100.0),
        )

        self.assertEqual(ranked[0]["base"], "GOOD")
        self.assertTrue(ranked[0]["rank_eligible"])
        self.assertEqual(ranked[1]["base"], "BAD")
        self.assertFalse(ranked[1]["rank_eligible"])
        self.assertIn("spot_top_liquidity_low", ranked[1]["rank_reasons"])

    def test_funding_postprocess_blocks_not_final_manifest(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": False, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                require_final=True,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "not_final")
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())

    def test_funding_postprocess_blocks_final_manifest_when_line_count_mismatches(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 2, "rows": 2}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                require_final=True,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "line_count_mismatch")
            self.assertEqual(result["collect_status"]["line_count"], 1)
            self.assertEqual(result["collect_status"]["manifest_rows"], 2)
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())

    def test_funding_postprocess_blocks_low_quality_collect_before_artifacts(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "final": True,
                        "cycles": 1,
                        "completed_cycles": 1,
                        "rows": 1,
                        "errors": 10,
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                data_quality_cfg=FundingDataQualityConfig(
                    min_rows=1,
                    min_markets=1,
                    min_completed_cycles=1,
                    max_error_rate=0.10,
                ),
                require_final=True,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "data_quality_rejected")
            self.assertIn("max_error_rate", result["data_quality"]["reasons"])
            self.assertGreater(result["data_quality"]["metrics"]["error_rate"], 0.10)
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())

    def test_funding_postprocess_blocks_duplicate_cycle_market_rows(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        duplicate_a = {**row, "cycle": 1}
        duplicate_b = {**row, "cycle": 1}
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            src.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [duplicate_a, duplicate_b]) + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "final": True,
                        "cycles": 2,
                        "completed_cycles": 2,
                        "rows": 2,
                        "errors": 0,
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                data_quality_cfg=FundingDataQualityConfig(
                    min_rows=2,
                    min_markets=1,
                    min_completed_cycles=2,
                    min_unique_cycles=2,
                    max_error_rate=1.0,
                    max_cycle_market_duplicate_rate=0.0,
                ),
                require_final=True,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "data_quality_rejected")
            self.assertIn("min_unique_cycles", result["data_quality"]["reasons"])
            self.assertIn("max_cycle_market_duplicate_rate", result["data_quality"]["reasons"])
            self.assertEqual(result["data_quality"]["metrics"]["unique_cycles"], 1)
            self.assertEqual(result["data_quality"]["metrics"]["cycle_market_duplicates"], 1)
            self.assertEqual(result["data_quality"]["metrics"]["cycle_market_duplicate_rate"], 0.5)
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())

    def test_funding_postprocess_blocks_missing_required_row_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            rows = [
                {"ts": 1.0, "exchange": "gateio", "spot_symbol": "HYPE_USDT", "perp_symbol": "HYPE_USDT", "cycle": 1},
                {
                    "ts": 2.0,
                    "exchange": "gateio",
                    "spot_symbol": "HYPE_USDT",
                    "perp_symbol": "HYPE_USDT",
                    "cycle": 2,
                    "spot_top_min_notional_quote": 1000.0,
                },
            ]
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 2, "rows": 2}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                data_quality_cfg=FundingDataQualityConfig(
                    min_rows=2,
                    min_markets=1,
                    min_completed_cycles=2,
                    required_row_fields=("spot_top_min_notional_quote",),
                    min_required_row_field_presence=1.0,
                ),
                require_final=True,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "data_quality_rejected")
            self.assertIn("required_row_field:spot_top_min_notional_quote", result["data_quality"]["reasons"])
            self.assertEqual(result["data_quality"]["metrics"]["required_row_field_presence"]["spot_top_min_notional_quote"], 0.5)
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())

    def test_funding_collect_status_reports_stale_and_line_mismatch(self) -> None:
        from basis import funding_collect_status

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            src.write_text("{}\n{}\n", encoding="utf-8")
            old_ts = time.time() - 1_000
            os.utime(src, (old_ts, old_ts))
            manifest.write_text(
                json.dumps(
                    {
                        "final": False,
                        "cycles": 10,
                        "completed_cycles": 2,
                        "rows": 3,
                        "errors": 1,
                    }
                ),
                encoding="utf-8",
            )

            status = funding_collect_status(src, manifest_path=manifest, stale_after_sec=300, now_ts=time.time())

            self.assertEqual(status["status"], "stale")
            self.assertFalse(status["ready_for_postprocess"])
            self.assertFalse(status["line_count_matches_manifest"])
            self.assertEqual(status["line_count"], 2)
            self.assertEqual(status["manifest_rows"], 3)
            self.assertEqual(status["remaining_cycles"], 8)

    def test_funding_collect_status_reports_eta_from_cycle_timestamps(self) -> None:
        from basis import funding_collect_status

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            src.write_text("{}\n{}\n", encoding="utf-8")
            os.utime(src, (1_600.0, 1_600.0))
            manifest.write_text(
                json.dumps(
                    {
                        "final": False,
                        "cycles": 5,
                        "completed_cycles": 2,
                        "rows": 2,
                        "errors": 0,
                        "duration_sec": 600.0,
                        "cycle_summaries": [
                            {"cycle": 1, "ts": 1_000.0},
                            {"cycle": 2, "ts": 1_300.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            status = funding_collect_status(src, manifest_path=manifest, stale_after_sec=900, now_ts=1_500.0)

            self.assertEqual(status["status"], "running_or_waiting")
            self.assertEqual(status["cycle_interval_estimate_sec"], 300.0)
            self.assertEqual(status["estimated_next_cycle_ts"], 1_600.0)
            self.assertEqual(status["estimated_next_cycle_in_sec"], 100.0)
            self.assertEqual(status["eta_sec"], 900.0)

    def test_funding_collect_status_reports_strict_readiness_quality_reasons(self) -> None:
        from basis import funding_collect_status

        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig()),
                "cycle": 1,
            },
            {
                **opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0), BasisScanConfig()),
                "cycle": 1,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "final": False,
                        "cycles": 288,
                        "completed_cycles": 1,
                        "rows": 2,
                        "errors": 1,
                    }
                ),
                encoding="utf-8",
            )

            status = funding_collect_status(
                src,
                manifest_path=manifest,
                stale_after_sec=900,
                now_ts=time.time(),
                data_quality_cfg=FundingDataQualityConfig(
                    min_rows=3,
                    min_markets=2,
                    min_completed_cycles=2,
                    min_unique_cycles=2,
                    min_avg_rows_per_cycle=3.0,
                    min_min_rows_per_cycle=3,
                    max_error_rate=0.2,
                    max_cycle_market_duplicate_rate=0.0,
                    required_row_fields=("missing_required_field",),
                    min_required_row_field_presence=1.0,
                ),
            )

            self.assertEqual(status["status"], "running_or_waiting")
            self.assertFalse(status["ready_for_postprocess"])
            self.assertFalse(status["readiness"]["accepted"])
            self.assertIn("status_not_final", status["readiness"]["reasons"])
            self.assertIn("data_quality:min_rows", status["readiness"]["reasons"])
            self.assertIn("data_quality:min_markets", status["readiness"]["reasons"])
            self.assertIn("data_quality:min_completed_cycles", status["readiness"]["reasons"])
            self.assertIn("data_quality:min_unique_cycles", status["readiness"]["reasons"])
            self.assertIn("data_quality:min_avg_rows_per_cycle", status["readiness"]["reasons"])
            self.assertIn("data_quality:min_min_rows_per_cycle", status["readiness"]["reasons"])
            self.assertIn("data_quality:max_error_rate", status["readiness"]["reasons"])
            self.assertIn("data_quality:max_cycle_market_duplicate_rate", status["readiness"]["reasons"])
            self.assertIn("data_quality:required_row_field:missing_required_field", status["readiness"]["reasons"])
            self.assertEqual(status["data_quality"]["metrics"]["rows"], 2)
            self.assertEqual(status["data_quality"]["metrics"]["unique_cycles"], 1)
            self.assertEqual(status["data_quality"]["metrics"]["avg_rows_per_cycle"], 2.0)
            self.assertEqual(status["data_quality"]["metrics"]["min_rows_per_cycle"], 2)
            self.assertEqual(status["data_quality"]["metrics"]["cycle_market_duplicates"], 1)
            self.assertEqual(status["data_quality"]["metrics"]["required_row_field_presence"]["missing_required_field"], 0.0)

    def test_funding_postprocess_runs_rank_and_backtest_for_final_manifest(self) -> None:
        rows = [
            {
                **opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig()),
                "total_score": 1.0,
            },
            {
                **opportunity_from_snapshots(_spot(ts=14_401.0), _funding(ts=14_401.0), BasisScanConfig()),
                "total_score": 1.0,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 2, "rows": 2}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(min_funding_observations=2),
                backtest_cfg=FundingBacktestConfig(
                    spot_fee_bps=0.0,
                    perp_fee_bps=0.0,
                    slippage_bps=0.0,
                    min_funding_observations=2,
                ),
                acceptance_cfg=FundingAcceptanceConfig(
                    min_trades=1,
                    min_win_rate=0.0,
                    min_expectancy_quote=-1e9,
                    min_net_pnl_quote=-1e9,
                    max_drawdown_quote=1e9,
                    min_profit_factor=0.0,
                ),
                stress_cfg=FundingStressConfig(enabled=False),
                require_final=True,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertTrue(rank_out.exists())
            self.assertTrue(backtest_out.exists())
            self.assertEqual(result["rank_summary"]["ranked_rows"], 1)
            self.assertEqual(result["backtest_metrics"]["total_trades"], 1)
            self.assertTrue(result["acceptance"]["accepted"])
            self.assertFalse(result["research_acceptance"]["accepted"])
            self.assertFalse(result["research_acceptance"]["oos_required_passed"])
            self.assertIn("oos_required", result["research_acceptance"]["reasons"])

    def test_funding_postprocess_requires_stress_gate_for_research_acceptance(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            oos_out = Path(tmp) / "oos.json"
            walk_out = Path(tmp) / "walk.json"
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 4, "rows": 4}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(
                    spot_fee_bps=0.0,
                    perp_fee_bps=0.0,
                    slippage_bps=0.0,
                    min_total_score=0.0,
                ),
                acceptance_cfg=FundingAcceptanceConfig(
                    min_trades=1,
                    min_win_rate=0.0,
                    min_expectancy_quote=-1e9,
                    min_net_pnl_quote=-1e9,
                    max_drawdown_quote=1e9,
                    min_profit_factor=0.0,
                ),
                stress_cfg=FundingStressConfig(enabled=False),
                oos_output_path=oos_out,
                oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=2, min_oos_rows=2),
                require_final=True,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(oos_out.exists())
            self.assertIn("oos", result)
            self.assertTrue(result["oos"]["accepted"])
            self.assertFalse(result["research_acceptance"]["accepted"])
            self.assertIn("stress_required", result["research_acceptance"]["reasons"])
            self.assertFalse(result["research_acceptance"]["stress_required_passed"])
            self.assertEqual(result["oos"]["split"]["train_rows"], 2)
            self.assertEqual(result["oos"]["split"]["oos_rows"], 2)

    def test_funding_postprocess_can_accept_oos_and_stress_for_final_manifest(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            oos_out = Path(tmp) / "oos.json"
            walk_out = Path(tmp) / "walk.json"
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 4, "rows": 4}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(
                    spot_fee_bps=0.0,
                    perp_fee_bps=0.0,
                    slippage_bps=0.0,
                    min_total_score=0.0,
                ),
                acceptance_cfg=FundingAcceptanceConfig(
                    min_trades=1,
                    min_win_rate=0.0,
                    min_expectancy_quote=-1e9,
                    min_net_pnl_quote=-1e9,
                    max_drawdown_quote=1e9,
                    min_profit_factor=0.0,
                ),
                stress_cfg=FundingStressConfig(
                    enabled=True,
                    adverse_basis_bps=1.0,
                    spread_widen_bps=1.0,
                    funding_flip_bps=1.0,
                    min_stress_net_pnl_quote=-1e9,
                    max_stress_drawdown_quote=1e9,
                ),
                oos_output_path=oos_out,
                oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=2, min_oos_rows=2),
                walk_forward_output_path=walk_out,
                walk_forward_cfg=FundingWalkForwardConfig(
                    train_rows=2,
                    test_rows=2,
                    step_rows=2,
                    min_windows=1,
                    min_accepted_windows=1,
                    min_accepted_ratio=1.0,
                ),
                require_final=True,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["acceptance"]["accepted"])
            self.assertTrue(result["oos"]["accepted"])
            self.assertTrue(result["walk_forward"]["accepted"])
            self.assertTrue(result["research_acceptance"]["accepted"])
            self.assertEqual(result["research_acceptance"]["reasons"], [])
            self.assertTrue(result["research_acceptance"]["walk_forward_required_passed"])
            self.assertTrue(result["research_acceptance"]["walk_forward_accepted"])
            self.assertTrue(result["research_acceptance"]["stress_required_passed"])
            self.assertTrue(result["research_acceptance"]["stress_assumptions_passed"])
            self.assertTrue(result["research_acceptance"]["stress_accepted"])

    def test_funding_postprocess_rejects_zero_stress_assumptions_for_research_acceptance(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            rank_out = Path(tmp) / "rank.json"
            backtest_out = Path(tmp) / "backtest.json"
            oos_out = Path(tmp) / "oos.json"
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 4, "rows": 4}), encoding="utf-8")

            result = run_funding_postprocess_file(
                input_path=src,
                manifest_path=manifest,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(
                    spot_fee_bps=0.0,
                    perp_fee_bps=0.0,
                    slippage_bps=0.0,
                    min_total_score=0.0,
                ),
                acceptance_cfg=FundingAcceptanceConfig(
                    min_trades=1,
                    min_win_rate=0.0,
                    min_expectancy_quote=-1e9,
                    min_net_pnl_quote=-1e9,
                    max_drawdown_quote=1e9,
                    min_profit_factor=0.0,
                ),
                stress_cfg=FundingStressConfig(
                    enabled=True,
                    adverse_basis_bps=0.0,
                    spread_widen_bps=0.0,
                    funding_flip_bps=0.0,
                    min_stress_net_pnl_quote=-1e9,
                    max_stress_drawdown_quote=1e9,
                ),
                oos_output_path=oos_out,
                oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=2, min_oos_rows=2),
                require_final=True,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["acceptance"]["accepted"])
            self.assertTrue(result["oos"]["accepted"])
            self.assertFalse(result["research_acceptance"]["accepted"])
            self.assertIn("stress_assumptions_required", result["research_acceptance"]["reasons"])
            self.assertTrue(result["research_acceptance"]["stress_required_passed"])
            self.assertFalse(result["research_acceptance"]["stress_assumptions_passed"])

    def test_funding_finalize_blocks_not_final_collect(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            postprocess_out = tmp_path / "postprocess.json"
            rank_out = tmp_path / "rank.json"
            backtest_out = tmp_path / "backtest.json"
            oos_out = tmp_path / "oos.json"
            walk_out = tmp_path / "walk.json"
            plan_out = tmp_path / "paper_plan.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": False, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = run_funding_research_finalize_file(
                input_path=src,
                manifest_path=manifest,
                postprocess_output_path=postprocess_out,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                oos_output_path=oos_out,
                walk_forward_output_path=walk_out,
                paper_plan_output_path=plan_out,
                paper_output_path=None,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                acceptance_cfg=FundingAcceptanceConfig(),
                stress_cfg=FundingStressConfig(enabled=True, adverse_basis_bps=1.0),
                oos_cfg=FundingOosConfig(min_train_rows=1, min_oos_rows=1),
                walk_forward_cfg=FundingWalkForwardConfig(train_rows=1, test_rows=1, min_windows=1, min_accepted_windows=1),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "not_ready_for_postprocess")
            self.assertFalse(postprocess_out.exists())
            self.assertFalse(plan_out.exists())

    def test_funding_final_review_blocks_not_final_collect_before_downstream_artifacts(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            review_out = tmp_path / "review.json"
            postprocess_out = tmp_path / "postprocess.json"
            rank_out = tmp_path / "rank.json"
            backtest_out = tmp_path / "backtest.json"
            oos_out = tmp_path / "oos.json"
            walk_out = tmp_path / "walk.json"
            plan_out = tmp_path / "paper_plan.json"
            gate_out = tmp_path / "gate.json"
            regime_out = tmp_path / "regime.json"
            frontier_out = tmp_path / "frontier.json"
            sensitivity_out = tmp_path / "sensitivity.json"
            decision_out = tmp_path / "decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": False, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = run_funding_final_review_file(
                input_path=src,
                manifest_path=manifest,
                output_path=review_out,
                postprocess_output_path=postprocess_out,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                oos_output_path=oos_out,
                walk_forward_output_path=walk_out,
                paper_plan_output_path=plan_out,
                paper_output_path=None,
                gate_report_output_path=gate_out,
                regime_report_output_path=regime_out,
                frontier_report_output_path=frontier_out,
                sensitivity_output_path=sensitivity_out,
                decision_report_output_path=decision_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                acceptance_cfg=FundingAcceptanceConfig(),
                stress_cfg=FundingStressConfig(enabled=True, adverse_basis_bps=1.0),
                sensitivity_cfg=FundingSensitivityConfig(),
                oos_cfg=FundingOosConfig(min_train_rows=1, min_oos_rows=1),
                walk_forward_cfg=FundingWalkForwardConfig(train_rows=1, test_rows=1, min_windows=1, min_accepted_windows=1),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "not_ready_for_postprocess")
            self.assertTrue(review_out.exists())
            self.assertFalse(postprocess_out.exists())
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())
            self.assertFalse(gate_out.exists())
            self.assertFalse(regime_out.exists())
            self.assertFalse(frontier_out.exists())
            self.assertFalse(sensitivity_out.exists())
            self.assertFalse(decision_out.exists())
            saved = json.loads(review_out.read_text(encoding="utf-8"))
            self.assertTrue(saved["research_only"])
            self.assertFalse(saved["live_orders"])
            self.assertFalse(saved["api_keys_required"])
            self.assertFalse(saved["leverage_enabled"])
            self.assertFalse(saved["margin_execution"])
            self.assertEqual(saved["summary"]["next_action"], "wait_and_recheck")
            self.assertEqual(saved["summary"]["collector_status"], "running_or_waiting")
            self.assertEqual(saved["summary"]["completed_cycles"], 1)
            self.assertEqual(saved["summary"]["line_count"], 1)
            self.assertIn("collector_not_ready", saved["summary"]["reasons"])
            self.assertEqual(saved["artifact_paths"]["regime_report"], str(regime_out))

    def test_funding_final_review_writes_regime_report_for_ready_collect(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            review_out = tmp_path / "review.json"
            postprocess_out = tmp_path / "postprocess.json"
            rank_out = tmp_path / "rank.json"
            backtest_out = tmp_path / "backtest.json"
            oos_out = tmp_path / "oos.json"
            walk_out = tmp_path / "walk.json"
            plan_out = tmp_path / "paper_plan.json"
            gate_out = tmp_path / "gate.json"
            regime_out = tmp_path / "regime.json"
            frontier_out = tmp_path / "frontier.json"
            sensitivity_out = tmp_path / "sensitivity.json"
            decision_out = tmp_path / "decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = run_funding_final_review_file(
                input_path=src,
                manifest_path=manifest,
                output_path=review_out,
                postprocess_output_path=postprocess_out,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                oos_output_path=oos_out,
                walk_forward_output_path=walk_out,
                paper_plan_output_path=plan_out,
                paper_output_path=None,
                gate_report_output_path=gate_out,
                regime_report_output_path=regime_out,
                frontier_report_output_path=frontier_out,
                sensitivity_output_path=sensitivity_out,
                decision_report_output_path=decision_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                acceptance_cfg=FundingAcceptanceConfig(),
                stress_cfg=FundingStressConfig(enabled=True, adverse_basis_bps=1.0),
                sensitivity_cfg=FundingSensitivityConfig(),
                oos_cfg=FundingOosConfig(min_train_rows=1, min_oos_rows=1),
                walk_forward_cfg=FundingWalkForwardConfig(train_rows=1, test_rows=1, min_windows=1, min_accepted_windows=1),
            )

            self.assertTrue(regime_out.exists())
            self.assertEqual(result["artifact_paths"]["regime_report"], str(regime_out))
            self.assertIn(str(regime_out), result["artifacts_created"])
            self.assertEqual(result["regime_summary"]["markets"], 1)
            self.assertEqual(result["summary"]["regime_eligible_markets"], result["regime_summary"]["eligible_markets"])
            self.assertFalse(result["summary"]["paper_plan_created"])
            self.assertEqual(result["summary"]["paper_plan_status"], "blocked_by_decision_report")
            self.assertTrue(plan_out.exists())
            saved_plan = json.loads(plan_out.read_text(encoding="utf-8"))
            self.assertFalse(saved_plan["ready_for_paper_forward"])
            self.assertEqual(saved_plan["status"], "blocked_by_decision_report")
            self.assertIn("decision_not_accepted", saved_plan["research_gate_reasons"])
            self.assertTrue(result["finalize"]["paper_plan_creation_deferred"])
            postprocess = result["finalize"]["postprocess"]
            metrics = postprocess["backtest_metrics"]
            summary = result["summary"]
            self.assertEqual(summary["data_quality_accepted"], postprocess["data_quality"]["accepted"])
            self.assertEqual(summary["backtest_total_trades"], metrics["total_trades"])
            self.assertEqual(summary["backtest_win_rate"], metrics["win_rate"])
            self.assertEqual(summary["backtest_expectancy_quote"], metrics["expectancy_quote"])
            self.assertEqual(summary["backtest_net_pnl_quote"], metrics["net_pnl_quote"])
            self.assertEqual(summary["backtest_max_drawdown_quote"], metrics["max_drawdown_quote"])
            self.assertEqual(summary["oos_accepted"], postprocess["oos"]["accepted"])
            self.assertEqual(summary["walk_forward_accepted"], postprocess["walk_forward"]["accepted"])
            self.assertEqual(summary["stress_accepted"], postprocess["research_acceptance"]["stress_accepted"])

    def test_funding_finalize_blocks_low_quality_collect_without_paper_plan(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            postprocess_out = tmp_path / "postprocess.json"
            rank_out = tmp_path / "rank.json"
            backtest_out = tmp_path / "backtest.json"
            oos_out = tmp_path / "oos.json"
            walk_out = tmp_path / "walk.json"
            plan_out = tmp_path / "paper_plan.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "final": True,
                        "cycles": 1,
                        "completed_cycles": 1,
                        "rows": 1,
                        "errors": 10,
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_research_finalize_file(
                input_path=src,
                manifest_path=manifest,
                postprocess_output_path=postprocess_out,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                oos_output_path=oos_out,
                walk_forward_output_path=walk_out,
                paper_plan_output_path=plan_out,
                paper_output_path=None,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(),
                acceptance_cfg=FundingAcceptanceConfig(),
                stress_cfg=FundingStressConfig(enabled=True, adverse_basis_bps=1.0),
                oos_cfg=FundingOosConfig(min_train_rows=1, min_oos_rows=1),
                walk_forward_cfg=FundingWalkForwardConfig(train_rows=1, test_rows=1, min_windows=1, min_accepted_windows=1),
                data_quality_cfg=FundingDataQualityConfig(max_error_rate=0.10),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "data_quality_rejected")
            self.assertTrue(postprocess_out.exists())
            saved = json.loads(postprocess_out.read_text(encoding="utf-8"))
            self.assertIn("max_error_rate", saved["data_quality"]["reasons"])
            self.assertFalse(rank_out.exists())
            self.assertFalse(backtest_out.exists())
            self.assertFalse(plan_out.exists())

    def test_funding_finalize_creates_postprocess_and_paper_plan_when_research_accepted(self) -> None:
        rows = []
        scan_cfg = BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0)
        for ts in [1.0, 14_401.0, 28_801.0, 43_201.0]:
            row = opportunity_from_snapshots(_spot(ts=ts), _funding(ts=ts, rate=0.0002), scan_cfg)
            assert row is not None
            row["total_score"] = 1.0
            rows.append(row)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            postprocess_out = tmp_path / "postprocess.json"
            rank_out = tmp_path / "rank.json"
            backtest_out = tmp_path / "backtest.json"
            oos_out = tmp_path / "oos.json"
            walk_out = tmp_path / "walk.json"
            plan_out = tmp_path / "paper_plan.json"
            paper_out = tmp_path / "paper_forward.jsonl"
            decision_out = tmp_path / "decision.json"
            src.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "completed_cycles": 4, "rows": 4}), encoding="utf-8")
            decision_out.write_text(
                json.dumps({"summary": {"accepted": True, "reasons": [], "verdict": "paper_forward_candidate"}}),
                encoding="utf-8",
            )

            result = run_funding_research_finalize_file(
                input_path=src,
                manifest_path=manifest,
                postprocess_output_path=postprocess_out,
                rank_output_path=rank_out,
                backtest_output_path=backtest_out,
                oos_output_path=oos_out,
                walk_forward_output_path=walk_out,
                paper_plan_output_path=plan_out,
                paper_output_path=paper_out,
                rank_cfg=FundingRankConfig(),
                backtest_cfg=FundingBacktestConfig(
                    spot_fee_bps=0.0,
                    perp_fee_bps=0.0,
                    slippage_bps=0.0,
                    min_total_score=0.0,
                ),
                acceptance_cfg=FundingAcceptanceConfig(
                    min_trades=1,
                    min_win_rate=0.0,
                    min_expectancy_quote=-1e9,
                    min_net_pnl_quote=-1e9,
                    max_drawdown_quote=1e9,
                    min_profit_factor=0.0,
                ),
                stress_cfg=FundingStressConfig(
                    enabled=True,
                    adverse_basis_bps=1.0,
                    spread_widen_bps=1.0,
                    funding_flip_bps=1.0,
                    min_stress_net_pnl_quote=-1e9,
                    max_stress_drawdown_quote=1e9,
                ),
                oos_cfg=FundingOosConfig(train_fraction=0.5, min_train_rows=2, min_oos_rows=2),
                walk_forward_cfg=FundingWalkForwardConfig(
                    train_rows=2,
                    test_rows=2,
                    step_rows=2,
                    min_windows=1,
                    min_accepted_windows=1,
                    min_accepted_ratio=1.0,
                ),
                min_forward_hours=24.0,
                min_forward_rows=20,
                min_forward_markets=1,
                create_paper_plan=True,
                decision_report_path=decision_out,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["research_acceptance"]["accepted"])
            self.assertTrue(result["paper_plan_created"])
            self.assertTrue(postprocess_out.exists())
            self.assertTrue(rank_out.exists())
            self.assertTrue(backtest_out.exists())
            self.assertTrue(oos_out.exists())
            self.assertTrue(walk_out.exists())
            self.assertTrue(plan_out.exists())
            saved_plan = json.loads(plan_out.read_text(encoding="utf-8"))
            self.assertTrue(saved_plan["ready_for_paper_forward"])
            self.assertEqual(saved_plan["source_decision_report"], str(decision_out))
            self.assertEqual(saved_plan["paper_output_path"], str(paper_out))

    def test_paper_forward_plan_requires_accepted_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            postprocess = Path(tmp) / "postprocess.json"
            plan = Path(tmp) / "paper_plan.json"
            paper_output = Path(tmp) / "paper_forward.jsonl"
            decision = Path(tmp) / "decision.json"
            postprocess.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "research_acceptance": {
                            "accepted": True,
                            "full_backtest_accepted": True,
                            "oos_required_passed": True,
                            "oos_accepted": True,
                            "walk_forward_required_passed": True,
                            "walk_forward_accepted": True,
                            "stress_required_passed": True,
                            "stress_assumptions_passed": True,
                            "stress_accepted": True,
                            "reasons": [],
                        },
                        "input": "funding.jsonl",
                        "rank_output": "rank.json",
                        "backtest_output": "backtest.json",
                        "oos_output": "oos.json",
                        "walk_forward_output": "walk.json",
                        "backtest_config": {"notional_quote": 100.0},
                        "acceptance_config": {"min_trades": 20},
                        "stress_config": {"enabled": True},
                        "data_quality": {
                            "accepted": True,
                            "metrics": {
                                "first_ts": 100.0,
                                "last_ts": 200.0,
                                "span_sec": 100.0,
                                "span_hours": 100.0 / 3600.0,
                            },
                        },
                        "oos": {"accepted": True, "split": {"train_rows": 10, "oos_rows": 5}},
                        "walk_forward": {"accepted": True, "summary": {"windows": 3, "accepted_windows": 3}},
                    }
                ),
                encoding="utf-8",
            )
            decision.write_text(
                json.dumps({"summary": {"accepted": True, "reasons": [], "verdict": "paper_forward_candidate"}}),
                encoding="utf-8",
            )

            result = create_funding_paper_forward_plan_file(
                postprocess,
                plan,
                paper_output_path=paper_output,
                decision_report_path=decision,
                min_forward_hours=24.0,
                min_forward_rows=30,
                min_forward_markets=2,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "ready_for_paper_forward")
            self.assertTrue(result["ready_for_paper_forward"])
            self.assertFalse(result["live_orders"])
            self.assertFalse(result["api_keys_required"])
            self.assertFalse(result["leverage_enabled"])
            self.assertEqual(result["min_forward_hours"], 24.0)
            self.assertEqual(result["min_forward_rows"], 30)
            self.assertEqual(result["min_forward_markets"], 2)
            self.assertEqual(result["paper_output_path"], str(paper_output))
            self.assertEqual(result["source_decision_report"], str(decision))
            self.assertTrue(result["decision_summary"]["accepted"])
            self.assertEqual(result["source_time_range"]["first_ts"], 100.0)
            self.assertEqual(result["source_time_range"]["last_ts"], 200.0)
            self.assertTrue(plan.exists())

    def test_paper_forward_plan_rejects_unaccepted_decision_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            postprocess = Path(tmp) / "postprocess.json"
            decision = Path(tmp) / "decision.json"
            plan = Path(tmp) / "paper_plan.json"
            postprocess.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "research_acceptance": _accepted_research_acceptance(),
                        "input": "funding.jsonl",
                        "rank_output": "rank.json",
                        "backtest_output": "backtest.json",
                        "oos_output": "oos.json",
                        "walk_forward_output": "walk.json",
                        "backtest_config": {"notional_quote": 100.0},
                        "acceptance_config": {"min_trades": 20},
                        "stress_config": {"enabled": True},
                        "data_quality": {
                            "accepted": True,
                            "metrics": {"first_ts": 100.0, "last_ts": 200.0, "span_sec": 100.0},
                        },
                        "oos": {"accepted": True},
                        "walk_forward": {"accepted": True},
                    }
                ),
                encoding="utf-8",
            )
            decision.write_text(
                json.dumps({"summary": {"accepted": False, "reasons": ["regime_economics_pass_zero"]}}),
                encoding="utf-8",
            )

            result = create_funding_paper_forward_plan_file(postprocess, plan, decision_report_path=decision)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "decision_report_not_accepted")
            self.assertFalse(result["ready_for_paper_forward"])
            self.assertIn("decision_report_not_accepted", result["research_gate_reasons"])
            self.assertIn("decision:regime_economics_pass_zero", result["research_gate_reasons"])

    def test_paper_forward_plan_rejects_incomplete_research_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            postprocess = Path(tmp) / "postprocess.json"
            plan = Path(tmp) / "paper_plan.json"
            postprocess.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "research_acceptance": {"accepted": True},
                        "acceptance": {"accepted": True},
                        "oos": {"accepted": True},
                        "stress_config": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )

            result = create_funding_paper_forward_plan_file(postprocess, plan)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "decision_report_required")
            self.assertFalse(result["ready_for_paper_forward"])
            self.assertIn("decision_report_missing", result["research_gate_reasons"])
            self.assertIn("full_backtest_accepted_missing", result["research_gate_reasons"])
            self.assertIn("oos_required_passed_missing", result["research_gate_reasons"])
            self.assertIn("walk_forward_required_passed_missing", result["research_gate_reasons"])
            self.assertIn("stress_required_passed_missing", result["research_gate_reasons"])
            self.assertIn("data_quality_missing", result["research_gate_reasons"])
            self.assertIn("source_time_range_missing", result["research_gate_reasons"])
            self.assertTrue(plan.exists())

    def test_paper_forward_plan_rejects_missing_data_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            postprocess = Path(tmp) / "postprocess.json"
            plan = Path(tmp) / "paper_plan.json"
            postprocess.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "research_acceptance": _accepted_research_acceptance(),
                        "input": "funding.jsonl",
                        "rank_output": "rank.json",
                        "backtest_output": "backtest.json",
                        "oos_output": "oos.json",
                        "backtest_config": {"notional_quote": 100.0},
                        "acceptance_config": {"min_trades": 20},
                        "stress_config": {"enabled": True},
                        "oos": {"accepted": True},
                    }
                ),
                encoding="utf-8",
            )

            result = create_funding_paper_forward_plan_file(postprocess, plan)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "decision_report_required")
            self.assertFalse(result["ready_for_paper_forward"])
            self.assertIn("decision_report_missing", result["research_gate_reasons"])
            self.assertIn("data_quality_missing", result["research_gate_reasons"])
            self.assertIn("source_time_range_missing", result["research_gate_reasons"])

    def test_paper_forward_plan_rejects_unaccepted_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            postprocess = Path(tmp) / "postprocess.json"
            plan = Path(tmp) / "paper_plan.json"
            postprocess.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "research_acceptance": {"accepted": False},
                        "acceptance": {"accepted": True},
                        "oos": {"accepted": False},
                    }
                ),
                encoding="utf-8",
            )

            result = create_funding_paper_forward_plan_file(postprocess, plan)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "research_not_accepted")
            self.assertFalse(result["ready_for_paper_forward"])
            self.assertTrue(plan.exists())

    def test_paper_forward_blocks_unready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": False,
                        "paper_output_path": str(output),
                        "research_acceptance": {"accepted": False},
                        "frozen_config": {},
                    }
                ),
                encoding="utf-8",
            )
            forward.write_text("", encoding="utf-8")

            result = run_funding_paper_forward_file(plan, forward, output)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "plan_not_ready")
            self.assertTrue(output.exists())
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[-1]["status"], "plan_not_ready")

    def test_paper_forward_rejects_ready_plan_without_decision_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            forward.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "frozen_config": {
                            "backtest_config": {"notional_quote": 100.0},
                            "acceptance_config": {"min_trades": 1},
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "plan_research_gate_failed")
            self.assertIn("decision_report_missing", result["plan_gate_reasons"])
            self.assertIn("decision_summary_missing", result["plan_gate_reasons"])

    def test_paper_forward_blocks_source_input_reuse_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            plan = tmp_path / "paper_plan.json"
            source.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "source_input": str(source),
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "frozen_config": {
                            "backtest_config": {"notional_quote": 100.0},
                            "acceptance_config": {"min_trades": 1},
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, source, output)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "source_input_reuse_blocked")
            self.assertTrue(output.exists())

    def test_paper_forward_rejects_forged_live_orders_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            summary_output = tmp_path / "paper_forward_summary.json"
            forward.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": True,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "frozen_config": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output, summary_output_path=summary_output)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "plan_safety_gate_failed")
            self.assertIn("live_orders_not_false", result["plan_gate_reasons"])
            self.assertTrue(output.exists())
            self.assertTrue(summary_output.exists())
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "plan_safety_gate_failed")
            self.assertEqual(records[0]["metrics"], {})

    def test_paper_forward_rejects_forged_plan_without_research_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            forward.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": {"accepted": True},
                        "research_gate_reasons": [],
                        "frozen_config": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "plan_research_gate_failed")
            self.assertIn("full_backtest_accepted_missing", result["plan_gate_reasons"])
            self.assertIn("oos_required_passed_missing", result["plan_gate_reasons"])
            self.assertIn("data_quality_missing", result["plan_gate_reasons"])
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[-1]["status"], "plan_research_gate_failed")

    def test_paper_forward_blocks_source_time_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            source = tmp_path / "source.jsonl"
            row1 = opportunity_from_snapshots(
                _spot(ts=150.0, bid=100.0, ask=100.01),
                _funding(ts=150.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            row2 = opportunity_from_snapshots(
                _spot(ts=14_550.0, bid=100.0, ask=100.01),
                _funding(ts=14_550.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            assert row1 is not None
            assert row2 is not None
            forward.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in [row1, row2]) + "\n",
                encoding="utf-8",
            )
            source.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "source_input": str(source),
                        "source_time_range": {"first_ts": 1.0, "last_ts": 200.0, "span_sec": 199.0, "span_hours": 199.0 / 3600.0},
                        "source_data_quality": _accepted_source_data_quality(first_ts=1.0, last_ts=200.0),
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "frozen_config": {
                            "backtest_config": {
                                "notional_quote": 100.0,
                                "spot_fee_bps": 0.0,
                                "perp_fee_bps": 0.0,
                                "slippage_bps": 0.0,
                                "min_funding_rate": 0.0,
                                "min_total_score": -1000.0,
                            },
                            "acceptance_config": {"min_trades": 1, "min_win_rate": 0.0, "min_expectancy_quote": 0.0, "min_net_pnl_quote": 0.0, "max_drawdown_quote": 100.0, "min_profit_factor": 0.0},
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "source_time_overlap_blocked")
            self.assertIn("source_time_overlap", result["temporal_gate"]["reasons"])
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "source_time_overlap_blocked")
            self.assertEqual(records[0]["metrics"], {})

    def test_paper_forward_runs_frozen_config_on_forward_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            summary_output = tmp_path / "paper_forward_summary.json"
            source = tmp_path / "source.jsonl"
            row1 = opportunity_from_snapshots(
                _spot(ts=1.0, bid=100.0, ask=100.01),
                _funding(ts=1.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            row2 = opportunity_from_snapshots(
                _spot(ts=14_401.0, bid=100.0, ask=100.01),
                _funding(ts=14_401.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            assert row1 is not None
            assert row2 is not None
            forward.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in [row1, row2]) + "\n",
                encoding="utf-8",
            )
            source.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "source_input": str(source),
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "frozen_config": {
                            "backtest_config": {
                                "notional_quote": 100.0,
                                "spot_fee_bps": 0.0,
                                "perp_fee_bps": 0.0,
                                "slippage_bps": 0.0,
                                "min_funding_rate": 0.0,
                                "min_total_score": -1000.0,
                            },
                            "acceptance_config": {
                                "min_trades": 1,
                                "min_win_rate": 0.0,
                                "min_expectancy_quote": 0.0,
                                "min_net_pnl_quote": 0.0,
                                "max_drawdown_quote": 100.0,
                                "min_profit_factor": 0.0,
                            },
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output, summary_output_path=summary_output)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["paper_acceptance"]["accepted"])
            self.assertEqual(result["metrics"]["total_trades"], 1)
            self.assertGreater(result["metrics"]["net_pnl_quote"], 0)
            self.assertFalse(result["live_orders"])
            self.assertEqual(result["summary_output"], str(summary_output))
            self.assertTrue(summary_output.exists())
            saved_summary = json.loads(summary_output.read_text(encoding="utf-8"))
            self.assertEqual(saved_summary["paper_acceptance"], result["paper_acceptance"])
            self.assertEqual(saved_summary["metrics"]["total_trades"], 1)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["event"], "start")
            self.assertEqual(records[-1]["event"], "summary")
            self.assertEqual(records[-1]["metrics"]["total_trades"], 1)

    def test_paper_decision_report_accepts_completed_paper_forward_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            summary_output = tmp_path / "paper_forward_summary.json"
            decision_output = tmp_path / "paper_decision.json"
            source = tmp_path / "source.jsonl"
            row1 = opportunity_from_snapshots(
                _spot(ts=1.0, bid=100.0, ask=100.01),
                _funding(ts=1.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            row2 = opportunity_from_snapshots(
                _spot(ts=14_401.0, bid=100.0, ask=100.01),
                _funding(ts=14_401.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            assert row1 is not None
            assert row2 is not None
            forward.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in [row1, row2]) + "\n",
                encoding="utf-8",
            )
            source.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "source_input": str(source),
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "frozen_config": {
                            "backtest_config": {
                                "notional_quote": 100.0,
                                "spot_fee_bps": 0.0,
                                "perp_fee_bps": 0.0,
                                "slippage_bps": 0.0,
                                "min_funding_rate": 0.0,
                                "min_total_score": -1000.0,
                            },
                            "acceptance_config": {
                                "min_trades": 1,
                                "min_win_rate": 0.0,
                                "min_expectancy_quote": 0.0,
                                "min_net_pnl_quote": 0.0,
                                "max_drawdown_quote": 100.0,
                                "min_profit_factor": 0.0,
                            },
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )
            run_funding_paper_forward_file(plan, forward, output, summary_output_path=summary_output)

            report = funding_paper_decision_report(summary_output, plan_path=plan, output_path=decision_output)

            self.assertTrue(report["summary"]["accepted"])
            self.assertEqual(report["summary"]["verdict"], "continue_paper_forward")
            self.assertEqual(report["summary"]["next_action"], "extend_paper_forward_dataset")
            self.assertEqual(report["summary"]["total_trades"], 1)
            self.assertIn("funding_pnl_quote", report["summary"])
            self.assertIn("basis_pnl_quote", report["summary"])
            self.assertIn("fees_quote", report["summary"])
            self.assertIn("slippage_quote", report["summary"])
            self.assertFalse(report["live_orders"])
            self.assertTrue(decision_output.exists())

    def test_paper_decision_report_rejects_missing_required_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary = tmp_path / "summary.json"
            plan = tmp_path / "paper_plan.json"
            decision = tmp_path / "decision.json"
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward",
                        "ok": True,
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "metrics": {
                            "total_trades": 10,
                            "win_rate": 0.7,
                            "expectancy_quote": 0.1,
                            "net_pnl_quote": 1.0,
                        },
                        "paper_acceptance": {"accepted": True, "reasons": []},
                        "coverage": {
                            "duration_accepted": True,
                            "rows_accepted": True,
                            "markets_accepted": True,
                        },
                        "frozen_config": {
                            "backtest_config": {},
                            "acceptance_config": {},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = funding_paper_decision_report(summary, plan_path=plan, output_path=decision)

            self.assertFalse(report["summary"]["accepted"])
            self.assertEqual(report["summary"]["verdict"], "paper_rework_required")
            self.assertIn("metric:max_drawdown_quote_missing", report["summary"]["reasons"])
            self.assertTrue(decision.exists())

    def test_paper_decision_report_requires_plan_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary = tmp_path / "summary.json"
            decision = tmp_path / "decision.json"
            summary.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward",
                        "ok": True,
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "metrics": {
                            "total_trades": 10,
                            "win_rate": 0.7,
                            "expectancy_quote": 0.1,
                            "net_pnl_quote": 1.0,
                            "max_drawdown_quote": 0.0,
                        },
                        "paper_acceptance": {"accepted": True, "reasons": []},
                        "coverage": {
                            "duration_accepted": True,
                            "rows_accepted": True,
                            "markets_accepted": True,
                        },
                        "frozen_config": {
                            "backtest_config": {},
                            "acceptance_config": {},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = funding_paper_decision_report(summary, output_path=decision)

            self.assertFalse(report["summary"]["accepted"])
            self.assertEqual(report["summary"]["verdict"], "paper_rework_required")
            self.assertIn("plan_required", report["summary"]["reasons"])
            self.assertTrue(decision.exists())

    def test_paper_decision_report_rejects_summary_without_plan_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "summary.json"
            decision = tmp_path / "decision.json"
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward",
                        "ok": True,
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "metrics": {
                            "total_trades": 10,
                            "win_rate": 0.7,
                            "expectancy_quote": 0.1,
                            "net_pnl_quote": 1.0,
                            "max_drawdown_quote": 0.0,
                        },
                        "paper_acceptance": {"accepted": True, "reasons": []},
                        "coverage": {
                            "duration_accepted": True,
                            "rows_accepted": True,
                            "markets_accepted": True,
                        },
                        "frozen_config": {
                            "backtest_config": {},
                            "acceptance_config": {},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = funding_paper_decision_report(summary, plan_path=plan, output_path=decision)

            self.assertFalse(report["summary"]["accepted"])
            self.assertIn("summary_plan_path_missing", report["summary"]["reasons"])

    def test_paper_decision_report_rejects_summary_plan_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            other_plan = tmp_path / "other_plan.json"
            summary = tmp_path / "summary.json"
            decision = tmp_path / "decision.json"
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                    }
                ),
                encoding="utf-8",
            )
            other_plan.write_text("{}", encoding="utf-8")
            summary.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward",
                        "ok": True,
                        "status": "completed",
                        "plan": str(other_plan),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "metrics": {
                            "total_trades": 10,
                            "win_rate": 0.7,
                            "expectancy_quote": 0.1,
                            "net_pnl_quote": 1.0,
                            "max_drawdown_quote": 0.0,
                        },
                        "paper_acceptance": {"accepted": True, "reasons": []},
                        "coverage": {
                            "duration_accepted": True,
                            "rows_accepted": True,
                            "markets_accepted": True,
                        },
                        "frozen_config": {
                            "backtest_config": {},
                            "acceptance_config": {},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = funding_paper_decision_report(summary, plan_path=plan, output_path=decision)

            self.assertFalse(report["summary"]["accepted"])
            self.assertIn("summary_plan_path_mismatch", report["summary"]["reasons"])

    def test_paper_decision_report_rejects_summary_frozen_config_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "summary.json"
            decision = tmp_path / "decision.json"
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "frozen_config": {
                            "backtest_config": {"notional_quote": 100.0},
                            "acceptance_config": {"min_trades": 1},
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward",
                        "ok": True,
                        "status": "completed",
                        "plan": str(plan),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "metrics": {
                            "total_trades": 10,
                            "win_rate": 0.7,
                            "expectancy_quote": 0.1,
                            "net_pnl_quote": 1.0,
                            "max_drawdown_quote": 0.0,
                        },
                        "paper_acceptance": {"accepted": True, "reasons": []},
                        "coverage": {
                            "duration_accepted": True,
                            "rows_accepted": True,
                            "markets_accepted": True,
                        },
                        "frozen_config": {
                            "backtest_config": {"notional_quote": 999.0},
                            "acceptance_config": {"min_trades": 1},
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = funding_paper_decision_report(summary, plan_path=plan, output_path=decision)

            self.assertFalse(report["summary"]["accepted"])
            self.assertIn("summary_frozen_config_mismatch", report["summary"]["reasons"])

    def test_paper_decision_report_rejects_summary_output_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            source = tmp_path / "research_source.jsonl"
            forward = tmp_path / "forward.jsonl"
            expected_output = tmp_path / "paper_forward.jsonl"
            other_output = tmp_path / "other_paper_forward.jsonl"
            summary = tmp_path / "summary.json"
            decision = tmp_path / "decision.json"
            frozen_config = {
                "backtest_config": {"notional_quote": 100.0},
                "acceptance_config": {"min_trades": 1},
                "stress_config": {"enabled": False},
            }
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(source),
                        "paper_output_path": str(expected_output),
                        "frozen_config": frozen_config,
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward",
                        "ok": True,
                        "status": "completed",
                        "plan": str(plan),
                        "input": str(forward),
                        "output": str(other_output),
                        "source_input": str(source),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "metrics": {
                            "total_trades": 10,
                            "win_rate": 0.7,
                            "expectancy_quote": 0.1,
                            "net_pnl_quote": 1.0,
                            "max_drawdown_quote": 0.0,
                        },
                        "paper_acceptance": {"accepted": True, "reasons": []},
                        "coverage": {
                            "duration_accepted": True,
                            "rows_accepted": True,
                            "markets_accepted": True,
                        },
                        "frozen_config": frozen_config,
                    }
                ),
                encoding="utf-8",
            )

            report = funding_paper_decision_report(summary, plan_path=plan, output_path=decision)

            self.assertFalse(report["summary"]["accepted"])
            self.assertIn("summary_output_path_mismatch", report["summary"]["reasons"])

    def test_funding_goal_audit_waits_for_unready_collect(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            audit = tmp_path / "audit.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": False, "cycles": 10, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                output_path=audit,
                data_quality_cfg=FundingDataQualityConfig(min_rows=2, min_markets=2, min_completed_cycles=2),
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "collecting_funding")
            self.assertEqual(result["summary"]["next_action"], "wait_and_recheck")
            self.assertIn("collector_not_ready", result["summary"]["blockers"])
            self.assertEqual(result["summary"]["expected_cycles"], 10)
            self.assertEqual(result["summary"]["remaining_cycles"], 9)
            self.assertAlmostEqual(result["summary"]["progress_pct"], 10.0)
            self.assertFalse(result["summary"]["data_quality_accepted"])
            self.assertIn("min_rows", result["summary"]["data_quality_reasons"])
            self.assertIn("min_markets", result["summary"]["data_quality_reasons"])
            self.assertIn("min_completed_cycles", result["summary"]["data_quality_reasons"])
            self.assertEqual(result["summary"]["data_quality_metrics"]["rows"], 1)
            self.assertEqual(result["summary"]["data_quality_metrics"]["markets"], 1)
            self.assertFalse(result["live_orders"])
            self.assertTrue(audit.exists())

    def test_funding_collect_diagnostics_reports_partial_quality_and_economics(self) -> None:
        row1 = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        row2 = opportunity_from_snapshots(_spot(ts=2.0), _funding(ts=2.0, rate=-0.0001), BasisScanConfig())
        assert row1 is not None
        assert row2 is not None
        row1["cycle"] = 1
        row2["cycle"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            output = tmp_path / "diagnostics.json"
            src.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in (row1, row2)) + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "final": False,
                        "cycles": 2,
                        "completed_cycles": 1,
                        "rows": 2,
                        "errors": 1,
                        "cycle_summaries": [
                            {
                                "cycle": 1,
                                "rows": 2,
                                "eligible": 1,
                                "errors": 1,
                                "error_breakdown": [{"key": "mexc:match_contract:no_perp_contract", "count": 1}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = funding_collect_diagnostics_file(src, manifest_path=manifest, output_path=output, top_n=1)

            self.assertEqual(result["mode"], "funding_collect_diagnostics")
            self.assertTrue(result["research_only"])
            self.assertFalse(result["live_orders"])
            self.assertEqual(result["summary"]["rows_jsonl"], 2)
            self.assertTrue(result["summary"]["rows_match_manifest"])
            self.assertEqual(result["summary"]["completed_cycles"], 1)
            self.assertEqual(result["summary"]["expected_cycles"], 2)
            self.assertEqual(result["manifest_error_breakdown"]["mexc:match_contract:no_perp_contract"], 1)
            self.assertEqual(result["summary"]["positive_expected_net_carry_rows"], 0)
            self.assertTrue(result["summary"]["all_expected_net_carry_negative"])
            self.assertEqual(len(result["top_by_total_score"]), 1)
            self.assertTrue(output.exists())

    def test_funding_goal_audit_validates_only_paper_forward_not_live(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            decision = tmp_path / "paper_decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {
                            "accepted": True,
                            "reasons": [],
                            "verdict": "paper_forward_candidate",
                            "next_action": "run_funding_paper_plan",
                            "backtest_total_trades": 20,
                            "backtest_win_rate": 0.65,
                            "backtest_expectancy_quote": 0.2,
                            "backtest_net_pnl_quote": 4.0,
                            "backtest_max_drawdown_quote": 1.0,
                            "backtest_funding_pnl_quote": 5.0,
                            "backtest_basis_pnl_quote": 0.5,
                            "backtest_fees_quote": 1.0,
                            "backtest_slippage_quote": 0.5,
                            "oos_accepted": True,
                            "oos_net_pnl_quote": 1.5,
                            "walk_forward_accepted": True,
                            "walk_forward_avg_test_net_pnl_quote": 0.5,
                            "stress_accepted": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(
                json.dumps(_paper_forward_summary_fixture(plan, src)),
                encoding="utf-8",
            )
            decision.write_text(json.dumps(_paper_decision_report_fixture(summary, plan)), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
                paper_decision_path=decision,
            )

            self.assertTrue(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_forward_validated")
            self.assertEqual(result["summary"]["next_action"], "extend_paper_forward_dataset")
            self.assertTrue(result["summary"]["final_review_accepted"])
            self.assertEqual(result["summary"]["final_review_verdict"], "paper_forward_candidate")
            self.assertEqual(result["summary"]["final_backtest_total_trades"], 20)
            self.assertEqual(result["summary"]["final_backtest_win_rate"], 0.65)
            self.assertEqual(result["summary"]["final_backtest_net_pnl_quote"], 4.0)
            self.assertEqual(result["summary"]["final_funding_pnl_quote"], 5.0)
            self.assertEqual(result["summary"]["final_basis_pnl_quote"], 0.5)
            self.assertEqual(result["summary"]["final_fees_quote"], 1.0)
            self.assertEqual(result["summary"]["final_slippage_quote"], 0.5)
            self.assertTrue(result["summary"]["final_oos_accepted"])
            self.assertTrue(result["summary"]["final_walk_forward_accepted"])
            self.assertTrue(result["summary"]["final_stress_accepted"])
            self.assertEqual(result["summary"]["paper_forward_total_trades"], 10)
            self.assertEqual(result["summary"]["paper_forward_win_rate"], 0.7)
            self.assertEqual(result["summary"]["paper_forward_expectancy_quote"], 0.1)
            self.assertEqual(result["summary"]["paper_forward_net_pnl_quote"], 1.0)
            self.assertEqual(result["summary"]["paper_forward_max_drawdown_quote"], 0.0)
            self.assertEqual(result["summary"]["paper_forward_funding_pnl_quote"], 1.5)
            self.assertEqual(result["summary"]["paper_forward_basis_pnl_quote"], 0.2)
            self.assertEqual(result["summary"]["paper_forward_fees_quote"], 0.5)
            self.assertEqual(result["summary"]["paper_forward_slippage_quote"], 0.2)
            self.assertTrue(result["summary"]["paper_forward_acceptance_accepted"])
            self.assertTrue(result["summary"]["paper_decision_accepted"])
            self.assertEqual(result["summary"]["paper_decision_verdict"], "continue_paper_forward")
            self.assertTrue(result["research_only"])
            self.assertFalse(result["live_orders"])
            self.assertFalse(result["api_keys_required"])

    def test_funding_goal_audit_rejects_paper_decision_summary_path_mismatch(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            other_summary = tmp_path / "other_paper_summary.json"
            decision = tmp_path / "paper_decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(json.dumps(_paper_forward_summary_fixture(plan, src)), encoding="utf-8")
            other_summary.write_text(json.dumps(_paper_forward_summary_fixture(plan, src)), encoding="utf-8")
            decision.write_text(json.dumps(_paper_decision_report_fixture(other_summary, plan)), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
                paper_decision_path=decision,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_decision_invalid")
            self.assertIn("paper_decision_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("paper_decision:summary_path_mismatch", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_paper_decision_live_orders(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            decision = tmp_path / "paper_decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(json.dumps(_paper_forward_summary_fixture(plan, src)), encoding="utf-8")
            decision_payload = _paper_decision_report_fixture(summary, plan)
            decision_payload["live_orders"] = True
            decision.write_text(json.dumps(decision_payload), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
                paper_decision_path=decision,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_decision_invalid")
            self.assertIn("paper_decision_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("paper_decision:live_orders_not_false", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_paper_summary_live_orders(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                    }
                ),
                encoding="utf-8",
            )
            summary_payload = _paper_forward_summary_fixture(plan, src)
            summary_payload["live_orders"] = True
            summary.write_text(json.dumps(summary_payload), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_forward_invalid")
            self.assertIn("paper_summary_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("paper_summary:live_orders_not_false", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_paper_summary_missing_metrics(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                    }
                ),
                encoding="utf-8",
            )
            summary_payload = _paper_forward_summary_fixture(plan, src)
            summary_payload.pop("metrics")
            summary.write_text(json.dumps(summary_payload), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_forward_invalid")
            self.assertIn("paper_summary_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("paper_summary:metric:total_trades_missing", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_paper_decision_missing_metrics(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            decision = tmp_path / "paper_decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(json.dumps(_paper_forward_summary_fixture(plan, src)), encoding="utf-8")
            decision_payload = _paper_decision_report_fixture(summary, plan)
            decision_payload.pop("metrics")
            decision.write_text(json.dumps(decision_payload), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
                paper_decision_path=decision,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_decision_invalid")
            self.assertIn("paper_decision_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("paper_decision:metric:total_trades_missing", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_paper_plan_postprocess_mismatch(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            expected_postprocess = tmp_path / "postprocess.json"
            other_postprocess = tmp_path / "other_postprocess.json"
            decision_report = tmp_path / "decision_report.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "artifact_paths": {
                            "postprocess": str(expected_postprocess),
                            "paper_plan": str(plan),
                            "decision_report": str(decision_report),
                        },
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "mode": "funding_paper_forward_plan",
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(path=str(decision_report)),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "source_input": str(src),
                        "source_postprocess": str(other_postprocess),
                    }
                ),
                encoding="utf-8",
            )

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_plan_not_ready")
            self.assertIn("paper_plan_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("paper_plan:source_postprocess_mismatch", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_final_review_input_mismatch(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            other_src = tmp_path / "other_collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            other_src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(other_src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "funding_final_review_invalid")
            self.assertIn("final_review_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("final_review:input_path_mismatch", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_final_review_live_orders(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": True,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "funding_final_review_invalid")
            self.assertIn("final_review_artifact_mismatch", result["summary"]["blockers"])
            self.assertIn("final_review:live_orders_not_false", result["summary"]["blockers"])

    def test_funding_goal_audit_rejects_ready_plan_without_decision_evidence(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            final_review = tmp_path / "final_review.json"
            plan = tmp_path / "paper_plan.json"
            summary = tmp_path / "paper_summary.json"
            decision = tmp_path / "paper_decision.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")
            final_review.write_text(
                json.dumps(
                    {
                        "mode": "funding_final_review",
                        "status": "completed",
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "input": str(src),
                        "manifest": str(manifest),
                        "summary": {"accepted": True, "reasons": []},
                    }
                ),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "status": "ready_for_paper_forward",
                        "ready_for_paper_forward": True,
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                    }
                ),
                encoding="utf-8",
            )
            summary.write_text(json.dumps({"mode": "funding_paper_forward", "status": "completed"}), encoding="utf-8")
            decision.write_text(json.dumps({"summary": {"accepted": True, "reasons": []}}), encoding="utf-8")

            result = funding_goal_audit(
                src,
                manifest_path=manifest,
                final_review_path=final_review,
                paper_plan_path=plan,
                paper_summary_path=summary,
                paper_decision_path=decision,
            )

            self.assertFalse(result["summary"]["accepted"])
            self.assertEqual(result["summary"]["stage"], "paper_plan_not_ready")
            self.assertIn("paper_plan_gate_failed", result["summary"]["blockers"])
            self.assertIn("paper_plan:decision_report_missing", result["summary"]["blockers"])
            self.assertIn("paper_plan:decision_summary_missing", result["summary"]["blockers"])

    def test_wait_funding_ready_returns_ready_without_sleep_for_final_collect(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            output = tmp_path / "wait.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": True, "cycles": 1, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = wait_funding_ready(src, manifest_path=manifest, output_path=output, timeout_sec=0.0)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "ready_for_postprocess")
            self.assertTrue(result["ready_for_postprocess"])
            self.assertEqual(len(result["history"]), 1)
            self.assertTrue(output.exists())
            self.assertFalse(result["live_orders"])

    def test_wait_funding_ready_times_out_without_ready_collect(self) -> None:
        row = opportunity_from_snapshots(_spot(ts=1.0), _funding(ts=1.0), BasisScanConfig())
        assert row is not None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "collect.jsonl"
            manifest = tmp_path / "collect.manifest.json"
            output = tmp_path / "wait.json"
            src.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"final": False, "cycles": 10, "completed_cycles": 1, "rows": 1}), encoding="utf-8")

            result = wait_funding_ready(src, manifest_path=manifest, output_path=output, timeout_sec=0.0)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "timeout")
            self.assertFalse(result["ready_for_postprocess"])
            self.assertEqual(result["history"][0]["status"], "running_or_waiting")
            self.assertEqual(result["history"][0]["expected_cycles"], 10)
            self.assertEqual(result["history"][0]["remaining_cycles"], 9)
            self.assertAlmostEqual(result["history"][0]["progress_pct"], 10.0)
            self.assertTrue(output.exists())

    def test_paper_forward_rejects_when_forward_duration_is_too_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            source = tmp_path / "source.jsonl"
            row1 = opportunity_from_snapshots(
                _spot(ts=1.0, bid=100.0, ask=100.01),
                _funding(ts=1.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            row2 = opportunity_from_snapshots(
                _spot(ts=3_601.0, bid=100.0, ask=100.01),
                _funding(ts=3_601.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            assert row1 is not None
            assert row2 is not None
            forward.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in [row1, row2]) + "\n",
                encoding="utf-8",
            )
            source.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "source_input": str(source),
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "min_forward_hours": 24.0,
                        "frozen_config": {
                            "backtest_config": {
                                "notional_quote": 100.0,
                                "spot_fee_bps": 0.0,
                                "perp_fee_bps": 0.0,
                                "slippage_bps": 0.0,
                                "min_funding_rate": 0.0,
                                "min_total_score": -1000.0,
                            },
                            "acceptance_config": {
                                "min_trades": 1,
                                "min_win_rate": 0.0,
                                "min_expectancy_quote": -100.0,
                                "min_net_pnl_quote": -100.0,
                                "max_drawdown_quote": 100.0,
                                "min_profit_factor": 0.0,
                            },
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertFalse(result["paper_acceptance"]["accepted"])
            self.assertIn("min_forward_hours", result["paper_acceptance"]["reasons"])
            self.assertLess(result["coverage"]["span_hours"], 24.0)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(records[-1]["paper_acceptance"]["accepted"])

    def test_paper_forward_rejects_when_forward_sample_is_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "paper_plan.json"
            forward = tmp_path / "forward.jsonl"
            output = tmp_path / "paper_forward.jsonl"
            source = tmp_path / "source.jsonl"
            row1 = opportunity_from_snapshots(
                _spot(ts=1.0, bid=100.0, ask=100.01),
                _funding(ts=1.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            row2 = opportunity_from_snapshots(
                _spot(ts=86_401.0, bid=100.0, ask=100.01),
                _funding(ts=86_401.0, rate=0.001, bid=100.0, ask=100.01, mark=100.005),
                BasisScanConfig(spot_fee_bps=0.0, perp_fee_bps=0.0, slippage_bps=0.0),
            )
            assert row1 is not None
            assert row2 is not None
            forward.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in [row1, row2]) + "\n",
                encoding="utf-8",
            )
            source.write_text("", encoding="utf-8")
            plan.write_text(
                json.dumps(
                    {
                        "ready_for_paper_forward": True,
                        "source_input": str(source),
                        "paper_output_path": str(output),
                        "research_only": True,
                        "live_orders": False,
                        "api_keys_required": False,
                        "leverage_enabled": False,
                        "margin_execution": False,
                        **_accepted_plan_decision_fields(),
                        "research_acceptance": _accepted_research_acceptance(),
                        "research_gate_reasons": [],
                        "source_data_quality": _accepted_source_data_quality(),
                        "source_time_range": _accepted_source_time_range(),
                        "min_forward_hours": 24.0,
                        "min_forward_rows": 3,
                        "min_forward_markets": 2,
                        "frozen_config": {
                            "backtest_config": {
                                "notional_quote": 100.0,
                                "spot_fee_bps": 0.0,
                                "perp_fee_bps": 0.0,
                                "slippage_bps": 0.0,
                                "min_funding_rate": 0.0,
                                "min_total_score": -1000.0,
                            },
                            "acceptance_config": {
                                "min_trades": 1,
                                "min_win_rate": 0.0,
                                "min_expectancy_quote": -100.0,
                                "min_net_pnl_quote": -100.0,
                                "max_drawdown_quote": 100.0,
                                "min_profit_factor": 0.0,
                            },
                            "stress_config": {"enabled": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_funding_paper_forward_file(plan, forward, output)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertFalse(result["paper_acceptance"]["accepted"])
            self.assertIn("min_forward_rows", result["paper_acceptance"]["reasons"])
            self.assertIn("min_forward_markets", result["paper_acceptance"]["reasons"])
            self.assertEqual(result["coverage"]["rows"], 2)
            self.assertEqual(result["coverage"]["markets"], 1)
            self.assertTrue(result["coverage"]["duration_accepted"])
            self.assertFalse(result["coverage"]["rows_accepted"])
            self.assertFalse(result["coverage"]["markets_accepted"])

    def test_collect_funding_file_writes_manifest(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        payload = {
            "rows": [row],
            "summary": {"markets": 1, "eligible": 1, "errors": 1},
            "errors": [{"exchange": "gateio", "stage": "scan_pair", "error": "boom"}],
            "discovery": {"gateio": {"symbols": ["HYPE_USDT"]}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            with patch("basis.run_funding_scan", return_value=payload):
                result = collect_funding_file(output, cycles=1, poll_interval_sec=0.0, manifest_path=manifest)
            self.assertEqual(result["rows"], 1)
            self.assertTrue(manifest.exists())
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(manifest_payload["final"])
            self.assertEqual(manifest_payload["completed_cycles"], 1)
            self.assertEqual(manifest_payload["errors"], 1)

    def test_collect_funding_file_resumes_from_manifest(self) -> None:
        row = opportunity_from_snapshots(_spot(), _funding(), BasisScanConfig())
        assert row is not None
        payload = {
            "rows": [row],
            "summary": {"markets": 1, "eligible": 1, "errors": 0},
            "errors": [],
            "discovery": {"mexc": {"symbols": ["HYPEUSDT"]}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "collect.jsonl"
            manifest = Path(tmp) / "collect.manifest.json"
            existing_row = dict(row)
            existing_row["cycle"] = 1
            output.write_text(json.dumps(existing_row, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "final": False,
                        "cycles": 3,
                        "completed_cycles": 1,
                        "rows": 1,
                        "errors": 2,
                        "duration_sec": 10.0,
                        "cycle_summaries": [{"cycle": 1, "rows": 1, "errors": 2}],
                    }
                ),
                encoding="utf-8",
            )

            with patch("basis.run_funding_scan", return_value=payload) as scan:
                result = collect_funding_file(
                    output,
                    cycles=3,
                    poll_interval_sec=0.0,
                    manifest_path=manifest,
                    resume=True,
                )

            self.assertEqual(scan.call_count, 2)
            self.assertEqual(result["rows"], 3)
            self.assertEqual(result["errors"], 2)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([item["cycle"] for item in rows], [1, 2, 3])
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(manifest_payload["final"])
            self.assertEqual(manifest_payload["completed_cycles"], 3)
            self.assertEqual(manifest_payload["rows"], 3)
            self.assertEqual(manifest_payload["errors"], 2)

    def test_cli_parser_accepts_funding_commands(self) -> None:
        parser = build_parser()
        scan_args = parser.parse_args(
            [
                "funding-scan",
                "--max-pairs-per-exchange",
                "1",
                "--min-spot-top-notional-quote",
                "150",
                "--min-basis-bps",
                "0",
                "--max-break-even-hours",
                "24",
            ]
        )
        self.assertEqual(scan_args.command, "funding-scan")
        self.assertEqual(scan_args.min_spot_top_notional_quote, 150.0)
        self.assertEqual(scan_args.min_basis_bps, 0.0)
        self.assertEqual(scan_args.max_break_even_hours, 24.0)
        collect_args = parser.parse_args(
            [
                "funding-collect",
                "--cycles",
                "1",
                "--resume",
                "--min-spot-top-notional-quote",
                "175",
                "--min-basis-bps",
                "0",
                "--max-break-even-hours",
                "24",
            ]
        )
        self.assertEqual(collect_args.command, "funding-collect")
        self.assertTrue(collect_args.resume)
        self.assertEqual(collect_args.min_spot_top_notional_quote, 175.0)
        self.assertEqual(collect_args.min_basis_bps, 0.0)
        self.assertEqual(collect_args.max_break_even_hours, 24.0)
        status_args = parser.parse_args(["funding-status", "--input", "collect.jsonl", "--stale-after-sec", "10"])
        self.assertEqual(status_args.command, "funding-status")
        self.assertEqual(status_args.stale_after_sec, 10.0)
        diagnostics_args = parser.parse_args(
            [
                "funding-collect-diagnostics",
                "--input",
                "collect.jsonl",
                "--manifest",
                "collect.manifest.json",
                "--output",
                "diagnostics.json",
                "--top-n",
                "7",
                "--required-row-fields",
                "ts,exchange",
            ]
        )
        self.assertEqual(diagnostics_args.command, "funding-collect-diagnostics")
        self.assertEqual(diagnostics_args.input, "collect.jsonl")
        self.assertEqual(diagnostics_args.manifest, "collect.manifest.json")
        self.assertEqual(diagnostics_args.output, "diagnostics.json")
        self.assertEqual(diagnostics_args.top_n, 7)
        self.assertEqual(diagnostics_args.required_row_fields, "ts,exchange")
        wait_args = parser.parse_args(
            [
                "funding-wait-ready",
                "--input",
                "collect.jsonl",
                "--timeout-sec",
                "30",
                "--poll-interval-sec",
                "5",
                "--output",
                "wait.json",
            ]
        )
        self.assertEqual(wait_args.command, "funding-wait-ready")
        self.assertEqual(wait_args.timeout_sec, 30.0)
        self.assertEqual(wait_args.poll_interval_sec, 5.0)
        self.assertEqual(wait_args.output, "wait.json")
        coverage_args = parser.parse_args(
            [
                "funding-coverage",
                "--exchanges",
                "mexc,gateio",
                "--max-symbols",
                "50",
                "--quote",
                "USDT",
                "--matched-universe-output",
                "matched.csv",
            ]
        )
        self.assertEqual(coverage_args.command, "funding-coverage")
        self.assertEqual(coverage_args.exchanges, "mexc,gateio")
        self.assertEqual(coverage_args.max_symbols, 50)
        self.assertEqual(coverage_args.quote, "USDT")
        self.assertEqual(coverage_args.matched_universe_output, "matched.csv")
        self.assertEqual(parser.parse_args(["funding-rank", "--top-n", "3"]).command, "funding-rank")
        rank_args = parser.parse_args(
            [
                "funding-rank",
                "--min-funding-observations",
                "3",
                "--min-funding-positive-ratio",
                "0.8",
                "--min-funding-persistence-score",
                "2.0",
                "--min-funding-rate",
                "0.001",
                "--max-spot-spread-bps",
                "12",
                "--max-perp-spread-bps",
                "8",
                "--max-abs-basis-bps",
                "250",
                "--min-basis-bps",
                "1.0",
                "--min-expected-net-carry-bps",
                "2.0",
                "--max-break-even-hours",
                "12",
                "--min-regime-observations",
                "4",
                "--min-perp-volume-24h-quote",
                "1000000",
                "--min-spot-top-notional-quote",
                "500",
                "--max-basis-std-bps",
                "3",
                "--max-avg-spot-spread-bps",
                "9",
                "--max-avg-perp-spread-bps",
                "7",
            ]
        )
        self.assertEqual(rank_args.min_funding_observations, 3)
        self.assertEqual(rank_args.min_funding_positive_ratio, 0.8)
        self.assertEqual(rank_args.min_funding_persistence_score, 2.0)
        self.assertEqual(rank_args.min_funding_rate, 0.001)
        self.assertEqual(rank_args.max_spot_spread_bps, 12.0)
        self.assertEqual(rank_args.max_perp_spread_bps, 8.0)
        self.assertEqual(rank_args.max_abs_basis_bps, 250.0)
        self.assertEqual(rank_args.min_basis_bps, 1.0)
        self.assertEqual(rank_args.min_expected_net_carry_bps, 2.0)
        self.assertEqual(rank_args.max_break_even_hours, 12.0)
        self.assertEqual(rank_args.min_regime_observations, 4)
        self.assertEqual(rank_args.min_perp_volume_24h_quote, 1_000_000)
        self.assertEqual(rank_args.min_spot_top_notional_quote, 500.0)
        self.assertEqual(rank_args.max_basis_std_bps, 3.0)
        self.assertEqual(rank_args.max_avg_spot_spread_bps, 9.0)
        self.assertEqual(rank_args.max_avg_perp_spread_bps, 7.0)
        gate_report_args = parser.parse_args(
            [
                "funding-gate-report",
                "--top-n",
                "7",
                "--quality-universe-output",
                "quality.csv",
                "--min-risk-adjusted-edge-bps",
                "1.25",
                "--basis-risk-multiplier",
                "2",
                "--spread-risk-multiplier",
                "0.25",
                "--strict-research",
            ]
        )
        self.assertEqual(gate_report_args.command, "funding-gate-report")
        self.assertEqual(gate_report_args.top_n, 7)
        self.assertEqual(gate_report_args.quality_universe_output, "quality.csv")
        self.assertEqual(gate_report_args.min_risk_adjusted_edge_bps, 1.25)
        self.assertEqual(gate_report_args.basis_risk_multiplier, 2.0)
        self.assertEqual(gate_report_args.spread_risk_multiplier, 0.25)
        self.assertTrue(gate_report_args.strict_research)
        regime_report_args = parser.parse_args(
            [
                "funding-regime-report",
                "--input",
                "collect.jsonl",
                "--top-n",
                "8",
                "--min-regime-observations",
                "6",
                "--min-perp-volume-24h-quote",
                "2000000",
                "--strict-research",
            ]
        )
        self.assertEqual(regime_report_args.command, "funding-regime-report")
        self.assertEqual(regime_report_args.input, "collect.jsonl")
        self.assertEqual(regime_report_args.top_n, 8)
        self.assertEqual(regime_report_args.min_regime_observations, 6)
        self.assertEqual(regime_report_args.min_perp_volume_24h_quote, 2_000_000)
        self.assertTrue(regime_report_args.strict_research)
        frontier_report_args = parser.parse_args(
            [
                "funding-frontier-report",
                "--input",
                "collect.jsonl",
                "--top-n",
                "6",
                "--min-spot-top-notional-quote",
                "750",
                "--strict-research",
            ]
        )
        self.assertEqual(frontier_report_args.command, "funding-frontier-report")
        self.assertEqual(frontier_report_args.input, "collect.jsonl")
        self.assertEqual(frontier_report_args.top_n, 6)
        self.assertEqual(frontier_report_args.min_spot_top_notional_quote, 750.0)
        self.assertTrue(frontier_report_args.strict_research)
        decision_report_args = parser.parse_args(
            [
                "funding-decision-report",
                "--input",
                "collect.jsonl",
                "--postprocess-report",
                "postprocess.json",
                "--gate-report",
                "gate.json",
                "--regime-report",
                "regime.json",
                "--frontier-report",
                "frontier.json",
                "--sensitivity-report",
                "sensitivity.json",
                "--strict-research",
            ]
        )
        self.assertEqual(decision_report_args.command, "funding-decision-report")
        self.assertEqual(decision_report_args.input, "collect.jsonl")
        self.assertEqual(decision_report_args.postprocess_report, "postprocess.json")
        self.assertEqual(decision_report_args.gate_report, "gate.json")
        self.assertEqual(decision_report_args.regime_report, "regime.json")
        self.assertEqual(decision_report_args.frontier_report, "frontier.json")
        self.assertEqual(decision_report_args.sensitivity_report, "sensitivity.json")
        self.assertTrue(decision_report_args.strict_research)
        progress_args = parser.parse_args(
            [
                "funding-progress-report",
                "--input",
                "collect.jsonl",
                "--manifest",
                "collect.manifest.json",
                "--top-n",
                "4",
                "--strict-research",
            ]
        )
        self.assertEqual(progress_args.command, "funding-progress-report")
        self.assertEqual(progress_args.input, "collect.jsonl")
        self.assertEqual(progress_args.manifest, "collect.manifest.json")
        self.assertEqual(progress_args.top_n, 4)
        self.assertTrue(progress_args.strict_research)
        backtest_args = parser.parse_args(
            [
                "funding-backtest",
                "--notional-quote",
                "50",
                "--min-funding-observations",
                "3",
                "--min-funding-positive-ratio",
                "0.8",
                "--min-funding-persistence-score",
                "2.0",
                "--min-regime-observations",
                "4",
                "--min-perp-volume-24h-quote",
                "1000000",
                "--min-spot-top-notional-quote",
                "250",
                "--max-basis-std-bps",
                "5",
                "--min-basis-bps",
                "1.5",
                "--max-break-even-hours",
                "36",
            ]
        )
        self.assertEqual(backtest_args.command, "funding-backtest")
        self.assertEqual(backtest_args.min_funding_observations, 3)
        self.assertEqual(backtest_args.min_funding_positive_ratio, 0.8)
        self.assertEqual(backtest_args.min_funding_persistence_score, 2.0)
        self.assertEqual(backtest_args.min_regime_observations, 4)
        self.assertEqual(backtest_args.min_perp_volume_24h_quote, 1_000_000)
        self.assertEqual(backtest_args.min_spot_top_notional_quote, 250.0)
        self.assertEqual(backtest_args.max_basis_std_bps, 5.0)
        self.assertEqual(backtest_args.min_basis_bps, 1.5)
        self.assertEqual(backtest_args.max_break_even_hours, 36.0)
        sensitivity_args = parser.parse_args(
            [
                "funding-sensitivity",
                "--spot-fee-bps-list",
                "0,5",
                "--perp-fee-bps-list",
                "0,2.5",
                "--slippage-bps-list",
                "0,1",
                "--target-hold-intervals-list",
                "1,3",
                "--max-break-even-hours-list",
                "24,72",
                "--min-basis-bps",
                "0",
                "--min-expected-net-carry-bps",
                "0",
                "--min-risk-adjusted-edge-bps",
                "1.5",
                "--basis-risk-multiplier",
                "2",
                "--spread-risk-multiplier",
                "0.5",
                "--accept-min-trades",
                "2",
                "--stress-enabled",
                "--sensitivity-oos",
                "--oos-train-fraction",
                "0.6",
                "--oos-min-train-rows",
                "10",
                "--oos-min-rows",
                "5",
                "--oos-min-train-span-hours",
                "3",
                "--oos-min-span-hours",
                "2",
                "--sensitivity-walk-forward",
                "--walk-train-rows",
                "20",
                "--walk-test-rows",
                "5",
                "--walk-step-rows",
                "5",
                "--walk-min-windows",
                "4",
                "--walk-min-accepted-windows",
                "3",
                "--walk-min-accepted-ratio",
                "0.75",
                "--walk-min-train-span-hours",
                "6",
                "--walk-min-test-span-hours",
                "2",
            ]
        )
        self.assertEqual(sensitivity_args.command, "funding-sensitivity")
        self.assertEqual(sensitivity_args.spot_fee_bps_list, "0,5")
        self.assertEqual(sensitivity_args.perp_fee_bps_list, "0,2.5")
        self.assertEqual(sensitivity_args.slippage_bps_list, "0,1")
        self.assertEqual(sensitivity_args.target_hold_intervals_list, "1,3")
        self.assertEqual(sensitivity_args.max_break_even_hours_list, "24,72")
        self.assertEqual(sensitivity_args.min_basis_bps, 0.0)
        self.assertEqual(sensitivity_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(sensitivity_args.min_risk_adjusted_edge_bps, 1.5)
        self.assertEqual(sensitivity_args.basis_risk_multiplier, 2.0)
        self.assertEqual(sensitivity_args.spread_risk_multiplier, 0.5)
        self.assertEqual(sensitivity_args.accept_min_trades, 2)
        self.assertTrue(sensitivity_args.stress_enabled)
        self.assertTrue(sensitivity_args.sensitivity_oos)
        self.assertEqual(sensitivity_args.oos_train_fraction, 0.6)
        self.assertEqual(sensitivity_args.oos_min_train_rows, 10)
        self.assertEqual(sensitivity_args.oos_min_rows, 5)
        self.assertEqual(sensitivity_args.oos_min_train_span_hours, 3.0)
        self.assertEqual(sensitivity_args.oos_min_span_hours, 2.0)
        self.assertTrue(sensitivity_args.sensitivity_walk_forward)
        self.assertEqual(sensitivity_args.walk_train_rows, 20)
        self.assertEqual(sensitivity_args.walk_test_rows, 5)
        self.assertEqual(sensitivity_args.walk_step_rows, 5)
        self.assertEqual(sensitivity_args.walk_min_windows, 4)
        self.assertEqual(sensitivity_args.walk_min_accepted_windows, 3)
        self.assertEqual(sensitivity_args.walk_min_accepted_ratio, 0.75)
        self.assertEqual(sensitivity_args.walk_min_train_span_hours, 6.0)
        self.assertEqual(sensitivity_args.walk_min_test_span_hours, 2.0)
        oos_args = parser.parse_args(
            [
                "funding-oos-backtest",
                "--train-fraction",
                "0.6",
                "--min-train-rows",
                "10",
                "--min-oos-rows",
                "5",
                "--min-train-span-hours",
                "2",
                "--min-oos-span-hours",
                "3",
                "--min-spot-top-notional-quote",
                "300",
                "--min-basis-bps",
                "2.5",
                "--max-break-even-hours",
                "48",
                "--accept-min-trades",
                "3",
                "--accept-min-markets",
                "2",
                "--accept-max-market-trade-share",
                "0.7",
                "--accept-min-exchanges",
                "2",
                "--accept-max-exchange-trade-share",
                "0.8",
                "--accept-min-profitable-windows",
                "2",
                "--accept-max-window-pnl-share",
                "0.6",
                "--stress-enabled",
            ]
        )
        self.assertEqual(oos_args.command, "funding-oos-backtest")
        self.assertEqual(oos_args.train_fraction, 0.6)
        self.assertEqual(oos_args.min_train_rows, 10)
        self.assertEqual(oos_args.min_oos_rows, 5)
        self.assertEqual(oos_args.min_train_span_hours, 2.0)
        self.assertEqual(oos_args.min_oos_span_hours, 3.0)
        self.assertEqual(oos_args.min_spot_top_notional_quote, 300.0)
        self.assertEqual(oos_args.min_basis_bps, 2.5)
        self.assertEqual(oos_args.max_break_even_hours, 48.0)
        self.assertEqual(oos_args.accept_min_trades, 3)
        self.assertEqual(oos_args.accept_min_markets, 2)
        self.assertEqual(oos_args.accept_max_market_trade_share, 0.7)
        self.assertEqual(oos_args.accept_min_exchanges, 2)
        self.assertEqual(oos_args.accept_max_exchange_trade_share, 0.8)
        self.assertEqual(oos_args.accept_min_profitable_windows, 2)
        self.assertEqual(oos_args.accept_max_window_pnl_share, 0.6)
        self.assertTrue(oos_args.stress_enabled)
        walk_args = parser.parse_args(
            [
                "funding-walk-forward",
                "--walk-train-rows",
                "20",
                "--walk-test-rows",
                "5",
                "--walk-step-rows",
                "5",
                "--walk-min-windows",
                "4",
                "--walk-min-accepted-windows",
                "3",
                "--walk-min-accepted-ratio",
                "0.75",
                "--walk-min-train-span-hours",
                "6",
                "--walk-min-test-span-hours",
                "2",
                "--strict-research",
            ]
        )
        self.assertEqual(walk_args.command, "funding-walk-forward")
        self.assertEqual(walk_args.walk_train_rows, 20)
        self.assertEqual(walk_args.walk_test_rows, 5)
        self.assertEqual(walk_args.walk_step_rows, 5)
        self.assertEqual(walk_args.walk_min_windows, 4)
        self.assertEqual(walk_args.walk_min_accepted_windows, 3)
        self.assertEqual(walk_args.walk_min_accepted_ratio, 0.75)
        self.assertEqual(walk_args.walk_min_train_span_hours, 6.0)
        self.assertEqual(walk_args.walk_min_test_span_hours, 2.0)
        self.assertTrue(walk_args.strict_research)
        postprocess_args = parser.parse_args(
            [
                "funding-postprocess",
                "--input",
                "collect.jsonl",
                "--manifest",
                "collect.manifest.json",
                "--rank-output",
                "rank.json",
                "--backtest-output",
                "backtest.json",
                "--oos-output",
                "oos.json",
                "--walk-forward-output",
                "walk.json",
                "--postprocess-output",
                "postprocess.json",
                "--min-regime-observations",
                "6",
                "--min-perp-volume-24h-quote",
                "2000000",
                "--min-spot-top-notional-quote",
                "400",
                "--max-basis-std-bps",
                "3",
                "--max-avg-spot-spread-bps",
                "10",
                "--max-avg-perp-spread-bps",
                "8",
                "--min-basis-bps",
                "3.5",
                "--max-break-even-hours",
                "60",
                "--accept-min-trades",
                "20",
                "--accept-min-win-rate",
                "0.6",
                "--accept-min-expectancy-quote",
                "0",
                "--accept-min-net-pnl-quote",
                "0",
                "--accept-max-drawdown-quote",
                "5",
                "--accept-min-profit-factor",
                "1.2",
                "--accept-min-markets",
                "3",
                "--accept-max-market-trade-share",
                "0.5",
                "--accept-min-exchanges",
                "2",
                "--accept-max-exchange-trade-share",
                "0.7",
                "--accept-min-profitable-windows",
                "4",
                "--accept-max-window-pnl-share",
                "0.45",
                "--stress-enabled",
                "--stress-adverse-basis-bps",
                "10",
                "--stress-spread-widen-bps",
                "5",
                "--stress-funding-flip-bps",
                "2",
                "--stress-min-net-pnl-quote",
                "0",
                "--stress-max-drawdown-quote",
                "5",
                "--oos-train-fraction",
                "0.65",
                "--oos-min-train-rows",
                "30",
                "--oos-min-rows",
                "12",
                "--oos-min-train-span-hours",
                "6",
                "--oos-min-span-hours",
                "8",
                "--walk-train-rows",
                "40",
                "--walk-test-rows",
                "10",
                "--walk-step-rows",
                "10",
                "--walk-min-windows",
                "3",
                "--walk-min-accepted-windows",
                "2",
                "--walk-min-accepted-ratio",
                "0.67",
                "--walk-min-train-span-hours",
                "8",
                "--walk-min-test-span-hours",
                "4",
                "--quality-min-rows",
                "100",
                "--quality-min-markets",
                "4",
                "--quality-min-completed-cycles",
                "10",
                "--quality-min-unique-cycles",
                "9",
                "--quality-max-error-rate",
                "0.25",
                "--quality-max-cycle-market-duplicate-rate",
                "0.01",
                "--quality-required-row-fields",
                "spot_top_min_notional_quote,spot_bid_qty",
                "--quality-min-required-row-field-presence",
                "0.9",
                "--allow-partial",
            ]
        )
        self.assertEqual(postprocess_args.command, "funding-postprocess")
        self.assertTrue(postprocess_args.allow_partial)
        self.assertEqual(postprocess_args.min_regime_observations, 6)
        self.assertEqual(postprocess_args.min_perp_volume_24h_quote, 2_000_000)
        self.assertEqual(postprocess_args.min_spot_top_notional_quote, 400.0)
        self.assertEqual(postprocess_args.max_basis_std_bps, 3.0)
        self.assertEqual(postprocess_args.max_avg_spot_spread_bps, 10.0)
        self.assertEqual(postprocess_args.max_avg_perp_spread_bps, 8.0)
        self.assertEqual(postprocess_args.min_basis_bps, 3.5)
        self.assertEqual(postprocess_args.max_break_even_hours, 60.0)
        self.assertEqual(postprocess_args.oos_output, "oos.json")
        self.assertEqual(postprocess_args.postprocess_output, "postprocess.json")
        self.assertEqual(postprocess_args.oos_train_fraction, 0.65)
        self.assertEqual(postprocess_args.oos_min_train_rows, 30)
        self.assertEqual(postprocess_args.oos_min_rows, 12)
        self.assertEqual(postprocess_args.oos_min_train_span_hours, 6.0)
        self.assertEqual(postprocess_args.oos_min_span_hours, 8.0)
        self.assertEqual(postprocess_args.walk_forward_output, "walk.json")
        self.assertEqual(postprocess_args.walk_train_rows, 40)
        self.assertEqual(postprocess_args.walk_test_rows, 10)
        self.assertEqual(postprocess_args.walk_step_rows, 10)
        self.assertEqual(postprocess_args.walk_min_windows, 3)
        self.assertEqual(postprocess_args.walk_min_accepted_windows, 2)
        self.assertEqual(postprocess_args.walk_min_accepted_ratio, 0.67)
        self.assertEqual(postprocess_args.walk_min_train_span_hours, 8.0)
        self.assertEqual(postprocess_args.walk_min_test_span_hours, 4.0)
        self.assertEqual(postprocess_args.quality_min_rows, 100)
        self.assertEqual(postprocess_args.quality_min_markets, 4)
        self.assertEqual(postprocess_args.quality_min_completed_cycles, 10)
        self.assertEqual(postprocess_args.quality_min_unique_cycles, 9)
        self.assertEqual(postprocess_args.quality_max_error_rate, 0.25)
        self.assertEqual(postprocess_args.quality_max_cycle_market_duplicate_rate, 0.01)
        self.assertEqual(postprocess_args.quality_required_row_fields, "spot_top_min_notional_quote,spot_bid_qty")
        self.assertEqual(postprocess_args.quality_min_required_row_field_presence, 0.9)
        self.assertEqual(postprocess_args.accept_min_trades, 20)
        self.assertEqual(postprocess_args.accept_min_win_rate, 0.6)
        self.assertEqual(postprocess_args.accept_min_expectancy_quote, 0.0)
        self.assertEqual(postprocess_args.accept_min_net_pnl_quote, 0.0)
        self.assertEqual(postprocess_args.accept_max_drawdown_quote, 5.0)
        self.assertEqual(postprocess_args.accept_min_profit_factor, 1.2)
        self.assertEqual(postprocess_args.accept_min_markets, 3)
        self.assertEqual(postprocess_args.accept_max_market_trade_share, 0.5)
        self.assertEqual(postprocess_args.accept_min_exchanges, 2)
        self.assertEqual(postprocess_args.accept_max_exchange_trade_share, 0.7)
        self.assertEqual(postprocess_args.accept_min_profitable_windows, 4)
        self.assertEqual(postprocess_args.accept_max_window_pnl_share, 0.45)
        self.assertTrue(postprocess_args.stress_enabled)
        self.assertEqual(postprocess_args.stress_adverse_basis_bps, 10.0)
        self.assertEqual(postprocess_args.stress_spread_widen_bps, 5.0)
        self.assertEqual(postprocess_args.stress_funding_flip_bps, 2.0)
        self.assertEqual(postprocess_args.stress_min_net_pnl_quote, 0.0)
        self.assertEqual(postprocess_args.stress_max_drawdown_quote, 5.0)
        finalize_args = parser.parse_args(
            [
                "funding-finalize",
                "--input",
                "collect.jsonl",
                "--manifest",
                "collect.manifest.json",
                "--postprocess-output",
                "postprocess.json",
                "--walk-forward-output",
                "walk_final.json",
                "--paper-plan-output",
                "paper_plan.json",
                "--paper-output",
                "paper_forward.jsonl",
                "--stress-enabled",
                "--stress-adverse-basis-bps",
                "1",
                "--min-spot-top-notional-quote",
                "450",
                "--min-basis-bps",
                "4.5",
                "--max-break-even-hours",
                "72",
                "--accept-min-markets",
                "4",
                "--accept-max-market-trade-share",
                "0.4",
                "--accept-min-exchanges",
                "2",
                "--accept-max-exchange-trade-share",
                "0.6",
                "--accept-min-profitable-windows",
                "5",
                "--accept-max-window-pnl-share",
                "0.35",
                "--quality-min-rows",
                "200",
                "--quality-min-markets",
                "5",
                "--quality-min-completed-cycles",
                "20",
                "--quality-min-unique-cycles",
                "18",
                "--quality-max-error-rate",
                "0.2",
                "--quality-max-cycle-market-duplicate-rate",
                "0.02",
                "--quality-required-row-fields",
                "spot_top_min_notional_quote",
                "--quality-min-required-row-field-presence",
                "0.95",
                "--oos-min-train-span-hours",
                "12",
                "--oos-min-span-hours",
                "16",
                "--walk-train-rows",
                "60",
                "--walk-test-rows",
                "20",
                "--walk-step-rows",
                "10",
                "--walk-min-windows",
                "5",
                "--walk-min-accepted-windows",
                "4",
                "--walk-min-accepted-ratio",
                "0.8",
                "--walk-min-train-span-hours",
                "18",
                "--walk-min-test-span-hours",
                "6",
                "--min-forward-hours",
                "48",
                "--min-forward-rows",
                "40",
                "--min-forward-markets",
                "3",
            ]
        )
        self.assertEqual(finalize_args.command, "funding-finalize")
        self.assertEqual(finalize_args.postprocess_output, "postprocess.json")
        self.assertEqual(finalize_args.paper_plan_output, "paper_plan.json")
        self.assertEqual(finalize_args.paper_output, "paper_forward.jsonl")
        self.assertEqual(finalize_args.walk_forward_output, "walk_final.json")
        self.assertTrue(finalize_args.stress_enabled)
        self.assertEqual(finalize_args.stress_adverse_basis_bps, 1.0)
        self.assertEqual(finalize_args.min_spot_top_notional_quote, 450.0)
        self.assertEqual(finalize_args.min_basis_bps, 4.5)
        self.assertEqual(finalize_args.max_break_even_hours, 72.0)
        self.assertEqual(finalize_args.accept_min_markets, 4)
        self.assertEqual(finalize_args.accept_max_market_trade_share, 0.4)
        self.assertEqual(finalize_args.accept_min_exchanges, 2)
        self.assertEqual(finalize_args.accept_max_exchange_trade_share, 0.6)
        self.assertEqual(finalize_args.accept_min_profitable_windows, 5)
        self.assertEqual(finalize_args.accept_max_window_pnl_share, 0.35)
        self.assertEqual(finalize_args.quality_min_rows, 200)
        self.assertEqual(finalize_args.quality_min_markets, 5)
        self.assertEqual(finalize_args.quality_min_completed_cycles, 20)
        self.assertEqual(finalize_args.quality_min_unique_cycles, 18)
        self.assertEqual(finalize_args.quality_max_error_rate, 0.2)
        self.assertEqual(finalize_args.quality_max_cycle_market_duplicate_rate, 0.02)
        self.assertEqual(finalize_args.quality_required_row_fields, "spot_top_min_notional_quote")
        self.assertEqual(finalize_args.quality_min_required_row_field_presence, 0.95)
        self.assertEqual(finalize_args.oos_min_train_span_hours, 12.0)
        self.assertEqual(finalize_args.oos_min_span_hours, 16.0)
        self.assertEqual(finalize_args.walk_train_rows, 60)
        self.assertEqual(finalize_args.walk_test_rows, 20)
        self.assertEqual(finalize_args.walk_step_rows, 10)
        self.assertEqual(finalize_args.walk_min_windows, 5)
        self.assertEqual(finalize_args.walk_min_accepted_windows, 4)
        self.assertEqual(finalize_args.walk_min_accepted_ratio, 0.8)
        self.assertEqual(finalize_args.walk_min_train_span_hours, 18.0)
        self.assertEqual(finalize_args.walk_min_test_span_hours, 6.0)
        self.assertEqual(finalize_args.min_forward_hours, 48.0)
        self.assertEqual(finalize_args.min_forward_rows, 40)
        self.assertEqual(finalize_args.min_forward_markets, 3)

        final_review_args = parser.parse_args(
            [
                "funding-final-review",
                "--input",
                "collect.jsonl",
                "--output",
                "review.json",
                "--gate-report-output",
                "gate.json",
                "--regime-report-output",
                "regime.json",
                "--frontier-report-output",
                "frontier.json",
                "--sensitivity-output",
                "sensitivity.json",
                "--decision-report-output",
                "decision.json",
                "--wait-timeout-sec",
                "30",
                "--wait-poll-interval-sec",
                "5",
                "--wait-output",
                "wait.json",
                "--sensitivity-spot-fee-bps",
                "0,10",
                "--sensitivity-oos",
                "--sensitivity-walk-forward",
                "--strict-research",
            ]
        )
        self.assertEqual(final_review_args.command, "funding-final-review")
        self.assertEqual(final_review_args.output, "review.json")
        self.assertEqual(final_review_args.gate_report_output, "gate.json")
        self.assertEqual(final_review_args.regime_report_output, "regime.json")
        self.assertEqual(final_review_args.frontier_report_output, "frontier.json")
        self.assertEqual(final_review_args.sensitivity_output, "sensitivity.json")
        self.assertEqual(final_review_args.decision_report_output, "decision.json")
        self.assertEqual(final_review_args.wait_timeout_sec, 30.0)
        self.assertEqual(final_review_args.wait_poll_interval_sec, 5.0)
        self.assertEqual(final_review_args.wait_output, "wait.json")
        self.assertEqual(final_review_args.sensitivity_spot_fee_bps, "0,10")
        self.assertTrue(final_review_args.sensitivity_oos)
        self.assertTrue(final_review_args.sensitivity_walk_forward)
        self.assertTrue(final_review_args.strict_research)

        default_postprocess_args = parser.parse_args(["funding-postprocess"])
        _apply_funding_strict_research_preset(default_postprocess_args)
        self.assertFalse(default_postprocess_args.strict_research)
        self.assertFalse(default_postprocess_args.stress_enabled)
        self.assertIsNone(default_postprocess_args.oos_output)
        self.assertIsNone(default_postprocess_args.walk_forward_output)
        self.assertEqual(default_postprocess_args.quality_min_rows, 1)

        strict_postprocess_args = parser.parse_args(["funding-postprocess", "--strict-research", "--allow-partial"])
        _apply_funding_strict_research_preset(strict_postprocess_args)
        self.assertTrue(strict_postprocess_args.strict_research)
        self.assertFalse(strict_postprocess_args.allow_partial)
        self.assertTrue(strict_postprocess_args.stress_enabled)
        self.assertEqual(strict_postprocess_args.min_spot_top_notional_quote, 500.0)
        self.assertEqual(strict_postprocess_args.min_basis_bps, 0.0)
        self.assertEqual(strict_postprocess_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_postprocess_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_postprocess_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_postprocess_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_postprocess_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_postprocess_args.quality_required_row_fields, "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote")
        self.assertEqual(strict_postprocess_args.quality_min_required_row_field_presence, 1.0)
        self.assertEqual(strict_postprocess_args.oos_output, AUTO_FUNDING_OOS_OUTPUT)
        self.assertEqual(strict_postprocess_args.walk_forward_output, AUTO_FUNDING_WALK_FORWARD_OUTPUT)
        self.assertEqual(strict_postprocess_args.stress_adverse_basis_bps, 5.0)
        self.assertEqual(strict_postprocess_args.stress_spread_widen_bps, 2.0)
        self.assertEqual(strict_postprocess_args.stress_funding_flip_bps, 2.0)
        self.assertEqual(strict_postprocess_args.oos_min_train_span_hours, 6.0)
        self.assertEqual(strict_postprocess_args.oos_min_span_hours, 6.0)
        self.assertEqual(strict_postprocess_args.walk_min_windows, 3)
        self.assertEqual(strict_postprocess_args.walk_min_accepted_windows, 3)
        self.assertEqual(strict_postprocess_args.walk_min_accepted_ratio, 1.0)
        self.assertEqual(strict_postprocess_args.walk_min_train_span_hours, 6.0)
        self.assertEqual(strict_postprocess_args.walk_min_test_span_hours, 6.0)
        self.assertEqual(strict_postprocess_args.quality_min_rows, 1000)
        self.assertEqual(strict_postprocess_args.quality_min_markets, 5)
        self.assertEqual(strict_postprocess_args.quality_min_completed_cycles, 250)
        self.assertEqual(strict_postprocess_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_postprocess_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_postprocess_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_postprocess_args.quality_max_error_rate, 0.30)
        self.assertEqual(strict_postprocess_args.quality_max_cycle_market_duplicate_rate, 0.01)
        self.assertEqual(strict_postprocess_args.accept_min_markets, 2)
        self.assertEqual(strict_postprocess_args.accept_max_market_trade_share, 0.65)
        self.assertEqual(strict_postprocess_args.accept_min_exchanges, 2)
        self.assertEqual(strict_postprocess_args.accept_max_exchange_trade_share, 0.75)
        self.assertEqual(strict_postprocess_args.accept_min_profitable_windows, 3)
        self.assertEqual(strict_postprocess_args.accept_max_window_pnl_share, 0.60)

        strict_finalize_args = parser.parse_args(["funding-finalize", "--strict-research"])
        _apply_funding_strict_research_preset(strict_finalize_args)
        self.assertTrue(strict_finalize_args.strict_research)
        self.assertTrue(strict_finalize_args.stress_enabled)
        self.assertEqual(strict_finalize_args.min_spot_top_notional_quote, 500.0)
        self.assertEqual(strict_finalize_args.min_basis_bps, 0.0)
        self.assertEqual(strict_finalize_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_finalize_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_finalize_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_finalize_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_finalize_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_finalize_args.quality_required_row_fields, "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote")
        self.assertEqual(strict_finalize_args.quality_min_required_row_field_presence, 1.0)
        self.assertEqual(strict_finalize_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_finalize_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_finalize_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_finalize_args.min_forward_hours, 24.0)
        self.assertEqual(strict_finalize_args.min_forward_rows, 100)
        self.assertEqual(strict_finalize_args.min_forward_markets, 2)
        self.assertEqual(strict_finalize_args.accept_min_exchanges, 2)
        self.assertEqual(strict_finalize_args.accept_max_exchange_trade_share, 0.75)
        self.assertEqual(strict_finalize_args.walk_min_windows, 3)
        self.assertEqual(strict_finalize_args.walk_min_accepted_windows, 3)
        self.assertEqual(strict_finalize_args.walk_min_accepted_ratio, 1.0)
        self.assertEqual(strict_finalize_args.walk_min_train_span_hours, 6.0)
        self.assertEqual(strict_finalize_args.walk_min_test_span_hours, 6.0)

        strict_final_review_args = parser.parse_args(["funding-final-review", "--strict-research"])
        _apply_funding_strict_research_preset(strict_final_review_args)
        self.assertTrue(strict_final_review_args.strict_research)
        self.assertTrue(strict_final_review_args.stress_enabled)
        self.assertEqual(strict_final_review_args.min_spot_top_notional_quote, 500.0)
        self.assertEqual(strict_final_review_args.min_basis_bps, 0.0)
        self.assertEqual(strict_final_review_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_final_review_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_final_review_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_final_review_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_final_review_args.quality_min_rows, 1000)
        self.assertEqual(strict_final_review_args.quality_min_markets, 5)
        self.assertEqual(strict_final_review_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_final_review_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_final_review_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_final_review_args.accept_min_exchanges, 2)
        self.assertEqual(strict_final_review_args.min_forward_rows, 100)

        strict_status_args = parser.parse_args(["funding-status", "--strict-research"])
        _apply_funding_strict_research_preset(strict_status_args)
        self.assertTrue(strict_status_args.strict_research)
        self.assertEqual(strict_status_args.quality_min_rows, 1000)
        self.assertEqual(strict_status_args.quality_min_markets, 5)
        self.assertEqual(strict_status_args.quality_min_completed_cycles, 250)
        self.assertEqual(strict_status_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_status_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_status_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_status_args.quality_max_error_rate, 0.30)
        self.assertEqual(strict_status_args.quality_max_cycle_market_duplicate_rate, 0.01)
        self.assertEqual(strict_status_args.quality_required_row_fields, "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote")
        self.assertEqual(strict_status_args.quality_min_required_row_field_presence, 1.0)
        strict_wait_args = parser.parse_args(["funding-wait-ready", "--strict-research"])
        _apply_funding_strict_research_preset(strict_wait_args)
        self.assertTrue(strict_wait_args.strict_research)
        self.assertEqual(strict_wait_args.quality_min_rows, 1000)
        self.assertEqual(strict_wait_args.quality_min_markets, 5)
        self.assertEqual(strict_wait_args.quality_min_completed_cycles, 250)
        self.assertEqual(strict_wait_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_wait_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_wait_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_wait_args.quality_max_error_rate, 0.30)
        self.assertEqual(strict_wait_args.quality_required_row_fields, "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote")
        strict_goal_audit_args = parser.parse_args(["funding-goal-audit", "--strict-research"])
        _apply_funding_strict_research_preset(strict_goal_audit_args)
        self.assertTrue(strict_goal_audit_args.strict_research)
        self.assertEqual(strict_goal_audit_args.quality_min_rows, 1000)
        self.assertEqual(strict_goal_audit_args.quality_min_markets, 5)
        self.assertEqual(strict_goal_audit_args.quality_min_completed_cycles, 250)
        self.assertEqual(strict_goal_audit_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_goal_audit_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_goal_audit_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_goal_audit_args.quality_max_error_rate, 0.30)
        self.assertEqual(strict_goal_audit_args.quality_required_row_fields, "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote")
        strict_rank_args = parser.parse_args(["funding-rank", "--strict-research"])
        _apply_funding_strict_research_preset(strict_rank_args)
        self.assertTrue(strict_rank_args.strict_research)
        self.assertEqual(strict_rank_args.min_basis_bps, 0.0)
        self.assertEqual(strict_rank_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_rank_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_rank_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_rank_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_rank_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_rank_args.min_spot_top_notional_quote, 500.0)
        strict_gate_report_args = parser.parse_args(["funding-gate-report", "--strict-research"])
        _apply_funding_strict_research_preset(strict_gate_report_args)
        self.assertTrue(strict_gate_report_args.strict_research)
        self.assertEqual(strict_gate_report_args.min_basis_bps, 0.0)
        self.assertEqual(strict_gate_report_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_gate_report_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_gate_report_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_gate_report_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_gate_report_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_gate_report_args.min_spot_top_notional_quote, 500.0)
        strict_regime_report_args = parser.parse_args(["funding-regime-report", "--strict-research"])
        _apply_funding_strict_research_preset(strict_regime_report_args)
        self.assertTrue(strict_regime_report_args.strict_research)
        self.assertEqual(strict_regime_report_args.min_basis_bps, 0.0)
        self.assertEqual(strict_regime_report_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_regime_report_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_regime_report_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_regime_report_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_regime_report_args.min_spot_top_notional_quote, 500.0)
        strict_frontier_report_args = parser.parse_args(["funding-frontier-report", "--strict-research"])
        _apply_funding_strict_research_preset(strict_frontier_report_args)
        self.assertTrue(strict_frontier_report_args.strict_research)
        self.assertEqual(strict_frontier_report_args.min_basis_bps, 0.0)
        self.assertEqual(strict_frontier_report_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_frontier_report_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_frontier_report_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_frontier_report_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_frontier_report_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_frontier_report_args.min_spot_top_notional_quote, 500.0)
        strict_decision_report_args = parser.parse_args(["funding-decision-report", "--strict-research"])
        _apply_funding_strict_research_preset(strict_decision_report_args)
        self.assertTrue(strict_decision_report_args.strict_research)
        self.assertEqual(strict_decision_report_args.quality_min_rows, 1000)
        self.assertEqual(strict_decision_report_args.quality_min_markets, 5)
        self.assertEqual(strict_decision_report_args.quality_min_completed_cycles, 250)
        self.assertEqual(strict_decision_report_args.quality_min_unique_cycles, 250)
        self.assertEqual(strict_decision_report_args.quality_min_avg_rows_per_cycle, 20.0)
        self.assertEqual(strict_decision_report_args.quality_min_min_rows_per_cycle, 20)
        self.assertEqual(strict_decision_report_args.quality_max_error_rate, 0.30)
        self.assertEqual(strict_decision_report_args.quality_required_row_fields, "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote")
        strict_sensitivity_args = parser.parse_args(["funding-sensitivity", "--strict-research"])
        _apply_funding_strict_research_preset(strict_sensitivity_args)
        self.assertTrue(strict_sensitivity_args.strict_research)
        self.assertEqual(strict_sensitivity_args.min_basis_bps, 0.0)
        self.assertEqual(strict_sensitivity_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_sensitivity_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_sensitivity_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_sensitivity_args.spread_risk_multiplier, 0.5)
        self.assertTrue(strict_sensitivity_args.stress_enabled)
        self.assertTrue(strict_sensitivity_args.sensitivity_oos)
        self.assertTrue(strict_sensitivity_args.sensitivity_walk_forward)
        self.assertEqual(strict_sensitivity_args.oos_min_train_span_hours, 6.0)
        self.assertEqual(strict_sensitivity_args.oos_min_span_hours, 6.0)
        self.assertEqual(strict_sensitivity_args.walk_min_windows, 3)
        self.assertEqual(strict_sensitivity_args.walk_min_accepted_windows, 3)
        self.assertEqual(strict_sensitivity_args.walk_min_accepted_ratio, 1.0)
        self.assertEqual(strict_sensitivity_args.walk_min_train_span_hours, 6.0)
        self.assertEqual(strict_sensitivity_args.walk_min_test_span_hours, 6.0)
        strict_walk_args = parser.parse_args(["funding-walk-forward", "--strict-research"])
        _apply_funding_strict_research_preset(strict_walk_args)
        self.assertTrue(strict_walk_args.strict_research)
        self.assertTrue(strict_walk_args.stress_enabled)
        self.assertEqual(strict_walk_args.min_basis_bps, 0.0)
        self.assertEqual(strict_walk_args.min_expected_net_carry_bps, 0.0)
        self.assertEqual(strict_walk_args.min_risk_adjusted_edge_bps, 0.0)
        self.assertEqual(strict_walk_args.basis_risk_multiplier, 1.0)
        self.assertEqual(strict_walk_args.spread_risk_multiplier, 0.5)
        self.assertEqual(strict_walk_args.max_break_even_hours, 24.0)
        self.assertEqual(strict_walk_args.min_spot_top_notional_quote, 500.0)
        self.assertEqual(strict_walk_args.walk_min_windows, 3)
        self.assertEqual(strict_walk_args.walk_min_accepted_windows, 3)
        self.assertEqual(strict_walk_args.walk_min_accepted_ratio, 1.0)
        self.assertEqual(strict_walk_args.walk_min_train_span_hours, 6.0)
        self.assertEqual(strict_walk_args.walk_min_test_span_hours, 6.0)
        paper_args = parser.parse_args(
            [
                "funding-paper-plan",
                "--postprocess",
                "postprocess.json",
                "--decision-report",
                "decision.json",
                "--output",
                "paper_plan.json",
                "--paper-output",
                "paper_forward.jsonl",
                "--min-forward-hours",
                "48",
                "--min-forward-rows",
                "40",
                "--min-forward-markets",
                "3",
            ]
        )
        self.assertEqual(paper_args.command, "funding-paper-plan")
        self.assertEqual(paper_args.postprocess, "postprocess.json")
        self.assertEqual(paper_args.decision_report, "decision.json")
        self.assertEqual(paper_args.output, "paper_plan.json")
        self.assertEqual(paper_args.paper_output, "paper_forward.jsonl")
        self.assertEqual(paper_args.min_forward_hours, 48.0)
        self.assertEqual(paper_args.min_forward_rows, 40)
        self.assertEqual(paper_args.min_forward_markets, 3)
        paper_forward_args = parser.parse_args(
            [
                "funding-paper-forward",
                "--plan",
                "paper_plan.json",
                "--input",
                "forward.jsonl",
                "--output",
                "paper_forward.jsonl",
                "--summary-output",
                "paper_forward_summary.json",
                "--allow-source-input",
            ]
        )
        self.assertEqual(paper_forward_args.command, "funding-paper-forward")
        self.assertEqual(paper_forward_args.plan, "paper_plan.json")
        self.assertEqual(paper_forward_args.input, "forward.jsonl")
        self.assertEqual(paper_forward_args.output, "paper_forward.jsonl")
        self.assertEqual(paper_forward_args.summary_output, "paper_forward_summary.json")
        self.assertTrue(paper_forward_args.allow_source_input)
        paper_decision_args = parser.parse_args(
            [
                "funding-paper-decision-report",
                "--summary",
                "paper_forward_summary.json",
                "--plan",
                "paper_plan.json",
                "--output",
                "paper_decision.json",
            ]
        )
        self.assertEqual(paper_decision_args.command, "funding-paper-decision-report")
        self.assertEqual(paper_decision_args.summary, "paper_forward_summary.json")
        self.assertEqual(paper_decision_args.plan, "paper_plan.json")
        self.assertEqual(paper_decision_args.output, "paper_decision.json")
        goal_audit_args = parser.parse_args(
            [
                "funding-goal-audit",
                "--input",
                "collect.jsonl",
                "--manifest",
                "collect.manifest.json",
                "--final-review",
                "final_review.json",
                "--paper-plan",
                "paper_plan.json",
                "--paper-summary",
                "paper_summary.json",
                "--paper-decision",
                "paper_decision.json",
                "--output",
                "goal_audit.json",
                "--strict-research",
            ]
        )
        self.assertEqual(goal_audit_args.command, "funding-goal-audit")
        self.assertEqual(goal_audit_args.input, "collect.jsonl")
        self.assertEqual(goal_audit_args.final_review, "final_review.json")
        self.assertEqual(goal_audit_args.paper_plan, "paper_plan.json")
        self.assertEqual(goal_audit_args.paper_summary, "paper_summary.json")
        self.assertEqual(goal_audit_args.paper_decision, "paper_decision.json")
        self.assertEqual(goal_audit_args.output, "goal_audit.json")
        self.assertTrue(goal_audit_args.strict_research)

    def test_cmd_funding_collect_passes_resume_to_collector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = AppConfig(
                exchange=ExchangeConfig(),
                strategy=StrategyConfig(),
                risk=RiskConfig(),
                paths=PathsConfig(funding_dir=str(tmp_path), universe_dir=str(tmp_path)),
            )
            universe = tmp_path / "universe.csv"
            universe.write_text("symbol,base,quote\nHYPEUSDT,HYPE,USDT\n", encoding="utf-8")
            output = tmp_path / "collect.jsonl"
            with patch("cli.collect_funding_file", return_value={"ok": True}) as collect, patch("builtins.print"):
                cmd_funding_collect(
                    cfg,
                    exchanges="mexc",
                    universe_path=str(universe),
                    quote="USDT",
                    max_symbols=10,
                    max_pairs_per_exchange=5,
                    cycles=3,
                    poll_interval_sec=0.0,
                    notional_quote=100.0,
                    max_spot_spread_bps=30.0,
                    max_perp_spread_bps=30.0,
                    max_abs_basis_bps=500.0,
                    min_basis_bps=0.0,
                    min_funding_rate=0.0,
                    min_volume_24h_quote=0.0,
                    min_spot_top_notional_quote=250.0,
                    spot_fee_bps=10.0,
                    perp_fee_bps=7.5,
                    slippage_bps=1.0,
                    target_hold_intervals=1.0,
                    min_expected_net_carry_bps=-1e9,
                    max_break_even_hours=24.0,
                    resume=True,
                    output_path=str(output),
                )

            self.assertTrue(collect.call_args.kwargs["resume"])
            self.assertEqual(collect.call_args.kwargs["cycles"], 3)
            self.assertEqual(collect.call_args.kwargs["cfg"].min_spot_top_notional_quote, 250.0)
            self.assertEqual(collect.call_args.kwargs["cfg"].min_basis_bps, 0.0)
            self.assertEqual(collect.call_args.kwargs["cfg"].max_break_even_hours, 24.0)

    def test_main_dispatches_funding_collect_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = AppConfig(
                exchange=ExchangeConfig(),
                strategy=StrategyConfig(),
                risk=RiskConfig(),
                paths=PathsConfig(funding_dir=str(tmp_path), universe_dir=str(tmp_path)),
            )
            universe = tmp_path / "universe.csv"
            universe.write_text("symbol,base,quote\nHYPEUSDT,HYPE,USDT\n", encoding="utf-8")
            output = tmp_path / "collect.jsonl"
            argv = [
                "trading-mvp",
                "--config",
                "ignored.json",
                "funding-collect",
                "--universe",
                str(universe),
                "--output",
                str(output),
                "--cycles",
                "1",
                "--min-basis-bps",
                "0",
                "--max-break-even-hours",
                "24",
                "--resume",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch("cli.load_config", return_value=cfg),
                patch("cli.collect_funding_file", return_value={"ok": True}) as collect,
                patch("builtins.print"),
            ):
                main()

            self.assertTrue(collect.call_args.kwargs["resume"])
            self.assertEqual(collect.call_args.kwargs["cfg"].min_basis_bps, 0.0)
            self.assertEqual(collect.call_args.kwargs["cfg"].max_break_even_hours, 24.0)


if __name__ == "__main__":
    unittest.main()
