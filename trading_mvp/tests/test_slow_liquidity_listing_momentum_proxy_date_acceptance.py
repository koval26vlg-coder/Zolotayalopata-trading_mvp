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
from slow_liquidity_listing_momentum_proxy_date_acceptance import (  # noqa: E402
    AGREEMENT_BUCKETS,
    EXPECTED_TWO_VENUE_COUNT,
    MATERIALIZATION_PATH,
    PLAN_ID,
    PROXY_PLAN_PATH,
    RECEIPT_STATUS,
    ListingMomentumProxyDateAcceptanceError,
    build_materialization_payload,
    build_proxy_date_acceptance_plan,
    census_proxy_listing_dates,
    fill_expected_approval_text,
    validate_acceptance_receipt,
    validate_proxy_date_acceptance_plan,
)
from slow_liquidity_calendar_first_universe import CALENDAR_PATH  # noqa: E402

RECEIPT_PATH = (
    ROOT
    / "docs/agent-log/approvals"
    / "2026-08-16-slow-liquidity-listing-momentum-proxy-date-acceptance-approval.json"
)


class ListingMomentumProxyDateAcceptancePlanTests(unittest.TestCase):
    def test_plan_awaits_receipt_without_authorizing_collection(self) -> None:
        plan = build_proxy_date_acceptance_plan("2026-08-16T19:30:00Z")
        validate_proxy_date_acceptance_plan(plan)
        dumped = json.dumps(plan)
        self.assertEqual(plan["plan_id"], PLAN_ID)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"], "AWAIT_PROXY_LISTING_DATE_ACCEPTANCE_RECEIPT"
        )
        self.assertEqual(
            plan["prepared_checkpoint"],
            "ACCEPT_PROXY_LISTING_DATE_SOURCE_USER_CONTRACT_DECISION",
        )
        self.assertFalse(plan["proxy_treated_as_official_announcement"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["ohlcv_collect_authorized"])
        self.assertFalse(plan["proxy_date_materialization_authorized"])
        self.assertFalse(plan["identity_verdict_allowed"])
        self.assertEqual(
            plan["proxy_listing_date_source"]["source_class"],
            "PROXY_TRADING_START_NOT_OFFICIAL_ANNOUNCEMENT",
        )
        self.assertFalse(
            plan["proxy_listing_date_source"][
                "usable_as_official_announcement_date"
            ]
        )
        self.assertEqual(
            plan["proxy_first_days_semantics"][
                "retrospective_window_available_count"
            ],
            EXPECTED_TWO_VENUE_COUNT,
        )
        self.assertFalse(
            plan["authorization_now"]["proxy_date_materialization_allowed"]
        )
        self.assertFalse(plan["authorization_now"]["actual_network_run_allowed"])
        self.assertGreaterEqual(len(plan["limitations"]), 5)
        self.assertNotIn("www.bing.com", dumped)
        self.assertNotIn("20260815-v7", dumped)
        self.assertNotIn("{BASE}_USDT", dumped)

    def test_treating_proxy_as_official_is_rejected(self) -> None:
        plan = build_proxy_date_acceptance_plan("2026-08-16T19:30:00Z")
        plan["proxy_treated_as_official_announcement"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            ListingMomentumProxyDateAcceptanceError, "official announcement"
        ):
            validate_proxy_date_acceptance_plan(plan)

    def test_authorizing_materialization_in_plan_is_rejected(self) -> None:
        plan = build_proxy_date_acceptance_plan("2026-08-16T19:30:00Z")
        plan["proxy_date_materialization_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            ListingMomentumProxyDateAcceptanceError, "materialization"
        ):
            validate_proxy_date_acceptance_plan(plan)

    def test_proxy_census_covers_full_universe(self) -> None:
        census = census_proxy_listing_dates(CALENDAR_PATH)
        self.assertEqual(census["two_venue_base_count"], EXPECTED_TWO_VENUE_COUNT)
        self.assertEqual(len(census["records"]), EXPECTED_TWO_VENUE_COUNT)
        self.assertEqual(
            sum(census["agreement_buckets"].values()), EXPECTED_TWO_VENUE_COUNT
        )
        self.assertEqual(
            sorted(census["agreement_buckets"]), sorted(AGREEMENT_BUCKETS)
        )
        self.assertEqual(census["proxy_event_available_count"], EXPECTED_TWO_VENUE_COUNT)
        for record in census["records"]:
            if record["proxy_event_ts"] is not None:
                self.assertIsNotNone(record["window_end_ts"])

    def test_checked_in_plan_matches_generator(self) -> None:
        if not PROXY_PLAN_PATH.is_file():
            raise FileNotFoundError(PROXY_PLAN_PATH)
        checked_in = json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))
        rebuilt = build_proxy_date_acceptance_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, rebuilt)

    def test_acceptance_receipt_binds_plan(self) -> None:
        if not RECEIPT_PATH.is_file():
            raise FileNotFoundError(RECEIPT_PATH)
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        plan = json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], RECEIPT_STATUS)
        validate_acceptance_receipt(receipt, plan)

    def test_receipt_with_opened_network_is_rejected(self) -> None:
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        plan = json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))
        tampered = dict(receipt)
        tampered["authorized_scope"] = dict(receipt["authorized_scope"])
        tampered["authorized_scope"]["actual_network_run"] = True
        tampered["receipt_hash"] = fill_expected_approval_text(
            "x", "y"
        )  # invalid hash must also fail
        with self.assertRaises(ListingMomentumProxyDateAcceptanceError):
            validate_acceptance_receipt(tampered, plan)

    def test_materialization_is_deterministic_and_hash_bound(self) -> None:
        receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        first = build_materialization_payload(receipt)
        second = build_materialization_payload(receipt)
        self.assertEqual(first, second)
        self.assertEqual(
            first["summary"]["proxy_event_available_count"],
            EXPECTED_TWO_VENUE_COUNT,
        )
        self.assertEqual(len(first["records"]), EXPECTED_TWO_VENUE_COUNT)
        self.assertEqual(first["source_class"], first["source_class"])
        self.assertEqual(
            first["authorized_by_receipt"]["plan_hash"],
            json.loads(PROXY_PLAN_PATH.read_text(encoding="utf-8"))["plan_hash"],
        )
        if MATERIALIZATION_PATH.is_file():
            on_disk = json.loads(MATERIALIZATION_PATH.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["materialization_hash"], first["materialization_hash"])


if __name__ == "__main__":
    unittest.main()
