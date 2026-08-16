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
    GATE_METADATA_ENDPOINT,
    MEXC_METADATA_ENDPOINT,
    collected_spot_instrument,
)
from slow_liquidity_official_identity_verification import (  # noqa: E402
    FetchedResponse,
    IdentityVerificationError,
)
from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    SpotV2OfficialPageDiscoveryError,
    build_spot_v2_official_page_discovery_plan,
    canonical_hash,
    discover_spot_v2_official_pages,
    validate_spot_v2_official_page_discovery_plan,
)


class SpotV2OfficialPageDiscoveryPlanTests(unittest.TestCase):
    def test_plan_uses_collected_spot_instruments_not_perp_tickers(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan("2026-08-15T17:50:00Z")
        validate_spot_v2_official_page_discovery_plan(plan)

        self.assertEqual(len(plan["seed_items"]), 18)
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
        self.assertEqual(mexc["instrument_id"], "STETHUSDT")
        self.assertEqual(gate["instrument_id"], "STETH_USDT")
        self.assertIn("STETHUSDT", mexc["navigation_query"])
        self.assertNotIn("STETH_USDT", mexc["navigation_query"])
        self.assertEqual(
            plan["official_source_contract"]["metadata_endpoints"]["mexc"],
            "https://api.mexc.com/api/v3/exchangeInfo",
        )
        self.assertNotIn("contract.mexc.com", json.dumps(plan))
        self.assertNotIn("{BASE}_USDT", json.dumps(plan))
        self.assertNotIn("20260815-v7", json.dumps(plan))
        self.assertFalse(plan["identity_evidence"])
        self.assertFalse(plan["network_authorized"])

    def test_edge_rain_are_fail_closed_and_perp_seed_is_rejected(self) -> None:
        plan = build_spot_v2_official_page_discovery_plan("2026-08-15T17:50:00Z")
        collision = {
            item["base_ticker"]: item["collision_fail_closed"]
            for item in plan["seed_items"]
        }
        self.assertTrue(collision["EDGE"])
        self.assertTrue(collision["RAIN"])

        plan["seed_items"][0]["instrument_id"] = "STETH_USDT"
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2OfficialPageDiscoveryError, "collected spot"):
            validate_spot_v2_official_page_discovery_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_official_page_discovery_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_spot_v2_official_page_discovery_plan(checked_in)


def _identifier_for(base: str) -> str:
    return "0x" + f"{abs(hash(base)) % (16**8):08x}" + "a" * 32


def _official_url(venue: str, base: str) -> str:
    if venue == "mexc":
        return f"https://www.mexc.com/support/articles/{base.lower()}-spot"
    return f"https://www.gate.com/announcements/article/{base.lower()}-spot"


def _rss_body(venue: str, base: str, instrument: str, extra_urls: tuple[str, ...] = ()) -> bytes:
    items = [
        (
            f"<item><title>{base} {instrument} listing</title>"
            f"<link>{_official_url(venue, base)}</link></item>"
        )
    ]
    for url in extra_urls:
        items.append(
            f"<item><title>{base} {instrument} listing</title><link>{url}</link></item>"
        )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        + "".join(items)
        + "</channel></rss>"
    ).encode("utf-8")


def _html_search_body(venue: str, base: str) -> bytes:
    url = _official_url(venue, base)
    return (
        "<!DOCTYPE html><html><body>"
        f'<a href="{url}">{base} official listing</a>'
        "</body></html>"
    ).encode("utf-8")


def _official_page_body(base: str, instrument: str) -> bytes:
    identifier = _identifier_for(base)
    return (
        "<html><body>"
        f"{base} {instrument} Contract Address {identifier}"
        "</body></html>"
    ).encode("utf-8")


def _mexc_metadata(extra_rows: list[dict] | None = None) -> bytes:
    rows = [
        {
            "symbol": collected_spot_instrument("mexc", base),
            "baseAsset": base,
            "quoteAsset": "USDT",
            "status": "ENABLED",
            "isSpotTradingAllowed": True,
        }
        for base in EXPECTED_BASES
    ]
    if extra_rows:
        rows.extend(extra_rows)
    return json.dumps({"symbols": rows}, separators=(",", ":")).encode("utf-8")


def _gate_metadata() -> bytes:
    rows = [
        {
            "id": collected_spot_instrument("gateio", base),
            "base": base,
            "quote": "USDT",
            "trade_status": "tradable",
        }
        for base in EXPECTED_BASES
    ]
    return json.dumps(rows, separators=(",", ":")).encode("utf-8")


class SpotV2OfficialPageDiscoveryExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))

    def test_fixture_discover_finds_eighteen_spot_pages_not_identity_verdict(self) -> None:
        seen: list[str] = []

        def fetch(url: str) -> FetchedResponse:
            seen.append(url)
            if url == MEXC_METADATA_ENDPOINT:
                body = _mexc_metadata(
                    extra_rows=[
                        {
                            "symbol": "BTCUSDT",
                            "baseAsset": "BTC",
                            "quoteAsset": "USDT",
                            "status": "ENABLED",
                            "isSpotTradingAllowed": True,
                        },
                        {
                            "symbol": "BTC-USDT",
                            "baseAsset": "BTC",
                            "quoteAsset": "USDT",
                            "status": "ENABLED",
                            "isSpotTradingAllowed": True,
                        },
                    ]
                )
            elif url == GATE_METADATA_ENDPOINT:
                body = _gate_metadata()
            else:
                seed = next(item for item in self.plan["seed_items"] if item["search_url"] == url)
                body = _rss_body(seed["venue"], seed["base_ticker"], seed["instrument_id"])
                if url == seed["search_url"]:
                    return FetchedResponse(url, url, 200, body)
                raise AssertionError(url)
            return FetchedResponse(url, url, 200, body)

        def fetch_all(url: str) -> FetchedResponse:
            if url in {MEXC_METADATA_ENDPOINT, GATE_METADATA_ENDPOINT}:
                return fetch(url)
            seed = next(
                (item for item in self.plan["seed_items"] if item["search_url"] == url),
                None,
            )
            if seed is not None:
                return FetchedResponse(
                    url,
                    url,
                    200,
                    _rss_body(seed["venue"], seed["base_ticker"], seed["instrument_id"]),
                )
            for venue in EXPECTED_VENUES:
                for base in EXPECTED_BASES:
                    if url == _official_url(venue, base):
                        return FetchedResponse(
                            url,
                            url,
                            200,
                            _official_page_body(base, collected_spot_instrument(venue, base)),
                        )
            raise AssertionError(url)

        result = discover_spot_v2_official_pages(
            self.plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch_all,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_COMPLETE")
        self.assertEqual(len(result.request_plan), 18)
        self.assertEqual(result.unresolved_pairs, ())
        self.assertFalse(result.identity_verdict)
        mexc_steth = next(
            item
            for item in result.request_plan
            if item["venue"] == "mexc" and item["base_ticker"] == "STETH"
        )
        self.assertEqual(mexc_steth["instrument_id"], "STETHUSDT")
        self.assertNotEqual(mexc_steth["instrument_id"], "STETH_USDT")
        self.assertTrue(mexc_steth["official_source_url"].startswith("https://www.mexc.com/support/articles/"))

    def test_html_navigation_and_edge_rain_ambiguity_are_fail_closed(self) -> None:
        def fetch(url: str) -> FetchedResponse:
            if url == MEXC_METADATA_ENDPOINT:
                return FetchedResponse(url, url, 200, _mexc_metadata())
            if url == GATE_METADATA_ENDPOINT:
                return FetchedResponse(url, url, 200, _gate_metadata())
            seed = next(
                (item for item in self.plan["seed_items"] if item["search_url"] == url),
                None,
            )
            if seed is not None:
                if seed["base_ticker"] in {"EDGE", "RAIN"}:
                    extra = _official_url(seed["venue"], seed["base_ticker"]) + "-alt"
                    return FetchedResponse(
                        url,
                        url,
                        200,
                        _rss_body(
                            seed["venue"],
                            seed["base_ticker"],
                            seed["instrument_id"],
                            extra_urls=(extra,),
                        ),
                    )
                return FetchedResponse(
                    url,
                    url,
                    200,
                    _html_search_body(seed["venue"], seed["base_ticker"]),
                )
            for venue in EXPECTED_VENUES:
                for base in EXPECTED_BASES:
                    if url == _official_url(venue, base):
                        return FetchedResponse(
                            url,
                            url,
                            200,
                            _official_page_body(base, collected_spot_instrument(venue, base)),
                        )
            raise IdentityVerificationError(f"unexpected url {url}")

        result = discover_spot_v2_official_pages(
            self.plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_PAGE_DISCOVERY_INCOMPLETE")
        self.assertFalse(result.identity_verdict)
        unresolved = " ".join(result.unresolved_pairs)
        self.assertIn("mexc:EDGE:AMBIGUOUS_KNOWN_TICKER_COLLISION", unresolved)
        self.assertIn("gateio:RAIN:AMBIGUOUS_KNOWN_TICKER_COLLISION", unresolved)
        self.assertEqual(len(result.request_plan), 14)

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(f"network must not start: {url}")

        with self.assertRaisesRegex(SpotV2OfficialPageDiscoveryError, "approval text"):
            discover_spot_v2_official_pages(
                self.plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
