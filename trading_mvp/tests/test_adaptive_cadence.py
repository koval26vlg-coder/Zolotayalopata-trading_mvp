from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adaptive_cadence import (  # noqa: E402
    CONFIRMED_INTERVAL_SEC,
    SCHEDULED_INTERVAL_SEC,
    SEARCH_INTERVAL_SEC,
    SOON_INTERVAL_SEC,
    CadenceStage,
    decide_cadence,
)


class AdaptiveCadenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)

    def test_no_event_uses_six_hour_search_interval(self) -> None:
        decision = decide_cadence({}, now=self.now)
        self.assertEqual(decision.stage, CadenceStage.SEARCH)
        self.assertEqual(decision.interval_sec, SEARCH_INTERVAL_SEC)

    def test_candidate_within_three_days_uses_three_hour_interval(self) -> None:
        decision = decide_cadence(
            {"event_eta_utc": (self.now + timedelta(hours=48)).isoformat(), "candidate": True},
            now=self.now,
        )
        self.assertEqual(decision.stage, CadenceStage.SOON)
        self.assertEqual(decision.interval_sec, SOON_INTERVAL_SEC)

    def test_official_confirmation_uses_one_hour_interval(self) -> None:
        decision = decide_cadence(
            {"official_confirmed": True, "event_eta_utc": (self.now + timedelta(days=7)).isoformat()},
            now=self.now,
        )
        self.assertEqual(decision.stage, CadenceStage.CONFIRMED)
        self.assertEqual(decision.interval_sec, CONFIRMED_INTERVAL_SEC)

    def test_exact_official_time_within_one_day_uses_five_minute_interval(self) -> None:
        decision = decide_cadence(
            {
                "official_confirmed": True,
                "exact_timestamp": True,
                "event_eta_utc": (self.now + timedelta(hours=6)).isoformat(),
            },
            now=self.now,
        )
        self.assertEqual(decision.stage, CadenceStage.SCHEDULED)
        self.assertEqual(decision.interval_sec, SCHEDULED_INTERVAL_SEC)

    def test_far_future_exact_time_does_not_use_five_minute_interval(self) -> None:
        decision = decide_cadence(
            {
                "official_confirmed": True,
                "exact_timestamp": True,
                "event_eta_utc": (self.now + timedelta(days=7)).isoformat(),
            },
            now=self.now,
        )
        self.assertEqual(decision.stage, CadenceStage.CONFIRMED)
        self.assertEqual(decision.interval_sec, CONFIRMED_INTERVAL_SEC)

    def test_proxy_without_eta_cannot_escalate_to_confirmed(self) -> None:
        decision = decide_cadence(
            {"source_class": "proxy", "proxy_timestamp": True, "candidate": True}, now=self.now
        )
        self.assertEqual(decision.stage, CadenceStage.SOON)
        self.assertEqual(decision.interval_sec, SOON_INTERVAL_SEC)

    def test_cancelled_or_expired_event_returns_to_search(self) -> None:
        for status in ("cancelled", "expired", "delisted"):
            decision = decide_cadence(
                {"lifecycle_status": status, "official_confirmed": True, "exact_timestamp": True},
                now=self.now,
            )
            self.assertEqual(decision.stage, CadenceStage.SEARCH)
            self.assertEqual(decision.interval_sec, SEARCH_INTERVAL_SEC)


if __name__ == "__main__":
    unittest.main()
