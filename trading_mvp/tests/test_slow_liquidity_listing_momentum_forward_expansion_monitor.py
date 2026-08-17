from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import slow_liquidity_listing_momentum_forward_expansion_monitor as monitor  # noqa: E402
import slow_liquidity_listing_momentum_forward_expansion_plan as plan_module  # noqa: E402
from listing_momentum_exchange_expansion import Candle  # noqa: E402


class FakeClient:
    max_candles_per_request = 1000

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, int, int]] = []

    def fetch_ohlcv(self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int):
        self.calls.append((symbol, granularity, start_ts, end_ts, limit))
        return [
            Candle(
                ts=start_ts,
                open=1.0,
                high=1.2,
                low=0.9,
                close=1.1,
                volume=10.0,
                quote_volume=11.0,
            )
        ]


class ExpansionMonitorTests(unittest.TestCase):
    def test_detection_time_proxy_is_explicit(self) -> None:
        baseline = {
            "schema": "fixture",
            "venues": [
                {
                    "exchange": "binance",
                    "snapshot_rows": [
                        {"exchange": "binance", "symbol": "BTCUSDT"}
                    ],
                }
            ],
        }
        now_ts = 1_710_000_000
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline_path = root / "preflight.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            plan = {
                "plan_hash": "fixture-plan",
                "source_bindings": {
                    "preflight": {
                        "path": str(baseline_path),
                        "baseline_as_of_ts": now_ts - 3600,
                    }
                },
            }
            fake_client = FakeClient()
            with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
                monitor, "STATE_PATH", root / "state.json"
            ), mock.patch.object(monitor, "CLAIM_PATH", root / "claim.json"), mock.patch.object(
                monitor, "SLEEP_SEC", 0
            ):
                manifest = monitor.run_tick(
                    plan,
                    tick_id="fixture_tick",
                    clients={
                        "binance": fake_client,
                        "bybit": fake_client,
                        "okx": fake_client,
                        "bitget": fake_client,
                    },
                    fetcher=lambda: (
                        [
                            {
                                "exchange": "binance",
                                "base": "NEW",
                                "symbol": "NEWUSDT",
                                "is_delisted": False,
                                "listed_ts": None,
                            }
                        ],
                        4,
                    ),
                    now_ts=now_ts,
                )
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(manifest["new_listing_count"], 1)
            self.assertEqual(manifest["jobs"][0]["timestamp_source"], "snapshot_diff_detection_time_proxy")
            self.assertTrue(fake_client.calls)
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["venues"], ["binance", "bybit", "okx", "bitget"])


class ExpansionPlanTests(unittest.TestCase):
    def test_checked_in_plan_is_hash_bound_and_isolated_from_v2(self) -> None:
        plan = json.loads(plan_module.FORWARD_PLAN_PATH.read_text(encoding="utf-8"))
        plan_module.validate_plan(plan)
        self.assertEqual(plan["status"], "READY_FOR_VISIBLE_EXPANSION_TICKS")
        self.assertEqual(plan["venues"], ["binance", "bybit", "okx", "bitget"])
        self.assertTrue(plan["source_bindings"]["parent_v2"]["parallel_immutable"])
        self.assertTrue(plan["guard_contract"]["v2_namespace_must_remain_untouched"])
        self.assertFalse(plan["evaluator_or_oos_allowed"])
        self.assertFalse(plan["replay_allowed"])


if __name__ == "__main__":
    unittest.main()
