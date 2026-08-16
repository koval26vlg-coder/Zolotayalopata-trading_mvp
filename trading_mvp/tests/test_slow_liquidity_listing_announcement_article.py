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
from slow_liquidity_official_identity_verification import FetchedResponse  # noqa: E402
from slow_liquidity_listing_announcement_article import (  # noqa: E402
    ARTICLE_PLAN_PATH,
    ARTICLE_URL,
    EXPECTED_APPROVAL_TEXT,
    PARENT_CANDIDATES_SHA256,
    PARENT_DISCOVERY_PLAN_FILE_SHA256,
    PARENT_DISCOVERY_PLAN_HASH,
    PLAN_ID,
    ListingAnnouncementArticleError,
    build_listing_announcement_article_plan,
    classify_listing_slug,
    extract_base_from_listing_slug,
    fetch_listing_announcement_article,
    validate_listing_announcement_article_plan,
)


class ListingAnnouncementArticlePlanTests(unittest.TestCase):
    def test_plan_binds_frozen_candidate_without_invented_tickers(self) -> None:
        plan = build_listing_announcement_article_plan("2026-08-16T07:20:00Z")
        validate_listing_announcement_article_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["seed_items"][0]["official_source_url"], ARTICLE_URL)
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["extracted_bases"], [])
        self.assertEqual(plan["excluded_bases"], list(EXPECTED_BASES))
        self.assertFalse(plan["listing_slug_match"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["replay_allowed"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertEqual(
            plan["parent_listing_announcement_discovery"]["plan_hash"],
            PARENT_DISCOVERY_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_announcement_discovery"]["parent_plan_file_sha256"],
            PARENT_DISCOVERY_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            plan["parent_listing_announcement_discovery"]["candidates_sha256"],
            PARENT_CANDIDATES_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertNotIn("keyword=", dumped)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not ARTICLE_PLAN_PATH.is_file():
            raise FileNotFoundError(ARTICLE_PLAN_PATH)
        checked_in = json.loads(ARTICLE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_announcement_article_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_listing_announcement_article_plan(checked_in)


class ListingAnnouncementArticleSlugTests(unittest.TestCase):
    def test_first_in_market_slug_is_not_a_listing_ticker(self) -> None:
        self.assertFalse(classify_listing_slug(ARTICLE_URL))
        self.assertIsNone(extract_base_from_listing_slug(ARTICLE_URL))

    def test_grounded_will_list_slug_extracts_base_only(self) -> None:
        url = (
            "https://www.mexc.com/announcements/article/"
            "initial-listing-mexc-will-list-akedo-ake-in-innovation-zone-17827791529373"
        )
        self.assertTrue(classify_listing_slug(url))
        self.assertEqual(extract_base_from_listing_slug(url), "AKE")


class ListingAnnouncementArticleExecutionTests(unittest.TestCase):
    def test_fetch_records_title_and_does_not_invent_ticker(self) -> None:
        plan = build_listing_announcement_article_plan("2026-08-16T07:20:00Z")

        def fetch(url: str) -> FetchedResponse:
            self.assertEqual(url, ARTICLE_URL)
            return FetchedResponse(
                url,
                url,
                200,
                b"<html><title>First in Market</title></html>",
            )

        result = fetch_listing_announcement_article(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertFalse(result.identity_verdict)
        self.assertEqual(result.status, "LISTING_ANNOUNCEMENT_ARTICLE_INCOMPLETE")
        self.assertEqual(result.extracted_bases, ())
        self.assertEqual(result.selected_bases, ())
        self.assertEqual(result.request_count, 1)
        self.assertEqual(result.title, "First in Market")
        self.assertFalse(result.listing_slug_match)

    def test_closed_base_in_slug_is_not_selected(self) -> None:
        self.assertIsNone(
            extract_base_from_listing_slug(
                "https://www.mexc.com/announcements/article/"
                "initial-listing-mexc-will-list-lido-steth-spot-1"
            )
        )

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_listing_announcement_article_plan("2026-08-16T07:20:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(url)

        with self.assertRaisesRegex(ListingAnnouncementArticleError, "approval text"):
            fetch_listing_announcement_article(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
