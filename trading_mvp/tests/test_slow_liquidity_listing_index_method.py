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
from slow_liquidity_listing_index_method import (  # noqa: E402
    METHOD_PLAN_PATH,
    PARENT_GAP_PLAN_FILE_SHA256,
    PARENT_GAP_PLAN_HASH,
    PLAN_ID,
    ListingIndexMethodError,
    build_listing_index_method_plan,
    validate_listing_index_method_plan,
)


class ListingIndexMethodPlanTests(unittest.TestCase):
    def test_plan_has_no_invented_index_or_ticker(self) -> None:
        plan = build_listing_index_method_plan("2026-08-16T07:50:00Z")
        validate_listing_index_method_plan(plan)
        dumped = json.dumps(plan, ensure_ascii=False)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"],
            "NO_GROUNDED_SECOND_LISTING_INDEX_AWAIT_UNIVERSE_OR_CLOSE",
        )
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertEqual(plan["invented_index_url_count"], 0)
        self.assertEqual(plan["seed_items"], [])
        self.assertEqual(plan["excluded_bases"], list(EXPECTED_BASES))
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["close_listing_first_authorized"])
        self.assertFalse(plan["new_universe_authorized"])
        self.assertEqual(
            plan["parent_listing_announcement_gap"]["plan_hash"],
            PARENT_GAP_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_announcement_gap"]["parent_plan_file_sha256"],
            PARENT_GAP_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertNotIn("keyword=", dumped)

    def test_invented_index_url_is_rejected(self) -> None:
        plan = build_listing_index_method_plan("2026-08-16T07:50:00Z")
        plan["seed_items"] = [
            {"index_url": "https://www.mexc.com/announcements/new-listings"}
        ]
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(ListingIndexMethodError, "invented index"):
            validate_listing_index_method_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not METHOD_PLAN_PATH.is_file():
            raise FileNotFoundError(METHOD_PLAN_PATH)
        checked_in = json.loads(METHOD_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_index_method_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_listing_index_method_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
