"""Which moment a cadence decision is actually waiting for, and how sure it is of it.

Both listing tracks collapsed several different kinds of timestamp into one field::

    # pre-market
    event_ts = contract.official_spot_listing_ts or contract.transition_ts or contract.tradable_ts
    # pre-IPO
    event_ts = contract.official_conversion_ts or contract.tradable_ts

Once collapsed, nothing downstream can tell which kind of moment ``event_eta_utc``
describes - and the code then labelled it ``exact_timestamp`` whenever the *contract
record* came from an official source. But ``source_class`` describes where the record
came from, not where the timestamp came from. A contract discovered officially whose
only timestamp is a first-trade time was being reported as an exact official event time.

The pre-IPO case is the sharpest: ``official_conversion_ts`` is read from Bybit's
``preMktSwTime`` and OKX's ``conversion_time``. The hardened capture repo maps that same
field to ``transition_ts`` and refuses ``official_spot_t0`` to anything that is not an
OFFICIAL_ANNOUNCEMENT. The legacy name asserted "official"; its source never said so.

So the kinds are kept apart here, and only a genuine official spot t0 may claim to be an
official exact time. Everything else is a proxy - which the cadence policy already
handles correctly on its own: a proxy may describe a candidate and select SOON, but can
never select CONFIRMED or SCHEDULED. The policy was never wrong; it was being fed
dishonest inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ANCHOR_OFFICIAL_SPOT_T0 = "official_spot_t0"
ANCHOR_TRANSITION = "transition_ts"
ANCHOR_FIRST_TRADE = "first_trade_ts"
ANCHOR_CONTRACT_LAUNCH = "premarket_contract_launch_ts"

# Ordered by how directly each kind describes the awaited event. The official spot t0 is
# the event; a transition is a proxy for it; a first trade is after it; a contract launch
# is before it. This reproduces the old ``or`` chains, but records which kind was taken.
ANCHOR_PRECEDENCE: tuple[str, ...] = (
    ANCHOR_OFFICIAL_SPOT_T0,
    ANCHOR_TRANSITION,
    ANCHOR_FIRST_TRADE,
    ANCHOR_CONTRACT_LAUNCH,
)

# Only this kind can carry an official exact time. Named as a set so that widening it is
# an explicit edit under review, never an accident of an ``or`` fallback.
OFFICIAL_ANCHOR_KINDS = frozenset({ANCHOR_OFFICIAL_SPOT_T0})

TERMINAL_LIFECYCLE = frozenset({"cancelled", "canceled", "expired", "delisted"})


@dataclass(frozen=True)
class TemporalAnchor:
    """One dated moment, with the kind of moment it is kept attached to it."""

    kind: str
    ts: float
    source_class: str

    @property
    def is_official_time(self) -> bool:
        """True only when an official source published this kind of moment.

        Both halves are required. An official source that published a transition time
        has not published an official spot t0, and a spot t0 inferred from venue
        metadata was not published by an announcement."""
        return self.kind in OFFICIAL_ANCHOR_KINDS and self.source_class == "official"

    @property
    def is_proxy(self) -> bool:
        return not self.is_official_time


def resolve_anchor(
    candidates: Mapping[str, Any],
    *,
    source_class: str = "",
    source_classes: Mapping[str, Any] | None = None,
    precedence: Sequence[str] = ANCHOR_PRECEDENCE,
) -> TemporalAnchor | None:
    """Pick an anchor while keeping provenance attached to each timestamp.

    ``source_class`` is retained for legacy non-official anchors only.  A
    record-wide label can never certify an official spot t0; that requires an
    explicit per-kind entry in ``source_classes`` from the resolver.
    """
    provenance = dict(source_classes or {})
    for kind in precedence:
        value = candidates.get(kind)
        if value is None:
            continue
        try:
            ts = float(value)
        except (TypeError, ValueError):
            continue
        kind_source = str(provenance.get(kind) or "").strip().lower()
        if not kind_source:
            kind_source = "proxy" if kind == ANCHOR_OFFICIAL_SPOT_T0 else str(source_class or "")
        return TemporalAnchor(kind=kind, ts=ts, source_class=kind_source)
    return None


def anchor_observation(anchor: TemporalAnchor | None) -> dict[str, Any]:
    """The cadence-facing view of an anchor.

    ``official_confirmed`` and ``exact_timestamp`` are properties *of this anchor*.
    They used to be computed with ``any()`` across every contract in the batch, so one
    contract's official source was combined with another contract's timestamp into a
    confirmation that no single observation supported."""
    if anchor is None:
        return {
            "event_anchor_kind": None,
            "event_anchor_ts": None,
            "official_confirmed": False,
            "exact_timestamp": False,
            "proxy_timestamp": False,
        }
    return {
        "event_anchor_kind": anchor.kind,
        "event_anchor_ts": anchor.ts,
        "official_confirmed": anchor.is_official_time,
        "exact_timestamp": anchor.is_official_time,
        "proxy_timestamp": anchor.is_proxy,
    }


def select_cadence_anchor(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_ts: float,
    terminal: frozenset[str] = TERMINAL_LIFECYCLE,
) -> Mapping[str, Any] | None:
    """The earliest still-future anchor among the observed contracts.

    The previous selection filtered only on a timestamp being *present*, called the
    result ``upcoming``, sorted ascending and took the first. On a set containing past
    events that is guaranteed to pick the stalest one, and to keep picking it forever:
    measured 2026-08-24, the pre-IPO track was pinned to 2026-05-07 and the crypto track
    to 2025-09-01, both still reporting CONFIRMED."""
    live = [
        row for row in rows
        if str(row.get("lifecycle_status") or "").lower() not in terminal
    ]
    dated = [row for row in live if row.get("event_anchor_ts") is not None]
    future = [row for row in dated if float(row["event_anchor_ts"]) >= now_ts]
    if future:
        return min(future, key=lambda row: float(row["event_anchor_ts"]))
    # Nothing ahead. Report the most recent past anchor rather than the oldest, so the
    # decision is made against the freshest thing actually observed; the cadence policy
    # then retires it on its own age.
    if dated:
        return max(dated, key=lambda row: float(row["event_anchor_ts"]))
    if live:
        return live[0]
    return rows[0] if rows else None


__all__ = [
    "ANCHOR_CONTRACT_LAUNCH",
    "ANCHOR_FIRST_TRADE",
    "ANCHOR_OFFICIAL_SPOT_T0",
    "ANCHOR_PRECEDENCE",
    "ANCHOR_TRANSITION",
    "OFFICIAL_ANCHOR_KINDS",
    "TERMINAL_LIFECYCLE",
    "TemporalAnchor",
    "anchor_observation",
    "resolve_anchor",
    "select_cadence_anchor",
]
