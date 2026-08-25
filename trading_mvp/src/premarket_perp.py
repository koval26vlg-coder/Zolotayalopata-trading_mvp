"""Public pre-market perpetual listing-impulse research primitives.

The module deliberately keeps the new hypothesis separate from the existing
spot Listing Momentum and generic MEXC/Gate perpetual collectors.  It accepts
public exchange payloads, normalises them into a common lifecycle/event shape,
and provides a deterministic paper replay for the two pre-registered entry
cohorts and four listing-relative exits.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum

from premarket_asset_class import (  # noqa: E402
    ASSET_CLASS_CRYPTO_TOKEN,
    belongs_to,
)
from typing import Any, Iterable, Mapping

from ws_replay import ReplayConfig


class PreMarketPhase(str, Enum):
    CALL_AUCTION = "call_auction"
    CONTINUOUS = "continuous"
    UNKNOWN = "unknown"


class SourceClass(str, Enum):
    OFFICIAL = "official"
    PROXY = "proxy"


EXIT_OFFSETS_SEC: tuple[int, ...] = (0, 5, 15, 60)
VENUES: tuple[str, ...] = ("bybit", "okx", "gate")
ENTRY_COHORTS: tuple[str, ...] = ("first_tradable", "last_1_4h")
MAX_BBO_STALENESS_SEC = 2.0


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return None if parsed is None else int(parsed)


def _timestamp(value: Any) -> float | None:
    """Convert seconds or milliseconds without guessing on small values."""

    parsed = _as_float(value)
    if parsed is None:
        return None
    return parsed / 1000.0 if abs(parsed) >= 10_000_000_000 else parsed


def _rate_to_bps(value: Any) -> float | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    # Public exchange fee fields are decimal ratios.  Accept a bps-like value
    # as-is as a defensive boundary for fixture/adapter payloads.
    return parsed if abs(parsed) > 1.0 else parsed * 10_000.0


def _phase(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if "call" in text or "auction" in text:
        return PreMarketPhase.CALL_AUCTION.value
    if "continuous" in text or text in {"trading", "continue", "continuous_trading"}:
        return PreMarketPhase.CONTINUOUS.value
    return PreMarketPhase.UNKNOWN.value


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalise_status(status: Any) -> str:
    return str(status or "").strip().lower().replace("-", "_")


@dataclass(frozen=True)
class PreMarketContract:
    venue: str
    contract_id: str
    spot_symbol: str
    base: str
    quote: str
    phase: str
    lifecycle_status: str
    source_class: str = SourceClass.OFFICIAL.value
    # Provenance belongs to the individual timestamp.  Venue instrument
    # metadata is useful lifecycle evidence, but it is not an official spot
    # listing announcement unless the resolver has independently materialised
    # and accepted that timestamp.
    listing_source_class: str = SourceClass.PROXY.value
    listing_acceptance_eligible: bool = False
    announcement_ts: float | None = None
    tradable_ts: float | None = None
    official_spot_listing_ts: float | None = None
    transition_ts: float | None = None
    expiry_ts: float | None = None
    tick_size: float | None = None
    lot_size: float | None = None
    min_qty: float | None = None
    contract_multiplier: float = 1.0
    max_leverage: float | None = None
    maintenance_margin_rate: float | None = None
    price_limit_up: float | None = None
    price_limit_down: float | None = None
    maker_fee_bps: float | None = None
    taker_fee_bps: float | None = None
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.contract_id}"

    @property
    def has_official_listing_time(self) -> bool:
        return (
            self.listing_source_class == SourceClass.OFFICIAL.value
            and self.listing_acceptance_eligible
            and self.official_spot_listing_ts is not None
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"key": self.key, "has_official_listing_time": self.has_official_listing_time}


def _base_from_symbol(symbol: str, quote: str, separator: str = "") -> str:
    normalized = symbol.upper()
    if separator and separator in normalized:
        return normalized.rsplit(separator, 1)[0]
    if quote and normalized.endswith(quote):
        return normalized[: -len(quote)]
    return normalized


def normalize_bybit_instrument(item: Mapping[str, Any], *, source_class: str = SourceClass.OFFICIAL.value) -> PreMarketContract | None:
    """Normalise a Bybit V5 linear pre-listing instrument."""

    raw = dict(item)
    quote = str(_first(raw, "quoteCoin", "settleCoin") or "").upper()
    status = _normalise_status(raw.get("status"))
    pre_info = raw.get("preListingInfo") or {}
    is_prelisting = bool(raw.get("isPreListing")) or status in {"prelaunch", "pre_launch"} or bool(pre_info)
    if not is_prelisting or quote != "USDT":
        return None

    symbol = str(raw.get("symbol") or "").upper()
    base = str(_first(raw, "baseCoin") or _base_from_symbol(symbol, quote)).upper()
    current_phase = _phase(_first(pre_info, "curAuctionPhase", "currentPhase"))
    if current_phase == PreMarketPhase.UNKNOWN.value:
        phases = pre_info.get("phases") or []
        if phases:
            current_phase = _phase(phases[0].get("phase"))

    launch_ts = _timestamp(_first(raw, "launchTime", "launch_time"))
    transition_ts = _timestamp(_first(raw, "preMktSwTime", "preMarketSwitchTime", "transitionTime"))
    official_listing_ts = _timestamp(_first(raw, "spotListingTime", "spotListTime", "officialSpotListingTime"))
    expiry_ts = _timestamp(_first(raw, "deliveryTime", "delivery_time", "expiryTime"))
    fee_info = pre_info.get("auctionFeeInfo") or {}
    lifecycle = current_phase if current_phase != PreMarketPhase.UNKNOWN.value else "scheduled"
    if status in {"trading", "live"} and not bool(raw.get("isPreListing")):
        lifecycle = "transitioned"

    price_filter = raw.get("priceFilter") or {}
    lot_filter = raw.get("lotSizeFilter") or {}
    leverage_filter = raw.get("leverageFilter") or {}
    return PreMarketContract(
        venue="bybit",
        contract_id=symbol,
        spot_symbol=f"{base}{quote}",
        base=base,
        quote=quote,
        phase=current_phase,
        lifecycle_status=lifecycle,
        source_class=source_class,
        announcement_ts=_timestamp(_first(raw, "announcementTime", "announceTime")),
        tradable_ts=launch_ts,
        official_spot_listing_ts=official_listing_ts,
        transition_ts=transition_ts,
        expiry_ts=expiry_ts,
        tick_size=_as_float(price_filter.get("tickSize")),
        lot_size=_as_float(lot_filter.get("qtyStep")),
        min_qty=_as_float(_first(lot_filter, "minOrderQty", "minNotionalValue")),
        max_leverage=_as_float(leverage_filter.get("maxLeverage")),
        maintenance_margin_rate=_as_float(_first(raw, "maintenanceMarginRate", "maintenanceRate")),
        price_limit_up=_as_float(_first(raw, "upperPriceLimit", "priceLimitUp")),
        price_limit_down=_as_float(_first(raw, "lowerPriceLimit", "priceLimitDown")),
        maker_fee_bps=_rate_to_bps(_first(fee_info, "makerFeeRate", "maker_fee_rate")),
        taker_fee_bps=_rate_to_bps(_first(fee_info, "takerFeeRate", "taker_fee_rate")),
        source_url="https://api.bybit.com/v5/market/instruments-info?category=linear&status=PreLaunch",
        raw=raw,
    )


def normalize_okx_instrument(item: Mapping[str, Any], *, source_class: str = SourceClass.OFFICIAL.value) -> PreMarketContract | None:
    """Normalise an OKX public SWAP pre-market instrument."""

    raw = dict(item)
    if str(raw.get("instType") or "SWAP").upper() != "SWAP":
        return None
    quote = str(_first(raw, "quoteCcy", "settleCcy") or "").upper()
    if quote != "USDT":
        return None
    rule_type = _normalise_status(raw.get("ruleType"))
    transition_ts = _timestamp(raw.get("preMktSwTime"))
    is_premarket = rule_type in {"pre_market", "premarket"} or transition_ts is not None or bool(raw.get("isPreMarket"))
    if not is_premarket:
        return None

    inst_id = str(raw.get("instId") or "").upper()
    base = str(_first(raw, "baseCcy") or "").upper()
    if not base:
        base = inst_id.removesuffix("-SWAP").rsplit("-", 1)[0]
    spot_symbol = f"{base}-{quote}"
    state = _normalise_status(raw.get("state"))
    phase = _phase(_first(raw, "openType", "phase"))
    lifecycle = phase if phase != PreMarketPhase.UNKNOWN.value else "scheduled"
    if state in {"suspend", "offline", "closed"}:
        lifecycle = "cancelled"
    elif rule_type not in {"pre_market", "premarket"} and transition_ts is not None:
        lifecycle = "transitioned"

    max_limit = _as_float(raw.get("maxPxLmtPct"))
    return PreMarketContract(
        venue="okx",
        contract_id=inst_id,
        spot_symbol=spot_symbol,
        base=base,
        quote=quote,
        phase=phase,
        lifecycle_status=lifecycle,
        source_class=source_class,
        announcement_ts=_timestamp(_first(raw, "announcementTime", "announceTime")),
        tradable_ts=_timestamp(_first(raw, "listTime", "auctionEndTime")),
        official_spot_listing_ts=_timestamp(_first(raw, "spotListingTime", "spotListTime")),
        transition_ts=transition_ts,
        expiry_ts=_timestamp(raw.get("expTime")),
        tick_size=_as_float(raw.get("tickSz")),
        lot_size=_as_float(raw.get("lotSz")),
        min_qty=_as_float(raw.get("minSz")),
        contract_multiplier=_as_float(raw.get("ctVal")) or 1.0,
        max_leverage=_as_float(raw.get("lever")),
        maintenance_margin_rate=_as_float(_first(raw, "maintenanceMarginRate", "mmr")),
        price_limit_up=max_limit,
        price_limit_down=max_limit,
        maker_fee_bps=_rate_to_bps(_first(raw, "makerFeeRate", "maker_fee_rate")),
        taker_fee_bps=_rate_to_bps(_first(raw, "takerFeeRate", "taker_fee_rate")),
        source_url="https://www.okx.com/api/v5/public/instruments?instType=SWAP",
        raw=raw,
    )


def normalize_gate_instrument(item: Mapping[str, Any], *, source_class: str = SourceClass.OFFICIAL.value) -> PreMarketContract | None:
    """Normalise a Gate USDT futures pre-launch/pre-market contract."""

    raw = dict(item)
    name = str(_first(raw, "name", "contract") or "").upper()
    quote = str(_first(raw, "quote", "settle", "settle_coin") or "USDT").upper()
    status = _normalise_status(raw.get("status"))
    phase = _phase(_first(raw, "phase", "auction_phase", "pre_market_phase"))
    premarket_flag = bool(_first(raw, "premarket", "pre_market", "is_pre_market", "isPreMarket"))
    is_premarket = premarket_flag or status in {"prelaunch", "pre_launch"} or "pre_market" in status
    if not is_premarket or quote != "USDT" or not name:
        return None

    base = str(_first(raw, "base", "base_coin") or _base_from_symbol(name, quote, "_")).upper()
    if phase == PreMarketPhase.UNKNOWN.value and status in {"trading", "live"}:
        phase = PreMarketPhase.CONTINUOUS.value
    lifecycle = "scheduled" if status in {"prelaunch", "pre_launch"} else phase
    if status in {"delisted", "closed"}:
        lifecycle = "delisted"
    elif status in {"delisting", "circuit_breaker"}:
        lifecycle = "delisted" if status == "delisting" else "cancelled"
    transition_ts = _timestamp(_first(raw, "spot_listing_time", "pre_market_switch_time", "transition_time", "preMktSwTime"))
    return PreMarketContract(
        venue="gate",
        contract_id=name,
        spot_symbol=f"{base}_{quote}",
        base=base,
        quote=quote,
        phase=phase,
        lifecycle_status=lifecycle,
        source_class=source_class,
        announcement_ts=_timestamp(_first(raw, "announcement_time", "announce_time")),
        tradable_ts=_timestamp(_first(raw, "create_time", "launch_time")),
        official_spot_listing_ts=_timestamp(_first(raw, "spot_listing_time", "spot_list_time")),
        transition_ts=transition_ts,
        expiry_ts=_timestamp(_first(raw, "delisting_time", "delisted_time", "expiry_time")),
        tick_size=_as_float(_first(raw, "order_price_round", "tick_size")),
        lot_size=_as_float(_first(raw, "order_size_min", "lot_size")),
        min_qty=_as_float(_first(raw, "order_size_min", "min_order_qty")),
        contract_multiplier=_as_float(_first(raw, "quanto_multiplier", "contract_size")) or 1.0,
        max_leverage=_as_float(_first(raw, "leverage_max", "max_leverage")),
        maintenance_margin_rate=_as_float(_first(raw, "maintenance_rate", "maintenance_margin_rate")),
        price_limit_up=_as_float(_first(raw, "market_order_slip_ratio", "price_limit_up")),
        price_limit_down=_as_float(_first(raw, "market_order_slip_ratio", "price_limit_down")),
        maker_fee_bps=_rate_to_bps(_first(raw, "maker_fee_rate", "makerFeeRate")),
        taker_fee_bps=_rate_to_bps(_first(raw, "taker_fee_rate", "takerFeeRate")),
        source_url="https://api.gateio.ws/api/v4/futures/usdt/contracts",
        raw=raw,
    )


def normalise_contract(
    venue: str,
    item: Mapping[str, Any],
    *,
    source_class: str = SourceClass.OFFICIAL.value,
    acceptance_class: str | None = ASSET_CLASS_CRYPTO_TOKEN,
    crypto_underlyings: Iterable[str] | None = None,
) -> PreMarketContract | None:
    """Normalise one venue instrument, refusing anything outside the asked-for class.

    acceptance_class defaults to crypto because this module feeds the crypto pre-market
    track. Pass None to normalise without an asset-class gate - descriptive observation
    is still allowed; what is forbidden is counting an instrument as a sample of a
    strategy whose asset class nobody established.

    Until 2026-08-24 there was no gate at all, and a pre-market marker was taken as
    sufficient. Bybit, OKX and Gate all mark equity pre-IPO products with exactly the
    same markers as crypto tokens, so the crypto track collected ANTHROPIC, ANDURIL,
    OPENAI and others that the Pre-IPO track was collecting at the same time.
    """
    venue_key = venue.strip().lower()
    if venue_key == "bybit":
        contract = normalize_bybit_instrument(item, source_class=source_class)
    elif venue_key == "okx":
        contract = normalize_okx_instrument(item, source_class=source_class)
    elif venue_key in {"gate", "gateio"}:
        contract = normalize_gate_instrument(item, source_class=source_class)
    else:
        raise ValueError(f"Unsupported pre-market venue: {venue}")

    if contract is None or acceptance_class is None:
        return contract
    if not belongs_to(
        contract.contract_id,
        acceptance_class,
        crypto_underlyings=crypto_underlyings,
    ):
        return None
    return contract


def _payload_data(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    if isinstance(payload, Mapping) and "result" in payload:
        result = payload["result"]
        if isinstance(result, Mapping):
            if "data" in result:
                return result["data"]
            if "list" in result:
                return result["list"]
        return result
    return payload


def _levels(value: Any) -> list[list[float]]:
    out: list[list[float]] = []
    if isinstance(value, Mapping):
        value = [[value.get("price", value.get("p")), value.get("qty", value.get("s", value.get("size")))] ]
    for row in value or []:
        if isinstance(row, Mapping):
            price = _as_float(_first(row, "price", "p"))
            qty = _as_float(_first(row, "qty", "size", "s"))
        else:
            price = _as_float(row[0]) if len(row) > 0 else None
            qty = _as_float(row[1]) if len(row) > 1 else None
        if price is not None and qty is not None and price > 0 and qty >= 0:
            out.append([price, qty])
    return out


def _event_common(
    *,
    venue: str,
    contract_id: str,
    kind: str,
    channel: str,
    exchange_ts: float | None,
    received_ts: float,
    phase: str | None = None,
    source_seq: Any = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "exchange": "gate" if venue.lower() == "gateio" else venue.lower(),
        "symbol": contract_id,
        "event_kind": kind,
        "channel": channel,
        "exchange_ts": exchange_ts if exchange_ts is not None else received_ts,
        "recv_ts": received_ts,
    }
    if phase:
        event["premarket_phase"] = phase
    if source_seq is not None:
        event["source_seq"] = source_seq
    return event


def _normalise_bybit_payload(venue: str, contract_id: str, payload: Mapping[str, Any], received_ts: float) -> list[dict[str, Any]]:
    topic = str(payload.get("topic") or payload.get("channel") or "")
    data = _payload_data(payload)
    rows = data if isinstance(data, list) else [data]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if "orderbook" in topic or "b" in row or "a" in row:
            exchange_ts = _timestamp(_first(row, "cts", "ts")) or _timestamp(payload.get("ts"))
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="depth",
                channel=topic or "premarket.orderbook",
                exchange_ts=exchange_ts,
                received_ts=received_ts,
                source_seq=_first(row, "u", "seq"),
            )
            event.update(
                {
                    "depth_type": str(payload.get("type") or "snapshot"),
                    "bids": _levels(row.get("b")),
                    "asks": _levels(row.get("a")),
                    "mark_price": _as_float(_first(row, "markPrice", "markPx")),
                    "index_price": _as_float(_first(row, "indexPrice", "idxPrice")),
                    "funding_rate": _as_float(row.get("fundingRate")),
                }
            )
            if event["bids"] and event["asks"]:
                event.update(
                    {
                        "bid_price": event["bids"][0][0],
                        "bid_qty": event["bids"][0][1],
                        "ask_price": event["asks"][0][0],
                        "ask_qty": event["asks"][0][1],
                    }
                )
            out.append(event)
        elif "trade" in topic:
            exchange_ts = _timestamp(_first(row, "T", "ts")) or _timestamp(payload.get("ts"))
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="trade",
                channel=topic or "premarket.trades",
                exchange_ts=exchange_ts,
                received_ts=received_ts,
                source_seq=_first(row, "i", "tradeId"),
            )
            event.update(
                {
                    "trade_id": _first(row, "i", "tradeId"),
                    "price": _as_float(_first(row, "p", "px")),
                    "qty": _as_float(_first(row, "v", "sz")),
                    "side": str(_first(row, "S", "side") or "").lower(),
                }
            )
            out.append(event)
        else:
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="bbo",
                channel=topic or "premarket.ticker",
                exchange_ts=_timestamp(_first(row, "ts", "T")) or _timestamp(payload.get("ts")),
                received_ts=received_ts,
            )
            event.update(
                {
                    "bid_price": _as_float(_first(row, "bid1Price", "bidPx")),
                    "bid_qty": _as_float(_first(row, "bid1Size", "bidSz")),
                    "ask_price": _as_float(_first(row, "ask1Price", "askPx")),
                    "ask_qty": _as_float(_first(row, "ask1Size", "askSz")),
                    "mark_price": _as_float(_first(row, "markPrice", "markPx")),
                    "index_price": _as_float(_first(row, "indexPrice", "idxPx")),
                    "funding_rate": _as_float(row.get("fundingRate")),
                    "next_funding_ts": _timestamp(_first(row, "nextFundingTime", "nextFundingTs")),
                    "open_interest": _as_float(_first(row, "openInterest", "oi")),
                }
            )
            out.append(event)
    return out


def _normalise_okx_payload(venue: str, contract_id: str, payload: Mapping[str, Any], received_ts: float) -> list[dict[str, Any]]:
    arg = payload.get("arg") or {}
    channel = str(arg.get("channel") or payload.get("channel") or "")
    rows = _payload_data(payload)
    if not isinstance(rows, list):
        rows = [rows]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if channel in {"books", "books5", "books50-l2-tbt", "books-l2-tbt"}:
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="depth",
                channel=channel,
                exchange_ts=_timestamp(row.get("ts")),
                received_ts=received_ts,
                source_seq=_first(row, "seqId", "checksum"),
            )
            event.update({"depth_type": "snapshot", "bids": _levels(row.get("bids")), "asks": _levels(row.get("asks"))})
            if event["bids"] and event["asks"]:
                event.update(
                    {
                        "bid_price": event["bids"][0][0],
                        "bid_qty": event["bids"][0][1],
                        "ask_price": event["asks"][0][0],
                        "ask_qty": event["asks"][0][1],
                    }
                )
            out.append(event)
        elif channel == "trades":
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="trade",
                channel=channel,
                exchange_ts=_timestamp(row.get("ts")),
                received_ts=received_ts,
                source_seq=_first(row, "tradeId", "trade_id"),
            )
            event.update({"trade_id": _first(row, "tradeId", "trade_id"), "price": _as_float(row.get("px")), "qty": _as_float(row.get("sz")), "side": str(row.get("side") or "").lower()})
            out.append(event)
        else:
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="bbo",
                channel=channel or "premarket.ticker",
                exchange_ts=_timestamp(_first(row, "ts", "ts")),
                received_ts=received_ts,
            )
            event.update(
                {
                    "bid_price": _as_float(row.get("bidPx")),
                    "bid_qty": _as_float(row.get("bidSz")),
                    "ask_price": _as_float(row.get("askPx")),
                    "ask_qty": _as_float(row.get("askSz")),
                    "mark_price": _as_float(row.get("markPx")),
                    "index_price": _as_float(row.get("idxPx")),
                    "funding_rate": _as_float(row.get("fundingRate")),
                    "open_interest": _as_float(row.get("oi")),
                }
            )
            out.append(event)
    return out


def _normalise_gate_payload(venue: str, contract_id: str, payload: Any, received_ts: float) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping) and isinstance(payload.get("result"), list):
        rows = payload["result"]
    elif isinstance(payload, Mapping):
        rows = [payload]
    else:
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        channel = str(row.get("channel") or row.get("method") or "")
        if "order" in channel or "book" in channel or "bids" in row or "asks" in row:
            bids = _levels(row.get("bids"))
            asks = _levels(row.get("asks"))
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="depth",
                channel=channel or "premarket.order_book",
                exchange_ts=_timestamp(_first(row, "t", "time", "update")),
                received_ts=received_ts,
                source_seq=_first(row, "id", "orderbook_id"),
            )
            event.update({"depth_type": "snapshot", "bids": bids, "asks": asks})
            if bids and asks:
                event.update({"bid_price": bids[0][0], "bid_qty": bids[0][1], "ask_price": asks[0][0], "ask_qty": asks[0][1]})
            out.append(event)
        elif "trade" in channel or "trades" in channel or "price" in row and "size" in row:
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="trade",
                channel=channel or "premarket.trades",
                exchange_ts=_timestamp(_first(row, "create_time_ms", "create_time", "time")),
                received_ts=received_ts,
                source_seq=_first(row, "id", "trade_id"),
            )
            size = _as_float(_first(row, "size", "qty", "amount"))
            event.update({"trade_id": _first(row, "id", "trade_id"), "price": _as_float(_first(row, "price", "px")), "qty": abs(size) if size is not None else None, "side": "buy" if size is not None and size > 0 else "sell" if size is not None and size < 0 else str(row.get("side") or "").lower()})
            out.append(event)
        else:
            event = _event_common(
                venue=venue,
                contract_id=contract_id,
                kind="bbo",
                channel=channel or "premarket.ticker",
                exchange_ts=_timestamp(_first(row, "time", "timestamp")),
                received_ts=received_ts,
            )
            event.update({"bid_price": _as_float(_first(row, "highest_bid", "bid")), "ask_price": _as_float(_first(row, "lowest_ask", "ask")), "mark_price": _as_float(row.get("mark_price")), "index_price": _as_float(row.get("index_price")), "funding_rate": _as_float(row.get("funding_rate")), "open_interest": _as_float(_first(row, "position_size", "open_interest"))})
            out.append(event)
    return out


def normalize_market_payload(venue: str, contract_id: str, payload: Mapping[str, Any] | list[Any], *, received_ts: float | None = None) -> list[dict[str, Any]]:
    received = time.time() if received_ts is None else float(received_ts)
    venue_key = venue.strip().lower()
    if venue_key == "bybit":
        return _normalise_bybit_payload(venue_key, contract_id, payload if isinstance(payload, Mapping) else {}, received)
    if venue_key == "okx":
        return _normalise_okx_payload(venue_key, contract_id, payload if isinstance(payload, Mapping) else {}, received)
    if venue_key in {"gate", "gateio"}:
        return _normalise_gate_payload(venue_key, contract_id, payload, received)
    raise ValueError(f"Unsupported pre-market venue: {venue}")


def normalize_market_event(venue: str, contract_id: str, payload: Mapping[str, Any], *, received_ts: float | None = None) -> dict[str, Any]:
    events = normalize_market_payload(venue, contract_id, payload, received_ts=received_ts)
    if not events:
        raise ValueError("market payload did not contain a supported public event")
    return events[0]


def build_entry_candidates(
    contract: Mapping[str, Any] | PreMarketContract,
    *,
    first_tradable_observation_ts: float | None = None,
) -> list[dict[str, Any]]:
    raw = contract.as_dict() if isinstance(contract, PreMarketContract) else dict(contract)
    # The observation proxy is explicitly separate from the official contract
    # launch timestamp and never upgrades a proxy event to acceptance-grade.
    tradable_ts = _as_float(first_tradable_observation_ts)
    tradable_source = "detection_proxy" if tradable_ts is not None else "official_contract"
    if tradable_ts is None:
        tradable_ts = _as_float(raw.get("tradable_ts"))
    listing_ts = _as_float(raw.get("official_spot_listing_ts"))
    if tradable_ts is None or listing_ts is None or listing_ts <= tradable_ts:
        return []
    base = {
        "venue": raw.get("venue"),
        "contract_id": raw.get("contract_id"),
        "spot_symbol": raw.get("spot_symbol"),
        "phase": raw.get("phase", PreMarketPhase.UNKNOWN.value),
        "source_class": raw.get("source_class", SourceClass.OFFICIAL.value),
        "listing_ts": listing_ts,
    }
    candidates = [base | {"entry_cohort": "first_tradable", "entry_ts": tradable_ts, "entry_ts_class": tradable_source}]
    candidates.append(base | {"entry_cohort": "last_1_4h", "entry_ts": max(tradable_ts, listing_ts - 14_400.0), "entry_ts_class": tradable_source})
    return candidates


def build_replay_config(
    *,
    notional_quote: float = 25.0,
    execution_mode: str = "taker",
    taker_fee_bps: float = 10.0,
    maker_fee_bps: float = 0.0,
    slippage_bps: float = 1.0,
    latency_ms: int = 250,
    maker_queue_ahead_qty: float = 0.0,
    maker_queue_model: str = "fixed",
    maker_queue_ahead_fraction: float = 1.0,
    maker_order_ttl_sec: float = 5.0,
) -> ReplayConfig:
    """Build the existing ws_replay/perp_replay execution contract.

    Pre-market replay keeps event-relative exits and lifecycle gating in this
    module, while latency, queue-ahead, maker TTL and fee/slippage settings use
    the same typed configuration as the existing perpetual replay engine.
    """

    return ReplayConfig(
        notional_quote=notional_quote,
        execution_mode=execution_mode,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        slippage_bps=slippage_bps,
        latency_ms=latency_ms,
        maker_queue_ahead_qty=maker_queue_ahead_qty,
        maker_queue_model=maker_queue_model,
        maker_queue_ahead_fraction=maker_queue_ahead_fraction,
        maker_order_ttl_sec=maker_order_ttl_sec,
    )


def _event_ts(event: Mapping[str, Any]) -> float | None:
    # Decisions can only use data after it reached our collector.  Exchange
    # time remains descriptive/freshness evidence and is only a fallback for
    # legacy fixtures that genuinely predate receive-time capture.
    return _timestamp(event.get("recv_ts")) or _timestamp(event.get("exchange_ts"))


def _bbo_event(event: Mapping[str, Any]) -> bool:
    return _as_float(event.get("bid_price")) is not None and _as_float(event.get("ask_price")) is not None


def _latest_bbo_before(
    events: Iterable[Mapping[str, Any]],
    ts: float,
    *,
    max_age_sec: float = MAX_BBO_STALENESS_SEC,
) -> Mapping[str, Any] | None:
    selected: Mapping[str, Any] | None = None
    selected_ts = -math.inf
    for event in events:
        event_ts = _event_ts(event)
        if (
            event_ts is None
            or event_ts > ts
            or event_ts < ts - max_age_sec
            or not _bbo_event(event)
        ):
            continue
        if event_ts >= selected_ts:
            selected = event
            selected_ts = event_ts
    return selected


def _first_bbo_at_or_after(
    events: Iterable[Mapping[str, Any]],
    ts: float,
    *,
    max_delay_sec: float = MAX_BBO_STALENESS_SEC,
) -> Mapping[str, Any] | None:
    candidates = [
        event
        for event in events
        if (event_ts := _event_ts(event)) is not None
        and ts <= event_ts <= ts + max_delay_sec
        and _bbo_event(event)
    ]
    return min(candidates, key=lambda event: _event_ts(event) or math.inf) if candidates else None


def _identity_key(value: Any) -> str:
    return "".join(char for char in str(value or "").upper() if char.isalnum())


def _event_contract_identity(event: Mapping[str, Any]) -> str:
    return _identity_key(
        _first(
            event,
            "premarket_contract_id",
            "contract_id",
            "instId",
            "inst_id",
            "symbol",
        )
    )


def _funding_between(entry_event: Mapping[str, Any], exit_event: Mapping[str, Any], qty: float, mark_price: float) -> tuple[float, int]:
    rate = _as_float(entry_event.get("funding_rate"))
    interval = _as_float(entry_event.get("funding_interval_sec")) or 28_800.0
    next_ts = _timestamp(entry_event.get("next_funding_ts"))
    start = _event_ts(entry_event) or 0.0
    end = _event_ts(exit_event) or start
    if rate is None or next_ts is None or interval <= 0 or next_ts > end:
        return 0.0, 0
    settlements = 0
    funding = 0.0
    while next_ts <= end:
        funding -= qty * mark_price * rate
        settlements += 1
        next_ts += interval
    return funding, settlements


def _liquidation_stress(entry_price: float, mark_events: Iterable[Mapping[str, Any]], maintenance_rate: float | None) -> dict[str, Any]:
    if maintenance_rate is None or maintenance_rate < 0 or maintenance_rate >= 1:
        return {"available": False, "reason": "liquidation_model_missing", "scenarios": []}
    scenarios: list[dict[str, Any]] = []
    for leverage in (2.0, 5.0):
        # Conservative linear-long proxy: available equity is 1/leverage and
        # maintenance margin plus a one-tick buffer is retained.
        liquidation_mark = entry_price * max(0.0, 1.0 - (1.0 / leverage) + maintenance_rate)
        hit = None
        for event in mark_events:
            mark = _as_float(event.get("mark_price"))
            ts = _event_ts(event)
            if mark is not None and ts is not None and mark <= liquidation_mark:
                hit = {"ts": ts, "mark_price": mark}
                break
        scenarios.append({"leverage": leverage, "liquidation_mark": liquidation_mark, "liquidated": hit is not None, "hit": hit})
    return {"available": True, "reason": None, "scenarios": scenarios}


def _maker_fill_qty(
    events: Iterable[Mapping[str, Any]],
    *,
    start_ts: float,
    ttl_sec: float,
    requested_qty: float,
    queue_ahead_qty: float,
    side: str,
) -> float:
    """Approximate queue consumption using causal trades inside order TTL."""

    if requested_qty <= 0 or ttl_sec <= 0:
        return 0.0
    consumed = 0.0
    end_ts = start_ts + ttl_sec
    for event in events:
        ts = _event_ts(event)
        if ts is None or ts < start_ts or ts > end_ts or str(event.get("event_kind")) != "trade":
            continue
        trade_side = str(event.get("side") or "").lower()
        if side == "buy" and trade_side not in {"sell", "-1", "short"}:
            continue
        if side == "sell" and trade_side not in {"buy", "+1", "long"}:
            continue
        qty = max(0.0, _as_float(event.get("qty")) or 0.0)
        if qty <= 0:
            continue
        if queue_ahead_qty > 0:
            queue_consumed = min(queue_ahead_qty, qty)
            queue_ahead_qty -= queue_consumed
            qty -= queue_consumed
        consumed += qty
        if consumed >= requested_qty:
            return requested_qty
    return min(requested_qty, consumed)


def replay_listing_event(
    contract: Mapping[str, Any] | PreMarketContract,
    events: Iterable[Mapping[str, Any]],
    *,
    notional_quote: float = 25.0,
    entry_ts: float | None = None,
    taker_fee_bps: float | None = None,
    slippage_bps: float = 0.0,
    replay_config: ReplayConfig | None = None,
) -> dict[str, Any]:
    """Replay one LONG event with causal entry and listing-relative exits.

    The default path is taker-like (the primary cost model). Passing a
    ``ReplayConfig`` from the existing ws/perp replay stack enables the same
    latency and maker queue/TTL sensitivity semantics without changing the
    pre-registered event-relative exit policy.
    """

    raw_contract = contract.as_dict() if isinstance(contract, PreMarketContract) else dict(contract)
    cfg = replay_config or build_replay_config(
        notional_quote=notional_quote,
        execution_mode="taker",
        taker_fee_bps=taker_fee_bps if taker_fee_bps is not None else (_as_float(raw_contract.get("taker_fee_bps")) or 0.0),
        slippage_bps=slippage_bps,
        latency_ms=0,
    )
    notional_quote = float(cfg.notional_quote)
    execution_mode = str(cfg.execution_mode).strip().lower()
    if execution_mode not in {"taker", "maker"}:
        raise ValueError(f"Unsupported replay execution_mode: {cfg.execution_mode}")
    effective_latency_sec = max(0.0, float(cfg.latency_ms)) / 1000.0
    effective_slippage_bps = float(cfg.slippage_bps)
    fee_rate = float(taker_fee_bps if taker_fee_bps is not None else (_as_float(raw_contract.get("taker_fee_bps")) or cfg.taker_fee_bps))
    contract_identity = _identity_key(raw_contract.get("contract_id"))
    raw_events = [dict(event) for event in events]
    mismatched_identity_events = [
        event
        for event in raw_events
        if (event_identity := _event_contract_identity(event))
        and contract_identity
        and event_identity != contract_identity
    ]
    matching_events = [event for event in raw_events if event not in mismatched_identity_events]
    identity_evidence_missing = not contract_identity or any(
        not _event_contract_identity(event) for event in matching_events
    )
    ordered = sorted(matching_events, key=lambda event: (_event_ts(event) or math.inf, event.get("recv_ts", math.inf)))
    listing_ts = _as_float(raw_contract.get("official_spot_listing_ts"))
    if entry_ts is None:
        entry_ts = _as_float(raw_contract.get("tradable_ts"))
    if listing_ts is None or entry_ts is None:
        return {"event_status": "incomplete", "acceptance_eligible": False, "reason": "missing_official_listing_or_entry_ts", "exits": {}, "exit_offsets_sec": list(EXIT_OFFSETS_SEC), "fill_denominator": 1}

    entry_ready_ts = entry_ts + effective_latency_sec
    entry_event = _latest_bbo_before(ordered, entry_ts) if effective_latency_sec <= 0 else _first_bbo_at_or_after(ordered, entry_ready_ts)
    listing_source_class = str(
        raw_contract.get("listing_source_class") or SourceClass.PROXY.value
    ).strip().lower()
    resolver_acceptance_eligible = raw_contract.get("acceptance_eligible") is True
    event_id = str(raw_contract.get("event_id") or "").strip() or (
        f"{str(raw_contract.get('venue') or '').lower()}:"
        f"{str(raw_contract.get('contract_id') or '')}:"
        f"{listing_ts:.6f}"
    )
    fee_model_missing = taker_fee_bps is None and _as_float(raw_contract.get("taker_fee_bps")) is None
    result: dict[str, Any] = {
        "event_id": event_id,
        "event_status": "complete",
        "acceptance_eligible": False,
        "entry_ts": entry_ts,
        "listing_ts": listing_ts,
        "exit_offsets_sec": list(EXIT_OFFSETS_SEC),
        "fill_denominator": 1,
        "source_class": listing_source_class,
        "contract_source_class": str(
            raw_contract.get("source_class") or SourceClass.PROXY.value
        ).strip().lower(),
        "resolver_acceptance_eligible": resolver_acceptance_eligible,
        "fee_model_missing": fee_model_missing,
        "identity_evidence_missing": identity_evidence_missing,
        "identity_mismatch_events_ignored": len(mismatched_identity_events),
        "venue": raw_contract.get("venue"),
        "contract_id": raw_contract.get("contract_id"),
        "entry_fill_status": "unfilled",
        "filled": False,
        "exits": {},
        "execution_mode": execution_mode,
        "latency_ms": int(cfg.latency_ms),
        "maker_order_ttl_sec": float(cfg.maker_order_ttl_sec),
        "maker_queue_ahead_qty": float(cfg.maker_queue_ahead_qty),
    }
    if entry_event is None:
        result.update({"event_status": "incomplete", "reason": "missing_causal_entry_bbo"})
        return result

    entry_ask = _as_float(entry_event.get("ask_price"))
    entry_ask_qty = _as_float(entry_event.get("ask_qty")) or 0.0
    if entry_ask is None or entry_ask <= 0:
        result.update({"event_status": "incomplete", "reason": "invalid_entry_ask"})
        return result
    if execution_mode == "maker":
        entry_ask = _as_float(entry_event.get("bid_price")) or entry_ask
        requested_qty = notional_quote / entry_ask
        queue_ahead = float(cfg.maker_queue_ahead_qty)
        if str(cfg.maker_queue_model) == "top_qty_fraction":
            queue_ahead = max(queue_ahead, (_as_float(entry_event.get("bid_qty")) or 0.0) * max(0.0, float(cfg.maker_queue_ahead_fraction)))
        filled_qty = _maker_fill_qty(
            ordered,
            start_ts=entry_ready_ts,
            ttl_sec=float(cfg.maker_order_ttl_sec),
            requested_qty=requested_qty,
            queue_ahead_qty=queue_ahead,
            side="buy",
        )
    else:
        requested_qty = notional_quote / entry_ask
        filled_qty = min(requested_qty, entry_ask_qty) if entry_ask_qty > 0 else 0.0
    if filled_qty <= 0:
        entry_status = "unfilled"
    elif filled_qty + 1e-12 < requested_qty:
        entry_status = "partial"
    else:
        entry_status = "full"
    result["entry_fill_status"] = entry_status
    result["filled"] = entry_status in {"full", "partial"}
    result["entry_price"] = entry_ask * (1.0 + effective_slippage_bps / 10_000.0) if execution_mode == "taker" else entry_ask
    result["requested_qty"] = requested_qty
    result["filled_qty"] = filled_qty
    result["entry_notional_quote"] = filled_qty * result["entry_price"]

    if execution_mode == "maker":
        fee_rate = float(_as_float(raw_contract.get("maker_fee_bps")) or cfg.maker_fee_bps)
    entry_fee = result["entry_notional_quote"] * fee_rate / 10_000.0
    result["entry_fee_quote"] = entry_fee

    exit_missing = False
    for offset in EXIT_OFFSETS_SEC:
        key = "t0" if offset == 0 else f"t0_plus_{offset}s"
        exit_ready_ts = listing_ts + offset + effective_latency_sec
        exit_event = _first_bbo_at_or_after(ordered, exit_ready_ts)
        if exit_event is None:
            exit_missing = True
            result["exits"][key] = {"offset_sec": offset, "available": False, "reason": "missing_exit_bbo"}
            continue
        exit_bid = _as_float(exit_event.get("bid_price"))
        exit_bid_qty = _as_float(exit_event.get("bid_qty")) or 0.0
        if execution_mode == "maker":
            queue_ahead = float(cfg.maker_queue_ahead_qty)
            if str(cfg.maker_queue_model) == "top_qty_fraction":
                queue_ahead = max(queue_ahead, (_as_float(exit_event.get("bid_qty")) or 0.0) * max(0.0, float(cfg.maker_queue_ahead_fraction)))
            exit_qty = _maker_fill_qty(
                ordered,
                start_ts=exit_ready_ts,
                ttl_sec=float(cfg.maker_order_ttl_sec),
                requested_qty=filled_qty,
                queue_ahead_qty=queue_ahead,
                side="sell",
            )
        else:
            exit_qty = min(filled_qty, exit_bid_qty) if exit_bid is not None and exit_bid_qty > 0 else 0.0
        if exit_qty <= 0:
            exit_status = "unfilled"
        elif exit_qty + 1e-12 < filled_qty:
            exit_status = "partial"
        else:
            exit_status = "full"
        exit_price = exit_bid if execution_mode == "maker" else exit_bid * (1.0 - effective_slippage_bps / 10_000.0) if exit_bid is not None else None
        exit_notional = exit_qty * exit_price if exit_price is not None else 0.0
        exit_fee = exit_notional * fee_rate / 10_000.0
        gross = (exit_price - result["entry_price"]) * exit_qty if exit_price is not None else 0.0
        funding, settlements = _funding_between(entry_event, exit_event, exit_qty, _as_float(entry_event.get("mark_price")) or result["entry_price"])
        net = gross - entry_fee * (exit_qty / filled_qty if filled_qty else 0.0) - exit_fee + funding
        result["exits"][key] = {
            "offset_sec": offset,
            "available": True,
            "fill_status": exit_status,
            "filled_qty": exit_qty,
            "exit_price": exit_price,
            "gross_pnl_quote": gross,
            "funding_pnl_quote": funding,
            "funding_settlements": settlements,
            "exit_fee_quote": exit_fee,
            "net_pnl_quote": net,
            "exit_ts": _event_ts(exit_event),
        }

    if exit_missing:
        result["event_status"] = "incomplete"
    result["liquidation_stress"] = _liquidation_stress(
        result["entry_price"],
        ordered,
        _as_float(raw_contract.get("maintenance_margin_rate")),
    )
    result["liquidation_model_missing"] = not bool(result["liquidation_stress"]["available"])
    t0 = result["exits"].get("t0") or {}
    result["net_pnl_quote"] = t0.get("net_pnl_quote", 0.0) if t0.get("available") else 0.0
    result["round_trip_filled"] = bool(
        result["filled"] and t0.get("fill_status") in {"full", "partial"}
    )
    result["acceptance_eligible"] = bool(
        result["event_status"] == "complete"
        and result["source_class"] == SourceClass.OFFICIAL.value
        and resolver_acceptance_eligible
        and not fee_model_missing
        and not identity_evidence_missing
        and not result["liquidation_model_missing"]
    )
    if result["source_class"] != SourceClass.OFFICIAL.value or not resolver_acceptance_eligible:
        result["acceptance_reason"] = "official_t0_resolver_evidence_missing"
    elif fee_model_missing:
        result["acceptance_reason"] = "public_taker_fee_missing"
    elif identity_evidence_missing:
        result["acceptance_reason"] = "contract_identity_evidence_missing"
    elif result["liquidation_model_missing"]:
        result["acceptance_reason"] = "liquidation_model_missing"
    elif result["event_status"] != "complete":
        result["acceptance_reason"] = "event_incomplete"
    else:
        result["acceptance_reason"] = None
    return result


def _profit_factor(values: list[float]) -> float:
    positive = sum(value for value in values if value > 0)
    negative = abs(sum(value for value in values if value < 0))
    if negative == 0:
        return math.inf if positive > 0 else 0.0
    return positive / negative


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


PRIMARY_ENTRY_COHORT = "first_tradable"
PRIMARY_EXIT_POLICY = "t0"


def _cell_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate one preregistered entry-cohort/exit-policy cell.

    Rows from different cohorts or exits never enter the same metric.  If one
    underlying event has multiple venue rows in a cell, no venue is selected
    after seeing the result: that event becomes an identity conflict and fails
    closed until a venue-selection rule is preregistered.
    """

    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_event.setdefault(str(row["event_id"]), []).append(row)

    events: list[dict[str, Any]] = []
    for event_id, group in by_event.items():
        conflict = len(group) != 1 or any(bool(row.get("cell_revision_conflict")) for row in group)
        row = group[0]
        official = all(
            str(item.get("source_class") or "").strip().lower()
            == SourceClass.OFFICIAL.value
            for item in group
        )
        round_trip_filled = bool(row.get("round_trip_filled")) if not conflict else False
        # An entry-only or zero-fill observation stays in the fill denominator
        # and contributes zero PnL; it never receives synthetic chart profit.
        pnl = (_as_float(row.get("net_pnl_quote")) or 0.0) if round_trip_filled else 0.0
        events.append(
            {
                "event_id": event_id,
                "venue": str(row.get("venue") or "").strip().lower() if not conflict else "",
                "identity_conflict": conflict,
                "official": official,
                "net_pnl_quote": pnl,
                "round_trip_filled": round_trip_filled,
                "stress_filled": bool(row.get("stress_filled")) if not conflict else False,
                "liquidation_model_missing": any(
                    bool(item.get("liquidation_model_missing")) for item in group
                ),
                "acceptance_eligible": (
                    not conflict
                    and all(bool(item.get("acceptance_eligible")) for item in group)
                ),
            }
        )

    official = [event for event in events if event["official"]]
    official_acceptance = [
        event
        for event in official
        if event["acceptance_eligible"]
        and not event["liquidation_model_missing"]
        and not event["identity_conflict"]
        and event["venue"]
    ]
    pnl = [float(event["net_pnl_quote"]) for event in official_acceptance]
    fill_rate = (
        sum(1 for event in official if event["round_trip_filled"]) / len(official)
        if official
        else 0.0
    )
    stress_fill_rate = (
        sum(1 for event in official if event["stress_filled"]) / len(official)
        if official
        else 0.0
    )
    official_events_by_venue = {
        venue: sum(1 for event in official_acceptance if event["venue"] == venue)
        for venue in sorted({str(event["venue"]) for event in official_acceptance})
    }
    positive_total = sum(value for value in pnl if value > 0)
    concentration = max(
        (
            value / positive_total
            for value in pnl
            if value > 0 and positive_total > 0
        ),
        default=0.0,
    )
    result: dict[str, Any] = {
        "status": "INSUFFICIENT_DATA_NOT_REJECTED",
        "acceptance_eligible": False,
        "complete_events": len(events),
        "official_events": len(official),
        "official_acceptance_events": len(official_acceptance),
        "official_events_by_venue": official_events_by_venue,
        "venue_specific_ready": {
            venue: official_events_by_venue.get(venue, 0) >= 5 for venue in VENUES
        },
        "fill_rate": fill_rate,
        "stress_fill_rate": stress_fill_rate,
        "net_expectancy_quote": sum(pnl) / len(pnl) if pnl else 0.0,
        "profit_factor": _profit_factor(pnl),
        "maximum_drawdown_quote": _max_drawdown(pnl),
        "maximum_positive_event_share": concentration,
        "identity_conflicts": sum(1 for event in events if event["identity_conflict"]),
        "reasons": [],
    }
    if len(events) < 30:
        result["reasons"].append("minimum_complete_events_not_met")
        return result
    if result["identity_conflicts"]:
        result["reasons"].append("event_identity_conflict")
    if len(official_acceptance) < 30:
        result["reasons"].append("minimum_official_events_not_met")
    if any(event["liquidation_model_missing"] for event in official):
        result["reasons"].append("liquidation_model_missing")
    if fill_rate < 0.80:
        result["reasons"].append("normal_fill_rate_below_80pct")
    if stress_fill_rate < 0.70:
        result["reasons"].append("stress_fill_rate_below_70pct")
    if result["net_expectancy_quote"] <= 0:
        result["reasons"].append("net_expectancy_not_positive")
    if result["profit_factor"] < 1.2:
        result["reasons"].append("profit_factor_below_1_2")
    if result["maximum_drawdown_quote"] > 2.5:
        result["reasons"].append("drawdown_above_10pct_of_25_usdt_capital")
    if concentration > 0.25:
        result["reasons"].append("positive_pnl_concentration_above_25pct")
    if result["reasons"]:
        result["status"] = "RESEARCH_GATES_FAILED"
        return result
    result["status"] = "ACCEPTANCE_CANDIDATE"
    result["acceptance_eligible"] = True
    return result


def evaluate_evidence_gate(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        dict(event)
        for event in events
        if str(event.get("event_status", "complete")) == "complete"
    ]
    unidentified_rows = sum(1 for row in rows if not str(row.get("event_id") or "").strip())

    # Collapse only byte-equivalent revisions of the same exact cell identity.
    # Conflicting revisions are preserved as one fail-closed row and can never
    # improve the sample by multiplying it.
    exact_cells: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        venue = str(row.get("venue") or "").strip().lower()
        cohort = str(row.get("entry_cohort") or "").strip()
        exit_policy = str(row.get("exit_policy") or "t0").strip()
        exact_cells.setdefault((event_id, venue, cohort, exit_policy), []).append(row)

    deduped: list[dict[str, Any]] = []
    for (_event_id, _venue, _cohort, _exit), revisions in exact_cells.items():
        canonical = {
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in revisions
        }
        row = dict(revisions[0])
        row["cell_revision_conflict"] = len(canonical) > 1
        deduped.append(row)

    cells: dict[str, list[dict[str, Any]]] = {}
    for row in deduped:
        cohort = str(row.get("entry_cohort") or "").strip()
        exit_policy = str(row.get("exit_policy") or "t0").strip()
        cells.setdefault(f"{cohort}|{exit_policy}", []).append(row)
    analysis_cells = {key: _cell_summary(value) for key, value in sorted(cells.items())}

    primary_key = f"{PRIMARY_ENTRY_COHORT}|{PRIMARY_EXIT_POLICY}"
    primary = dict(analysis_cells.get(primary_key) or _cell_summary([]))
    all_event_ids = {
        str(row.get("event_id") or "").strip()
        for row in deduped
        if str(row.get("event_id") or "").strip()
    }
    primary.update(
        {
            "complete_rows": len(rows),
            "complete_events": len(all_event_ids),
            "primary_complete_events": int(
                (analysis_cells.get(primary_key) or {}).get("complete_events", 0)
            ),
            "unidentified_complete_rows": unidentified_rows,
            "primary_analysis_cell": {
                "entry_cohort": PRIMARY_ENTRY_COHORT,
                "exit_policy": PRIMARY_EXIT_POLICY,
            },
            "analysis_cells": analysis_cells,
            "official_venues": sorted(
                (analysis_cells.get(primary_key) or {}).get("official_events_by_venue", {})
            ),
        }
    )
    if unidentified_rows and "event_identity_missing" not in primary["reasons"]:
        primary["reasons"].append("event_identity_missing")
        primary["status"] = (
            "INSUFFICIENT_DATA_NOT_REJECTED"
            if primary["primary_complete_events"] < 30
            else "RESEARCH_GATES_FAILED"
        )
        primary["acceptance_eligible"] = False
    return primary


def official_preflight_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "research_only": True,
        "public_data_only": True,
        "private_api": False,
        "live_orders": False,
        "venues": list(VENUES),
        "entry_cohorts": list(ENTRY_COHORTS),
        "exit_offsets_sec": list(EXIT_OFFSETS_SEC),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Pre-market perpetual research-only utilities")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = official_preflight_contract() if args.preflight else {"ok": True, "usage": "--preflight"}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
