from __future__ import annotations

import base64
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Mapping


WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_32BIT = 5

GATE_MARKET_CHANNELS = {
    "spot.book_ticker": "bbo",
    "spot.order_book_update": "depth",
    "spot.trades": "trade",
}
MEXC_CHANNEL_PREFIXES = {
    "spot@public.aggre.bookTicker.v3.api.pb": ("bbo", "aggre_book_ticker"),
    "spot@public.limit.depth.v3.api.pb": ("depth", "limit_depth"),
    "spot@public.aggre.deals.v3.api.pb": ("trade", "aggre_deals"),
}
CONTROL_EVENT_TYPES = {
    "collector_start",
    "collector_stop",
    "collector_error",
    "connect_attempt",
    "connect_attempt_error",
    "subscribe_sent",
    "heartbeat_sent",
    "market_silence_detected",
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _epoch_seconds(value: Any) -> float | None:
    num = _as_float(value)
    if num is None:
        return None
    if num > 1e15:
        return num / 1e6
    if num > 1e11:
        return num / 1e3
    return num


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 1e4


class ProtoDecodeError(RuntimeError):
    pass


class MarketDataClassificationError(ValueError):
    """A market-looking frame failed the frozen structural contract."""


@dataclass(frozen=True)
class ProtoField:
    number: int
    wire_type: int
    value: int | bytes


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
        if shift > 70:
            raise ProtoDecodeError("varint is too long")
    raise ProtoDecodeError("unexpected end of varint")


def _parse_proto_fields(data: bytes) -> list[ProtoField]:
    fields: list[ProtoField] = []
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number <= 0:
            raise ProtoDecodeError(f"invalid field number: {field_number}")
        if wire_type == WIRE_VARINT:
            value, pos = _read_varint(data, pos)
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, pos = _read_varint(data, pos)
            end = pos + length
            if end > len(data):
                raise ProtoDecodeError("length-delimited field exceeds message length")
            value = data[pos:end]
            pos = end
        elif wire_type == WIRE_64BIT:
            end = pos + 8
            if end > len(data):
                raise ProtoDecodeError("64-bit field exceeds message length")
            value = data[pos:end]
            pos = end
        elif wire_type == WIRE_32BIT:
            end = pos + 4
            if end > len(data):
                raise ProtoDecodeError("32-bit field exceeds message length")
            value = data[pos:end]
            pos = end
        else:
            raise ProtoDecodeError(f"unsupported wire type: {wire_type}")
        fields.append(ProtoField(field_number, wire_type, value))
    return fields


def _fields_by_number(data: bytes) -> dict[int, list[ProtoField]]:
    out: dict[int, list[ProtoField]] = {}
    for field in _parse_proto_fields(data):
        out.setdefault(field.number, []).append(field)
    return out


def _first(fields: dict[int, list[ProtoField]], number: int) -> ProtoField | None:
    values = fields.get(number) or []
    return values[0] if values else None


def _first_int(fields: dict[int, list[ProtoField]], number: int) -> int | None:
    field = _first(fields, number)
    if field is None or not isinstance(field.value, int):
        return None
    return field.value


def _first_str(fields: dict[int, list[ProtoField]], number: int) -> str | None:
    field = _first(fields, number)
    if field is None or not isinstance(field.value, bytes):
        return None
    try:
        return field.value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _message_values(fields: dict[int, list[ProtoField]], number: int) -> list[bytes]:
    return [field.value for field in fields.get(number, []) if isinstance(field.value, bytes)]


def _price_qty_item(data: bytes) -> list[float]:
    fields = _fields_by_number(data)
    price = _as_float(_first_str(fields, 1))
    qty = _as_float(_first_str(fields, 2))
    if price is None or qty is None:
        raise ProtoDecodeError("price/qty item is incomplete")
    return [price, qty]


def _parse_mexc_book_ticker(data: bytes) -> dict[str, Any]:
    fields = _fields_by_number(data)
    return {
        "bid_price": _as_float(_first_str(fields, 1)),
        "bid_qty": _as_float(_first_str(fields, 2)),
        "ask_price": _as_float(_first_str(fields, 3)),
        "ask_qty": _as_float(_first_str(fields, 4)),
    }


def _parse_mexc_limit_depth(data: bytes) -> dict[str, Any]:
    fields = _fields_by_number(data)
    asks = [_price_qty_item(item) for item in _message_values(fields, 1)]
    bids = [_price_qty_item(item) for item in _message_values(fields, 2)]
    return {
        "asks": asks,
        "bids": bids,
        "event_type": _first_str(fields, 3),
        "version": _first_str(fields, 4),
    }


def _parse_mexc_deal_item(data: bytes) -> dict[str, Any]:
    fields = _fields_by_number(data)
    trade_type = _first_int(fields, 3)
    return {
        "price": _as_float(_first_str(fields, 1)),
        "qty": _as_float(_first_str(fields, 2)),
        "side": "buy" if trade_type == 1 else "sell" if trade_type == 2 else None,
        "trade_type": trade_type,
        "trade_ts": _epoch_seconds(_first_int(fields, 4)),
    }


def _parse_mexc_deals(data: bytes) -> dict[str, Any]:
    fields = _fields_by_number(data)
    return {
        "deals": [_parse_mexc_deal_item(item) for item in _message_values(fields, 1)],
        "event_type": _first_str(fields, 2),
    }


def decode_mexc_wrapper(raw: bytes) -> dict[str, Any]:
    fields = _fields_by_number(raw)
    decoded: dict[str, Any] = {
        "channel": _first_str(fields, 1),
        "symbol": _first_str(fields, 3),
        "symbol_id": _first_str(fields, 4),
        "create_time": _epoch_seconds(_first_int(fields, 5)),
        "send_time": _epoch_seconds(_first_int(fields, 6)),
        "body_type": None,
        "body": None,
    }

    if _message_values(fields, 303):
        decoded["body_type"] = "limit_depth"
        decoded["body"] = _parse_mexc_limit_depth(_message_values(fields, 303)[0])
    elif _message_values(fields, 314):
        decoded["body_type"] = "aggre_deals"
        decoded["body"] = _parse_mexc_deals(_message_values(fields, 314)[0])
    elif _message_values(fields, 315):
        decoded["body_type"] = "aggre_book_ticker"
        decoded["body"] = _parse_mexc_book_ticker(_message_values(fields, 315)[0])
    elif _message_values(fields, 305):
        decoded["body_type"] = "book_ticker"
        decoded["body"] = _parse_mexc_book_ticker(_message_values(fields, 305)[0])

    return decoded


def _base_event(raw_row: dict[str, Any], symbol: str | None, kind: str, exchange_ts: float | None) -> dict[str, Any]:
    return {
        "recv_ts": raw_row.get("recv_ts"),
        "exchange_ts": exchange_ts,
        "exchange": raw_row.get("exchange"),
        "symbol": symbol or raw_row.get("symbol"),
        "event_kind": kind,
        "channel": raw_row.get("channel"),
    }


def _positive_float(value: Any, *, label: str) -> float:
    number = _as_float(value)
    if number is None or number <= 0:
        raise MarketDataClassificationError(f"{label} must be finite and positive")
    return number


def _validated_levels(value: Any, *, label: str) -> list[list[float]]:
    if not isinstance(value, list):
        raise MarketDataClassificationError(f"{label} must be a list")
    levels: list[list[float]] = []
    for index, item in enumerate(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise MarketDataClassificationError(f"{label}[{index}] must be [price, qty]")
        price = _positive_float(item[0], label=f"{label}[{index}].price")
        qty = _as_float(item[1])
        if qty is None or qty < 0:
            raise MarketDataClassificationError(
                f"{label}[{index}].qty must be finite and non-negative"
            )
        levels.append([price, qty])
    return levels


def _mexc_channel_contract(channel: Any) -> tuple[str, str, str]:
    value = str(channel or "")
    for prefix, (kind, body_type) in MEXC_CHANNEL_PREFIXES.items():
        marker = f"{prefix}@"
        if not value.startswith(marker):
            continue
        tail = value[len(marker) :].split("@")
        if len(tail) != 2:
            break
        if kind == "depth":
            symbol, levels = tail
            if levels not in {"5", "10", "20"}:
                break
        else:
            interval, symbol = tail
            if interval not in {"10ms", "100ms"}:
                break
        if not symbol or symbol != symbol.upper():
            break
        return kind, body_type, symbol
    raise MarketDataClassificationError(f"unsupported or malformed MEXC channel: {value!r}")


def expected_market_channels(
    exchange: str,
    symbol: str,
    *,
    update_interval: str = "100ms",
    depth_levels: int = 20,
) -> dict[str, str]:
    venue = exchange.strip().lower()
    market = symbol.strip().upper()
    if venue == "gateio":
        return {kind: channel for channel, kind in GATE_MARKET_CHANNELS.items()}
    if venue == "mexc":
        interval = "10ms" if update_interval == "10ms" else "100ms"
        levels = 20 if depth_levels >= 20 else 10 if depth_levels >= 10 else 5
        return {
            "bbo": f"spot@public.aggre.bookTicker.v3.api.pb@{interval}@{market}",
            "depth": f"spot@public.limit.depth.v3.api.pb@{market}@{levels}",
            "trade": f"spot@public.aggre.deals.v3.api.pb@{interval}@{market}",
        }
    raise ValueError(f"unsupported WS exchange: {exchange!r}")


def _normalize_mexc_row(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    payload = raw_row.get("payload") or {}
    if payload.get("encoding") != "base64":
        return []
    data = payload.get("data")
    if not isinstance(data, str):
        raise MarketDataClassificationError("MEXC base64 payload data is missing")
    try:
        decoded = decode_mexc_wrapper(base64.b64decode(data, validate=True))
    except (ValueError, TypeError, ProtoDecodeError) as exc:
        raise MarketDataClassificationError(f"MEXC protobuf decode failed: {exc}") from exc
    body = decoded.get("body") or {}
    channel = decoded.get("channel")
    kind, expected_body_type, channel_symbol = _mexc_channel_contract(channel)
    symbol = str(decoded.get("symbol") or "")
    if symbol != channel_symbol:
        raise MarketDataClassificationError(
            f"MEXC symbol/channel mismatch: symbol={symbol!r} channel_symbol={channel_symbol!r}"
        )
    raw_channel = raw_row.get("channel")
    if raw_channel is not None and raw_channel != channel:
        raise MarketDataClassificationError("MEXC envelope channel mismatch")
    raw_symbol = raw_row.get("symbol")
    if raw_symbol is not None and str(raw_symbol).upper() != symbol:
        raise MarketDataClassificationError("MEXC envelope symbol mismatch")
    exchange_ts = decoded.get("send_time") or decoded.get("create_time")
    body_type = decoded.get("body_type")
    if body_type != expected_body_type or not isinstance(body, dict):
        raise MarketDataClassificationError(
            f"MEXC body/channel mismatch: kind={kind!r} body_type={body_type!r}"
        )

    if kind == "bbo":
        bid = _positive_float(body.get("bid_price"), label="MEXC bid_price")
        bid_qty = _positive_float(body.get("bid_qty"), label="MEXC bid_qty")
        ask = _positive_float(body.get("ask_price"), label="MEXC ask_price")
        ask_qty = _positive_float(body.get("ask_qty"), label="MEXC ask_qty")
        if ask < bid:
            raise MarketDataClassificationError("MEXC ask_price is below bid_price")
        event = _base_event(raw_row, symbol, "bbo", exchange_ts)
        event.update(
            {
                "channel": channel,
                "bid_price": bid,
                "bid_qty": bid_qty,
                "ask_price": ask,
                "ask_qty": ask_qty,
                "spread_bps": _spread_bps(bid, ask),
            }
        )
        return [event]

    if kind == "depth":
        bids = _validated_levels(body.get("bids"), label="MEXC bids")
        asks = _validated_levels(body.get("asks"), label="MEXC asks")
        if not bids and not asks:
            raise MarketDataClassificationError("MEXC depth has no positive levels")
        event = _base_event(raw_row, symbol, "depth", exchange_ts)
        event.update(
            {
                "channel": channel,
                "depth_type": "snapshot",
                "bids": bids,
                "asks": asks,
                "version": body.get("version"),
            }
        )
        return [event]

    if kind == "trade":
        deals = body.get("deals")
        if not isinstance(deals, list) or not deals:
            raise MarketDataClassificationError("MEXC trade packet is empty")
        out: list[dict[str, Any]] = []
        for index, item in enumerate(deals):
            if not isinstance(item, dict):
                raise MarketDataClassificationError(f"MEXC trade[{index}] is not an object")
            price = _positive_float(item.get("price"), label=f"MEXC trade[{index}].price")
            qty = _positive_float(item.get("qty"), label=f"MEXC trade[{index}].qty")
            side = item.get("side")
            if side not in {"buy", "sell"}:
                raise MarketDataClassificationError(f"MEXC trade[{index}].side is invalid")
            event = _base_event(raw_row, symbol, "trade", item.get("trade_ts") or exchange_ts)
            event.update(
                {
                    "channel": channel,
                    "price": price,
                    "qty": qty,
                    "side": side,
                    "trade_type": item.get("trade_type"),
                }
            )
            out.append(event)
        return out

    raise MarketDataClassificationError(f"unsupported MEXC market kind: {kind!r}")


def _gate_result(payload_data: dict[str, Any]) -> dict[str, Any] | None:
    result = payload_data.get("result")
    return result if isinstance(result, dict) else None


def _normalize_gate_row(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    payload = raw_row.get("payload") or {}
    if payload.get("encoding") != "json":
        return []
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("event") != "update":
        return []
    result = _gate_result(data)
    if result is None:
        raise MarketDataClassificationError("Gate update result is missing")
    channel = str(data.get("channel") or "")
    kind = GATE_MARKET_CHANNELS.get(channel)
    if kind is None:
        raise MarketDataClassificationError(f"unsupported Gate market channel: {channel!r}")
    raw_channel = raw_row.get("channel")
    if raw_channel is not None and raw_channel != channel:
        raise MarketDataClassificationError("Gate envelope channel mismatch")
    exchange_ts = _epoch_seconds(data.get("time_ms") or result.get("t") or data.get("time"))

    if kind == "bbo":
        symbol = str(result.get("s") or "")
        bid = _positive_float(result.get("b"), label="Gate bid_price")
        bid_qty = _positive_float(result.get("B"), label="Gate bid_qty")
        ask = _positive_float(result.get("a"), label="Gate ask_price")
        ask_qty = _positive_float(result.get("A"), label="Gate ask_qty")
        if ask < bid:
            raise MarketDataClassificationError("Gate ask_price is below bid_price")
        event = _base_event(raw_row, symbol, "bbo", exchange_ts)
        event.update(
            {
                "channel": channel,
                "bid_price": bid,
                "bid_qty": bid_qty,
                "ask_price": ask,
                "ask_qty": ask_qty,
                "spread_bps": _spread_bps(bid, ask),
                "sequence": result.get("u"),
            }
        )
    elif kind == "depth":
        symbol = str(result.get("s") or "")
        bids = _validated_levels(result.get("b"), label="Gate bids")
        asks = _validated_levels(result.get("a"), label="Gate asks")
        if not bids and not asks:
            raise MarketDataClassificationError("Gate depth has no positive levels")
        event = _base_event(raw_row, symbol, "depth", exchange_ts)
        event.update(
            {
                "channel": channel,
                "depth_type": "delta",
                "bids": bids,
                "asks": asks,
                "first_update_id": result.get("U"),
                "last_update_id": result.get("u"),
            }
        )
    else:
        symbol = str(result.get("currency_pair") or "")
        price = _positive_float(result.get("price"), label="Gate trade.price")
        qty = _positive_float(result.get("amount"), label="Gate trade.qty")
        side = result.get("side")
        if side not in {"buy", "sell"}:
            raise MarketDataClassificationError("Gate trade.side is invalid")
        event = _base_event(
            raw_row,
            symbol,
            "trade",
            _epoch_seconds(result.get("create_time_ms")) or exchange_ts,
        )
        event.update(
            {
                "channel": channel,
                "trade_id": result.get("id"),
                "price": price,
                "qty": qty,
                "side": side,
            }
        )
    if not symbol or symbol != symbol.upper():
        raise MarketDataClassificationError("Gate symbol is missing or non-canonical")
    raw_symbol = raw_row.get("symbol")
    if raw_symbol is not None and str(raw_symbol).upper() != symbol:
        raise MarketDataClassificationError("Gate envelope symbol mismatch")
    return [event]


def normalize_ws_row(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    exchange = str(raw_row.get("exchange") or "").lower()
    if exchange == "mexc":
        return _normalize_mexc_row(raw_row)
    if exchange == "gateio":
        return _normalize_gate_row(raw_row)
    return []


def _is_control_row(raw_row: Mapping[str, Any]) -> bool:
    event_type = str(raw_row.get("event_type") or "")
    if event_type in CONTROL_EVENT_TYPES:
        return True
    payload = raw_row.get("payload")
    if not isinstance(payload, Mapping):
        return False
    encoding = str(payload.get("encoding") or "")
    data = payload.get("data")
    if encoding == "text" and isinstance(data, str):
        return data.strip().upper() in {"PING", "PONG"}
    if encoding != "json" or not isinstance(data, Mapping):
        return False
    method = str(data.get("method") or "").upper()
    event = str(data.get("event") or "").lower()
    channel = str(data.get("channel") or "").lower()
    message = str(data.get("msg") or "").upper()
    return (
        method in {"PING", "PONG", "SUBSCRIPTION", "UNSUBSCRIPTION"}
        or event in {"subscribe", "unsubscribe"}
        or channel in {"spot.ping", "spot.pong"}
        or message in {"PING", "PONG"}
    )


def classify_ws_row(
    raw_row: Mapping[str, Any],
    *,
    expected_exchange: str | None = None,
    expected_symbols: Collection[str] | None = None,
    expected_channels_by_symbol: Mapping[str, Collection[str]] | None = None,
) -> dict[str, Any]:
    """Classify a raw frame using the same fail-closed rules everywhere."""

    row = dict(raw_row)
    exchange = str(row.get("exchange") or "").lower()
    expected_venue = str(expected_exchange or exchange).lower()
    if exchange != expected_venue:
        return {
            "classification": "unclassified",
            "reason": "exchange_mismatch",
            "events": [],
            "qualifies_market_liveness": False,
        }
    expected_symbol_set = (
        {str(item).strip().upper() for item in expected_symbols}
        if expected_symbols is not None
        else None
    )
    try:
        events = normalize_ws_row(row)
    except (MarketDataClassificationError, ProtoDecodeError, ValueError, TypeError) as exc:
        return {
            "classification": "unclassified",
            "reason": f"market_structure:{type(exc).__name__}:{exc}",
            "events": [],
            "qualifies_market_liveness": False,
        }
    if events:
        for event in events:
            event_exchange = str(event.get("exchange") or "").lower()
            symbol = str(event.get("symbol") or "").upper()
            channel = str(event.get("channel") or "")
            if event_exchange != expected_venue:
                reason = "normalized_exchange_mismatch"
                break
            if expected_symbol_set is not None and symbol not in expected_symbol_set:
                reason = f"foreign_symbol:{symbol}"
                break
            if expected_channels_by_symbol is not None:
                allowed_channels = {
                    str(item) for item in expected_channels_by_symbol.get(symbol, ())
                }
                if channel not in allowed_channels:
                    reason = f"foreign_channel:{channel}"
                    break
        else:
            return {
                "classification": "market",
                "reason": "valid_exact_market_event",
                "events": events,
                "qualifies_market_liveness": True,
            }
        return {
            "classification": "unclassified",
            "reason": reason,
            "events": [],
            "qualifies_market_liveness": False,
        }
    if _is_control_row(row):
        return {
            "classification": "control",
            "reason": "recognized_control",
            "events": [],
            "qualifies_market_liveness": False,
        }
    return {
        "classification": "unclassified",
        "reason": "no_valid_market_event_or_known_control",
        "events": [],
        "qualifies_market_liveness": False,
    }


def _read_manifest_or_raw_paths(input_path: Path) -> list[Path]:
    if input_path.suffix.lower() != ".json":
        return [input_path]
    manifest = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("results"), list):
        return [input_path]
    paths: list[Path] = []
    for item in manifest["results"]:
        if not isinstance(item, dict) or not item.get("output"):
            continue
        output = Path(str(item["output"]))
        if not output.is_absolute():
            output = input_path.parents[3] / output if len(input_path.parents) >= 4 else output
        paths.append(output)
    return paths


def normalize_ws_files(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(input_path)
    paths = _read_manifest_or_raw_paths(source)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    raw_rows = 0
    decode_errors: list[dict[str, Any]] = []
    by_kind: Counter[str] = Counter()
    by_exchange: Counter[str] = Counter()

    with target.open("w", encoding="utf-8") as out:
        for path in paths:
            with path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    raw_rows += 1
                    try:
                        raw_row = json.loads(line)
                        for event in normalize_ws_row(raw_row):
                            out.write(_json_dumps(event) + "\n")
                            rows_written += 1
                            by_kind[str(event.get("event_kind"))] += 1
                            by_exchange[str(event.get("exchange"))] += 1
                    except Exception as exc:  # noqa: BLE001
                        decode_errors.append(
                            {
                                "file": str(path),
                                "line": line_no,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )

    return {
        "input_files": [str(path) for path in paths],
        "output": str(target),
        "raw_rows": raw_rows,
        "normalized_rows": rows_written,
        "by_kind": dict(by_kind),
        "by_exchange": dict(by_exchange),
        "decode_errors": decode_errors[:50],
        "decode_error_count": len(decode_errors),
    }


def default_normalized_path(normalized_dir: str | Path) -> Path:
    return Path(normalized_dir) / f"ws_normalized_{utc_stamp()}.jsonl"
