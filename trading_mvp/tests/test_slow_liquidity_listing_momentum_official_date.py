from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from listing_calendar import GATE_CURRENCY_PAIRS_URL, MEXC_EXCHANGE_INFO_URL  # noqa: E402
from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
from slow_liquidity_listing_momentum_official_date import (  # noqa: E402
    DATE_PLAN_PATH,
    PARENT_SCOPE_PLAN_FILE_SHA256,
    PARENT_SCOPE_PLAN_HASH,
    PLAN_ID,
    ListingMomentumOfficialDateError,
    build_listing_momentum_official_date_plan,
    validate_listing_momentum_official_date_plan,
)


class ListingMomentumOfficialDatePlanTests(unittest.TestCase):
    def test_plan_records_unavailable_method_without_invented_url(self) -> None:
        plan = build_listing_momentum_official_date_plan("2026-08-16T17:00:00Z")
        validate_listing_momentum_official_date_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"],
            "NO_DOCUMENTED_OFFICIAL_ANNOUNCEMENT_DATE_METHOD_AWAIT_ACCEPTANCE",
        )
        self.assertEqual(
            plan["prepared_checkpoint"],
            "RECORD_OFFICIAL_DATE_METHOD_UNAVAILABLE",
        )
        self.assertFalse(plan["documented_unsigned_announcement_json_endpoint"])
        self.assertFalse(plan["public_trading_start_fields_are_official_announcement"])
        self.assertEqual(plan["first_days_sample_count"], 0)
        self.assertEqual(plan["invented_announcement_api_url_count"], 0)
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["close_listing_momentum_authorized"])
        self.assertEqual(
            plan["already_consumed_public_trading_start_fields"]["mexc"]["url"],
            MEXC_EXCHANGE_INFO_URL,
        )
        self.assertEqual(
            plan["already_consumed_public_trading_start_fields"]["gateio"]["url"],
            GATE_CURRENCY_PAIRS_URL,
        )
        self.assertEqual(
            plan["parent_listing_momentum_scope"]["plan_hash"],
            PARENT_SCOPE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_momentum_scope"]["parent_plan_file_sha256"],
            PARENT_SCOPE_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertFalse(plan["authorization_now"]["invent_announcement_url_allowed"])

    def test_claiming_trading_start_is_official_is_rejected(self) -> None:
        plan = build_listing_momentum_official_date_plan("2026-08-16T17:00:00Z")
        plan["public_trading_start_fields_are_official_announcement"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            ListingMomentumOfficialDateError,
            "official announcement",
        ):
            validate_listing_momentum_official_date_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not DATE_PLAN_PATH.is_file():
            raise FileNotFoundError(DATE_PLAN_PATH)
        checked_in = json.loads(DATE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_momentum_official_date_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_listing_momentum_official_date_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
