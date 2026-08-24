from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from funding_regime_persistence_v2 import write_plan_from_basis_v2_cache  # noqa: E402
from funding_regime_persistence_v2_evaluator import run_train_feasibility  # noqa: E402
from trading_mvp.tests.test_funding_regime_persistence_v2 import (  # noqa: E402
    DAY_SEC,
    _fixture,
)

try:
    oos = importlib.import_module("funding_regime_persistence_v2_oos")
except ModuleNotFoundError:
    oos = None


HOUR_SEC = 3_600
CANDLE_SCHEMA = "trading_mvp_historical_basis_v2_normalized_candles_v2"
FUNDING_SCHEMA = "trading_mvp_historical_basis_v2_funding_events_v2"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _full_fixture(root: Path) -> tuple[dict, Path, dict, Path]:
    quality_path, bank_path, goal_path = _fixture(root)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    split = quality["split"]
    ranking = quality["train_liquidity_ranking"]
    train_path = Path(quality["train_output"])
    oos_path = Path(quality["oos_output"])
    funding_path = Path(quality["funding_output"])

    train_rows: list[dict] = []
    for ts in range(split["train_start_sec"], split["train_end_sec"], DAY_SEC):
        for candidate in ranking:
            train_rows.append(
                {
                    "schema": CANDLE_SCHEMA,
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": candidate["base"],
                    "segment_id": 0,
                    "ts": ts,
                    "mexc_trade_open": 100.0,
                    "gateio_trade_open": 100.0,
                }
            )

    oos_rows: list[dict] = []
    for ts in range(split["oos_start_sec"], split["oos_end_sec"], HOUR_SEC):
        for candidate in ranking:
            oos_rows.append(
                {
                    "schema": CANDLE_SCHEMA,
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": candidate["base"],
                    "segment_id": 0,
                    "ts": ts,
                    "mexc_trade_open": 100.0,
                    "gateio_trade_open": 100.0,
                }
            )

    funding_rows: list[dict] = []
    first_day = split["train_start_sec"] - 3 * DAY_SEC
    last_day = split["oos_end_sec"]
    for candidate_index, candidate in enumerate(ranking):
        canonical_id = candidate["canonical_asset_id"]
        base = candidate["base"]
        for day_index, day_start in enumerate(range(first_day, last_day, DAY_SEC)):
            positive_mexc = ((day_index + candidate_index * 2) // 14) % 2 == 0
            mexc_rate = 0.006 if positive_mexc else 0.0
            gate_rate = 0.0 if positive_mexc else 0.006
            for venue, rate in (("mexc", mexc_rate), ("gateio", gate_rate)):
                ts = day_start + HOUR_SEC
                funding_rows.append(
                    {
                        "schema": FUNDING_SCHEMA,
                        "canonical_asset_id": canonical_id,
                        "base": base,
                        "venue": venue,
                        "settlement_ts": ts,
                        "ts": ts,
                        "funding_rate": rate,
                        "event_id": f"{canonical_id}:{venue}:{ts}",
                    }
                )
    funding_rows.sort(key=lambda row: (row["settlement_ts"], row["canonical_asset_id"], row["venue"]))
    _write_jsonl(train_path, train_rows)
    _write_jsonl(oos_path, oos_rows)
    _write_jsonl(funding_path, funding_rows)

    quality["train_row_count"] = len(train_rows)
    quality["oos_row_count"] = len(oos_rows)
    quality["funding_event_count"] = len(funding_rows)
    quality["train_output_sha256"] = _sha256(train_path)
    quality["oos_output_sha256"] = _sha256(oos_path)
    quality["funding_output_sha256"] = _sha256(funding_path)
    _write_json(quality_path, quality)

    plan_path = root / "funding-regime-plan.json"
    write_plan_from_basis_v2_cache(
        quality_path,
        plan_path,
        hypothesis_bank_path=bank_path,
        goal_path=goal_path,
        created_at_utc="2026-07-16T21:00:00+00:00",
        max_runtime_sec=300,
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    feasibility_path = root / "train-feasibility.json"
    feasibility = run_train_feasibility(
        plan_path,
        expected_plan_hash=plan["plan_hash"],
        output_path=feasibility_path,
        max_runtime_sec=1_800,
    )
    if feasibility["verdict"] != "FEASIBLE_FOR_OOS":
        raise AssertionError(feasibility)
    return plan, plan_path, feasibility, feasibility_path


class FundingRegimePersistenceOosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(oos, "funding_regime_persistence_v2_oos module must be implemented")
        for name in (
            "calculate_episode_trade",
            "summarize_trades",
            "historical_oos_verdict",
            "run_oos_evaluation",
            "validate_oos_result",
        ):
            self.assertTrue(callable(getattr(oos, name, None)), name)

    def test_episode_math_separates_price_funding_costs_and_stress(self) -> None:
        episode = {
            "canonical_asset_id": "asset:a",
            "signal_day": 0,
            "entry_day": 1,
            "exit_day": 3,
            "holding_days": 2,
            "direction": "short_mexc_long_gate",
            "exit_reason": "maximum_holding_days",
        }
        candles = {
            DAY_SEC: {
                "ts": DAY_SEC,
                "segment_id": 0,
                "mexc_trade_open": 100.0,
                "gateio_trade_open": 100.0,
            },
            3 * DAY_SEC: {
                "ts": 3 * DAY_SEC,
                "segment_id": 0,
                "mexc_trade_open": 90.0,
                "gateio_trade_open": 110.0,
            },
        }
        funding = [
            {"venue": "mexc", "settlement_ts": DAY_SEC + HOUR_SEC, "funding_rate": 0.001},
            {"venue": "gateio", "settlement_ts": DAY_SEC + HOUR_SEC, "funding_rate": 0.0002},
        ]

        trade = oos.calculate_episode_trade(
            episode,
            candles_by_ts=candles,
            funding_events=funding,
            notional_per_leg=500.0,
            normal_cycle_cost_bps=78.0,
            stress_cycle_cost_bps=116.0,
            stress_favorable_funding_haircut=0.5,
        )

        self.assertAlmostEqual(trade["price_pnl_quote"], 100.0)
        self.assertAlmostEqual(trade["funding_pnl_quote"], 0.4)
        self.assertAlmostEqual(trade["normal_cost_quote"], 3.9)
        self.assertAlmostEqual(trade["normal_net_pnl_quote"], 96.5)
        self.assertAlmostEqual(trade["stress_funding_pnl_quote"], 0.15)
        self.assertAlmostEqual(trade["stress_cost_quote"], 5.8)
        self.assertAlmostEqual(trade["stress_net_pnl_quote"], 94.35)

    def test_historical_verdict_cannot_be_rescued_by_win_rate(self) -> None:
        gates = {
            "minimum_independent_regime_episodes": 20,
            "minimum_unique_signal_dates": 10,
            "total_net_expectancy_after_costs_gt": 0.0,
            "profit_factor_gte": 1.2,
            "positive_event_rate_gte": 0.6,
            "minimum_positive_walk_forward_folds": 4,
            "stress_total_net_pnl_gte": 0.0,
            "cluster_bootstrap_95pct_expectancy_lower_bound_gt": 0.0,
            "maximum_single_base_positive_pnl_share": 0.25,
            "maximum_single_date_positive_pnl_share": 0.25,
            "maximum_single_event_positive_pnl_share": 0.25,
            "maximum_drawdown_fraction_of_collateral": 0.1,
            "maximum_holding_days": 14,
        }
        metrics = {
            "independent_episode_count": 20,
            "unique_signal_dates": 10,
            "total_net_expectancy_quote": -0.01,
            "profit_factor": 0.99,
            "positive_event_rate": 0.95,
            "positive_walk_forward_folds": 5,
            "stress_total_net_pnl_quote": -1.0,
            "cluster_bootstrap_lower_95_quote": -0.01,
            "maximum_single_base_positive_pnl_share": 0.2,
            "maximum_single_date_positive_pnl_share": 0.2,
            "maximum_single_event_positive_pnl_share": 0.1,
            "maximum_drawdown_fraction_of_collateral": 0.02,
            "maximum_observed_holding_days": 14,
        }

        verdict, reasons = oos.historical_oos_verdict(metrics, gates)

        self.assertEqual(verdict, "REJECT")
        self.assertIn("total_net_expectancy_after_costs", reasons)
        self.assertIn("stress_total_net_pnl", reasons)

    def test_full_oos_is_hash_bound_deterministic_and_never_authorizes_live(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, plan_path, feasibility, feasibility_path = _full_fixture(root)
            first_path = root / "oos-a.json"
            second_path = root / "oos-b.json"
            kwargs = {
                "expected_plan_hash": plan["plan_hash"],
                "feasibility_path": feasibility_path,
                "expected_feasibility_result_hash": feasibility["deterministic_result_hash"],
                "max_runtime_sec": 1_800,
            }

            first = oos.run_oos_evaluation(plan_path, output_path=first_path, **kwargs)
            second = oos.run_oos_evaluation(plan_path, output_path=second_path, **kwargs)

            self.assertEqual(first["verdict"], "ACCEPT_FOR_EXECUTION_PROBE")
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertGreaterEqual(first["metrics"]["independent_episode_count"], 20)
            self.assertGreaterEqual(first["metrics"]["unique_signal_dates"], 10)
            self.assertGreaterEqual(first["metrics"]["positive_walk_forward_folds"], 4)
            self.assertTrue(first["data_access_audit"]["oos_values_read"])
            self.assertFalse(first["data_access_audit"]["grid_search"])
            self.assertFalse(first["data_access_audit"]["retune"])
            self.assertFalse(first["permissions"]["live_orders"])
            self.assertEqual(first["next_allowed_action"], "create_execution_probe_planonly")
            oos.validate_oos_result(first, require_accept=True)

    def test_wrong_feasibility_hash_fails_before_opening_oos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, plan_path, _, feasibility_path = _full_fixture(root)
            output = root / "must-not-exist.json"

            with self.assertRaisesRegex(ValueError, "feasibility result hash"):
                oos.run_oos_evaluation(
                    plan_path,
                    expected_plan_hash=plan["plan_hash"],
                    feasibility_path=feasibility_path,
                    expected_feasibility_result_hash="0" * 64,
                    output_path=output,
                )
            self.assertFalse(output.exists())

    def test_run_mvp_exposes_bounded_hash_bound_oos_action(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))(wrapper)
        self.assertIn('"fast-edge-funding-persistence-v2-oos"', text)
        self.assertIn('[string]$ExpectedFeasibilityResultHash = ""', text)
        self.assertIn(
            "MaxRuntimeSec must be <= 1800 for fast-edge-funding-persistence-v2-oos",
            text,
        )
        self.assertIn(
            'Join-Path $codeSnapshot.snapshot_path "funding_regime_persistence_v2_oos.py"',
            text,
        )

    def test_oos_has_visible_deterministic_repeat_launcher(self) -> None:
        launcher = (
            Path(__file__).resolve().parents[2]
            / "tools"
            / "run_funding_regime_persistence_v2_oos_visible.ps1"
        )
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("[int]$MaxRuntimeSec = 1800", text)
        self.assertIn("[int]$HoldOpenSec = 60", text)
        self.assertIn("check_active_run_gate.ps1", text)
        self.assertIn("fast-edge-funding-persistence-v2-oos", text)
        self.assertIn("deterministic repeat mismatch", text)
        self.assertIn("Start-Process", text)
        self.assertIn("-WindowStyle Normal", text)
        self.assertIn("launch_record_path", text)
        self.assertNotIn("-WindowStyle Hidden", text)


if __name__ == "__main__":
    unittest.main()
