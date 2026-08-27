from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_listing_expansion_child_evidence import ChildEvidenceFixture  # noqa: E402


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class LedgerRecordingTimeTests(unittest.TestCase):
    """The ledger row is written after the manifest, and that is not a contradiction.

    The child writes the terminal manifest, rebuilds its state, and only then appends the
    ledger row, stamping it with a fresh clock reading. The first real activated tick left
    a three-second gap and was refused, because the rule demanded the two timestamps be
    identical. They mean different things: the manifest records when the tick finished,
    the ledger records when the attempt was recorded. Ordering is the honest relation.

    Every offset below is computed from the fixture rather than written as a literal. My
    first version of this test assumed a time the fixture does not use, so its string
    substitutions silently did nothing and it passed on values it never actually changed.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="child-evidence-timing-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = ChildEvidenceFixture(Path(self.temporary.name))
        self.fixture.write()
        self.manifest_finished = moment(self.fixture.manifest["finished_at_utc"])
        self.window_end = moment(self.fixture.finished)

    def recorded_at(self, value: str) -> dict:
        row = self.fixture.ledger_row()
        row["finished_at_utc"] = value
        self.fixture.ledger_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return self.fixture.call()

    def test_a_ledger_recorded_after_the_manifest_is_accepted(self) -> None:
        self.assertLess(self.manifest_finished, self.window_end, "fixture leaves no gap")
        later = self.manifest_finished + timedelta(seconds=1)
        self.assertLessEqual(later, self.window_end)
        result = self.recorded_at(stamp(later))
        self.assertEqual("COMPLETE", result["status"], result.get("reason"))

    def test_a_ledger_recorded_at_the_same_moment_is_still_accepted(self) -> None:
        result = self.recorded_at(self.fixture.manifest["finished_at_utc"])
        self.assertEqual("COMPLETE", result["status"], result.get("reason"))

    def test_a_ledger_recorded_before_the_manifest_finished_is_refused(self) -> None:
        # A record cannot predate the thing it records.
        earlier = self.manifest_finished - timedelta(seconds=1)
        result = self.recorded_at(stamp(earlier))
        self.assertEqual("RETRY_NEXT_INTERVAL", result["status"])
        self.assertIn("before the tick finished", result["reason"])

    def test_a_ledger_recorded_past_the_launch_window_is_refused(self) -> None:
        beyond = self.window_end + timedelta(hours=1)
        result = self.recorded_at(stamp(beyond))
        self.assertEqual("RETRY_NEXT_INTERVAL", result["status"])
        self.assertIn("outside the launch window", result["reason"])

    def test_the_started_timestamps_must_still_agree(self) -> None:
        # Both come from one value in the child, so a difference here is a real
        # contradiction rather than two clocks read at two moments.
        row = self.fixture.ledger_row()
        row["started_at_utc"] = stamp(moment(row["started_at_utc"]) + timedelta(seconds=1))
        self.fixture.ledger_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        result = self.fixture.call()
        self.assertEqual("RETRY_NEXT_INTERVAL", result["status"])
        self.assertIn("started_at_utc", result["reason"])

    def test_an_unreadable_ledger_timestamp_is_refused(self) -> None:
        for value in ("", "not a timestamp", "2026-08-26T01:00:04"):
            with self.subTest(value=value):
                self.assertEqual(
                    "RETRY_NEXT_INTERVAL", self.recorded_at(value)["status"]
                )


if __name__ == "__main__":
    unittest.main()
