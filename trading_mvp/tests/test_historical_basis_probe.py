from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_edge import build_historical_basis_plan, sha256_file, sha256_json  # noqa: E402
from historical_basis_probe import (  # noqa: E402
    build_basis_probe_plan,
    build_basis_sprint_report,
    depth_execution_metrics,
)


def _semantic(payload: dict[str, object]) -> str:
    return sha256_json(
        {
            key: value
            for key, value in payload.items()
            if key not in {"deterministic_result_hash", "generated_at_utc", "runtime_sec"}
        }
    )


def _artifact(path: Path, payload: dict[str, object]) -> dict[str, object]:
    payload["deterministic_result_hash"] = _semantic(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


class HistoricalBasisProbeMathTests(unittest.TestCase):
    def test_depth_metrics_require_full_500_quote_and_measure_impact(self) -> None:
        book = [[100.0, 3.0], [100.05, 3.0], [100.2, 10.0]]
        metrics = depth_execution_metrics(book, side="buy", notional_quote=500.0, max_impact_bps=10.0)
        self.assertTrue(metrics["filled"])
        self.assertGreater(metrics["capacity_quote_at_max_impact"], 500.0)
        self.assertLessEqual(metrics["impact_bps"], 10.0)
        thin = depth_execution_metrics([[100.0, 1.0]], side="buy", notional_quote=500.0, max_impact_bps=10.0)
        self.assertFalse(thin["filled"])


class HistoricalBasisProbeChainTests(unittest.TestCase):
    def _evaluation_fixture(self, root: Path, verdict: str = "ACCEPT_FOR_EXECUTION_PROBE"):
        root.mkdir(parents=True, exist_ok=True)
        plan_path = root / "plan.json"
        plan = build_historical_basis_plan(
            [
                {
                    "canonical_asset_id": f"asset:a{index}",
                    "base": "AAA" if index == 0 else f"A{index}",
                    "quote": "USDT",
                    "mexc_symbol": "AAA_USDT" if index == 0 else f"A{index}_USDT",
                    "gateio_symbol": "AAA_USDT" if index == 0 else f"A{index}_USDT",
                    "mexc_status": "trading",
                    "gateio_status": "trading",
                    "common_history_days": 400,
                    "binance_spot": False,
                    "categories": [],
                    "liquidity_rank": index,
                }
                for index in range(8)
            ],
            plan_path,
            frozen_at_utc="2026-07-15T00:00:00+00:00",
        )
        quality = {"primary_assets": ["AAA"]}
        quality_path = root / "quality.json"
        quality_path.write_text(json.dumps(quality), encoding="utf-8")
        evaluation = {
            "schema": "trading_mvp_historical_basis_owned_evaluation_v1",
            "stage": "full_evaluation",
            "verdict": verdict,
            "plan_hash": plan["plan_hash"],
            "plan_path": str(plan_path),
            "plan_file_sha256": sha256_file(plan_path),
            "quality_report_path": str(quality_path),
            "normal_trades": [{"base": "AAA"}],
        }
        evaluation_path = root / "evaluation.json"
        _artifact(evaluation_path, evaluation)
        return plan, evaluation, evaluation_path

    def test_probe_plan_requires_historical_accept_and_freezes_three_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, evaluation_path = self._evaluation_fixture(root)
            output = root / "probe-plan.json"
            plan = build_basis_probe_plan(
                evaluation_path,
                output,
                first_window_start_utc="2026-07-16T00:00:00+00:00",
            )
            self.assertEqual(len(plan["windows"]), 3)
            self.assertEqual(plan["windows"][1]["start_utc"], "2026-07-16T04:00:00+00:00")
            self.assertEqual(plan["duration_sec"], 1200)
            self.assertEqual(plan["interval_sec"], 5)
            self.assertEqual(plan["minimum_valid_cycles_per_window"], 180)
            self.assertEqual(
                plan["code_provenance"],
                json.loads((root / "plan.json").read_text(encoding="utf-8"))["code_provenance"],
            )

            _, _, rejected_path = self._evaluation_fixture(root / "rejected", verdict="REJECT")
            with self.assertRaisesRegex(ValueError, "ACCEPT_FOR_EXECUTION_PROBE"):
                build_basis_probe_plan(
                    rejected_path,
                    root / "rejected-plan.json",
                    first_window_start_utc="2026-07-16T00:00:00+00:00",
                )

    def test_final_report_distinguishes_await_event_from_paper_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            _, _, evaluation_path = self._evaluation_fixture(root)
            probe_plan_path = root / "probe-plan.json"
            probe_plan = build_basis_probe_plan(
                evaluation_path,
                probe_plan_path,
                first_window_start_utc="2026-07-16T00:00:00+00:00",
            )

            manifests = []
            for index in range(3):
                samples = root / f"samples-{index}.jsonl"
                samples.write_text("", encoding="utf-8")
                payload = {
                    "schema": "trading_mvp_historical_basis_probe_manifest_v1",
                    "final": True,
                    "probe_plan_hash": probe_plan["probe_plan_hash"],
                    "window_index": index,
                    "valid_cycles": 200,
                    "expected_cycles": 240,
                    "coverage": 200 / 240,
                    "p95_timestamp_skew_ms": 500.0,
                    "minimum_capacity_quote": 600.0,
                    "p95_impact_bps": 8.0,
                    "error_count": 0,
                    "qualifying_event_count": 0,
                    "samples_path": str(samples),
                    "samples_sha256": sha256_file(samples),
                }
                path = root / f"manifest-{index}.json"
                _artifact(path, payload)
                manifests.append(path)
            await_event = build_basis_sprint_report(
                evaluation_path=evaluation_path,
                probe_plan_path=probe_plan_path,
                manifest_paths=manifests,
                output_path=root / "await.json",
            )
            self.assertEqual(await_event["verdict"], "HISTORICAL_ACCEPT_AWAIT_EVENT")

            third = json.loads(manifests[2].read_text(encoding="utf-8"))
            third["qualifying_event_count"] = 1
            third.pop("deterministic_result_hash")
            third["deterministic_result_hash"] = _semantic(third)
            manifests[2].write_text(json.dumps(third), encoding="utf-8")
            ready = build_basis_sprint_report(
                evaluation_path=evaluation_path,
                probe_plan_path=probe_plan_path,
                manifest_paths=manifests,
                output_path=root / "ready.json",
            )
            self.assertEqual(ready["verdict"], "PAPER_FORWARD_READY")
            self.assertNotEqual(await_event["deterministic_result_hash"], ready["deterministic_result_hash"])


if __name__ == "__main__":
    unittest.main()
