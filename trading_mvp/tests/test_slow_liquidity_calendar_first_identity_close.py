from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
from slow_liquidity_calendar_first_identity_close import (  # noqa: E402
    CLOSE_PLAN_PATH,
    EXPECTED_SELECTED_COUNT,
    EXPECTED_UNIQUE_GATE_COUNT,
    EXPECTED_UNRESOLVED_COUNT,
    PARENT_GAP_PLAN_FILE_SHA256,
    PARENT_GAP_PLAN_HASH,
    PLAN_ID,
    CalendarFirstIdentityCloseError,
    build_calendar_first_identity_close_plan,
    validate_calendar_first_identity_close_plan,
)


class CalendarFirstIdentityClosePlanTests(unittest.TestCase):
    def test_plan_awaits_close_without_second_venue_or_ohlcv(self) -> None:
        plan = build_calendar_first_identity_close_plan("2026-08-16T15:50:00Z")
        validate_calendar_first_identity_close_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "AWAIT_EXACT_HASH_BOUND_CLOSE_ACCEPTANCE")
        self.assertEqual(
            plan["prepared_checkpoint"],
            "CLOSE_TWO_VENUE_OFFICIAL_IDENTITY_AS_INCOMPLETE",
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
        self.assertFalse(plan["close_two_venue_identity_authorized"])
        self.assertFalse(plan["mexc_public_contract_json"]["documented_unsigned_endpoint"])
        self.assertTrue(plan["documented_second_venue_method_unavailable"])
        self.assertEqual(
            plan["parent_calendar_first_identity_gap"]["plan_hash"],
            PARENT_GAP_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_calendar_first_identity_gap"]["parent_plan_file_sha256"],
            PARENT_GAP_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        self.assertFalse(plan["authorization_now"]["close_two_venue_identity_allowed"])

    def test_authorizing_close_now_is_rejected(self) -> None:
        plan = build_calendar_first_identity_close_plan("2026-08-16T15:50:00Z")
        plan["close_two_venue_identity_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstIdentityCloseError, "close"):
            validate_calendar_first_identity_close_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not CLOSE_PLAN_PATH.is_file():
            raise FileNotFoundError(CLOSE_PLAN_PATH)
        checked_in = json.loads(CLOSE_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_calendar_first_identity_close_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_calendar_first_identity_close_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
