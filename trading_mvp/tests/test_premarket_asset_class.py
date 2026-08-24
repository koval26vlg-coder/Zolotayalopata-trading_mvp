"""An instrument may not enter two acceptance universes, nor be guessed into one.

Measured 2026-08-24: no venue exposes an asset class on its instruments endpoint. Gate
has no such field at all - its nine pre-market contracts and BTC_USDT alike report
type "direct". Bybit's isPreListing and OKX's ruleType=pre_market mark ANTHROPIC exactly
as they would mark a crypto token.

Because of that the crypto pre-market track was collecting ANTHROPICUSDT, ANDURIL_USDT
and the OKX equity contracts that the Pre-IPO track was collecting in parallel. These
tests pin the rule that ends it: unclassified is its own answer, never a synonym for
crypto.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from premarket_asset_class import (  # noqa: E402
    ASSET_CLASS_CRYPTO_TOKEN,
    ASSET_CLASS_EQUITY_PREIPO,
    ASSET_CLASS_UNCLASSIFIED,
    belongs_to,
    classify_contract,
    underlying_of,
)


class UnderlyingTests(unittest.TestCase):
    def test_the_same_company_is_recognised_in_every_venue_spelling(self):
        # A classification that depended on venue spelling would catch one and miss two.
        for contract_id in ("ANTHROPICUSDT", "ANTHROPIC-USDT-SWAP", "ANTHROPIC_USDT"):
            with self.subTest(contract_id=contract_id):
                self.assertEqual(underlying_of(contract_id), "ANTHROPIC")

    def test_quote_suffixes_are_stripped_only_when_they_are_suffixes(self):
        self.assertEqual(underlying_of("BTCUSDT"), "BTC")
        self.assertEqual(underlying_of("USDTUSDT"), "USDT")

    def test_an_empty_contract_id_yields_nothing(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(underlying_of(value), "")


class ClassificationTests(unittest.TestCase):
    def test_every_declared_equity_underlying_is_recognised(self):
        for contract_id in ("ANTHROPICUSDT", "ANDURIL_USDT", "OPENAI-USDT-SWAP",
                            "KALSHI_USDT", "NEURALINK_USDT", "POLYMARKET_USDT",
                            "MOONSHOTUSDT", "KIMI_USDT", "QNTX_USDT", "BP_USDT"):
            with self.subTest(contract_id=contract_id):
                self.assertEqual(classify_contract(contract_id), ASSET_CLASS_EQUITY_PREIPO)

    def test_an_ordinary_token_is_unclassified_rather_than_crypto(self):
        # The heart of it: nothing observed positively establishes "crypto", so the
        # collector must not infer it. Defaulting to crypto is the bug being removed.
        for contract_id in ("BTCUSDT", "SOME_USDT", "NEWTOKEN-USDT-SWAP"):
            with self.subTest(contract_id=contract_id):
                self.assertEqual(classify_contract(contract_id), ASSET_CLASS_UNCLASSIFIED)

    def test_case_and_separator_do_not_change_the_verdict(self):
        for contract_id in ("anthropicusdt", "Anthropic_USDT", "ANTHROPIC-usdt-swap"):
            with self.subTest(contract_id=contract_id):
                self.assertEqual(classify_contract(contract_id), ASSET_CLASS_EQUITY_PREIPO)


class AcceptanceMembershipTests(unittest.TestCase):
    def test_equity_never_enters_the_crypto_universe(self):
        for contract_id in ("ANTHROPICUSDT", "ANDURIL_USDT", "OPENAI-USDT-SWAP"):
            with self.subTest(contract_id=contract_id):
                self.assertFalse(belongs_to(contract_id, ASSET_CLASS_CRYPTO_TOKEN))

    def test_equity_enters_the_equity_universe(self):
        self.assertTrue(belongs_to("ANTHROPICUSDT", ASSET_CLASS_EQUITY_PREIPO))

    def test_an_unclassified_instrument_enters_neither(self):
        # Not one, not the other, and above all not both.
        self.assertFalse(belongs_to("BTCUSDT", ASSET_CLASS_CRYPTO_TOKEN))
        self.assertFalse(belongs_to("BTCUSDT", ASSET_CLASS_EQUITY_PREIPO))

    def test_no_instrument_can_belong_to_both_universes(self):
        for contract_id in ("ANTHROPICUSDT", "BTCUSDT", "ANDURIL_USDT", "SOME_USDT"):
            with self.subTest(contract_id=contract_id):
                memberships = [
                    belongs_to(contract_id, ASSET_CLASS_CRYPTO_TOKEN),
                    belongs_to(contract_id, ASSET_CLASS_EQUITY_PREIPO),
                ]
                self.assertLessEqual(
                    sum(memberships), 1,
                    f"{contract_id} entered two acceptance universes",
                )

    def test_unclassified_is_not_itself_an_acceptance_universe(self):
        with self.assertRaises(ValueError):
            belongs_to("BTCUSDT", ASSET_CLASS_UNCLASSIFIED)

    def test_an_unknown_acceptance_class_is_refused(self):
        with self.assertRaises(ValueError):
            belongs_to("BTCUSDT", "something_else")


class CollectorGateTests(unittest.TestCase):
    """The gate as the collector actually applies it."""

    def _bybit(self, symbol):
        return {
            "symbol": symbol,
            "quoteCoin": "USDT",
            "baseCoin": symbol.replace("USDT", ""),
            "status": "PreLaunch",
            "isPreListing": True,
            "contractType": "LinearPerpetual",
            "launchTime": "1800000000000",
        }

    def test_the_crypto_collector_drops_equity_instruments(self):
        import premarket_perp

        # This exact payload shape was being accepted before 2026-08-24.
        self.assertIsNone(
            premarket_perp.normalise_contract("bybit", self._bybit("ANTHROPICUSDT"))
        )

    def test_descriptive_normalisation_without_a_gate_still_works(self):
        import premarket_perp

        contract = premarket_perp.normalise_contract(
            "bybit", self._bybit("ANTHROPICUSDT"), acceptance_class=None
        )
        self.assertIsNotNone(contract)
        self.assertEqual(contract.contract_id, "ANTHROPICUSDT")

    def test_the_equity_universe_accepts_what_the_crypto_one_refuses(self):
        import premarket_perp

        contract = premarket_perp.normalise_contract(
            "bybit",
            self._bybit("ANTHROPICUSDT"),
            acceptance_class=ASSET_CLASS_EQUITY_PREIPO,
        )
        self.assertIsNotNone(contract)


if __name__ == "__main__":
    unittest.main()
