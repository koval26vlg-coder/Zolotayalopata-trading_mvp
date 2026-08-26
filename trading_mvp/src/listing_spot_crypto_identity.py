"""Propose a positive crypto-token identity, from what the venue itself publishes.

The acceptance universe is empty by declaration: ``DECLARED_CRYPTO_TOKEN_BASES`` is ``{}``,
so no instrument is currently eligible. That is the correct starting point - it is what
stopped ANTHROPIC being counted as a crypto listing - but it also means the crypto track
cannot accept anything until some instrument is positively established as a token. This
module is the mechanism for that, and it is deliberately harder to satisfy than its
tokenised-equity counterpart.

The asymmetry is the point. ``listing_asset_class_heuristic`` may only ever move an
instrument *out* of the acceptance universe, so a wrong proposal there costs coverage.
A proposal here moves an instrument *in*, so a wrong one costs correctness - it puts a
non-token into a sample whose whole purpose is to measure crypto listings. Everything
below follows from that: stronger evidence, narrower sources, and an output that still
cannot be mistaken for a decision.

**What counts as evidence.** Only the venue's own published asset metadata, fetched from
the venue's own domain. A third party asserting that a symbol is a token establishes
nothing about *this venue's* instrument with *this* ticker; symbol collision is exactly
how a tokenised share and a token come to look alike.

**What the evidence has to show.** That the base can be deposited *and* withdrawn on a
named public network. A tokenised share on these venues is an internal instrument: it
exists in the exchange's ledger and cannot leave it. Something that can be moved onto a
public chain and off it again is a token in the sense the research question means.

**What it still is not.** A proposal. Withdrawability is strong evidence and not a proof:
a venue could in principle issue a tokenised share as a real on-chain asset, and then
this test would pass for something that is not a crypto listing. So the output carries no
``acceptance_eligible`` field and no source that would let it stand in for a
``SpotAssetClassification``. Editing ``DECLARED_CRYPTO_TOKEN_BASES`` stays a human act.

This module performs no collection. Fetching the evidence is a separate, separately
authorised step; what arrives here is already-observed data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse

from listing_spot_asset_class import (
    ASSET_CLASS_CRYPTO_TOKEN,
    DECLARED_CRYPTO_TOKEN_BASES,
    DECLARED_TOKENIZED_EQUITY_BASES,
)
from listing_asset_class_heuristic import propose as propose_tokenized_equity

# The venue must be the one making the claim, so each venue is pinned to the hosts it
# actually publishes from. A new venue is an explicit edit, never a wildcard.
VENUE_EVIDENCE_HOSTS: dict[str, frozenset[str]] = {
    "binance": frozenset({"api.binance.com", "www.binance.com"}),
    "bitget": frozenset({"api.bitget.com", "www.bitget.com"}),
    "bybit": frozenset({"api.bybit.com", "www.bybit.com"}),
    "okx": frozenset({"www.okx.com", "okx.com"}),
}

PROPOSAL_SOURCE = "venue_chain_evidence_proposal_not_a_classification"

_BASE_RE = re.compile(r"\A[A-Z0-9]{1,20}\Z")


class CryptoIdentityError(ValueError):
    """The evidence cannot be read as evidence at all."""


@dataclass(frozen=True)
class ChainListing:
    """One network the venue says this asset lives on, and what it allows there."""

    network: str
    contract_address: str | None = None
    deposit_enabled: bool = False
    withdraw_enabled: bool = False

    @property
    def is_movable(self) -> bool:
        """Both directions, or it is not a public-chain asset in any useful sense.

        Deposit alone can mean a venue accepts a wrapped form it will not return;
        withdrawal alone can be a one-way migration. An instrument that can be brought
        in and taken out is one that exists outside this exchange's ledger."""
        return bool(self.network) and self.deposit_enabled and self.withdraw_enabled


@dataclass(frozen=True)
class VenueAssetEvidence:
    """What one venue published about one base asset, and when."""

    exchange: str
    base: str
    source_url: str
    observed_at_utc: str
    chains: tuple[ChainListing, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CryptoIdentityProposal:
    """A candidate for the declared crypto registry, and only that.

    It carries no ``acceptance_eligible`` and no ``DECLARATION_SOURCE``, so it cannot be
    passed where a decided classification is expected."""

    exchange: str
    base: str
    proposed_class: str
    supporting_networks: tuple[str, ...]
    source_url: str
    observed_at_utc: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    requires_human_review: bool = True

    def __post_init__(self) -> None:
        if self.proposed_class != ASSET_CLASS_CRYPTO_TOKEN:
            raise ValueError(
                "this module proposes crypto_token only; proposing anything else here "
                "would let venue chain evidence decide a question it cannot answer"
            )
        if not self.requires_human_review:
            raise ValueError("a proposal is always subject to review")
        if not self.supporting_networks:
            raise ValueError("a proposal must name the networks that support it")


def _normalise(exchange: str, base: str) -> tuple[str, str]:
    return str(exchange or "").strip().lower(), str(base or "").strip().upper()


def _host_is_the_venue(exchange: str, source_url: str) -> bool:
    allowed = VENUE_EVIDENCE_HOSTS.get(exchange)
    if not allowed:
        return False
    try:
        parsed = urlparse(str(source_url or ""))
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    return (parsed.hostname or "").lower() in allowed


def _observed_recently(observed_at_utc: str, *, now: datetime, max_age_days: int) -> bool:
    try:
        moment = datetime.fromisoformat(str(observed_at_utc).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if moment.tzinfo is None:
        # A naive timestamp leaves open which clock produced it.
        return False
    moment = moment.astimezone(timezone.utc)
    if moment > now:
        return False
    return (now - moment).days <= max_age_days


def _already_declared(exchange: str, base: str) -> bool:
    for registry in (DECLARED_TOKENIZED_EQUITY_BASES, DECLARED_CRYPTO_TOKEN_BASES):
        if base in registry.get(exchange, frozenset()):
            return True
    return False


def propose_crypto_identity(
    evidence: VenueAssetEvidence,
    *,
    now: datetime | None = None,
    max_age_days: int = 30,
    equity_tickers: Iterable[str] | None = None,
) -> CryptoIdentityProposal | None:
    """Propose a crypto-token candidate, or nothing.

    Nothing is returned - rather than an error - whenever the evidence simply fails to
    support the claim, because "not established" is the resting state of every instrument
    here and needs no explanation. Malformed evidence is a different matter and raises,
    since a caller that hands over an unreadable record has a bug rather than a negative
    result."""
    if not isinstance(evidence, VenueAssetEvidence):
        raise CryptoIdentityError("evidence must be a VenueAssetEvidence")
    exchange, base = _normalise(evidence.exchange, evidence.base)
    if not exchange or not base:
        raise CryptoIdentityError("evidence names no venue or no base")
    if not _BASE_RE.match(base):
        raise CryptoIdentityError(f"unusable base symbol: {evidence.base!r}")

    if _already_declared(exchange, base):
        # A settled identity is not a question, in either direction.
        return None
    if not _host_is_the_venue(exchange, evidence.source_url):
        return None
    moment = now or datetime.now(timezone.utc)
    if not _observed_recently(evidence.observed_at_utc, now=moment, max_age_days=max_age_days):
        return None

    # An instrument the equity heuristic recognises is not a token candidate, whatever
    # its chain metadata says. The two proposals must never disagree in silence.
    if propose_tokenized_equity(exchange, base, equity_tickers=equity_tickers) is not None:
        return None

    networks = tuple(
        sorted({chain.network.strip() for chain in evidence.chains if chain.is_movable})
    )
    if not networks:
        return None

    addressed = sorted(
        {
            f"{chain.network.strip()}:{chain.contract_address.strip()}"
            for chain in evidence.chains
            if chain.is_movable and (chain.contract_address or "").strip()
        }
    )
    reasons = [
        f"{evidence.exchange} publishes deposit and withdrawal for {base} on "
        f"{len(networks)} public network(s): {', '.join(networks)}",
        f"evidence read from the venue's own host {urlparse(evidence.source_url).hostname}",
        f"observed at {evidence.observed_at_utc}",
    ]
    if addressed:
        reasons.append("contract addresses published: " + ", ".join(addressed))
    else:
        # Native assets have no contract; say so rather than leaving a silent gap.
        reasons.append("no contract address published; consistent with a native chain asset")

    return CryptoIdentityProposal(
        exchange=exchange,
        base=base,
        proposed_class=ASSET_CLASS_CRYPTO_TOKEN,
        supporting_networks=networks,
        source_url=evidence.source_url,
        observed_at_utc=evidence.observed_at_utc,
        evidence=tuple(reasons),
    )


def review_queue(
    observations: Sequence[VenueAssetEvidence],
    *,
    now: datetime | None = None,
    max_age_days: int = 30,
    equity_tickers: Iterable[str] | None = None,
) -> list[CryptoIdentityProposal]:
    """Every proposal the observations support, deduplicated and ordered."""
    seen: set[tuple[str, str]] = set()
    queue: list[CryptoIdentityProposal] = []
    for observation in observations:
        proposal = propose_crypto_identity(
            observation, now=now, max_age_days=max_age_days, equity_tickers=equity_tickers
        )
        if proposal is None:
            continue
        key = (proposal.exchange, proposal.base)
        if key in seen:
            continue
        seen.add(key)
        queue.append(proposal)
    queue.sort(key=lambda item: (item.exchange, item.base))
    return queue


def unresolved_bases(
    observed: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """The venue/base pairs that no registry has an answer for yet.

    This is what the crypto track is actually blocked on, and naming it explicitly keeps
    "we have not established this" from being read as "there is nothing here"."""
    out: list[tuple[str, str]] = []
    for exchange, base in observed:
        venue, symbol = _normalise(exchange, base)
        if not venue or not symbol or _already_declared(venue, symbol):
            continue
        if (venue, symbol) not in out:
            out.append((venue, symbol))
    out.sort()
    return out


__all__ = [
    "ASSET_CLASS_CRYPTO_TOKEN",
    "PROPOSAL_SOURCE",
    "VENUE_EVIDENCE_HOSTS",
    "ChainListing",
    "CryptoIdentityError",
    "CryptoIdentityProposal",
    "VenueAssetEvidence",
    "propose_crypto_identity",
    "review_queue",
    "unresolved_bases",
]
