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
from ws_grid_search import parse_float_list, parse_int_list, parse_str_list, run_grid_search, run_grid_search_file  # noqa: E402
from ws_replay import ReplayConfig  # noqa: E402


def _bbo(ts: float, bid: float, ask: float, bid_qty: float = 10.0, ask_qty: float = 2.0) -> dict[str, object]:
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


class WsGridSearchTests(unittest.TestCase):
    def test_grid_search_is_explicitly_in_sample_and_cannot_accept_strategy(self) -> None:
        result = run_grid_search(
            events=[_bbo(1.0, 100.0, 100.01), _trade(1.1, "buy", 100.01, 10.0), _bbo(1.2, 100.0, 100.01)],
            base_strategy=StrategyConfig(),
            risk_cfg=RiskConfig(
                max_notional_per_trade=100.0,
                max_position_qty=10.0,
                max_trades_per_day=10,
                daily_loss_limit_quote=100.0,
            ),
            replay_cfg=ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
            grid={
                "entry_imbalance_abs": [0.1],
                "entry_signed_flow_notional": [50.0],
                "max_spread_bps": [5.0],
                "take_profit_bps": [3.0],
                "stop_loss_bps": [3.0],
                "max_hold_sec": [10],
            },
            min_trades=0,
            top_n=1,
        )

        self.assertEqual(result["evaluation_scope"], "in_sample_grid_search_only")
        self.assertFalse(result["strategy_accepted"])
        self.assertFalse(result["paper_forward_allowed"])
        self.assertFalse(result["oos_evaluated"])
        self.assertEqual(result["oos_status"], "not_run")
        self.assertTrue(result["multiple_testing"]["sealed_holdout_required"])
        self.assertEqual(result["multiple_testing"]["tested_combinations"], 1)
        self.assertTrue(result["top_results"][0]["in_sample_eligible"] in {True, False})

    def test_grid_search_rejects_combinations_above_budget(self) -> None:
        grid = {
            "entry_imbalance_abs": [0.1, 0.2],
            "entry_signed_flow_notional": [50.0],
            "max_spread_bps": [5.0],
            "take_profit_bps": [3.0],
            "stop_loss_bps": [3.0],
            "max_hold_sec": [10],
        }

        with self.assertRaisesRegex(ValueError, "multiple-testing budget"):
            run_grid_search(
                events=[_bbo(1.0, 100.0, 100.01)],
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(),
                replay_cfg=ReplayConfig(),
                grid=grid,
                max_combinations=1,
            )

    def test_parse_grid_values(self) -> None:
        self.assertEqual(parse_float_list("0.1, 0.25"), [0.1, 0.25])
        self.assertEqual(parse_int_list("5, 25"), [5, 25])
        self.assertEqual(
            parse_str_list("flow_continue, fade_exhaustion, liquidity_sweep_reversal"),
            ["flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"],
        )

    def test_grid_search_file_ranks_eligible_results(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
            _bbo(2.1, 100.10, 100.11),
        ]
        grid = {
            "entry_imbalance_abs": [0.1, 0.9],
            "entry_signed_flow_notional": [50.0],
            "max_spread_bps": [5.0],
            "take_profit_bps": [3.0],
            "stop_loss_bps": [3.0],
            "max_hold_sec": [10],
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "grid.json"
            src.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            result = run_grid_search_file(
                input_path=src,
                output_path=out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(
                    max_notional_per_trade=100.0,
                    max_position_qty=10.0,
                    max_trades_per_day=10,
                    daily_loss_limit_quote=100.0,
                ),
                replay_cfg=ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
                grid=grid,
                min_trades=1,
                top_n=2,
            )
            self.assertEqual(result["total_combinations"], 2)
            self.assertEqual(result["eligible_combinations"], 1)
            self.assertTrue(result["top_results"][0]["eligible"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["total_combinations"], 2)

    def test_grid_search_marks_results_ineligible_when_economics_fail(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
            _bbo(2.0, 100.10, 100.11),
            _bbo(2.1, 100.10, 100.11),
        ]
        grid = {
            "entry_imbalance_abs": [0.1],
            "entry_signed_flow_notional": [50.0],
            "max_spread_bps": [5.0],
            "take_profit_bps": [3.0],
            "stop_loss_bps": [3.0],
            "max_hold_sec": [10],
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "grid.json"
            src.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            result = run_grid_search_file(
                input_path=src,
                output_path=out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(
                    max_notional_per_trade=100.0,
                    max_position_qty=10.0,
                    max_trades_per_day=10,
                    daily_loss_limit_quote=100.0,
                ),
                replay_cfg=ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
                grid=grid,
                min_trades=1,
                min_net_pnl_quote=999.0,
                top_n=1,
            )
            self.assertEqual(result["eligible_combinations"], 0)
            self.assertFalse(result["top_results"][0]["eligible"])
            self.assertIn("min_net_pnl_quote", result["top_results"][0]["eligibility_reasons"])

    def test_grid_search_includes_signal_type_dimension(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.01),
            _trade(1.1, "buy", 100.01, 10.0),
            _bbo(1.2, 100.0, 100.01),
        ]
        grid = {
            "signal_type": ["flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"],
            "entry_imbalance_abs": [0.1],
            "entry_signed_flow_notional": [50.0],
            "max_spread_bps": [5.0],
            "take_profit_bps": [3.0],
            "stop_loss_bps": [3.0],
            "max_hold_sec": [10],
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "grid.json"
            src.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            result = run_grid_search_file(
                input_path=src,
                output_path=out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(
                    max_notional_per_trade=100.0,
                    max_position_qty=10.0,
                    max_trades_per_day=10,
                    daily_loss_limit_quote=100.0,
                ),
                replay_cfg=ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
                grid=grid,
                min_trades=0,
                top_n=3,
            )
            signal_types = {item["strategy_config"]["signal_type"] for item in result["top_results"]}
            self.assertEqual(result["total_combinations"], 3)
            self.assertEqual(signal_types, {"flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"})
            self.assertEqual(
                set(result["best_by_signal_type"]),
                {"flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"},
            )

    def test_grid_search_reports_min_net_take_profit_filter(self) -> None:
        grid = {
            "entry_imbalance_abs": [0.1],
            "entry_signed_flow_notional": [50.0],
            "max_spread_bps": [5.0],
            "take_profit_bps": [3.0],
            "stop_loss_bps": [3.0],
            "max_hold_sec": [10],
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "normalized.jsonl"
            out = Path(tmp) / "grid.json"
            src.write_text(json.dumps(_bbo(1.0, 100.0, 100.01)), encoding="utf-8")
            result = run_grid_search_file(
                input_path=src,
                output_path=out,
                base_strategy=StrategyConfig(),
                risk_cfg=RiskConfig(),
                replay_cfg=ReplayConfig(min_net_take_profit_bps=1.0),
                grid=grid,
                top_n=1,
            )
            self.assertEqual(result["eligibility_filters"]["min_net_take_profit_bps"], 1.0)
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["eligibility_filters"]["min_net_take_profit_bps"], 1.0)


if __name__ == "__main__":
    unittest.main()
