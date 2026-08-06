from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import night_schedule_plan as schedule  # noqa: E402
import pit_schedule_time_amendment as amendment  # noqa: E402
from hypothesis_contract import build_pit_membership_drift_contract  # noqa: E402


class PitScheduleTimeAmendmentTests(unittest.TestCase):
    def _base_plan(self, root: Path) -> tuple[dict, Path]:
        bank = root / "bank.json"
        goal = root / "goal.md"
        output = root / "base-plan.json"
        contract = build_pit_membership_drift_contract()
        bank.write_text(
            json.dumps(
                {
                    "hypotheses": [
                        {
                            "id": "pit_universe_membership_drift_reversion_v1",
                            "required_data_type": contract["required_data_type"],
                            "status": "BANKED_NEEDS_NEW_DATA",
                            "minimum_data": {
                                "days": 120,
                                "portfolio_events": 20,
                                "per_venue_events": 10,
                                "unique_dates": 10,
                            },
                            "contract": contract,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        goal.write_text("# Goal\n", encoding="utf-8")
        result = schedule.build_night_schedule_plan(
            hypothesis_bank_path=bank,
            hypothesis_id="pit_universe_membership_drift_reversion_v1",
            data_type="PIT_UNIVERSE_V2_FORWARD",
            goal_path=goal,
            output_path=output,
            schedule_start_date="2026-08-05",
            nights=2,
            segment_start_local="01:00",
            segment_duration_sec=1200,
            interval_sec=300,
            output_root=str(root / "output"),
            created_at_utc="2026-08-03T16:00:00+00:00",
        )
        return result, output

    def test_defers_one_segment_in_the_same_night_and_preserves_everything_else(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base, base_path = self._base_plan(root)
            amended_path = root / "amended-plan.json"
            run_id = "pit_universe_v2_forward_20260805_n01"

            result = amendment.build_time_amendment_plan(
                base_plan_path=base_path,
                expected_base_plan_hash=base["plan_hash"],
                run_id=run_id,
                new_start_local="2026-08-05T02:15:00+03:00",
                output_path=amended_path,
                created_at_utc="2026-08-03T16:10:00+00:00",
            )

            amended = json.loads(amended_path.read_text(encoding="utf-8"))
            self.assertEqual(result["verdict"], "TIME_ONLY_AMENDMENT_VALID")
            self.assertNotEqual(result["plan_hash"], base["plan_hash"])
            self.assertEqual(
                amended["time_only_amendment"]["run_id"],
                run_id,
            )
            first = amended["segments"][0]
            self.assertEqual(first["start_local"], "2026-08-05T02:15:00+03:00")
            self.assertEqual(first["end_local"], "2026-08-05T02:35:00+03:00")
            self.assertIn(result["plan_hash"], first["command_after_approval"])
            self.assertEqual(
                amended["sealed_schedule"]["segments"][1],
                json.loads(base_path.read_text(encoding="utf-8"))["sealed_schedule"]["segments"][1],
            )
            self.assertEqual(
                schedule.validate_night_schedule_plan(amended_path, result["plan_hash"])["verdict"],
                "VALID",
            )

    def test_refuses_to_move_before_original_end_or_past_night_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base, base_path = self._base_plan(root)
            run_id = "pit_universe_v2_forward_20260805_n01"
            with self.assertRaisesRegex(ValueError, "defer the segment"):
                amendment.build_time_amendment_plan(
                    base_plan_path=base_path,
                    expected_base_plan_hash=base["plan_hash"],
                    run_id=run_id,
                    new_start_local="2026-08-05T01:10:00+03:00",
                    output_path=root / "too-early.json",
                    created_at_utc="2026-08-03T16:10:00+00:00",
                )
            with self.assertRaisesRegex(ValueError, "after its hard deadline"):
                amendment.build_time_amendment_plan(
                    base_plan_path=base_path,
                    expected_base_plan_hash=base["plan_hash"],
                    run_id=run_id,
                    new_start_local="2026-08-05T06:50:00+03:00",
                    output_path=root / "too-late.json",
                    created_at_utc="2026-08-03T16:10:00+00:00",
                )

    def test_rejects_wrong_base_hash_and_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base, base_path = self._base_plan(root)
            run_id = "pit_universe_v2_forward_20260805_n01"
            with self.assertRaisesRegex(ValueError, "Plan hash mismatch"):
                amendment.build_time_amendment_plan(
                    base_plan_path=base_path,
                    expected_base_plan_hash="0" * 64,
                    run_id=run_id,
                    new_start_local="2026-08-05T02:15:00+03:00",
                    output_path=root / "wrong-hash.json",
                    created_at_utc="2026-08-03T16:10:00+00:00",
                )
            existing = root / "existing.json"
            existing.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                amendment.build_time_amendment_plan(
                    base_plan_path=base_path,
                    expected_base_plan_hash=base["plan_hash"],
                    run_id=run_id,
                    new_start_local="2026-08-05T02:15:00+03:00",
                    output_path=existing,
                    created_at_utc="2026-08-03T16:10:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
