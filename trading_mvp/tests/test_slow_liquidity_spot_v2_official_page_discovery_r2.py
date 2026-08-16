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
from slow_liquidity_spot_v2_official_page_discovery_r2 import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    PARENT_PLAN_FILE_SHA256,
    PLAN_ID,
    SpotV2OfficialPageDiscoveryR2Error,
    build_spot_v2_official_page_discovery_plan_r2,
    canonical_hash,
    discover_spot_v2_official_pages_r2,
    validate_spot_v2_official_page_discovery_plan_r2,
)


def _identifier_for(base: str) -> str:
    return "0x" + f"{abs(hash(base)) % (16**8):08x}" + "b" * 32


def _official_url(venue: str, base: str) -> str:
    if venue == "mexc":
        return f"https://www.mexc.com/support/articles/{base.lower()}-spot-r2"
    return f"https://www.gate.com/announcements/article/{base.lower()}-spot-r2"


def _rss_body(venue: str, base: str, instrument: str) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<item><title>{base} {instrument} listing</title>"
        f"<link>{_official_url(venue, base)}</link></item>"
        "</channel></rss>"
    ).encode("utf-8")


def _official_page_body(base: str, instrument: str) -> bytes:
    return (
        "<html><body>"
        f"{base} {instrument} Contract Address {_identifier_for(base)}"
        "</body></html>"
    ).encode("utf-8")


def _mexc_one(instrument: str, *, spot_allowed: bool = True) -> bytes:
    return json.dumps(
        {
            "symbols": [
                {
                    "symbol": instrument,
                    "baseAsset": instrument.removesuffix("USDT"),
                    "quoteAsset": "USDT",
                    "status": "1",
                    "isSpotTradingAllowed": spot_allowed,
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


class SpotV2OfficialPageDiscoveryR2PlanTests(unittest.TestCase):
    def test_plan_uses_per_symbol_metadata_not_full_catalog(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r2("2026-08-15T18:25:00Z")
        validate_spot_v2_official_page_discovery_plan_r2(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(len(plan["seed_items"]), 18)
        self.assertEqual(plan["limits"]["maximum_total_http_requests"], 56)
        self.assertEqual(plan["limits"]["maximum_response_bytes_per_request"], 1_000_000)
        self.assertNotIn("https://api.mexc.com/api/v3/exchangeInfo\"", dumped)
        self.assertNotIn(
            "https://api.gateio.ws/api/v4/spot/currency_pairs\"",
            dumped,
        )
        mexc = next(
            item
            for item in plan["seed_items"]
            if item["venue"] == "mexc" and item["base_ticker"] == "STETH"
        )
        gate = next(
            item
            for item in plan["seed_items"]
            if item["venue"] == "gateio" and item["base_ticker"] == "STETH"
        )
        self.assertEqual(
            mexc["metadata_url"],
            "https://api.mexc.com/api/v3/exchangeInfo?symbol=STETHUSDT",
        )
        self.assertEqual(
            gate["metadata_url"],
            "https://api.gateio.ws/api/v4/spot/currency_pairs/STETH_USDT",
        )
        self.assertTrue(plan["parent_discovery"]["retry_of_parent_forbidden"])
        self.assertEqual(
            plan["parent_discovery"]["parent_plan_file_sha256"],
            PARENT_PLAN_FILE_SHA256,
        )
        self.assertGreater(
            plan["catalog_size_evidence"]["mexc_spot_exchangeinfo_bytes"],
            1_000_000,
        )
        self.assertGreater(
            plan["catalog_size_evidence"]["gate_spot_currency_pairs_bytes"],
            1_000_000,
        )
        self.assertFalse(plan["identity_evidence"])
        self.assertFalse(plan["network_authorized"])
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_official_page_discovery_plan_r2(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_spot_v2_official_page_discovery_plan_r2(checked_in)


class SpotV2OfficialPageDiscoveryR2ExecutionTests(unittest.TestCase):
    def test_fixture_discover_accepts_collected_mexc_flag_false(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r2("2026-08-15T18:25:00Z")

        def fetch(url: str) -> FetchedResponse:
            for item in plan["seed_items"]:
                if url == item["metadata_url"]:
                    body = (
                        _mexc_one(item["instrument_id"], spot_allowed=False)
                        if item["venue"] == "mexc"
                        else _gate_one(item["instrument_id"])
                    )
                    return FetchedResponse(url, url, 200, body)
                if url == item["search_url"]:
                    return FetchedResponse(
                        url,
                        url,
                        200,
                        _rss_body(
                            item["venue"],
                            item["base_ticker"],
                            item["instrument_id"],
                        ),
                    )
            for venue in EXPECTED_VENUES:
                for base in EXPECTED_BASES:
                    if url == _official_url(venue, base):
                        return FetchedResponse(
                            url,
                            url,
                            200,
                            _official_page_body(
                                base, collected_spot_instrument(venue, base)
                            ),
                        )
            raise AssertionError(url)

        result = discover_spot_v2_official_pages_r2(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE")
        self.assertEqual(len(result.request_plan), 18)
        self.assertFalse(result.identity_verdict)
        self.assertEqual(result.request_count, 54)
        self.assertTrue(
            all(row["status"] == "LISTED" for row in result.metadata_diagnostics)
        )

    def test_oversize_metadata_is_recorded_and_does_not_abort_run(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r2("2026-08-15T18:25:00Z")

        def fetch(url: str) -> FetchedResponse:
            first = plan["seed_items"][0]
            if url == first["metadata_url"]:
                return FetchedResponse(url, url, 200, b"x" * 1_000_001)
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
                        _rss_body(
                            item["venue"],
                            item["base_ticker"],
                            item["instrument_id"],
                        ),
                    )
            for venue in EXPECTED_VENUES:
                for base in EXPECTED_BASES:
                    if url == _official_url(venue, base):
                        return FetchedResponse(
                            url,
                            url,
                            200,
                            _official_page_body(
                                base, collected_spot_instrument(venue, base)
                            ),
                        )
            raise AssertionError(url)

        result = discover_spot_v2_official_pages_r2(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE")
        self.assertFalse(result.identity_verdict)
        self.assertEqual(len(result.request_plan), 17)
        self.assertIn(
            "mexc:STETH:METADATA_RESPONSE_CAP_EXCEEDED",
            result.unresolved_pairs,
        )

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan_r2("2026-08-15T18:25:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(f"network must not start: {url}")

        with self.assertRaisesRegex(SpotV2OfficialPageDiscoveryR2Error, "approval text"):
            discover_spot_v2_official_pages_r2(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
