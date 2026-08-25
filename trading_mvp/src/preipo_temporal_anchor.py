"""Equity-specific cadence anchors for the pre-IPO perpetual track.

The awaited event is the underlying equity's first executed trade.  Contract launch,
contract ``First Trading``, conversion, transition and rebase moments are useful
descriptive proxies, but none can certify that equity event.  Provenance therefore stays
attached to each timestamp and a record-wide ``official`` label is never sufficient.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from premarket_temporal_anchor import (
    TERMINAL_LIFECYCLE,
    select_cadence_anchor,
)
from preipo_perp_event import ACTIVE_VENUES, is_official_source_url


ANCHOR_OFFICIAL_FIRST_TRADE = "official_first_trade_ts"
ANCHOR_CONVERSION_WINDOW = "conversion_window_ts"
ANCHOR_TRANSITION = "transition_ts"
ANCHOR_CONTRACT_LAUNCH = "premarket_contract_launch_ts"

ANCHOR_PRECEDENCE: tuple[str, ...] = (
    ANCHOR_OFFICIAL_FIRST_TRADE,
    ANCHOR_CONVERSION_WINDOW,
    ANCHOR_TRANSITION,
    ANCHOR_CONTRACT_LAUNCH,
)
OFFICIAL_ANCHOR_KINDS = frozenset({ANCHOR_OFFICIAL_FIRST_TRADE})


@dataclass(frozen=True)
class PreIPOTemporalAnchor:
    kind: str
    ts: float
    source_class: str
    source_url: str = ""
    venue: str = ""
    announcement_ts: float | None = None

    @property
    def is_official_time(self) -> bool:
        try:
            ts = float(self.ts)
            announcement_ts = float(self.announcement_ts)
        except (TypeError, ValueError):
            return False
        return (
            self.kind in OFFICIAL_ANCHOR_KINDS
            and self.source_class == "official"
            and self.venue in ACTIVE_VENUES
            and math.isfinite(ts)
            and ts > 0
            and math.isfinite(announcement_ts)
            and announcement_ts > 0
            and is_official_source_url(self.venue, self.source_url)
        )

    @property
    def is_proxy(self) -> bool:
        return not self.is_official_time


def resolve_anchor(
    candidates: Mapping[str, Any],
    *,
    source_class: str = "",
    source_classes: Mapping[str, Any] | None = None,
    source_urls: Mapping[str, Any] | None = None,
    source_venues: Mapping[str, Any] | None = None,
    announcement_timestamps: Mapping[str, Any] | None = None,
    precedence: Sequence[str] = ANCHOR_PRECEDENCE,
) -> PreIPOTemporalAnchor | None:
    """Resolve one anchor without allowing metadata provenance to certify equity t0."""

    provenance = dict(source_classes or {})
    urls = dict(source_urls or {})
    venues = dict(source_venues or {})
    announcements = dict(announcement_timestamps or {})
    for kind in precedence:
        value = candidates.get(kind)
        if value is None:
            continue
        try:
            ts = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ts) or ts <= 0:
            continue
        kind_source = str(provenance.get(kind) or "").strip().lower()
        if not kind_source:
            kind_source = (
                "proxy"
                if kind == ANCHOR_OFFICIAL_FIRST_TRADE
                else str(source_class or "").strip().lower()
            )
        return PreIPOTemporalAnchor(
            kind=kind,
            ts=ts,
            source_class=kind_source,
            source_url=str(urls.get(kind) or "").strip(),
            venue=str(venues.get(kind) or "").strip().lower(),
            announcement_ts=announcements.get(kind),
        )
    return None


def anchor_observation(anchor: PreIPOTemporalAnchor | None) -> dict[str, Any]:
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


__all__ = [
    "ANCHOR_CONTRACT_LAUNCH",
    "ANCHOR_CONVERSION_WINDOW",
    "ANCHOR_OFFICIAL_FIRST_TRADE",
    "ANCHOR_PRECEDENCE",
    "ANCHOR_TRANSITION",
    "OFFICIAL_ANCHOR_KINDS",
    "PreIPOTemporalAnchor",
    "TERMINAL_LIFECYCLE",
    "anchor_observation",
    "resolve_anchor",
    "select_cadence_anchor",
]
