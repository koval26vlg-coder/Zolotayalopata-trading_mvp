from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from continuous_production import (  # noqa: E402
    resolve_run_window,
    validate_runtime_request,
)


POLICY = {
    "schema": "trading_mvp_continuous_production_policy_v1",
    "run_windows": {
        "timezone": "Europe/Volgograd",
        "utc_offset_minutes": 180,
        "new_campaign_start_local": "19:00",
        "weekday_hard_stop_local": "08:00",
        "weekend": {
            "opens": "FRIDAY 19:00",
            "hard_stop": "MONDAY 08:00",
        },
    },
    "approval": {
        "request_lead_minutes": 30,
    },
    "runtime": {
        "short_offline_task_max_runtime_sec": 1800,
    },
}


class ContinuousProductionTests(unittest.TestCase):
    def test_weeknight_opens_at_1900_and_stops_at_0800(self) -> None:
        result = resolve_run_window(
            POLICY,
            observed_at_utc="2026-07-30T16:00:00Z",
        )

        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(result["window_type"], "WEEKNIGHT")
        self.assertEqual(
            result["hard_deadline_local"],
            "2026-07-31T08:00:00+03:00",
        )
        self.assertEqual(result["max_remaining_runtime_sec"], 46_800)

    def test_weekday_0800_is_closed_until_1900(self) -> None:
        result = resolve_run_window(
            POLICY,
            observed_at_utc="2026-07-30T05:00:00Z",
        )

        self.assertEqual(result["status"], "CLOSED")
        self.assertFalse(result["new_campaign_start_allowed_now"])
        self.assertEqual(
            result["next_opens_at_local"],
            "2026-07-30T19:00:00+03:00",
        )
        self.assertEqual(result["approval_request_status"], "NOT_DUE")

    def test_preopen_approval_is_due_at_1830(self) -> None:
        result = resolve_run_window(
            POLICY,
            observed_at_utc="2026-07-30T15:30:00Z",
        )

        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["approval_request_status"], "DUE")
        self.assertEqual(
            result["approval_request_at_local"],
            "2026-07-30T18:30:00+03:00",
        )

    def test_friday_evening_opens_weekend_until_monday(self) -> None:
        result = resolve_run_window(
            POLICY,
            observed_at_utc="2026-07-31T16:00:00Z",
        )

        self.assertEqual(result["window_type"], "WEEKEND")
        self.assertEqual(
            result["hard_deadline_local"],
            "2026-08-03T08:00:00+03:00",
        )
        self.assertEqual(result["max_remaining_runtime_sec"], 219_600)

    def test_sunday_daytime_remains_inside_weekend_window(self) -> None:
        result = resolve_run_window(
            POLICY,
            observed_at_utc="2026-08-02T09:00:00Z",
        )

        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(result["window_type"], "WEEKEND")
        self.assertEqual(
            result["hard_deadline_local"],
            "2026-08-03T08:00:00+03:00",
        )

    def test_monday_0800_closes_weekend_window(self) -> None:
        result = resolve_run_window(
            POLICY,
            observed_at_utc="2026-08-03T05:00:00Z",
        )

        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(
            result["next_opens_at_local"],
            "2026-08-03T19:00:00+03:00",
        )

    def test_runtime_is_bounded_by_window_not_three_hours(self) -> None:
        result = validate_runtime_request(
            POLICY,
            requested_start_local="2026-07-30T19:00:00+03:00",
            expected_duration_sec=39_600,
            max_runtime_sec=46_800,
        )

        self.assertEqual(result["classification"], "LONG_CAMPAIGN")
        self.assertEqual(
            result["requested_max_end_local"],
            "2026-07-31T08:00:00+03:00",
        )

    def test_runtime_rejects_end_after_hard_deadline(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "exceeds the rolling window hard deadline",
        ):
            validate_runtime_request(
                POLICY,
                requested_start_local="2026-07-30T19:00:00+03:00",
                expected_duration_sec=46_800,
                max_runtime_sec=46_801,
            )


if __name__ == "__main__":
    unittest.main()
