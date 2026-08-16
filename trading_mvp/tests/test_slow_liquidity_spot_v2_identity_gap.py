from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_spot_v2_official_page_discovery import canonical_hash  # noqa: E402
from slow_liquidity_spot_v2_identity_gap import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
    PARENT_CURRENCY_JSON_PLAN_HASH,
    PARENT_CURRENCY_JSON_RECORDS_SHA256,
    PLAN_ID,
    SpotV2IdentityGapError,
    build_spot_v2_identity_gap_plan,
    validate_spot_v2_identity_gap_plan,
)


class SpotV2IdentityGapPlanTests(unittest.TestCase):
    def test_plan_is_offline_gap_not_retry_or_page_locator(self) -> None:
        plan = build_spot_v2_identity_gap_plan("2026-08-15T20:20:00Z")
        validate_spot_v2_identity_gap_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "IDENTITY_UNIVERSE_UNREACHABLE_AWAIT_RESCOPE_OR_CLOSE")
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_verdict_allowed"])
        self.assertFalse(plan["html_request_plan_available"])
        self.assertEqual(plan["official_page_request_plan_item_count"], 0)
        self.assertEqual(plan["unique_gate_evm_base_count"], 4)
        self.assertEqual(plan["two_venue_verified_base_count"], 0)
        self.assertLess(plan["unique_gate_evm_base_count"], 8)
        self.assertTrue(plan["eighteen_item_official_page_plan_unreachable"])
        self.assertTrue(plan["minimum_eight_two_venue_bases_unreachable"])
        self.assertTrue(plan["parent_retry_forbidden"])
        self.assertTrue(plan["page_locator_r5_forbidden"])
        self.assertEqual(
            plan["parent_currency_json"]["plan_hash"],
            PARENT_CURRENCY_JSON_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_currency_json"]["parent_plan_file_sha256"],
            PARENT_CURRENCY_JSON_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            plan["parent_currency_json"]["records_sha256"],
            PARENT_CURRENCY_JSON_RECORDS_SHA256,
        )
        self.assertEqual(
            plan["unique_gate_evm_bases"],
            ["STETH", "WEETH", "OKB", "MNT"],
        )
        self.assertIn("RAIN", plan["fail_closed_bases"])
        self.assertIn("EDGE", plan["fail_closed_bases"])
        self.assertFalse(plan["mexc_public_contract_json"]["documented_unsigned_endpoint"])
        self.assertFalse(plan["authorization_now"]["actual_network_run_allowed"])
        self.assertFalse(plan["authorization_now"]["rescope_authorized"])
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_authorizing_retry_or_network_is_rejected(self) -> None:
        plan = build_spot_v2_identity_gap_plan("2026-08-15T20:20:00Z")
        plan["parent_retry_forbidden"] = False
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2IdentityGapError, "retry"):
            validate_spot_v2_identity_gap_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_identity_gap_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_spot_v2_identity_gap_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
