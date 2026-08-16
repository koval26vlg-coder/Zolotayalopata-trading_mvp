from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_official_identity_proposal import EXPECTED_BASES  # noqa: E402
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash  # noqa: E402
from slow_liquidity_calendar_first_universe import (  # noqa: E402
    PARENT_CLOSE_PLAN_FILE_SHA256,
    PARENT_CLOSE_PLAN_HASH,
    PLAN_ID,
    UNIVERSE_PLAN_PATH,
    CalendarFirstUniverseError,
    build_calendar_first_universe_plan,
    validate_calendar_first_universe_plan,
)


class CalendarFirstUniversePlanTests(unittest.TestCase):
    def test_plan_is_method_not_ticker_list(self) -> None:
        plan = build_calendar_first_universe_plan("2026-08-16T12:40:00Z")
        validate_calendar_first_universe_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "AWAIT_EXACT_HASH_BOUND_UNIVERSE_ACCEPTANCE")
        self.assertEqual(
            plan["universe_selection"],
            "FROZEN_LOCAL_TWO_VENUE_LISTING_CALENDAR",
        )
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertEqual(plan["excluded_bases"], list(EXPECTED_BASES))
        self.assertGreater(plan["two_venue_candidate_count"], 0)
        self.assertTrue(plan["identity_before_ohlcv_collect"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["listing_first_name_discovery_reopened"])
        self.assertEqual(
            plan["parent_listing_first_close"]["plan_hash"],
            PARENT_CLOSE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_first_close"]["parent_plan_file_sha256"],
            PARENT_CLOSE_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_selecting_tickers_in_plan_is_rejected(self) -> None:
        plan = build_calendar_first_universe_plan("2026-08-16T12:40:00Z")
        plan["selected_bases"] = ["SNT"]
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstUniverseError, "tickers were invented"):
            validate_calendar_first_universe_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not UNIVERSE_PLAN_PATH.is_file():
            raise FileNotFoundError(UNIVERSE_PLAN_PATH)
        checked_in = json.loads(UNIVERSE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_calendar_first_universe_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_calendar_first_universe_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
