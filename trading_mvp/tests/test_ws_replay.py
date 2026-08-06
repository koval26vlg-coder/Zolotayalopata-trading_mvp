from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import RiskConfig, StrategyConfig  # noqa: E402
from ws_replay import (  # noqa: E402
    EventDrivenReplayBacktester,
    ReplayConfig,
    ReplayRisk,
    load_normalized_events,
    save_replay_result,
)


def _bbo(ts: float, bid: float, ask: float, bid_qty: float = 10.0, ask_qty: float = 2.0) -> dict[str, object]:
    mid = (bid + ask) / 2.0
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": "gateio",
        "symbol": "HYPE_USDT",
        "event_kind": "bbo",
        "channel": "spot.book_ticker",
        "bid_price": bid,
        "bid_qty": bid_qty,
        "ask_price": ask,
        "ask_qty": ask_qty,
        "spread_bps": ((ask - bid) / mid) * 1e4,
    }


def _trade(ts: float, side: str, price: float, qty: float) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": "gateio",
        "symbol": "HYPE_USDT",
        "event_kind": "trade",
        "channel": "spot.trades",
        "trade_id": int(ts * 1000),
        "price": price,
        "qty": qty,
        "side": side,
    }


class WsReplayTests(unittest.TestCase):
    def _strategy(self) -> StrategyConfig:
        return StrategyConfig(
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
        )

    def _risk(self) -> RiskConfig:
        return RiskConfig(
            max_notional_per_trade=100.0,
            max_position_qty=10.0,
            max_trades_per_day=10,
            daily_loss_limit_quote=100.0,
        )

    def test_replay_opens_long_and_closes_take_profit(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
            _bbo(2.1, 100.10, 100.11),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["exit_reason"], "take_profit")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_replay_fees_reduce_net_pnl(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
            _bbo(2.1, 100.10, 100.11),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        trade = result["trades"][0]
        self.assertGreater(trade["gross_pnl_quote"], trade["net_pnl_quote"])
        self.assertGreater(result["metrics"]["fees_quote"], 0)

    def test_min_net_take_profit_filter_blocks_fee_dominated_signal(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                notional_quote=25.0,
                taker_fee_bps=10.0,
                slippage_bps=0.0,
                latency_ms=0,
                min_net_take_profit_bps=0.0,
            ),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertEqual(result["metrics"]["round_trip_fee_bps"], 20.0)
        self.assertLess(result["metrics"]["net_take_profit_bps"], 0.0)
        self.assertGreater(result["skipped_signals"]["min_net_take_profit_bps"], 0)

    def test_short_signal_is_skipped_by_default_for_spot(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=2.0, ask_qty=10.0),
            _trade(1.1, "sell", 100.0, 10.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=2.0, ask_qty=10.0),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"]["short_disabled"], 0)

    def test_fade_exhaustion_opens_long_on_sell_flow_bid_absorption(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=10.0, ask_qty=2.0),
            _trade(1.1, "sell", 100.0, 10.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=10.0, ask_qty=2.0),
            _bbo(2.0, 100.10, 100.11, bid_qty=10.0, ask_qty=2.0),
            _bbo(2.1, 100.10, 100.11, bid_qty=10.0, ask_qty=2.0),
        ]
        strategy = StrategyConfig(
            signal_type="fade_exhaustion",
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["side"], "LONG")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_fade_exhaustion_short_signal_is_blocked_without_allow_short(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=2.0, ask_qty=10.0),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=2.0, ask_qty=10.0),
        ]
        strategy = StrategyConfig(
            signal_type="fade_exhaustion",
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"]["short_disabled"], 0)

    def test_liquidity_sweep_reversal_opens_long_after_sell_sweep_reclaim(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _trade(1.1, "sell", 99.90, 10.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=10.0, ask_qty=2.0),
            _bbo(1.21, 100.0, 100.01, bid_qty=10.0, ask_qty=2.0),
            _bbo(2.0, 100.10, 100.11, bid_qty=10.0, ask_qty=2.0),
            _bbo(2.1, 100.10, 100.11, bid_qty=10.0, ask_qty=2.0),
        ]
        strategy = StrategyConfig(
            signal_type="liquidity_sweep_reversal",
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["side"], "LONG")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_liquidity_sweep_reversal_short_signal_is_blocked_without_allow_short(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _trade(1.1, "buy", 100.20, 10.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=2.0, ask_qty=10.0),
        ]
        strategy = StrategyConfig(
            signal_type="liquidity_sweep_reversal",
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"]["short_disabled"], 0)

    def test_liquidity_sweep_reversal_v2_opens_short_with_slice_filters(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _trade(1.1, "buy", 100.20, 30.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _bbo(1.21, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _bbo(2.0, 99.80, 99.81, bid_qty=5.0, ask_qty=5.0),
            _bbo(2.1, 99.80, 99.81, bid_qty=5.0, ask_qty=5.0),
        ]
        strategy = StrategyConfig(
            signal_type="liquidity_sweep_reversal_v2",
            entry_signed_flow_notional=2500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
            sweep_v2_allowed_markets="gateio:HYPE_USDT",
            sweep_v2_side="SHORT",
            sweep_v2_min_trade_notional_quote=2500.0,
            sweep_v2_max_pre_spread_bps=1.0,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0, allow_short=True),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["side"], "SHORT")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_liquidity_sweep_reversal_v2_blocks_unlisted_market(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _trade(1.1, "buy", 100.20, 30.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
        ]
        strategy = StrategyConfig(
            signal_type="liquidity_sweep_reversal_v2",
            entry_signed_flow_notional=2500.0,
            max_spread_bps=5.0,
            sweep_v2_allowed_markets="mexc:HYPE_USDT",
            sweep_v2_side="SHORT",
            sweep_v2_min_trade_notional_quote=2500.0,
            sweep_v2_max_pre_spread_bps=1.0,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0, allow_short=True),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"]["sweep_v2_allowed_markets"], 0)

    def test_unknown_signal_type_raises_clear_error(self) -> None:
        events = [_bbo(1.0, 100.0, 100.01)]
        strategy = StrategyConfig(signal_type="unknown")
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        with self.assertRaisesRegex(ValueError, "Unknown signal_type"):
            bt.run(events)

    def test_quality_filter_blocks_sparse_trade_flow_signal(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                notional_quote=25.0,
                taker_fee_bps=0.0,
                slippage_bps=0.0,
                latency_ms=0,
                quality_filter_enabled=True,
                quality_window_sec=60.0,
                quality_min_trade_count=2,
            ),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"]["quality_min_trade_count"], 0)

    def test_quality_filter_allows_dense_trade_flow_signal(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 5.0),
            _trade(1.2, "buy", 100.01, 5.0),
            _bbo(1.3, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
            _bbo(2.1, 100.10, 100.11),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                notional_quote=25.0,
                taker_fee_bps=0.0,
                slippage_bps=0.0,
                latency_ms=0,
                quality_filter_enabled=True,
                quality_window_sec=60.0,
                quality_min_trade_count=2,
                quality_min_trade_notional=1000.0,
                quality_max_avg_spread_bps=5.0,
                quality_min_quote_updates=1,
            ),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_maker_replay_fills_only_on_opposing_trade_prints(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(1.3, 100.0, 100.01),       # passive buy gets placed at bid
            _trade(1.4, "sell", 100.0, 1.0), # entry fill
            _bbo(2.0, 100.10, 100.11),       # exit signal
            _bbo(2.1, 100.10, 100.11),       # passive sell gets placed at ask
            _trade(2.2, "buy", 100.11, 1.0), # exit fill
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                notional_quote=25.0,
                execution_mode="maker",
                maker_fee_bps=0.0,
                taker_fee_bps=10.0,
                slippage_bps=0.0,
                latency_ms=0,
                maker_queue_ahead_qty=0.0,
                maker_order_ttl_sec=5.0,
            ),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["entry_price"], 100.0)
        self.assertEqual(result["trades"][0]["exit_price"], 100.11)
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_maker_top_qty_queue_requires_visible_size_to_trade_through(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=2.0, ask_qty=0.5),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=2.0, ask_qty=0.5),
            _bbo(1.3, 100.0, 100.01, bid_qty=2.0, ask_qty=0.5),
            _trade(1.4, "sell", 100.0, 1.0),  # queue still ahead
            _trade(1.5, "sell", 100.0, 1.0),  # queue consumed, own order is still unfilled
            _trade(1.6, "sell", 100.0, 0.25),  # own entry quantity fills
            _bbo(2.0, 100.10, 100.11, bid_qty=2.0, ask_qty=0.5),
            _bbo(2.1, 100.10, 100.11, bid_qty=2.0, ask_qty=0.5),
            _trade(2.2, "buy", 100.11, 0.25),  # entry is checked for exit after this
            _bbo(2.3, 100.10, 100.11, bid_qty=2.0, ask_qty=0.5),
            _trade(2.4, "buy", 100.11, 0.25),  # exit queue consumed, still no fill
            _trade(2.5, "buy", 100.11, 0.25),  # own exit quantity fills
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                notional_quote=25.0,
                execution_mode="maker",
                maker_fee_bps=0.0,
                taker_fee_bps=10.0,
                slippage_bps=0.0,
                latency_ms=0,
                maker_queue_model="top_qty_fraction",
                maker_queue_ahead_fraction=1.0,
                maker_order_ttl_sec=5.0,
            ),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertAlmostEqual(result["trades"][0]["entry_ts"], 1.6)
        self.assertAlmostEqual(result["trades"][0]["exit_ts"], 2.5)

    def test_replay_risk_resets_daily_limits_on_utc_day_boundary(self) -> None:
        risk = ReplayRisk(
            RiskConfig(
                max_notional_per_trade=100.0,
                max_position_qty=10.0,
                max_trades_per_day=1,
                daily_loss_limit_quote=5.0,
            )
        )
        risk.register_open(ts=1.0)
        risk.register_close(-6.0, ts=2.0)
        blocked, reason = risk.can_open(
            qty=0.1,
            price=10.0,
            open_positions=0,
            max_open_positions=5,
            ts=3.0,
        )
        self.assertFalse(blocked)
        self.assertEqual(reason, "kill_switch_active")

        risk.advance_time(86_401.0)
        allowed, reason = risk.can_open(
            qty=0.1,
            price=10.0,
            open_positions=0,
            max_open_positions=5,
            ts=86_401.0,
        )

        self.assertTrue(allowed)
        self.assertEqual(reason, "ok")
        self.assertEqual(risk.trades_opened, 0)
        self.assertEqual(risk.daily_realized_pnl, 0.0)
        self.assertEqual(risk.total_realized_pnl, -6.0)
        self.assertFalse(risk.kill_switch)

    def test_stale_quote_blocks_signal_and_is_reported(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(10.0, "buy", 100.01, 10.0),
        ]
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                notional_quote=25.0,
                taker_fee_bps=0.0,
                slippage_bps=0.0,
                latency_ms=0,
                max_quote_age_sec=1.0,
            ),
        )

        result = bt.run(events)

        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"].get("stale_quote", 0), 0)

    def test_max_drawdown_includes_intratrade_mark_to_market_loss(self) -> None:
        strategy = StrategyConfig(
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=2000.0,
            stop_loss_bps=2000.0,
            max_hold_sec=100.0,
        )
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 90.0, 90.01),
            _bbo(3.0, 100.01, 100.02),
        ]
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )

        result = bt.run(events)

        self.assertAlmostEqual(result["metrics"]["net_pnl_quote"], 0.0, places=8)
        self.assertLess(result["metrics"]["max_drawdown_quote"], -2.0)
        self.assertTrue(any(point.get("unrealized_pnl_quote", 0.0) < -2.0 for point in result["equity_curve"]))

    def test_replay_costs_resolve_by_exchange_with_global_fallback(self) -> None:
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            self._risk(),
            ReplayConfig(
                execution_mode="taker",
                taker_fee_bps=10.0,
                taker_fee_bps_by_exchange={"gateio": 6.0, "mexc": 8.0},
                slippage_bps_by_exchange={"gateio": 2.0},
            ),
        )

        self.assertEqual(bt._round_trip_fee_bps("gateio"), 12.0)
        self.assertEqual(bt._round_trip_fee_bps("mexc"), 16.0)
        self.assertEqual(bt._round_trip_fee_bps("unknown"), 20.0)
        self.assertEqual(bt._slippage_bps("gateio"), 2.0)
        self.assertEqual(bt._slippage_bps("mexc"), 1.0)

    def test_risk_cost_gate_from_config_blocks_fee_dominated_taker(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
        ]
        risk = RiskConfig(
            max_notional_per_trade=100.0,
            max_position_qty=10.0,
            max_trades_per_day=10,
            daily_loss_limit_quote=100.0,
            min_net_take_profit_bps=1.0,
        )
        bt = EventDrivenReplayBacktester(
            self._strategy(),
            risk,
            ReplayConfig(notional_quote=25.0, taker_fee_bps=10.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 0)
        self.assertGreater(result["skipped_signals"]["min_net_take_profit_bps"], 0)

    def test_replay_risk_unrealized_loss_triggers_kill_switch(self) -> None:
        risk = ReplayRisk(
            RiskConfig(
                max_notional_per_trade=100.0,
                max_position_qty=10.0,
                max_trades_per_day=10,
                daily_loss_limit_quote=5.0,
            )
        )
        risk.mark_unrealized(-6.0)
        self.assertTrue(risk.kill_switch)
        ok, reason = risk.can_open(qty=0.1, price=10.0, open_positions=0, max_open_positions=5)
        self.assertFalse(ok)
        self.assertEqual(reason, "kill_switch_active")

    def test_large_move_breakout_opens_long_on_upside_break_with_flow(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _bbo(1.1, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _bbo(1.2, 100.0, 100.01, bid_qty=5.0, ask_qty=5.0),
            _trade(1.3, "buy", 100.01, 10.0),
            _bbo(1.4, 100.04, 100.05, bid_qty=5.0, ask_qty=5.0),  # breakout -> entry scheduled
            _bbo(1.5, 100.04, 100.05, bid_qty=5.0, ask_qty=5.0),  # entry fills at ask 100.05
            _bbo(2.0, 100.20, 100.21, bid_qty=5.0, ask_qty=5.0),  # take-profit signal
            _bbo(2.1, 100.20, 100.21, bid_qty=5.0, ask_qty=5.0),  # exit fills at bid 100.20
        ]
        strategy = StrategyConfig(
            signal_type="large_move_breakout",
            entry_signed_flow_notional=500.0,
            max_spread_bps=5.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=10,
            breakout_lookback_sec=30.0,
            breakout_bps=2.0,
            breakout_min_samples=3,
        )
        bt = EventDrivenReplayBacktester(
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        result = bt.run(events)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["side"], "LONG")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_load_and_save_replay_files(self) -> None:
        events = [_bbo(1.0, 100.0, 100.01), _trade(1.1, "buy", 100.01, 10.0)]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "replay.json"
            src.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            loaded = load_normalized_events(src)
            save_replay_result(out, {"events": len(loaded)})
            self.assertEqual(len(loaded), 2)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["events"], 2)


if __name__ == "__main__":
    unittest.main()
