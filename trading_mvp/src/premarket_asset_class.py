"""Which acceptance universe an instrument belongs to, and why it is never guessed.

Measured 2026-08-24 against the live venues: **none of the three exposes an asset class
on its instruments endpoint.** Gate carries no such field at all - its nine pre-market
contracts and BTC_USDT alike report ``type: "direct"``, differing only in
``leverage_max`` (10 against 200), which is a risk parameter and not a class. Bybit's
``isPreListing`` and OKX's ``ruleType=pre_market`` mark ANTHROPIC exactly as they would
mark a crypto token.

So classification cannot be derived from venue metadata, and a collector must not
pretend otherwise.

The failure that made this module necessary: the crypto pre-market track accepted
anything carrying a pre-market marker, and so collected ANTHROPICUSDT on Bybit,
ANDURIL_USDT on Gate and twenty-one OKX contracts - the same instruments the Pre-IPO
track was collecting in parallel. One instrument was landing in two supposedly
independent acceptance universes, which makes both counts meaningless: the samples are
neither independent nor about the same thing.

Hence the rule here: **unclassified is its own answer, not a synonym for crypto.** An
instrument enters an acceptance universe only when something outside venue metadata says
which one it belongs to. Defaulting to crypto is exactly the bug this replaces.
"""

from __future__ import annotations

import re
from typing import Iterable

ASSET_CLASS_CRYPTO_TOKEN = "crypto_token"
ASSET_CLASS_EQUITY_PREIPO = "equity_preipo"
ASSET_CLASS_UNCLASSIFIED = "unclassified"

ASSET_CLASSES = (
    ASSET_CLASS_CRYPTO_TOKEN,
    ASSET_CLASS_EQUITY_PREIPO,
    ASSET_CLASS_UNCLASSIFIED,
)

# Underlyings declared as equity - private companies whose "listing" is an IPO, or
# tokenised shares of public ones. Declared rather than detected, because no venue
# endpoint distinguishes them; the evidence is the venues' own announcement wording,
# e.g. Bybit's "New listing: MOONSHOT Pre-IPO Perpetual Contract on Bybit".
#
# Adding a name here is a review decision. Removing one is too.
DECLARED_EQUITY_PREIPO_UNDERLYINGS: frozenset[str] = frozenset({
    "ANDURIL",     # private defence company
    "ANTHROPIC",   # private
    "BP",          # tokenised equity of a listed company, not a crypto token
    "KALSHI",      # private
    "KIMI",        # Moonshot AI product line, private
    "MOONSHOT",    # private; Bybit's announcement calls it Pre-IPO
    "NEURALINK",   # private
    "OPENAI",      # private
    "POLYMARKET",  # private
    "QNTX",        # private
    "SPACEX",      # private; Crypto.com, Coinbase and BitMEX all list a SpaceX pre-IPO
                   # perpetual, BitMEX under the ticker SPCX - see UNDERLYING_ALIASES
})

# Venue tickers that name a company already declared above under a different string.
# Without this the same company reaches classification as two different underlyings, so
# it would be counted as two distinct events and could sit in two acceptance samples at
# once - the very thing this module exists to prevent. Declared, never inferred: a
# guessed alias would silently merge two genuinely different assets, which is worse than
# leaving one unclassified.
UNDERLYING_ALIASES: dict[str, str] = {
    "SPCX": "SPACEX",   # BitMEX SPCXUSDT
}

_QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH")
_SEPARATORS = re.compile(r"[-_/]")


def underlying_of(contract_id: str) -> str:
    """The bare underlying behind a venue's contract id.

    BYBIT ANTHROPICUSDT, OKX ANTHROPIC-USDT-SWAP and Gate ANTHROPIC_USDT all name the
    same company; a classification that depended on venue spelling would classify one
    of them and miss the others."""
    text = str(contract_id or "").strip().upper()
    if not text:
        return ""
    head = _SEPARATORS.split(text)[0]
    for quote in _QUOTES:
        if head.endswith(quote) and len(head) > len(quote):
            head = head[: -len(quote)]
            break
    return UNDERLYING_ALIASES.get(head, head)


def classify_underlying(
    underlying: str,
    *,
    equity_underlyings: Iterable[str] | None = None,
    crypto_underlyings: Iterable[str] | None = None,
) -> str:
    """Classify a bare underlying, refusing to guess.

    Only the declared equity set is recognised. Everything else is UNCLASSIFIED - not
    crypto - because nothing observed so far positively establishes that an instrument
    is a crypto token."""
    name = str(underlying or "").strip().upper()
    if not name:
        return ASSET_CLASS_UNCLASSIFIED
    declared = (
        DECLARED_EQUITY_PREIPO_UNDERLYINGS
        if equity_underlyings is None
        else frozenset(str(x).strip().upper() for x in equity_underlyings)
    )
    attested_crypto = frozenset(
        str(item).strip().upper() for item in (crypto_underlyings or ()) if str(item).strip()
    )
    # Contradictory identity evidence is not resolved by precedence.  It must be
    # reviewed at the registry boundary before this classifier can accept it.
    if name in declared and name in attested_crypto:
        return ASSET_CLASS_UNCLASSIFIED
    if name in declared:
        return ASSET_CLASS_EQUITY_PREIPO
    if name in attested_crypto:
        return ASSET_CLASS_CRYPTO_TOKEN
    return ASSET_CLASS_UNCLASSIFIED


def classify_contract(
    contract_id: str,
    *,
    equity_underlyings: Iterable[str] | None = None,
    crypto_underlyings: Iterable[str] | None = None,
) -> str:
    return classify_underlying(
        underlying_of(contract_id),
        equity_underlyings=equity_underlyings,
        crypto_underlyings=crypto_underlyings,
    )


def belongs_to(contract_id: str, acceptance_class: str, **kwargs: object) -> bool:
    """Whether this contract may enter the named acceptance universe.

    An unclassified instrument belongs to none of them. It may still be observed
    descriptively - refusing to classify is not refusing to look - but it must not be
    counted as a sample of a strategy whose asset class nobody has established."""
    if acceptance_class not in ASSET_CLASSES:
        raise ValueError(f"unknown acceptance class: {acceptance_class}")
    if acceptance_class == ASSET_CLASS_UNCLASSIFIED:
        raise ValueError("UNCLASSIFIED is not an acceptance universe")
    return classify_contract(contract_id, **kwargs) == acceptance_class  # type: ignore[arg-type]
