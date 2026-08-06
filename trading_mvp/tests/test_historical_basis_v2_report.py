from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from historical_basis_v2_evaluator import SCHEMA as EVALUATION_SCHEMA
from historical_basis_v2_evaluator import _artifact_hash
from historical_basis_v2 import sha256_json
from historical_basis_v2_report import SCHEMA, build_terminal_report


def _passing_metrics() -> dict[str, object]:
    return {
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
    }


def _trades() -> list[dict[str, object]]:
    return [
        {"episode_id": f"episode-{index}", "base": f"A{index % 8:02d}"}
        for index in range(40)
    ]


def _evaluation(verdict: str = "REJECT") -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": EVALUATION_SCHEMA,
        "stage": "full_evaluation",
        "plan_hash": "a" * 64,
        "verdict": verdict,
        "rejection_reasons": [] if verdict == "ACCEPT_FOR_EXECUTION_PROBE" else ["stress_net_pnl"],
        "metrics": _passing_metrics(),
        "normal_trades": _trades(),
        "stress_trades": _trades(),
        "four_hour_robustness": {
            "passed": verdict == "ACCEPT_FOR_EXECUTION_PROBE",
            "rejection_reasons": [] if verdict == "ACCEPT_FOR_EXECUTION_PROBE" else ["stress_net_pnl"],
        },
        "oos_read": True,
        "oos_input_hashes": {"candles_sha256": "b" * 64},
        "feasibility_provenance": {"deterministic_result_hash": "c" * 64},
        "code_provenance": {"code_snapshot_hash": "d" * 64},
        "data_access_audit": {
            "oos_files_opened": True,
            "oos_returns_read": True,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
    }
    payload["deterministic_result_hash"] = _artifact_hash(payload)
    return payload


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quality_reject_closure(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    plan_hash = "a" * 64
    plan = root / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "hypothesis": {
                    "id": "cross_venue_perp_basis_convergence_1h_v2",
                    "frozen_parameters_no_grid": True,
                },
                "plan_hash": plan_hash,
            }
        ),
        encoding="utf-8",
    )

    collector = root / "collector-manifest.json"
    collector.write_text(
        json.dumps(
            {
                "status": "READY_FOR_POSTPROCESS",
                "final": True,
                "plan_hash": plan_hash,
                "expected_plan_hash": plan_hash,
                "expected_items": 120,
                "completed_items": 120,
                "error_count": 0,
            }
        ),
        encoding="utf-8",
    )

    quality = root / "quality-report.json"
    quality_payload: dict[str, object] = {
        "schema": "trading_mvp_historical_basis_v2_quality_v2",
        "status": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "final": True,
        "plan_hash": plan_hash,
        "quality_surviving_asset_count": 20,
        "surviving_asset_count": 5,
        "quality_gates": {"minimum_train_median_quote_volume": 1_000_000.0},
        "primary_assets": [
            {"canonical_asset_id": f"asset:{index}", "base": f"A{index:02d}"}
            for index in range(5)
        ],
        "train_liquidity_ranking": [
            {
                "canonical_asset_id": f"asset:{index}",
                "base": f"A{index:02d}",
                "train_worse_leg_quote_volume": 2_000_000.0 + index,
            }
            for index in range(5)
        ],
        "train_row_count": 10_200,
        "oos_row_count": 9_600,
        "funding_event_count": 12_977,
        "input_file_merkle_sha256": "b" * 64,
        "data_access_audit": {
            "returns_read": False,
            "pnl_read": False,
            "pnl_computed": False,
            "signals_read": False,
            "oos_metrics_read": False,
            "oos_candle_values_used_for_liquidity": False,
        },
        "output_artifacts": {"report": {"sha256": None}},
    }
    from historical_basis_v2_evaluator import quality_semantic_hash

    quality_payload["report_payload_sha256"] = quality_semantic_hash(quality_payload)
    quality.write_text(json.dumps(quality_payload), encoding="utf-8")

    postprocess = root / "postprocess-manifest.json"
    postprocess_payload: dict[str, object] = {
        "schema": "trading_mvp_historical_basis_v2_train_postprocess_v1",
        "status": "BRANCH_CLOSED_QUALITY_REJECTED",
        "final": True,
        "plan_hash": plan_hash,
        "quality_verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "oos_read": False,
        "full_evaluation": False,
        "network_access": False,
        "grid_search": False,
        "retune": False,
        "next_allowed_command": "close-hypothesis-without-retune",
    }
    postprocess_payload["deterministic_result_hash"] = sha256_json(postprocess_payload)
    postprocess.write_text(json.dumps(postprocess_payload), encoding="utf-8")

    closure = root / "closure.json"
    closure_payload = {
        "schema": "trading_mvp_historical_basis_v2_branch_closure_v1",
        "project": "trading_mvp",
        "hypothesis_id": "cross_venue_perp_basis_convergence_1h_v2",
        "run_id": "fixture-run",
        "final": True,
        "verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
        "branch_status": "CLOSED_WITHOUT_OOS_OR_RETUNE",
        "reason_code": "TRAIN_LIQUIDITY_SURVIVORS_BELOW_FROZEN_MINIMUM",
        "reason": "Only 5 assets passed; 8 required.",
        "edge_evaluated": False,
        "train_signal_metrics_read": False,
        "oos_read": False,
        "pnl_read": False,
        "plan_provenance": {
            "path": str(plan),
            "file_sha256": _file_sha256(plan),
            "plan_hash": plan_hash,
            "universe_hash": "c" * 64,
            "code_snapshot_hash": "d" * 64,
            "frozen_parameters_no_grid": True,
        },
        "collector": {
            "manifest_path": str(collector),
            "manifest_file_sha256": _file_sha256(collector),
            "status": "READY_FOR_POSTPROCESS",
            "final": True,
            "expected_series": 120,
            "completed_series": 120,
            "error_count": 0,
        },
        "quality": {
            "report_path": str(quality),
            "report_file_sha256": _file_sha256(quality),
            "report_payload_sha256": quality_payload["report_payload_sha256"],
            "status": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
            "quality_surviving_assets": 20,
            "liquidity_surviving_assets": 5,
            "minimum_required_assets": 8,
            "minimum_train_median_quote_volume": 1_000_000.0,
            "accepted_assets": quality_payload["train_liquidity_ranking"],
            "train_rows": 10_200,
            "oos_rows_normalized_not_evaluated": 9_600,
            "funding_events": 12_977,
            "input_file_merkle_sha256": "b" * 64,
            "data_access_audit": quality_payload["data_access_audit"],
        },
        "train_postprocess": {
            "manifest_path": str(postprocess),
            "manifest_file_sha256": _file_sha256(postprocess),
            "status": "BRANCH_CLOSED_QUALITY_REJECTED",
            "verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
            "deterministic_result_hash": postprocess_payload["deterministic_result_hash"],
            "network_access": False,
            "oos_read": False,
            "grid_search": False,
            "retune": False,
        },
        "safety": {
            "research_only": True,
            "public_api_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "grid_search": False,
            "automatic_oos": False,
            "leverage_or_margin": False,
        },
        "next_allowed_action": "open_materially_new_planonly_hypothesis_or_continue_independent_pit_shadow_track",
        "artifact_hash": "e" * 64,
    }
    closure.write_text(json.dumps(closure_payload), encoding="utf-8")

    manifest = root / "closure.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_historical_basis_v2_branch_closure_manifest_v1",
                "project": "trading_mvp",
                "run_id": "fixture-run",
                "hypothesis_id": "cross_venue_perp_basis_convergence_1h_v2",
                "status": "BRANCH_CLOSED_QUALITY_REJECTED",
                "final": True,
                "verdict": "INSUFFICIENT_EXECUTABLE_UNIVERSE",
                "closure_path": str(closure),
                "closure_file_sha256": _file_sha256(closure),
                "closure_artifact_hash": closure_payload["artifact_hash"],
                "source_postprocess_manifest": str(postprocess),
                "source_deterministic_result_hash": postprocess_payload["deterministic_result_hash"],
                "oos_read": False,
                "pnl_read": False,
                "retune": False,
                "replay_allowed": False,
                "grid_allowed": False,
                "live_orders_allowed": False,
                "next_allowed_action": closure_payload["next_allowed_action"],
            }
        ),
        encoding="utf-8",
    )
    return manifest


class HistoricalBasisV2ReportTests(unittest.TestCase):
    def test_quality_reject_closure_builds_terminal_report_without_oos_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_manifest = _quality_reject_closure(root)

            result = build_terminal_report(
                None,
                root / "report.json",
                closure_manifest_path=closure_manifest,
            )

            self.assertEqual(result["verdict"], "INSUFFICIENT_EXECUTABLE_UNIVERSE")
            self.assertEqual(result["status"], "TERMINAL_PRE_OOS_QUALITY_VERDICT")
            self.assertEqual(result["maximum_authority"], "BRANCH_CLOSED_NO_OOS")
            self.assertFalse(result["data_access_audit"]["oos_read"])
            self.assertFalse(result["data_access_audit"]["pnl_read"])
            self.assertNotIn("metrics", result)
            self.assertEqual(result["quality_summary"]["liquidity_surviving_assets"], 5)
            self.assertEqual(result["quality_summary"]["minimum_required_assets"], 8)
            self.assertEqual(
                result["next_allowed_command"],
                "open-materially-new-planonly-hypothesis-or-continue-pit-shadow",
            )

    def test_quality_reject_closure_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_manifest = _quality_reject_closure(root)
            manifest = json.loads(closure_manifest.read_text(encoding="utf-8"))
            closure = Path(manifest["closure_path"])
            closure.write_text(closure.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "closure file hash mismatch"):
                build_terminal_report(
                    None,
                    root / "report.json",
                    closure_manifest_path=closure_manifest,
                )

    def test_quality_reject_source_artifact_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure_manifest = _quality_reject_closure(root)
            manifest = json.loads(closure_manifest.read_text(encoding="utf-8"))
            closure = json.loads(Path(manifest["closure_path"]).read_text(encoding="utf-8"))
            quality = Path(closure["quality"]["report_path"])
            quality.write_text(quality.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "quality report file hash mismatch"):
                build_terminal_report(
                    None,
                    root / "report.json",
                    closure_manifest_path=closure_manifest,
                )

    def test_exactly_one_terminal_source_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation.json"
            evaluation.write_text(json.dumps(_evaluation()), encoding="utf-8")
            closure_manifest = _quality_reject_closure(root / "closure")

            with self.assertRaisesRegex(ValueError, "exactly one"):
                build_terminal_report(
                    evaluation,
                    root / "both.json",
                    closure_manifest_path=closure_manifest,
                )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                build_terminal_report(None, root / "neither.json")

    def test_accept_never_authorizes_more_than_execution_probe_planonly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation.json"
            output = root / "report.json"
            evaluation.write_text(json.dumps(_evaluation("ACCEPT_FOR_EXECUTION_PROBE")), encoding="utf-8")

            result = build_terminal_report(evaluation, output)

            self.assertEqual(result["schema"], SCHEMA)
            self.assertEqual(result["maximum_authority"], "EXECUTION_PROBE_PLANONLY")
            self.assertEqual(
                result["next_allowed_command"],
                "fast-edge-basis-v2-execution-probe-plan",
            )
            self.assertFalse(result["safety"]["live_orders"])

    def test_reject_closes_without_retune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation.json"
            evaluation.write_text(json.dumps(_evaluation()), encoding="utf-8")
            result = build_terminal_report(evaluation, root / "report.json")
            self.assertEqual(result["next_allowed_command"], "close-hypothesis-without-retune")

    def test_preserves_canonical_evaluator_metrics_and_robustness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation.json"
            payload = _evaluation("ACCEPT_FOR_EXECUTION_PROBE")
            payload["metrics"] = {**_passing_metrics(), "normal_net_pnl_quote": 12.5}
            payload["four_hour_robustness"] = {
                "passed": True,
                "normal_net_pnl_quote": 2.0,
                "stress_net_pnl_quote": 0.5,
            }
            payload["deterministic_result_hash"] = _artifact_hash(payload)
            evaluation.write_text(json.dumps(payload), encoding="utf-8")

            result = build_terminal_report(evaluation, root / "report.json")

            self.assertEqual(result["metrics"], payload["metrics"])
            self.assertEqual(
                result["four_hour_robustness"],
                payload["four_hour_robustness"],
            )

    def test_hash_valid_accept_without_verified_oos_access_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation.json"
            payload = _evaluation("ACCEPT_FOR_EXECUTION_PROBE")
            payload["oos_read"] = False
            payload["data_access_audit"] = {
                **payload["data_access_audit"],  # type: ignore[arg-type]
                "oos_files_opened": False,
                "oos_returns_read": False,
            }
            payload["deterministic_result_hash"] = _artifact_hash(payload)
            evaluation.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "OOS"):
                build_terminal_report(evaluation, root / "report.json")

    def test_invalid_hash_and_train_artifact_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evaluation = root / "evaluation.json"
            payload = _evaluation()
            payload["deterministic_result_hash"] = "0" * 64
            evaluation.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                build_terminal_report(evaluation, root / "invalid.json")

            payload = _evaluation()
            payload["stage"] = "train_feasibility"
            payload["deterministic_result_hash"] = _artifact_hash(payload)
            evaluation.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "full_evaluation"):
                build_terminal_report(evaluation, root / "train.json")

    def test_result_hash_is_location_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_input = root / "one" / "evaluation.json"
            second_input = root / "two" / "evaluation.json"
            first_input.parent.mkdir()
            second_input.parent.mkdir()
            text = json.dumps(_evaluation())
            first_input.write_text(text, encoding="utf-8")
            second_input.write_text(text, encoding="utf-8")
            first = build_terminal_report(first_input, root / "one" / "report.json")
            second = build_terminal_report(second_input, root / "two" / "report.json")
            self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])


if __name__ == "__main__":
    unittest.main()
