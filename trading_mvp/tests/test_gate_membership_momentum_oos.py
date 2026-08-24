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

from gate_historical_membership_history_plan import sha256_file, sha256_json  # noqa: E402
from gate_historical_membership_history_quality import _quality_hash  # noqa: E402
from gate_membership_momentum import DAY_SEC  # noqa: E402
from gate_membership_momentum_oos import (  # noqa: E402
    HISTORICAL_ACCEPT_DECISION,
    OOS_REJECTED_DECISION,
    build_oos_plan,
    evaluate_oos_plan,
    oos_plan_hash,
)
from gate_membership_momentum_train import (  # noqa: E402
    FEASIBLE_DECISION,
    build_train_plan,
    evaluate_train_plan,
)


TRAIN_DAYS = 170
OOS_DAYS = 210
TOTAL_DAYS = TRAIN_DAYS + OOS_DAYS


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _manifest_hash(payload: dict) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"generated_at_utc", "artifact_hash"}
        }
    )


class GateMembershipMomentumOosTests(unittest.TestCase):
    def _write_fixture(self, root: Path, *, oos_edge: bool = True) -> dict[str, object]:
        train_root = root / "normalized" / "train"
        oos_root = root / "normalized" / "oos-sealed"
        universe: list[dict] = []
        train_files: list[dict] = []
        oos_files: list[dict] = []
        for index in range(24):
            base = f"A{index:02d}"
            symbol = f"{base}_USDT"
            train_return = 0.01 if index >= 12 else -0.01
            rows: list[dict] = []
            price = 100.0
            for day in range(TOTAL_DAYS):
                daily_return = train_return if day < TRAIN_DAYS or oos_edge else 0.0
                open_price = price
                price *= 1.0 + daily_return
                rows.append(
                    {
                        "ts": day * DAY_SEC,
                        "open": open_price,
                        "high": max(open_price, price),
                        "low": min(open_price, price),
                        "close": price,
                        "volume_base": 20_000.0,
                        "volume_quote": 2_000_000.0,
                        "observed_hours": 24,
                    }
                )
            universe.append(
                {
                    "exchange": "gateio",
                    "symbol": symbol,
                    "base": base,
                    "canonical_asset_id": f"coingecko:{base.lower()}",
                    "non_binance_baseline": True,
                }
            )
            stage_files = []
            for stage_root, stage_rows, target in (
                (train_root, rows[:TRAIN_DAYS], train_files),
                (oos_root, rows[TRAIN_DAYS:], oos_files),
            ):
                kline_path = stage_root / "gateio" / "klines" / f"{symbol}.json"
                funding_path = stage_root / "gateio" / "funding" / f"{symbol}.json"
                _write_json(
                    kline_path,
                    {
                        "schema": "trading_mvp_daily_ohlcv_v1",
                        "exchange": "gateio",
                        "symbol": symbol,
                        "interval": "1d",
                        "rows": stage_rows,
                    },
                )
                _write_json(
                    funding_path,
                    {
                        "schema": "trading_mvp_funding_settlements_v1",
                        "exchange": "gateio",
                        "symbol": symbol,
                        "rows": [],
                    },
                )
                target.append(
                    {
                        "symbol": symbol,
                        "kline_path": str(kline_path),
                        "kline_sha256": sha256_file(kline_path),
                        "funding_path": str(funding_path),
                        "funding_sha256": sha256_file(funding_path),
                    }
                )
                stage_files.append(target[-1])
        train_manifest = {
            "schema": "trading_mvp_gate_membership_daily_history_split_v1",
            "stage": "train_view",
            "range": {"start_sec": 0, "end_sec": TRAIN_DAYS * DAY_SEC},
            "sealed": False,
            "oos_paths_present": False,
            "universe": universe,
            "normalized_files": train_files,
        }
        train_manifest["artifact_hash"] = _manifest_hash(train_manifest)
        train_manifest_path = train_root / "manifest.json"
        _write_json(train_manifest_path, train_manifest)
        oos_manifest = {
            "schema": "trading_mvp_gate_membership_daily_history_split_v1",
            "stage": "sealed_oos",
            "range": {
                "start_sec": TRAIN_DAYS * DAY_SEC,
                "end_sec": TOTAL_DAYS * DAY_SEC,
            },
            "sealed": True,
            "oos_paths_present": True,
            "universe": universe,
            "normalized_files": oos_files,
        }
        oos_manifest["artifact_hash"] = _manifest_hash(oos_manifest)
        oos_manifest_path = oos_root / "manifest.json"
        _write_json(oos_manifest_path, oos_manifest)
        quality = {
            "schema": "trading_mvp_gate_historical_membership_history_quality_v1",
            "final": True,
            "accepted": True,
            "decision": "GATE_MEMBERSHIP_HISTORY_QUALITY_ACCEPTED_READY_FOR_FROZEN_TRAIN_PLANONLY",
            "plan_hash": "a" * 64,
            "normalized_manifest_hash": "b" * 64,
            "train_manifest_path": str(train_manifest_path),
            "train_manifest_hash": train_manifest["artifact_hash"],
            "oos_manifest_path": str(oos_manifest_path),
            "oos_commitment_hash": oos_manifest["artifact_hash"],
            "data_access_audit": {"returns_computed": False, "oos_read": False},
        }
        quality["artifact_hash"] = _quality_hash(quality)
        quality_path = root / "quality.json"
        _write_json(quality_path, quality)
        train_plan_path = root / "train-plan.json"
        train_plan = build_train_plan(
            quality_report_path=quality_path,
            expected_quality_hash=quality["artifact_hash"],
            output_path=train_plan_path,
            run_id="membership_oos_train_fixture",
            max_runtime_sec=120,
            generated_at_utc="2026-07-17T05:00:00Z",
        )
        train_result_path = root / "train-result.json"
        train_result = evaluate_train_plan(
            plan_path=train_plan_path,
            expected_plan_hash=train_plan["plan_hash"],
            output_path=train_result_path,
            max_runtime_sec=120,
        )
        self.assertEqual(train_result["decision"], FEASIBLE_DECISION)
        return {
            "quality_path": quality_path,
            "quality": quality,
            "train_plan_path": train_plan_path,
            "train_plan": train_plan,
            "train_result_path": train_result_path,
            "train_result": train_result,
            "oos_manifest_path": oos_manifest_path,
            "oos_manifest": oos_manifest,
        }

    def _build_oos_plan(self, root: Path, fixture: dict[str, object]) -> tuple[Path, dict]:
        output = root / "oos-plan.json"
        plan = build_oos_plan(
            quality_report_path=fixture["quality_path"],
            expected_quality_hash=fixture["quality"]["artifact_hash"],
            train_plan_path=fixture["train_plan_path"],
            expected_train_plan_hash=fixture["train_plan"]["plan_hash"],
            train_result_path=fixture["train_result_path"],
            expected_train_result_hash=fixture["train_result"]["deterministic_result_hash"],
            output_path=output,
            run_id="membership_oos_fixture",
            max_runtime_sec=120,
            generated_at_utc="2026-07-17T06:00:00Z",
        )
        return output, plan

    def test_oos_plan_is_hash_bound_to_feasible_train_and_sealed_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self._write_fixture(root)
            _, plan = self._build_oos_plan(root, fixture)

            self.assertEqual(plan["plan_hash"], oos_plan_hash(plan))
            self.assertEqual(plan["oos_input"]["manifest_path"], str(fixture["oos_manifest_path"].resolve()))
            self.assertEqual(plan["oos_input"]["manifest_hash"], fixture["oos_manifest"]["artifact_hash"])
            self.assertEqual(len(plan["fold_contract"]), 5)
            self.assertTrue(all(fold["days"] == 42 for fold in plan["fold_contract"]))
            self.assertEqual(plan["strategy"], fixture["train_plan"]["strategy"])
            self.assertEqual(plan["cost_contract"], fixture["train_plan"]["cost_contract"])
            self.assertFalse(plan["network_access"])
            self.assertFalse(plan["grid_search"])
            self.assertFalse(plan["retune"])

    def test_oos_evaluator_is_deterministic_five_fold_and_stops_at_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self._write_fixture(root)
            plan_path, plan = self._build_oos_plan(root, fixture)

            first = evaluate_oos_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "oos-first.json",
                max_runtime_sec=120,
            )
            second = evaluate_oos_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "oos-second.json",
                max_runtime_sec=120,
            )

            self.assertEqual(first["decision"], HISTORICAL_ACCEPT_DECISION)
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertGreaterEqual(first["normal_metrics"]["independent_rebalances"], 20)
            self.assertEqual(len(first["fold_metrics"]), 5)
            self.assertGreaterEqual(first["positive_folds"], 4)
            self.assertGreater(first["bootstrap"]["expectancy_lower_95_bps"], 0.0)
            self.assertGreaterEqual(first["stress_metrics"]["total_net_expectancy_bps"], 0.0)
            self.assertEqual(first["capacity_status"], "REQUIRES_EXECUTION_PROBE")
            self.assertEqual(
                first["next_allowed_command"],
                "fast-edge-membership-momentum-execution-probe-plan",
            )
            self.assertTrue(first["data_access_audit"]["oos_files_opened"])
            self.assertFalse(first["data_access_audit"]["grid_search"])
            self.assertFalse(first["live_orders"])

    def test_negative_oos_closes_branch_without_retune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self._write_fixture(root, oos_edge=False)
            plan_path, plan = self._build_oos_plan(root, fixture)

            result = evaluate_oos_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "oos-reject.json",
                max_runtime_sec=120,
            )

            self.assertEqual(result["decision"], OOS_REJECTED_DECISION)
            self.assertIn("price_only_net_expectancy_not_positive", result["rejection_reasons"])
            self.assertEqual(result["next_allowed_command"], "none_membership_momentum_branch_closed_no_retune")
            self.assertFalse(result["retune_allowed"])

    def test_tampered_train_result_is_rejected_before_oos_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self._write_fixture(root)
            train_result_path = fixture["train_result_path"]
            payload = json.loads(train_result_path.read_text(encoding="utf-8"))
            payload["decision"] = "tampered"
            _write_json(train_result_path, payload)

            with self.assertRaisesRegex(ValueError, "train result"):
                self._build_oos_plan(root, fixture)

    def test_runtime_cap_is_thirty_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self._write_fixture(root)

            with self.assertRaisesRegex(ValueError, "max_runtime_sec must be in"):
                build_oos_plan(
                    quality_report_path=fixture["quality_path"],
                    expected_quality_hash=fixture["quality"]["artifact_hash"],
                    train_plan_path=fixture["train_plan_path"],
                    expected_train_plan_hash=fixture["train_plan"]["plan_hash"],
                    train_result_path=fixture["train_result_path"],
                    expected_train_result_hash=fixture["train_result"]["deterministic_result_hash"],
                    output_path=None,
                    run_id="too_long",
                    max_runtime_sec=1801,
                )


class GateMembershipMomentumOosPowerShellTests(unittest.TestCase):
    def test_run_mvp_wires_offline_oos_plan_and_evaluator(self) -> None:
        script = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((REPO_ROOT / "trading_mvp" / "run_mvp.ps1"))

        self.assertIn('"fast-edge-membership-momentum-oos-plan"', script)
        self.assertIn('"fast-edge-membership-momentum-oos"', script)
        self.assertIn("gate_membership_momentum_oos.py", script)
        self.assertIn("ExpectedFeasibilityResultHash is required for fast-edge-membership-momentum-oos-plan", script)
        self.assertIn("MaxRuntimeSec must be <= 1800 for fast-edge-membership-momentum-oos", script)


if __name__ == "__main__":
    unittest.main()
