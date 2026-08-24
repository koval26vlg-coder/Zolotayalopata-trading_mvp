from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ws_normalizer import classify_ws_row, expected_market_channels


MARKET_SILENCE_RECONNECT_SEC = 120.0


class MarketSilenceError(RuntimeError):
    pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _payload_for_storage(message: str | bytes) -> dict[str, Any]:
    if isinstance(message, bytes):
        return {
            "encoding": "base64",
            "byte_length": len(message),
            "data": base64.b64encode(message).decode("ascii"),
        }
    try:
        return {"encoding": "json", "data": json.loads(message)}
    except json.JSONDecodeError:
        return {"encoding": "text", "data": message}


def _nested_symbol(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("symbol", "currency_pair", "s"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _nested_symbol(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _nested_symbol(item)
            if found:
                return found
    return None


@dataclass(frozen=True)
class WsCollectResult:
    exchange: str
    symbols: list[str]
    output: str
    events: int
    errors: list[str]
    duration_sec: float
    chunk_index: int = 0
    chunk_count: int = 1
    requested_duration_sec: int = 0
    completed: bool = False
    duration_completed: bool = False
    liveness_clean: bool = False
    quality_eligible: bool = False
    stop_reason: str = "unknown"
    attempts: int = 0
    transport_rows: int = 0
    market_envelope_rows: int = 0
    normalized_events: int = 0
    control_rows: int = 0
    unclassified_messages: int = 0
    market_silence_events: int = 0
    reconnect_attempts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbols": self.symbols,
            "output": self.output,
            "events": self.events,
            "errors": self.errors,
            "duration_sec": self.duration_sec,
            "actual_duration_sec": self.duration_sec,
            "requested_duration_sec": self.requested_duration_sec,
            "completed": self.completed,
            "duration_completed": self.duration_completed,
            "liveness_clean": self.liveness_clean,
            "quality_eligible": self.quality_eligible,
            "stop_reason": self.stop_reason,
            "attempts": self.attempts,
            "transport_rows": self.transport_rows,
            "market_envelope_rows": self.market_envelope_rows,
            "normalized_events": self.normalized_events,
            "control_rows": self.control_rows,
            "unclassified_messages": self.unclassified_messages,
            "market_silence_events": self.market_silence_events,
            "reconnect_attempts": self.reconnect_attempts,
            "chunk_index": self.chunk_index,
            "chunk_count": self.chunk_count,
        }


class RawEventWriter:
    def __init__(self, path: Path, flush_every: int = 100) -> None:
        self.path = path
        self.flush_every = max(1, flush_every)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.events = 0
        self.market_envelope_rows = 0
        self.normalized_events = 0
        self.control_rows = 0
        self.unclassified_messages = 0
        self.market_silence_events = 0

    def write_control(self, exchange: str, event_type: str, payload: Any) -> dict[str, Any]:
        row = {
            "recv_ts": time.time(),
            "exchange": exchange,
            "event_type": event_type,
            "channel": None,
            "symbol": None,
            "payload": {"encoding": "json", "data": payload},
        }
        self._write(row)
        self.control_rows += 1
        if event_type == "market_silence_detected":
            self.market_silence_events += 1
        return row

    def write_message(
        self,
        adapter: "WsAdapter",
        message: str | bytes,
        *,
        expected_symbols: list[str],
        expected_channels_by_symbol: dict[str, set[str]],
    ) -> dict[str, Any]:
        stored = _payload_for_storage(message)
        hint = adapter.message_hint(stored)
        row = {
            "recv_ts": time.time(),
            "exchange": adapter.exchange_id,
            "event_type": hint.get("event_type", "message"),
            "channel": hint.get("channel"),
            "symbol": hint.get("symbol"),
            "payload": stored,
        }
        self._write(row)
        classification = classify_ws_row(
            row,
            expected_exchange=adapter.exchange_id,
            expected_symbols=expected_symbols,
            expected_channels_by_symbol=expected_channels_by_symbol,
        )
        if classification["classification"] == "market":
            self.market_envelope_rows += 1
            self.normalized_events += len(classification["events"])
        elif classification["classification"] == "control":
            self.control_rows += 1
        else:
            self.unclassified_messages += 1
        return classification

    def _write(self, row: dict[str, Any]) -> None:
        self._fh.write(_json_dumps(row) + "\n")
        self.events += 1
        if self.events % self.flush_every == 0:
            self._fh.flush()

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()


class WsAdapter:
    exchange_id = ""
    display_name = ""
    ws_url = ""
    max_channels_per_connection: int | None = None

    def channels_per_symbol(
        self,
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> int:
        return 1

    def max_symbols_per_connection(
        self,
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> int | None:
        if self.max_channels_per_connection is None:
            return None
        channels = max(1, self.channels_per_symbol(update_interval, depth_levels))
        return max(1, self.max_channels_per_connection // channels)

    def subscription_messages(
        self,
        symbols: list[str],
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def heartbeat_message(self) -> dict[str, Any] | None:
        return None

    def message_hint(self, stored_payload: dict[str, Any]) -> dict[str, Any]:
        data = stored_payload.get("data")
        if stored_payload.get("encoding") == "base64":
            return {"event_type": "binary", "channel": None, "symbol": None}
        if isinstance(data, dict):
            return {
                "event_type": str(data.get("event") or data.get("method") or "json"),
                "channel": data.get("channel") or data.get("msg"),
                "symbol": data.get("symbol") or _nested_symbol(data.get("result")),
            }
        return {"event_type": stored_payload.get("encoding", "message"), "channel": None, "symbol": None}


class MexcWsAdapter(WsAdapter):
    exchange_id = "mexc"
    display_name = "MEXC"
    ws_url = "wss://wbs-api.mexc.com/ws"
    max_channels_per_connection = 30

    def channels_per_symbol(
        self,
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> int:
        return 3

    def subscription_messages(
        self,
        symbols: list[str],
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> list[dict[str, Any]]:
        interval = "10ms" if update_interval == "10ms" else "100ms"
        levels = 20 if depth_levels >= 20 else 10 if depth_levels >= 10 else 5
        channels: list[str] = []
        for symbol in symbols:
            channels.extend(
                [
                    f"spot@public.aggre.bookTicker.v3.api.pb@{interval}@{symbol}",
                    f"spot@public.aggre.deals.v3.api.pb@{interval}@{symbol}",
                    f"spot@public.limit.depth.v3.api.pb@{symbol}@{levels}",
                ]
            )
        if len(channels) > self.max_channels_per_connection:
            raise ValueError(
                f"MEXC supports up to {self.max_channels_per_connection} channels per connection; "
                f"requested {len(channels)}. Reduce --max-pairs-per-exchange."
            )
        return [{"method": "SUBSCRIPTION", "params": channels}]

    def heartbeat_message(self) -> dict[str, Any] | None:
        return {"method": "PING"}

    def message_hint(self, stored_payload: dict[str, Any]) -> dict[str, Any]:
        data = stored_payload.get("data")
        if stored_payload.get("encoding") == "base64":
            return {"event_type": "protobuf", "channel": None, "symbol": None}
        if isinstance(data, dict):
            return {
                "event_type": str(data.get("method") or "control"),
                "channel": data.get("channel") or data.get("msg"),
                "symbol": data.get("symbol"),
            }
        return super().message_hint(stored_payload)


class GateWsAdapter(WsAdapter):
    exchange_id = "gateio"
    display_name = "Gate"
    ws_url = "wss://api.gateio.ws/ws/v4/"

    def subscription_messages(
        self,
        symbols: list[str],
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> list[dict[str, Any]]:
        now = int(time.time())
        messages: list[dict[str, Any]] = [
            {"time": now, "channel": "spot.trades", "event": "subscribe", "payload": symbols},
            {"time": now, "channel": "spot.book_ticker", "event": "subscribe", "payload": symbols},
        ]
        for symbol in symbols:
            messages.append(
                {
                    "time": now,
                    "channel": "spot.order_book_update",
                    "event": "subscribe",
                    "payload": [symbol, update_interval],
                }
            )
        return messages

    def message_hint(self, stored_payload: dict[str, Any]) -> dict[str, Any]:
        data = stored_payload.get("data")
        if isinstance(data, dict):
            return {
                "event_type": str(data.get("event") or "json"),
                "channel": data.get("channel"),
                "symbol": _nested_symbol(data.get("result")) or _nested_symbol(data.get("payload")),
            }
        return super().message_hint(stored_payload)


class KucoinWsAdapter(WsAdapter):
    exchange_id = "kucoin"
    display_name = "Kucoin"
    max_channels_per_connection = 300

    @property
    def ws_url(self) -> str:
        import urllib.request
        import json
        req = urllib.request.Request("https://api.kucoin.com/api/v1/bullet-public", method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            token = data["data"]["token"]
            endpoint = data["data"]["instanceServers"][0]["endpoint"]
            return f"{endpoint}?token={token}"

    def subscription_messages(
        self,
        symbols: list[str],
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> list[dict[str, Any]]:
        now = int(time.time() * 1000)
        formatted_symbols = [f"{s.replace('_', '-')}" for s in symbols]
        sym_str = ",".join(formatted_symbols)
        return [
            {
                "id": now,
                "type": "subscribe",
                "topic": f"/market/ticker:{sym_str}",
                "privateChannel": False,
                "response": True
            },
            {
                "id": now + 1,
                "type": "subscribe",
                "topic": f"/market/level2:{sym_str}",
                "privateChannel": False,
                "response": True
            },
            {
                "id": now + 2,
                "type": "subscribe",
                "topic": f"/market/match:{sym_str}",
                "privateChannel": False,
                "response": True
            }
        ]

    def heartbeat_message(self) -> dict[str, Any] | None:
        return {"id": int(time.time() * 1000), "type": "ping"}

    def message_hint(self, stored_payload: dict[str, Any]) -> dict[str, Any]:
        data = stored_payload.get("data")
        if isinstance(data, dict):
            topic = str(data.get("topic") or "")
            subject = str(data.get("subject") or "")
            event_type = subject or data.get("type") or "json"
            symbol = None
            if ":" in topic:
                symbol = topic.split(":", 1)[1].replace("-", "_")
            return {
                "event_type": event_type,
                "channel": topic,
                "symbol": symbol,
            }
        return super().message_hint(stored_payload)


class BingxWsAdapter(WsAdapter):
    exchange_id = "bingx"
    display_name = "BingX"
    ws_url = "wss://open-api-ws.bingx.com/market"

    def subscription_messages(
        self,
        symbols: list[str],
        update_interval: str = "100ms",
        depth_levels: int = 20,
    ) -> list[dict[str, Any]]:
        messages = []
        for symbol in symbols:
            s = symbol.replace("_", "-")
            messages.append({"id": str(time.time()), "reqType": "sub", "dataType": f"{s}@trade"})
            messages.append({"id": str(time.time()), "reqType": "sub", "dataType": f"{s}@bookTicker"})
            messages.append({"id": str(time.time()), "reqType": "sub", "dataType": f"{s}@depth20"})
        return messages

    def heartbeat_message(self) -> dict[str, Any] | None:
        # BingX requires Ping/Pong. Usually sent as "Ping", responding with "Pong".
        # But this works for json pings.
        return None

    def message_hint(self, stored_payload: dict[str, Any]) -> dict[str, Any]:
        import gzip
        data = stored_payload.get("data")
        if stored_payload.get("encoding") == "base64":
            try:
                import base64
                raw = base64.b64decode(data)
                unzipped = gzip.decompress(raw)
                payload = json.loads(unzipped.decode('utf-8'))
                if payload.get("ping"):
                    return {"event_type": "ping", "channel": None, "symbol": None}
                datatype = str(payload.get("dataType") or "")
                symbol = None
                if "@" in datatype:
                    symbol = datatype.split("@")[0].replace("-", "_")
                return {
                    "event_type": payload.get("reqType", "json"),
                    "channel": datatype,
                    "symbol": symbol,
                }
            except Exception:
                pass
        if isinstance(data, dict):
            datatype = str(data.get("dataType") or "")
            event_type = "json"
            symbol = None
            if "@" in datatype:
                symbol = datatype.split("@")[0].replace("-", "_")
            return {
                "event_type": event_type,
                "channel": datatype,
                "symbol": symbol,
            }
        return super().message_hint(stored_payload)


WS_ADAPTERS: dict[str, type[WsAdapter]] = {
    MexcWsAdapter.exchange_id: MexcWsAdapter,
    GateWsAdapter.exchange_id: GateWsAdapter,
    KucoinWsAdapter.exchange_id: KucoinWsAdapter,
    BingxWsAdapter.exchange_id: BingxWsAdapter,
}


def build_ws_adapter(exchange_id: str) -> WsAdapter:
    key = exchange_id.strip().lower()
    if key not in WS_ADAPTERS:
        raise ValueError(f"WebSocket collector пока поддерживает: {', '.join(sorted(WS_ADAPTERS))}")
    return WS_ADAPTERS[key]()


def split_ws_symbols_for_connections(
    adapter: WsAdapter,
    symbols: list[str],
    update_interval: str = "100ms",
    depth_levels: int = 20,
) -> list[list[str]]:
    limit = adapter.max_symbols_per_connection(update_interval, depth_levels)
    if limit is None or limit <= 0 or len(symbols) <= limit:
        return [symbols]
    return [symbols[index : index + limit] for index in range(0, len(symbols), limit)]


def _collect_exchange_sync(
    adapter: WsAdapter,
    symbols: list[str],
    out_dir: Path,
    duration_sec: int,
    update_interval: str,
    depth_levels: int,
    chunk_index: int = 0,
    chunk_count: int = 1,
) -> WsCollectResult:
    chunk_suffix = f"_{chunk_index + 1:02d}of{chunk_count:02d}" if chunk_count > 1 else ""
    output = out_dir / f"ws_{adapter.exchange_id}{chunk_suffix}_{_utc_stamp()}.jsonl"
    writer = RawEventWriter(output)
    errors: list[str] = []
    started_monotonic = time.monotonic()
    deadline_monotonic = started_monotonic + duration_sec
    ws: Any = None
    attempts = 0
    duration_completed = False
    stop_reason = "not_started"
    try:
        import websocket  # type: ignore[import-not-found]

        subscribe_messages = adapter.subscription_messages(symbols, update_interval, depth_levels)
        expected_channels_by_symbol = {
            symbol.upper(): set(
                expected_market_channels(
                    adapter.exchange_id,
                    symbol,
                    update_interval=update_interval,
                    depth_levels=depth_levels,
                ).values()
            )
            for symbol in symbols
        }
        writer.write_control(
            adapter.exchange_id,
            "collector_start",
            {
                "ws_url": adapter.ws_url,
                "symbols": symbols,
                "subscriptions": subscribe_messages,
                "duration_sec": duration_sec,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
            },
        )
        stop_reason = "duration_sec"
        while time.monotonic() < deadline_monotonic:
            attempts += 1
            try:
                remaining_sec = max(0.0, deadline_monotonic - time.monotonic())
                writer.write_control(
                    adapter.exchange_id,
                    "connect_attempt",
                    {"attempt": attempts, "remaining_sec": round(remaining_sec, 3)},
                )
                ws = websocket.create_connection(adapter.ws_url, timeout=10)
                ws.settimeout(1)
                for message in subscribe_messages:
                    ws.send(_json_dumps(message))
                    writer.write_control(adapter.exchange_id, "subscribe_sent", message)

                subscriptions_sent_monotonic = time.monotonic()
                last_market_monotonic = subscriptions_sent_monotonic
                last_heartbeat_monotonic = subscriptions_sent_monotonic
                while time.monotonic() < deadline_monotonic:
                    now_monotonic = time.monotonic()
                    heartbeat = adapter.heartbeat_message()
                    if heartbeat is not None and now_monotonic - last_heartbeat_monotonic >= 20:
                        ws.send(_json_dumps(heartbeat))
                        writer.write_control(adapter.exchange_id, "heartbeat_sent", heartbeat)
                        last_heartbeat_monotonic = time.monotonic()
                    try:
                        message = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        message = None
                    if message in ("", b""):
                        raise ConnectionError("websocket returned an empty closed frame")
                    if message is not None:
                        classification = writer.write_message(
                            adapter,
                            message,
                            expected_symbols=symbols,
                            expected_channels_by_symbol=expected_channels_by_symbol,
                        )
                        if classification["qualifies_market_liveness"]:
                            last_market_monotonic = time.monotonic()
                    silence_sec = time.monotonic() - last_market_monotonic
                    if silence_sec >= MARKET_SILENCE_RECONNECT_SEC:
                        writer.write_control(
                            adapter.exchange_id,
                            "market_silence_detected",
                            {
                                "attempt": attempts,
                                "silence_sec": round(silence_sec, 3),
                                "threshold_sec": MARKET_SILENCE_RECONNECT_SEC,
                                "subscriptions_sent_monotonic": subscriptions_sent_monotonic,
                            },
                        )
                        raise MarketSilenceError(
                            f"no valid exact market event for {silence_sec:.3f}s"
                        )
                duration_completed = True
                stop_reason = (
                    "duration_sec_liveness_dirty"
                    if writer.market_silence_events
                    else "duration_sec"
                )
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"attempt={attempts} {type(exc).__name__}: {exc}")
                writer.write_control(
                    adapter.exchange_id,
                    "connect_attempt_error",
                    {"attempt": attempts, "error": errors[-1]},
                )
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ws = None
                if time.monotonic() >= deadline_monotonic:
                    duration_completed = True
                    stop_reason = (
                        "duration_sec_liveness_dirty"
                        if writer.market_silence_events
                        else "duration_sec_after_connection_error"
                    )
                    break
                # Long collectors must survive transient SSL/reset/network failures
                # without restarting the whole run. Bound backoff so visible guards
                # still get regular progress and stderr/status updates.
                sleep_sec = min(
                    30.0,
                    max(1.0, float(attempts)),
                    max(0.0, deadline_monotonic - time.monotonic()),
                )
                if sleep_sec > 0:
                    time.sleep(sleep_sec)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
        duration_completed = False
        stop_reason = "collector_error"
        writer.write_control(adapter.exchange_id, "collector_error", {"error": errors[-1]})
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        actual_duration_sec = time.monotonic() - started_monotonic
        liveness_clean = (
            writer.market_silence_events == 0
            and writer.unclassified_messages == 0
        )
        quality_eligible = duration_completed and liveness_clean and not errors
        writer.write_control(
            adapter.exchange_id,
            "collector_stop",
            {
                "errors": errors,
                "attempts": attempts,
                "completed": quality_eligible,
                "duration_completed": duration_completed,
                "liveness_clean": liveness_clean,
                "quality_eligible": quality_eligible,
                "stop_reason": stop_reason,
                "requested_duration_sec": duration_sec,
                "actual_duration_sec": actual_duration_sec,
            },
        )
        writer.close()

    actual_duration_sec = time.monotonic() - started_monotonic
    liveness_clean = (
        writer.market_silence_events == 0
        and writer.unclassified_messages == 0
    )
    quality_eligible = duration_completed and liveness_clean and not errors
    return WsCollectResult(
        exchange=adapter.exchange_id,
        symbols=symbols,
        output=str(output),
        events=writer.events,
        errors=errors,
        duration_sec=actual_duration_sec,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        requested_duration_sec=duration_sec,
        completed=quality_eligible,
        duration_completed=duration_completed,
        liveness_clean=liveness_clean,
        quality_eligible=quality_eligible,
        stop_reason=stop_reason,
        attempts=attempts,
        transport_rows=writer.events,
        market_envelope_rows=writer.market_envelope_rows,
        normalized_events=writer.normalized_events,
        control_rows=writer.control_rows,
        unclassified_messages=writer.unclassified_messages,
        market_silence_events=writer.market_silence_events,
        reconnect_attempts=max(0, attempts - 1),
    )


async def _collect_exchange(
    adapter: WsAdapter,
    symbols: list[str],
    out_dir: Path,
    duration_sec: int,
    update_interval: str,
    depth_levels: int,
    chunk_index: int = 0,
    chunk_count: int = 1,
) -> WsCollectResult:
    return await asyncio.to_thread(
        _collect_exchange_sync,
        adapter,
        symbols,
        out_dir,
        duration_sec,
        update_interval,
        depth_levels,
        chunk_index,
        chunk_count,
    )


async def collect_ws_markets_async(
    symbols_by_exchange: dict[str, list[str]],
    out_dir: str | Path,
    duration_sec: int,
    update_interval: str = "100ms",
    depth_levels: int = 20,
) -> dict[str, Any]:
    if duration_sec <= 0:
        raise ValueError("duration_sec должен быть больше 0")
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    started_at_utc = _utc_stamp()
    tasks = []
    for exchange_id, symbols in symbols_by_exchange.items():
        if not symbols:
            continue
        planning_adapter = build_ws_adapter(exchange_id)
        chunks = split_ws_symbols_for_connections(
            planning_adapter,
            symbols,
            update_interval=update_interval,
            depth_levels=depth_levels,
        )
        for chunk_index, chunk in enumerate(chunks):
            tasks.append(
                _collect_exchange(
                    adapter=build_ws_adapter(exchange_id),
                    symbols=chunk,
                    out_dir=target_dir,
                    duration_sec=duration_sec,
                    update_interval=update_interval,
                    depth_levels=depth_levels,
                    chunk_index=chunk_index,
                    chunk_count=len(chunks),
                )
            )
    if not tasks:
        raise ValueError("Нет символов для WebSocket-сбора")
    results = await asyncio.gather(*tasks)
    errors: dict[str, list[str]] = {}
    for item in results:
        if item.errors:
            errors.setdefault(item.exchange, []).extend(item.errors)
    actual_duration_sec = max((item.duration_sec for item in results), default=0.0)
    duration_completed = all(item.duration_completed for item in results)
    liveness_clean = all(item.liveness_clean for item in results)
    quality_eligible = duration_completed and liveness_clean
    completed = quality_eligible
    stop_reasons = sorted({item.stop_reason for item in results})
    stop_condition = (
        "duration_sec"
        if quality_eligible
        else "duration_sec_liveness_dirty"
        if duration_completed
        else "incomplete"
    )
    return {
        "started_at_utc": started_at_utc,
        "duration_sec": duration_sec,
        "requested_duration_sec": duration_sec,
        "actual_duration_sec": actual_duration_sec,
        "completed": completed,
        "duration_completed": duration_completed,
        "liveness_clean": liveness_clean,
        "quality_eligible": quality_eligible,
        "final": quality_eligible,
        "stop_condition": stop_condition,
        "stop_reasons": stop_reasons,
        "update_interval": update_interval,
        "depth_levels": depth_levels,
        "results": [item.as_dict() for item in results],
        "total_events": sum(item.events for item in results),
        "transport_rows": sum(item.transport_rows for item in results),
        "market_envelope_rows": sum(item.market_envelope_rows for item in results),
        "normalized_events": sum(item.normalized_events for item in results),
        "control_rows": sum(item.control_rows for item in results),
        "unclassified_messages": sum(item.unclassified_messages for item in results),
        "market_silence_events": sum(item.market_silence_events for item in results),
        "reconnect_attempts": sum(item.reconnect_attempts for item in results),
        "errors": errors,
    }


def collect_ws_markets(
    symbols_by_exchange: dict[str, list[str]],
    out_dir: str | Path,
    duration_sec: int,
    update_interval: str = "100ms",
    depth_levels: int = 20,
) -> dict[str, Any]:
    return asyncio.run(
        collect_ws_markets_async(
            symbols_by_exchange=symbols_by_exchange,
            out_dir=out_dir,
            duration_sec=duration_sec,
            update_interval=update_interval,
            depth_levels=depth_levels,
        )
    )


def ws_manifest_path(raw_dir: str | Path) -> Path:
    return Path(raw_dir) / f"ws_collect_{_utc_stamp()}.json"


def save_ws_manifest(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
