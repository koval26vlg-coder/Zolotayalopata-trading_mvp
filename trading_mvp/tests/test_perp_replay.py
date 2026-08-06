from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import build_parser  # noqa: E402
from config import RiskConfig, StrategyConfig  # noqa: E402
from perp_replay import run_perp_grid_search_file, run_perp_replay  # noqa: E402
from ws_replay import ReplayConfig  # noqa: E402


def _bbo(
    ts: float,
    bid: float,
    ask: float,
    bid_qty: float = 2.0,
    ask_qty: float = 10.0,
    *,
    mark_price: float | None = None,
    index_price: float | None = None,
    funding_rate: float | None = None,
    funding_interval_sec: int | None = None,
    next_funding_ts: float | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": "gateio",
        "symbol": "HYPE_USDT",
        "event_kind": "bbo",
        "channel": "perp.book_ticker",
        "bid_price": bid,
        "bid_qty": bid_qty,
        "ask_price": ask,
        "ask_qty": ask_qty,
    }
    if mark_price is not None:
        event["mark_price"] = mark_price
    if index_price is not None:
        event["index_price"] = index_price
    if funding_rate is not None:
        event["funding_rate"] = funding_rate
    if funding_interval_sec is not None:
        event["funding_interval_sec"] = funding_interval_sec
    if next_funding_ts is not None:
        event["next_funding_ts"] = next_funding_ts
    return event


def _trade(ts: float, side: str, price: float, qty: float) -> dict[str, object]:
    return {
        "recv_ts": ts,
        "exchange_ts": ts,
        "exchange": "gateio",
        "symbol": "HYPE_USDT",
        "event_kind": "trade",
        "channel": "perp.trades",
        "trade_id": int(ts * 1000),
        "price": price,
        "qty": qty,
        "side": side,
    }


class PerpReplayTests(unittest.TestCase):
    def _strategy(self) -> StrategyConfig:
        return StrategyConfig(
            signal_type="flow_continue",
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=10.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=5,
        )

    def _risk(self) -> RiskConfig:
        return RiskConfig(
            max_notional_per_trade=100.0,
            max_position_qty=10.0,
            max_trades_per_day=10,
            daily_loss_limit_quote=100.0,
        )

    def test_perp_replay_allows_short_by_default(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.1),
            _trade(1.1, "sell", 100.0, 10.0),
            _bbo(1.2, 100.0, 100.1),
            _bbo(2.0, 99.8, 99.9),
            _bbo(2.1, 99.8, 99.9),
        ]
        result = run_perp_replay(
            events,
            self._strategy(),
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        self.assertEqual(result["mode"], "perp_event_driven_replay")
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["side"], "SHORT")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_perp_replay_accrues_positive_funding_for_short(self) -> None:
        events = [
            _bbo(
                1.0,
                100.0,
                100.1,
                mark_price=100.05,
                index_price=100.0,
                funding_rate=0.01,
                funding_interval_sec=10,
                next_funding_ts=5.0,
            ),
            _trade(1.1, "sell", 100.0, 10.0),
            _bbo(
                1.2,
                100.0,
                100.1,
                mark_price=100.05,
                index_price=100.0,
                funding_rate=0.01,
                funding_interval_sec=10,
                next_funding_ts=5.0,
            ),
            _bbo(
                7.0,
                100.0,
                100.1,
                mark_price=100.05,
                index_price=100.0,
                funding_rate=0.01,
                funding_interval_sec=10,
                next_funding_ts=15.0,
            ),
            _bbo(
                7.1,
                100.0,
                100.1,
                mark_price=100.05,
                index_price=100.0,
                funding_rate=0.01,
                funding_interval_sec=10,
                next_funding_ts=15.0,
            ),
        ]
        result = run_perp_replay(
            events,
            self._strategy(),
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        trade = result["trades"][0]
        self.assertGreater(result["metrics"]["funding_pnl_quote"], 0)
        self.assertGreater(trade["funding_pnl_quote"], 0)
        self.assertGreater(result["metrics"]["net_pnl_quote"], trade["funding_pnl_quote"] * 0.5)

    def test_perp_replay_does_not_prorate_funding_before_settlement(self) -> None:
        events = [
            _bbo(
                1.0,
                100.0,
                100.1,
                mark_price=100.05,
                funding_rate=0.01,
                funding_interval_sec=10,
                next_funding_ts=10.0,
            ),
            _trade(1.1, "sell", 100.0, 10.0),
            _bbo(
                1.2,
                100.0,
                100.1,
                mark_price=100.05,
                funding_rate=0.01,
                funding_interval_sec=10,
                next_funding_ts=10.0,
            ),
            _bbo(7.0, 100.0, 100.1, mark_price=100.05, funding_rate=0.01, funding_interval_sec=10, next_funding_ts=10.0),
            _bbo(7.1, 100.0, 100.1, mark_price=100.05, funding_rate=0.01, funding_interval_sec=10, next_funding_ts=10.0),
        ]

        result = run_perp_replay(
            events,
            self._strategy(),
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )

        self.assertEqual(result["metrics"]["funding_pnl_quote"], 0.0)
        self.assertEqual(result["trades"][0]["funding_pnl_quote"], 0.0)

    def test_perp_liquidity_sweep_reversal_can_open_short(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.1, bid_qty=5.0, ask_qty=5.0),
            _trade(1.1, "buy", 100.3, 10.0),
            _bbo(1.2, 100.0, 100.1, bid_qty=2.0, ask_qty=10.0),
            _bbo(1.21, 100.0, 100.1, bid_qty=2.0, ask_qty=10.0),
            _bbo(2.0, 99.8, 99.9, bid_qty=2.0, ask_qty=10.0),
            _bbo(2.1, 99.8, 99.9, bid_qty=2.0, ask_qty=10.0),
        ]
        strategy = StrategyConfig(
            signal_type="liquidity_sweep_reversal",
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=500.0,
            max_spread_bps=10.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=5,
        )
        result = run_perp_replay(
            events,
            strategy,
            self._risk(),
            ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
        )
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertEqual(result["trades"][0]["side"], "SHORT")
        self.assertGreater(result["metrics"]["net_pnl_quote"], 0)

    def test_perp_grid_search_includes_signal_type_dimension(self) -> None:
        events = [
            _bbo(1.0, 100.0, 100.1),
            _trade(1.1, "sell", 100.0, 10.0),
            _bbo(1.2, 100.0, 100.1),
            _bbo(2.0, 99.8, 99.9),
            _bbo(2.1, 99.8, 99.9),
        ]
        grid = {
            "signal_type": ["flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"],
            "entry_imbalance_abs": [0.2],
            "entry_signed_flow_notional": [500.0],
            "max_spread_bps": [10.0],
            "take_profit_bps": [5.0],
            "stop_loss_bps": [5.0],
            "max_hold_sec": [5],
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "perp.jsonl"
            out = Path(tmp) / "perp_grid.json"
            src.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            result = run_perp_grid_search_file(
                input_path=src,
                output_path=out,
                base_strategy=self._strategy(),
                risk_cfg=self._risk(),
                replay_cfg=ReplayConfig(notional_quote=25.0, taker_fee_bps=0.0, slippage_bps=0.0, latency_ms=0),
                grid=grid,
                min_trades=0,
                top_n=3,
            )
            self.assertEqual(result["mode"], "perp_event_driven_replay_grid_search")
            self.assertEqual(result["total_combinations"], 3)
            self.assertEqual(set(result["best_by_signal_type"]), {"flow_continue", "fade_exhaustion", "liquidity_sweep_reversal"})
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["mode"], "perp_event_driven_replay_grid_search")

    def test_cli_parser_accepts_perp_commands(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["perp-replay", "--signal-type", "fade_exhaustion"]).command, "perp-replay")
        self.assertEqual(parser.parse_args(["perp-grid-search", "--top-n", "3"]).command, "perp-grid-search")
        venue_costs = '{"gateio":{"taker_fee_bps":10,"maker_fee_bps":2,"slippage_bps":1}}'
        perp_args = parser.parse_args(
            ["perp-replay", "--venue-costs-json", venue_costs, "--max-quote-age-sec", "2"]
        )
        ws_args = parser.parse_args(
            ["ws-replay", "--venue-costs-json", venue_costs, "--max-quote-age-sec", "2"]
        )
        funding_args = parser.parse_args(["funding-backtest", "--venue-costs-json", venue_costs])
        self.assertEqual(perp_args.venue_costs_json, venue_costs)
        self.assertEqual(perp_args.max_quote_age_sec, 2.0)
        self.assertEqual(ws_args.venue_costs_json, venue_costs)
        self.assertEqual(funding_args.venue_costs_json, venue_costs)


if __name__ == "__main__":
    unittest.main()
