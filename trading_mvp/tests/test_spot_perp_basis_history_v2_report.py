from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from spot_perp_basis_history_v2 import sha256_json  # noqa: E402
from spot_perp_basis_history_v2 import sha256_file  # noqa: E402
from spot_perp_basis_history_v2_report import (  # noqa: E402
    CLOSURE_MANIFEST_SCHEMA,
    CLOSURE_SCHEMA,
    summarize_basis_values,
    validate_train_reject_closure_manifest,
    validate_train_reject_result,
)
from spot_perp_basis_history_v2_train import TRAIN_RESULT_SCHEMA  # noqa: E402


class GateSpotPerpTrainClosureTests(unittest.TestCase):
    def test_basis_summary_proves_frozen_threshold_was_not_observed(self) -> None:
        summary = summarize_basis_values(
            {"A": [10.0, 112.0, 122.0], "B": [20.0, 119.0]},
            normal_break_even_bps=102.0,
            stress_break_even_bps=112.0,
            frozen_entry_threshold_bps=132.0,
        )

        self.assertEqual(summary["observation_count"], 5)
        self.assertEqual(summary["maximum_basis_bps"], 122.0)
        self.assertEqual(summary["count_at_or_above_stress_break_even"], 3)
        self.assertEqual(summary["count_at_or_above_frozen_entry"], 0)
        self.assertEqual(summary["asset_count_at_or_above_frozen_entry"], 0)
        self.assertEqual(len(summary["diagnostic_hash"]), 64)

    def test_train_reject_validation_accepts_hash_bound_repeat(self) -> None:
        plan_hash = "a" * 64
        result = {
            "schema": TRAIN_RESULT_SCHEMA,
            "generated_at_utc": "ignored",
            "final": True,
            "decision": "INFEASIBLE_ON_CURRENT_DATA",
            "train_plan_hash": plan_hash,
            "metrics": {"episode_count": 0},
            "rejection_reasons": ["minimum_independent_episodes"],
            "asset_diagnostics": {},
            "episodes": [],
            "oos_read": False,
            "grid_search": False,
            "retune": False,
            "network_access": False,
            "live_orders": False,
            "next_allowed_command": "none_branch_closed_no_retune",
        }
        core = {key: value for key, value in result.items() if key != "generated_at_utc"}
        result_hash = sha256_json(core)
        result["deterministic_result_hash"] = result_hash
        result["deterministic_repeat_match"] = True
        result["deterministic_repeat_hash"] = result_hash

        validate_train_reject_result(result, expected_train_plan_hash=plan_hash)

    def test_train_reject_validation_rejects_oos_access(self) -> None:
        plan_hash = "b" * 64
        result = {
            "schema": TRAIN_RESULT_SCHEMA,
            "final": True,
            "decision": "INFEASIBLE_ON_CURRENT_DATA",
            "train_plan_hash": plan_hash,
            "metrics": {},
            "rejection_reasons": [],
            "asset_diagnostics": {},
            "episodes": [],
            "oos_read": True,
            "grid_search": False,
            "retune": False,
            "network_access": False,
            "live_orders": False,
            "next_allowed_command": "none_branch_closed_no_retune",
        }
        core = dict(result)
        result_hash = sha256_json(core)
        result["deterministic_result_hash"] = result_hash
        result["deterministic_repeat_match"] = True
        result["deterministic_repeat_hash"] = result_hash

        with self.assertRaisesRegex(ValueError, "OOS/grid"):
            validate_train_reject_result(result, expected_train_plan_hash=plan_hash)

    def test_closure_manifest_rejects_changed_provenance(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            references = {}
            for name in ("parent_plan", "collector", "quality", "train_plan", "train_result"):
                reference_path = root / f"{name}.json"
                reference_path.write_text("{}\n", encoding="utf-8")
                references[name] = {
                    "path": str(reference_path),
                    "file_sha256": sha256_file(reference_path),
                }
            closure = {
                "schema": CLOSURE_SCHEMA,
                "generated_at_utc": "ignored",
                "hypothesis_id": "gate_spot_perp_basis_convergence_history_v2",
                "final": True,
                "verdict": "INFEASIBLE_ON_CURRENT_DATA",
                "branch_status": "CLOSED_WITHOUT_OOS_OR_RETUNE",
                "reason_code": "FROZEN_ECONOMIC_ENTRY_THRESHOLD_NOT_OBSERVED_IN_TRAIN",
                **references,
                "train_basis_diagnostic": {
                    "count_at_or_above_frozen_entry": 0,
                    "maximum_basis_bps": 120.0,
                    "thresholds": {"frozen_entry_threshold_bps": 132.0},
                },
                "data_access_audit": {"train_pnl_computed": True, "oos_read": False},
            }
            closure["artifact_hash"] = sha256_json(
                {key: value for key, value in closure.items() if key not in {"generated_at_utc", "artifact_hash"}}
            )
            closure_path = root / "closure.json"
            closure_path.write_text(json.dumps(closure) + "\n", encoding="utf-8")
            manifest = {
                "schema": CLOSURE_MANIFEST_SCHEMA,
                "generated_at_utc": "ignored",
                "hypothesis_id": "gate_spot_perp_basis_convergence_history_v2",
                "status": "BRANCH_CLOSED_TRAIN_INFEASIBLE",
                "final": True,
                "verdict": "INFEASIBLE_ON_CURRENT_DATA",
                "closure_path": str(closure_path),
                "closure_file_sha256": sha256_file(closure_path),
                "closure_artifact_hash": closure["artifact_hash"],
                "oos_read": False,
                "retune": False,
                "grid_allowed": False,
                "replay_allowed": False,
                "execution_probe_allowed": False,
                "paper_forward_allowed": False,
                "live_orders_allowed": False,
            }
            manifest["manifest_hash"] = sha256_json(
                {key: value for key, value in manifest.items() if key not in {"generated_at_utc", "manifest_hash"}}
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            validate_train_reject_closure_manifest(manifest_path)
            (root / "quality.json").write_text('{"changed":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance changed: quality"):
                validate_train_reject_closure_manifest(manifest_path)


if __name__ == "__main__":
    unittest.main()
