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

**A leading X is not the evidence.** ``X`` alone would misclassify any genuine token
whose symbol starts with one - XMR and XRP are the obvious casualties. The evidence is
``X`` followed by a symbol that is independently a listed-equity ticker: XCRM against
CRM, XKO against KO, XRDDT against RDDT. Both halves are required, and a symbol whose
remainder is unknown yields no proposal at all rather than a weak one.

**Its output is not a classification.** ``ClassificationProposal`` deliberately carries
no ``acceptance_eligible`` and no ``source`` field, so it cannot be substituted for a
``SpotAssetClassification`` anywhere the pipeline expects one. Promoting a proposal into
``DECLARED_TOKENIZED_EQUITY_BASES`` stays a human edit under review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from listing_spot_asset_class import (
    ASSET_CLASS_TOKENIZED_EQUITY,
    DECLARED_CRYPTO_TOKEN_BASES,
    DECLARED_TOKENIZED_EQUITY_BASES,
)

# The wrapper venues use for a tokenised share. Held as a tuple so a second convention
# can be added by review rather than by pattern-matching.
TOKENIZED_EQUITY_PREFIXES: tuple[str, ...] = ("X",)

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
        derive_equity_ticker_reference()
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
                f"remainder {remainder!r} is a listed-equity ticker already reviewed "
                "on another venue",
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
        derive_equity_ticker_reference()
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
    "propose",
    "review_queue",
]
