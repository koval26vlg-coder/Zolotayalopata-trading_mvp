from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "docs" / "plans" / "funding-asset-universe-policy-v1.json"


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FundingAssetUniversePolicyTests(unittest.TestCase):
    def test_all_asset_categories_are_allowed_for_funding_strategies(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))

        self.assertEqual(policy["scope"], "FUNDING_STRATEGIES_ONLY")
        self.assertEqual(
            policy["asset_universe"]["mode"],
            "ALL_ASSETS_WITHOUT_CATEGORY_EXCLUSIONS",
        )
        self.assertFalse(policy["asset_universe"]["whitelist_required"])
        self.assertEqual(policy["asset_universe"]["blacklisted_symbols"], [])
        self.assertEqual(policy["asset_universe"]["blacklisted_categories"], [])
        self.assertEqual(
            policy["asset_universe"]["binance_listing_status_filter"],
            "NONE",
        )
        for key, value in policy["asset_universe"]["category_filters"].items():
            self.assertFalse(value, key)

    def test_only_identity_and_execution_feasibility_can_exclude_a_candidate(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        gates = policy["candidate_eligibility_gates"]

        self.assertEqual(
            gates["official_identity"],
            "EXACT_SAME_UNDERLYING_VERIFIED_PER_VENUE",
        )
        self.assertTrue(gates["public_market_exists_on_each_required_venue"])
        self.assertTrue(gates["required_data_complete"])
        self.assertTrue(gates["quality_liquidity_and_cost_gates_apply"])
        self.assertEqual(gates["asset_category_may_exclude"], [])
        self.assertEqual(policy["current_venue_scope"], ["mexc", "gateio"])
        self.assertFalse(policy["venue_scope_changed_by_this_policy"])

    def test_policy_hash_is_canonical_and_self_consistent(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        expected = policy.pop("policy_hash")

        self.assertEqual(
            policy["policy_hash_method"],
            "sha256_canonical_json_excluding_policy_hash",
        )
        self.assertEqual(expected, _canonical_hash(policy))


if __name__ == "__main__":
    unittest.main()
