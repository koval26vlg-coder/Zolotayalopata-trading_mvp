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
from slow_liquidity_spot_v2_official_page_discovery_r3 import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    GATE_ANNOUNCEMENT_SITEMAP,
    MEXC_SUPPORT_SITEMAP_INDEX,
    PARENT_R2_PLAN_FILE_SHA256,
    PLAN_ID,
    SpotV2OfficialPageDiscoveryR3Error,
    build_spot_v2_official_page_discovery_plan_r3,
    discover_spot_v2_official_pages_r3,
    validate_spot_v2_official_page_discovery_plan_r3,
)


def _identifier_for(base: str) -> str:
    return "0x" + f"{abs(hash(base)) % (16**8):08x}" + "c" * 32


def _official_url(venue: str, base: str) -> str:
    if venue == "mexc":
        return f"https://www.mexc.com/support/articles/{base.lower()}-spot-r3"
    return f"https://www.gate.com/announcements/article/{base.lower()}-spot-r3"


def _mexc_one(instrument: str) -> bytes:
    return json.dumps(
        {
            "symbols": [
                {
                    "symbol": instrument,
                    "baseAsset": instrument.removesuffix("USDT"),
                    "quoteAsset": "USDT",
                    "status": "1",
                    "isSpotTradingAllowed": False,
                }
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _gate_one(instrument: str) -> bytes:
    return json.dumps(
        {
            "id": instrument,
            "base": instrument.removesuffix("_USDT"),
            "quote": "USDT",
            "trade_status": "tradable",
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _search_html(venue: str, base: str) -> bytes:
    return (
        "<html><body>"
        f'<a href="{_official_url(venue, base)}">{base} listing</a>'
        "</body></html>"
    ).encode("utf-8")


def _page(base: str, instrument: str) -> bytes:
    return (
        "<html><body>"
        f"{base} {instrument} Contract Address {_identifier_for(base)}"
        "</body></html>"
    ).encode("utf-8")


class SpotV2OfficialPageDiscoveryR3PlanTests(unittest.TestCase):
    def test_plan_uses_official_sitemaps_not_bing_and_not_r2_retry(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r3("2026-08-15T19:10:00Z")
        validate_spot_v2_official_page_discovery_plan_r3(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(len(plan["seed_items"]), 18)
        self.assertEqual(
            plan["navigation_contract"]["provider"],
            "OFFICIAL_SITEMAP_AND_VENUE_SEARCH",
        )
        self.assertEqual(
            plan["navigation_contract"]["mexc_support_sitemap_index"],
            MEXC_SUPPORT_SITEMAP_INDEX,
        )
        self.assertEqual(
            plan["navigation_contract"]["gate_announcement_sitemap"],
            GATE_ANNOUNCEMENT_SITEMAP,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertTrue(plan["parent_discovery"]["retry_of_parent_forbidden"])
        self.assertEqual(
            plan["parent_discovery"]["parent_plan_file_sha256"],
            PARENT_R2_PLAN_FILE_SHA256,
        )
        self.assertFalse(plan["identity_evidence"])
        self.assertFalse(plan["network_authorized"])
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        mexc = next(
            item
            for item in plan["seed_items"]
            if item["venue"] == "mexc" and item["base_ticker"] == "STETH"
        )
        self.assertIn("announcements?keyword=STETH", mexc["search_url"])
        self.assertNotIn("bing.com", mexc["search_url"])

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_official_page_discovery_plan_r3(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_spot_v2_official_page_discovery_plan_r3(checked_in)


class SpotV2OfficialPageDiscoveryR3ExecutionTests(unittest.TestCase):
    def test_fixture_official_search_finds_allowlisted_pages(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r3("2026-08-15T19:10:00Z")

        def fetch(url: str) -> FetchedResponse:
            if url in {
                MEXC_SUPPORT_SITEMAP_INDEX,
                GATE_ANNOUNCEMENT_SITEMAP,
            }:
                return FetchedResponse(
                    url,
                    url,
                    200,
                    b'<?xml version="1.0"?><urlset></urlset>',
                )
            for item in plan["seed_items"]:
                if url == item["metadata_url"]:
                    body = (
                        _mexc_one(item["instrument_id"])
                        if item["venue"] == "mexc"
                        else _gate_one(item["instrument_id"])
                    )
                    return FetchedResponse(url, url, 200, body)
                if url == item["search_url"]:
                    return FetchedResponse(
                        url,
                        url,
                        200,
                        _search_html(item["venue"], item["base_ticker"]),
                    )
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

        result = discover_spot_v2_official_pages_r3(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE")
        self.assertEqual(len(result.request_plan), 18)
        self.assertFalse(result.identity_verdict)
        self.assertEqual(result.pending_allowlist, ())

    def test_mexc_announcement_url_is_pending_not_identity_verdict(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r3("2026-08-15T19:10:00Z")
        announcement = (
            "https://www.mexc.com/announcements/article/steth-spot-listing"
        )

        def fetch(url: str) -> FetchedResponse:
            if url in {MEXC_SUPPORT_SITEMAP_INDEX, GATE_ANNOUNCEMENT_SITEMAP}:
                return FetchedResponse(
                    url, url, 200, b'<?xml version="1.0"?><urlset></urlset>'
                )
            for item in plan["seed_items"]:
                if url == item["metadata_url"]:
                    body = (
                        _mexc_one(item["instrument_id"])
                        if item["venue"] == "mexc"
                        else _gate_one(item["instrument_id"])
                    )
                    return FetchedResponse(url, url, 200, body)
                if url == item["search_url"] and item["venue"] == "mexc":
                    return FetchedResponse(
                        url,
                        url,
                        200,
                        (
                            "<html><body>"
                            f'<a href="{announcement}">STETH listing</a>'
                            "</body></html>"
                        ).encode(),
                    )
                if url == item["search_url"]:
                    return FetchedResponse(
                        url,
                        url,
                        200,
                        _search_html(item["venue"], item["base_ticker"]),
                    )
            if url == announcement:
                return FetchedResponse(
                    url, url, 200, _page("STETH", "STETHUSDT")
                )
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

        result = discover_spot_v2_official_pages_r3(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE")
        self.assertFalse(result.identity_verdict)
        self.assertEqual(len(result.request_plan), 9)
        self.assertTrue(any("STETH" in item for item in result.pending_allowlist))

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r3("2026-08-15T19:10:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(f"network must not start: {url}")

        with self.assertRaisesRegex(SpotV2OfficialPageDiscoveryR3Error, "approval text"):
            discover_spot_v2_official_pages_r3(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
