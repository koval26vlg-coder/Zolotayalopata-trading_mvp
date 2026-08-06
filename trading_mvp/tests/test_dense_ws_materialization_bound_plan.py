from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_materialization_bound_plan as bound  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safety() -> dict[str, bool]:
    return {key: False for key in bound.FALSE_SAFETY_KEYS}


def _fixture(root: Path) -> dict[str, object]:
    campaign_root = (root / "campaign").resolve()
    segment_root = campaign_root / "phase_01" / "seg_001"
    raw_mexc = segment_root / "ws_mexc.jsonl"
    raw_gate = segment_root / "ws_gateio.jsonl"
    raw_mexc.parent.mkdir(parents=True, exist_ok=True)
    raw_mexc.write_text('{"exchange":"mexc","event":"bbo"}\n', encoding="utf-8")
    raw_gate.write_text('{"exchange":"gateio","event":"bbo"}\n', encoding="utf-8")

    segment_manifest = segment_root / "manifest.json"
    _write_json(
        segment_manifest,
        {
            "completed": True,
            "final": True,
            "segment_started_epoch": 0.0,
            "segment_finished_epoch": 3600.0,
        },
    )
    phase_manifest = campaign_root / "phase_01" / "manifest.json"
    _write_json(phase_manifest, {"completed": True, "final": True})

    campaign_id = "dense_ws_microstructure_regime_filter_v1_20260803_aef_24h"
    campaign_contract = {"contract_hash": "c" * 64}
    campaign_contract_path = root / "campaign-contract.json"
    _write_json(campaign_contract_path, campaign_contract)
    campaign_plan = {
        "campaign_id": campaign_id,
        "plan_hash": "b" * 64,
        "contract": {
            "path": str(campaign_contract_path.resolve()),
            "file_sha256": _sha(campaign_contract_path),
            "contract_hash": campaign_contract["contract_hash"],
            "candidate_contract_hash": "a" * 64,
        },
        "outputs": {"campaign_root": str(campaign_root)},
    }
    campaign_plan_path = root / "campaign-plan.json"
    _write_json(campaign_plan_path, campaign_plan)

    campaign_manifest = campaign_root / "campaign-manifest.json"
    _write_json(
        campaign_manifest,
        {
            "schema": bound.CAMPAIGN_MANIFEST_SCHEMA,
            "completed": True,
            "final": True,
            "campaign_id": campaign_id,
            "plan_hash": campaign_plan["plan_hash"],
            "contract_hash": campaign_contract["contract_hash"],
        },
    )
    quality = {
        "schema": bound.QUALITY_SCHEMA,
        "campaign_id": campaign_id,
        "plan_hash": campaign_plan["plan_hash"],
        "contract_hash": campaign_contract["contract_hash"],
        "candidate_contract_hash": campaign_plan["contract"][
            "candidate_contract_hash"
        ],
        "accepted": True,
        "decision": "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
        "inputs": {
            "campaign_manifest": {
                "path": str(campaign_manifest.resolve()),
                "sha256": _sha(campaign_manifest),
            },
            "phase_manifests": [
                {
                    "phase_id": "phase_01",
                    "path": str(phase_manifest.resolve()),
                    "sha256": _sha(phase_manifest),
                }
            ],
        },
        "segments": [
            {
                "phase_id": "phase_01",
                "run_id": f"{campaign_id}_phase_01",
                "segment_index": 1,
                "segment_dir": "seg_001",
                "manifest": {
                    "path": str(segment_manifest.resolve()),
                    "sha256": _sha(segment_manifest),
                },
                "valid": True,
                "raw_files": [
                    {"path": str(raw_mexc.resolve()), "sha256": _sha(raw_mexc)},
                    {"path": str(raw_gate.resolve()), "sha256": _sha(raw_gate)},
                ],
            }
        ],
        "safety": _safety(),
    }
    quality["deterministic_result_hash"] = bound._deterministic_result_hash(quality)
    quality_path = campaign_root / "_postrun" / "campaign-quality.json"
    _write_json(quality_path, quality)

    labels_path = campaign_root / "_postrun" / "causal-regime-labels.jsonl"
    labels_path.write_text(
        json.dumps({"schema": bound.LABEL_SCHEMA, "label": "DENSE_BOTH"}) + "\n",
        encoding="utf-8",
    )
    snapshots_path = campaign_root / "_postrun" / "execution-snapshots.jsonl"
    snapshots_path.write_text(
        json.dumps({"schema": bound.SNAPSHOT_SCHEMA, "base": "HYPE"}) + "\n",
        encoding="utf-8",
    )
    materialization = {
        "schema": bound.MATERIALIZATION_SCHEMA,
        "campaign_id": campaign_id,
        "plan_hash": campaign_plan["plan_hash"],
        "contract_hash": campaign_contract["contract_hash"],
        "candidate_contract_hash": campaign_plan["contract"][
            "candidate_contract_hash"
        ],
        "quality_report": {
            "path": str(quality_path.resolve()),
            "sha256": _sha(quality_path),
            "deterministic_result_hash": quality["deterministic_result_hash"],
        },
        "accepted": True,
        "decision": "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW",
        "valid_segments": 1,
        "labels": {
            "path": str(labels_path.resolve()),
            "sha256": _sha(labels_path),
            "rows": 1,
        },
        "execution_snapshots": {
            "path": str(snapshots_path.resolve()),
            "sha256": _sha(snapshots_path),
            "rows": 1,
        },
        "safety": _safety(),
    }
    materialization["deterministic_result_hash"] = (
        bound._deterministic_result_hash(materialization)
    )
    materialization_path = campaign_root / "_postrun" / "materialization.json"
    _write_json(materialization_path, materialization)

    frozen_contract = {
        "contract_hash": "d" * 64,
        "identity": {
            "campaign_id": campaign_id,
            "hypothesis_id": "dense_ws_microstructure_regime_filter_v1",
            "data_type": "DENSE_WS_SEGMENTED",
        },
        "source_campaign": {
            "plan_hash": campaign_plan["plan_hash"],
            "contract_hash": campaign_contract["contract_hash"],
        },
        "materialization_binding_contract": {
            "required_future_bindings": [
                "campaign_manifest_sha256",
                "campaign_quality_report_sha256",
                "causal_materialization_manifest_sha256",
                "causal_materialization_deterministic_result_hash",
                "regime_labels_sha256",
                "execution_snapshots_sha256",
                "raw_bbo_segment_chain_and_file_hashes",
            ]
        },
        "authorization": {"evaluation_authorized": False},
        "signal_contract": {"parameter_combinations": 1},
        "execution_realization_contract": {"normal_latency_ms": 250},
        "evaluation_design_contract": {"grid_search": False, "retune": False},
        "acceptance_contract": {"robustness": {"deterministic_repeats": 2}},
        "decision_contract": {"historical_result_can_accept_strategy": False},
    }
    frozen_contract_path = root / "frozen-contract.json"
    _write_json(frozen_contract_path, frozen_contract)
    frozen_plan = {"plan_hash": "e" * 64, "executable": False}
    frozen_plan_path = root / "frozen-plan.json"
    _write_json(frozen_plan_path, frozen_plan)
    proposal_path = root / "proposal.json"
    receipt_path = root / "freeze-approval.json"
    _write_json(proposal_path, {"proposal_hash": "f" * 64})
    _write_json(receipt_path, {"status": "APPROVED"})

    return {
        "frozen_contract": frozen_contract,
        "frozen_contract_path": frozen_contract_path,
        "frozen_plan": frozen_plan,
        "frozen_plan_path": frozen_plan_path,
        "campaign_contract": campaign_contract,
        "campaign_contract_path": campaign_contract_path,
        "campaign_plan": campaign_plan,
        "campaign_plan_path": campaign_plan_path,
        "quality": quality,
        "quality_path": quality_path,
        "materialization": materialization,
        "materialization_path": materialization_path,
        "proposal_path": proposal_path,
        "receipt_path": receipt_path,
        "raw_mexc": raw_mexc,
    }


def _build(fixture: dict[str, object]) -> dict:
    with (
        patch.object(bound.freeze, "validate_frozen_plan"),
        patch.object(bound.campaign, "validate_contract"),
        patch.object(bound.campaign, "validate_plan"),
    ):
        return bound.build_materialization_bound_plan(
            frozen_contract=fixture["frozen_contract"],
            frozen_contract_path=fixture["frozen_contract_path"],
            frozen_plan=fixture["frozen_plan"],
            frozen_plan_path=fixture["frozen_plan_path"],
            campaign_contract=fixture["campaign_contract"],
            campaign_contract_path=fixture["campaign_contract_path"],
            campaign_plan=fixture["campaign_plan"],
            campaign_plan_path=fixture["campaign_plan_path"],
            quality=fixture["quality"],
            quality_path=fixture["quality_path"],
            materialization=fixture["materialization"],
            materialization_path=fixture["materialization_path"],
            max_runtime_sec=30,
        )


class DenseWsMaterializationBoundPlanTests(unittest.TestCase):
    def _temporary_root(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(dir=REPO_ROOT / "trading_mvp" / "tests")

    def test_binds_every_future_hash_without_authorizing_evaluator(self) -> None:
        with self._temporary_root() as temp_dir:
            fixture = _fixture(Path(temp_dir))
            plan = _build(fixture)

            self.assertEqual(plan["schema"], bound.PLAN_SCHEMA)
            self.assertEqual(plan["status"], bound.PLAN_STATUS)
            self.assertFalse(plan["executable"])
            self.assertFalse(plan["authorization"]["evaluation_authorized"])
            self.assertFalse(plan["authorization"]["returns_pnl_oos_allowed"])
            self.assertTrue(plan["authorization"]["materialization_output_bound"])
            self.assertEqual(
                plan["next_allowed_action"],
                "REQUEST_EXACT_HASH_BOUND_EVALUATOR_APPROVAL",
            )
            bindings = plan["materialization"]["required_future_bindings"]
            self.assertEqual(len(bindings), 7)
            self.assertEqual(plan["materialization"]["raw_bbo"]["raw_files"], 2)
            self.assertFalse(
                plan["materialization"]["raw_bbo"][
                    "full_data_hash_revalidation_required_before_evaluator"
                ]
            )
            bound.validate_materialization_bound_plan(plan)

    def test_changed_raw_file_is_rejected_before_plan_creation(self) -> None:
        with self._temporary_root() as temp_dir:
            fixture = _fixture(Path(temp_dir))
            Path(fixture["raw_mexc"]).write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(
                bound.MaterializationBoundPlanIntegrityError,
                "sha256 mismatch",
            ):
                _build(fixture)

    def test_rejects_attempt_to_turn_plan_into_evaluator(self) -> None:
        with self._temporary_root() as temp_dir:
            fixture = _fixture(Path(temp_dir))
            plan = copy.deepcopy(_build(fixture))
            plan["executable"] = True
            plan["authorization"]["evaluation_authorized"] = True
            plan["plan_hash"] = bound.canonical_plan_hash(plan)

            with self.assertRaisesRegex(
                bound.MaterializationBoundPlanIntegrityError,
                "plan.executable",
            ):
                bound.validate_materialization_bound_plan(plan)

    def test_file_builder_is_immutable_and_has_one_total_deadline(self) -> None:
        with self._temporary_root() as temp_dir:
            fixture = _fixture(Path(temp_dir))
            output = Path(temp_dir) / "bound-plan.json"
            with (
                patch.object(bound.freeze, "validate_frozen_files"),
                patch.object(bound.freeze, "validate_frozen_plan"),
                patch.object(bound.campaign, "validate_contract"),
                patch.object(bound.campaign, "validate_plan"),
            ):
                result = bound.build_materialization_bound_plan_file(
                    proposal_path=fixture["proposal_path"],
                    freeze_approval_receipt_path=fixture["receipt_path"],
                    frozen_contract_path=fixture["frozen_contract_path"],
                    frozen_plan_path=fixture["frozen_plan_path"],
                    campaign_contract_path=fixture["campaign_contract_path"],
                    campaign_plan_path=fixture["campaign_plan_path"],
                    quality_path=fixture["quality_path"],
                    materialization_path=fixture["materialization_path"],
                    output_path=output,
                    max_runtime_sec=30,
                )
                self.assertTrue(output.is_file())
                self.assertFalse(result["evaluation_authorized"])
                self.assertEqual(result["file_sha256"], _sha(output))
                with self.assertRaises(FileExistsError):
                    bound.build_materialization_bound_plan_file(
                        proposal_path=fixture["proposal_path"],
                        freeze_approval_receipt_path=fixture["receipt_path"],
                        frozen_contract_path=fixture["frozen_contract_path"],
                        frozen_plan_path=fixture["frozen_plan_path"],
                        campaign_contract_path=fixture["campaign_contract_path"],
                        campaign_plan_path=fixture["campaign_plan_path"],
                        quality_path=fixture["quality_path"],
                        materialization_path=fixture["materialization_path"],
                        output_path=output,
                        max_runtime_sec=30,
                    )

    def test_expired_deadline_creates_no_output(self) -> None:
        with self._temporary_root() as temp_dir:
            fixture = _fixture(Path(temp_dir))
            output = Path(temp_dir) / "bound-plan.json"
            with self.assertRaises(bound.MaterializationBoundPlanRuntimeError):
                bound.build_materialization_bound_plan_file(
                    proposal_path=fixture["proposal_path"],
                    freeze_approval_receipt_path=fixture["receipt_path"],
                    frozen_contract_path=fixture["frozen_contract_path"],
                    frozen_plan_path=fixture["frozen_plan_path"],
                    campaign_contract_path=fixture["campaign_contract_path"],
                    campaign_plan_path=fixture["campaign_plan_path"],
                    quality_path=fixture["quality_path"],
                    materialization_path=fixture["materialization_path"],
                    output_path=output,
                    max_runtime_sec=30,
                    _deadline_monotonic=time.monotonic() - 1,
                )
            self.assertFalse(output.exists())

    def test_visible_wrapper_is_hash_bound_and_cannot_run_evaluator(self) -> None:
        wrapper_path = (
            REPO_ROOT
            / "tools"
            / "build_dense_ws_materialization_bound_planonly_visible.ps1"
        )
        policy_path = (
            REPO_ROOT / "docs" / "plans" / "trading-mvp-autopilot-policy-v1.json"
        )
        wrapper = wrapper_path.read_text(encoding="utf-8")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        config = policy["dense_ws_materialization_bound_planonly"]

        self.assertEqual(Path(config["builder_path"]), Path(bound.__file__).resolve())
        self.assertEqual(
            config["builder_sha256"],
            _sha(Path(bound.__file__).resolve()),
        )
        self.assertEqual(Path(config["visible_wrapper_path"]), wrapper_path.resolve())
        self.assertEqual(config["visible_wrapper_sha256"], _sha(wrapper_path))
        self.assertIn("[switch]$PreflightOnly", wrapper)
        self.assertIn("-WindowStyle Normal", wrapper)
        self.assertIn("\"-NoExit\"", wrapper)
        self.assertIn("VISIBLE_TERMINAL_LAUNCHED", wrapper)
        self.assertIn("terminal_ownership_verified = $true", wrapper)
        self.assertIn("dense_ws_materialization_bound_plan.py", config["builder_path"])
        self.assertNotIn("dense_ws_signal_evaluator.py", wrapper)
        self.assertFalse(config["evaluation_authorized"])
        self.assertFalse(config["returns_pnl_oos_allowed"])
        self.assertFalse(config["grid_or_retune_allowed"])
        self.assertFalse(
            config[
                "paper_live_private_api_real_capital_leverage_margin_allowed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
