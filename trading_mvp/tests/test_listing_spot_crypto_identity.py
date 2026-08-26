from __future__ import annotations

import sys
import unittest
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from listing_spot_asset_class import (  # noqa: E402
    ASSET_CLASS_CRYPTO_TOKEN,
    ASSET_CLASS_TOKENIZED_EQUITY,
    DECLARATION_SOURCE,
    SpotAssetClassification,
)
from listing_spot_crypto_identity import (  # noqa: E402
    ChainListing,
    CryptoIdentityError,
    CryptoIdentityProposal,
    VenueAssetEvidence,
    propose_crypto_identity,
    review_queue,
    unresolved_bases,
)

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def evidence(**overrides) -> VenueAssetEvidence:
    payload = {
        "exchange": "bitget",
        "base": "SWARM",
        "source_url": "https://api.bitget.com/api/v2/spot/public/coins?coin=SWARM",
        "observed_at_utc": "2026-08-26T11:00:00Z",
        "chains": (
            ChainListing(
                network="Ethereum",
                contract_address="0xabc0000000000000000000000000000000000001",
                deposit_enabled=True,
                withdraw_enabled=True,
            ),
        ),
    }
    payload.update(overrides)
    return VenueAssetEvidence(**payload)


class CryptoIdentityProposalTests(unittest.TestCase):
    def test_venue_published_two_way_chain_movement_supports_a_proposal(self) -> None:
        proposal = propose_crypto_identity(evidence(), now=NOW)
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual("bitget", proposal.exchange)
        self.assertEqual("SWARM", proposal.base)
        self.assertEqual(ASSET_CLASS_CRYPTO_TOKEN, proposal.proposed_class)
        self.assertEqual(("Ethereum",), proposal.supporting_networks)
        self.assertTrue(proposal.requires_human_review)
        self.assertTrue(any("Ethereum" in reason for reason in proposal.evidence))

    def test_a_proposal_cannot_stand_in_for_a_decided_classification(self) -> None:
        names = {item.name for item in fields(CryptoIdentityProposal)}
        self.assertNotIn("acceptance_eligible", names)
        self.assertNotIn("source", names)
        decided = {item.name for item in fields(SpotAssetClassification)}
        self.assertIn("acceptance_eligible", decided)
        proposal = propose_crypto_identity(evidence(), now=NOW)
        assert proposal is not None
        self.assertNotIn(DECLARATION_SOURCE, str(proposal))

    def test_proposal_refuses_to_be_built_for_any_other_class_or_without_review(self) -> None:
        common = {
            "exchange": "bitget",
            "base": "SWARM",
            "supporting_networks": ("Ethereum",),
            "source_url": "https://api.bitget.com/x",
            "observed_at_utc": "2026-08-26T11:00:00Z",
        }
        with self.assertRaisesRegex(ValueError, "crypto_token only"):
            CryptoIdentityProposal(proposed_class=ASSET_CLASS_TOKENIZED_EQUITY, **common)
        with self.assertRaisesRegex(ValueError, "subject to review"):
            CryptoIdentityProposal(
                proposed_class=ASSET_CLASS_CRYPTO_TOKEN,
                requires_human_review=False,
                **common,
            )
        with self.assertRaisesRegex(ValueError, "name the networks"):
            CryptoIdentityProposal(
                proposed_class=ASSET_CLASS_CRYPTO_TOKEN,
                **{**common, "supporting_networks": ()},
            )

    def test_one_way_movement_is_not_enough(self) -> None:
        for chain in (
            ChainListing(network="Ethereum", deposit_enabled=True, withdraw_enabled=False),
            ChainListing(network="Ethereum", deposit_enabled=False, withdraw_enabled=True),
            ChainListing(network="", deposit_enabled=True, withdraw_enabled=True),
        ):
            with self.subTest(chain=chain):
                self.assertIsNone(
                    propose_crypto_identity(evidence(chains=(chain,)), now=NOW)
                )

    def test_no_chains_at_all_is_the_resting_state_not_an_error(self) -> None:
        self.assertIsNone(propose_crypto_identity(evidence(chains=()), now=NOW))

    def test_a_native_asset_without_a_contract_address_still_qualifies(self) -> None:
        proposal = propose_crypto_identity(
            evidence(
                base="BTC",
                chains=(
                    ChainListing(
                        network="Bitcoin", deposit_enabled=True, withdraw_enabled=True
                    ),
                ),
            ),
            now=NOW,
        )
        assert proposal is not None
        self.assertEqual(("Bitcoin",), proposal.supporting_networks)
        self.assertTrue(
            any("native chain asset" in reason for reason in proposal.evidence),
            proposal.evidence,
        )

    def test_only_the_venue_may_make_the_claim(self) -> None:
        for url in (
            "https://api.coingecko.com/api/v3/coins/swarm",
            "https://bitget.example.com/coins",
            "http://api.bitget.com/api/v2/spot/public/coins",
            "https://api.binance.com/sapi/v1/capital/config/getall",
            "not a url",
            "",
        ):
            with self.subTest(url=url):
                self.assertIsNone(propose_crypto_identity(evidence(source_url=url), now=NOW))

    def test_an_unknown_venue_has_no_trusted_host_and_so_no_proposal(self) -> None:
        self.assertIsNone(
            propose_crypto_identity(
                evidence(exchange="mexc", source_url="https://api.mexc.com/coins"), now=NOW
            )
        )

    def test_stale_naive_or_future_observations_are_refused(self) -> None:
        for observed in (
            "2026-06-01T11:00:00Z",
            "2026-08-26T11:00:00",
            "2026-08-27T11:00:00Z",
            "not a timestamp",
            "",
        ):
            with self.subTest(observed=observed):
                self.assertIsNone(
                    propose_crypto_identity(evidence(observed_at_utc=observed), now=NOW)
                )

    def test_the_age_bound_is_the_callers_to_set_and_is_enforced(self) -> None:
        old = (NOW - timedelta(days=20)).isoformat().replace("+00:00", "Z")
        self.assertIsNotNone(
            propose_crypto_identity(evidence(observed_at_utc=old), now=NOW, max_age_days=30)
        )
        self.assertIsNone(
            propose_crypto_identity(evidence(observed_at_utc=old), now=NOW, max_age_days=7)
        )

    def test_an_already_declared_identity_is_not_reopened(self) -> None:
        # XCRM is declared tokenised equity on OKX; chain metadata must not overturn a
        # declaration, in either direction.
        self.assertIsNone(
            propose_crypto_identity(
                evidence(
                    exchange="okx",
                    base="XCRM",
                    source_url="https://www.okx.com/api/v5/asset/currencies?ccy=XCRM",
                ),
                now=NOW,
            )
        )

    def test_an_instrument_the_equity_heuristic_recognises_is_never_proposed(self) -> None:
        # XKO on Bitget is undeclared there, but the wrapper plus a reviewed ticker is
        # exactly the equity signal; the two proposals must not disagree in silence.
        self.assertIsNone(
            propose_crypto_identity(evidence(exchange="bitget", base="XKO"), now=NOW)
        )

    def test_malformed_evidence_is_an_error_rather_than_a_negative_result(self) -> None:
        with self.assertRaises(CryptoIdentityError):
            propose_crypto_identity({"exchange": "bitget"}, now=NOW)  # type: ignore[arg-type]
        for bad in ({"exchange": ""}, {"base": ""}, {"base": "swarm token"}, {"base": "-"}):
            with self.subTest(bad=bad):
                with self.assertRaises(CryptoIdentityError):
                    propose_crypto_identity(evidence(**bad), now=NOW)

    def test_lowercase_input_is_normalised_without_changing_the_answer(self) -> None:
        proposal = propose_crypto_identity(
            evidence(exchange="BITGET", base="swarm"), now=NOW
        )
        assert proposal is not None
        self.assertEqual("bitget", proposal.exchange)
        self.assertEqual("SWARM", proposal.base)

    def test_review_queue_deduplicates_and_orders(self) -> None:
        queue = review_queue(
            [
                evidence(base="SWARM"),
                evidence(base="SWARM"),
                evidence(base="ALIGN"),
                evidence(base="DGAI", chains=()),
            ],
            now=NOW,
        )
        self.assertEqual(
            [("bitget", "ALIGN"), ("bitget", "SWARM")],
            [(item.exchange, item.base) for item in queue],
        )

    def test_multiple_networks_are_reported_sorted_and_deduplicated(self) -> None:
        proposal = propose_crypto_identity(
            evidence(
                chains=(
                    ChainListing(network="Polygon", deposit_enabled=True, withdraw_enabled=True),
                    ChainListing(network="Ethereum", deposit_enabled=True, withdraw_enabled=True),
                    ChainListing(network="Ethereum", deposit_enabled=True, withdraw_enabled=True),
                    ChainListing(network="Solana", deposit_enabled=True, withdraw_enabled=False),
                )
            ),
            now=NOW,
        )
        assert proposal is not None
        self.assertEqual(("Ethereum", "Polygon"), proposal.supporting_networks)

    def test_unresolved_bases_names_what_the_track_is_blocked_on(self) -> None:
        observed = [
            ("bitget", "ALIGN"), ("bitget", "DGAI"), ("bitget", "PWT"),
            ("bitget", "SWARM"), ("bitget", "TMX"), ("okx", "XCRM"), ("bitget", "align"),
        ]
        self.assertEqual(
            [("bitget", "ALIGN"), ("bitget", "DGAI"), ("bitget", "PWT"),
             ("bitget", "SWARM"), ("bitget", "TMX")],
            unresolved_bases(observed),
        )

    def test_the_module_performs_no_collection(self) -> None:
        source = (SRC_ROOT / "listing_spot_crypto_identity.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib.request", "http.client", "socket"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
