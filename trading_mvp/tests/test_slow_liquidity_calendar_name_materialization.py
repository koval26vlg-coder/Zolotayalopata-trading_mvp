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
from slow_liquidity_calendar_name_materialization import (  # noqa: E402
    MATERIALIZATION_PLAN_PATH,
    PARENT_UNIVERSE_PLAN_FILE_SHA256,
    PARENT_UNIVERSE_PLAN_HASH,
    PLAN_ID,
    CalendarNameMaterializationError,
    build_calendar_name_materialization_plan,
    validate_calendar_name_materialization_plan,
)


class CalendarNameMaterializationPlanTests(unittest.TestCase):
    def test_plan_materializes_calendar_names_without_inventing(self) -> None:
        plan = build_calendar_name_materialization_plan("2026-08-16T12:45:00Z")
        validate_calendar_name_materialization_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["invented_ticker_count"], 0)
        self.assertEqual(len(plan["selected_bases"]), 407)
        self.assertEqual(plan["selected_bases"], sorted(plan["selected_bases"]))
        self.assertTrue(plan["names_materialized"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_execution_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["spot_v2_runtime_reuse"])
        self.assertFalse(plan["listing_first_name_discovery_reopened"])
        for closed in EXPECTED_BASES:
            self.assertNotIn(closed, plan["selected_bases"])
        self.assertEqual(
            plan["parent_calendar_first_universe"]["plan_hash"],
            PARENT_UNIVERSE_PLAN_HASH,
        )
        self.assertEqual(
            plan["parent_calendar_first_universe"]["parent_plan_file_sha256"],
            PARENT_UNIVERSE_PLAN_FILE_SHA256,
        )
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_adding_a_closed_base_is_rejected(self) -> None:
        plan = build_calendar_name_materialization_plan("2026-08-16T12:45:00Z")
        plan["selected_bases"] = [*plan["selected_bases"], "STETH"]
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(CalendarNameMaterializationError, "closed"):
            validate_calendar_name_materialization_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not MATERIALIZATION_PLAN_PATH.is_file():
            raise FileNotFoundError(MATERIALIZATION_PLAN_PATH)
        checked_in = json.loads(MATERIALIZATION_PLAN_PATH.read_text(encoding="utf-8"))
        generated = build_calendar_name_materialization_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, generated)
        validate_calendar_name_materialization_plan(checked_in)


if __name__ == "__main__":
    unittest.main()
