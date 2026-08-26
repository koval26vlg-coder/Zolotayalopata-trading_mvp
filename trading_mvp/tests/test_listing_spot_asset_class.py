"""The module that decides crypto eligibility for the whole expansion track.

Four production modules import it - the expansion adapter, evaluator, monitor and plan
generator - and its answer is what admits a window to the acceptance sample or keeps it
descriptive. Its behaviour was not pinned anywhere, so it is pinned here.

The property that matters most is the one that is easy to erode later: an instrument is
acceptance-eligible only on positive crypto identity, and today no such identity is
declared, so nothing is eligible at all. That is an honest empty universe rather than a
permissive default, and a test should notice if it ever stops being empty by accident.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from listing_spot_asset_class import (  # noqa: E402
    ASSET_CLASS_CRYPTO_TOKEN,
    ASSET_CLASS_TOKENIZED_EQUITY,
    ASSET_CLASS_UNCLASSIFIED,
    DECLARATION_SOURCE,
    DECLARED_CRYPTO_TOKEN_BASES,
    DECLARED_TOKENIZED_EQUITY_BASES,
    classify_spot_asset,
)


class FailClosedTests(unittest.TestCase):
    def test_an_unknown_symbol_is_unclassified_and_not_eligible(self):
        result = classify_spot_asset("okx", "SOMENEWTOKEN")
        self.assertEqual(result.asset_class, ASSET_CLASS_UNCLASSIFIED)
        self.assertFalse(result.acceptance_eligible)

    def test_an_unclassified_result_says_why(self):
        # The source distinguishes "declared" from "nobody has decided", which is what
        # lets a reviewer tell a gap from a verdict.
        result = classify_spot_asset("okx", "SOMENEWTOKEN")
        self.assertNotEqual(result.source, DECLARATION_SOURCE)
        self.assertEqual(result.source, "unclassified_no_positive_identity")

    def test_a_declaration_on_one_venue_does_not_leak_to_another(self):
        """XCRM is declared on OKX only; the same symbol elsewhere is undecided."""
        self.assertEqual(
            classify_spot_asset("okx", "XCRM").asset_class,
            ASSET_CLASS_TOKENIZED_EQUITY,
        )
        self.assertEqual(
            classify_spot_asset("bitget", "XCRM").asset_class,
            ASSET_CLASS_UNCLASSIFIED,
        )

    def test_empty_and_blank_inputs_are_unclassified(self):
        for exchange, base in (("", "XCRM"), ("okx", ""), ("", ""), ("okx", "   ")):
            with self.subTest(exchange=exchange, base=base):
                result = classify_spot_asset(exchange, base)
                self.assertEqual(result.asset_class, ASSET_CLASS_UNCLASSIFIED)
                self.assertFalse(result.acceptance_eligible)


class EligibilityTests(unittest.TestCase):
    def test_tokenized_equity_is_never_acceptance_eligible(self):
        for base in sorted(DECLARED_TOKENIZED_EQUITY_BASES["okx"]):
            with self.subTest(base=base):
                result = classify_spot_asset("okx", base)
                self.assertEqual(result.asset_class, ASSET_CLASS_TOKENIZED_EQUITY)
                self.assertFalse(result.acceptance_eligible)

    def test_the_declared_crypto_universe_is_exactly_what_was_reviewed(self):
        """Eligibility comes from a reviewed declaration, never from a default.

        This test used to assert the registry was empty, and it was right to: the
        emptiness was the whole safeguard. It is no longer empty, so it now pins what
        was actually declared. Four Bitget bases were established on 2026-08-26 under
        probe plan listing_spot_crypto_identity_probe_20260826_v2, each because the
        venue publishes two-way movement on a public chain. Anything appearing here
        without that review should fail this test."""
        self.assertEqual({"bitget"}, set(DECLARED_CRYPTO_TOKEN_BASES))
        self.assertEqual(
            frozenset({"ALIGN", "DGAI", "PWT", "SWARM"}),
            DECLARED_CRYPTO_TOKEN_BASES["bitget"],
        )
        for base in sorted(DECLARED_CRYPTO_TOKEN_BASES["bitget"]):
            with self.subTest(base=base):
                result = classify_spot_asset("bitget", base)
                self.assertEqual(result.asset_class, ASSET_CLASS_CRYPTO_TOKEN)
                self.assertTrue(result.acceptance_eligible)

    def test_everything_undeclared_stays_ineligible(self):
        # TMX is the pointed case: it was probed in the same run and not established,
        # because Bitget publishes deposit for it and not withdrawal.
        for venue, base in (
            ("bitget", "TMX"), ("okx", "BTC"), ("bitget", "ETH"), ("binance", "SOL"),
            ("okx", "ALIGN"),
        ):
            with self.subTest(venue=venue, base=base):
                self.assertFalse(classify_spot_asset(venue, base).acceptance_eligible)

    def test_a_declared_crypto_identity_would_be_eligible(self):
        # Pins the contract the future registry must satisfy, without declaring one.
        DECLARED_CRYPTO_TOKEN_BASES["testvenue"] = frozenset({"TESTTOKEN"})
        try:
            result = classify_spot_asset("testvenue", "TESTTOKEN")
            self.assertEqual(result.asset_class, ASSET_CLASS_CRYPTO_TOKEN)
            self.assertEqual(result.source, DECLARATION_SOURCE)
            self.assertTrue(result.acceptance_eligible)
        finally:
            DECLARED_CRYPTO_TOKEN_BASES.pop("testvenue", None)


class NormalisationTests(unittest.TestCase):
    def test_case_and_surrounding_space_do_not_change_the_verdict(self):
        for exchange, base in (("OKX", "xcrm"), (" okx ", " XCRM "), ("Okx", "XcRm")):
            with self.subTest(exchange=exchange, base=base):
                self.assertEqual(
                    classify_spot_asset(exchange, base).asset_class,
                    ASSET_CLASS_TOKENIZED_EQUITY,
                )


if __name__ == "__main__":
    unittest.main()
