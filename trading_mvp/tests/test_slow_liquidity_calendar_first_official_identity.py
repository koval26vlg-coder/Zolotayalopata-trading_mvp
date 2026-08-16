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
from slow_liquidity_spot_v2_official_page_discovery import canonical_hash  # noqa: E402
from slow_liquidity_calendar_first_official_identity import (  # noqa: E402
    IDENTITY_PLAN_PATH,
    PARENT_MATERIALIZATION_PLAN_FILE_SHA256,
    PARENT_MATERIALIZATION_PLAN_HASH,
    PLAN_ID,
    CalendarFirstOfficialIdentityError,
    build_calendar_first_official_identity_plan,
    validate_calendar_first_official_identity_plan,
)


class CalendarFirstOfficialIdentityPlanTests(unittest.TestCase):
    def test_plan_binds_calendar_names_to_gate_json_only(self) -> None:
        plan = build_calendar_first_official_identity_plan("2026-08-16T12:50:00Z")
        validate_calendar_first_official_identity_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["selected_base_count"], 407)
        self.assertEqual(len(plan["selected_bases"]), 407)
        self.assertEqual(plan["invented_ticker_count"], 0)
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
            "https://api.gateio.ws/api/v4/spot/currencies/",
        )
        self.assertEqual(
            plan["parent_calendar_name_materialization"]["plan_hash"],
            PARENT_MATERIALIZATION_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_calendar_name_materialization"]["parent_plan_file_sha256"],
            PARENT_MATERIALIZATION_PLAN_FILE_SHA256,
        )
        for closed in EXPECTED_BASES:
            self.assertNotIn(closed, plan["selected_bases"])
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_authorizing_ohlcv_is_rejected(self) -> None:
        plan = build_calendar_first_official_identity_plan("2026-08-16T12:50:00Z")
        plan["ohlcv_collect_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarFirstOfficialIdentityError, "ohlcv"):
            validate_calendar_first_official_identity_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not IDENTITY_PLAN_PATH.is_file():
            raise FileNotFoundError(IDENTITY_PLAN_PATH)
        checked_in = json.loads(IDENTITY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_calendar_first_official_identity_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_calendar_first_official_identity_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
