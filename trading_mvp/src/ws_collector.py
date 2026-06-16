from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "symbols": self.symbols,
            "output": self.output,
            "events": self.events,
            "errors": self.errors,
            "duration_sec": self.duration_sec,
        }


class RawEventWriter:
    def __init__(self, path: Path, flush_every: int = 100) -> None:
        self.path = path
        self.flush_every = max(1, flush_every)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.events = 0

    def write_control(self, exchange: str, event_type: str, payload: Any) -> None:
        self._write(
            {
                "recv_ts": time.time(),
                "exchange": exchange,
                "event_type": event_type,
                "channel": None,
                "symbol": None,
                "payload": {"encoding": "json", "data": payload},
            }
        )

    def write_message(self, adapter: "WsAdapter", message: str | bytes) -> None:
        stored = _payload_for_storage(message)
        hint = adapter.message_hint(stored)
        self._write(
            {
                "recv_ts": time.time(),
                "exchange": adapter.exchange_id,
                "event_type": hint.get("event_type", "message"),
                "channel": hint.get("channel"),
                "symbol": hint.get("symbol"),
                "payload": stored,
            }
        )

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
    max_channels_per_connection = 30

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


WS_ADAPTERS: dict[str, type[WsAdapter]] = {
    MexcWsAdapter.exchange_id: MexcWsAdapter,
    GateWsAdapter.exchange_id: GateWsAdapter,
}


def build_ws_adapter(exchange_id: str) -> WsAdapter:
    key = exchange_id.strip().lower()
    if key not in WS_ADAPTERS:
        raise ValueError(f"WebSocket collector пока поддерживает: {', '.join(sorted(WS_ADAPTERS))}")
    return WS_ADAPTERS[key]()


def _collect_exchange_sync(
    adapter: WsAdapter,
    symbols: list[str],
    out_dir: Path,
    duration_sec: int,
    update_interval: str,
    depth_levels: int,
) -> WsCollectResult:
    output = out_dir / f"ws_{adapter.exchange_id}_{_utc_stamp()}.jsonl"
    writer = RawEventWriter(output)
    errors: list[str] = []
    started = time.time()
    ws: Any = None
    try:
        import websocket  # type: ignore[import-not-found]

        subscribe_messages = adapter.subscription_messages(symbols, update_interval, depth_levels)
        writer.write_control(
            adapter.exchange_id,
            "collector_start",
            {
                "ws_url": adapter.ws_url,
                "symbols": symbols,
                "subscriptions": subscribe_messages,
                "duration_sec": duration_sec,
            },
        )
        for attempt in range(1, 4):
            try:
                writer.write_control(adapter.exchange_id, "connect_attempt", {"attempt": attempt})
                ws = websocket.create_connection(adapter.ws_url, timeout=10)
                ws.settimeout(1)
                for message in subscribe_messages:
                    ws.send(_json_dumps(message))
                    writer.write_control(adapter.exchange_id, "subscribe_sent", message)

                deadline = time.time() + duration_sec
                last_heartbeat = time.time()
                while time.time() < deadline:
                    heartbeat = adapter.heartbeat_message()
                    if heartbeat is not None and time.time() - last_heartbeat >= 20:
                        ws.send(_json_dumps(heartbeat))
                        writer.write_control(adapter.exchange_id, "heartbeat_sent", heartbeat)
                        last_heartbeat = time.time()
                    try:
                        message = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    writer.write_message(adapter, message)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"attempt={attempt} {type(exc).__name__}: {exc}")
                writer.write_control(adapter.exchange_id, "connect_attempt_error", {"attempt": attempt, "error": errors[-1]})
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ws = None
                if attempt < 3:
                    time.sleep(1.0 * attempt)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
        writer.write_control(adapter.exchange_id, "collector_error", {"error": errors[-1]})
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        writer.write_control(adapter.exchange_id, "collector_stop", {"errors": errors})
        writer.close()

    return WsCollectResult(
        exchange=adapter.exchange_id,
        symbols=symbols,
        output=str(output),
        events=writer.events,
        errors=errors,
        duration_sec=time.time() - started,
    )


async def _collect_exchange(
    adapter: WsAdapter,
    symbols: list[str],
    out_dir: Path,
    duration_sec: int,
    update_interval: str,
    depth_levels: int,
) -> WsCollectResult:
    return await asyncio.to_thread(
        _collect_exchange_sync,
        adapter,
        symbols,
        out_dir,
        duration_sec,
        update_interval,
        depth_levels,
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
        adapter = build_ws_adapter(exchange_id)
        tasks.append(
            _collect_exchange(
                adapter=adapter,
                symbols=symbols,
                out_dir=target_dir,
                duration_sec=duration_sec,
                update_interval=update_interval,
                depth_levels=depth_levels,
            )
        )
    if not tasks:
        raise ValueError("Нет символов для WebSocket-сбора")
    results = await asyncio.gather(*tasks)
    return {
        "started_at_utc": started_at_utc,
        "duration_sec": duration_sec,
        "update_interval": update_interval,
        "depth_levels": depth_levels,
        "results": [item.as_dict() for item in results],
        "total_events": sum(item.events for item in results),
        "errors": {item.exchange: item.errors for item in results if item.errors},
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
