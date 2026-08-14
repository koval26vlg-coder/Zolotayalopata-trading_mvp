from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from slow_liquidity_official_identity_proposal import (  # noqa: E402
    EXPECTED_BASES,
    IdentityProposalError,
    build_proposal,
    canonical_hash,
    validate_proposal,
)


class SlowLiquidityOfficialIdentityProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.proposal = build_proposal(ROOT, "2026-08-13T06:40:00Z")

    def test_planonly_is_hash_bound_and_does_not_authorize_network(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        validate_proposal(proposal, ROOT)

        self.assertEqual(proposal["proposal_hash"], canonical_hash(proposal))
        self.assertEqual(
            tuple(proposal["verification_scope"]["bases"]), EXPECTED_BASES
        )
        self.assertFalse(
            proposal["authorization_now"]["actual_network_run_allowed"]
        )
        self.assertFalse(proposal["authorization_now"]["identity_claim_allowed"])
        self.assertTrue(
            proposal["authorization_now"]["exact_user_approval_required"]
        )

    def test_symbol_or_name_match_cannot_be_identity_evidence(self) -> None:
        for field in (
            "ticker_match_is_identity_evidence",
            "asset_name_match_is_identity_evidence",
        ):
            with self.subTest(field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal["identity_contract"][field] = True
                proposal["proposal_hash"] = canonical_hash(proposal)
                with self.assertRaises(IdentityProposalError):
                    validate_proposal(proposal, ROOT)

    def test_wrapped_or_economic_equivalence_cannot_replace_identifier(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["identity_contract"][
            "economic_or_wrapped_asset_equivalence_allowed"
        ] = True
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "equivalence"):
            validate_proposal(proposal, ROOT)

    def test_request_runtime_and_output_caps_are_frozen(self) -> None:
        mutations = {
            "maximum_total_http_requests": 41,
            "max_runtime_sec": 601,
            "hard_output_cap_bytes": 20_000_001,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal["official_source_contract"][field] = value
                proposal["proposal_hash"] = canonical_hash(proposal)
                with self.assertRaises(IdentityProposalError):
                    validate_proposal(proposal, ROOT)

    def test_redirects_raw_payloads_and_market_values_remain_forbidden(self) -> None:
        fields = (
            "http_redirect_following_allowed",
            "raw_response_persistence_allowed",
            "prices_or_funding_rates_persisted_allowed",
        )
        for field in fields:
            with self.subTest(field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal["official_source_contract"][field] = True
                proposal["proposal_hash"] = canonical_hash(proposal)
                with self.assertRaises(IdentityProposalError):
                    validate_proposal(proposal, ROOT)

    def test_any_current_authorization_without_exact_approval_is_rejected(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["authorization_now"]["official_source_content_read_allowed"] = True
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "unauthorized action"):
            validate_proposal(proposal, ROOT)

    def test_tampered_source_binding_fails_closed(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["source_bindings"]["technical_quality"]["file_sha256"] = "0" * 64
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "bound source changed"):
            validate_proposal(proposal, ROOT)

    def test_proposal_hash_tampering_is_rejected(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["objective"] = "tampered"
        with self.assertRaisesRegex(IdentityProposalError, "proposal hash mismatch"):
            validate_proposal(proposal, ROOT)

    def test_missing_source_binding_is_rejected(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        del proposal["source_bindings"]["technical_quality"]
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "binding set"):
            validate_proposal(proposal, ROOT)

    def test_execution_cannot_be_authorized_by_phase_one_approval(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["authorized_scope_after_exact_approval"][
            "one_visible_public_read_only_identity_run"
        ] = True
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "execution scope"):
            validate_proposal(proposal, ROOT)

    def test_output_overwrite_and_runtime_retry_are_rejected(self) -> None:
        mutations = (
            ("output_contract", "overwrite_allowed", True),
            ("runtime_contract_after_approval", "preflight_only_required", False),
            (
                "runtime_contract_after_approval",
                "stopped_incomplete_retry_authorized",
                True,
            ),
        )
        for block, field, value in mutations:
            with self.subTest(block=block, field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal[block][field] = value
                proposal["proposal_hash"] = canonical_hash(proposal)
                with self.assertRaises(IdentityProposalError):
                    validate_proposal(proposal, ROOT)

    def test_required_identifier_evidence_cannot_be_removed(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["identity_contract"]["required_per_venue"].remove(
            "evidence_locator_value"
        )
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "identity evidence"):
            validate_proposal(proposal, ROOT)

    def test_partial_universe_or_symbol_blacklist_is_rejected(self) -> None:
        mutations = (
            ("all_bases_must_be_reviewed", False),
            ("category_exclusions_allowed", True),
            ("symbol_blacklist_allowed", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal["verification_scope"][field] = value
                proposal["proposal_hash"] = canonical_hash(proposal)
                with self.assertRaises(IdentityProposalError):
                    validate_proposal(proposal, ROOT)

    def test_unofficial_evidence_host_or_method_is_rejected(self) -> None:
        mutations = (
            ("evidence_hosts", 0, "host", "example.com"),
            ("metadata_endpoints", 1, "method", "POST"),
        )
        for collection, index, field, value in mutations:
            with self.subTest(collection=collection, field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal["official_source_contract"][collection][index][field] = value
                proposal["proposal_hash"] = canonical_hash(proposal)
                with self.assertRaises(IdentityProposalError):
                    validate_proposal(proposal, ROOT)

    def test_search_navigation_cannot_be_promoted_to_identity_evidence(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["official_source_contract"][
            "search_or_navigation_output_is_identity_evidence"
        ] = True
        proposal["proposal_hash"] = canonical_hash(proposal)
        with self.assertRaisesRegex(IdentityProposalError, "search output"):
            validate_proposal(proposal, ROOT)

    def test_checked_in_draft_matches_generator(self) -> None:
        path = (
            ROOT
            / "docs/plans/drafts/slow-liquidity-official-asset-identity-"
            "verification-proposal-20260813-v1.json"
        )
        checked_in = json.loads(path.read_text(encoding="utf-8"))
        generated = build_proposal(ROOT, checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)


if __name__ == "__main__":
    unittest.main()
