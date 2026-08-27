"""Propose asset-class candidates for review. Never decide one.

The declared registries in ``listing_spot_asset_class`` are hand-maintained, so they go
stale the moment a venue lists a new product, and they currently cover OKX only - the
same tokenised equity on Bitget or Binance falls through to ``unclassified``. This module
exists to cut that toil without touching the property that makes the registries worth
having.

Three rules keep it safe, and each is enforced rather than merely intended.

**It proposes equity, never crypto.** A proposal can only ever move an instrument *out*
of the crypto acceptance universe, never into it. There is no ticker shape that
establishes an instrument is a crypto token; believing otherwise is what had the crypto
track collecting ANTHROPIC. So the heuristic can shrink the acceptance universe and can
never grow it, which makes a wrong proposal cost coverage rather than correctness.

**A leading wrapper letter is not the evidence.** ``X`` alone would misclassify any
genuine token whose symbol starts with one - XMR and XRP are the obvious casualties. The
evidence is the wrapper followed by a symbol that is independently a listed share: XCRM
against CRM, RULTA against ULTA. Both halves are required, and a symbol whose remainder
is unknown yields no proposal at all rather than a weak one.

**The reference is narrowed on purpose, and it is still not decisive.** Reading against
the exchange symbol directory rather than against the 28 hand-declared companies is what
lets the fifteen R-wrapped shares on Bitget be recognised at all - but a wide reference
makes the remainder test cheap, because thousands of short tickers exist. Measured over
42 well-known tokens beginning with these letters, the full directory falsely matches 18
and the ordinary-share subset 14: RARE against Alexandria Real Estate, RED against
Consolidated Edison, XAI against C3.ai. So the narrowing helps and does not save it, and
the proposal is explicitly *not* allowed to silently suppress a crypto proposal - see
``listing_spot_crypto_identity``, where a disagreement is recorded rather than resolved.

**Its output is not a classification.** ``ClassificationProposal`` deliberately carries
no ``acceptance_eligible`` and no ``source`` field, so it cannot be substituted for a
``SpotAssetClassification`` anywhere the pipeline expects one. Promoting a proposal into
``DECLARED_TOKENIZED_EQUITY_BASES`` stays a human edit under review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import listing_equity_ticker_reference as equity_reference
from listing_spot_asset_class import (
    ASSET_CLASS_TOKENIZED_EQUITY,
    DECLARED_CRYPTO_TOKEN_BASES,
    DECLARED_TOKENIZED_EQUITY_BASES,
)

# The wrappers venues use for a tokenised share. Held as a tuple so a convention is
# added by review rather than by pattern-matching: ``X`` is OKX's, ``R`` is the one
# Bitget used for the fifteen US shares it listed in August 2026.
TOKENIZED_EQUITY_PREFIXES: tuple[str, ...] = ("X", "R")

PROPOSAL_SOURCE = "heuristic_proposal_not_a_classification"


@dataclass(frozen=True)
class ClassificationProposal:
    """A candidate for the declared registry, and only that.

    It has no acceptance_eligible and no source matching DECLARATION_SOURCE precisely so
    that it cannot be passed where a decided classification is expected."""

    exchange: str
    base: str
    proposed_class: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    requires_human_review: bool = True

    def __post_init__(self) -> None:
        if self.proposed_class != ASSET_CLASS_TOKENIZED_EQUITY:
            raise ValueError(
                "the heuristic may only propose tokenized_equity; proposing crypto "
                "would let a guess reach the acceptance universe"
            )
        if not self.requires_human_review:
            raise ValueError("a proposal is always subject to review")


def derive_equity_ticker_reference(
    declared: Mapping[str, Iterable[str]] | None = None,
) -> frozenset[str]:
    """The equity tickers already implied by what has been declared by hand.

    This is what lets one venue's curation generalise to the others: the 28 companies
    reviewed on OKX become recognisable on Bitget, Binance and Bybit without anyone
    re-typing them. It is a bootstrap, not a market reference - a real listed-equity
    universe should be supplied by the caller when one is available."""
    source = DECLARED_TOKENIZED_EQUITY_BASES if declared is None else declared
    tickers: set[str] = set()
    for bases in source.values():
        for base in bases:
            symbol = str(base).strip().upper()
            for prefix in TOKENIZED_EQUITY_PREFIXES:
                if symbol.startswith(prefix) and len(symbol) > len(prefix):
                    tickers.add(symbol[len(prefix):])
    return frozenset(tickers)


def equity_ticker_reference() -> frozenset[str]:
    """The reference to read a remainder against: the directory, or the bootstrap.

    The frozen snapshot is preferred because it is the thing that actually answers the
    question. When no snapshot has been fetched the bootstrap still works - narrower, so
    fewer proposals, which is the safe direction to fail in - and the caller is never
    left guessing which was used, because the proposal says so in its evidence."""
    declared = derive_equity_ticker_reference()
    if not equity_reference.available():
        return declared
    return declared | equity_reference.common_stock_tickers()


def _reference_origin() -> str:
    return (
        "the exchange symbol directory"
        if equity_reference.available()
        else "the hand-declared registry on another venue"
    )


def _already_settled(exchange: str, base: str) -> bool:
    venue, symbol = exchange.strip().lower(), base.strip().upper()
    for registry in (DECLARED_TOKENIZED_EQUITY_BASES, DECLARED_CRYPTO_TOKEN_BASES):
        if symbol in registry.get(venue, frozenset()):
            return True
    return False


def propose(
    exchange: str,
    base: str,
    *,
    equity_tickers: Iterable[str] | None = None,
) -> ClassificationProposal | None:
    """Propose a tokenised-equity candidate, or nothing.

    Nothing is returned when the instrument is already declared - there is no proposal
    to make about a settled identity - and when the evidence is only a leading X."""
    venue, symbol = str(exchange or "").strip().lower(), str(base or "").strip().upper()
    if not venue or not symbol or _already_settled(venue, symbol):
        return None

    reference = (
        equity_ticker_reference()
        if equity_tickers is None
        else frozenset(str(t).strip().upper() for t in equity_tickers if str(t).strip())
    )
    for prefix in TOKENIZED_EQUITY_PREFIXES:
        if not symbol.startswith(prefix) or len(symbol) <= len(prefix):
            continue
        remainder = symbol[len(prefix):]
        if remainder not in reference:
            # A leading X on its own is the misclassification risk, not the evidence.
            continue
        return ClassificationProposal(
            exchange=venue,
            base=symbol,
            proposed_class=ASSET_CLASS_TOKENIZED_EQUITY,
            evidence=(
                f"symbol carries the {prefix!r} tokenised-share wrapper",
                f"remainder {remainder!r} is a listed share according to "
                f"{_reference_origin()}",
                "a symbol coincidence produces the same evidence, so this does not "
                "override positive on-chain evidence to the contrary",
            ),
        )
    return None


def review_queue(
    observed: Iterable[tuple[str, str]],
    *,
    equity_tickers: Iterable[str] | None = None,
) -> list[ClassificationProposal]:
    """Every proposal the observed instruments support, deduplicated and ordered."""
    reference = (
        equity_ticker_reference()
        if equity_tickers is None
        else frozenset(str(t).strip().upper() for t in equity_tickers if str(t).strip())
    )
    seen: set[tuple[str, str]] = set()
    queue: list[ClassificationProposal] = []
    for exchange, base in observed:
        proposal = propose(exchange, base, equity_tickers=reference)
        if proposal is None:
            continue
        key = (proposal.exchange, proposal.base)
        if key in seen:
            continue
        seen.add(key)
        queue.append(proposal)
    queue.sort(key=lambda p: (p.exchange, p.base))
    return queue


__all__ = [
    "ClassificationProposal",
    "PROPOSAL_SOURCE",
    "TOKENIZED_EQUITY_PREFIXES",
    "derive_equity_ticker_reference",
    "equity_ticker_reference",
    "propose",
    "review_queue",
]
