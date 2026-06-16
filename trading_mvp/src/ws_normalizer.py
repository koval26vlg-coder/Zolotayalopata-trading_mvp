from __future__ import annotations

import base64
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_32BIT = 5


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _normalize_mexc_row(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    payload = raw_row.get("payload") or {}
    if payload.get("encoding") != "base64":
        return []
    decoded = decode_mexc_wrapper(base64.b64decode(payload["data"]))
    body = decoded.get("body") or {}
    symbol = decoded.get("symbol")
    channel = decoded.get("channel") or raw_row.get("channel")
    exchange_ts = decoded.get("send_time") or decoded.get("create_time")
    body_type = decoded.get("body_type")

    if body_type in {"aggre_book_ticker", "book_ticker"}:
        bid = body.get("bid_price")
        ask = body.get("ask_price")
        event = _base_event(raw_row, symbol, "bbo", exchange_ts)
        event.update(
            {
                "channel": channel,
                "bid_price": bid,
                "bid_qty": body.get("bid_qty"),
                "ask_price": ask,
                "ask_qty": body.get("ask_qty"),
                "spread_bps": _spread_bps(bid, ask),
            }
        )
        return [event]

    if body_type == "limit_depth":
        event = _base_event(raw_row, symbol, "depth", exchange_ts)
        event.update(
            {
                "channel": channel,
                "depth_type": "snapshot",
                "bids": body.get("bids", []),
                "asks": body.get("asks", []),
                "version": body.get("version"),
            }
        )
        return [event]

    if body_type == "aggre_deals":
        out: list[dict[str, Any]] = []
        for item in body.get("deals", []):
            event = _base_event(raw_row, symbol, "trade", item.get("trade_ts") or exchange_ts)
            event.update(
                {
                    "channel": channel,
                    "price": item.get("price"),
                    "qty": item.get("qty"),
                    "side": item.get("side"),
                    "trade_type": item.get("trade_type"),
                }
            )
            out.append(event)
        return out

    return []


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
        return []
    channel = data.get("channel")
    exchange_ts = _epoch_seconds(data.get("time_ms") or result.get("t") or data.get("time"))

    if channel == "spot.book_ticker":
        bid = _as_float(result.get("b"))
        ask = _as_float(result.get("a"))
        event = _base_event(raw_row, result.get("s"), "bbo", exchange_ts)
        event.update(
            {
                "channel": channel,
                "bid_price": bid,
                "bid_qty": _as_float(result.get("B")),
                "ask_price": ask,
                "ask_qty": _as_float(result.get("A")),
                "spread_bps": _spread_bps(bid, ask),
                "sequence": result.get("u"),
            }
        )
        return [event]

    if channel == "spot.order_book_update":
        event = _base_event(raw_row, result.get("s"), "depth", exchange_ts)
        event.update(
            {
                "channel": channel,
                "depth_type": "delta",
                "bids": [[_as_float(p), _as_float(q)] for p, q in result.get("b", [])],
                "asks": [[_as_float(p), _as_float(q)] for p, q in result.get("a", [])],
                "first_update_id": result.get("U"),
                "last_update_id": result.get("u"),
            }
        )
        return [event]

    if channel == "spot.trades":
        event = _base_event(raw_row, result.get("currency_pair"), "trade", _epoch_seconds(result.get("create_time_ms")) or exchange_ts)
        event.update(
            {
                "channel": channel,
                "trade_id": result.get("id"),
                "price": _as_float(result.get("price")),
                "qty": _as_float(result.get("amount")),
                "side": result.get("side"),
            }
        )
        return [event]

    return []


def normalize_ws_row(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    exchange = str(raw_row.get("exchange") or "").lower()
    if exchange == "mexc":
        return _normalize_mexc_row(raw_row)
    if exchange == "gateio":
        return _normalize_gate_row(raw_row)
    return []


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
