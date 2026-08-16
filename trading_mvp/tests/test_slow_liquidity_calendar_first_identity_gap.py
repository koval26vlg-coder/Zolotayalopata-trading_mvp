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
from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
from slow_liquidity_calendar_first_identity_gap import (  # noqa: E402
    EXPECTED_SELECTED_COUNT,
    EXPECTED_UNIQUE_GATE_COUNT,
    EXPECTED_UNRESOLVED_COUNT,
    GAP_PLAN_PATH,
    PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
    PARENT_CURRENCY_JSON_PLAN_HASH,
    PARENT_CURRENCY_JSON_RECORDS_SHA256,
    PLAN_ID,
    CalendarFirstIdentityGapError,
    build_calendar_first_identity_gap_plan,
    validate_calendar_first_identity_gap_plan,
)


class CalendarFirstIdentityGapPlanTests(unittest.TestCase):
    def test_plan_records_two_venue_gap_without_verdict(self) -> None:
        plan = build_calendar_first_identity_gap_plan("2026-08-16T15:40:00Z")
        validate_calendar_first_identity_gap_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"],
            "TWO_VENUE_OFFICIAL_IDENTITY_INCOMPLETE_AWAIT_GAP_ACCEPTANCE",
        )
        self.assertEqual(plan["selected_base_count"], EXPECTED_SELECTED_COUNT)
        self.assertEqual(plan["unique_gate_evm_base_count"], EXPECTED_UNIQUE_GATE_COUNT)
        self.assertEqual(plan["unresolved_count"], EXPECTED_UNRESOLVED_COUNT)
        self.assertEqual(plan["two_venue_verified_base_count"], 0)
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_verdict_allowed"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["listing_first_name_discovery_reopened"])
        self.assertTrue(plan["parent_retry_forbidden"])
        self.assertFalse(plan["mexc_public_contract_json"]["documented_unsigned_endpoint"])
        self.assertFalse(plan["two_venue_official_identity_complete"])
        self.assertEqual(
            plan["parent_calendar_first_gate_currency_json"]["plan_hash"],
            PARENT_CURRENCY_JSON_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_calendar_first_gate_currency_json"]["parent_plan_file_sha256"],
            PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            plan["parent_calendar_first_gate_currency_json"]["records_sha256"],
            PARENT_CURRENCY_JSON_RECORDS_SHA256,
        )
        for closed in EXPECTED_BASES:
            self.assertNotIn(closed, plan["unique_gate_evm_bases"])
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertFalse(plan["authorization_now"]["actual_network_run_allowed"])

    def test_authorizing_retry_ohlcv_or_verdict_is_rejected(self) -> None:
        plan = build_calendar_first_identity_gap_plan("2026-08-16T15:40:00Z")
        plan["parent_retry_forbidden"] = False
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstIdentityGapError, "retry"):
            validate_calendar_first_identity_gap_plan(plan)
        plan = build_calendar_first_identity_gap_plan("2026-08-16T15:40:00Z")
        plan["ohlcv_collect_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstIdentityGapError, "ohlcv"):
            validate_calendar_first_identity_gap_plan(plan)
        plan = build_calendar_first_identity_gap_plan("2026-08-16T15:40:00Z")
        plan["identity_verdict_allowed"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstIdentityGapError, "identity verdict"):
            validate_calendar_first_identity_gap_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not GAP_PLAN_PATH.is_file():
            raise FileNotFoundError(GAP_PLAN_PATH)
        checked_in = json.loads(GAP_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_calendar_first_identity_gap_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_calendar_first_identity_gap_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
