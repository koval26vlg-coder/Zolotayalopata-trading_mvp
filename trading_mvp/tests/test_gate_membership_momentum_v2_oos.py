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
from gate_membership_momentum_v2_oos import (  # noqa: E402
    HISTORICAL_ACCEPT_DECISION,
    OOS_REJECTED_DECISION,
    PLAN_DECISION,
    build_oos_plan,
    evaluate_oos_plan,
    oos_plan_hash,
)
from gate_membership_momentum_v2_train import (  # noqa: E402
    FEASIBLE_DECISION,
    build_train_plan,
    evaluate_train_plan,
)


START_DAY = 20_000
TRAIN_VIEW_DAYS = 120
OOS_DAYS = 100


def _write_series(
    root: Path,
    *,
    symbol: str,
    start_day: int,
    days: int,
    initial_price: float,
    daily_return: float,
) -> tuple[Path, Path, float]:
    price = initial_price
    rows = []
    for offset in range(days):
        open_price = price
        price *= 1.0 + daily_return
        rows.append(
            {
                "ts": (start_day + offset) * DAY_SEC,
                "open": open_price,
                "high": max(open_price, price),
                "low": min(open_price, price),
                "close": price,
                "volume_base": 20_000.0,
                "volume_quote": 2_000_000.0,
                "observed_hours": 24,
            }
        )
    kline_path = root / "gateio" / "klines" / f"{symbol}.json"
    funding_path = root / "gateio" / "funding" / f"{symbol}.json"
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
    return kline_path, funding_path, price


def _split_manifest(
    *,
    root: Path,
    stage: str,
    start_sec: int,
    end_sec: int,
    universe: list[dict],
    files: list[dict],
) -> Path:
    manifest = {
        "schema": v3_quality.SPLIT_MANIFEST_SCHEMA,
        "generated_at_utc": "2026-07-17T08:00:00Z",
        "run_id": "membership-v3-oos-fixture",
        "stage": stage,
        "range": {"start_sec": start_sec, "end_sec": end_sec},
        "sealed": stage == "sealed_oos",
        "oos_paths_present": stage == "sealed_oos",
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
    manifest["artifact_hash"] = v3_quality._normalized_manifest_hash(manifest)
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_fixture(root: Path, *, oos_trending: bool = True) -> tuple[Path, Path, Path]:
    train_root = root / "normalized" / "train"
    oos_root = root / "normalized" / "sealed-oos"
    train_start_sec = START_DAY * DAY_SEC
    train_end_sec = (START_DAY + TRAIN_VIEW_DAYS) * DAY_SEC
    oos_end_sec = (START_DAY + TRAIN_VIEW_DAYS + OOS_DAYS) * DAY_SEC
    train_universe: list[dict] = []
    oos_universe: list[dict] = []
    train_files: list[dict] = []
    oos_files: list[dict] = []
    for index in range(24):
        base = f"A{index:02d}"
        symbol = f"{base}_USDT"
        train_return = 0.01 if index >= 12 else -0.01
        oos_return = train_return if oos_trending else 0.0
        train_kline, train_funding, ending_price = _write_series(
            train_root,
            symbol=symbol,
            start_day=START_DAY,
            days=TRAIN_VIEW_DAYS,
            initial_price=100.0,
            daily_return=train_return,
        )
        oos_kline, oos_funding, _ = _write_series(
            oos_root,
            symbol=symbol,
            start_day=START_DAY + TRAIN_VIEW_DAYS,
            days=OOS_DAYS,
            initial_price=ending_price,
            daily_return=oos_return,
        )
        identity = {
            "exchange": "gateio",
            "symbol": symbol,
            "base": base,
            "quote": "USDT",
            "canonical_asset_id": f"coingecko:asset-{index}",
            "coin_id": f"asset-{index}",
            "non_binance_baseline": True,
            "non_binance_evidence": "fixture:binance-spot-absent",
            "listed_from_ts": train_start_sec - 30 * DAY_SEC,
            "listed_to_ts": None,
            "status": "active",
            "is_delisted": False,
            "survivorship_status": "trading_at_train_boundary",
            "lifecycle_end_resolution": "not_observed_by_train_boundary",
            "resolved_lifecycle_end_sec": None,
        }
        train_universe.append(dict(identity))
        oos_universe.append(dict(identity))
        train_files.append(
            {
                "symbol": symbol,
                "kline_path": str(train_kline.resolve()),
                "kline_sha256": v3_quality.history_plan.sha256_file(train_kline),
                "funding_path": str(train_funding.resolve()),
                "funding_sha256": v3_quality.history_plan.sha256_file(train_funding),
            }
        )
        oos_files.append(
            {
                "symbol": symbol,
                "kline_path": str(oos_kline.resolve()),
                "kline_sha256": v3_quality.history_plan.sha256_file(oos_kline),
                "funding_path": str(oos_funding.resolve()),
                "funding_sha256": v3_quality.history_plan.sha256_file(oos_funding),
            }
        )

    train_manifest_path = _split_manifest(
        root=train_root,
        stage="train_view",
        start_sec=train_start_sec,
        end_sec=train_end_sec,
        universe=train_universe,
        files=train_files,
    )
    oos_manifest_path = _split_manifest(
        root=oos_root,
        stage="sealed_oos",
        start_sec=train_end_sec,
        end_sec=oos_end_sec,
        universe=oos_universe,
        files=oos_files,
    )
    train_manifest = json.loads(train_manifest_path.read_text(encoding="utf-8"))
    oos_manifest = json.loads(oos_manifest_path.read_text(encoding="utf-8"))
    quality = {
        "schema": v3_quality.REPORT_SCHEMA,
        "generated_at_utc": "2026-07-17T08:01:00Z",
        "run_id": "membership-v3-oos-fixture",
        "plan_path": str((root / "quality-plan.json").resolve()),
        "plan_hash": "1" * 64,
        "history_plan_hash": "2" * 64,
        "collect_artifact_hash": "3" * 64,
        "normalized_manifest_path": str((root / "normalized" / "manifest.json").resolve()),
        "normalized_manifest_hash": "4" * 64,
        "train_manifest_path": str(train_manifest_path.resolve()),
        "train_manifest_hash": train_manifest["artifact_hash"],
        "oos_manifest_path": str(oos_manifest_path.resolve()),
        "oos_commitment_hash": oos_manifest["artifact_hash"],
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
    quality["artifact_hash"] = v3_quality._artifact_hash(quality)
    quality_path = root / "quality-report.json"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")
    return quality_path, train_manifest_path, oos_manifest_path


def _authorized_inputs(root: Path, *, oos_trending: bool = True) -> tuple[Path, dict, Path, dict]:
    quality_path, _, _ = _write_fixture(root, oos_trending=oos_trending)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    train_plan_path = root / "train-plan.json"
    train_plan = build_train_plan(
        quality_report_path=quality_path,
        expected_quality_hash=quality["artifact_hash"],
        output_path=train_plan_path,
        run_id="membership-momentum-v2",
        max_runtime_sec=120,
    )
    train_result_path = root / "train-result.json"
    train_result = evaluate_train_plan(
        plan_path=train_plan_path,
        expected_plan_hash=train_plan["plan_hash"],
        output_path=train_result_path,
        max_runtime_sec=120,
    )
    if train_result["decision"] != FEASIBLE_DECISION:
        raise AssertionError("fixture train stage must be feasible")
    return quality_path, train_plan, train_result_path, train_result


class GateMembershipMomentumV2OosTests(unittest.TestCase):
    def test_plan_is_hash_bound_to_feasible_train_and_five_folds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_plan, train_result_path, train_result = _authorized_inputs(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            plan = build_oos_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                train_plan_path=root / "train-plan.json",
                expected_train_plan_hash=train_plan["plan_hash"],
                train_result_path=train_result_path,
                expected_train_result_hash=train_result["deterministic_result_hash"],
                output_path=None,
                run_id="membership-momentum-v2-oos",
                max_runtime_sec=120,
                generated_at_utc="2026-07-17T08:02:00Z",
            )

            self.assertEqual(plan["decision"], PLAN_DECISION)
            self.assertTrue(plan["oos_allowed_now"])
            self.assertEqual([fold["days"] for fold in plan["fold_contract"]], [20] * 5)
            self.assertEqual(plan["sample_capacity"]["theoretical_max_independent_rebalances"], 9)
            self.assertEqual(plan["oos_gates"]["minimum_independent_rebalances"], 8)
            self.assertEqual(plan["strategy"]["lookback_days"], 30)
            self.assertEqual(plan["strategy"]["hold_days"], 7)
            schedule = plan["rebalance_schedule_contract"]
            self.assertEqual(schedule["semantics"], "global_train_anchor_v1")
            self.assertEqual(schedule["anchor_day"], START_DAY + 30)
            self.assertEqual(schedule["cadence_days"], 7)
            eligible = [
                signal_day
                for fold in plan["fold_contract"]
                for signal_day in fold["eligible_signal_days"]
            ]
            excluded = [
                signal_day
                for fold in plan["fold_contract"]
                for signal_day in fold["boundary_excluded_signal_days"]
            ]
            self.assertEqual(
                eligible,
                [START_DAY + offset for offset in (121, 128, 142, 149, 163, 170, 184, 191, 205)],
            )
            self.assertEqual(
                excluded,
                [START_DAY + offset for offset in (135, 156, 177, 198, 212, 219)],
            )
            self.assertTrue(
                all(
                    (signal_day - schedule["anchor_day"]) % schedule["cadence_days"] == 0
                    for signal_day in eligible + excluded
                )
            )
            self.assertEqual(schedule["next_scheduled_signal_day_at_or_after_oos_end"], START_DAY + 226)
            self.assertEqual(plan["plan_hash"], oos_plan_hash(plan))

    def test_evaluator_is_deterministic_and_maxes_out_at_execution_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_plan, train_result_path, train_result = _authorized_inputs(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            plan_path = root / "oos-plan.json"
            plan = build_oos_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                train_plan_path=root / "train-plan.json",
                expected_train_plan_hash=train_plan["plan_hash"],
                train_result_path=train_result_path,
                expected_train_result_hash=train_result["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-oos",
                max_runtime_sec=120,
            )
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
            self.assertEqual(first["normal_metrics"]["independent_rebalances"], 9)
            self.assertEqual(first["positive_folds"], 5)
            self.assertTrue(
                all(
                    (event["signal_day"] - plan["rebalance_schedule_contract"]["anchor_day"])
                    % plan["rebalance_schedule_contract"]["cadence_days"]
                    == 0
                    for event in first["events"]
                )
            )
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
            self.assertEqual(first["capacity_status"], "REQUIRES_EXECUTION_PROBE")
            self.assertEqual(
                first["next_allowed_command"],
                "create_hash_bound_gate_membership_momentum_v2_execution_probe_planonly",
            )
            self.assertFalse(first["paper_forward_allowed"])

    def test_flat_oos_closes_branch_without_retune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_plan, train_result_path, train_result = _authorized_inputs(
                root,
                oos_trending=False,
            )
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            plan_path = root / "oos-plan.json"
            plan = build_oos_plan(
                quality_report_path=quality_path,
                expected_quality_hash=quality["artifact_hash"],
                train_plan_path=root / "train-plan.json",
                expected_train_plan_hash=train_plan["plan_hash"],
                train_result_path=train_result_path,
                expected_train_result_hash=train_result["deterministic_result_hash"],
                output_path=plan_path,
                run_id="membership-momentum-v2-flat-oos",
                max_runtime_sec=120,
            )
            result = evaluate_oos_plan(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "oos-result.json",
                max_runtime_sec=120,
            )

            self.assertEqual(result["decision"], OOS_REJECTED_DECISION)
            self.assertIn("price_only_net_expectancy_not_positive", result["rejection_reasons"])
            self.assertEqual(
                result["next_allowed_command"],
                "none_membership_momentum_v2_branch_closed_no_retune",
            )
            self.assertFalse(result["retune_allowed"])

    def test_tampered_train_result_is_rejected_before_oos_manifest_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_plan, train_result_path, train_result = _authorized_inputs(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            oos_manifest_path = Path(quality["oos_manifest_path"])
            oos_manifest_path.unlink()
            train_result["decision"] = "tampered"
            train_result_path.write_text(json.dumps(train_result), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "train result"):
                build_oos_plan(
                    quality_report_path=quality_path,
                    expected_quality_hash=quality["artifact_hash"],
                    train_plan_path=root / "train-plan.json",
                    expected_train_plan_hash=train_plan["plan_hash"],
                    train_result_path=train_result_path,
                    expected_train_result_hash=train_result["deterministic_result_hash"],
                    output_path=None,
                    run_id="tampered-train",
                    max_runtime_sec=120,
                )

    def test_runtime_cap_is_thirty_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality_path, train_plan, train_result_path, train_result = _authorized_inputs(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "max_runtime_sec"):
                build_oos_plan(
                    quality_report_path=quality_path,
                    expected_quality_hash=quality["artifact_hash"],
                    train_plan_path=root / "train-plan.json",
                    expected_train_plan_hash=train_plan["plan_hash"],
                    train_result_path=train_result_path,
                    expected_train_result_hash=train_result["deterministic_result_hash"],
                    output_path=None,
                    run_id="too-long",
                    max_runtime_sec=1801,
                )


class GateMembershipMomentumV2OosPowerShellTests(unittest.TestCase):
    def test_run_mvp_wires_v2_oos_plan_and_evaluator(self) -> None:
        script = (REPO_ROOT / "trading_mvp" / "run_mvp.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('"fast-edge-membership-momentum-v2-oos-plan"', script)
        self.assertIn('"fast-edge-membership-momentum-v2-oos"', script)
        self.assertIn("gate_membership_momentum_v2_oos.py", script)


if __name__ == "__main__":
    unittest.main()
