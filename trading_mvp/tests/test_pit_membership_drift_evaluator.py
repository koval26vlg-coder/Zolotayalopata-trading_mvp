from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402
from pit_membership_drift_evaluator import (  # noqa: E402
    ActivationEvent,
    MarketSnapshot,
    SnapshotCycle,
    detect_activation_events_by_daily_segments,
    decide_verdict,
    detect_activation_events_by_segment,
    detect_activation_events,
    simulate_event,
    split_quality_dates,
)


def _snapshot(
    venue: str,
    base: str,
    mid: float,
    *,
    spread_bps: float = 10.0,
    volume: float = 1_000_000.0,
    bid_size_contracts: float = 100_000.0,
    ask_size_contracts: float = 100_000.0,
) -> MarketSnapshot:
    half = spread_bps / 20_000.0
    return MarketSnapshot(
        exchange=venue,
        base=base,
        symbol=f"{base}_USDT",
        observed=True,
        bid=mid * (1.0 - half),
        ask=mid * (1.0 + half),
        mid=mid,
        spread_bps=spread_bps,
        volume_24h_quote=volume,
        non_binance_spot=True,
        funding_rate=0.0001,
        funding_interval_sec=28_800,
        contract_multiplier=1.0,
        minimum_order_size=0.001,
        bid_size_contracts=bid_size_contracts,
        ask_size_contracts=ask_size_contracts,
    )


def _cycle(index: int, rows: list[MarketSnapshot], *, both_successful: bool = True) -> SnapshotCycle:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * index)
    return SnapshotCycle(
        timestamp=timestamp,
        successful_exchanges=frozenset({"mexc", "gateio"} if both_successful else {"gateio"}),
        markets={(row.exchange, row.base): row for row in rows},
    )


def _event_cycles() -> list[SnapshotCycle]:
    return [
        _cycle(0, [_snapshot("gateio", "AAA", 100.0)]),
        _cycle(1, [_snapshot("gateio", "AAA", 100.0)]),
        _cycle(2, [_snapshot("gateio", "AAA", 100.0), _snapshot("mexc", "AAA", 102.0)]),
        _cycle(3, [_snapshot("gateio", "AAA", 100.0), _snapshot("mexc", "AAA", 102.0)]),
        _cycle(4, [_snapshot("gateio", "AAA", 100.0), _snapshot("mexc", "AAA", 102.0)]),
        _cycle(5, [_snapshot("gateio", "AAA", 101.0), _snapshot("mexc", "AAA", 101.0)]),
    ]


def _daily_segment(day: int, rows: list[MarketSnapshot]) -> list[SnapshotCycle]:
    output = []
    for cycle in range(4):
        output.append(
            SnapshotCycle(
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(days=day, minutes=5 * cycle),
                successful_exchanges=frozenset({"mexc", "gateio"}),
                markets={(row.exchange, row.base): row for row in rows},
            )
        )
    return output


def _daily_event_groups(*, gap_before_entry: bool = False) -> list[list[SnapshotCycle]]:
    groups: list[list[SnapshotCycle]] = []
    day_values = [0, 1, 2, 3, 5, 6] if gap_before_entry else list(range(7))
    for logical_day, timestamp_day in enumerate(day_values):
        if logical_day <= 1:
            rows = [_snapshot("gateio", "AAA", 100.0)]
        elif logical_day <= 4:
            rows = [_snapshot("gateio", "AAA", 100.0), _snapshot("mexc", "AAA", 102.0)]
        elif logical_day == 5:
            rows = [_snapshot("gateio", "AAA", 100.6), _snapshot("mexc", "AAA", 101.4)]
        else:
            rows = [_snapshot("gateio", "AAA", 101.0), _snapshot("mexc", "AAA", 101.0)]
        groups.append(_daily_segment(timestamp_day, rows))
    return groups


class PitMembershipDriftEvaluatorTests(unittest.TestCase):
    def test_quality_date_split_is_20_train_plus_five_non_overlapping_20_day_folds(self) -> None:
        contract = build_pit_membership_drift_contract()
        dates = [f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}" for index in range(120)]

        split = split_quality_dates(dates, contract)

        self.assertEqual(len(split["train_dates"]), 20)
        self.assertEqual(len(split["oos_dates"]), 100)
        self.assertEqual([len(fold["test_dates"]) for fold in split["walk_forward_folds"]], [20] * 5)
        flattened = [date for fold in split["walk_forward_folds"] for date in fold["test_dates"]]
        self.assertEqual(flattened, split["oos_dates"])
        self.assertEqual(len(set(flattened)), 100)

    def test_detects_confirmed_missing_to_observed_transition_without_lookahead(self) -> None:
        contract = build_pit_membership_drift_contract()

        events = detect_activation_events(contract, _event_cycles())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].base, "AAA")
        self.assertEqual(events[0].activation_venue, "mexc")
        self.assertEqual(events[0].reference_venue, "gateio")
        self.assertEqual(events[0].confirmation_cycle_index, 3)
        self.assertEqual(events[0].entry_cycle_index, 4)

    def test_failed_exchange_cycle_cannot_create_an_activation_event(self) -> None:
        contract = build_pit_membership_drift_contract()
        cycles = _event_cycles()
        cycles[1] = _cycle(1, [_snapshot("gateio", "AAA", 100.0)], both_successful=False)

        self.assertEqual(detect_activation_events(contract, cycles), [])

    def test_segment_dedup_and_entry_delay_never_bridge_an_unobserved_gap(self) -> None:
        contract = build_pit_membership_drift_contract()
        first = _event_cycles()
        second = [
            SnapshotCycle(
                timestamp=cycle.timestamp + timedelta(days=1),
                successful_exchanges=cycle.successful_exchanges,
                markets=cycle.markets,
            )
            for cycle in _event_cycles()
        ]

        events, flattened = detect_activation_events_by_segment(contract, [first, second])

        self.assertEqual(len(events), 1)
        self.assertIsNotNone(simulate_event(contract, events[0], flattened, scenario="normal"))

        truncated = first[:4]
        following = second[:1]
        boundary_events, boundary_cycles = detect_activation_events_by_segment(
            contract,
            [truncated, following],
        )
        self.assertEqual(len(boundary_events), 1)
        self.assertIsNone(simulate_event(contract, boundary_events[0], boundary_cycles, scenario="normal"))

    def test_daily_segments_detect_event_and_allow_exit_only_across_consecutive_dates(self) -> None:
        contract = build_pit_membership_drift_contract()

        events, daily_cycles = detect_activation_events_by_daily_segments(
            contract,
            _daily_event_groups(),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].entry_cycle_index, 4)
        result = simulate_event(contract, events[0], daily_cycles, scenario="normal")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.exit_cycle_index, 6)
        self.assertAlmostEqual(result.holding_days, 2.0)
        self.assertAlmostEqual(result.break_even_holding_days, 1.0)

        gap_events, gap_cycles = detect_activation_events_by_daily_segments(
            contract,
            _daily_event_groups(gap_before_entry=True),
        )
        self.assertEqual(len(gap_events), 1)
        self.assertIsNone(simulate_event(contract, gap_events[0], gap_cycles, scenario="normal"))

    def test_normal_execution_uses_delayed_entry_convergence_exit_and_full_frozen_cost(self) -> None:
        contract = build_pit_membership_drift_contract()
        cycles = _event_cycles()
        event = detect_activation_events(contract, cycles)[0]

        result = simulate_event(contract, event, cycles, scenario="normal")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.long_venue, "gateio")
        self.assertEqual(result.short_venue, "mexc")
        self.assertEqual(result.entry_cycle_index, 4)
        self.assertEqual(result.exit_cycle_index, 5)
        entry_long = cycles[4].markets[("gateio", "AAA")]
        entry_short = cycles[4].markets[("mexc", "AAA")]
        exit_long = cycles[5].markets[("gateio", "AAA")]
        exit_short = cycles[5].markets[("mexc", "AAA")]
        expected_gross = 500.0 * (exit_long.bid / entry_long.ask - 1.0) + 500.0 * (
            1.0 - exit_short.ask / entry_short.bid
        )
        self.assertAlmostEqual(result.gross_price_pnl_quote, expected_gross, places=8)
        self.assertAlmostEqual(result.cost_quote, 500.0 * 58.0 / 10_000.0, places=8)
        self.assertAlmostEqual(result.net_price_pnl_quote, expected_gross - result.cost_quote, places=8)
        self.assertTrue(result.spread_cost_embedded_in_bbo)
        self.assertEqual(result.exit_reason, "convergence")

    def test_entry_is_not_executable_when_top_of_book_cannot_fill_frozen_notional(self) -> None:
        contract = build_pit_membership_drift_contract()
        cycles = _event_cycles()
        event = detect_activation_events(contract, cycles)[0]
        thin_gate = replace(
            cycles[4].markets[("gateio", "AAA")],
            ask_size_contracts=1.0,
        )
        cycles[4] = _cycle(
            4,
            [thin_gate, cycles[4].markets[("mexc", "AAA")]],
        )

        self.assertIsNone(simulate_event(contract, event, cycles, scenario="normal"))

    def test_capacity_is_minimum_entry_and_exit_bbo_quote_not_daily_volume_proxy(self) -> None:
        contract = build_pit_membership_drift_contract()
        cycles = _event_cycles()
        event = detect_activation_events(contract, cycles)[0]
        cycles[4] = _cycle(
            4,
            [
                replace(
                    cycles[4].markets[("gateio", "AAA")],
                    ask_size_contracts=8.0,
                ),
                replace(
                    cycles[4].markets[("mexc", "AAA")],
                    bid_size_contracts=7.0,
                ),
            ],
        )
        cycles[5] = _cycle(
            5,
            [
                replace(
                    cycles[5].markets[("gateio", "AAA")],
                    bid_size_contracts=6.0,
                ),
                replace(
                    cycles[5].markets[("mexc", "AAA")],
                    ask_size_contracts=5.0,
                ),
            ],
        )

        result = simulate_event(contract, event, cycles, scenario="normal")

        self.assertIsNotNone(result)
        assert result is not None
        capacity = getattr(result, "executable_capacity_quote_per_leg", None)
        self.assertIsNotNone(capacity)
        expected = min(
            cycles[4].markets[("gateio", "AAA")].ask * 8.0,
            cycles[4].markets[("mexc", "AAA")].bid * 7.0,
            cycles[5].markets[("gateio", "AAA")].bid * 6.0,
            cycles[5].markets[("mexc", "AAA")].ask * 5.0,
        )
        self.assertAlmostEqual(float(capacity), expected, places=8)

    def test_signal_below_frozen_dislocation_or_with_wide_spread_is_not_executable(self) -> None:
        contract = build_pit_membership_drift_contract()
        cycles = _event_cycles()
        event = detect_activation_events(contract, cycles)[0]
        narrow = copy.deepcopy(cycles)
        narrow[4] = _cycle(4, [_snapshot("gateio", "AAA", 100.0), _snapshot("mexc", "AAA", 100.5)])
        wide = copy.deepcopy(cycles)
        wide[4] = _cycle(
            4,
            [_snapshot("gateio", "AAA", 100.0, spread_bps=25.0), _snapshot("mexc", "AAA", 102.0)],
        )

        self.assertIsNone(simulate_event(contract, event, narrow, scenario="normal"))
        self.assertIsNone(simulate_event(contract, event, wide, scenario="normal"))

    def test_verdict_prioritizes_sample_then_economics_and_never_exceeds_probe(self) -> None:
        contract = build_pit_membership_drift_contract()
        metrics = {
            "oos_closed_days": 100,
            "event_count": 20,
            "event_count_by_activation_venue": {"mexc": 10, "gateio": 10},
            "unique_event_dates": 10,
            "dual_venue_coverage": 1.0,
            "net_expectancy_quote": 1.0,
            "profit_factor": 1.5,
            "positive_event_rate": 0.65,
            "net_expectancy_by_activation_venue": {"mexc": 1.0, "gateio": 1.0},
            "normal_net_pnl_quote": 20.0,
            "robustness_net_pnl_quote": 5.0,
            "stress_net_pnl_quote": 0.0,
            "positive_combined_walk_forward_folds": 4,
            "positive_walk_forward_folds_by_activation_venue": {"mexc": 3, "gateio": 3},
            "max_drawdown_fraction": 0.05,
            "max_single_event_positive_pnl_share": 0.2,
            "max_single_base_positive_pnl_share": 0.2,
            "max_single_venue_positive_pnl_share": 0.5,
            "break_even_holding_days_p95": 2.0,
            "minimum_executable_capacity_quote_per_leg": 500.0,
        }

        insufficient = copy.deepcopy(metrics)
        insufficient["event_count"] = 19
        self.assertEqual(decide_verdict(contract, insufficient)["verdict"], "INSUFFICIENT_DATA")

        rejected = copy.deepcopy(metrics)
        rejected["net_expectancy_quote"] = -0.01
        self.assertEqual(decide_verdict(contract, rejected)["verdict"], "REJECT")

        accepted = decide_verdict(contract, metrics)
        self.assertEqual(accepted["verdict"], "ACCEPT_FOR_SHORT_EXECUTION_PROBE")
        self.assertFalse(accepted["paper_forward_allowed"])
        self.assertFalse(accepted["live_orders"])


if __name__ == "__main__":
    unittest.main()
