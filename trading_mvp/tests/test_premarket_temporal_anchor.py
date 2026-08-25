"""A cadence decision must know which moment it waits for, and not overstate its evidence.

Measured 2026-08-24 on the live state files, both tracks reported:

    cadence_stage          CONFIRMED
    event_eta_utc          2025-09-01T13:30:00Z   (crypto)
    event_eta_utc          2026-05-07T09:15:00Z   (pre-IPO)
    official_confirmation  True

Both anchors were in the past - one by nearly a year - and both tracks were still
holding the hourly CONFIRMED cadence and asserting official confirmation. Three separate
defects produced that, and each has a test here:

  1. decide_cadence had no time check on the CONFIRMED branch at all, so once
     official_confirmed was set the hourly cadence held forever;
  2. the anchor was chosen by sorting every dated row ascending and taking the first,
     under the name "upcoming" but without ever testing that it was upcoming - which on
     a set containing past events picks the stalest one, permanently;
  3. official_confirmed and exact_timestamp were any() over the whole batch, so one
     contract's official source was attached to another contract's timestamp.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from adaptive_cadence import (  # noqa: E402
    CONFIRMED_INTERVAL_SEC,
    EVENT_SPENT_AFTER_SEC,
    SEARCH_INTERVAL_SEC,
    CadenceStage,
    decide_cadence,
)
from premarket_temporal_anchor import (  # noqa: E402
    ANCHOR_CONTRACT_LAUNCH,
    ANCHOR_OFFICIAL_SPOT_T0,
    ANCHOR_TRANSITION,
    anchor_observation,
    resolve_anchor,
    select_cadence_anchor,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class AnchorKindTests(unittest.TestCase):
    def test_a_transition_from_an_official_source_is_not_an_official_time(self):
        # preMktSwTime read from an officially-sourced record. The record is official;
        # the timestamp is a transition. Conflating the two is the original defect.
        anchor = resolve_anchor({ANCHOR_TRANSITION: 1.0}, source_class="official")
        self.assertEqual(anchor.kind, ANCHOR_TRANSITION)
        self.assertFalse(anchor.is_official_time)
        self.assertTrue(anchor.is_proxy)

    def test_a_contract_launch_from_an_official_source_is_not_an_official_time(self):
        anchor = resolve_anchor({ANCHOR_CONTRACT_LAUNCH: 1.0}, source_class="official")
        self.assertFalse(anchor.is_official_time)

    def test_only_an_announced_spot_t0_carries_an_official_exact_time(self):
        anchor = resolve_anchor(
            {ANCHOR_OFFICIAL_SPOT_T0: 1.0},
            source_classes={ANCHOR_OFFICIAL_SPOT_T0: "official"},
        )
        self.assertTrue(anchor.is_official_time)
        self.assertFalse(anchor.is_proxy)

    def test_record_wide_official_metadata_cannot_certify_a_spot_t0(self):
        anchor = resolve_anchor(
            {ANCHOR_OFFICIAL_SPOT_T0: 1.0},
            source_class="official",
        )
        self.assertFalse(anchor.is_official_time)

    def test_an_unofficial_source_cannot_carry_an_official_time_even_for_a_spot_t0(self):
        anchor = resolve_anchor({ANCHOR_OFFICIAL_SPOT_T0: 1.0}, source_class="venue_metadata")
        self.assertFalse(anchor.is_official_time)

    def test_the_most_direct_available_kind_wins(self):
        anchor = resolve_anchor(
            {
                ANCHOR_OFFICIAL_SPOT_T0: 300.0,
                ANCHOR_TRANSITION: 200.0,
                ANCHOR_CONTRACT_LAUNCH: 100.0,
            },
            source_classes={ANCHOR_OFFICIAL_SPOT_T0: "official"},
        )
        self.assertEqual(anchor.kind, ANCHOR_OFFICIAL_SPOT_T0)
        self.assertEqual(anchor.ts, 300.0)

    def test_a_contract_with_no_timestamps_yields_no_anchor(self):
        self.assertIsNone(resolve_anchor({}, source_class="official"))
        observation = anchor_observation(None)
        self.assertFalse(observation["official_confirmed"])
        self.assertFalse(observation["exact_timestamp"])
        self.assertIsNone(observation["event_anchor_kind"])

    def test_the_kind_is_carried_into_the_observation(self):
        # Without this, nothing downstream can tell what event_eta_utc means.
        observation = anchor_observation(
            resolve_anchor({ANCHOR_TRANSITION: 5.0}, source_class="official")
        )
        self.assertEqual(observation["event_anchor_kind"], ANCHOR_TRANSITION)
        self.assertTrue(observation["proxy_timestamp"])


class AnchorSelectionTests(unittest.TestCase):
    def _row(self, ts, **kw):
        row = {"lifecycle_status": "continuous", "event_anchor_ts": ts}
        row.update(kw)
        return row

    def test_a_future_anchor_is_preferred_over_an_earlier_past_one(self):
        # The exact shape that pinned the live tracks: sorting ascending and taking the
        # first would return the 2025 row here, forever.
        past = self._row(NOW.timestamp() - 365 * 86400)
        future = self._row(NOW.timestamp() + 3600)
        chosen = select_cadence_anchor([past, future], now_ts=NOW.timestamp())
        self.assertIs(chosen, future)

    def test_the_earliest_future_anchor_wins_among_several(self):
        near = self._row(NOW.timestamp() + 3600)
        far = self._row(NOW.timestamp() + 30 * 86400)
        chosen = select_cadence_anchor([far, near], now_ts=NOW.timestamp())
        self.assertIs(chosen, near)

    def test_with_nothing_ahead_the_freshest_past_anchor_is_reported(self):
        old = self._row(NOW.timestamp() - 365 * 86400)
        recent = self._row(NOW.timestamp() - 86400)
        chosen = select_cadence_anchor([old, recent], now_ts=NOW.timestamp())
        self.assertIs(chosen, recent)

    def test_terminal_contracts_are_never_chosen_as_the_anchor(self):
        dead = self._row(NOW.timestamp() + 60, lifecycle_status="delisted")
        live = self._row(NOW.timestamp() + 3600)
        chosen = select_cadence_anchor([dead, live], now_ts=NOW.timestamp())
        self.assertIs(chosen, live)

    def test_an_undated_live_contract_is_still_reported_as_a_candidate(self):
        undated = self._row(None)
        chosen = select_cadence_anchor([undated], now_ts=NOW.timestamp())
        self.assertIs(chosen, undated)

    def test_no_contracts_yields_no_anchor(self):
        self.assertIsNone(select_cadence_anchor([], now_ts=NOW.timestamp()))


class ConfirmationIsNotSmearedTests(unittest.TestCase):
    """One contract's official source must not confirm another contract's timestamp."""

    def test_confirmation_travels_with_the_anchor_not_with_the_batch(self):
        official_but_undated = {
            "lifecycle_status": "continuous",
            "event_anchor_ts": None,
            **anchor_observation(
                resolve_anchor({ANCHOR_OFFICIAL_SPOT_T0: None}, source_class="official")
            ),
        }
        dated_but_proxy = {
            "lifecycle_status": "continuous",
            "event_anchor_ts": NOW.timestamp() + 3600,
            **anchor_observation(
                resolve_anchor({ANCHOR_TRANSITION: NOW.timestamp() + 3600}, source_class="venue_metadata")
            ),
        }
        chosen = select_cadence_anchor(
            [official_but_undated, dated_but_proxy], now_ts=NOW.timestamp()
        )
        self.assertIs(chosen, dated_but_proxy)
        # The old any() would have reported True here off the other row.
        self.assertFalse(chosen["official_confirmed"])
        self.assertFalse(chosen["exact_timestamp"])

    def test_a_proxy_anchor_cannot_reach_the_confirmed_cadence(self):
        # This is the policy that was always correct and merely fed bad inputs.
        observation = {
            **anchor_observation(
                resolve_anchor({ANCHOR_TRANSITION: (NOW + timedelta(hours=6)).timestamp()},
                               source_class="official")
            ),
            "event_eta_utc": _iso(NOW + timedelta(hours=6)),
            "contract_present": True,
        }
        decision = decide_cadence(observation, now=NOW)
        self.assertNotEqual(decision.stage, CadenceStage.CONFIRMED)
        self.assertNotEqual(decision.stage, CadenceStage.SCHEDULED)


class SpentAnchorTests(unittest.TestCase):
    """A confirmed event that has already happened is not an upcoming event."""

    def test_the_observed_crypto_anchor_no_longer_holds_the_hourly_cadence(self):
        decision = decide_cadence(
            {"official_confirmed": True, "event_eta_utc": "2025-09-01T13:30:00Z"}, now=NOW
        )
        self.assertEqual(decision.stage, CadenceStage.SEARCH)
        self.assertEqual(decision.interval_sec, SEARCH_INTERVAL_SEC)
        self.assertEqual(decision.reason, "anchor_event_already_passed")

    def test_the_observed_preipo_anchor_no_longer_holds_the_hourly_cadence(self):
        decision = decide_cadence(
            {"official_confirmed": True, "event_eta_utc": "2026-05-07T09:15:00Z"}, now=NOW
        )
        self.assertEqual(decision.stage, CadenceStage.SEARCH)
        self.assertEqual(decision.reason, "anchor_event_already_passed")

    def test_a_spent_anchor_is_not_carried_forward_as_the_eta(self):
        # Reporting a stale eta alongside a SEARCH decision would keep the phantom
        # visible in the state file and in every manifest downstream of it.
        decision = decide_cadence(
            {"official_confirmed": True, "event_eta_utc": "2025-09-01T13:30:00Z"}, now=NOW
        )
        self.assertIsNone(decision.event_eta_utc)

    def test_a_just_passed_event_is_still_watched(self):
        # The window exists so that an event under observation is not dropped the
        # instant it starts. Retiring it at t0 would end collection exactly at t0.
        recent = NOW - timedelta(seconds=EVENT_SPENT_AFTER_SEC // 2)
        decision = decide_cadence(
            {"official_confirmed": True, "event_eta_utc": _iso(recent)}, now=NOW
        )
        self.assertEqual(decision.stage, CadenceStage.CONFIRMED)
        self.assertEqual(decision.interval_sec, CONFIRMED_INTERVAL_SEC)

    def test_an_upcoming_confirmed_event_is_unaffected(self):
        decision = decide_cadence(
            {"official_confirmed": True, "event_eta_utc": _iso(NOW + timedelta(days=2))},
            now=NOW,
        )
        self.assertEqual(decision.stage, CadenceStage.CONFIRMED)

    def test_a_spent_anchor_beats_confirmation_but_not_a_terminal_lifecycle(self):
        decision = decide_cadence(
            {
                "official_confirmed": True,
                "event_eta_utc": "2025-09-01T13:30:00Z",
                "lifecycle_status": "delisted",
            },
            now=NOW,
        )
        self.assertEqual(decision.stage, CadenceStage.SEARCH)
        self.assertEqual(decision.reason, "terminal_lifecycle:delisted")


if __name__ == "__main__":
    unittest.main()
