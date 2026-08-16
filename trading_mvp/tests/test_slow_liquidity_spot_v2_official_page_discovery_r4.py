from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_official_identity_proposal import (  # noqa: E402
    EXPECTED_BASES,
    EXPECTED_VENUES,
    collected_spot_instrument,
)
from slow_liquidity_official_identity_verification import FetchedResponse  # noqa: E402
from slow_liquidity_spot_v2_official_page_discovery_r4 import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    GATE_ANNOUNCEMENT_SITEMAP,
    GATE_GOOGLE_NEWS_SITEMAP,
    MEXC_NEWS_SITEMAP_INDEX,
    PARENT_R3_PLAN_FILE_SHA256,
    PLAN_ID,
    SpotV2OfficialPageDiscoveryR4Error,
    build_spot_v2_official_page_discovery_plan_r4,
    discover_spot_v2_official_pages_r4,
    validate_spot_v2_official_page_discovery_plan_r4,
)


def _identifier_for(base: str) -> str:
    return "0x" + f"{abs(hash(base)) % (16**8):08x}" + "d" * 32


def _official_url(venue: str, base: str) -> str:
    if venue == "mexc":
        return f"https://www.mexc.com/support/articles/{base.lower()}-spot-r4"
    return f"https://www.gate.com/announcements/article/{base.lower()}-spot-r4"


def _mexc_one(instrument: str) -> bytes:
    return json.dumps(
        {
            "symbols": [
                {
                    "symbol": instrument,
                    "baseAsset": instrument.removesuffix("USDT"),
                    "quoteAsset": "USDT",
                    "status": "1",
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def _gate_one(instrument: str) -> bytes:
    return json.dumps(
        {
            "id": instrument,
            "base": instrument.removesuffix("_USDT"),
            "quote": "USDT",
            "trade_status": "tradable",
        },
        separators=(",", ":"),
    ).encode()


def _titled_sitemap() -> bytes:
    items = []
    for venue in EXPECTED_VENUES:
        for base in EXPECTED_BASES:
            url = _official_url(venue, base)
            items.append(
                "<url>"
                f"<loc>{url}</loc>"
                f"<news:title>{base} listing notice</news:title>"
                "</url>"
            )
    return (
        '<?xml version="1.0"?>'
        '<urlset xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
        + "".join(items)
        + "</urlset>"
    ).encode()


def _numeric_sitemap() -> bytes:
    return (
        b'<?xml version="1.0"?><urlset>'
        b"<url><loc>https://www.gate.com/announcements/article/21688</loc></url>"
        b"</urlset>"
    )


def _page(base: str, instrument: str) -> bytes:
    return (
        f"<html><body>{base} {instrument} Contract Address {_identifier_for(base)}</body></html>"
    ).encode()


class SpotV2OfficialPageDiscoveryR4PlanTests(unittest.TestCase):
    def test_plan_uses_news_title_sitemaps_not_bing_or_r3_search(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r4("2026-08-15T19:35:00Z")
        validate_spot_v2_official_page_discovery_plan_r4(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(
            plan["navigation_contract"]["provider"],
            "OFFICIAL_NEWS_SITEMAP_TITLE_AND_SLUG",
        )
        self.assertEqual(
            plan["navigation_contract"]["mexc_news_sitemap_index"],
            MEXC_NEWS_SITEMAP_INDEX,
        )
        self.assertEqual(
            plan["navigation_contract"]["gate_google_news_sitemap"],
            GATE_GOOGLE_NEWS_SITEMAP,
        )
        self.assertEqual(
            plan["navigation_contract"]["gate_announcement_sitemap"],
            GATE_ANNOUNCEMENT_SITEMAP,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("announcements?keyword=", dumped)
        self.assertTrue(plan["parent_discovery"]["retry_of_parent_forbidden"])
        self.assertEqual(
            plan["parent_discovery"]["parent_plan_file_sha256"],
            PARENT_R3_PLAN_FILE_SHA256,
        )
        self.assertFalse(plan["identity_evidence"])
        self.assertFalse(plan["network_authorized"])
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_official_page_discovery_plan_r4(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_spot_v2_official_page_discovery_plan_r4(checked_in)


class SpotV2OfficialPageDiscoveryR4ExecutionTests(unittest.TestCase):
    def test_news_title_binds_unique_official_page(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r4("2026-08-15T19:35:00Z")

        def fetch(url: str) -> FetchedResponse:
            if url == MEXC_NEWS_SITEMAP_INDEX:
                return FetchedResponse(
                    url,
                    url,
                    200,
                    b'<?xml version="1.0"?><sitemapindex></sitemapindex>',
                )
            if url in {GATE_GOOGLE_NEWS_SITEMAP, GATE_ANNOUNCEMENT_SITEMAP}:
                return FetchedResponse(url, url, 200, _titled_sitemap())
            for item in plan["seed_items"]:
                if url == item["metadata_url"]:
                    body = (
                        _mexc_one(item["instrument_id"])
                        if item["venue"] == "mexc"
                        else _gate_one(item["instrument_id"])
                    )
                    return FetchedResponse(url, url, 200, body)
            for venue in EXPECTED_VENUES:
                for base in EXPECTED_BASES:
                    if url == _official_url(venue, base):
                        return FetchedResponse(
                            url,
                            url,
                            200,
                            _page(base, collected_spot_instrument(venue, base)),
                        )
            raise AssertionError(url)

        result = discover_spot_v2_official_pages_r4(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE")
        self.assertEqual(len(result.request_plan), 18)
        self.assertFalse(result.identity_verdict)
        self.assertGreater(result.locator_diagnostics["title_match_count"], 0)

    def test_numeric_loc_without_title_does_not_bind(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r4("2026-08-15T19:35:00Z")

        def fetch(url: str) -> FetchedResponse:
            if url == MEXC_NEWS_SITEMAP_INDEX:
                return FetchedResponse(
                    url,
                    url,
                    200,
                    b'<?xml version="1.0"?><sitemapindex></sitemapindex>',
                )
            if url in {GATE_GOOGLE_NEWS_SITEMAP, GATE_ANNOUNCEMENT_SITEMAP}:
                return FetchedResponse(url, url, 200, _numeric_sitemap())
            for item in plan["seed_items"]:
                if url == item["metadata_url"]:
                    body = (
                        _mexc_one(item["instrument_id"])
                        if item["venue"] == "mexc"
                        else _gate_one(item["instrument_id"])
                    )
                    return FetchedResponse(url, url, 200, body)
            raise AssertionError(url)

        result = discover_spot_v2_official_pages_r4(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE")
        self.assertEqual(result.request_plan, ())
        self.assertFalse(result.identity_verdict)
        self.assertIn("gateio:STETH:EXACT_OFFICIAL_URL_NOT_FOUND", result.unresolved_pairs)

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r4("2026-08-15T19:35:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(f"network must not start: {url}")

        with self.assertRaisesRegex(SpotV2OfficialPageDiscoveryR4Error, "approval text"):
            discover_spot_v2_official_pages_r4(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
