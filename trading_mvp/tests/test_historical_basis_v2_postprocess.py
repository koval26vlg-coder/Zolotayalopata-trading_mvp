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

from historical_basis_v2 import DAY_SEC, build_historical_basis_v2_plan  # noqa: E402
from historical_basis_v2_collector import SCHEMA as COLLECTOR_SCHEMA  # noqa: E402
from historical_basis_v2_postprocess import (  # noqa: E402
    build_train_postprocess_preview,
    run_train_postprocess,
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


def _fixture(root: Path) -> tuple[dict[str, object], Path, Path]:
    plan_path = root / "plan.json"
    plan = build_historical_basis_v2_plan(
        [_asset(index) for index in range(8)],
        output_path=plan_path,
        window_end_ts=179 * DAY_SEC,
        frozen_at_utc="2026-07-16T00:00:00+00:00",
    )
    manifest_path = root / "collector-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": COLLECTOR_SCHEMA,
                "run_id": "basis-v2-fixture",
                "status": "READY_FOR_POSTPROCESS",
                "final": True,
                "plan_hash": plan["plan_hash"],
                "expected_plan_hash": plan["plan_hash"],
                "expected_items": 144,
                "completed_items": 144,
                "error_count": 0,
            }
        ),
        encoding="utf-8",
    )
    return plan, plan_path, manifest_path


class HistoricalBasisV2TrainPostprocessTests(unittest.TestCase):
    def test_preview_is_hash_bound_and_does_not_read_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, manifest_path = _fixture(root)

            preview = build_train_postprocess_preview(
                plan_path=plan_path,
                expected_plan_hash=str(plan["plan_hash"]),
                collector_manifest_path=manifest_path,
                output_root=root / "postprocess",
                max_runtime_sec=1_800,
            )

            self.assertEqual(preview["decision"], "READY_FOR_VISIBLE_TRAIN_POSTPROCESS")
            self.assertEqual(preview["plan_hash"], plan["plan_hash"])
            self.assertEqual(preview["stages"], ["quality", "train_feasibility_repeat_1", "train_feasibility_repeat_2"])
            self.assertFalse(preview["network_access"])
            self.assertFalse(preview["oos_read"])
            self.assertFalse(preview["full_evaluation"])

    def test_preview_rejects_nonfinal_collector_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, manifest_path = _fixture(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["final"] = False
            manifest["status"] = "STOPPED_INCOMPLETE"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "collector manifest is not final"):
                build_train_postprocess_preview(
                    plan_path=plan_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    collector_manifest_path=manifest_path,
                    output_root=root / "postprocess",
                    max_runtime_sec=1_800,
                )

    def test_pipeline_runs_quality_and_two_matching_train_repeats_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, manifest_path = _fixture(root)

            def fake_quality(*_args: object, **kwargs: object) -> dict[str, object]:
                report_path = Path(str(kwargs["report_output"]))
                payload = {
                    "verdict": "QUALITY_ACCEPTED_NOT_EVALUATED",
                    "report_payload_sha256": "q" * 64,
                }
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(payload), encoding="utf-8")
                for key in ("candles_output", "funding_output"):
                    Path(str(kwargs[key])).write_text("", encoding="utf-8")
                candles = Path(str(kwargs["candles_output"]))
                candles.with_name(f"{candles.stem}.train{candles.suffix}").write_text("", encoding="utf-8")
                candles.with_name(f"{candles.stem}.oos{candles.suffix}").write_text("", encoding="utf-8")
                return payload

            def fake_evaluate(*_args: object, **kwargs: object) -> dict[str, object]:
                self.assertEqual(kwargs["stage"], "train_feasibility")
                self.assertIsNone(kwargs.get("feasibility_path"))
                payload = {
                    "stage": "train_feasibility",
                    "verdict": "FEASIBLE_FOR_OOS",
                    "deterministic_result_hash": "d" * 64,
                    "oos_read": False,
                    "data_access_audit": {
                        "oos_files_opened": False,
                        "oos_rows_read": 0,
                        "network_access": False,
                    },
                }
                output = Path(str(kwargs["output_path"]))
                output.write_text(json.dumps(payload), encoding="utf-8")
                return payload

            with (
                patch("historical_basis_v2_postprocess.run_historical_basis_v2_quality", side_effect=fake_quality),
                patch("historical_basis_v2_postprocess.run_hash_bound_evaluation", side_effect=fake_evaluate) as evaluator,
            ):
                result = run_train_postprocess(
                    plan_path=plan_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    collector_manifest_path=manifest_path,
                    output_root=root / "postprocess",
                    max_runtime_sec=1_800,
                )

            self.assertEqual(evaluator.call_count, 2)
            self.assertEqual(result["status"], "READY_FOR_OOS_EVALUATION_NOT_RUN")
            self.assertEqual(result["verdict"], "FEASIBLE_FOR_OOS")
            self.assertFalse(result["oos_read"])
            self.assertFalse(result["full_evaluation"])
            self.assertTrue(Path(result["manifest_path"]).is_file())

    def test_mismatched_repeat_hashes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, plan_path, manifest_path = _fixture(root)

            def fake_quality(*_args: object, **kwargs: object) -> dict[str, object]:
                report = Path(str(kwargs["report_output"]))
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps({"verdict": "QUALITY_ACCEPTED_NOT_EVALUATED"}), encoding="utf-8")
                for key in ("candles_output", "funding_output"):
                    Path(str(kwargs[key])).write_text("", encoding="utf-8")
                candles = Path(str(kwargs["candles_output"]))
                candles.with_name(f"{candles.stem}.train{candles.suffix}").write_text("", encoding="utf-8")
                candles.with_name(f"{candles.stem}.oos{candles.suffix}").write_text("", encoding="utf-8")
                return {"verdict": "QUALITY_ACCEPTED_NOT_EVALUATED"}

            hashes = iter(("a" * 64, "b" * 64))

            def fake_evaluate(*_args: object, **kwargs: object) -> dict[str, object]:
                payload = {
                    "stage": "train_feasibility",
                    "verdict": "FEASIBLE_FOR_OOS",
                    "deterministic_result_hash": next(hashes),
                    "oos_read": False,
                    "data_access_audit": {"oos_files_opened": False, "oos_rows_read": 0},
                }
                Path(str(kwargs["output_path"])).write_text(json.dumps(payload), encoding="utf-8")
                return payload

            with (
                patch("historical_basis_v2_postprocess.run_historical_basis_v2_quality", side_effect=fake_quality),
                patch("historical_basis_v2_postprocess.run_hash_bound_evaluation", side_effect=fake_evaluate),
            ):
                with self.assertRaisesRegex(ValueError, "deterministic train repeat mismatch"):
                    run_train_postprocess(
                        plan_path=plan_path,
                        expected_plan_hash=str(plan["plan_hash"]),
                        collector_manifest_path=manifest_path,
                        output_root=root / "postprocess",
                        max_runtime_sec=1_800,
                    )

            failure = root / "postprocess" / "basis-v2-fixture" / "postprocess-failure.json"
            self.assertTrue(failure.is_file())
            self.assertEqual(json.loads(failure.read_text(encoding="utf-8"))["status"], "STOPPED_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
