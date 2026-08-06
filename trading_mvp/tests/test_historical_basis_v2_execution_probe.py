from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2 import (  # noqa: E402
    DAY_SEC,
    build_historical_basis_v2_plan,
    sha256_file,
)
from historical_basis_v2_evaluator import (  # noqa: E402
    SCHEMA as EVALUATION_SCHEMA,
    _artifact_hash as evaluation_hash,
)
from historical_basis_v2_execution_probe import (  # noqa: E402
    artifact_hash,
    build_arg_parser,
    build_execution_probe_plan,
    build_execution_probe_report,
    finalize_execution_probe_window,
    validate_execution_probe_plan,
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


def _write_evaluation(
    root: Path,
    *,
    verdict: str = "ACCEPT_FOR_EXECUTION_PROBE",
) -> tuple[dict[str, object], Path]:
    plan_path = root / "historical-plan.json"
    plan = build_historical_basis_v2_plan(
        [_asset(index) for index in range(8)],
        output_path=plan_path,
        window_end_ts=179 * DAY_SEC,
        frozen_at_utc="2026-07-16T00:00:00+00:00",
    )
    evaluation: dict[str, object] = {
        "schema": EVALUATION_SCHEMA,
        "stage": "full_evaluation",
        "verdict": verdict,
        "plan_hash": plan["plan_hash"],
        "plan_path": str(plan_path),
        "plan_file_sha256": sha256_file(plan_path),
        "code_provenance": plan["code_provenance"],
        "normal_trades": [
            {"base": f"A{index % 8:02d}", "episode_id": f"episode-{index}"}
            for index in range(40)
        ],
        "stress_trades": [
            {"base": f"A{index % 8:02d}", "episode_id": f"episode-{index}"}
            for index in range(40)
        ],
        "metrics": {
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
        "four_hour_robustness": {
            "passed": verdict == "ACCEPT_FOR_EXECUTION_PROBE",
            "rejection_reasons": [] if verdict == "ACCEPT_FOR_EXECUTION_PROBE" else ["fixture"],
        },
        "oos_read": True,
        "oos_input_hashes": {"candles_sha256": "b" * 64},
        "feasibility_provenance": {"deterministic_result_hash": "c" * 64},
        "data_access_audit": {
            "oos_files_opened": True,
            "oos_returns_read": True,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
        "rejection_reasons": [] if verdict == "ACCEPT_FOR_EXECUTION_PROBE" else ["fixture"],
    }
    evaluation["deterministic_result_hash"] = evaluation_hash(evaluation)
    evaluation_path = root / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    return plan, evaluation_path


def _write_samples(
    path: Path,
    *,
    window_index: int,
    base: str,
    valid_rows: int = 200,
    qualifying: bool = False,
    capacity_quote: float = 600.0,
    impact_bps: float = 8.0,
) -> None:
    rows = []
    for cycle in range(1, valid_rows + 1):
        rows.append(
            {
                "schema": "trading_mvp_historical_basis_v2_execution_probe_sample_v1",
                "window_index": window_index,
                "cycle": cycle,
                "base": base,
                "timestamp_skew_ms": 500.0,
                "long_execution": {
                    "filled": True,
                    "impact_bps": impact_bps,
                    "capacity_quote_at_max_impact": capacity_quote,
                },
                "short_execution": {
                    "filled": True,
                    "impact_bps": impact_bps,
                    "capacity_quote_at_max_impact": capacity_quote,
                },
                "valid": True,
                "qualifying": qualifying and cycle == valid_rows,
            }
        )
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class HistoricalBasisV2ExecutionProbeTests(unittest.TestCase):
    def test_plan_requires_full_accept_and_freezes_hash_bound_three_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical_plan, evaluation_path = _write_evaluation(root)
            output = root / "probe-plan.json"
            plan = build_execution_probe_plan(
                evaluation_path,
                output,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )

            self.assertEqual(len(plan["windows"]), 3)
            self.assertEqual(plan["windows"][1]["start_utc"], "2026-07-17T04:00:00+00:00")
            self.assertEqual(plan["duration_sec"], 1200)
            self.assertEqual(plan["interval_sec"], 5)
            self.assertEqual(plan["minimum_valid_snapshots_per_base_per_window"], 180)
            self.assertEqual(plan["minimum_coverage_per_base"], 0.80)
            self.assertEqual(plan["minimum_capacity_quote_per_leg"], 500.0)
            self.assertEqual(plan["maximum_p95_impact_bps"], 10.0)
            self.assertEqual(plan["historical_plan_hash"], historical_plan["plan_hash"])
            self.assertEqual(
                plan["historical_evaluation"]["deterministic_result_hash"],
                json.loads(evaluation_path.read_text(encoding="utf-8"))["deterministic_result_hash"],
            )
            self.assertFalse(plan["safety"]["live_orders"])
            self.assertFalse(plan["safety"]["private_api_keys"])
            self.assertFalse(plan["safety"]["leverage_or_margin"])

            rejected_root = root / "rejected"
            rejected_root.mkdir()
            _, rejected_evaluation = _write_evaluation(rejected_root, verdict="REJECT")
            with self.assertRaisesRegex(ValueError, "ACCEPT_FOR_EXECUTION_PROBE"):
                build_execution_probe_plan(
                    rejected_evaluation,
                    rejected_root / "probe-plan.json",
                    first_window_start_utc="2026-07-17T00:00:00+00:00",
                )

    def test_hash_valid_accept_without_oos_access_cannot_create_probe_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
            payload["oos_read"] = False
            payload["data_access_audit"]["oos_files_opened"] = False
            payload["data_access_audit"]["oos_returns_read"] = False
            payload["deterministic_result_hash"] = evaluation_hash(payload)
            evaluation_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "OOS"):
                build_execution_probe_plan(
                    evaluation_path,
                    root / "probe-plan.json",
                    first_window_start_utc="2026-07-17T00:00:00+00:00",
                )

    def test_three_windows_recompute_raw_samples_and_distinguish_await_from_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            probe_plan_path = root / "probe-plan.json"
            probe_plan = build_execution_probe_plan(
                evaluation_path,
                probe_plan_path,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )

            manifests: list[Path] = []
            for window_index in range(3):
                samples = root / f"samples-{window_index}.jsonl"
                _write_samples(samples, window_index=window_index, base="A00")
                manifest = root / f"manifest-{window_index}.json"
                finalize_execution_probe_window(
                    probe_plan_path,
                    expected_probe_plan_hash=probe_plan["probe_plan_hash"],
                    window_index=window_index,
                    samples_path=samples,
                    manifest_path=manifest,
                    completed_cycles=240,
                    expected_cycles=240,
                    errors=[],
                )
                manifests.append(manifest)

            await_report = build_execution_probe_report(
                evaluation_path=evaluation_path,
                probe_plan_path=probe_plan_path,
                manifest_paths=manifests,
                output_path=root / "await-report.json",
            )
            self.assertEqual(await_report["verdict"], "HISTORICAL_ACCEPT_AWAIT_EVENT")
            self.assertEqual(await_report["execution_eligible_bases"], ["A00"])
            self.assertEqual(await_report["maximum_authority"], "PAPER_FORWARD_PLANONLY")

            samples = root / "samples-2-ready.jsonl"
            _write_samples(
                samples,
                window_index=2,
                base="A00",
                qualifying=True,
            )
            ready_manifest = root / "manifest-2-ready.json"
            finalize_execution_probe_window(
                probe_plan_path,
                expected_probe_plan_hash=probe_plan["probe_plan_hash"],
                window_index=2,
                samples_path=samples,
                manifest_path=ready_manifest,
                completed_cycles=240,
                expected_cycles=240,
                errors=[],
            )
            ready_report = build_execution_probe_report(
                evaluation_path=evaluation_path,
                probe_plan_path=probe_plan_path,
                manifest_paths=[manifests[0], manifests[1], ready_manifest],
                output_path=root / "ready-report.json",
            )
            self.assertEqual(ready_report["verdict"], "PAPER_FORWARD_READY")
            self.assertEqual(
                ready_report["next_allowed_command"],
                "fast-edge-basis-v2-paper-plan",
            )
            self.assertEqual(ready_report["qualifying_execution_eligible_bases"], ["A00"])
            self.assertNotEqual(
                await_report["deterministic_result_hash"],
                ready_report["deterministic_result_hash"],
            )

    def test_pooled_pass_cannot_hide_per_base_capacity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            probe_plan_path = root / "probe-plan.json"
            probe_plan = build_execution_probe_plan(
                evaluation_path,
                probe_plan_path,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )
            manifests = []
            for window_index in range(3):
                samples = root / f"samples-{window_index}.jsonl"
                _write_samples(
                    samples,
                    window_index=window_index,
                    base="A01",
                    qualifying=True,
                    capacity_quote=499.0,
                )
                manifest = root / f"manifest-{window_index}.json"
                finalize_execution_probe_window(
                    probe_plan_path,
                    expected_probe_plan_hash=probe_plan["probe_plan_hash"],
                    window_index=window_index,
                    samples_path=samples,
                    manifest_path=manifest,
                    completed_cycles=240,
                    expected_cycles=240,
                    errors=[],
                )
                manifests.append(manifest)

            report = build_execution_probe_report(
                evaluation_path=evaluation_path,
                probe_plan_path=probe_plan_path,
                manifest_paths=manifests,
                output_path=root / "report.json",
            )
            self.assertEqual(report["verdict"], "REJECT")
            self.assertIn("no_base_passed_all_three_execution_windows", report["rejection_reasons"])
            self.assertEqual(report["execution_eligible_bases"], [])

    def test_report_requires_exactly_three_distinct_final_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            probe_plan_path = root / "probe-plan.json"
            probe_plan = build_execution_probe_plan(
                evaluation_path,
                probe_plan_path,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )
            samples = root / "samples.jsonl"
            _write_samples(samples, window_index=0, base="A00")
            manifest = root / "manifest.json"
            finalize_execution_probe_window(
                probe_plan_path,
                expected_probe_plan_hash=probe_plan["probe_plan_hash"],
                window_index=0,
                samples_path=samples,
                manifest_path=manifest,
                completed_cycles=240,
                expected_cycles=240,
                errors=[],
            )
            with self.assertRaisesRegex(ValueError, "exactly three distinct"):
                build_execution_probe_report(
                    evaluation_path=evaluation_path,
                    probe_plan_path=probe_plan_path,
                    manifest_paths=[manifest],
                    output_path=root / "report.json",
                )

    def test_probe_plan_and_report_fail_closed_on_provenance_or_metric_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            probe_plan_path = root / "probe-plan.json"
            probe_plan = build_execution_probe_plan(
                evaluation_path,
                probe_plan_path,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )

            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
            evaluation["rejection_reasons"] = ["tampered-after-plan"]
            evaluation["deterministic_result_hash"] = evaluation_hash(evaluation)
            evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                validate_execution_probe_plan(
                    probe_plan_path,
                    probe_plan["probe_plan_hash"],
                )

    def test_manifest_claims_are_recomputed_and_incomplete_window_cannot_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, evaluation_path = _write_evaluation(root)
            probe_plan_path = root / "probe-plan.json"
            probe_plan = build_execution_probe_plan(
                evaluation_path,
                probe_plan_path,
                first_window_start_utc="2026-07-17T00:00:00+00:00",
            )
            samples = root / "samples.jsonl"
            _write_samples(samples, window_index=0, base="A00")
            manifest = root / "manifest.json"
            finalize_execution_probe_window(
                probe_plan_path,
                expected_probe_plan_hash=probe_plan["probe_plan_hash"],
                window_index=0,
                samples_path=samples,
                manifest_path=manifest,
                completed_cycles=239,
                expected_cycles=240,
                errors=[],
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["final"] = True
            payload["window_metrics"]["eligible_bases"] = ["A00"]
            payload["deterministic_result_hash"] = artifact_hash(payload)
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "completed cycle count"):
                build_execution_probe_report(
                    evaluation_path=evaluation_path,
                    probe_plan_path=probe_plan_path,
                    manifest_paths=[manifest, manifest, manifest],
                    output_path=root / "report.json",
                )

    def test_collect_cli_preserves_owned_run_id(self) -> None:
        args = build_arg_parser().parse_args(
            [
                "collect",
                "--plan",
                "plan.json",
                "--expected-plan-hash",
                "a" * 64,
                "--window-index",
                "1",
                "--samples",
                "samples.jsonl",
                "--manifest",
                "manifest.json",
                "--run-id",
                "owned-probe-run",
            ]
        )
        self.assertEqual(args.run_id, "owned-probe-run")


if __name__ == "__main__":
    unittest.main()
