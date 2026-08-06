from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_edge import build_historical_basis_plan, sha256_json  # noqa: E402
from historical_basis_evaluator import run_hash_bound_evaluation  # noqa: E402


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _asset(index: int) -> dict[str, object]:
    base = f"A{index}"
    return {
        "canonical_asset_id": f"asset:{base.lower()}",
        "base": base,
        "quote": "USDT",
        "mexc_symbol": f"{base}_USDT",
        "gateio_symbol": f"{base}_USDT",
        "mexc_status": "trading",
        "gateio_status": "trading",
        "common_history_days": 400,
        "binance_spot": False,
        "categories": [],
        "liquidity_rank": index,
    }


def _quality(root: Path, plan: dict[str, object], *, tamper_train_hash: bool = False):
    train = root / "normalized.train.jsonl"
    oos = root / "normalized.oos.jsonl"
    train.write_text("", encoding="utf-8")
    oos.write_text("", encoding="utf-8")
    quality = {
        "schema": "trading_mvp_historical_basis_quality_v1",
        "verdict": "QUALITY_ACCEPTED_NOT_EVALUATED",
        "plan_hash": plan["plan_hash"],
        "input_merkle_sha256": "fixture-merkle",
        "train_output": str(train),
        "train_output_sha256": "bad" if tamper_train_hash else _sha_text(""),
        "train_rows": 0,
        "oos_output": str(oos),
        "oos_output_sha256": _sha_text(""),
        "oos_rows": 0,
        "surviving_asset_count": 8,
        "primary_assets": [f"A{i}" for i in range(8)],
        "reserve_assets": [],
    }
    quality["deterministic_result_hash"] = sha256_json(quality)
    path = root / "quality.json"
    path.write_text(json.dumps(quality), encoding="utf-8")
    return quality, path, train, oos


class HistoricalBasisOwnedEvaluatorTests(unittest.TestCase):
    def test_train_stage_does_not_open_oos_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = build_historical_basis_plan(
                [_asset(index) for index in range(8)],
                plan_path,
                frozen_at_utc="2026-07-15T00:00:00+00:00",
            )
            _, quality_path, _, oos = _quality(root, plan)
            oos.unlink()
            result = run_hash_bound_evaluation(
                plan_path=plan_path,
                quality_report_path=quality_path,
                output_path=root / "train-result.json",
                stage="train_feasibility",
                expected_plan_hash=plan["plan_hash"],
                max_runtime_sec=60,
            )
            self.assertEqual(result["verdict"], "INSUFFICIENT_DATA")
            self.assertFalse(result["data_access_audit"]["oos_file_opened"])
            self.assertFalse(result["oos_read"])
            self.assertIn("code_provenance", result)
            self.assertIn("code_snapshot_hash", result["code_provenance"])

    def test_full_evaluation_requires_feasible_hash_bound_train_result_before_oos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = build_historical_basis_plan(
                [_asset(index) for index in range(8)],
                plan_path,
                frozen_at_utc="2026-07-15T00:00:00+00:00",
            )
            _, quality_path, _, oos = _quality(root, plan)
            quality_sha = hashlib.sha256(quality_path.read_bytes()).hexdigest()
            feasibility = {
                "schema": "trading_mvp_historical_basis_owned_evaluation_v1",
                "stage": "train_feasibility",
                "plan_hash": plan["plan_hash"],
                "quality_report_sha256": quality_sha,
                "verdict": "INSUFFICIENT_DATA",
            }
            feasibility["deterministic_result_hash"] = sha256_json(feasibility)
            feasibility_path = root / "feasibility.json"
            feasibility_path.write_text(json.dumps(feasibility), encoding="utf-8")
            oos.unlink()
            with self.assertRaisesRegex(ValueError, "not FEASIBLE_FOR_OOS"):
                run_hash_bound_evaluation(
                    plan_path=plan_path,
                    quality_report_path=quality_path,
                    output_path=root / "oos-result.json",
                    stage="full_evaluation",
                    feasibility_path=feasibility_path,
                    expected_plan_hash=plan["plan_hash"],
                    max_runtime_sec=60,
                )

    def test_tampered_train_shard_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan = build_historical_basis_plan(
                [_asset(index) for index in range(8)],
                plan_path,
                frozen_at_utc="2026-07-15T00:00:00+00:00",
            )
            _, quality_path, _, _ = _quality(root, plan, tamper_train_hash=True)
            with self.assertRaisesRegex(ValueError, "train shard hash"):
                run_hash_bound_evaluation(
                    plan_path=plan_path,
                    quality_report_path=quality_path,
                    output_path=root / "train-result.json",
                    stage="train_feasibility",
                    expected_plan_hash=plan["plan_hash"],
                    max_runtime_sec=60,
                )


if __name__ == "__main__":
    unittest.main()
