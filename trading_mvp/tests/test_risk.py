from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import RiskConfig  # noqa: E402
from trading import RiskEngine  # noqa: E402


class RiskEngineTests(unittest.TestCase):
    def test_risk_limits_block_too_large_notional(self) -> None:
        risk = RiskEngine(
            RiskConfig(
                max_notional_per_trade=10.0,
                max_position_qty=1.0,
                max_trades_per_day=10,
                daily_loss_limit_quote=5.0,
            )
        )
        ok, reason = risk.can_open(qty=1.0, price=20.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "max_notional_per_trade")

    def test_risk_kill_switch_after_daily_loss(self) -> None:
        risk = RiskEngine(
            RiskConfig(
                max_notional_per_trade=100.0,
                max_position_qty=1.0,
                max_trades_per_day=10,
                daily_loss_limit_quote=5.0,
            )
        )
        risk.register_close(-6.0)
        self.assertTrue(risk.kill_switch)

    def test_risk_kill_switch_includes_unrealized_loss(self) -> None:
        risk = RiskEngine(
            RiskConfig(
                max_notional_per_trade=100.0,
                max_position_qty=1.0,
                max_trades_per_day=10,
                daily_loss_limit_quote=5.0,
            )
        )
        risk.mark_unrealized(-3.0)
        self.assertFalse(risk.kill_switch)
        risk.mark_unrealized(-6.0)
        self.assertTrue(risk.kill_switch)
        ok, reason = risk.can_open(qty=0.1, price=10.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "kill_switch_active")


if __name__ == "__main__":
    unittest.main()
