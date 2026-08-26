"""A heuristic may propose. It may not decide, and it may not widen acceptance.

The declared registries are hand-maintained and cover OKX only, so the same tokenised
share on Bitget falls to unclassified. This heuristic removes that toil, and these tests
pin the three properties that stop it removing the safety with it.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import listing_asset_class_heuristic as heuristic  # noqa: E402
from listing_spot_asset_class import (  # noqa: E402
    ASSET_CLASS_CRYPTO_TOKEN,
    ASSET_CLASS_TOKENIZED_EQUITY,
    DECLARATION_SOURCE,
    classify_spot_asset,
)


class DirectionTests(unittest.TestCase):
    """A wrong proposal must cost coverage, never correctness."""

    def test_the_heuristic_can_never_propose_crypto(self):
        # Proposing crypto would let a ticker shape reach the acceptance universe -
        # the defect that had the crypto track collecting ANTHROPIC.
        with self.assertRaisesRegex(ValueError, "may only propose tokenized_equity"):
            heuristic.ClassificationProposal(
                exchange="bitget", base="XCRM", proposed_class=ASSET_CLASS_CRYPTO_TOKEN
            )

    def test_every_proposal_the_module_makes_is_equity(self):
        observed = [("bitget", "XCRM"), ("binance", "XKO"), ("bybit", "XRDDT")]
        for proposal in heuristic.review_queue(observed):
            with self.subTest(base=proposal.base):
                self.assertEqual(proposal.proposed_class, ASSET_CLASS_TOKENIZED_EQUITY)

    def test_a_proposal_cannot_be_mistaken_for_a_classification(self):
        """It carries neither acceptance_eligible nor the declaration source."""
        proposal = heuristic.propose("bitget", "XCRM")
        self.assertIsNotNone(proposal)
        fields = {f.name for f in dataclasses.fields(proposal)}
        self.assertNotIn("acceptance_eligible", fields)
        self.assertNotIn("source", fields)
        self.assertIs(proposal.requires_human_review, True)

    def test_a_proposal_does_not_change_what_the_classifier_says(self):
        # Until a human promotes it into the registry, the answer is unchanged.
        before = classify_spot_asset("bitget", "XCRM")
        heuristic.propose("bitget", "XCRM")
        after = classify_spot_asset("bitget", "XCRM")
        self.assertEqual(before, after)
        self.assertFalse(after.acceptance_eligible)


class EvidenceTests(unittest.TestCase):
    def test_a_leading_x_alone_is_not_evidence(self):
        """XMR and XRP are the casualties a prefix rule would take."""
        for base in ("XMR", "XRP", "XLM", "XTZ"):
            with self.subTest(base=base):
                self.assertIsNone(heuristic.propose("bitget", base))

    def test_the_wrapper_and_a_known_ticker_together_are_evidence(self):
        proposal = heuristic.propose("bitget", "XCRM")
        self.assertIsNotNone(proposal)
        self.assertEqual(len(proposal.evidence), 2)
        self.assertIn("CRM", proposal.evidence[1])

    def test_an_ordinary_symbol_yields_nothing(self):
        for base in ("BTC", "ALIGN", "SWARM", "ETH"):
            with self.subTest(base=base):
                self.assertIsNone(heuristic.propose("okx", base))

    def test_an_unknown_remainder_yields_nothing_rather_than_a_weak_proposal(self):
        self.assertIsNone(heuristic.propose("bitget", "XNOTATICKER"))


class GeneralisationTests(unittest.TestCase):
    def test_one_venues_curation_reaches_the_others(self):
        """The point of the exercise: 28 companies reviewed once on OKX."""
        reference = heuristic.derive_equity_ticker_reference()
        self.assertEqual(len(reference), 28)
        for venue in ("bitget", "binance", "bybit"):
            with self.subTest(venue=venue):
                self.assertIsNotNone(heuristic.propose(venue, "XCRM"))

    def test_an_already_declared_instrument_produces_no_proposal(self):
        # OKX:XCRM is settled; there is nothing to propose about it.
        self.assertIsNone(heuristic.propose("okx", "XCRM"))

    def test_the_queue_is_deduplicated_and_ordered(self):
        observed = [
            ("bitget", "XKO"),
            ("bitget", "XCRM"),
            ("bitget", "XKO"),
            ("binance", "XCRM"),
        ]
        queue = heuristic.review_queue(observed)
        self.assertEqual(
            [(p.exchange, p.base) for p in queue],
            [("binance", "XCRM"), ("bitget", "XCRM"), ("bitget", "XKO")],
        )

    def test_a_caller_supplied_reference_overrides_the_bootstrap(self):
        queue = heuristic.review_queue(
            [("bitget", "XAAPL"), ("bitget", "XCRM")], equity_tickers=["AAPL"]
        )
        self.assertEqual([p.base for p in queue], ["XAAPL"])


if __name__ == "__main__":
    unittest.main()
