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
from slow_liquidity_listing_first_universe import (  # noqa: E402
    DISCOVERY_PLAN_PATH,
    PARENT_CLOSED_PLAN_FILE_SHA256,
    PARENT_CLOSED_PLAN_HASH,
    PLAN_ID,
    SpotV2ListingFirstUniverseError,
    build_listing_first_universe_plan,
    validate_listing_first_universe_plan,
)


class ListingFirstUniversePlanTests(unittest.TestCase):
    def test_plan_is_listing_first_and_excludes_closed_nine(self) -> None:
        plan = build_listing_first_universe_plan("2026-08-15T20:50:00Z")
        validate_listing_first_universe_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "AWAIT_EXACT_HASH_BOUND_UNIVERSE_ACCEPTANCE")
        self.assertEqual(plan["universe_selection"], "OFFICIAL_LISTING_ANNOUNCEMENT_FIRST")
        self.assertEqual(plan["excluded_bases"], list(EXPECTED_BASES))
        self.assertEqual(plan["selected_bases"], [])
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertTrue(plan["identity_before_ohlcv_collect"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["replay_allowed"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertEqual(
            plan["parent_identity_closed"]["plan_hash"],
            PARENT_CLOSED_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_identity_closed"]["parent_plan_file_sha256"],
            PARENT_CLOSED_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            plan["official_listing_path_prefixes"]["mexc"],
            "/announcements/article/",
        )
        self.assertEqual(
            plan["official_listing_path_prefixes"]["gateio"],
            "/announcements/article/",
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("sitemap-index", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)
        for closed in EXPECTED_BASES:
            self.assertNotIn(f'"{closed}"', json.dumps(plan["selected_bases"]))

    def test_selecting_a_closed_base_is_rejected(self) -> None:
        plan = build_listing_first_universe_plan("2026-08-15T20:50:00Z")
        plan["selected_bases"] = ["STETH"]
        plan["invented_ticker_count"] = 1
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2ListingFirstUniverseError, "closed"):
            validate_listing_first_universe_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        checked_in = json.loads(DISCOVERY_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_listing_first_universe_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_listing_first_universe_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
