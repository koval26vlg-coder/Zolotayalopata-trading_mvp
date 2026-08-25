"""Public OKX/Gate/BitMEX/Kraken adapters for the pre-IPO perpetual track.

The adapters are deliberately split into two layers:

* pure normalizers consume captured public payloads and are fixture-friendly;
* the small REST/WS clients fetch only unauthenticated public data.

No authenticated endpoint, order path, leverage or margin execution exists in
this module.  Official announcement parsing is delegated to the separate
``preipo_perp_event`` contract so an expected date cannot become an official
IPO timestamp by accident.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

import requests

from preipo_perp_event import (
    PreIPOEvent,
    PreIPOEventError,
    is_official_source_url,
    parse_announcement,
)


ADAPTER_SCHEMA = "trading_mvp_preipo_public_adapter_v1"
VENUES = ("okx", "gate", "bitmex", "kraken")
OFFICIAL_FIRST_TRADE_SOURCE_FAMILIES = {
    "bitmex": "bitmex_official_equity_first_trade_notice",
    "gate": "gate_preipo_perpetual_official_first_trade_notice",
    "kraken": "kraken_official_equity_first_trade_notice",
    "okx": "okx_official_equity_first_trade_notice",
}


def _timestamp(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        if abs(parsed) >= 10_000_000_000:
            parsed /= 1000.0
        return parsed if parsed > 0 and math.isfinite(parsed) else None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        parsed = float(text)
        if abs(parsed) >= 10_000_000_000:
            parsed /= 1000.0
        return parsed if parsed > 0 and math.isfinite(parsed) else None
    try:
        parsed_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
    return parsed_dt.astimezone(timezone.utc).timestamp()


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalise_status(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        .replace(".", "_")
    )


def _top_level(levels: Any) -> tuple[float | None, float | None]:
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes, bytearray)) or not levels:
        return None, None
    first = levels[0]
    if isinstance(first, Mapping):
        price = _float(first.get("p", first.get("price")))
        quantity = _float(first.get("s", first.get("qty", first.get("size"))))
        return price, quantity
    if isinstance(first, Sequence) and not isinstance(first, (str, bytes, bytearray)):
        price = _float(first[0] if len(first) > 0 else None)
        quantity = _float(first[1] if len(first) > 1 else None)
        return price, quantity
    return None, None


def _payload_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    result = payload.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, Mapping)]
    if isinstance(result, Mapping):
        return [result]
    return [payload]


def _channel(payload: Mapping[str, Any]) -> str:
    arg = payload.get("arg")
    if isinstance(arg, Mapping):
        return _normalise_status(arg.get("channel"))
    return _normalise_status(
        payload.get("channel") or payload.get("table") or payload.get("feed")
    )


def _event_base(
    venue: str,
    contract_id: str,
    *,
    event_kind: str,
    exchange_ts: float | None,
    received_ts: float,
    channel: str,
) -> dict[str, Any]:
    return {
        "schema": ADAPTER_SCHEMA,
        "venue": venue,
        "contract_id": str(contract_id).strip().upper(),
        "event_kind": event_kind,
        "exchange_ts": exchange_ts or float(received_ts),
        "received_ts": float(received_ts),
        "channel": channel,
    }


def _matches_contract(row: Mapping[str, Any], contract_id: str) -> bool:
    observed = (
        row.get("symbol")
        or row.get("instId")
        or row.get("contract")
        or row.get("product_id")
        or row.get("productId")
    )
    return observed in (None, "") or str(observed).strip().upper() == str(
        contract_id
    ).strip().upper()


def _normalise_bitmex_snapshot(
    contract_id: str,
    payload: Mapping[str, Any],
    *,
    received_ts: float,
) -> list[dict[str, Any]]:
    table = _normalise_status(payload.get("table"))
    rows = _payload_rows(payload)
    if table in {"orderbookl2", "orderbookl2_25"}:
        bids: list[tuple[float, float]] = []
        asks: list[tuple[float, float]] = []
        timestamps: list[float] = []
        for row in rows:
            if not _matches_contract(row, contract_id):
                continue
            price = _float(row.get("price"))
            size = _float(row.get("size"))
            side = _normalise_status(row.get("side"))
            if price is not None and size is not None and size >= 0:
                if side in {"buy", "bid"}:
                    bids.append((price, size))
                elif side in {"sell", "ask"}:
                    asks.append((price, size))
            timestamp = _timestamp(row.get("timestamp") or row.get("transactTime"))
            if timestamp is not None:
                timestamps.append(timestamp)
        event = _event_base(
            "bitmex",
            contract_id,
            event_kind="bbo" if bids and asks else "depth",
            exchange_ts=max(timestamps) if timestamps else None,
            received_ts=received_ts,
            channel=table,
        )
        if bids:
            event["bid"], event["bid_qty"] = max(bids, key=lambda level: level[0])
        if asks:
            event["ask"], event["ask_qty"] = min(asks, key=lambda level: level[0])
        return [event]

    if table == "trade":
        events: list[dict[str, Any]] = []
        for row in rows:
            if not _matches_contract(row, contract_id):
                continue
            price = _float(row.get("price"))
            quantity = _float(row.get("size") or row.get("qty"))
            if price is None or quantity is None:
                continue
            event = _event_base(
                "bitmex",
                contract_id,
                event_kind="trade",
                exchange_ts=_timestamp(row.get("timestamp") or row.get("transactTime")),
                received_ts=received_ts,
                channel=table,
            )
            event.update(
                {
                    "last": price,
                    "qty": quantity,
                    "side": str(row.get("side") or "").strip().lower(),
                }
            )
            trade_id = row.get("trdMatchID") or row.get("id")
            if trade_id not in (None, ""):
                event["trade_id"] = trade_id
            sequence = row.get("seq") or row.get("sequence")
            if sequence not in (None, ""):
                event["sequence"] = sequence
            events.append(event)
        return events

    if table == "instrument":
        events: list[dict[str, Any]] = []
        for row in rows:
            if not _matches_contract(row, contract_id):
                continue
            event = _event_base(
                "bitmex",
                contract_id,
                event_kind="ticker",
                exchange_ts=_timestamp(row.get("timestamp")),
                received_ts=received_ts,
                channel=table,
            )
            for source_key, target_key in (
                ("bidPrice", "bid"),
                ("askPrice", "ask"),
                ("lastPrice", "last"),
                ("markPrice", "mark_price"),
                ("indicativeSettlePrice", "index_price"),
                ("fundingRate", "funding_rate"),
                ("openInterest", "open_interest"),
            ):
                value = _float(row.get(source_key))
                if value is not None:
                    event[target_key] = value
            events.append(event)
        return events
    return []


def _normalise_kraken_snapshot(
    contract_id: str,
    payload: Mapping[str, Any],
    *,
    received_ts: float,
) -> list[dict[str, Any]]:
    feed = _normalise_status(payload.get("feed") or payload.get("channel"))
    data = payload.get("data")
    body: Mapping[str, Any] = data if isinstance(data, Mapping) else payload

    trades = payload.get("trades")
    if not isinstance(trades, list):
        trades = body.get("trades") if isinstance(body.get("trades"), list) else None
    if trades is not None or "trade" in feed:
        trade_rows = trades if trades is not None else [body]
        events: list[dict[str, Any]] = []
        for row in trade_rows:
            if not isinstance(row, Mapping):
                continue
            if not _matches_contract(row, contract_id):
                continue
            price = _float(row.get("price"))
            quantity = _float(row.get("qty") or row.get("size"))
            if price is None or quantity is None:
                continue
            event = _event_base(
                "kraken",
                contract_id,
                event_kind="trade",
                exchange_ts=_timestamp(row.get("time") or row.get("timestamp")),
                received_ts=received_ts,
                channel=feed,
            )
            event.update(
                {
                    "last": price,
                    "qty": quantity,
                    "side": str(row.get("side") or "").strip().lower(),
                }
            )
            trade_id = row.get("uid") or row.get("trade_id")
            if trade_id not in (None, ""):
                event["trade_id"] = trade_id
            sequence = row.get("seq") or row.get("sequence")
            if sequence not in (None, ""):
                try:
                    event["sequence"] = int(sequence)
                except (TypeError, ValueError):
                    event["sequence"] = str(sequence)
            events.append(event)
        return events

    order_book = body.get("orderBook") or body.get("order_book")
    if isinstance(order_book, Mapping):
        book = order_book
    else:
        book = body
    bids = book.get("bids") or book.get("b")
    asks = book.get("asks") or book.get("a")
    bid, bid_qty = _top_level(bids)
    ask, ask_qty = _top_level(asks)
    if bid is not None or ask is not None or "book" in feed:
        event = _event_base(
            "kraken",
            contract_id,
            event_kind="bbo" if bid is not None and ask is not None else "depth",
            exchange_ts=_timestamp(
                body.get("serverTime")
                or body.get("timestamp")
                or payload.get("timestamp")
                or payload.get("time")
            ),
            received_ts=received_ts,
            channel=feed,
        )
        if bid is not None:
            event["bid"], event["bid_qty"] = bid, bid_qty or 0.0
        if ask is not None:
            event["ask"], event["ask_qty"] = ask, ask_qty or 0.0
        sequence = body.get("seq") or body.get("sequence") or payload.get("seq")
        if sequence not in (None, ""):
            event["sequence"] = sequence
        return [event]

    ticker_rows = body.get("tickers") if isinstance(body.get("tickers"), list) else [body]
    events = []
    for row in ticker_rows:
        if not isinstance(row, Mapping):
            continue
        if not _matches_contract(row, contract_id):
            continue
        event = _event_base(
            "kraken",
            contract_id,
            event_kind="ticker",
            exchange_ts=_timestamp(row.get("lastTime") or row.get("timestamp")),
            received_ts=received_ts,
            channel=feed,
        )
        for source_keys, target in (
            (("bid", "bidPrice"), "bid"),
            (("ask", "askPrice"), "ask"),
            (("last", "lastPrice"), "last"),
            (("markPrice", "mark_price"), "mark_price"),
            (("indexPrice", "index_price"), "index_price"),
            (("fundingRate", "funding_rate"), "funding_rate"),
            (("openInterest", "open_interest"), "open_interest"),
        ):
            value = next((_float(row.get(key)) for key in source_keys if row.get(key) not in (None, "")), None)
            if value is not None:
                event[target] = value
        events.append(event)
    return events


@dataclass(frozen=True)
class PreIPOContract:
    venue: str
    contract_id: str
    underlying_symbol: str
    quote: str
    lifecycle_status: str
    phase: str
    source_class: str = "official"
    asset_class: str = "preipo_equity"
    tradable_ts: float | None = None
    rebase_ts: float | None = None
    official_conversion_ts: float | None = None
    official_first_trade_ts: float | None = None
    official_first_trade_announcement_ts: float | None = None
    official_first_trade_source_class: str = ""
    official_first_trade_source_url: str = ""
    official_first_trade_source_family: str = ""
    maintenance_margin_rate: float | None = None
    taker_fee_bps: float | None = None
    maker_fee_bps: float | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        venue = str(self.venue).strip().lower()
        if venue == "gateio":
            venue = "gate"
        if venue not in VENUES:
            raise ValueError(f"unsupported pre-IPO venue: {self.venue}")
        object.__setattr__(self, "venue", venue)
        if self.asset_class != "preipo_equity":
            raise ValueError("pre-IPO adapter cannot emit crypto contracts")
        if not self.contract_id.strip() or not self.underlying_symbol.strip() or not self.quote.strip():
            raise ValueError("contract identity is incomplete")
        proof_present = any(
            value not in (None, "")
            for value in (
                self.official_first_trade_ts,
                self.official_first_trade_announcement_ts,
                self.official_first_trade_source_class,
                self.official_first_trade_source_url,
                self.official_first_trade_source_family,
            )
        )
        if proof_present:
            if (
                self.official_first_trade_ts is None
                or not math.isfinite(float(self.official_first_trade_ts))
                or float(self.official_first_trade_ts) <= 0
                or self.official_first_trade_announcement_ts is None
                or not math.isfinite(
                    float(self.official_first_trade_announcement_ts)
                )
                or float(self.official_first_trade_announcement_ts) <= 0
                or self.official_first_trade_source_class != "official"
                or self.official_first_trade_source_family.strip()
                != OFFICIAL_FIRST_TRADE_SOURCE_FAMILIES[venue]
                or not is_official_source_url(
                    venue,
                    self.official_first_trade_source_url,
                )
            ):
                raise ValueError(
                    "official first trade requires complete venue-official provenance"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = ADAPTER_SCHEMA
        return payload


def normalize_okx_contract(item: Mapping[str, Any], *, source_class: str = "official") -> PreIPOContract | None:
    """Normalize an OKX SWAP instrument only when it carries a pre-IPO marker."""

    inst_id = str(item.get("instId") or item.get("inst_id") or "").strip().upper()
    rule_type = _normalise_status(item.get("ruleType") or item.get("rule_type"))
    is_preipo = (
        rule_type in {"pre_market", "premarket", "pre_ipo", "preipo"}
        or bool(item.get("isPreMarket"))
        or bool(item.get("isPreIPO"))
        or _normalise_status(item.get("category")) in {"pre_ipo", "preipo"}
    )
    if not inst_id or not is_preipo:
        return None
    base = str(item.get("baseCcy") or item.get("base_ccy") or "").strip().upper()
    if not base:
        underlying = str(item.get("uly") or "").strip().upper()
        base = underlying.split("-")[0] if underlying else ""
    quote = str(item.get("quoteCcy") or item.get("quote_ccy") or "USDT").strip().upper()
    state = _normalise_status(item.get("state"))
    lifecycle = "preipo_continuous" if state in {"live", "online", "open"} else "scheduled"
    return PreIPOContract(
        venue="okx",
        contract_id=inst_id,
        underlying_symbol=base,
        quote=quote,
        lifecycle_status=lifecycle,
        phase="preipo_continuous" if lifecycle == "preipo_continuous" else "scheduled",
        source_class=source_class,
        tradable_ts=_timestamp(item.get("listTime") or item.get("list_time")),
        rebase_ts=_timestamp(item.get("rebaseTime") or item.get("rebase_time")),
        official_conversion_ts=_timestamp(item.get("preMktSwTime") or item.get("pre_market_switch_time")),
        maintenance_margin_rate=_float(item.get("mmr") or item.get("maintenanceMarginRate")),
        taker_fee_bps=(_float(item.get("takerFeeRate")) or 0.0) * 10_000.0,
        maker_fee_bps=(_float(item.get("makerFeeRate")) or 0.0) * 10_000.0,
    )


def normalize_bitmex_contract(item: Mapping[str, Any], *, source_class: str = "official") -> PreIPOContract | None:
    """Normalize a BitMEX instrument, refusing to guess that it is pre-IPO.

    BitMEX publishes no pre-IPO marker at all - unlike OKX ruleType or Gate's fields,
    there is nothing on the instrument that says "this tracks a private company". So the
    only honest test is the declared equity list: an instrument enters here when its
    underlying is one we have declared, and otherwise it is refused. Guessing from the
    ticker would be the same defect that had the crypto track collecting ANTHROPIC.

    The `listing` field is BitMEX's own timestamp for when the *instrument* was listed on
    BitMEX. That is a contract launch, not the underlying's IPO and not an observed first
    trade, so it maps to tradable_ts. Nothing here can satisfy the acceptance gate's
    exact_first_trade_t0 requirement, and it must not be presented as if it could.
    """
    from premarket_asset_class import (
        ASSET_CLASS_EQUITY_PREIPO,
        classify_contract,
        underlying_of,
    )

    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    # FFWCSX is BitMEX's perpetual contract type; anything else is a future or an index.
    typ = _normalise_status(item.get("typ"))
    if typ and typ not in {"ffwcsx", "ffwcsf"}:
        return None
    if classify_contract(symbol) != ASSET_CLASS_EQUITY_PREIPO:
        return None

    state = _normalise_status(item.get("state"))
    if state in {"unlisted", "settled", "closed"}:
        lifecycle = "delisted" if state != "settled" else "expired"
    elif state == "open":
        lifecycle = "preipo_continuous"
    else:
        lifecycle = "scheduled"

    quote = str(item.get("quoteCurrency") or item.get("quote_currency") or "USDT").strip().upper()
    # The canonical underlying, not the venue's spelling: BitMEX writes SPCX where other
    # venues write SPACEX, and storing the raw field would split one company into two
    # underlyings the moment a second venue is added - which is the whole point of adding
    # venues in the first place.
    underlying = underlying_of(symbol) or str(
        item.get("underlying") or item.get("rootSymbol") or ""
    ).strip().upper()
    return PreIPOContract(
        venue="bitmex",
        contract_id=symbol,
        underlying_symbol=underlying,
        quote=quote,
        lifecycle_status=lifecycle,
        phase="preipo_continuous" if lifecycle == "preipo_continuous" else "scheduled",
        source_class=source_class,
        # Contract launch, deliberately not official_conversion_ts: BitMEX publishes no
        # conversion time, and inventing one would be the collapsed-taxonomy defect again.
        tradable_ts=_timestamp(item.get("listing")),
        official_conversion_ts=None,
        maintenance_margin_rate=_float(item.get("maintMargin")),
        taker_fee_bps=(_float(item.get("takerFee")) or 0.0) * 10_000.0,
        maker_fee_bps=(_float(item.get("makerFee")) or 0.0) * 10_000.0,
    )


def normalize_kraken_contract(item: Mapping[str, Any], *, source_class: str = "official") -> PreIPOContract | None:
    """Normalize a Kraken Futures instrument, refusing to guess that it is pre-IPO.

    Like BitMEX, Kraken publishes no pre-IPO marker, so membership comes from the
    declared equity list and everything else is refused.

    Two Kraken specifics are worth stating because both are easy to get wrong:

      * `type` is "flexible_futures" for a perpetual. The dated and inverse types are
        different instruments and are not collected here.
      * `tradeable` is documented as "True if this instrument is, or has ever been, a
        tradable instrument". It is a history flag, not a liveness flag, so using it to
        decide whether a contract is live would keep delisted instruments in the sample
        forever. `isExpired` is the terminal signal.

    `openingDate` is documented as when the instrument became available for trading -
    a contract launch, like BitMEX's `listing`. It is not the underlying's IPO and not
    an observed first trade, so it maps to tradable_ts and cannot satisfy the acceptance
    gate's exact_first_trade_t0 requirement.
    """
    from premarket_asset_class import (
        ASSET_CLASS_EQUITY_PREIPO,
        classify_underlying,
        underlying_of,
    )

    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    if _normalise_status(item.get("type")) != "flexible_futures":
        return None
    base = str(item.get("base") or item.get("underlying") or "").strip().upper()
    canonical = underlying_of(base) if base else underlying_of(symbol)
    if classify_underlying(canonical) != ASSET_CLASS_EQUITY_PREIPO:
        return None

    lifecycle = "expired" if bool(item.get("isExpired")) else "preipo_continuous"
    quote = str(item.get("quote") or "USD").strip().upper()
    margins = item.get("marginLevels") or item.get("retailMarginLevels") or []
    maintenance = None
    if isinstance(margins, list) and margins:
        first = margins[0]
        if isinstance(first, Mapping):
            maintenance = _float(first.get("maintenanceMargin"))
    return PreIPOContract(
        venue="kraken",
        contract_id=symbol,
        underlying_symbol=canonical,
        quote=quote,
        lifecycle_status=lifecycle,
        phase="preipo_continuous" if lifecycle == "preipo_continuous" else "scheduled",
        source_class=source_class,
        tradable_ts=_timestamp(item.get("openingDate")),
        official_conversion_ts=None,
        maintenance_margin_rate=maintenance,
    )


def normalize_gate_contract(item: Mapping[str, Any], *, source_class: str = "official") -> PreIPOContract | None:
    """Normalize a Gate USDT contract only with an explicit equity pre-IPO marker."""

    name = str(item.get("name") or item.get("contract") or "").strip().upper()
    marker = bool(item.get("preipo") or item.get("pre_ipo") or item.get("is_preipo") or item.get("isPreIPO"))
    marker = marker or _normalise_status(item.get("instrument_type")) in {"preipo", "pre_ipo", "equity_preipo"}
    marker = marker or _normalise_status(item.get("underlying_type")) in {"equity", "stock"}
    if not name or not marker:
        return None
    base = str(item.get("base") or name.split("_")[0]).strip().upper()
    quote = str(item.get("quote") or name.split("_")[-1] or "USDT").strip().upper()
    status = _normalise_status(item.get("status"))
    lifecycle = "preipo_continuous" if status in {"live", "online", "open"} else "scheduled"
    return PreIPOContract(
        venue="gate",
        contract_id=name,
        underlying_symbol=base,
        quote=quote,
        lifecycle_status=lifecycle,
        phase="preipo_continuous" if lifecycle == "preipo_continuous" else "scheduled",
        source_class=source_class,
        tradable_ts=_timestamp(item.get("launch_time") or item.get("launchTime")),
        rebase_ts=_timestamp(item.get("rebase_time") or item.get("rebaseTime")),
        official_conversion_ts=_timestamp(item.get("conversion_time") or item.get("transition_time")),
        maintenance_margin_rate=_float(item.get("maintenance_rate") or item.get("maintenanceMarginRate")),
        taker_fee_bps=(_float(item.get("taker_fee_rate") or item.get("takerFeeRate")) or 0.0) * 10_000.0,
        maker_fee_bps=(_float(item.get("maker_fee_rate") or item.get("makerFeeRate")) or 0.0) * 10_000.0,
    )


def normalize_market_snapshot(
    venue: str,
    contract_id: str,
    payload: Mapping[str, Any],
    *,
    received_ts: float,
) -> list[dict[str, Any]]:
    """Normalize one captured REST/WS payload while preserving both clocks."""

    venue = str(venue).strip().lower()
    if venue == "gateio":
        venue = "gate"
    if venue not in VENUES:
        raise ValueError(f"unsupported pre-IPO venue: {venue}")
    if not math.isfinite(float(received_ts)) or float(received_ts) <= 0:
        raise ValueError("received_ts must be positive and finite")
    if venue == "bitmex":
        return _normalise_bitmex_snapshot(
            contract_id,
            payload,
            received_ts=float(received_ts),
        )
    if venue == "kraken":
        return _normalise_kraken_snapshot(
            contract_id,
            payload,
            received_ts=float(received_ts),
        )
    channel = _channel(payload)
    rows = _payload_rows(payload)
    events: list[dict[str, Any]] = []
    for row in rows:
        exchange_ts = _timestamp(
            row.get("ts")
            or row.get("timestamp")
            or row.get("time")
            or row.get("uTime")
            or row.get("current")
            or payload.get("ts")
        )
        if exchange_ts is None:
            exchange_ts = float(received_ts)
        event: dict[str, Any] = {
            "schema": ADAPTER_SCHEMA,
            "venue": venue,
            "contract_id": str(contract_id).strip().upper(),
            "event_kind": "ticker",
            "exchange_ts": exchange_ts,
            "received_ts": float(received_ts),
            "channel": channel,
        }
        bids = row.get("bids") or row.get("b")
        asks = row.get("asks") or row.get("a")
        bid, bid_qty = _top_level(bids)
        ask, ask_qty = _top_level(asks)
        if bid is not None:
            event["bid"] = bid
            event["bid_qty"] = bid_qty or 0.0
        if ask is not None:
            event["ask"] = ask
            event["ask_qty"] = ask_qty or 0.0
        if bid is None:
            bid = _float(row.get("highest_bid") or row.get("best_bid"))
            if bid is not None:
                event["bid"] = bid
                event["bid_qty"] = _float(row.get("highest_bid_size") or row.get("bid_size")) or 0.0
        if ask is None:
            ask = _float(row.get("lowest_ask") or row.get("best_ask"))
            if ask is not None:
                event["ask"] = ask
                event["ask_qty"] = _float(row.get("lowest_ask_size") or row.get("ask_size")) or 0.0
        is_book = channel in {
            "books",
            "book",
            "order_book",
            "orderbook",
            "futures_order_book",
            "futures_order_book_update",
        }
        if bid is not None and ask is not None:
            event["event_kind"] = "bbo" if is_book else "ticker"
        elif is_book:
            event["event_kind"] = "depth"

        last = _float(row.get("last") or row.get("lastPx") or row.get("price") or row.get("p"))
        mark = _float(row.get("mark_price") or row.get("markPx") or row.get("markPrice"))
        index = _float(row.get("index_price") or row.get("idxPx") or row.get("indexPrice"))
        funding = _float(row.get("funding_rate") or row.get("fundingRate"))
        open_interest = _float(row.get("open_interest") or row.get("oi") or row.get("openInterest"))
        if last is not None:
            event["last"] = last
        if mark is not None:
            event["mark_price"] = mark
            event["event_kind"] = "mark" if channel in {"mark_price", "mark", "mark_price_channel"} else event["event_kind"]
        if index is not None:
            event["index_price"] = index
        if funding is not None:
            event["funding_rate"] = funding
            event["event_kind"] = "funding" if "funding" in channel else event["event_kind"]
        if open_interest is not None:
            event["open_interest"] = open_interest
            event["event_kind"] = "open_interest" if "interest" in channel else event["event_kind"]
        sequence = (
            row.get("seqId")
            or row.get("seq")
            or row.get("u")
            or row.get("update_id")
            or row.get("id")
        )
        if sequence not in (None, ""):
            try:
                event["sequence"] = int(sequence)
            except (TypeError, ValueError):
                event["sequence"] = str(sequence)
        side = row.get("side") or row.get("S")
        qty = _float(row.get("qty") or row.get("sz") or row.get("size") or row.get("amount"))
        if last is not None and qty is not None and (
            "trade" in channel or channel in {"trades", "public_trade"}
        ):
            event["event_kind"] = "trade"
            event["side"] = str(side or "").lower()
            event["qty"] = qty
        events.append(event)
    return events


def parse_official_announcement(payload: Mapping[str, Any]) -> PreIPOEvent:
    """Parse a captured active-venue official announcement; never fetches it."""

    event = parse_announcement(payload, require_official_source=True)
    if event.venue not in VENUES:
        raise PreIPOEventError(f"unsupported active pre-IPO venue: {event.venue}")
    return event


def bind_official_first_trade(
    contract: PreIPOContract,
    payload: Mapping[str, Any],
    *,
    source_family: str,
) -> PreIPOContract:
    """Attach a validated official equity first-trade event to one contract.

    The binding is identity-strict.  A notice about another contract or underlying can
    never lend its timestamp to this row, and a generic venue metadata timestamp never
    enters this function.
    """

    required_fields = (
        "venue",
        "contract_id",
        "underlying_symbol",
        "quote",
        "source_url",
        "announcement_ts",
        "official_first_trade_ts",
    )
    missing = [field for field in required_fields if payload.get(field) in (None, "")]
    if missing:
        raise PreIPOEventError(
            "official first-trade binding is missing exact fields: "
            + ",".join(missing)
        )
    family = str(source_family or "").strip()
    event = parse_official_announcement(payload)
    if family != OFFICIAL_FIRST_TRADE_SOURCE_FAMILIES.get(event.venue):
        raise PreIPOEventError("unregistered official first-trade source family")
    if (
        event.venue != contract.venue
        or event.contract_id != contract.contract_id.strip().upper()
        or event.underlying_symbol != contract.underlying_symbol.strip().upper()
        or event.quote != contract.quote.strip().upper()
    ):
        raise PreIPOEventError("official first-trade announcement identity mismatch")
    if (
        not event.acceptance_eligible
        or event.official_first_trade_ts is None
        or event.announcement_ts is None
    ):
        raise PreIPOEventError("announcement lacks acceptance-grade official first trade")
    return replace(
        contract,
        official_first_trade_ts=event.official_first_trade_ts,
        official_first_trade_announcement_ts=event.announcement_ts,
        official_first_trade_source_class=event.source_class,
        official_first_trade_source_url=event.source_url,
        official_first_trade_source_family=family,
    )


class PublicPreIPOAdapter:
    venue = ""
    base_url = ""
    ws_url = ""
    allowed_https_hosts: tuple[str, ...] = ()

    def __init__(self, timeout_sec: float = 10.0, session: requests.Session | None = None) -> None:
        self.timeout_sec = float(timeout_sec)
        self.session = session or requests.Session()
        self.session.trust_env = False

    def _validate_public_url(self, url: str) -> str:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() != "https":
            raise ValueError(f"{self.venue} public REST URL must use HTTPS")
        if parsed.username or parsed.password:
            raise ValueError(f"{self.venue} public REST URL cannot contain credentials")
        if parsed.port not in (None, 443):
            raise ValueError(f"{self.venue} public REST URL uses an unapproved port")
        if not host or host not in self.allowed_https_hosts:
            raise ValueError(f"{self.venue} public REST URL host is not allow-listed: {host}")
        return url

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        self._validate_public_url(url)
        response = self.session.get(url, params=dict(params or {}), timeout=self.timeout_sec)
        self._validate_public_url(str(getattr(response, "url", None) or url))
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, Mapping):
            for code_key in ("code", "retCode"):
                code = str(payload.get(code_key, "0"))
                if code not in {"0", "", "200"}:
                    raise RuntimeError(f"{self.venue} {code_key}={code} message={payload.get('msg') or payload.get('retMsg')}")
        return payload

    def discover_contracts(self) -> list[PreIPOContract]:
        raise NotImplementedError

    def snapshot_payloads(self, contract: PreIPOContract) -> Iterable[Mapping[str, Any]]:
        raise NotImplementedError

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize_snapshot(self, contract: PreIPOContract, payload: Mapping[str, Any], *, received_ts: float) -> list[dict[str, Any]]:
        return normalize_market_snapshot(self.venue, contract.contract_id, payload, received_ts=received_ts)


class OkxPreIPOAdapter(PublicPreIPOAdapter):
    venue = "okx"
    base_url = "https://www.okx.com"
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"
    allowed_https_hosts = ("www.okx.com",)

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/api/v5/public/instruments", {"instType": "SWAP"})
        items = payload.get("data") if isinstance(payload, Mapping) else []
        return [contract for item in items or [] if (contract := normalize_okx_contract(item)) is not None]

    def snapshot_payloads(self, contract: PreIPOContract) -> Iterable[Mapping[str, Any]]:
        yield {"arg": {"channel": "books", "instId": contract.contract_id}, **self._get("/api/v5/market/books", {"instId": contract.contract_id, "sz": 50})}
        yield {"arg": {"channel": "tickers", "instId": contract.contract_id}, **self._get("/api/v5/market/ticker", {"instId": contract.contract_id})}
        yield {"arg": {"channel": "mark-price", "instId": contract.contract_id}, **self._get("/api/v5/public/mark-price", {"instType": "SWAP", "instId": contract.contract_id})}
        yield {"arg": {"channel": "funding-rate", "instId": contract.contract_id}, **self._get("/api/v5/public/funding-rate", {"instType": "SWAP", "instId": contract.contract_id})}
        yield {"arg": {"channel": "open-interest", "instId": contract.contract_id}, **self._get("/api/v5/public/open-interest", {"instType": "SWAP", "instId": contract.contract_id})}

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        return [
            {"op": "subscribe", "args": [{"channel": "books", "instId": contract.contract_id}]},
            {"op": "subscribe", "args": [{"channel": "trades", "instId": contract.contract_id}]},
            {"op": "subscribe", "args": [{"channel": "tickers", "instId": contract.contract_id}]},
            {"op": "subscribe", "args": [{"channel": "mark-price", "instId": contract.contract_id}]},
        ]


class GatePreIPOAdapter(PublicPreIPOAdapter):
    venue = "gate"
    base_url = "https://api.gateio.ws/api/v4"
    ws_url = "wss://fx-ws.gateio.ws/v4/ws/usdt"
    allowed_https_hosts = ("api.gateio.ws",)

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/futures/usdt/contracts")
        return [contract for item in payload or [] if (contract := normalize_gate_contract(item)) is not None]

    def snapshot_payloads(self, contract: PreIPOContract) -> Iterable[Mapping[str, Any]]:
        yield {"channel": "futures.order_book", "result": self._get("/futures/usdt/order_book", {"contract": contract.contract_id, "limit": 50})}
        yield {"channel": "futures.tickers", "result": self._get("/futures/usdt/tickers", {"contract": contract.contract_id})}
        yield {"channel": "futures.funding_rate", "result": self._get("/futures/usdt/funding_rate", {"contract": contract.contract_id})}
        yield {"channel": "futures.contract_stats", "result": self._get("/futures/usdt/contract_stats", {"contract": contract.contract_id, "interval": "5m", "limit": 1})}

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        now = int(time.time())
        return [
            {"time": now, "channel": "futures.order_book", "event": "subscribe", "payload": [contract.contract_id, "50", "100ms"]},
            {"time": now, "channel": "futures.trades", "event": "subscribe", "payload": [contract.contract_id]},
            {"time": now, "channel": "futures.tickers", "event": "subscribe", "payload": [contract.contract_id]},
        ]


# Registered after every adapter class below, so VENUES and ADAPTERS cannot drift: a
# venue named in VENUES but missing here would make build_public_adapters raise the
# moment anyone called it with the default argument. A test asserts the two agree.
ADAPTERS: dict[str, type[PublicPreIPOAdapter]] = {"okx": OkxPreIPOAdapter, "gate": GatePreIPOAdapter}

class BitmexPreIPOAdapter(PublicPreIPOAdapter):
    """BitMEX public market data. No key, no signing - /instrument/active is open.

    The immutable PlanOnly rebind remains a separate step: this adapter makes the
    declared active runtime surface complete, but does not itself authorize capture.
    """

    venue = "bitmex"
    base_url = "https://www.bitmex.com/api/v1"
    ws_url = "wss://ws.bitmex.com/realtime"
    allowed_https_hosts = ("www.bitmex.com",)

    def __init__(
        self,
        timeout_sec: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(timeout_sec=timeout_sec, session=session)
        self._l2_books: dict[str, dict[int, dict[str, Any]]] = {}

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/instrument/active")
        return [
            contract
            for item in payload or []
            if (contract := normalize_bitmex_contract(item)) is not None
        ]

    def snapshot_payloads(self, contract: PreIPOContract) -> Iterable[Mapping[str, Any]]:
        symbol = contract.contract_id
        yield {"table": "orderBookL2_25", "data": self._get("/orderBook/L2", {"symbol": symbol, "depth": 25})}
        yield {"table": "instrument", "data": self._get("/instrument", {"symbol": symbol})}
        yield {"table": "trade", "data": self._get("/trade", {"symbol": symbol, "count": 50, "reverse": "true"})}

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        symbol = contract.contract_id
        return [
            {"op": "subscribe", "args": [f"orderBookL2_25:{symbol}"]},
            {"op": "subscribe", "args": [f"trade:{symbol}"]},
            {"op": "subscribe", "args": [f"instrument:{symbol}"]},
        ]

    def normalize_snapshot(
        self,
        contract: PreIPOContract,
        payload: Mapping[str, Any],
        *,
        received_ts: float,
    ) -> list[dict[str, Any]]:
        table = _normalise_status(payload.get("table"))
        if table not in {"orderbookl2", "orderbookl2_25"}:
            return normalize_market_snapshot(
                self.venue,
                contract.contract_id,
                payload,
                received_ts=received_ts,
            )
        action = _normalise_status(payload.get("action"))
        book = self._l2_books.setdefault(contract.contract_id, {})
        if action in {"", "partial", "snapshot"}:
            book.clear()
        for row in _payload_rows(payload):
            if not _matches_contract(row, contract.contract_id):
                continue
            try:
                level_id = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if action == "delete":
                book.pop(level_id, None)
                continue
            previous = book.get(level_id, {})
            merged = {**previous, **dict(row)}
            size = _float(merged.get("size"))
            if size is not None and size <= 0:
                book.pop(level_id, None)
                continue
            if (
                _float(merged.get("price")) is None
                or _normalise_status(merged.get("side"))
                not in {"buy", "bid", "sell", "ask"}
            ):
                continue
            book[level_id] = merged
        normalized_payload = {
            "table": payload.get("table") or "orderBookL2_25",
            "data": list(book.values()),
        }
        return _normalise_bitmex_snapshot(
            contract.contract_id,
            normalized_payload,
            received_ts=received_ts,
        )



def build_public_adapters(
    venues: Iterable[str] = VENUES,
    *,
    timeout_sec: float = 10.0,
    session_factory: Any = requests.Session,
) -> dict[str, PublicPreIPOAdapter]:
    result: dict[str, PublicPreIPOAdapter] = {}
    for raw_venue in venues:
        venue = str(raw_venue).strip().lower()
        if venue == "gateio":
            venue = "gate"
        if venue not in ADAPTERS:
            raise ValueError(f"unsupported pre-IPO venue: {raw_venue}")
        result[venue] = ADAPTERS[venue](timeout_sec=timeout_sec, session=session_factory())
    return result


class KrakenPreIPOAdapter(PublicPreIPOAdapter):
    """Kraken Futures public market data. /instruments needs no key."""

    venue = "kraken"
    base_url = "https://futures.kraken.com/derivatives/api/v3"
    ws_url = "wss://futures.kraken.com/ws/v1"
    allowed_https_hosts = ("futures.kraken.com",)

    def __init__(
        self,
        timeout_sec: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(timeout_sec=timeout_sec, session=session)
        self._books: dict[str, dict[str, dict[float, float]]] = {}

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/instruments")
        rows = payload.get("instruments") if isinstance(payload, Mapping) else payload
        return [
            contract
            for item in rows or []
            if (contract := normalize_kraken_contract(item)) is not None
        ]

    def snapshot_payloads(self, contract: PreIPOContract) -> Iterable[Mapping[str, Any]]:
        symbol = contract.contract_id
        yield {"feed": "book_snapshot", "data": self._get("/orderbook", {"symbol": symbol})}
        yield {"feed": "ticker", "data": self._get("/tickers", {"symbol": symbol})}

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        symbol = contract.contract_id
        return [
            {"event": "subscribe", "feed": "book", "product_ids": [symbol]},
            {"event": "subscribe", "feed": "trade", "product_ids": [symbol]},
            {"event": "subscribe", "feed": "ticker", "product_ids": [symbol]},
        ]

    def normalize_snapshot(
        self,
        contract: PreIPOContract,
        payload: Mapping[str, Any],
        *,
        received_ts: float,
    ) -> list[dict[str, Any]]:
        feed = _normalise_status(payload.get("feed") or payload.get("channel"))
        if "book" not in feed:
            return normalize_market_snapshot(
                self.venue,
                contract.contract_id,
                payload,
                received_ts=received_ts,
            )
        if not _matches_contract(payload, contract.contract_id):
            return []
        data = payload.get("data")
        body: Mapping[str, Any] = data if isinstance(data, Mapping) else payload
        order_book = body.get("orderBook") or body.get("order_book")
        book_payload = order_book if isinstance(order_book, Mapping) else body
        state = self._books.setdefault(
            contract.contract_id,
            {"buy": {}, "sell": {}},
        )
        if "snapshot" in feed or isinstance(order_book, Mapping):
            state["buy"].clear()
            state["sell"].clear()

        def apply_levels(side: str, levels: Any) -> None:
            if not isinstance(levels, Sequence) or isinstance(
                levels, (str, bytes, bytearray)
            ):
                return
            for level in levels:
                if isinstance(level, Mapping):
                    price = _float(level.get("price") or level.get("p"))
                    quantity = _float(
                        level.get("qty") or level.get("size") or level.get("s")
                    )
                elif isinstance(level, Sequence) and not isinstance(
                    level, (str, bytes, bytearray)
                ):
                    price = _float(level[0] if len(level) > 0 else None)
                    quantity = _float(level[1] if len(level) > 1 else None)
                else:
                    continue
                if price is None or quantity is None:
                    continue
                if quantity <= 0:
                    state[side].pop(price, None)
                else:
                    state[side][price] = quantity

        apply_levels("buy", book_payload.get("bids") or book_payload.get("b"))
        apply_levels("sell", book_payload.get("asks") or book_payload.get("a"))
        delta_side = _normalise_status(body.get("side") or payload.get("side"))
        if delta_side in {"buy", "bid", "sell", "ask"}:
            side = "buy" if delta_side in {"buy", "bid"} else "sell"
            price = _float(body.get("price") or payload.get("price"))
            quantity = _float(
                body.get("qty")
                or body.get("size")
                or payload.get("qty")
                or payload.get("size")
            )
            if price is not None and quantity is not None:
                if quantity <= 0:
                    state[side].pop(price, None)
                else:
                    state[side][price] = quantity

        bids = state["buy"]
        asks = state["sell"]
        event = _event_base(
            "kraken",
            contract.contract_id,
            event_kind="bbo" if bids and asks else "depth",
            exchange_ts=_timestamp(
                body.get("serverTime")
                or body.get("timestamp")
                or body.get("time")
                or payload.get("timestamp")
                or payload.get("time")
            ),
            received_ts=received_ts,
            channel=feed,
        )
        if bids:
            bid = max(bids)
            event["bid"], event["bid_qty"] = bid, bids[bid]
        if asks:
            ask = min(asks)
            event["ask"], event["ask_qty"] = ask, asks[ask]
        sequence = body.get("seq") or body.get("sequence") or payload.get("seq")
        if sequence not in (None, ""):
            try:
                event["sequence"] = int(sequence)
            except (TypeError, ValueError):
                event["sequence"] = str(sequence)
        return [event]


ADAPTERS["bitmex"] = BitmexPreIPOAdapter
ADAPTERS["kraken"] = KrakenPreIPOAdapter
assert set(ADAPTERS) == set(VENUES), "every declared venue needs an adapter"
