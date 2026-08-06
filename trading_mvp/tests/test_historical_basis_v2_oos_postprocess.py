from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2 import (  # noqa: E402
    DAY_SEC,
    build_historical_basis_v2_plan,
    sha256_file,
    sha256_json,
)
from historical_basis_v2_evaluator import (  # noqa: E402
    SCHEMA as EVALUATION_SCHEMA,
    _artifact_hash,
)
from historical_basis_v2_postprocess import SCHEMA as TRAIN_POSTPROCESS_SCHEMA  # noqa: E402
from historical_basis_v2_oos_postprocess import (  # noqa: E402
    build_oos_postprocess_preview,
    run_oos_postprocess,
)


def _asset(index: int) -> dict[str, object]:
    base = f"A{index:02d}"
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": 179,
        "binance_spot": False,
        "categories": [],
        "availability_rank": index,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _fixture(root: Path) -> tuple[dict[str, object], Path, Path]:
    plan_path = root / "plan.json"
    plan = build_historical_basis_v2_plan(
        [_asset(index) for index in range(8)],
        output_path=plan_path,
        window_end_ts=179 * DAY_SEC,
        frozen_at_utc="2026-07-16T00:00:00+00:00",
    )
    quality_path = root / "train-postprocess" / "quality-report.json"
    _write_json(quality_path, {"schema": "fixture-quality", "verdict": "QUALITY_ACCEPTED_NOT_EVALUATED"})

    feasibility_paths = [
        root / "train-postprocess" / "train-feasibility-repeat-1.json",
        root / "train-postprocess" / "train-feasibility-repeat-2.json",
    ]
    feasibility = {
        "schema": EVALUATION_SCHEMA,
        "stage": "train_feasibility",
        "verdict": "FEASIBLE_FOR_OOS",
        "plan_hash": plan["plan_hash"],
        "quality_report_sha256": sha256_file(quality_path),
        "quality_semantic_hash": "q" * 64,
        "train_input_hashes": {"fixture": True},
        "oos_seal": {"sealed": True, "fixture": "oos"},
        "code_provenance": {"fixture": True},
        "oos_read": False,
        "data_access_audit": {
            "oos_files_opened": False,
            "oos_rows_read": 0,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
    }
    feasibility["deterministic_result_hash"] = _artifact_hash(feasibility)
    for path in feasibility_paths:
        _write_json(path, feasibility)

    manifest_path = root / "train-postprocess" / "postprocess-manifest.json"
    manifest: dict[str, object] = {
        "schema": TRAIN_POSTPROCESS_SCHEMA,
        "status": "READY_FOR_OOS_EVALUATION_NOT_RUN",
        "final": True,
        "generated_at_utc": "2026-07-16T00:00:00+00:00",
        "plan_path": str(plan_path.resolve()),
        "plan_file_sha256": sha256_file(plan_path),
        "plan_hash": plan["plan_hash"],
        "collector_manifest_path": str((root / "collector-manifest.json").resolve()),
        "collector_manifest_sha256": "c" * 64,
        "collector_run_id": "basis-v2-fixture",
        "quality_report_path": str(quality_path.resolve()),
        "quality_report_sha256": sha256_file(quality_path),
        "quality_verdict": "QUALITY_ACCEPTED_NOT_EVALUATED",
        "feasibility_repeat_paths": [str(path.resolve()) for path in feasibility_paths],
        "feasibility_repeat_file_sha256": [sha256_file(path) for path in feasibility_paths],
        "feasibility_deterministic_result_hash": feasibility["deterministic_result_hash"],
        "verdict": "FEASIBLE_FOR_OOS",
        "rejection_reasons": [],
        "oos_seal": feasibility["oos_seal"],
        "oos_read": False,
        "full_evaluation": False,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "live_orders": False,
        "private_api_keys": False,
        "leverage_or_margin": False,
        "runtime_sec": 1.0,
        "max_runtime_sec": 1800,
        "next_allowed_command": "visible-hash-bound-full-evaluation-no-grid",
    }
    manifest["deterministic_result_hash"] = sha256_json(
        {key: value for key, value in manifest.items() if key not in {"generated_at_utc", "runtime_sec"}}
    )
    _write_json(manifest_path, manifest)
    return plan, plan_path, manifest_path


def _full_result(plan_hash: str, *, marker: str = "same") -> dict[str, object]:
    trades = [
        {"episode_id": f"episode-{index}", "base": f"A{index % 8:02d}"}
        for index in range(40)
    ]
    payload: dict[str, object] = {
        "schema": EVALUATION_SCHEMA,
        "stage": "full_evaluation",
        "verdict": "ACCEPT_FOR_EXECUTION_PROBE",
        "plan_hash": plan_hash,
        "rejection_reasons": [],
        "metrics": {
            "marker": marker,
            "independent_episode_count": 40,
            "unique_dates": 20,
            "base_count": 8,
            "price_only_expectancy_quote": 1.0,
            "total_expectancy_quote": 1.0,
            "profit_factor": 1.4,
            "positive_fixed_subperiods": 4,
            "normal_net_pnl_quote": 40.0,
            "stress_net_pnl_quote": 5.0,
            "stress_expectancy_quote": 0.125,
            "cluster_bootstrap_lower_95_quote": 0.01,
            "max_concentration_share": 0.20,
            "max_drawdown_fraction": 0.05,
            "direction_net_pnl_quote": {"mexc_long": 1.0, "gateio_long": 1.0},
        },
        "normal_trades": trades,
        "stress_trades": trades,
        "four_hour_robustness": {"passed": True, "rejection_reasons": []},
        "oos_read": True,
        "oos_input_hashes": {"candles_sha256": "b" * 64},
        "feasibility_provenance": {"deterministic_result_hash": "c" * 64},
        "code_provenance": {"code_snapshot_hash": "d" * 64},
        "data_access_audit": {
            "oos_files_opened": True,
            "oos_rows_read": 100,
            "oos_returns_read": True,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
    }
    payload["deterministic_result_hash"] = _artifact_hash(payload)
    return payload


class HistoricalBasisV2OosPostprocessTests(unittest.TestCase):
    def test_preview_is_bound_to_two_matching_train_repeats_without_oos_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)

            preview = build_oos_postprocess_preview(
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                train_postprocess_manifest_path=train_manifest,
                output_root=root / "oos-postprocess",
                max_runtime_sec=1800,
            )

            self.assertEqual(preview["decision"], "READY_FOR_VISIBLE_OOS_POSTPROCESS")
            self.assertEqual(preview["plan_hash"], plan["plan_hash"])
            self.assertEqual(preview["stages"], ["full_evaluation_repeat_1", "full_evaluation_repeat_2", "terminal_report"])
            self.assertFalse(preview["oos_read"])
            self.assertFalse(preview["network_access"])
            self.assertFalse((root / "oos-postprocess").exists())

    def test_preview_rejects_nonfinal_or_infeasible_train_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)
            manifest = json.loads(train_manifest.read_text(encoding="utf-8"))
            manifest["status"] = "BRANCH_CLOSED_TRAIN_INFEASIBLE"
            manifest["verdict"] = "INFEASIBLE_ON_CURRENT_DATA"
            _write_json(train_manifest, manifest)

            with self.assertRaisesRegex(ValueError, "not READY_FOR_OOS_EVALUATION_NOT_RUN"):
                build_oos_postprocess_preview(
                    plan_path=plan_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    train_postprocess_manifest_path=train_manifest,
                    output_root=root / "oos-postprocess",
                )

    def test_preview_rejects_tampered_train_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)
            manifest = json.loads(train_manifest.read_text(encoding="utf-8"))
            first = Path(manifest["feasibility_repeat_paths"][0])
            first.write_text('{"tampered":true}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "feasibility repeat file hash mismatch"):
                build_oos_postprocess_preview(
                    plan_path=plan_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    train_postprocess_manifest_path=train_manifest,
                    output_root=root / "oos-postprocess",
                )

    def test_pipeline_runs_two_matching_full_evaluations_and_terminal_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)
            manifest = json.loads(train_manifest.read_text(encoding="utf-8"))
            selected_feasibility = manifest["feasibility_repeat_paths"][0]

            def fake_evaluate(*_args: object, **kwargs: object) -> dict[str, object]:
                self.assertEqual(kwargs["stage"], "full_evaluation")
                self.assertEqual(str(kwargs["feasibility_path"]), selected_feasibility)
                payload = _full_result(str(plan["plan_hash"]))
                _write_json(Path(str(kwargs["output_path"])), payload)
                return payload

            with patch(
                "historical_basis_v2_oos_postprocess.run_hash_bound_evaluation",
                side_effect=fake_evaluate,
            ) as evaluator:
                result = run_oos_postprocess(
                    plan_path=plan_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    train_postprocess_manifest_path=train_manifest,
                    output_root=root / "oos-postprocess",
                    max_runtime_sec=1800,
                )

            self.assertEqual(evaluator.call_count, 2)
            self.assertEqual(result["status"], "HISTORICAL_ACCEPT_FOR_EXECUTION_PROBE")
            self.assertEqual(result["verdict"], "ACCEPT_FOR_EXECUTION_PROBE")
            self.assertTrue(result["oos_read"])
            self.assertTrue(Path(result["terminal_report_path"]).is_file())
            self.assertTrue(Path(result["manifest_path"]).is_file())
            self.assertEqual(result["next_allowed_command"], "create-separate-visible-execution-probe-planonly")

    def test_mismatched_oos_repeats_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, train_manifest = _fixture(root)
            markers = iter(("first", "second"))

            def fake_evaluate(*_args: object, **kwargs: object) -> dict[str, object]:
                payload = _full_result(str(plan["plan_hash"]), marker=next(markers))
                _write_json(Path(str(kwargs["output_path"])), payload)
                return payload

            with patch(
                "historical_basis_v2_oos_postprocess.run_hash_bound_evaluation",
                side_effect=fake_evaluate,
            ):
                with self.assertRaisesRegex(ValueError, "deterministic OOS repeat mismatch"):
                    run_oos_postprocess(
                        plan_path=plan_path,
                        expected_plan_hash=str(plan["plan_hash"]),
                        train_postprocess_manifest_path=train_manifest,
                        output_root=root / "oos-postprocess",
                        max_runtime_sec=1800,
                    )

            failure = root / "oos-postprocess" / "basis-v2-fixture" / "oos-postprocess-failure.json"
            payload = json.loads(failure.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "STOPPED_INCOMPLETE")
            self.assertFalse(payload["final"])
            self.assertTrue(payload["oos_read"])


if __name__ == "__main__":
    unittest.main()
