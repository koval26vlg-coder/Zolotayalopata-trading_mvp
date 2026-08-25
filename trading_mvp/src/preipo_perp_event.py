"""Research-only pre-IPO perpetual event model and causal paper replay.

This module is deliberately separate from the crypto pre-market listing track.
It models a pre-IPO equity perpetual, its lifecycle, official/proxy evidence,
value-neutral rebases, and fixed event-relative paper exits.  It never places
orders and it does not treat a proxy date or a rebase as trading PnL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA = "trading_mvp_preipo_perpetual_event_v1"
ASSET_CLASS = "preipo_equity"
ACTIVE_VENUES = ("okx", "gate", "bitmex", "kraken")
CANDIDATE_VENUES = ("bybit", "coinbase_intx", "cryptocom")
SOURCE_OFFICIAL = "official"
SOURCE_PROXY = "proxy"

LIFECYCLE_STATUSES = (
    "scheduled",
    "preipo_continuous",
    "s1_disclosed",
    "rebase",
    "ipo_pending",
    "ipo_open",
    "converted",
    "postponed",
    "cancelled",
    "delisted",
    "expired",
)
ENTRY_COHORTS = ("first_tradable", "last_1_4h")
EXIT_LABELS = (
    "ipo_open",
    "ipo_open_plus_5s",
    "ipo_open_plus_15s",
    "ipo_open_plus_60s",
    "conversion",
)

_EXIT_OFFSETS_SEC = {
    "ipo_open": 0,
    "ipo_open_plus_5s": 5,
    "ipo_open_plus_15s": 15,
    "ipo_open_plus_60s": 60,
}
_OFFICIAL_HOSTS = {
    "okx": ("okx.com", "okx-digital.com"),
    "gate": ("gate.com", "gate.io", "gateio.ws"),
    "bybit": ("bybit.com", "bybit-exchange.github.io"),
    "bitmex": ("bitmex.com",),
    "kraken": ("kraken.com",),
}
_TERMINAL_STATUSES = {"converted", "cancelled", "delisted", "expired"}
_ALLOWED_TRANSITIONS = {
    "scheduled": {"preipo_continuous", "s1_disclosed", "ipo_pending", "postponed", "cancelled", "expired"},
    "preipo_continuous": {"s1_disclosed", "rebase", "ipo_pending", "postponed", "cancelled", "delisted", "expired"},
    "s1_disclosed": {"rebase", "ipo_pending", "postponed", "cancelled", "expired"},
    "rebase": {"ipo_pending", "ipo_open", "postponed", "cancelled", "expired"},
    "ipo_pending": {"ipo_open", "postponed", "cancelled", "expired"},
    "ipo_open": {"converted", "delisted", "expired"},
    "postponed": {"ipo_pending", "cancelled", "expired"},
    "converted": set(),
    "cancelled": set(),
    "delisted": set(),
    "expired": set(),
}


class PreIPOEventError(ValueError):
    """Raised when a pre-IPO event is unsafe or internally inconsistent."""


def _normalise_venue(value: Any) -> str:
    venue = str(value or "").strip().lower()
    if venue == "gateio":
        venue = "gate"
    if venue not in _OFFICIAL_HOSTS:
        raise PreIPOEventError(f"unsupported venue: {value}")
    return venue


def _as_timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        if abs(parsed) >= 10_000_000_000:
            parsed /= 1000.0
        return parsed if parsed > 0 and math.isfinite(parsed) else None
    text = str(value).strip()
    if not text or text in {"...", "…", "tbd", "todo", "unknown"}:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        parsed = float(text)
        if abs(parsed) >= 10_000_000_000:
            parsed /= 1000.0
        return parsed if parsed > 0 and math.isfinite(parsed) else None
    iso = text.replace("Z", "+00:00")
    try:
        parsed_dt = datetime.fromisoformat(iso)
    except ValueError:
        parsed_dt = None
    if parsed_dt is not None:
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        return parsed_dt.astimezone(timezone.utc).timestamp()
    return None


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _walk_mappings(child)


def _find(payload: Mapping[str, Any], *keys: str) -> Any:
    wanted = {_key(key) for key in keys}
    for mapping in _walk_mappings(payload):
        for raw_key, value in mapping.items():
            if _key(raw_key) in wanted and value not in (None, ""):
                return value
    return None


def _is_official_url(venue: str, source_url: str) -> bool:
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme.lower() == "https"
        and not parsed.username
        and not parsed.password
        and bool(host)
        and any(
            host == root or host.endswith(f".{root}")
            for root in _OFFICIAL_HOSTS[venue]
        )
    )


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PreIPOEvent:
    venue: str
    contract_id: str
    underlying_symbol: str
    quote: str
    lifecycle_status: str = "scheduled"
    phase: str = "preipo_continuous"
    asset_class: str = ASSET_CLASS
    announcement_ts: float | None = None
    expected_ipo_date: str | None = None
    official_first_trade_ts: float | None = None
    conversion_window_start_ts: float | None = None
    conversion_window_end_ts: float | None = None
    actual_conversion_ts: float | None = None
    rebase_ts: float | None = None
    source_url: str = ""
    title: str = ""
    source_class: str = SOURCE_PROXY
    evidence_class: str = "PROXY_EXPECTED_DATE"
    confidence: str = "low"
    status_reason: str = ""

    def __post_init__(self) -> None:
        venue = _normalise_venue(self.venue)
        if venue != self.venue:
            object.__setattr__(self, "venue", venue)
        if self.asset_class != ASSET_CLASS:
            raise PreIPOEventError("pre-IPO event cannot use a crypto or spot asset class")
        if self.lifecycle_status not in LIFECYCLE_STATUSES:
            raise PreIPOEventError(f"unknown lifecycle status: {self.lifecycle_status}")
        if not self.contract_id.strip() or not self.underlying_symbol.strip() or not self.quote.strip():
            raise PreIPOEventError("contract_id, underlying_symbol and quote are required")
        if self.source_class not in {SOURCE_OFFICIAL, SOURCE_PROXY}:
            raise PreIPOEventError(f"unknown source class: {self.source_class}")
        for label, value in (
            ("announcement_ts", self.announcement_ts),
            ("official_first_trade_ts", self.official_first_trade_ts),
            ("conversion_window_start_ts", self.conversion_window_start_ts),
            ("conversion_window_end_ts", self.conversion_window_end_ts),
            ("actual_conversion_ts", self.actual_conversion_ts),
            ("rebase_ts", self.rebase_ts),
        ):
            if value is not None and (not math.isfinite(float(value)) or float(value) <= 0):
                raise PreIPOEventError(f"{label} must be a positive finite timestamp")
        if self.source_class == SOURCE_OFFICIAL and not self.source_url:
            raise PreIPOEventError("official event requires source_url")

    @property
    def proxy_only(self) -> bool:
        return self.source_class == SOURCE_PROXY or self.official_first_trade_ts is None

    @property
    def acceptance_eligible(self) -> bool:
        return (
            self.venue in ACTIVE_VENUES
            and self.source_class == SOURCE_OFFICIAL
            and self.official_first_trade_ts is not None
            and self.lifecycle_status not in {"cancelled", "postponed", "delisted", "expired"}
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = SCHEMA
        payload["proxy_only"] = self.proxy_only
        payload["acceptance_eligible"] = self.acceptance_eligible
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PreIPOEvent":
        return cls(
            venue=str(payload.get("venue") or ""),
            contract_id=str(payload.get("contract_id") or ""),
            underlying_symbol=str(payload.get("underlying_symbol") or ""),
            quote=str(payload.get("quote") or "USDT"),
            lifecycle_status=str(payload.get("lifecycle_status") or "scheduled"),
            phase=str(payload.get("phase") or "preipo_continuous"),
            asset_class=str(payload.get("asset_class") or ASSET_CLASS),
            announcement_ts=_as_timestamp(payload.get("announcement_ts")),
            expected_ipo_date=str(payload.get("expected_ipo_date")) if payload.get("expected_ipo_date") else None,
            official_first_trade_ts=_as_timestamp(payload.get("official_first_trade_ts")),
            conversion_window_start_ts=_as_timestamp(payload.get("conversion_window_start_ts")),
            conversion_window_end_ts=_as_timestamp(payload.get("conversion_window_end_ts")),
            actual_conversion_ts=_as_timestamp(payload.get("actual_conversion_ts")),
            rebase_ts=_as_timestamp(payload.get("rebase_ts")),
            source_url=str(payload.get("source_url") or ""),
            title=str(payload.get("title") or ""),
            source_class=str(payload.get("source_class") or SOURCE_PROXY),
            evidence_class=str(payload.get("evidence_class") or "PROXY_EXPECTED_DATE"),
            confidence=str(payload.get("confidence") or "low"),
            status_reason=str(payload.get("status_reason") or ""),
        )


def parse_announcement(payload: Mapping[str, Any], *, require_official_source: bool = True) -> PreIPOEvent:
    """Parse a captured public announcement without fetching the network."""

    venue = _normalise_venue(_find(payload, "venue", "exchange"))
    source_url = str(_find(payload, "source_url", "official_source_url", "url") or "").strip()
    if require_official_source and not _is_official_url(venue, source_url):
        raise PreIPOEventError(f"source_url is not an official {venue} URL")
    contract_id = str(_find(payload, "contract_id", "preipo_contract_id", "pre_ipo_contract", "instrument_id", "inst_id") or "").strip().upper()
    underlying = str(_find(payload, "underlying_symbol", "underlying", "symbol", "base") or "").strip().upper()
    quote = str(_find(payload, "quote", "quote_currency", "quote_ccy") or "USDT").strip().upper()
    if not contract_id or not underlying:
        raise PreIPOEventError("announcement is missing contract_id or underlying_symbol")

    official_first_trade_ts = _as_timestamp(_find(
        payload,
        "official_first_trade_ts",
        "first_trade_ts",
        "ipo_open_ts",
        "ipo_start_ts",
        "first_trading_ts",
    ))
    conversion_start = _as_timestamp(_find(payload, "conversion_window_start_ts", "conversion_start_ts", "conversion_ts"))
    conversion_end = _as_timestamp(_find(payload, "conversion_window_end_ts", "conversion_end_ts"))
    actual_conversion = _as_timestamp(_find(payload, "actual_conversion_ts", "transition_ts"))
    rebase_ts = _as_timestamp(_find(payload, "rebase_ts", "rebase_time"))
    expected_date_raw = _find(payload, "expected_ipo_date", "ipo_date", "expected_listing_date")
    expected_date = str(expected_date_raw).strip() if expected_date_raw not in (None, "") else None
    announcement_ts = _as_timestamp(_find(payload, "announcement_ts", "published_at", "published_ts", "created_at"))
    lifecycle = str(_find(payload, "lifecycle_status", "status") or "scheduled").strip().lower().replace("-", "_")
    if lifecycle not in LIFECYCLE_STATUSES:
        lifecycle = "scheduled"
    phase = str(_find(payload, "phase", "auction_phase") or "preipo_continuous").strip().lower().replace("-", "_")

    if official_first_trade_ts is not None:
        source_class = SOURCE_OFFICIAL
        evidence_class = "OFFICIAL_FIRST_TRADE_TIME"
        confidence = "high"
    elif conversion_start is not None and conversion_end is not None:
        source_class = SOURCE_OFFICIAL
        evidence_class = "OFFICIAL_CONVERSION_WINDOW_NO_T0"
        confidence = "medium"
    else:
        source_class = SOURCE_PROXY
        evidence_class = "PROXY_EXPECTED_DATE"
        confidence = "low"

    return PreIPOEvent(
        venue=venue,
        contract_id=contract_id,
        underlying_symbol=underlying,
        quote=quote,
        lifecycle_status=lifecycle,
        phase=phase,
        announcement_ts=announcement_ts,
        expected_ipo_date=expected_date,
        official_first_trade_ts=official_first_trade_ts,
        conversion_window_start_ts=conversion_start,
        conversion_window_end_ts=conversion_end,
        actual_conversion_ts=actual_conversion,
        rebase_ts=rebase_ts,
        source_url=source_url,
        title=str(_find(payload, "title", "headline") or ""),
        source_class=source_class,
        evidence_class=evidence_class,
        confidence=confidence,
    )


def transition_event(event: PreIPOEvent, new_status: str, *, at_ts: float, reason: str) -> PreIPOEvent:
    """Apply one explicit lifecycle transition and retain its causal reason."""

    new_status = str(new_status).strip().lower().replace("-", "_")
    if new_status not in LIFECYCLE_STATUSES:
        raise PreIPOEventError(f"unknown lifecycle status: {new_status}")
    if not math.isfinite(float(at_ts)) or float(at_ts) <= 0:
        raise PreIPOEventError("transition timestamp must be positive and finite")
    if event.lifecycle_status in _TERMINAL_STATUSES:
        raise PreIPOEventError(f"cannot transition terminal event {event.lifecycle_status}")
    if new_status not in _ALLOWED_TRANSITIONS[event.lifecycle_status]:
        raise PreIPOEventError(f"illegal transition {event.lifecycle_status}->{new_status}")
    return replace(
        event,
        lifecycle_status=new_status,
        actual_conversion_ts=float(at_ts) if new_status == "converted" else event.actual_conversion_ts,
        status_reason=str(reason).strip(),
    )


def rebase_position(
    *,
    entry_price: float,
    entry_quantity: float,
    estimated_share_count: float,
    actual_share_count: float,
) -> dict[str, float | bool]:
    """Apply the venue's share-count rebase as value-neutral quantity/price math."""

    values = (entry_price, entry_quantity, estimated_share_count, actual_share_count)
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in values):
        raise PreIPOEventError("rebase values must be positive and finite")
    ratio = float(actual_share_count) / float(estimated_share_count)
    post_price = float(entry_price) / ratio
    post_quantity = float(entry_quantity) * ratio
    pre_notional = float(entry_price) * float(entry_quantity)
    post_notional = post_price * post_quantity
    neutral = math.isclose(pre_notional, post_notional, rel_tol=1e-12, abs_tol=1e-12)
    return {
        "share_count_ratio": ratio,
        "pre_price": float(entry_price),
        "post_price": post_price,
        "pre_quantity": float(entry_quantity),
        "post_quantity": post_quantity,
        "pre_notional": pre_notional,
        "post_notional": post_notional,
        "value_neutral": neutral,
        "pnl_credit": 0.0,
    }


def build_entry_candidates(event: PreIPOEvent, *, first_tradable_ts: float) -> list[dict[str, Any]]:
    """Build timestamp-only cohorts; no future price or peak information is used."""

    if not math.isfinite(float(first_tradable_ts)) or float(first_tradable_ts) <= 0:
        raise PreIPOEventError("first_tradable_ts must be positive and finite")
    candidates = [
        {
            "venue": event.venue,
            "contract_id": event.contract_id,
            "entry_cohort": "first_tradable",
            "entry_ts": float(first_tradable_ts),
            "entry_ts_class": "observed_tradable",
        }
    ]
    if event.official_first_trade_ts is not None:
        candidates.append(
            {
                "venue": event.venue,
                "contract_id": event.contract_id,
                "entry_cohort": "last_1_4h",
                "entry_ts": float(event.official_first_trade_ts) - 4 * 3600,
                "entry_ts_class": "derived_from_official_ipo_t0",
            }
        )
    return candidates


def _snapshot_ts(snapshot: Mapping[str, Any]) -> float:
    value = _as_timestamp(snapshot.get("ts", snapshot.get("exchange_ts")))
    if value is None:
        raise PreIPOEventError("market snapshot is missing a valid ts")
    return value


def _first_snapshot_at_or_after(snapshots: Sequence[Mapping[str, Any]], target_ts: float) -> Mapping[str, Any] | None:
    for snapshot in sorted(snapshots, key=_snapshot_ts):
        if _snapshot_ts(snapshot) >= target_ts:
            return snapshot
    return None


def _price(snapshot: Mapping[str, Any], key: str) -> float:
    try:
        value = float(snapshot[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreIPOEventError(f"snapshot is missing {key}") from exc
    if not math.isfinite(value) or value <= 0:
        raise PreIPOEventError(f"snapshot {key} must be positive and finite")
    return value


def _quantity(snapshot: Mapping[str, Any], key: str) -> float:
    try:
        value = float(snapshot.get(key, 0.0))
    except (TypeError, ValueError) as exc:
        raise PreIPOEventError(f"snapshot {key} is invalid") from exc
    return max(0.0, value) if math.isfinite(value) else 0.0


def _execution_price(snapshot: Mapping[str, Any], *, side: str, entry: bool, slippage_bps: float) -> float:
    raw = _price(snapshot, "ask" if (entry and side == "long") or (not entry and side == "short") else "bid")
    slip = float(slippage_bps) / 10_000.0
    if slip < 0 or not math.isfinite(slip):
        raise PreIPOEventError("slippage_bps must be finite and non-negative")
    if entry:
        return raw * (1 + slip) if side == "long" else raw * (1 - slip)
    return raw * (1 - slip) if side == "long" else raw * (1 + slip)


def _base_result(event: PreIPOEvent, side: str, entry_ts: float) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "venue": event.venue,
        "contract_id": event.contract_id,
        "asset_class": event.asset_class,
        "source_class": event.source_class,
        "side": side,
        "entry_ts": float(entry_ts),
        "event_t0": event.official_first_trade_ts,
        "event_status": "proxy_only" if event.proxy_only else "incomplete",
        "acceptance_eligible": False,
        "entry_fill_status": "unfilled",
        "filled_quantity": 0.0,
        "fill_denominator": 1,
        "net_pnl_quote": 0.0,
        "exits": {},
    }


def replay_preipo_event(
    event: PreIPOEvent,
    snapshots: Sequence[Mapping[str, Any]],
    *,
    entry_ts: float,
    side: str,
    notional_quote: float = 25.0,
    taker_fee_bps: float = 10.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Replay one paper position using fixed causal exits only."""

    side = str(side).strip().lower()
    if side not in {"long", "short"}:
        raise PreIPOEventError("side must be long or short")
    if not math.isfinite(float(entry_ts)) or float(entry_ts) <= 0:
        raise PreIPOEventError("entry_ts must be positive and finite")
    if not math.isfinite(float(notional_quote)) or float(notional_quote) <= 0:
        raise PreIPOEventError("notional_quote must be positive and finite")
    if not math.isfinite(float(taker_fee_bps)) or float(taker_fee_bps) < 0:
        raise PreIPOEventError("taker_fee_bps must be finite and non-negative")
    result = _base_result(event, side, entry_ts)
    if event.proxy_only:
        result["result_hash"] = _canonical_hash({key: value for key, value in result.items() if key != "result_hash"})
        return result

    entry_snapshot = _first_snapshot_at_or_after(snapshots, float(entry_ts))
    if entry_snapshot is None:
        result["event_status"] = "incomplete"
        result["result_hash"] = _canonical_hash({key: value for key, value in result.items() if key != "result_hash"})
        return result
    entry_price = _execution_price(entry_snapshot, side=side, entry=True, slippage_bps=slippage_bps)
    target_quantity = float(notional_quote) / entry_price
    available_quantity = _quantity(entry_snapshot, "ask_qty" if side == "long" else "bid_qty")
    filled_quantity = min(target_quantity, available_quantity)
    result["filled_quantity"] = filled_quantity
    if filled_quantity <= 0:
        result["entry_fill_status"] = "unfilled"
        result["event_status"] = "incomplete"
        result["result_hash"] = _canonical_hash({key: value for key, value in result.items() if key != "result_hash"})
        return result
    result["entry_fill_status"] = "full" if filled_quantity >= target_quantity * (1 - 1e-12) else "partial"
    entry_notional = entry_price * filled_quantity
    fee_rate = float(taker_fee_bps) / 10_000.0
    exit_targets = {label: float(event.official_first_trade_ts) + offset for label, offset in _EXIT_OFFSETS_SEC.items()}
    conversion_ts = event.actual_conversion_ts or event.conversion_window_start_ts
    if conversion_ts is not None:
        exit_targets["conversion"] = float(conversion_ts)
    else:
        exit_targets["conversion"] = float(event.official_first_trade_ts)

    all_exits_observed = True
    for label in EXIT_LABELS:
        target_ts = exit_targets[label]
        snapshot = _first_snapshot_at_or_after(snapshots, target_ts)
        if snapshot is None:
            all_exits_observed = False
            result["exits"][label] = {
                "target_ts": target_ts,
                "status": "missing_exit_snapshot",
                "fill_status": "unfilled",
                "filled_quantity": 0.0,
                "net_pnl_quote": 0.0,
                "causal": True,
            }
            continue
        exit_price = _execution_price(snapshot, side=side, entry=False, slippage_bps=slippage_bps)
        available_exit = _quantity(snapshot, "bid_qty" if side == "long" else "ask_qty")
        exit_quantity = min(filled_quantity, available_exit)
        if exit_quantity <= 0:
            all_exits_observed = False
            result["exits"][label] = {
                "target_ts": target_ts,
                "observed_ts": _snapshot_ts(snapshot),
                "status": "unfilled_exit",
                "fill_status": "unfilled",
                "filled_quantity": 0.0,
                "net_pnl_quote": 0.0,
                "causal": True,
            }
            continue
        direction = 1.0 if side == "long" else -1.0
        gross = direction * (exit_price - entry_price) * exit_quantity
        exit_notional = exit_price * exit_quantity
        fees = (entry_notional + exit_notional) * fee_rate
        funding_quote = float(snapshot.get("funding_quote", 0.0) or 0.0)
        if not math.isfinite(funding_quote):
            raise PreIPOEventError("funding_quote must be finite")
        net = gross - fees - funding_quote
        fill_status = "full" if exit_quantity >= filled_quantity * (1 - 1e-12) else "partial"
        if fill_status != "full":
            all_exits_observed = False
        result["exits"][label] = {
            "target_ts": target_ts,
            "observed_ts": _snapshot_ts(snapshot),
            "status": "filled",
            "fill_status": fill_status,
            "filled_quantity": exit_quantity,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "gross_pnl_quote": gross,
            "fees_quote": fees,
            "funding_quote": funding_quote,
            "net_pnl_quote": net,
            "causal": True,
        }

    result["event_status"] = "complete" if all_exits_observed else "incomplete"
    result["acceptance_eligible"] = bool(event.acceptance_eligible and result["event_status"] == "complete" and result["entry_fill_status"] == "full")
    result["net_pnl_quote"] = float(result["exits"].get("ipo_open", {}).get("net_pnl_quote", 0.0) or 0.0)
    result["result_hash"] = _canonical_hash({key: value for key, value in result.items() if key != "result_hash"})
    return result


def evaluate_event_set(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate the non-terminal feasibility gate without tuning thresholds."""

    rows = [dict(result) for result in results]
    complete = [row for row in rows if row.get("event_status") == "complete"]
    official = [row for row in complete if row.get("source_class") == SOURCE_OFFICIAL]
    fill_denominator = len(rows)
    filled = sum(row.get("entry_fill_status") in {"full", "partial"} for row in rows)
    fill_rate = filled / fill_denominator if fill_denominator else 0.0
    pnl = [float(row.get("net_pnl_quote") or 0.0) for row in complete]
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = abs(sum(value for value in pnl if value < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    status = "INSUFFICIENT_DATA_NOT_REJECTED" if len(complete) < 30 else "READY_FOR_STANDARD_GATES"
    return {
        "schema": SCHEMA,
        "status": status,
        "complete_events": len(complete),
        "official_complete_events": len(official),
        "fill_denominator": fill_denominator,
        "full_or_partial_fill_rate": fill_rate,
        "net_expectancy_quote": (sum(pnl) / len(pnl)) if pnl else 0.0,
        "profit_factor": profit_factor,
        "positive_event_share": (sum(value > 0 for value in pnl) / len(pnl)) if pnl else 0.0,
        "acceptance_eligible": False,
        "result_hash": _canonical_hash({
            "status": status,
            "complete_events": len(complete),
            "official_complete_events": len(official),
            "fill_denominator": fill_denominator,
            "full_or_partial_fill_rate": fill_rate,
            "net_expectancy_quote": (sum(pnl) / len(pnl)) if pnl else 0.0,
            "profit_factor": profit_factor,
            "positive_event_share": (sum(value > 0 for value in pnl) / len(pnl)) if pnl else 0.0,
        }),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate a captured pre-IPO announcement")
    parser.add_argument("--announcement", required=True, help="JSON file containing a public announcement payload")
    args = parser.parse_args()
    payload = json.loads(Path(args.announcement).read_text(encoding="utf-8"))
    print(json.dumps(parse_announcement(payload).to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
