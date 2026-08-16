from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
from slow_liquidity_listing_momentum_scope import (  # noqa: E402
    EXPECTED_AGE_BUCKETS,
    EXPECTED_TWO_VENUE_COUNT,
    PARENT_CLOSE_PLAN_FILE_SHA256,
    PARENT_CLOSE_PLAN_HASH,
    PLAN_ID,
    SCOPE_PLAN_PATH,
    V6_OK_ROWS,
    ListingMomentumScopeError,
    build_listing_momentum_scope_plan,
    census_listing_momentum_calendar,
    fill_expected_approval_text,
    validate_listing_momentum_scope_plan,
)
from slow_liquidity_calendar_first_universe import CALENDAR_PATH  # noqa: E402


class ListingMomentumScopePlanTests(unittest.TestCase):
    def test_census_has_empty_first_days_sample(self) -> None:
        census = census_listing_momentum_calendar(CALENDAR_PATH)
        self.assertEqual(census["two_venue_base_count"], EXPECTED_TWO_VENUE_COUNT)
        self.assertEqual(census["first_days_sample_count"], 0)
        self.assertEqual(census["official_announcement_row_count"], 0)
        self.assertEqual(census["age_buckets_as_of"], EXPECTED_AGE_BUCKETS)
        self.assertEqual(
            census["calendar_source_class"],
            "PUBLIC_API_CURRENT_SNAPSHOT_NOT_OFFICIAL_ANNOUNCEMENT",
        )

    def test_plan_remaps_away_from_v6_postprocess(self) -> None:
        plan = build_listing_momentum_scope_plan("2026-08-16T16:20:00Z")
        validate_listing_momentum_scope_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "AWAIT_EXACT_HASH_BOUND_SCOPE_ACCEPTANCE")
        self.assertEqual(
            plan["prepared_checkpoint"],
            "REMAP_LISTING_MOMENTUM_NOT_V6_POSTPROCESS",
        )
        self.assertEqual(plan["selected_base_count"], EXPECTED_TWO_VENUE_COUNT)
        self.assertEqual(plan["v6_trailing_history"]["ok_rows"], V6_OK_ROWS)
        self.assertFalse(plan["dashboard_claim"]["matches_listing_momentum"])
        self.assertFalse(plan["v6_trailing_history"]["usable_as_listing_momentum"])
        self.assertFalse(plan["v6_postprocess_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["replay_allowed"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["closed_nine_reopened"])
        self.assertEqual(plan["calendar_census"]["first_days_sample_count"], 0)
        self.assertEqual(
            plan["parent_calendar_first_identity_close"]["plan_hash"],
            PARENT_CLOSE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_calendar_first_identity_close"]["parent_plan_file_sha256"],
            PARENT_CLOSE_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertFalse(plan["authorization_now"]["v6_postprocess_allowed"])

    def test_authorizing_v6_postprocess_now_is_rejected(self) -> None:
        plan = build_listing_momentum_scope_plan("2026-08-16T16:20:00Z")
        plan["v6_postprocess_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(ListingMomentumScopeError, "v6 postprocess"):
            validate_listing_momentum_scope_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not SCOPE_PLAN_PATH.is_file():
            raise FileNotFoundError(SCOPE_PLAN_PATH)
        checked_in = json.loads(SCOPE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_momentum_scope_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_listing_momentum_scope_plan(checked_in)

    def test_accepted_receipt_rejects_v6_postprocess(self) -> None:
        receipt_path = (
            ROOT
            / "docs"
            / "agent-log"
            / "approvals"
            / "2026-08-16-slow-liquidity-listing-momentum-scope-approval.json"
        )
        if not receipt_path.is_file():
            raise FileNotFoundError(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        plan = json.loads(SCOPE_PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["status"],
            "ACCEPTED_LISTING_MOMENTUM_SCOPE_NOT_V6_POSTPROCESS",
        )
        self.assertEqual(receipt["plan_hash"], plan["plan_hash"])
        self.assertEqual(
            receipt["user_approval_text"],
            fill_expected_approval_text(
                receipt["plan_hash"],
                receipt["plan_file_sha256"],
            ),
        )
        self.assertEqual(receipt["first_days_sample_count"], 0)
        self.assertFalse(receipt["v6_usable_as_listing_momentum"])
        self.assertFalse(receipt["v6_postprocess_authorized"])
        self.assertFalse(receipt["ohlcv_collect_authorized"])
        self.assertFalse(receipt["network_authorized"])
        self.assertFalse(receipt["replay_allowed"])
        self.assertFalse(receipt["authorized_scope"]["treat_v6_as_listing_momentum"])
        self.assertFalse(receipt["authorized_scope"]["ohlcv_collect"])


if __name__ == "__main__":
    unittest.main()
