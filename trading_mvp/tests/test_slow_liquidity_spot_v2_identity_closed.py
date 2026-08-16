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
from slow_liquidity_spot_v2_identity_closed import (  # noqa: E402
    CLOSED_PAIR_COUNT,
    DISCOVERY_PLAN_PATH,
    PARENT_GAP_PLAN_FILE_SHA256,
    PARENT_GAP_PLAN_HASH,
    PLAN_ID,
    SpotV2IdentityClosedError,
    build_spot_v2_identity_closed_plan,
    validate_spot_v2_identity_closed_plan,
)


class SpotV2IdentityClosedPlanTests(unittest.TestCase):
    def test_plan_closes_nine_two_venue_bases_without_replay(self) -> None:
        plan = build_spot_v2_identity_closed_plan("2026-08-15T20:36:00Z")
        validate_spot_v2_identity_closed_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "IDENTITY_CLOSED_AS_UNREACHABLE")
        self.assertEqual(plan["selected_checkpoint"], "CLOSE_IDENTITY_AS_UNREACHABLE")
        self.assertEqual(plan["closed_bases"], list(EXPECTED_BASES))
        self.assertEqual(plan["closed_venues"], ["mexc", "gateio"])
        self.assertEqual(plan["closed_pair_count"], CLOSED_PAIR_COUNT)
        self.assertEqual(plan["closed_pair_count"], 18)
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_verdict_allowed"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["replay_allowed"])
        self.assertFalse(plan["rescope_authorized"])
        self.assertTrue(plan["ohlcv_dataset_retained"])
        self.assertTrue(plan["frozen_html_consumer_unchanged"])
        self.assertEqual(
            plan["parent_identity_gap"]["plan_hash"],
            PARENT_GAP_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_identity_gap"]["parent_plan_file_sha256"],
            PARENT_GAP_PLAN_FILE_SHA256,
        )
        self.assertIn("RAIN", plan["fail_closed_bases"])
        self.assertIn("EDGE", plan["fail_closed_bases"])
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_authorizing_replay_or_identity_execution_is_rejected(self) -> None:
        plan = build_spot_v2_identity_closed_plan("2026-08-15T20:36:00Z")
        plan["replay_allowed"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2IdentityClosedError, "replay"):
            validate_spot_v2_identity_closed_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_identity_closed_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_spot_v2_identity_closed_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
