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
from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
from slow_liquidity_spot_v2_official_currency_json import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS,
    GATE_CURRENCY_URL_PREFIX,
    PARENT_R4_PLAN_FILE_SHA256,
    PLAN_ID,
    SpotV2OfficialCurrencyJsonError,
    build_spot_v2_official_currency_json_plan,
    collect_spot_v2_official_currency_json,
    validate_spot_v2_official_currency_json_plan,
)


def _gate_currency(base: str, addr: str, extra: list[dict] | None = None) -> bytes:
    chains = [{"name": "ETH", "addr": addr, "deposit_disabled": False}]
    if extra:
        chains.extend(extra)
    return json.dumps(
        {"currency": base, "delisted": False, "trade_disabled": False, "chains": chains},
        separators=(",", ":"),
    ).encode()


class SpotV2OfficialCurrencyJsonPlanTests(unittest.TestCase):
    def test_plan_is_official_json_not_page_locator(self) -> None:
        plan = build_spot_v2_official_currency_json_plan("2026-08-15T19:50:00Z")
        validate_spot_v2_official_currency_json_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["evidence_class"], "OFFICIAL_PUBLIC_REST_CURRENCY_JSON")
        self.assertEqual(len(plan["seed_items"]), 9)
        self.assertTrue(
            plan["seed_items"][0]["currency_url"].startswith(GATE_CURRENCY_URL_PREFIX)
        )
        self.assertNotIn("www.bing.com", dumped)
        for marker in FORBIDDEN_LIVE_PAGE_LOCATOR_MARKERS:
            self.assertNotIn(marker, dumped.lower())
        self.assertNotIn("www.mexc.com/support", dumped)
        self.assertTrue(plan["parent_discovery"]["retry_of_parent_forbidden"])
        self.assertEqual(
            plan["parent_discovery"]["parent_plan_file_sha256"],
            PARENT_R4_PLAN_FILE_SHA256,
        )
        self.assertFalse(plan["identity_verdict_allowed"])
        self.assertFalse(plan["network_authorized"])
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertTrue(plan["mexc_public_contract_json"]["documented_unsigned_endpoint"] is False)

    def test_live_sitemap_or_bing_locator_is_rejected(self) -> None:
        plan = build_spot_v2_official_currency_json_plan("2026-08-15T19:50:00Z")
        plan["goal"] = "https://www.mexc.com/news/sitemap-index.xml"
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2OfficialCurrencyJsonError, "live page locator"):
            validate_spot_v2_official_currency_json_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_official_currency_json_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_spot_v2_official_currency_json_plan(checked_in)


class SpotV2OfficialCurrencyJsonExecutionTests(unittest.TestCase):
    def test_unique_gate_evm_addr_is_collected_not_identity_verdict(self) -> None:
        plan = build_spot_v2_official_currency_json_plan("2026-08-15T19:50:00Z")
        addrs = {base: "0x" + f"{i:040x}" for i, base in enumerate(EXPECTED_BASES, start=1)}

        def fetch(url: str) -> FetchedResponse:
            for item in plan["seed_items"]:
                if url == item["currency_url"]:
                    base = item["base_ticker"]
                    extra = (
                        [{"name": "BSC", "addr": addrs[base], "deposit_disabled": False}]
                        if base == "OKB"
                        else None
                    )
                    return FetchedResponse(url, url, 200, _gate_currency(base, addrs[base], extra))
            raise AssertionError(url)

        result = collect_spot_v2_official_currency_json(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "SPOT_V2_OFFICIAL_CURRENCY_JSON_INCOMPLETE")
        self.assertFalse(result.identity_verdict)
        self.assertEqual(len(result.gate_records), 7)
        self.assertIn("RAIN:AMBIGUOUS_KNOWN_TICKER_COLLISION", result.unresolved)
        self.assertIn("EDGE:AMBIGUOUS_KNOWN_TICKER_COLLISION", result.unresolved)
        self.assertTrue(all(row["venue"] == "gateio" for row in result.gate_records))
        self.assertTrue(all(not row.get("mexc_record") for row in result.gate_records))

    def test_two_distinct_evm_addrs_fail_closed(self) -> None:
        plan = build_spot_v2_official_currency_json_plan("2026-08-15T19:50:00Z")

        def fetch(url: str) -> FetchedResponse:
            item = next(row for row in plan["seed_items"] if row["currency_url"] == url)
            base = item["base_ticker"]
            body = _gate_currency(
                base,
                "0x" + "1" * 40,
                extra=[{"name": "ARB", "addr": "0x" + "2" * 40}],
            )
            return FetchedResponse(url, url, 200, body)

        result = collect_spot_v2_official_currency_json(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.gate_records, ())
        self.assertTrue(all("NOT_UNIQUE_EVM_ADDR" in row or "COLLISION" in row for row in result.unresolved))
        self.assertFalse(result.identity_verdict)

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_spot_v2_official_currency_json_plan("2026-08-15T19:50:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(url)

        with self.assertRaisesRegex(SpotV2OfficialCurrencyJsonError, "approval text"):
            collect_spot_v2_official_currency_json(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
