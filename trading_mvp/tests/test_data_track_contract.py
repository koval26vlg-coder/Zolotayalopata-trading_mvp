from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from data_track_contract import build_data_track_contract  # noqa: E402
from feasibility_gate import evaluate_feasibility, validate_frozen_plan  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _hypothesis_bank(path: Path) -> Path:
    _write_json(
        path,
        {
            "version": "test-v1",
            "closed_track": "NO_FAST_EDGE_ON_CURRENT_DAILY_DATA",
            "hypotheses": [
                {
                    "id": "pit_universe_membership_drift_reversion_v1",
                    "status": "BANKED_NEEDS_NEW_DATA",
                    "required_data_type": "PIT_UNIVERSE_V2_FORWARD",
                    "thesis": "Fixture thesis frozen before forward data.",
                    "minimum_data": {"portfolio_events": 20},
                    "forbidden": ["grid-search", "OOS before feasibility"],
                }
            ],
        },
    )
    return path


class DataTrackContractTests(unittest.TestCase):
    def _build(self, root: Path, **overrides: object) -> tuple[dict, Path]:
        bank_path = _hypothesis_bank(root / "hypotheses.json")
        goal_path = root / "goal.md"
        goal_path.write_text("# Frozen canonical goal\n", encoding="utf-8")
        output_path = root / "plan.json"
        arguments: dict[str, object] = {
            "hypothesis_bank_path": bank_path,
            "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
            "data_type": "PIT_UNIVERSE_V2_FORWARD",
            "dataset_id": "pit-v2-fixture",
            "input_merkle_sha256": "a" * 64,
            "output_path": output_path,
            "goal_path": goal_path,
            "track_id": "pit-v2-track-fixture",
            "dataset_root": "E:\\fixture-data",
            "train_candidate_events": 200,
            "train_valid_events": 200,
            "oos_candidate_events": 40,
            "per_venue_oos_candidate_events_json": '{"mexc":20,"gateio":20}',
            "unique_oos_dates": 20,
            "dual_venue_coverage": 1.0,
            "capacity_proxy_quote_per_selected_leg": 750.0,
            "max_runtime_sec": 120,
            "created_at_utc": "2026-07-14T12:00:00+00:00",
        }
        arguments.update(overrides)
        return build_data_track_contract(**arguments), output_path

    def test_builds_hash_bound_plan_that_passes_feasibility_without_oos_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result, output_path = self._build(Path(temp_dir))
            plan = json.loads(output_path.read_text(encoding="utf-8"))

            validate_frozen_plan(plan)
            self.assertEqual(result["next_allowed_action"], "run_fast_edge_feasibility_before_any_oos")
            self.assertFalse(plan["evaluation_allowed"])
            self.assertEqual(plan["oos_metrics"], {})
            self.assertEqual(plan["observed_performance"], {})
            self.assertFalse(plan["data_access_audit"]["oos_returns_read"])
            self.assertFalse(plan["data_access_audit"]["network_access"])
            self.assertFalse(plan["track"]["actual_collection_started"])

            feasibility = evaluate_feasibility(output_path)
            self.assertEqual(feasibility["verdict"], "FEASIBLE_FOR_OOS")
            self.assertEqual(feasibility["next_allowed_action"], "run_visible_owned_no_grid_oos")
            self.assertFalse(feasibility["oos_metrics_read"])
            self.assertFalse(feasibility["pnl_or_returns_read"])

    def test_rejects_data_type_that_does_not_match_banked_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "requires data_type=PIT_UNIVERSE_V2_FORWARD"):
                self._build(Path(temp_dir), data_type="DENSE_WS_SEGMENTED")

    def test_rejects_non_hex_input_merkle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "SHA-256 hex"):
                self._build(Path(temp_dir), input_merkle_sha256="z" * 64)

    def test_refuses_to_overwrite_immutable_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._build(root)
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite immutable"):
                self._build(root)

    def test_rejects_runtime_above_planonly_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, r"MaxRuntimeSec must be in \[1, 1200\]"):
                self._build(Path(temp_dir), max_runtime_sec=1201)


if __name__ == "__main__":
    unittest.main()
