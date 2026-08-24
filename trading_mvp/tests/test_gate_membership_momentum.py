from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_membership_momentum import (  # noqa: E402
    DAY_SEC,
    FrozenMomentumConfig,
    MarketSeries,
    RebalanceEvent,
    adjusted_event_funding,
    cost_contract,
    evaluate_rebalance,
    portfolio_metrics,
)
from gate_membership_momentum_train import (  # noqa: E402
    FEASIBLE_DECISION,
    build_train_plan,
    evaluate_train_plan,
    train_plan_hash,
)


def _market(base: str, daily_return: float, *, funding_rate: float = 0.0) -> MarketSeries:
    market = MarketSeries(
        exchange="gateio",
        symbol=f"{base}_USDT",
        base=base,
        canonical_asset_id=f"coingecko:{base.lower()}",
    )
    price = 100.0
    for day in range(0, 180):
        open_price = price
        price *= 1.0 + daily_return
        market.opens[day] = open_price
        market.closes[day] = price
        market.quote_volumes[day] = 2_000_000.0
    market.funding = [
        (day * DAY_SEC + 1, funding_rate)
        for day in range(0, 180)
    ]
    return market


class GateMembershipMomentumCoreTests(unittest.TestCase):
    def test_next_open_execution_avoids_signal_close_lookahead(self) -> None:
        config = FrozenMomentumConfig(min_per_side=1, minimum_scored_markets=4)
        markets = [
            _market("WIN", 0.01),
            _market("UP", 0.005),
            _market("DOWN", -0.005),
            _market("LOSE", -0.01),
        ]

        event = evaluate_rebalance(markets, signal_day=40, config=config)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.entry_day, 41)
        self.assertEqual(event.exit_day, 48)
        self.assertEqual(event.long_bases, ("WIN",))
        self.assertEqual(event.short_bases, ("LOSE",))
        expected_long = markets[0].opens[48] / markets[0].opens[41] - 1.0
        expected_short = -(markets[3].opens[48] / markets[3].opens[41] - 1.0)
        self.assertAlmostEqual(event.price_return, 0.5 * (expected_long + expected_short))

    def test_cost_contract_is_base_fee_and_ohlcv_conservative(self) -> None:
        costs = cost_contract()

        self.assertEqual(costs["normal"]["fee_bps"], 20.0)
        self.assertEqual(costs["normal"]["total_bps"], 46.0)
        self.assertEqual(costs["stress"]["total_bps"], 72.0)
        self.assertEqual(costs["maker_fill_probability"], 0.0)

    def test_price_only_and_funding_metrics_remain_separate(self) -> None:
        config = FrozenMomentumConfig(min_per_side=1, minimum_scored_markets=4)
        event = evaluate_rebalance(
            [
                _market("WIN", 0.01, funding_rate=0.0001),
                _market("UP", 0.005, funding_rate=0.0001),
                _market("DOWN", -0.005, funding_rate=0.0001),
                _market("LOSE", -0.01, funding_rate=0.0001),
            ],
            signal_day=40,
            config=config,
        )
        assert event is not None

        metrics = portfolio_metrics([event], cost_bps=46.0, favorable_funding_multiplier=1.0)

        self.assertIn("price_only_net_expectancy_bps", metrics)
        self.assertIn("funding_expectancy_bps", metrics)
        self.assertIn("total_net_expectancy_bps", metrics)
        self.assertAlmostEqual(metrics["funding_expectancy_bps"], 0.0, places=8)

    def test_stress_removes_favorable_funding_per_asset_not_after_netting(self) -> None:
        event = RebalanceEvent(
            signal_day=40,
            entry_day=41,
            exit_day=48,
            long_bases=("LONG",),
            short_bases=("SHORT",),
            price_return=0.0,
            funding_return=-0.001,
            base_price_contributions={"LONG": 0.0, "SHORT": 0.0},
            base_funding_contributions={"LONG": 0.001, "SHORT": -0.002},
        )

        self.assertAlmostEqual(adjusted_event_funding(event, 1.0), -0.001)
        self.assertAlmostEqual(adjusted_event_funding(event, 0.0), -0.002)
        metrics = portfolio_metrics([event], cost_bps=0.0, favorable_funding_multiplier=0.0)
        self.assertAlmostEqual(metrics["funding_expectancy_bps"], -20.0)


class GateMembershipMomentumTrainTests(unittest.TestCase):
    def _write_train_fixture(self, root: Path) -> tuple[Path, Path]:
        train_root = root / "normalized" / "train"
        universe = []
        files = []
        for index in range(24):
            base = f"A{index:02d}"
            symbol = f"{base}_USDT"
            direction = 0.01 if index >= 12 else -0.01
            market = _market(base, direction)
            kline_path = train_root / "gateio" / "klines" / f"{symbol}.json"
            funding_path = train_root / "gateio" / "funding" / f"{symbol}.json"
            kline_path.parent.mkdir(parents=True, exist_ok=True)
            funding_path.parent.mkdir(parents=True, exist_ok=True)
            kline_path.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_daily_ohlcv_v1",
                        "exchange": "gateio",
                        "symbol": symbol,
                        "interval": "1d",
                        "rows": [
                            {
                                "ts": day * DAY_SEC,
                                "open": market.opens[day],
                                "high": max(market.opens[day], market.closes[day]),
                                "low": min(market.opens[day], market.closes[day]),
                                "close": market.closes[day],
                                "volume_base": 20_000.0,
                                "volume_quote": market.quote_volumes[day],
                                "observed_hours": 24,
                            }
                            for day in range(180)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            funding_path.write_text(
                json.dumps(
                    {
                        "schema": "trading_mvp_funding_settlements_v1",
                        "exchange": "gateio",
                        "symbol": symbol,
                        "rows": [],
                    }
                ),
                encoding="utf-8",
            )
            from gate_historical_membership_history_plan import sha256_file

            universe.append(
                {
                    "exchange": "gateio",
                    "symbol": symbol,
                    "base": base,
                    "canonical_asset_id": f"coingecko:{base.lower()}",
                    "non_binance_baseline": True,
                }
            )
            files.append(
                {
                    "symbol": symbol,
                    "kline_path": str(kline_path),
                    "kline_sha256": sha256_file(kline_path),
                    "funding_path": str(funding_path),
                    "funding_sha256": sha256_file(funding_path),
                }
            )
        train_manifest = {
            "schema": "trading_mvp_gate_membership_daily_history_split_v1",
            "stage": "train_view",
            "range": {"start_sec": 0, "end_sec": 180 * DAY_SEC},
            "universe": universe,
            "normalized_files": files,
            "oos_paths_present": False,
        }
        from gate_historical_membership_history_plan import sha256_json

        train_manifest["artifact_hash"] = sha256_json(train_manifest)
        train_manifest_path = train_root / "manifest.json"
        train_manifest_path.write_text(json.dumps(train_manifest), encoding="utf-8")

        quality = {
            "schema": "trading_mvp_gate_historical_membership_history_quality_v1",
            "final": True,
            "accepted": True,
            "decision": "GATE_MEMBERSHIP_HISTORY_QUALITY_ACCEPTED_READY_FOR_FROZEN_TRAIN_PLANONLY",
            "plan_hash": "a" * 64,
            "normalized_manifest_hash": "b" * 64,
            "train_manifest_path": str(train_manifest_path),
            "train_manifest_hash": train_manifest["artifact_hash"],
            "oos_commitment_hash": "c" * 64,
            "data_access_audit": {"returns_computed": False, "oos_read": False},
        }
        quality["artifact_hash"] = __import__(
            "gate_historical_membership_history_quality"
        )._quality_hash(quality)
        quality_path = root / "quality.json"
        quality_path.write_text(json.dumps(quality), encoding="utf-8")
        return quality_path, train_manifest_path

    def test_train_plan_contains_only_train_path_and_oos_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_manifest_path = self._write_train_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))

            plan = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=None,
                run_id="membership_train_fixture",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T04:00:00Z",
            )

            self.assertEqual(plan["train_input"]["manifest_path"], str(train_manifest_path.resolve()))
            self.assertEqual(plan["oos_commitment_hash"], "c" * 64)
            self.assertNotIn("quality_report_path", plan["train_input"])
            def oos_artifact_paths(value: object) -> list[str]:
                if isinstance(value, dict):
                    found = [
                        str(key)
                        for key in value
                        if "oos" in str(key).lower() and str(key).lower().endswith("_path")
                    ]
                    for item in value.values():
                        found.extend(oos_artifact_paths(item))
                    return found
                if isinstance(value, list):
                    return [key for item in value for key in oos_artifact_paths(item)]
                return []

            self.assertEqual(oos_artifact_paths(plan), [])
            self.assertEqual(plan["plan_hash"], train_plan_hash(plan))

    def test_train_evaluator_is_deterministic_and_never_reads_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, _ = self._write_train_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            plan_path = root / "train-plan.json"
            first_path = root / "first.json"
            second_path = root / "second.json"
            plan = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=plan_path,
                run_id="membership_train_fixture",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T04:00:00Z",
            )

            first = evaluate_train_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=first_path,
                max_runtime_sec=120,
            )
            second = evaluate_train_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=second_path,
                max_runtime_sec=120,
            )

            self.assertEqual(first["decision"], FEASIBLE_DECISION)
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertFalse(first["data_access_audit"]["oos_files_opened"])
            self.assertFalse(first["oos_read"])


class GateMembershipMomentumPowerShellWiringTests(unittest.TestCase):
    def test_run_mvp_wires_bounded_offline_train_plan_and_evaluator(self) -> None:
        script = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((REPO_ROOT / "trading_mvp" / "run_mvp.ps1"))

        self.assertIn('"fast-edge-membership-momentum-train-plan"', script)
        self.assertIn('"fast-edge-membership-momentum-train"', script)
        plan_start = script.index('"fast-edge-membership-momentum-train-plan" {')
        evaluate_start = script.index('"fast-edge-membership-momentum-train" {', plan_start)
        next_action = script.index('"fast-edge-basis-universe-build" {', evaluate_start)
        plan_block = script[plan_start:evaluate_start]
        evaluate_block = script[evaluate_start:next_action]
        self.assertIn("Assert-BasisActionGate -OfflineWork", plan_block)
        self.assertIn('"plan"', plan_block)
        self.assertIn('"--quality-report", $PlanPath', plan_block)
        self.assertIn('"--expected-quality-hash", $ExpectedArtifactHash', plan_block)
        self.assertIn("MaxRuntimeSec must be <= 1800", plan_block)
        self.assertIn("Assert-BasisActionGate -OfflineWork", evaluate_block)
        self.assertIn('"evaluate"', evaluate_block)
        self.assertIn('"--expected-plan-hash", $ExpectedPlanHash', evaluate_block)
        self.assertIn("MaxRuntimeSec must be <= 1800", evaluate_block)


if __name__ == "__main__":
    unittest.main()
