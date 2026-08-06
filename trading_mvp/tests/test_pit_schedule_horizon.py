from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pit_schedule_horizon import compute_schedule_horizon  # noqa: E402
from pit_train_progress_monitor import summarize_progress  # noqa: E402


TZ = timezone(timedelta(hours=3))
CONTRACT_HASH = "a" * 64


def make_plan(*, first_date: str, nights: int, target: int = 20) -> dict:
    first = datetime.fromisoformat(f"{first_date}T01:00:00+03:00")
    segments = []
    for index in range(nights):
        start = first + timedelta(days=index)
        segments.append(
            {
                "sequence": index + 1,
                "run_id": f"run-{index + 1}",
                "start_local": start.isoformat(),
                "hard_deadline_local": start.replace(
                    hour=7,
                    minute=0,
                ).isoformat(),
            }
        )
    return {
        "sealed_schedule": {
            "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
            "data_type": "PIT_UNIVERSE_V2_FORWARD",
            "hypothesis_contract_sha256": CONTRACT_HASH,
            "collection_stage": {
                "name": "train_accrual",
                "stage_target_distinct_dates": target,
            },
            "segments": segments,
        }
    }


def quality_row(
    scheduled_date: str,
    accepted: bool,
    *,
    contract_hash: str = CONTRACT_HASH,
) -> dict:
    return {
        "schema": "pit_universe_v2_quality_certification_v1",
        "hypothesis_id": "pit_universe_membership_drift_reversion_v1",
        "data_type": "PIT_UNIVERSE_V2_FORWARD",
        "hypothesis_contract_sha256": contract_hash,
        "scheduled_date": scheduled_date,
        "technical_quality_accepted": accepted,
    }


class PitScheduleHorizonTests(unittest.TestCase):
    def test_detects_four_date_shortfall_after_two_expired_windows(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-16", False),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 7, 30, 21, 0, tzinfo=TZ),
        )

        self.assertEqual(result["decision"], "PLANONLY_EXTENSION_REQUIRED")
        self.assertEqual(result["accepted_distinct_dates"], 4)
        self.assertEqual(result["expired_unaccepted_dates"], ["2026-07-29", "2026-07-30"])
        self.assertEqual(result["reachable_scheduled_dates"], 12)
        self.assertEqual(result["maximum_reachable_distinct_dates"], 16)
        self.assertEqual(result["train_gate_shortfall_dates"], 4)
        self.assertEqual(result["observed_quality_acceptance_rate"], 0.8)
        self.assertEqual(result["recommended_extension_nights"], 5)
        self.assertEqual(result["extension_start_date"], "2026-08-12")

    def test_reports_sufficient_when_current_horizon_can_reach_target(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=16)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
        )

        self.assertEqual(
            result["decision"],
            "CURRENT_SCHEDULE_SUFFICIENT_FOR_TRAIN_GATE",
        )
        self.assertEqual(result["train_gate_shortfall_dates"], 0)
        self.assertEqual(result["recommended_extension_nights"], 0)
        self.assertIsNone(result["extension_start_date"])

    def test_ignores_quality_rows_from_another_contract(self) -> None:
        plan = make_plan(first_date="2026-07-29", nights=1, target=2)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True, contract_hash="b" * 64),
        ]

        result = compute_schedule_horizon(
            plan,
            rows,
            observed_at=datetime(2026, 7, 28, 21, 0, tzinfo=TZ),
        )

        self.assertEqual(result["accepted_dates"], ["2026-07-14"])
        self.assertEqual(result["maximum_reachable_distinct_dates"], 2)
        self.assertEqual(
            result["decision"],
            "CURRENT_SCHEDULE_SUFFICIENT_FOR_TRAIN_GATE",
        )

    def test_horizon_and_progress_projection_share_expiry_semantics(
        self,
    ) -> None:
        plan = make_plan(first_date="2026-07-29", nights=14)
        rows = [
            quality_row("2026-07-14", True),
            quality_row("2026-07-15", True),
            quality_row("2026-07-16", False),
            quality_row("2026-07-23", True),
            quality_row("2026-07-28", True),
        ]
        observed_at = datetime(2026, 7, 30, 21, 0, tzinfo=TZ)
        horizon = compute_schedule_horizon(
            plan,
            rows,
            observed_at=observed_at,
        )
        accepted = [
            {
                "scheduled_date": str(row["scheduled_date"]),
                "segment_run_id": f"accepted-{row['scheduled_date']}",
            }
            for row in rows
            if row["technical_quality_accepted"]
        ]
        progress = summarize_progress(
            plan=plan,
            validation={
                "plan_path": r"E:\schedule.json",
                "plan_hash": "b" * 64,
                "plan_file_sha256": "c" * 64,
                "collection_stage": "train_accrual",
                "current_accepted_certifications": accepted,
            },
            gate={
                "gate_status": "READY_FOR_POSTPROCESS",
                "run_id": "sidecar",
                "replay_allowed": False,
                "process_ids": [],
            },
            now_local=observed_at,
            approval_status={"status": "HASH_VALID_ACTIVE"},
        )

        self.assertEqual(
            progress["train_eta"]["scheduled_new_dates_available"],
            horizon["reachable_scheduled_dates"],
        )
        self.assertEqual(
            progress["train_eta"]["expired_uncertified_dates"],
            horizon["expired_unaccepted_dates"],
        )
        self.assertEqual(
            progress["train_eta"][
                "projected_accepted_dates_at_schedule_end"
            ],
            horizon["maximum_reachable_distinct_dates"],
        )
        self.assertEqual(
            progress["train_eta"]["additional_dates_needed_after_schedule"],
            horizon["train_gate_shortfall_dates"],
        )


if __name__ == "__main__":
    unittest.main()
