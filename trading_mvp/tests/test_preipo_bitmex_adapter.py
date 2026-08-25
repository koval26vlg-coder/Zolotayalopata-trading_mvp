"""BitMEX carries pre-IPO perpetuals but publishes no marker saying so.

Unlike OKX ruleType or Gate's fields, nothing on a BitMEX instrument says "this tracks a
private company". So the only honest test is the declared equity list, and everything
else must be refused rather than guessed - the same rule that stopped the crypto track
collecting ANTHROPIC.

The other thing worth pinning is what BitMEX's `listing` field means. It is when the
instrument was listed on BitMEX: a contract launch, not the underlying's IPO and not an
observed first trade. Recording it as a conversion or an official t0 would recreate the
collapsed-taxonomy defect.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from preipo_adapters import (  # noqa: E402
    BitmexPreIPOAdapter,
    normalize_bitmex_contract,
    normalize_okx_contract,
)


def _instrument(symbol="SPCXUSDT", **overrides):
    item = {
        "symbol": symbol,
        "typ": "FFWCSX",
        "state": "Open",
        "quoteCurrency": "USDT",
        "underlying": "SPCX",
        "listing": "2026-06-01T04:00:00.000Z",
        "maintMargin": 0.02,
        "takerFee": 0.00075,
        "makerFee": -0.00025,
    }
    item.update(overrides)
    return item


class ClassificationTests(unittest.TestCase):
    def test_a_declared_equity_underlying_is_accepted(self):
        contract = normalize_bitmex_contract(_instrument())
        self.assertIsNotNone(contract)
        self.assertEqual(contract.venue, "bitmex")
        self.assertEqual(contract.lifecycle_status, "preipo_continuous")

    def test_a_crypto_instrument_is_refused_rather_than_guessed(self):
        # BitMEX offers no pre-IPO marker, so an undeclared underlying must not be
        # inferred into the sample.
        self.assertIsNone(
            normalize_bitmex_contract(_instrument(symbol="XBTUSD", underlying="XBT"))
        )

    def test_a_non_perpetual_is_refused(self):
        self.assertIsNone(normalize_bitmex_contract(_instrument(typ="FFCCSX")))

    def test_an_empty_symbol_is_refused(self):
        self.assertIsNone(normalize_bitmex_contract(_instrument(symbol="")))


class TimestampMeaningTests(unittest.TestCase):
    def test_listing_is_recorded_as_a_contract_launch(self):
        contract = normalize_bitmex_contract(_instrument())
        self.assertIsNotNone(contract.tradable_ts)
        # Not a conversion: BitMEX publishes none, and inventing one would collapse two
        # different kinds of moment into one field again.
        self.assertIsNone(contract.official_conversion_ts)

    def test_a_missing_listing_leaves_the_launch_unknown(self):
        contract = normalize_bitmex_contract(_instrument(listing=None))
        self.assertIsNotNone(contract)
        self.assertIsNone(contract.tradable_ts)


class CrossVenueIdentityTests(unittest.TestCase):
    def test_bitmex_and_okx_agree_on_the_underlying(self):
        """The point of adding a venue is more events for the same company.

        BitMEX writes SPCX where OKX writes SPACEX. If the raw venue spelling were
        stored, one company would split into two underlyings the moment the second venue
        was added, and the widening would have made the sample worse, not larger."""
        bitmex = normalize_bitmex_contract(_instrument())
        okx = normalize_okx_contract(
            {
                "instId": "SPACEX-USDT-SWAP",
                "ruleType": "pre_market",
                "baseCcy": "SPACEX",
                "quoteCcy": "USDT",
                "state": "live",
            }
        )
        self.assertIsNotNone(okx)
        self.assertEqual(bitmex.underlying_symbol, okx.underlying_symbol)
        self.assertEqual(bitmex.underlying_symbol, "SPACEX")


class LifecycleTests(unittest.TestCase):
    def test_terminal_states_map_to_terminal_lifecycles(self):
        for state, expected in (
            ("Settled", "expired"),
            ("Unlisted", "delisted"),
            ("Closed", "delisted"),
        ):
            with self.subTest(state=state):
                contract = normalize_bitmex_contract(_instrument(state=state))
                self.assertEqual(contract.lifecycle_status, expected)


class AdapterSurfaceTests(unittest.TestCase):
    def test_the_adapter_uses_public_endpoints_only(self):
        self.assertEqual(BitmexPreIPOAdapter.venue, "bitmex")
        self.assertTrue(BitmexPreIPOAdapter.base_url.startswith("https://"))
        self.assertTrue(BitmexPreIPOAdapter.ws_url.startswith("wss://"))

    def test_l2_partial_and_delta_updates_keep_a_causal_bbo(self):
        adapter = BitmexPreIPOAdapter()
        contract = normalize_bitmex_contract(_instrument())
        partial = adapter.normalize_snapshot(
            contract,
            {
                "table": "orderBookL2_25",
                "action": "partial",
                "data": [
                    {"symbol": "SPCXUSDT", "id": 1, "side": "Buy", "size": 4, "price": 10.0},
                    {"symbol": "SPCXUSDT", "id": 2, "side": "Sell", "size": 3, "price": 10.1},
                ],
            },
            received_ts=1_780_000_100.0,
        )
        update = adapter.normalize_snapshot(
            contract,
            {
                "table": "orderBookL2_25",
                "action": "update",
                "data": [{"symbol": "SPCXUSDT", "id": 1, "size": 8}],
            },
            received_ts=1_780_000_101.0,
        )

        self.assertEqual(partial[0]["event_kind"], "bbo")
        self.assertEqual(update[0]["event_kind"], "bbo")
        self.assertEqual(update[0]["bid"], 10.0)
        self.assertEqual(update[0]["bid_qty"], 8.0)
        self.assertEqual(update[0]["ask"], 10.1)


if __name__ == "__main__":
    unittest.main()
