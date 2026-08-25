"""Public OKX/Gate adapters for the isolated pre-IPO perpetual track.

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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import requests

from preipo_perp_event import PreIPOEvent, PreIPOEventError, parse_announcement


ADAPTER_SCHEMA = "trading_mvp_preipo_public_adapter_v1"
VENUES = ("okx", "gate", "bitmex", "kraken")


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
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


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
    return _normalise_status(payload.get("channel"))


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
    channel = _channel(payload)
    rows = _payload_rows(payload)
    events: list[dict[str, Any]] = []
    for row in rows:
        exchange_ts = _timestamp(row.get("ts") or row.get("timestamp") or row.get("time") or row.get("uTime") or payload.get("ts"))
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
        if bid is not None and ask is not None:
            event["event_kind"] = "bbo" if channel in {"books", "book", "order_book", "orderbook"} else "ticker"
        elif channel in {"books", "book", "order_book", "orderbook"}:
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
        sequence = row.get("seqId") or row.get("seq") or row.get("u") or row.get("update_id")
        if sequence not in (None, ""):
            try:
                event["sequence"] = int(sequence)
            except (TypeError, ValueError):
                event["sequence"] = str(sequence)
        side = row.get("side") or row.get("S")
        qty = _float(row.get("qty") or row.get("sz") or row.get("size") or row.get("amount"))
        if last is not None and qty is not None and ("trade" in channel or channel in {"trades", "public_trade"}):
            event["event_kind"] = "trade"
            event["side"] = str(side or "").lower()
            event["qty"] = qty
        events.append(event)
    return events


def parse_official_announcement(payload: Mapping[str, Any]) -> PreIPOEvent:
    """Parse a captured OKX/Gate official announcement; never fetches it."""

    event = parse_announcement(payload, require_official_source=True)
    if event.venue not in VENUES:
        raise PreIPOEventError(f"unsupported active pre-IPO venue: {event.venue}")
    return event


class PublicPreIPOAdapter:
    venue = ""
    base_url = ""
    ws_url = ""

    def __init__(self, timeout_sec: float = 10.0, session: requests.Session | None = None) -> None:
        self.timeout_sec = float(timeout_sec)
        self.session = session or requests.Session()
        self.session.trust_env = False

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self.session.get(url, params=dict(params or {}), timeout=self.timeout_sec)
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

    def snapshot_payloads(self, contract: PreIPOContract) -> list[Mapping[str, Any]]:
        raise NotImplementedError

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize_snapshot(self, contract: PreIPOContract, payload: Mapping[str, Any], *, received_ts: float) -> list[dict[str, Any]]:
        return normalize_market_snapshot(self.venue, contract.contract_id, payload, received_ts=received_ts)


class OkxPreIPOAdapter(PublicPreIPOAdapter):
    venue = "okx"
    base_url = "https://www.okx.com"
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/api/v5/public/instruments", {"instType": "SWAP"})
        items = payload.get("data") if isinstance(payload, Mapping) else []
        return [contract for item in items or [] if (contract := normalize_okx_contract(item)) is not None]

    def snapshot_payloads(self, contract: PreIPOContract) -> list[Mapping[str, Any]]:
        return [
            {"arg": {"channel": "books", "instId": contract.contract_id}, **self._get("/api/v5/market/books", {"instId": contract.contract_id, "sz": 50})},
            {"arg": {"channel": "tickers", "instId": contract.contract_id}, **self._get("/api/v5/market/ticker", {"instId": contract.contract_id})},
            {"arg": {"channel": "mark-price", "instId": contract.contract_id}, **self._get("/api/v5/public/mark-price", {"instType": "SWAP", "instId": contract.contract_id})},
            {"arg": {"channel": "funding-rate", "instId": contract.contract_id}, **self._get("/api/v5/public/funding-rate", {"instType": "SWAP", "instId": contract.contract_id})},
            {"arg": {"channel": "open-interest", "instId": contract.contract_id}, **self._get("/api/v5/public/open-interest", {"instType": "SWAP", "instId": contract.contract_id})},
        ]

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

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/futures/usdt/contracts")
        return [contract for item in payload or [] if (contract := normalize_gate_contract(item)) is not None]

    def snapshot_payloads(self, contract: PreIPOContract) -> list[Mapping[str, Any]]:
        return [
            {"channel": "futures.order_book", "result": self._get("/futures/usdt/order_book", {"contract": contract.contract_id, "limit": 50})},
            {"channel": "futures.tickers", "result": self._get("/futures/usdt/tickers", {"contract": contract.contract_id})},
            {"channel": "futures.funding_rate", "result": self._get("/futures/usdt/funding_rate", {"contract": contract.contract_id})},
            {"channel": "futures.contract_stats", "result": self._get("/futures/usdt/contract_stats", {"contract": contract.contract_id, "interval": "5m", "limit": 1})},
        ]

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

    Declared as a candidate venue, not an active one: writing the adapter says we can
    collect here, and that is a separate statement from being authorised to. Promotion
    to the active venue set needs a capture run the operator authorises.
    """

    venue = "bitmex"
    base_url = "https://www.bitmex.com/api/v1"
    ws_url = "wss://ws.bitmex.com/realtime"

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/instrument/active")
        return [
            contract
            for item in payload or []
            if (contract := normalize_bitmex_contract(item)) is not None
        ]

    def snapshot_payloads(self, contract: PreIPOContract) -> list[Mapping[str, Any]]:
        symbol = contract.contract_id
        return [
            {"table": "orderBookL2_25", "data": self._get("/orderBook/L2", {"symbol": symbol, "depth": 25})},
            {"table": "instrument", "data": self._get("/instrument", {"symbol": symbol})},
            {"table": "trade", "data": self._get("/trade", {"symbol": symbol, "count": 50, "reverse": "true"})},
        ]

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        symbol = contract.contract_id
        return [
            {"op": "subscribe", "args": [f"orderBookL2_25:{symbol}"]},
            {"op": "subscribe", "args": [f"trade:{symbol}"]},
            {"op": "subscribe", "args": [f"instrument:{symbol}"]},
        ]



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

    def discover_contracts(self) -> list[PreIPOContract]:
        payload = self._get("/instruments")
        rows = payload.get("instruments") if isinstance(payload, Mapping) else payload
        return [
            contract
            for item in rows or []
            if (contract := normalize_kraken_contract(item)) is not None
        ]

    def snapshot_payloads(self, contract: PreIPOContract) -> list[Mapping[str, Any]]:
        symbol = contract.contract_id
        return [
            {"feed": "book_snapshot", "data": self._get("/orderbook", {"symbol": symbol})},
            {"feed": "ticker", "data": self._get("/tickers", {"symbol": symbol})},
        ]

    def websocket_subscriptions(self, contract: PreIPOContract) -> list[dict[str, Any]]:
        symbol = contract.contract_id
        return [
            {"event": "subscribe", "feed": "book", "product_ids": [symbol]},
            {"event": "subscribe", "feed": "trade", "product_ids": [symbol]},
            {"event": "subscribe", "feed": "ticker", "product_ids": [symbol]},
        ]


ADAPTERS["bitmex"] = BitmexPreIPOAdapter
ADAPTERS["kraken"] = KrakenPreIPOAdapter
assert set(ADAPTERS) == set(VENUES), "every declared venue needs an adapter"
