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

from funding_regime_persistence_v2 import (  # noqa: E402
    build_plan_from_basis_v2_cache,
    write_plan_from_basis_v2_cache,
)
from trading_mvp.tests.test_funding_regime_persistence_v2 import (  # noqa: E402
    DAY_SEC,
    _fixture,
)

try:
    evaluator = importlib.import_module("funding_regime_persistence_v2_evaluator")
except ModuleNotFoundError:
    evaluator = None


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


def _evaluation_fixture(root: Path, *, missing_gate_days_for: str | None = None) -> tuple[dict, Path]:
    quality_path, bank_path, goal_path = _fixture(root)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    train_path = Path(quality["train_output"])
    funding_path = Path(quality["funding_output"])
    split = quality["split"]
    ranking = quality["train_liquidity_ranking"]

    candle_rows: list[dict] = []
    for day_start in range(split["train_start_sec"], split["train_end_sec"], DAY_SEC):
        for candidate in ranking:
            candle_rows.append(
                {
                    "schema": "trading_mvp_historical_basis_v2_normalized_candles_v2",
                    "canonical_asset_id": candidate["canonical_asset_id"],
                    "base": candidate["base"],
                    "ts": day_start,
                    "mexc_trade_open": 100.0,
                    "gateio_trade_open": 100.0,
                }
            )
    _write_jsonl(train_path, candle_rows)

    funding_rows: list[dict] = []
    first_day = split["train_start_sec"] - 3 * DAY_SEC
    last_day = split["train_end_sec"]
    for candidate in ranking:
        canonical_id = candidate["canonical_asset_id"]
        base = candidate["base"]
        for day_index, day_start in enumerate(range(first_day, last_day, DAY_SEC)):
            if canonical_id == missing_gate_days_for and day_index % 2:
                continue
            phase = (day_index // 15) % 2
            mexc_rate = 0.0012 if phase == 0 else 0.0
            gate_rate = 0.0 if phase == 0 else 0.0012
            for venue, rate in (("mexc", mexc_rate), ("gateio", gate_rate)):
                ts = day_start + 3_600
                funding_rows.append(
                    {
                        "schema": "trading_mvp_historical_basis_v2_funding_events_v2",
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
    _write_jsonl(funding_path, funding_rows)

    quality["train_row_count"] = len(candle_rows)
    quality["funding_event_count"] = len(funding_rows)
    quality["train_output_sha256"] = _sha256(train_path)
    quality["funding_output_sha256"] = _sha256(funding_path)
    _write_json(quality_path, quality)

    plan_path = root / "funding-regime-plan.json"
    result = write_plan_from_basis_v2_cache(
        quality_path,
        plan_path,
        hypothesis_bank_path=bank_path,
        goal_path=goal_path,
        created_at_utc="2026-07-16T21:00:00+00:00",
        max_runtime_sec=300,
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert result["plan_hash"] == plan["plan_hash"]
    return plan, plan_path


class FundingRegimePersistenceEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(
            evaluator,
            "funding_regime_persistence_v2_evaluator module must be implemented",
        )
        for name in (
            "aggregate_daily_funding",
            "detect_regime_episodes",
            "run_train_feasibility",
        ):
            self.assertTrue(callable(getattr(evaluator, name, None)), name)

    def test_daily_funding_uses_completed_settlements_and_preserves_direction(self) -> None:
        rows = [
            {"canonical_asset_id": "asset:a", "venue": "mexc", "settlement_ts": DAY_SEC + 1, "funding_rate": 0.0012, "event_id": "1"},
            {"canonical_asset_id": "asset:a", "venue": "gateio", "settlement_ts": DAY_SEC + 2, "funding_rate": 0.0, "event_id": "2"},
            {"canonical_asset_id": "asset:a", "venue": "mexc", "settlement_ts": 2 * DAY_SEC + 1, "funding_rate": 0.0, "event_id": "3"},
            {"canonical_asset_id": "asset:a", "venue": "gateio", "settlement_ts": 2 * DAY_SEC + 2, "funding_rate": 0.0012, "event_id": "4"},
            {"canonical_asset_id": "asset:a", "venue": "mexc", "settlement_ts": 3 * DAY_SEC, "funding_rate": 9.0, "event_id": "future"},
        ]

        daily = evaluator.aggregate_daily_funding(
            rows,
            candidate_ids={"asset:a"},
            before_ts=3 * DAY_SEC,
        )

        self.assertEqual(daily["asset:a"][1]["differential_bps"], 12.0)
        self.assertEqual(daily["asset:a"][2]["differential_bps"], -12.0)
        self.assertNotIn(3, daily["asset:a"])

    def test_episode_detection_is_non_overlapping_and_has_both_directions(self) -> None:
        daily = {"asset:a": {}}
        for day in range(40):
            sign = 1.0 if (day // 10) % 2 == 0 else -1.0
            daily["asset:a"][day] = {
                "differential_bps": 12.0 * sign,
                "mexc_bps": 12.0 if sign > 0 else 0.0,
                "gateio_bps": 0.0 if sign > 0 else 12.0,
            }

        episodes = evaluator.detect_regime_episodes(
            daily,
            train_start_sec=3 * DAY_SEC,
            train_end_sec=40 * DAY_SEC,
            candidate_ids={"asset:a"},
            entry_bar_timestamps={"asset:a": set(range(4 * DAY_SEC, 40 * DAY_SEC, DAY_SEC))},
            confirmation_days=3,
            minimum_abs_daily_bps=9.0,
            adverse_exit_days=2,
            maximum_holding_days=14,
        )

        self.assertGreaterEqual(len(episodes), 3)
        self.assertEqual({row["direction"] for row in episodes}, {"short_mexc_long_gate", "long_mexc_short_gate"})
        for left, right in zip(episodes, episodes[1:]):
            self.assertLessEqual(left["exit_day"], right["signal_day"])

    def test_train_feasibility_is_hash_bound_deterministic_and_keeps_oos_embargo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, plan_path = _evaluation_fixture(root)
            first_path = root / "feasibility-a.json"
            second_path = root / "feasibility-b.json"

            first = evaluator.run_train_feasibility(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=first_path,
                max_runtime_sec=1_800,
            )
            second = evaluator.run_train_feasibility(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=second_path,
                max_runtime_sec=1_800,
            )

            self.assertEqual(first["verdict"], "FEASIBLE_FOR_OOS")
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertGreaterEqual(first["metrics"]["independent_regime_episodes"], 10)
            self.assertGreaterEqual(first["metrics"]["unique_signal_dates"], 5)
            self.assertEqual(
                set(first["metrics"]["route_directions"]),
                {"short_mexc_long_gate", "long_mexc_short_gate"},
            )
            self.assertFalse(first["data_access_audit"]["oos_values_read"])
            self.assertFalse(first["data_access_audit"]["pnl_computed"])
            self.assertEqual(first["next_allowed_action"], "implement_hash_bound_oos_evaluator")
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_low_dual_leg_coverage_is_insufficient_not_feasible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, plan_path = _evaluation_fixture(root, missing_gate_days_for="coingecko:h-humanity")
            output = root / "feasibility.json"

            result = evaluator.run_train_feasibility(
                plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=1_800,
            )

            self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
            self.assertIn("dual_leg_coverage_below_minimum", result["reasons"])
            self.assertFalse(result["data_access_audit"]["oos_values_read"])

    def test_expected_plan_hash_mismatch_fails_before_loading_train_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, plan_path = _evaluation_fixture(root)

            with self.assertRaisesRegex(ValueError, "Expected plan hash"):
                evaluator.run_train_feasibility(
                    plan_path,
                    expected_plan_hash="0" * 64,
                    output_path=root / "must-not-exist.json",
                )
            self.assertFalse((root / "must-not-exist.json").exists())


if __name__ == "__main__":
    unittest.main()
