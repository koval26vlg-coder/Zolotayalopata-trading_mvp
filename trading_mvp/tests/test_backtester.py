from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import RiskConfig, StrategyConfig  # noqa: E402
from trading import Backtester  # noqa: E402


def _snap(
    ts: float,
    bid: float,
    ask: float,
    imbalance: float,
    signed_flow_notional: float,
) -> dict[str, float]:
    mid = (bid + ask) / 2.0
    spread_bps = ((ask - bid) / mid) * 1e4
    return {
        "ts": ts,
        "bid": bid,
        "ask": ask,
        "imbalance": imbalance,
        "spread_bps": spread_bps,
        "signed_flow_notional": signed_flow_notional,
    }


class BacktesterTests(unittest.TestCase):
    def test_backtester_opens_and_closes_long(self) -> None:
        strategy = StrategyConfig(
            entry_imbalance_abs=0.2,
            entry_signed_flow_notional=100.0,
            max_spread_bps=10.0,
            take_profit_bps=5.0,
            stop_loss_bps=5.0,
            max_hold_sec=100,
        )
        risk = RiskConfig(
            max_notional_per_trade=1000.0,
            max_position_qty=1.0,
            max_trades_per_day=10,
            daily_loss_limit_quote=100.0,
        )
        bt = Backtester(strategy, risk)
        snapshots = [
            _snap(1.0, 100.0, 100.02, 0.3, 300.0),   # вход long
            _snap(2.0, 100.08, 100.10, 0.1, 10.0),   # выход по tp
        ]
        result = bt.run(snapshots=snapshots, qty=0.1)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertGreater(result["metrics"]["gross_pnl_quote"], 0)


if __name__ == "__main__":
    unittest.main()
