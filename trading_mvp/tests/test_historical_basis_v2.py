from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from costs import base_api_cost_profile  # noqa: E402
import historical_basis_v2 as basis_v2  # noqa: E402
from historical_basis_v2 import (  # noqa: E402
    DAY_SEC,
    HOUR_SEC,
    HYPOTHESIS_ID,
    BasisBar,
    FundingEvent,
    TradeResult,
    aggregate_1h_to_4h,
    build_historical_basis_v2_plan,
    build_historical_basis_v2_plan_from_preflight,
    build_split_contract,
    compute_funding_cashflow,
    historical_oos_verdict,
    label_split_timestamp,
    main,
    sha256_json,
    simulate_basis_episodes,
    validate_historical_basis_v2_plan,
)


def _asset(index: int) -> dict[str, object]:
    base = f"A{index:02d}"
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": 179,
        "binance_spot": False,
        "categories": [],
        "availability_rank": index,
    }


def _bar(
    ts: int,
    *,
    base: str = "AAA",
    spread_bps: float = 0.0,
    cheap_venue: str = "mexc",
    mexc_open: float = 100.0,
    gate_open: float = 100.0,
    mexc_close: float | None = None,
    gate_close: float | None = None,
    volume: float = 1_000_000.0,
) -> BasisBar:
    index = 100.0
    high_basis_mark = index * (1.0 + spread_bps / 10_000.0)
    if cheap_venue == "mexc":
        mexc_mark, gate_mark = index, high_basis_mark
    else:
        mexc_mark, gate_mark = high_basis_mark, index
    return BasisBar(
        ts=ts,
        base=base,
        mexc_trade_open=mexc_open,
        mexc_trade_close=mexc_open if mexc_close is None else mexc_close,
        mexc_mark_close=mexc_mark,
        mexc_index_close=index,
        mexc_volume_quote=volume,
        gateio_trade_open=gate_open,
        gateio_trade_close=gate_open if gate_close is None else gate_close,
        gateio_mark_close=gate_mark,
        gateio_index_close=index,
        gateio_volume_quote=volume,
    )


def _passing_metrics(episodes: int) -> dict[str, object]:
    return {
        "independent_episode_count": episodes,
        "unique_dates": 25,
        "base_count": 8,
        "price_only_expectancy_quote": 1.0,
        "total_expectancy_quote": 1.1,
        "profit_factor": 1.5,
        "positive_fixed_subperiods": 4,
        "normal_net_pnl_quote": 40.0,
        "stress_net_pnl_quote": 5.0,
        "stress_expectancy_quote": 0.1,
        "cluster_bootstrap_lower_95_quote": 0.01,
        "direction_net_pnl_quote": {"mexc_long": 1.0, "gateio_long": 1.0},
        "max_concentration_share": 0.20,
        "max_drawdown_fraction": 0.05,
    }


def _trade_result(
    episode_id: str,
    *,
    price_only_pnl: float,
    funding_pnl: float,
    stress: bool,
) -> TradeResult:
    return TradeResult(
        episode_id=episode_id,
        base="AAA",
        signal_ts=0,
        signal_available_ts=HOUR_SEC,
        entry_ts=HOUR_SEC,
        exit_signal_ts=2 * HOUR_SEC,
        exit_ts=3 * HOUR_SEC,
        long_venue="mexc",
        short_venue="gateio",
        exit_reason="convergence",
        long_entry_price=100.0,
        short_entry_price=100.0,
        long_exit_price=100.0,
        short_exit_price=100.0,
        gross_price_pnl_quote=price_only_pnl,
        funding_pnl_quote=funding_pnl,
        cost_quote=0.0,
        price_only_net_pnl_quote=price_only_pnl,
        net_pnl_quote=price_only_pnl + funding_pnl,
        holding_sec=2 * HOUR_SEC,
        stress=stress,
        funding_event_ids=(),
    )


class HistoricalBasisV2SchemaTests(unittest.TestCase):
    def test_basis_bar_has_no_funding_fields_and_funding_event_is_immutable(self) -> None:
        self.assertFalse(
            any("funding" in name.lower() for name in BasisBar.__dataclass_fields__)
        )
        event = FundingEvent("gate", "aaa", 3_601, 0.0001)
        self.assertEqual(event.venue, "gateio")
        self.assertEqual(event.base, "AAA")
        self.assertEqual(
            event.event_id,
            FundingEvent("gateio", "AAA", 3_601, 0.0001).event_id,
        )
        with self.assertRaises(FrozenInstanceError):
            event.rate = 0.0  # type: ignore[misc]

    def test_funding_event_preserves_stable_external_ledger_identity(self) -> None:
        event = FundingEvent.from_dict(
            {
                "venue": "mexc",
                "base": "AAA",
                "settlement_ts": 3_601,
                "funding_rate": 0.0001,
                "event_id": "quality-ledger-event-id",
            }
        )
        self.assertEqual(event.event_id, "quality-ledger-event-id")
        self.assertEqual(
            event.settlement_identity,
            FundingEvent("mexc", "AAA", 3_601, 0.0001).settlement_identity,
        )

    def test_split_contract_has_exact_labels_and_five_fixed_oos_subperiods(self) -> None:
        split = build_split_contract(0, 179 * DAY_SEC)
        self.assertEqual(split["warmup"]["days"], 14)
        self.assertEqual(split["train"]["days"], 85)
        self.assertEqual(split["oos"]["days"], 80)
        self.assertEqual(len(split["oos_subperiods"]), 5)
        self.assertEqual(
            [row["label"] for row in split["oos_subperiods"]],
            [f"oos_subperiod_{index}" for index in range(1, 6)],
        )
        self.assertTrue(all(row["days"] == 16 for row in split["oos_subperiods"]))
        self.assertEqual(label_split_timestamp(split, 0), "warmup")
        self.assertEqual(label_split_timestamp(split, 14 * DAY_SEC), "train")
        self.assertEqual(label_split_timestamp(split, 99 * DAY_SEC), "oos_subperiod_1")
        self.assertIsNone(label_split_timestamp(split, 179 * DAY_SEC))


class HistoricalBasisV2PlanTests(unittest.TestCase):
    def test_plan_freezes_v2_contract_and_derives_threshold_from_cost_profile(self) -> None:
        profile = replace(base_api_cost_profile(), slippage_bps_per_order=3.0)
        plan = build_historical_basis_v2_plan(
            [_asset(index) for index in range(8)],
            window_end_ts=179 * DAY_SEC,
            cost_profile=profile,
            frozen_at_utc="2026-07-16T00:00:00+00:00",
        )
        self.assertEqual(plan["hypothesis"]["id"], HYPOTHESIS_ID)
        self.assertEqual(plan["sample_plan"]["interval"], "1h")
        self.assertEqual(plan["sample_plan"]["total_closed_days"], 179)
        self.assertEqual(plan["sample_plan"]["warmup_days"], 14)
        self.assertEqual(plan["sample_plan"]["train_days"], 85)
        self.assertEqual(plan["sample_plan"]["oos_days"], 80)
        self.assertEqual(plan["sample_plan"]["fixed_oos_subperiod_count"], 5)
        self.assertEqual(plan["sample_plan"]["fixed_oos_subperiod_days"], 16)
        self.assertEqual(
            plan["acceptance_gates"]["minimum_four_hour_independent_episodes"], 1
        )
        self.assertTrue(
            plan["acceptance_gates"]["four_hour_price_only_must_be_nonnegative"]
        )
        self.assertTrue(
            plan["acceptance_gates"]["four_hour_total_net_must_be_nonnegative"]
        )
        expected = (
            plan["economics"]["stress_cycle_cost"]["total_bps"]
            + plan["strategy"]["exit_threshold_bps"]
            + plan["strategy"]["safety_margin_bps"]
        )
        self.assertEqual(plan["strategy"]["entry_threshold_bps"], expected)
        self.assertNotEqual(plan["strategy"]["entry_threshold_bps"], 128.0)
        self.assertNotIn("walk", json.dumps(plan, sort_keys=True).lower())
        self.assertEqual(validate_historical_basis_v2_plan(plan)["plan_hash"], plan["plan_hash"])

    def test_default_frozen_costs_are_78_normal_88_stress_and_128_entry(self) -> None:
        plan = build_historical_basis_v2_plan(
            [_asset(index) for index in range(8)],
            window_end_ts=179 * DAY_SEC,
        )
        self.assertEqual(plan["economics"]["normal_cycle_cost"]["total_bps"], 78.0)
        self.assertEqual(plan["economics"]["stress_cycle_cost"]["total_bps"], 88.0)
        self.assertEqual(plan["strategy"]["entry_threshold_bps"], 128.0)

    def test_plan_hash_is_deterministic_and_tampering_is_rejected(self) -> None:
        first = build_historical_basis_v2_plan(
            [_asset(index) for index in range(8)],
            window_end_ts=179 * DAY_SEC,
            frozen_at_utc="2026-07-16T00:00:00+00:00",
        )
        second = build_historical_basis_v2_plan(
            list(reversed([_asset(index) for index in range(8)])),
            window_end_ts=179 * DAY_SEC,
            frozen_at_utc="2026-07-16T00:00:01+00:00",
        )
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        tampered = copy.deepcopy(first)
        tampered["strategy"]["maximum_holding_hours"] = 71
        with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
            validate_historical_basis_v2_plan(tampered)

    def test_preflight_bound_plan_hash_depends_on_content_not_file_location(self) -> None:
        payload = {
            "schema": "trading_mvp_historical_basis_v2_preflight_v2",
            "verdict": "PREFLIGHT_ACCEPTED_NOT_COLLECTED",
            "window": {
                "window_start_sec": 0,
                "window_end_sec": 179 * DAY_SEC,
                "expected_candle_rows": 179 * 24,
                "interval": "[start,end)",
            },
            "universe": {
                "candidate_count": 8,
                "candidates": [_asset(index) for index in range(8)],
            },
            "data_access_audit": {
                "returns_read": False,
                "pnl_read": False,
                "signals_read": False,
                "oos_metrics_read": False,
                "liquidity_used_for_selection": False,
            },
        }
        payload["preflight_hash"] = sha256_json(payload)
        expected_preflight_hash = payload["preflight_hash"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_preflight = root / "first-preflight.json"
            second_preflight = root / "second-preflight.json"
            encoded = json.dumps(payload, sort_keys=True)
            first_preflight.write_text(encoded, encoding="utf-8")
            second_preflight.write_text(encoded, encoding="utf-8")
            first = build_historical_basis_v2_plan_from_preflight(
                first_preflight,
                root / "first-plan.json",
            )
            second = build_historical_basis_v2_plan_from_preflight(
                second_preflight,
                root / "second-plan.json",
            )
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(
            first["preflight_provenance"]["preflight_hash"],
            expected_preflight_hash,
        )

    def test_cli_plan_and_validate_plan_are_versioned_subcommands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = root / "preflight.json"
            preflight.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_historical_basis_v2_preflight_v1",
                        "verdict": "PREFLIGHT_ACCEPTED_NOT_COLLECTED",
                        "window": {
                            "window_start_sec": 0,
                            "window_end_sec": 179 * DAY_SEC,
                            "expected_candle_rows": 179 * 24,
                            "interval": "[start,end)",
                        },
                        "universe": {
                            "candidate_count": 8,
                            "candidates": [_asset(index) for index in range(8)],
                        },
                        "data_access_audit": {
                            "returns_read": False,
                            "pnl_read": False,
                            "signals_read": False,
                            "oos_metrics_read": False,
                            "liquidity_used_for_selection": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            plan_path = root / "plan.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "plan",
                            "--preflight",
                            str(preflight),
                            "--output",
                            str(plan_path),
                            "--max-runtime-sec",
                            "60",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["validate-plan", "--plan", str(plan_path)]),
                    0,
                )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["hypothesis"]["id"], HYPOTHESIS_ID)


class HistoricalBasisV2CausalityTests(unittest.TestCase):
    def test_signal_uses_closed_bar_entry_uses_next_open_and_exit_uses_next_open(self) -> None:
        bars = [
            _bar(0, spread_bps=100.0),
            _bar(HOUR_SEC, spread_bps=130.0),
            _bar(2 * HOUR_SEC, spread_bps=130.0, mexc_open=99.0, gate_open=101.0),
            _bar(3 * HOUR_SEC, spread_bps=10.0),
            _bar(4 * HOUR_SEC, spread_bps=10.0, mexc_open=100.0, gate_open=100.0),
        ]
        result = simulate_basis_episodes(
            bars,
            [],
            entry_threshold_bps=128.0,
            cycle_cost_bps=0.0,
        )
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.signal_ts, HOUR_SEC)
        self.assertEqual(trade.signal_available_ts, 2 * HOUR_SEC)
        self.assertEqual(trade.entry_ts, 2 * HOUR_SEC)
        self.assertEqual(trade.exit_signal_ts, 3 * HOUR_SEC)
        self.assertEqual(trade.exit_ts, 4 * HOUR_SEC)
        self.assertEqual(trade.long_entry_price, 99.0)
        self.assertEqual(trade.short_entry_price, 101.0)

    def test_entry_requires_a_fresh_crossing_from_below(self) -> None:
        bars = [
            _bar(0, spread_bps=130.0),
            _bar(HOUR_SEC, spread_bps=140.0),
            _bar(2 * HOUR_SEC, spread_bps=10.0),
            _bar(3 * HOUR_SEC, spread_bps=130.0),
            _bar(4 * HOUR_SEC, spread_bps=130.0),
            _bar(5 * HOUR_SEC, spread_bps=10.0),
            _bar(6 * HOUR_SEC, spread_bps=10.0),
        ]
        result = simulate_basis_episodes(
            bars,
            [],
            entry_threshold_bps=128.0,
            cycle_cost_bps=0.0,
        )
        self.assertEqual([trade.entry_ts for trade in result.trades], [4 * HOUR_SEC])

    def test_position_rearms_only_after_post_close_reset_and_later_recross(self) -> None:
        spreads = [100.0, 130.0, 130.0, 10.0, 130.0, 10.0, 130.0, 130.0, 10.0, 10.0]
        result = simulate_basis_episodes(
            [_bar(index * HOUR_SEC, spread_bps=spread) for index, spread in enumerate(spreads)],
            [],
            entry_threshold_bps=128.0,
            cycle_cost_bps=0.0,
        )
        self.assertEqual(
            [trade.entry_ts for trade in result.trades],
            [2 * HOUR_SEC, 7 * HOUR_SEC],
        )

    def test_max_hold_exits_at_first_contiguous_open_at_or_after_deadline(self) -> None:
        bars = [_bar(0, spread_bps=100.0)]
        bars.extend(_bar(index * HOUR_SEC, spread_bps=130.0) for index in range(1, 6))
        result = simulate_basis_episodes(
            bars,
            [],
            entry_threshold_bps=128.0,
            maximum_holding_hours=2,
            cycle_cost_bps=0.0,
        )
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].entry_ts, 2 * HOUR_SEC)
        self.assertEqual(result.trades[0].exit_ts, 4 * HOUR_SEC)
        self.assertEqual(result.trades[0].exit_reason, "max_hold")

    def test_non_contiguous_execution_invalidates_position_without_cross_gap_pnl(self) -> None:
        bars = [
            _bar(0, spread_bps=100.0),
            _bar(HOUR_SEC, spread_bps=130.0),
            _bar(2 * HOUR_SEC, spread_bps=130.0),
            _bar(4 * HOUR_SEC, spread_bps=10.0, mexc_open=1_000.0, gate_open=1.0),
        ]
        result = simulate_basis_episodes(
            bars,
            [],
            entry_threshold_bps=128.0,
            cycle_cost_bps=0.0,
        )
        self.assertEqual(result.trades, ())
        self.assertEqual(len(result.invalidated_positions), 1)
        self.assertEqual(result.invalidated_positions[0].reason, "non_contiguous_execution")


class HistoricalBasisV2FundingTests(unittest.TestCase):
    def test_funding_uses_half_open_position_interval_with_jitter_and_multiple_events(self) -> None:
        events = [
            FundingEvent("mexc", "AAA", HOUR_SEC - 1, 0.5),
            FundingEvent("mexc", "AAA", HOUR_SEC, 0.001),
            FundingEvent("gateio", "AAA", HOUR_SEC + 1, 0.002),
            FundingEvent("gateio", "AAA", HOUR_SEC + 2, 0.001),
            FundingEvent("gateio", "AAA", 2 * HOUR_SEC, 0.5),
        ]
        normal = compute_funding_cashflow(
            events,
            base="AAA",
            long_venue="mexc",
            short_venue="gateio",
            entry_ts=HOUR_SEC,
            exit_ts=2 * HOUR_SEC,
            notional_quote_per_leg=500.0,
            stress=False,
        )
        stress = compute_funding_cashflow(
            events,
            base="AAA",
            long_venue="mexc",
            short_venue="gateio",
            entry_ts=HOUR_SEC,
            exit_ts=2 * HOUR_SEC,
            notional_quote_per_leg=500.0,
            stress=True,
        )
        self.assertAlmostEqual(normal, 1.0)
        self.assertAlmostEqual(stress, 0.25)

    def test_duplicate_funding_event_identity_is_rejected_not_merged(self) -> None:
        event = FundingEvent("mexc", "AAA", HOUR_SEC, 0.001)
        with self.assertRaisesRegex(ValueError, "duplicate funding event"):
            compute_funding_cashflow(
                [event, event],
                base="AAA",
                long_venue="mexc",
                short_venue="gateio",
                entry_ts=HOUR_SEC,
                exit_ts=2 * HOUR_SEC,
                notional_quote_per_leg=500.0,
            )

    def test_conflicting_rates_at_same_venue_base_settlement_are_duplicate_identity(self) -> None:
        first = FundingEvent("mexc", "AAA", HOUR_SEC, 0.001)
        conflicting = FundingEvent("mexc", "AAA", HOUR_SEC, 0.002)
        self.assertEqual(first.event_id, conflicting.event_id)
        with self.assertRaisesRegex(ValueError, "duplicate funding event"):
            compute_funding_cashflow(
                [first, conflicting],
                base="AAA",
                long_venue="mexc",
                short_venue="gateio",
                entry_ts=HOUR_SEC,
                exit_ts=2 * HOUR_SEC,
                notional_quote_per_leg=500.0,
            )


class HistoricalBasisV2AcceptanceTests(unittest.TestCase):
    def test_four_hour_robustness_rejects_zero_episode_sample(self) -> None:
        helper = getattr(basis_v2, "compute_four_hour_robustness", None)
        self.assertIsNotNone(helper, "4h robustness helper is missing")
        result = helper([], [])
        self.assertFalse(result["passed"])
        self.assertIn("four_hour_no_independent_episodes", result["rejection_reasons"])

    def test_four_hour_funding_cannot_rescue_negative_price_only_pnl(self) -> None:
        helper = getattr(basis_v2, "compute_four_hour_robustness", None)
        self.assertIsNotNone(helper, "4h robustness helper is missing")
        normal = _trade_result(
            "episode-1", price_only_pnl=-1.0, funding_pnl=2.0, stress=False
        )
        stress = _trade_result(
            "episode-1", price_only_pnl=-2.0, funding_pnl=3.0, stress=True
        )
        result = helper([normal], [stress])
        self.assertFalse(result["passed"])
        self.assertEqual(result["normal_net_pnl_quote"], 1.0)
        self.assertEqual(result["stress_net_pnl_quote"], 1.0)
        self.assertIn(
            "four_hour_normal_price_only_net_pnl", result["rejection_reasons"]
        )
        self.assertIn(
            "four_hour_stress_price_only_net_pnl", result["rejection_reasons"]
        )

    def test_any_oos_scarcity_below_40_is_insufficient_never_reject(self) -> None:
        for count in (0, 19, 20, 39):
            with self.subTest(count=count):
                verdict, reasons = historical_oos_verdict(_passing_metrics(count))
                self.assertEqual(verdict, "INSUFFICIENT_DATA")
                self.assertEqual(reasons, ["oos_independent_episodes_below_40"])

    def test_40_or_more_episodes_can_accept_or_reject_on_economics(self) -> None:
        self.assertEqual(
            historical_oos_verdict(_passing_metrics(40)),
            ("ACCEPT_FOR_EXECUTION_PROBE", []),
        )
        failing = _passing_metrics(40)
        failing["price_only_expectancy_quote"] = -0.01
        verdict, reasons = historical_oos_verdict(failing)
        self.assertEqual(verdict, "REJECT")
        self.assertIn("price_only_expectancy", reasons)


class HistoricalBasisV2AggregationTests(unittest.TestCase):
    def test_four_hour_aggregation_uses_only_complete_immutable_one_hour_groups(self) -> None:
        bars = [
            _bar(
                index * HOUR_SEC,
                spread_bps=10.0 + index,
                mexc_open=100.0 + index,
                gate_open=200.0 + index,
                mexc_close=101.0 + index,
                gate_close=201.0 + index,
                volume=10.0 + index,
            )
            for index in range(5)
        ]
        before = tuple(asdict(bar) for bar in bars)
        aggregated = aggregate_1h_to_4h(bars)
        self.assertEqual(len(aggregated), 1)
        row = aggregated[0]
        self.assertEqual(row.ts, 0)
        self.assertEqual(row.mexc_trade_open, bars[0].mexc_trade_open)
        self.assertEqual(row.mexc_trade_close, bars[3].mexc_trade_close)
        self.assertEqual(row.gateio_trade_open, bars[0].gateio_trade_open)
        self.assertEqual(row.gateio_trade_close, bars[3].gateio_trade_close)
        self.assertEqual(row.mexc_mark_close, bars[3].mexc_mark_close)
        self.assertEqual(row.gateio_index_close, bars[3].gateio_index_close)
        self.assertEqual(row.mexc_volume_quote, sum(bar.mexc_volume_quote for bar in bars[:4]))
        self.assertEqual(tuple(asdict(bar) for bar in bars), before)


if __name__ == "__main__":
    unittest.main()
