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
from slow_liquidity_calendar_first_gate_currency_json import (  # noqa: E402
    CURRENCY_PLAN_PATH,
    EXPECTED_APPROVAL_TEXT,
    EXPECTED_SELECTED_COUNT,
    GATE_CURRENCY_URL_PREFIX,
    PARENT_IDENTITY_PLAN_FILE_SHA256,
    PARENT_IDENTITY_PLAN_HASH,
    PARENT_SELECTED_BASES_SHA256,
    PLAN_ID,
    CalendarFirstGateCurrencyJsonError,
    build_calendar_first_gate_currency_json_plan,
    collect_calendar_first_gate_currency_json,
    validate_calendar_first_gate_currency_json_plan,
)


def _gate_currency(base: str, addr: str, extra: list[dict] | None = None) -> bytes:
    chains = [{"name": "ETH", "addr": addr, "deposit_disabled": False}]
    if extra:
        chains.extend(extra)
    return json.dumps(
        {"currency": base, "delisted": False, "trade_disabled": False, "chains": chains},
        separators=(",", ":"),
    ).encode()


class CalendarFirstGateCurrencyJsonPlanTests(unittest.TestCase):
    def test_plan_binds_407_gate_json_only(self) -> None:
        plan = build_calendar_first_gate_currency_json_plan("2026-08-16T13:50:00Z")
        validate_calendar_first_gate_currency_json_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["selected_base_count"], EXPECTED_SELECTED_COUNT)
        self.assertEqual(len(plan["selected_bases"]), EXPECTED_SELECTED_COUNT)
        self.assertEqual(len(plan["seed_items"]), EXPECTED_SELECTED_COUNT)
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertEqual(plan["selected_bases_sha256"], PARENT_SELECTED_BASES_SHA256)
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["identity_verdict_allowed"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["listing_first_name_discovery_reopened"])
        self.assertFalse(plan["mexc_public_contract_json"]["documented_unsigned_endpoint"])
        self.assertTrue(plan["not_html_official_page_request_plan"])
        self.assertEqual(
            plan["official_json_contract"]["url_prefix"],
            GATE_CURRENCY_URL_PREFIX,
        )
        self.assertEqual(plan["limits"]["maximum_total_http_requests"], 407)
        self.assertEqual(plan["limits"]["maximum_attempts_per_url"], 1)
        self.assertEqual(plan["limits"]["max_runtime_sec"], 900)
        self.assertEqual(
            plan["parent_calendar_first_official_identity"]["plan_hash"],
            PARENT_IDENTITY_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_calendar_first_official_identity"]["parent_plan_file_sha256"],
            PARENT_IDENTITY_PLAN_FILE_SHA256,
        )
        for closed in EXPECTED_BASES:
            self.assertNotIn(closed, plan["selected_bases"])
        for item in plan["seed_items"]:
            self.assertTrue(item["currency_url"].startswith(GATE_CURRENCY_URL_PREFIX))
            self.assertEqual(
                item["currency_url"],
                f"{GATE_CURRENCY_URL_PREFIX}{item['base_ticker']}",
            )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertFalse(plan["authorization_now"]["actual_network_run_allowed"])

    def test_authorizing_ohlcv_or_verdict_is_rejected(self) -> None:
        plan = build_calendar_first_gate_currency_json_plan("2026-08-16T13:50:00Z")
        plan["ohlcv_collect_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstGateCurrencyJsonError, "ohlcv"):
            validate_calendar_first_gate_currency_json_plan(plan)
        plan = build_calendar_first_gate_currency_json_plan("2026-08-16T13:50:00Z")
        plan["identity_verdict_allowed"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstGateCurrencyJsonError, "identity verdict"):
            validate_calendar_first_gate_currency_json_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not CURRENCY_PLAN_PATH.is_file():
            raise FileNotFoundError(CURRENCY_PLAN_PATH)
        checked_in = json.loads(CURRENCY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_calendar_first_gate_currency_json_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_calendar_first_gate_currency_json_plan(checked_in)


class CalendarFirstGateCurrencyJsonExecutionTests(unittest.TestCase):
    def test_unique_gate_evm_addr_is_collected_not_identity_verdict(self) -> None:
        plan = build_calendar_first_gate_currency_json_plan("2026-08-16T13:50:00Z")
        addrs = {
            item["base_ticker"]: "0x" + f"{index:040x}"
            for index, item in enumerate(plan["seed_items"], start=1)
        }

        def fetch(url: str) -> FetchedResponse:
            item = next(row for row in plan["seed_items"] if row["currency_url"] == url)
            base = item["base_ticker"]
            return FetchedResponse(url, url, 200, _gate_currency(base, addrs[base]))

        result = collect_calendar_first_gate_currency_json(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.status, "CALENDAR_FIRST_GATE_CURRENCY_JSON_INCOMPLETE")
        self.assertFalse(result.identity_verdict)
        self.assertEqual(len(result.gate_records), EXPECTED_SELECTED_COUNT)
        self.assertEqual(result.unresolved, ())
        self.assertEqual(result.request_count, EXPECTED_SELECTED_COUNT)
        self.assertTrue(all(row["venue"] == "gateio" for row in result.gate_records))
        self.assertTrue(all(not row.get("mexc_record") for row in result.gate_records))

    def test_two_distinct_evm_addrs_fail_closed(self) -> None:
        plan = build_calendar_first_gate_currency_json_plan("2026-08-16T13:50:00Z")

        def fetch(url: str) -> FetchedResponse:
            item = next(row for row in plan["seed_items"] if row["currency_url"] == url)
            body = _gate_currency(
                item["base_ticker"],
                "0x" + "1" * 40,
                extra=[{"name": "ARB", "addr": "0x" + "2" * 40}],
            )
            return FetchedResponse(url, url, 200, body)

        result = collect_calendar_first_gate_currency_json(
            plan,
            user_approval_text=EXPECTED_APPROVAL_TEXT,
            fetch=fetch,
        )
        self.assertEqual(result.gate_records, ())
        self.assertEqual(len(result.unresolved), EXPECTED_SELECTED_COUNT)
        self.assertTrue(all("NOT_UNIQUE_EVM_ADDR" in row for row in result.unresolved))
        self.assertFalse(result.identity_verdict)

    def test_wrong_approval_text_is_rejected_without_fetch(self) -> None:
        plan = build_calendar_first_gate_currency_json_plan("2026-08-16T13:50:00Z")

        def fetch(url: str) -> FetchedResponse:
            raise AssertionError(url)

        with self.assertRaisesRegex(CalendarFirstGateCurrencyJsonError, "approval text"):
            collect_calendar_first_gate_currency_json(
                plan,
                user_approval_text="wrong",
                fetch=fetch,
            )


if __name__ == "__main__":
    unittest.main()
