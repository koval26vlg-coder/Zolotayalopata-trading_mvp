"""Kraken Futures carries pre-IPO perpetuals and publishes when each one opened.

Two Kraken specifics are easy to get wrong and are pinned here:

  * `type` is "flexible_futures" for a perpetual; the dated and inverse types are
    different instruments and must not enter the sample.
  * `tradeable` is documented as "True if this instrument is, or has ever been, a
    tradable instrument". It is a history flag, not a liveness flag - using it to decide
    whether a contract is live would keep delisted instruments in the sample forever.

`openingDate` is when the instrument became available for trading: a contract launch,
the same kind of moment as BitMEX's `listing`. It is not the underlying's IPO and not an
observed first trade.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import preipo_adapters as adapters  # noqa: E402
from preipo_adapters import (  # noqa: E402
    ADAPTERS,
    VENUES,
    normalize_bitmex_contract,
    normalize_kraken_contract,
)


def _instrument(**overrides):
    item = {
        "symbol": "PF_SPACEXUSD",
        "type": "flexible_futures",
        "base": "SPACEX",
        "quote": "USD",
        "tradeable": True,
        "isExpired": False,
        "openingDate": "2026-06-15T08:00:00.000Z",
        "marginLevels": [{"initialMargin": 0.05, "maintenanceMargin": 0.025}],
    }
    item.update(overrides)
    return item


class ClassificationTests(unittest.TestCase):
    def test_a_declared_equity_underlying_is_accepted(self):
        contract = normalize_kraken_contract(_instrument())
        self.assertIsNotNone(contract)
        self.assertEqual(contract.venue, "kraken")
        self.assertEqual(contract.underlying_symbol, "SPACEX")

    def test_a_crypto_instrument_is_refused_rather_than_guessed(self):
        self.assertIsNone(
            normalize_kraken_contract(_instrument(symbol="PF_XBTUSD", base="XBT"))
        )

    def test_only_the_perpetual_type_is_collected(self):
        for wrong in ("futures_vanilla", "futures_inverse", "options"):
            with self.subTest(type=wrong):
                self.assertIsNone(normalize_kraken_contract(_instrument(type=wrong)))


class LivenessTests(unittest.TestCase):
    def test_tradeable_is_not_used_as_a_liveness_flag(self):
        """Kraken's `tradeable` means "is, or has ever been" tradable.

        An expired instrument still carries tradeable true, so a normaliser that keyed
        on it would never drop anything."""
        expired = _instrument(tradeable=True, isExpired=True)
        contract = normalize_kraken_contract(expired)
        self.assertEqual(contract.lifecycle_status, "expired")

    def test_a_live_instrument_is_continuous(self):
        contract = normalize_kraken_contract(_instrument(isExpired=False))
        self.assertEqual(contract.lifecycle_status, "preipo_continuous")


class TimestampMeaningTests(unittest.TestCase):
    def test_opening_date_is_recorded_as_a_contract_launch(self):
        contract = normalize_kraken_contract(_instrument())
        self.assertIsNotNone(contract.tradable_ts)
        self.assertIsNone(contract.official_conversion_ts)

    def test_a_missing_opening_date_leaves_the_launch_unknown(self):
        contract = normalize_kraken_contract(_instrument(openingDate=None))
        self.assertIsNotNone(contract)
        self.assertIsNone(contract.tradable_ts)


class CrossVenueIdentityTests(unittest.TestCase):
    def test_kraken_and_bitmex_agree_on_the_underlying(self):
        kraken = normalize_kraken_contract(_instrument())
        bitmex = normalize_bitmex_contract(
            {
                "symbol": "SPCXUSDT",
                "typ": "FFWCSX",
                "state": "Open",
                "quoteCurrency": "USDT",
                "listing": "2026-06-01T04:00:00.000Z",
            }
        )
        self.assertEqual(kraken.underlying_symbol, bitmex.underlying_symbol)


class RegistryTests(unittest.TestCase):
    def test_every_declared_venue_has_an_adapter(self):
        """A venue in VENUES with no entry in ADAPTERS makes the default call raise."""
        self.assertEqual(set(ADAPTERS), set(VENUES))

    def test_the_default_factory_builds_every_venue(self):
        built = adapters.build_public_adapters()
        self.assertEqual(set(built), set(VENUES))

    def test_an_unknown_venue_is_refused(self):
        with self.assertRaises(ValueError):
            adapters.build_public_adapters(["binance"])


class WebSocketBookTests(unittest.TestCase):
    def test_snapshot_and_one_sided_delta_keep_current_bbo(self):
        adapter = adapters.KrakenPreIPOAdapter()
        contract = normalize_kraken_contract(_instrument())
        snapshot = adapter.normalize_snapshot(
            contract,
            {
                "feed": "book_snapshot",
                "product_id": contract.contract_id,
                "seq": 1,
                "bids": [{"price": 20.0, "qty": 4}],
                "asks": [{"price": 20.2, "qty": 5}],
            },
            received_ts=1_780_000_100.0,
        )
        delta = adapter.normalize_snapshot(
            contract,
            {
                "feed": "book",
                "product_id": contract.contract_id,
                "seq": 2,
                "side": "buy",
                "price": 20.1,
                "qty": 3,
            },
            received_ts=1_780_000_101.0,
        )

        self.assertEqual(snapshot[0]["event_kind"], "bbo")
        self.assertEqual(delta[0]["event_kind"], "bbo")
        self.assertEqual(delta[0]["bid"], 20.1)
        self.assertEqual(delta[0]["ask"], 20.2)
        self.assertEqual(delta[0]["sequence"], 2)


if __name__ == "__main__":
    unittest.main()
