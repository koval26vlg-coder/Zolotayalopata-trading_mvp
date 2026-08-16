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
from slow_liquidity_listing_announcement_article import ARTICLE_URL  # noqa: E402
from slow_liquidity_listing_announcement_gap import (  # noqa: E402
    GAP_PLAN_PATH,
    PARENT_ARTICLE_PLAN_FILE_SHA256,
    PARENT_ARTICLE_PLAN_HASH,
    PARENT_ARTICLE_RECORD_SHA256,
    PLAN_ID,
    ListingAnnouncementGapError,
    build_listing_announcement_gap_plan,
    validate_listing_announcement_gap_plan,
)


class ListingAnnouncementGapPlanTests(unittest.TestCase):
    def test_plan_is_offline_gap_without_invented_tickers(self) -> None:
        plan = build_listing_announcement_gap_plan("2026-08-16T07:40:00Z")
        validate_listing_announcement_gap_plan(plan)
        dumped = json.dumps(plan, ensure_ascii=False)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"],
            "LISTING_ANNOUNCEMENT_PATH_INCOMPLETE_AWAIT_RESCOPE_OR_CLOSE",
        )
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["extracted_bases"], [])
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertEqual(plan["excluded_bases"], list(EXPECTED_BASES))
        self.assertFalse(plan["listing_slug_match"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertTrue(plan["parent_retry_forbidden"])
        self.assertEqual(plan["official_source_url"], ARTICLE_URL)
        self.assertEqual(
            plan["parent_listing_announcement_article"]["plan_hash"],
            PARENT_ARTICLE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_announcement_article"]["parent_plan_file_sha256"],
            PARENT_ARTICLE_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            plan["parent_listing_announcement_article"]["record_sha256"],
            PARENT_ARTICLE_RECORD_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertNotRegex(dumped, r'"selected_bases": \["')

    def test_invented_ticker_is_rejected(self) -> None:
        plan = build_listing_announcement_gap_plan("2026-08-16T07:40:00Z")
        plan["selected_bases"] = ["NIU"]
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(ListingAnnouncementGapError, "tickers were invented"):
            validate_listing_announcement_gap_plan(plan)

    def test_authorizing_identity_or_consumer_reuse_is_rejected(self) -> None:
        plan = build_listing_announcement_gap_plan("2026-08-16T07:40:00Z")
        plan["spot_v2_runtime_reuse"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(ListingAnnouncementGapError, "spot v2"):
            validate_listing_announcement_gap_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not GAP_PLAN_PATH.is_file():
            raise FileNotFoundError(GAP_PLAN_PATH)
        checked_in = json.loads(GAP_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_announcement_gap_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_listing_announcement_gap_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
