from __future__ import annotations

import ast

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

# Modules that actually open a connection. urllib.parse is not among them: parsing a URL
# to check which host published a claim is the opposite of fetching from it, and a check
# that forbade the whole urllib package would forbid reading the evidence carefully.
NETWORK_MODULES = (
    "requests",
    "urllib.request",
    "urllib.error",
    "http.client",
    "socket",
    "aiohttp",
    "httpx",
    "websockets",
)


def _imported_modules(path: Path) -> set[str]:
    """Every module this file imports, by full dotted name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


# An undeclared base on purpose. SWARM and its three companions were declared on
# 2026-08-26, so proposing about them now correctly returns nothing - which would make
# every case below test the "already settled" path instead of the mechanism.
UNDECLARED_BASE = "NEWCOIN"


def evidence(**overrides) -> VenueAssetEvidence:
    payload = {
        "exchange": "bitget",
        "base": UNDECLARED_BASE,
        "source_url": "https://api.bitget.com/api/v2/spot/public/coins?coin=NEWCOIN",
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
        self.assertEqual(UNDECLARED_BASE, proposal.base)
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
            "base": UNDECLARED_BASE,
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
            "https://api.coingecko.com/api/v3/coins/newcoin",
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

    def test_an_instrument_the_equity_heuristic_recognises_is_marked_contested(self) -> None:
        """The heuristic used to veto here. It no longer does, and this pins why.

        Its reference is now the exchange symbol directory rather than 28 curated names,
        which makes the remainder test cheap: of 42 well-known tokens beginning with a
        wrapper letter, 14 have a remainder that is a real listed share. A veto would
        have made every one of them permanently unproposable on the strength of a
        spelling, and silently. The disagreement is recorded instead - loudly enough that
        nobody promotes the proposal without seeing it."""
        proposal = propose_crypto_identity(evidence(exchange="bitget", base="XKO"), now=NOW)
        self.assertIsNotNone(proposal)
        self.assertTrue(proposal.contested_by_equity_heuristic)
        self.assertTrue(any(line.startswith("CONTESTED:") for line in proposal.evidence))
        self.assertTrue(proposal.requires_human_review)

    def test_an_uncontested_proposal_says_so_rather_than_staying_silent(self) -> None:
        proposal = propose_crypto_identity(evidence(exchange="bitget"), now=NOW)
        self.assertIsNotNone(proposal)
        self.assertFalse(proposal.contested_by_equity_heuristic)
        self.assertFalse(any(line.startswith("CONTESTED:") for line in proposal.evidence))

    def test_a_declared_identity_still_ends_the_question_outright(self) -> None:
        """Dropping the veto weakened one thing deliberately; it must not weaken this.

        A hand-reviewed declaration is not a heuristic, and no chain metadata reopens it."""
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

    def test_malformed_evidence_is_an_error_rather_than_a_negative_result(self) -> None:
        with self.assertRaises(CryptoIdentityError):
            propose_crypto_identity({"exchange": "bitget"}, now=NOW)  # type: ignore[arg-type]
        for bad in ({"exchange": ""}, {"base": ""}, {"base": "swarm token"}, {"base": "-"}):
            with self.subTest(bad=bad):
                with self.assertRaises(CryptoIdentityError):
                    propose_crypto_identity(evidence(**bad), now=NOW)

    def test_lowercase_input_is_normalised_without_changing_the_answer(self) -> None:
        proposal = propose_crypto_identity(
            evidence(exchange="BITGET", base=UNDECLARED_BASE.lower()), now=NOW
        )
        assert proposal is not None
        self.assertEqual("bitget", proposal.exchange)
        self.assertEqual(UNDECLARED_BASE, proposal.base)

    def test_review_queue_deduplicates_and_orders(self) -> None:
        queue = review_queue(
            [
                evidence(base="NEWCOIN"),
                evidence(base="NEWCOIN"),
                evidence(base="OTHERCOIN"),
                evidence(base="THIRDCOIN", chains=()),
                evidence(base="SWARM"),
            ],
            now=NOW,
        )
        # SWARM is declared, so it is absent: a settled identity is not a question.
        self.assertEqual(
            [("bitget", "NEWCOIN"), ("bitget", "OTHERCOIN")],
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
        # Four of these were declared on 2026-08-26 and drop out; TMX did not and stays.
        observed = [
            ("bitget", "ALIGN"), ("bitget", "DGAI"), ("bitget", "PWT"),
            ("bitget", "SWARM"), ("bitget", "TMX"), ("okx", "XCRM"), ("bitget", "tmx"),
        ]
        self.assertEqual([("bitget", "TMX")], unresolved_bases(observed))

    def test_the_module_performs_no_collection(self) -> None:
        # Checked against the imports rather than the text. A substring search would
        # also match the word in prose or in a field name, reporting a network
        # dependency that is not there - and would miss one hidden behind an alias.
        imported = _imported_modules(SRC_ROOT / "listing_spot_crypto_identity.py")
        for forbidden in NETWORK_MODULES:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imported)
        # And it does read URLs, which is the point: it checks who published the claim.
        self.assertIn("urllib.parse", imported)


if __name__ == "__main__":
    unittest.main()
