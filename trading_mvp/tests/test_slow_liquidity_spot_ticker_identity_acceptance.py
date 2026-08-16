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
import slow_liquidity_spot_ticker_identity_acceptance as m  # noqa: E402


class SpotTickerIdentityAcceptancePlanTests(unittest.TestCase):
    def test_plan_awaits_receipt_with_7_accepted_bases(self) -> None:
        plan = m.build_identity_acceptance_plan("2026-08-16T23:30:00Z")
        m.validate_identity_acceptance_plan(plan)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(
            plan["status"], "AWAIT_SPOT_TICKER_IDENTITY_ACCEPTANCE_RECEIPT"
        )
        self.assertEqual(
            plan["identity_contract"]["accepted_bases"],
            ["BDX", "CC", "MNT", "OKB", "STETH", "USDD", "WEETH"],
        )
        self.assertEqual(
            plan["identity_contract"]["fail_closed_bases"], ["EDGE", "RAIN"]
        )
        self.assertFalse(plan["official_identity_claim"])
        self.assertFalse(plan["network_authorized"])
        self.assertFalse(plan["identity_verdict_authorized"])
        self.assertFalse(plan["replay_allowed"])

    def test_plan_with_official_claim_is_rejected(self) -> None:
        plan = m.build_identity_acceptance_plan("2026-08-16T23:30:00Z")
        plan["official_identity_claim"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            m.SpotTickerIdentityAcceptanceError, "official identity"
        ):
            m.validate_identity_acceptance_plan(plan)

    def test_plan_with_premature_verdict_authorization_is_rejected(self) -> None:
        plan = m.build_identity_acceptance_plan("2026-08-16T23:30:00Z")
        plan["identity_verdict_authorized"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            m.SpotTickerIdentityAcceptanceError, "verdict"
        ):
            m.validate_identity_acceptance_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not m.PLAN_PATH.is_file():
            raise FileNotFoundError(m.PLAN_PATH)
        checked_in = json.loads(m.PLAN_PATH.read_text(encoding="utf-8"))
        rebuilt = m.build_identity_acceptance_plan(checked_in["generated_at_utc"])
        self.assertEqual(checked_in, rebuilt)


class SpotTickerIdentityVerdictTests(unittest.TestCase):
    def test_verdict_partition_from_real_v6_quality(self) -> None:
        quality = m.load_v6_quality()
        verdict = m.compute_identity_verdict(quality)
        self.assertEqual(verdict["accepted_base_count"], 7)
        self.assertEqual(verdict["excluded_base_count"], 2)
        self.assertEqual(
            [entry["base"] for entry in verdict["excluded_bases"]],
            ["EDGE", "RAIN"],
        )
        self.assertTrue(
            set(verdict["accepted_bases"]).isdisjoint({"EDGE", "RAIN"})
        )

    def test_receipt_binds_plan_and_authorizes_materialization(self) -> None:
        if not m.RECEIPT_PATH.is_file():
            raise FileNotFoundError(m.RECEIPT_PATH)
        receipt = json.loads(m.RECEIPT_PATH.read_text(encoding="utf-8"))
        plan = json.loads(m.PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], m.RECEIPT_STATUS)
        m.validate_acceptance_receipt(receipt, plan)

    def test_receipt_with_opened_replay_is_rejected(self) -> None:
        receipt = json.loads(m.RECEIPT_PATH.read_text(encoding="utf-8"))
        plan = json.loads(m.PLAN_PATH.read_text(encoding="utf-8"))
        tampered = json.loads(json.dumps(receipt))
        tampered["authorized_scope"]["replay_direct"] = True
        tampered["receipt_hash"] = "0" * 64
        with self.assertRaises(m.SpotTickerIdentityAcceptanceError):
            m.validate_acceptance_receipt(tampered, plan)

    def test_materialized_verdict_and_rebind_are_deterministic(self) -> None:
        if not m.VERDICT_PATH.is_file() or not m.QUALITY_REBIND_PATH.is_file():
            self.skipTest("materialization not yet written")
        receipt = json.loads(m.RECEIPT_PATH.read_text(encoding="utf-8"))
        verdict = m.build_verdict_payload(receipt)
        on_disk = json.loads(m.VERDICT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["verdict_hash"], verdict["verdict_hash"])
        rebind = m.build_quality_rebind_payload(receipt)
        rebind_disk = json.loads(m.QUALITY_REBIND_PATH.read_text(encoding="utf-8"))
        self.assertEqual(rebind_disk["rebind_hash"], rebind["rebind_hash"])
        self.assertEqual(
            rebind["decision"], m.REBOUND_QUALITY_DECISION
        )
        self.assertTrue(rebind["fixed_signal_plan_allowed"])
        self.assertFalse(rebind["replay_allowed"])
        self.assertEqual(
            rebind["identity_acceptance"]["accepted_bases"],
            ["BDX", "CC", "MNT", "OKB", "STETH", "USDD", "WEETH"],
        )


if __name__ == "__main__":
    unittest.main()
