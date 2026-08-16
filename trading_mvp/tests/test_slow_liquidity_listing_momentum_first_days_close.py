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
from slow_liquidity_listing_momentum_first_days_close import (  # noqa: E402
    CLOSE_PLAN_PATH,
    PARENT_DATE_PLAN_FILE_SHA256,
    PARENT_DATE_PLAN_HASH,
    PARENT_SCOPE_PLAN_FILE_SHA256,
    PARENT_SCOPE_PLAN_HASH,
    PLAN_ID,
    ListingMomentumFirstDaysCloseError,
    build_listing_momentum_first_days_close_plan,
    fill_expected_approval_text,
    validate_listing_momentum_first_days_close_plan,
)


class ListingMomentumFirstDaysClosePlanTests(unittest.TestCase):
    def test_plan_awaits_close_without_ohlcv_or_invented_url(self) -> None:
        plan = build_listing_momentum_first_days_close_plan("2026-08-16T17:20:00Z")
        validate_listing_momentum_first_days_close_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE")
        self.assertEqual(
            plan["prepared_checkpoint"],
            "CLOSE_LISTING_MOMENTUM_FIRST_DAYS_AS_INCOMPLETE",
        )
        self.assertTrue(plan["documented_official_date_method_unavailable"])
        self.assertFalse(plan["user_supplied_grounded_official_date_method"])
        self.assertFalse(plan["listing_momentum_first_days_complete"])
        self.assertFalse(plan["close_listing_momentum_authorized"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertEqual(plan["first_days_sample_count"], 0)
        self.assertEqual(
            plan["parent_listing_momentum_scope"]["plan_hash"],
            PARENT_SCOPE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_momentum_scope"]["parent_plan_file_sha256"],
            PARENT_SCOPE_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            plan["parent_official_date_method"]["plan_hash"],
            PARENT_DATE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_official_date_method"]["parent_plan_file_sha256"],
            PARENT_DATE_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertFalse(plan["authorization_now"]["close_listing_momentum_allowed"])

    def test_authorizing_close_now_is_rejected(self) -> None:
        plan = build_listing_momentum_first_days_close_plan("2026-08-16T17:20:00Z")
        plan["close_listing_momentum_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(ListingMomentumFirstDaysCloseError, "close"):
            validate_listing_momentum_first_days_close_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not CLOSE_PLAN_PATH.is_file():
            raise FileNotFoundError(CLOSE_PLAN_PATH)
        checked_in = json.loads(CLOSE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_momentum_first_days_close_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_listing_momentum_first_days_close_plan(checked_in)

    def test_accepted_receipt_closes_first_days_only(self) -> None:
        receipt_path = (
            ROOT
            / "docs"
            / "agent-log"
            / "approvals"
            / "2026-08-16-slow-liquidity-listing-momentum-first-days-close-approval.json"
        )
        if not receipt_path.is_file():
            raise FileNotFoundError(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        plan = json.loads(CLOSE_PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["status"],
            "LISTING_MOMENTUM_FIRST_DAYS_CLOSED_AS_INCOMPLETE",
        )
        self.assertEqual(receipt["plan_hash"], plan["plan_hash"])
        self.assertEqual(
            receipt["user_approval_text"],
            fill_expected_approval_text(
                receipt["plan_hash"],
                receipt["plan_file_sha256"],
            ),
        )
        self.assertTrue(receipt["listing_momentum_first_days_closed_as_incomplete"])
        self.assertFalse(receipt["listing_momentum_first_days_complete"])
        self.assertTrue(receipt["documented_official_date_method_unavailable"])
        self.assertFalse(receipt["ohlcv_collect_authorized"])
        self.assertFalse(receipt["network_authorized"])
        self.assertFalse(receipt["authorized_scope"]["ohlcv_collect"])
        self.assertTrue(
            receipt["authorized_scope"][
                "close_listing_momentum_first_days_as_incomplete"
            ]
        )


if __name__ == "__main__":
    unittest.main()
