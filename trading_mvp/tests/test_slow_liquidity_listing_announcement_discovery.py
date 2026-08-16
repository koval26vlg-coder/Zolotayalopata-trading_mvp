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
from slow_liquidity_listing_announcement_discovery import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    GATE_INDEX_URL,
    MEXC_INDEX_URL,
    PARENT_UNIVERSE_PLAN_FILE_SHA256,
    PARENT_UNIVERSE_PLAN_HASH,
    PLAN_ID,
    ListingAnnouncementDiscoveryError,
    build_listing_announcement_discovery_plan,
    collect_listing_announcement_candidates,
    validate_listing_announcement_discovery_plan,
)


class ListingAnnouncementDiscoveryPlanTests(unittest.TestCase):
    def test_plan_uses_grounded_indexes_without_invented_tickers(self) -> None:
        plan = build_listing_announcement_discovery_plan("2026-08-16T06:40:00Z")
        validate_listing_announcement_discovery_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            [row["index_url"] for row in plan["seed_items"]],
            [MEXC_INDEX_URL, GATE_INDEX_URL],
        )
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["excluded_bases"], list(EXPECTED_BASES))
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["replay_allowed"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertEqual(
            plan["parent_listing_first_universe"]["plan_hash"],
            PARENT_UNIVERSE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_listing_first_universe"]["parent_plan_file_sha256"],
            PARENT_UNIVERSE_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertNotIn("keyword=", dumped)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_announcement_discovery_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_listing_announcement_discovery_plan(checked_in)


class ListingAnnouncementDiscoveryExecutionTests(unittest.TestCase):
    def test_extracts_article_urls_and_skips_closed_bases(self) -> None:
        plan = build_listing_announcement_discovery_plan("2026-08-16T06:40:00Z")
        pages = {
            MEXC_INDEX_URL: (
                b"<html><a href='/announcements/article/initial-listing-newcoin-xyz-1'>"
                b"NEW</a><a href='/announcements/article/steth-spot'>STETH</a></html>"
            ),
            GATE_INDEX_URL: (
                b"<html><a href='https://www.gate.com/announcements/article/99999'>"
                b"NEW</a></html>"
            ),
        }

        def fetch(url: str) -> FetchedResponse:
            return FetchedResponse(url, url, 200, pages[url])

        result = collect_listing_announcement_candidates(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertFalse(result.identity_verdict)
        self.assertEqual(result.status, "LISTING_ANNOUNCEMENT_DISCOVERY_INCOMPLETE")
        urls = {row["official_source_url"] for row in result.candidates}
        self.assertIn(
            "https://www.mexc.com/announcements/article/initial-listing-newcoin-xyz-1",
            urls,
        )
        self.assertIn("https://www.gate.com/announcements/article/99999", urls)
        self.assertTrue(all("steth" not in url.lower() for url in urls))
        self.assertEqual(result.request_count, 2)

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_listing_announcement_discovery_plan("2026-08-16T06:40:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(url)

        with self.assertRaisesRegex(ListingAnnouncementDiscoveryError, "approval text"):
            collect_listing_announcement_candidates(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
