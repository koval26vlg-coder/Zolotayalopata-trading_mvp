from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_spot_v2_request_plan import (  # noqa: E402
    BINDINGS_PATH,
    SpotV2RequestPlanError,
    build_spot_v2_request_plan_bindings,
    canonical_hash,
    validate_spot_v2_request_plan_bindings,
)


class SpotV2RequestPlanBindingsTests(unittest.TestCase):
    def test_bindings_cover_eighteen_collected_spot_pairs(self) -> None:
        plan = build_spot_v2_request_plan_bindings("2026-08-15T17:40:00Z")
        validate_spot_v2_request_plan_bindings(plan)

        pairs = {(item["venue"], item["base_ticker"]) for item in plan["pairs"]}
        self.assertEqual(len(plan["pairs"]), 18)
        self.assertEqual(len(pairs), 18)
        self.assertEqual(
            next(
                item["instrument_id"]
                for item in plan["pairs"]
                if item["venue"] == "mexc" and item["base_ticker"] == "STETH"
            ),
            "STETHUSDT",
        )
        self.assertEqual(
            next(
                item["instrument_id"]
                for item in plan["pairs"]
                if item["venue"] == "gateio" and item["base_ticker"] == "STETH"
            ),
            "STETH_USDT",
        )
        self.assertFalse(plan["identity_evidence"])
        self.assertFalse(plan["execution_authorized"])
        self.assertTrue(plan["not_substitutable_for_execution_request_plan_sha256"])

    def test_edge_and_rain_are_fail_closed_and_perp_tickers_rejected(self) -> None:
        plan = build_spot_v2_request_plan_bindings("2026-08-15T17:40:00Z")
        collision = {
            item["base_ticker"]: item["collision_fail_closed"] for item in plan["pairs"]
        }
        self.assertTrue(collision["EDGE"])
        self.assertTrue(collision["RAIN"])
        self.assertFalse(collision["STETH"])

        plan["pairs"][0]["instrument_id"] = "STETH_USDT"
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2RequestPlanError, "collected spot"):
            validate_spot_v2_request_plan_bindings(plan)

        plan = build_spot_v2_request_plan_bindings("2026-08-15T17:40:00Z")
        plan["pairs"][0]["official_source_url"] = "https://www.mexc.com/support/articles/x"
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(SpotV2RequestPlanError, "official source"):
            validate_spot_v2_request_plan_bindings(plan)

    def test_checked_in_bindings_match_generator(self) -> None:
        checked_in = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
        generated = build_spot_v2_request_plan_bindings(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)
        validate_spot_v2_request_plan_bindings(checked_in)


if __name__ == "__main__":
    unittest.main()
