from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import RiskConfig, StrategyConfig  # noqa: E402
from exchanges import MarketPair, MarketSnapshot, PublicSpotClient  # noqa: E402
from multi_bot import MultiExchangePaperBot, select_pairs  # noqa: E402


class FakeClient(PublicSpotClient):
    exchange_id = "fake"
    display_name = "Fake"

    def __init__(self) -> None:
        super().__init__()
        self.index = 0

    def fetch_pairs(self, quote: str = "USDT") -> list[MarketPair]:
        return []

    def fetch_snapshot(self, pair: MarketPair, depth_limit: int, trades_limit: int) -> MarketSnapshot:
        snapshots = [
            MarketSnapshot("fake", "HYPE-USDT", 1.0, 100.0, 100.02, 8.0, 2.0, 2.0, 0.6, 0.0, 0, None),
            MarketSnapshot("fake", "HYPE-USDT", 2.0, 100.0, 100.02, 8.0, 2.0, 2.0, 0.6, 300.0, 1, 100.02),
            MarketSnapshot("fake", "HYPE-USDT", 3.0, 100.10, 100.12, 3.0, 3.0, 2.0, 0.0, 0.0, 0, 100.10),
        ]
        snapshot = snapshots[min(self.index, len(snapshots) - 1)]
        self.index += 1
        return snapshot


class MultiBotTests(unittest.TestCase):
    def test_spot_clients_ignore_proxy_environment(self) -> None:
        self.assertFalse(FakeClient().session.trust_env)

    def test_select_pairs_preserves_universe_priority(self) -> None:
        pairs = [
            MarketPair("mexc", "OKB-USDT", "OKB", "USDT"),
            MarketPair("mexc", "HYPE-USDT", "HYPE", "USDT"),
        ]
        selected = select_pairs(pairs, ["HYPE", "OKB"], max_pairs=2)
        self.assertEqual([pair.base for pair in selected], ["HYPE", "OKB"])

    def test_paper_bot_opens_and_closes_trade(self) -> None:
        pair = MarketPair("fake", "HYPE-USDT", "HYPE", "USDT")
        bot = MultiExchangePaperBot(
            clients={"fake": FakeClient()},
            pairs_by_exchange={"fake": [pair]},
            strategy_cfg=StrategyConfig(
                entry_imbalance_abs=0.2,
                entry_signed_flow_notional=100.0,
                max_spread_bps=5.0,
                take_profit_bps=5.0,
                stop_loss_bps=5.0,
                max_hold_sec=100,
            ),
            risk_cfg=RiskConfig(
                max_notional_per_trade=25.0,
                max_position_qty=1000.0,
                max_trades_per_day=10,
                daily_loss_limit_quote=10.0,
            ),
            paper_notional_quote=25.0,
            depth_limit=20,
            trades_limit=100,
            poll_interval_sec=0.0,
        )
        result = bot.run(cycles=3)
        self.assertEqual(result["metrics"]["total_trades"], 1)
        self.assertGreater(result["metrics"]["gross_pnl_quote"], 0)


if __name__ == "__main__":
    unittest.main()
