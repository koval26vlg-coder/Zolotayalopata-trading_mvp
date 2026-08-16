from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_spot_v2_official_page_discovery import canonical_hash  # noqa: E402
from slow_liquidity_listing_first_close import (  # noqa: E402
    CLOSE_PLAN_PATH,
    PARENT_METHOD_PLAN_FILE_SHA256,
    PARENT_METHOD_PLAN_HASH,
    PLAN_ID,
    ListingFirstCloseError,
    build_listing_first_close_plan,
    validate_listing_first_close_plan,
)


class ListingFirstClosePlanTests(unittest.TestCase):
    def test_plan_awaits_close_without_invented_tickers(self) -> None:
        plan = build_listing_first_close_plan("2026-08-16T12:30:00Z")
        validate_listing_first_close_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"],
            "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE",
        )
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["new_universe_authorized"])
        self.assertFalse(plan["close_listing_first_authorized"])
        self.assertTrue(plan["listing_first_name_discovery_unreachable"])
        self.assertEqual(
            plan["parent_listing_index_method"]["plan_hash"],
            PARENT_METHOD_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_index_method"]["parent_plan_file_sha256"],
            PARENT_METHOD_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_authorizing_close_now_is_rejected(self) -> None:
        plan = build_listing_first_close_plan("2026-08-16T12:30:00Z")
        plan["close_listing_first_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(ListingFirstCloseError, "close"):
            validate_listing_first_close_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not CLOSE_PLAN_PATH.is_file():
            raise FileNotFoundError(CLOSE_PLAN_PATH)
        checked_in = json.loads(CLOSE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_first_close_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_listing_first_close_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
