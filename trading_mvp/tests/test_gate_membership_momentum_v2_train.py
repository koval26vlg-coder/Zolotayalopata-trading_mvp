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

import gate_historical_membership_v3_history_quality as v3_quality  # noqa: E402
from gate_membership_momentum import DAY_SEC  # noqa: E402
from gate_membership_momentum_v2_train import (  # noqa: E402
    FEASIBLE_DECISION,
    INFEASIBLE_DECISION,
    PLAN_DECISION,
    build_train_plan,
    evaluate_train_plan,
    train_plan_hash,
)


START_DAY = 20_000
TRAIN_VIEW_DAYS = 120


def _contains_oos_path(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if "oos" in normalized and normalized.endswith("_path"):
                return True
            if _contains_oos_path(item):
                return True
    if isinstance(value, list):
        return any(_contains_oos_path(item) for item in value)
    return False


def _write_fixture(root: Path, *, trending: bool = True) -> tuple[Path, Path, Path]:
    train_root = root / "normalized" / "train"
    start_sec = START_DAY * DAY_SEC
    end_sec = (START_DAY + TRAIN_VIEW_DAYS) * DAY_SEC
    universe: list[dict] = []
    files: list[dict] = []
    for index in range(24):
        base = f"A{index:02d}"
        symbol = f"{base}_USDT"
        daily_return = (0.01 if index >= 12 else -0.01) if trending else 0.0
        price = 100.0
        rows = []
        for offset in range(TRAIN_VIEW_DAYS):
            open_price = price
            price *= 1.0 + daily_return
            rows.append(
                {
                    "ts": (START_DAY + offset) * DAY_SEC,
                    "open": open_price,
                    "high": max(open_price, price),
                    "low": min(open_price, price),
                    "close": price,
                    "volume_base": 20_000.0,
                    "volume_quote": 2_000_000.0,
                    "observed_hours": 24,
                }
            )
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
                    "rows": rows,
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
        universe.append(
            {
                "exchange": "gateio",
                "symbol": symbol,
                "base": base,
                "canonical_asset_id": f"coingecko:asset-{index}",
                "listed_from_ts": start_sec - 30 * DAY_SEC,
                "listed_to_ts": None,
                "status": "active",
                "is_delisted": False,
                "survivorship_status": "trading_at_train_boundary",
                "lifecycle_end_resolution": "not_observed_by_train_boundary",
                "resolved_lifecycle_end_sec": None,
            }
        )
        files.append(
            {
                "symbol": symbol,
                "kline_path": str(kline_path.resolve()),
                "kline_sha256": v3_quality.history_plan.sha256_file(kline_path),
                "funding_path": str(funding_path.resolve()),
                "funding_sha256": v3_quality.history_plan.sha256_file(funding_path),
            }
        )

    train_manifest = {
        "schema": v3_quality.SPLIT_MANIFEST_SCHEMA,
        "generated_at_utc": "2026-07-17T07:30:00Z",
        "run_id": "membership-v3-quality-fixture",
        "stage": "train_view",
        "range": {"start_sec": start_sec, "end_sec": end_sec},
        "sealed": False,
        "oos_paths_present": False,
        "point_in_time_universe": True,
        "historical_universe": True,
        "lifecycle_mask_applied": True,
        "no_interpolation": True,
        "universe": universe,
        "normalized_files": files,
        "input_provenance": {
            "quality_plan_hash": "1" * 64,
            "history_plan_hash": "2" * 64,
            "collect_artifact_hash": "3" * 64,
        },
    }
    train_manifest["artifact_hash"] = v3_quality._normalized_manifest_hash(train_manifest)
    train_manifest_path = train_root / "manifest.json"
    train_manifest_path.write_text(json.dumps(train_manifest), encoding="utf-8")

    oos_sentinel = root / "oos-sealed" / "DO_NOT_OPEN.json"
    quality_report = {
        "schema": v3_quality.REPORT_SCHEMA,
        "generated_at_utc": "2026-07-17T07:31:00Z",
        "run_id": "membership-v3-quality-fixture",
        "plan_path": str((root / "quality-plan.json").resolve()),
        "plan_hash": "1" * 64,
        "history_plan_hash": "2" * 64,
        "collect_artifact_hash": "3" * 64,
        "normalized_manifest_path": str((root / "normalized" / "manifest.json").resolve()),
        "normalized_manifest_hash": "4" * 64,
        "train_manifest_path": str(train_manifest_path.resolve()),
        "train_manifest_hash": train_manifest["artifact_hash"],
        "oos_manifest_path": str(oos_sentinel.resolve()),
        "oos_commitment_hash": "5" * 64,
        "output_root": str((root / "normalized").resolve()),
        "final": True,
        "accepted": True,
        "decision": v3_quality.ACCEPTED_DECISION,
        "runtime_sec": 1.0,
        "cache_reused": False,
        "minimum_canonical_assets": 20,
        "minimum_series_coverage": 0.98,
        "minimum_delisted_end_coverage": 0.90,
        "planned_assets": 24,
        "accepted_assets": 24,
        "rejected_assets": 0,
        "planned_delisted_assets": 0,
        "resolved_delisted_assets": 0,
        "delisted_end_coverage": 1.0,
        "rejection_reasons": [],
        "per_asset": [],
        "parse_error_samples": [],
        "data_access_audit": {
            "archive_payload_read_for_normalization": True,
            "prices_read_for_normalization": True,
            "returns_computed": False,
            "pnl_read": False,
            "signals_read": False,
            "oos_evaluated": False,
        },
        "research_only": True,
        "public_data_only": True,
        "replay_allowed": False,
        "oos_allowed": False,
        "grid_allowed": False,
        "paper_forward_allowed": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "next_allowed_command": "create_hash_bound_gate_membership_momentum_v2_train_planonly",
        "limitations": [],
    }
    quality_report["artifact_hash"] = v3_quality._artifact_hash(quality_report)
    quality_path = root / "quality-report.json"
    quality_path.write_text(json.dumps(quality_report), encoding="utf-8")
    return quality_path, train_manifest_path, oos_sentinel


class GateMembershipMomentumV2TrainTests(unittest.TestCase):
    def test_plan_accepts_v3_quality_without_exposing_oos_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_manifest_path, oos_sentinel = _write_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))

            plan = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=None,
                run_id="membership-momentum-v2-train",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T07:32:00Z",
            )

            self.assertEqual(plan["decision"], PLAN_DECISION)
            self.assertEqual(plan["train_input"]["manifest_path"], str(train_manifest_path.resolve()))
            self.assertEqual(plan["oos_commitment_hash"], "5" * 64)
            self.assertFalse(_contains_oos_path(plan))
            self.assertFalse(oos_sentinel.exists())
            self.assertEqual(plan["strategy"]["lookback_days"], 30)
            self.assertEqual(plan["strategy"]["hold_days"], 7)
            self.assertEqual(plan["strategy"]["rebalance_every_days"], 7)
            self.assertEqual(plan["sample_capacity"]["theoretical_max_independent_rebalances"], 12)
            self.assertEqual(plan["train_gates"]["minimum_independent_rebalances"], 10)
            schedule = plan["rebalance_schedule_contract"]
            self.assertEqual(schedule["semantics"], "global_train_anchor_v1")
            self.assertEqual(schedule["anchor_day"], START_DAY + 30)
            self.assertEqual(schedule["cadence_days"], 7)
            self.assertEqual(len(schedule["eligible_signal_days"]), 12)
            self.assertEqual(schedule["boundary_excluded_signal_days"], [START_DAY + 114])
            self.assertEqual(schedule["next_scheduled_signal_day_at_or_after_view_end"], START_DAY + 121)
            self.assertTrue(
                all(
                    (signal_day - schedule["anchor_day"]) % schedule["cadence_days"] == 0
                    for signal_day in schedule["eligible_signal_days"]
                    + schedule["boundary_excluded_signal_days"]
                )
            )
            self.assertEqual(plan["plan_hash"], train_plan_hash(plan))

    def test_plan_is_deterministic_and_rejects_wrong_quality_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, _, _ = _write_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            first = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=None,
                run_id="membership-momentum-v2-train",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T07:32:00Z",
            )
            second = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=None,
                run_id="membership-momentum-v2-train",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T08:32:00Z",
            )
            self.assertEqual(first["plan_hash"], second["plan_hash"])

            quality["next_allowed_command"] = "something_else"
            quality["artifact_hash"] = v3_quality._artifact_hash(quality)
            quality_path.write_text(json.dumps(quality), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "next transition"):
                build_train_plan(
                    quality_report_path=quality_path,
                    expected_quality_hash=quality["artifact_hash"],
                    output_path=None,
                    run_id="wrong-transition",
                    max_runtime_sec=120,
                )

    def test_plan_rejects_future_lifecycle_end_in_train_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_manifest_path, _ = _write_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            manifest = json.loads(train_manifest_path.read_text(encoding="utf-8"))
            manifest["universe"][0]["listed_to_ts"] = manifest["range"]["end_sec"] + DAY_SEC
            manifest["universe"][0]["is_delisted"] = True
            manifest["artifact_hash"] = v3_quality._normalized_manifest_hash(manifest)
            train_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            quality["train_manifest_hash"] = manifest["artifact_hash"]
            quality["artifact_hash"] = v3_quality._artifact_hash(quality)
            quality_path.write_text(json.dumps(quality), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "future lifecycle"):
                build_train_plan(
                    quality_report_path=quality_path,
                    expected_quality_hash=quality["artifact_hash"],
                    output_path=None,
                    run_id="future-lifecycle",
                    max_runtime_sec=120,
                )

    def test_evaluator_is_deterministic_and_never_opens_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, _, oos_sentinel = _write_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            plan_path = root / "train-plan.json"
            plan = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-train",
                max_runtime_sec=120,
            )
            first = evaluate_train_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "first.json",
                max_runtime_sec=120,
            )
            second = evaluate_train_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "second.json",
                max_runtime_sec=120,
            )

            self.assertEqual(first["decision"], FEASIBLE_DECISION)
            self.assertEqual(first["normal_metrics"]["independent_rebalances"], 12)
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertFalse(first["data_access_audit"]["oos_paths_available"])
            self.assertFalse(first["data_access_audit"]["oos_files_opened"])
            self.assertFalse(_contains_oos_path(first))
            self.assertFalse(oos_sentinel.exists())

    def test_negative_train_economics_closes_without_retune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, _, _ = _write_fixture(root, trending=False)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            plan_path = root / "train-plan.json"
            plan = build_train_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-flat",
                max_runtime_sec=120,
            )
            result = evaluate_train_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "result.json",
                max_runtime_sec=120,
            )

            self.assertEqual(result["decision"], INFEASIBLE_DECISION)
            self.assertIn("price_only_net_expectancy_not_positive", result["rejection_reasons"])
            self.assertEqual(result["next_allowed_command"], "none_membership_momentum_v2_branch_closed_no_retune")


class GateMembershipMomentumV2PowerShellTests(unittest.TestCase):
    def test_run_mvp_wires_v2_train_plan_and_evaluator(self) -> None:
        script = (lambda p: (p.parent.parent / "tools" / "run_ws_pipeline.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_signals.ps1").read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "run_funding.ps1").read_text(encoding="utf-8-sig") + "\n" + p.read_text(encoding="utf-8-sig") + "\n" + (p.parent.parent / "tools" / "trading_gate_assertions.ps1").read_text(encoding="utf-8-sig"))((REPO_ROOT / "trading_mvp" / "run_mvp.ps1"))
        self.assertIn('"fast-edge-membership-momentum-v2-train-plan"', script)
        self.assertIn('"fast-edge-membership-momentum-v2-train"', script)
        self.assertIn("gate_membership_momentum_v2_train.py", script)


if __name__ == "__main__":
    unittest.main()
