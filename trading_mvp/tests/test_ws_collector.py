from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ws_collector  # noqa: E402
from ws_collector import GateWsAdapter, MexcWsAdapter, RawEventWriter, split_ws_symbols_for_connections  # noqa: E402


class FakeClock:
    def __init__(self, current: float = 1_000.0) -> None:
        self.current = current

    def time(self) -> float:
        return self.current

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += max(0.0, seconds)


class FakeWebSocketTimeout(Exception):
    pass


def _gate_bbo(symbol: str = "HYPE_USDT") -> str:
    return json.dumps(
        {
            "time_ms": 1_780_506_001_383,
            "channel": "spot.book_ticker",
            "event": "update",
            "result": {
                "s": symbol,
                "b": "72.788",
                "B": "4.06",
                "a": "72.794",
                "A": "0.95",
                "u": 1,
            },
        }
    )


class FakeConnection:
    def __init__(
        self,
        clock: FakeClock,
        *,
        fail_first_recv: bool = False,
        message_factory: object = _gate_bbo,
    ) -> None:
        self.clock = clock
        self.fail_first_recv = fail_first_recv
        self.message_factory = message_factory
        self.recv_count = 0
        self.closed = False

    def settimeout(self, _seconds: float) -> None:
        return None

    def send(self, _message: str) -> None:
        return None

    def recv(self) -> str:
        if self.fail_first_recv and self.recv_count == 0:
            self.recv_count += 1
            raise ConnectionResetError("simulated reset")
        self.recv_count += 1
        self.clock.current += 1.0
        if self.message_factory is None:
            raise FakeWebSocketTimeout("synthetic timeout")
        return self.message_factory()  # type: ignore[operator]

    def close(self) -> None:
        self.closed = True


class FakeWebSocketModule:
    WebSocketTimeoutException = FakeWebSocketTimeout

    def __init__(
        self,
        clock: FakeClock,
        *,
        fail_first_connection: bool = True,
        message_factory: object = _gate_bbo,
    ) -> None:
        self.clock = clock
        self.fail_first_connection = fail_first_connection
        self.message_factory = message_factory
        self.connections: list[FakeConnection] = []

    def create_connection(self, _url: str, timeout: int = 10) -> FakeConnection:
        del timeout
        connection = FakeConnection(
            self.clock,
            fail_first_recv=(
                self.fail_first_connection and len(self.connections) == 0
            ),
            message_factory=self.message_factory,
        )
        self.connections.append(connection)
        return connection


class WsCollectorTests(unittest.TestCase):
    def test_raw_event_writer_encodes_binary_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "events.jsonl"
            writer = RawEventWriter(out, flush_every=1)
            writer.write_message(
                MexcWsAdapter(),
                b"\x08\x01\x12\x03abc",
                expected_symbols=["HYPEUSDT"],
                expected_channels_by_symbol={"HYPEUSDT": set()},
            )
            writer.close()

            row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["exchange"], "mexc")
            self.assertEqual(row["event_type"], "protobuf")
            self.assertEqual(row["payload"]["encoding"], "base64")
            self.assertEqual(row["payload"]["byte_length"], 7)

    def test_gate_subscriptions_include_trades_book_ticker_and_depth(self) -> None:
        messages = GateWsAdapter().subscription_messages(["HYPE_USDT"], update_interval="100ms")
        channels = [item["channel"] for item in messages]
        self.assertEqual(channels, ["spot.trades", "spot.book_ticker", "spot.order_book_update"])
        self.assertEqual(messages[0]["payload"], ["HYPE_USDT"])
        self.assertEqual(messages[2]["payload"], ["HYPE_USDT", "100ms"])

    def test_mexc_subscription_uses_three_channels_per_symbol(self) -> None:
        messages = MexcWsAdapter().subscription_messages(["HYPEUSDT", "XMRUSDT"])
        params = messages[0]["params"]
        self.assertEqual(len(params), 6)
        self.assertIn("spot@public.aggre.bookTicker.v3.api.pb@100ms@HYPEUSDT", params)
        self.assertIn("spot@public.aggre.deals.v3.api.pb@100ms@HYPEUSDT", params)
        self.assertIn("spot@public.limit.depth.v3.api.pb@HYPEUSDT@20", params)

    def test_mexc_rejects_more_than_connection_channel_limit(self) -> None:
        symbols = [f"COIN{i}USDT" for i in range(11)]
        with self.assertRaises(ValueError):
            MexcWsAdapter().subscription_messages(symbols)

    def test_mexc_symbols_are_chunked_before_hitting_channel_limit(self) -> None:
        symbols = [f"COIN{i}USDT" for i in range(16)]
        chunks = split_ws_symbols_for_connections(MexcWsAdapter(), symbols)

        self.assertEqual([len(chunk) for chunk in chunks], [10, 6])
        for chunk in chunks:
            params = MexcWsAdapter().subscription_messages(chunk)[0]["params"]
            self.assertLessEqual(len(params), 30)

    def test_gate_symbols_stay_on_single_connection(self) -> None:
        symbols = [f"COIN{i}_USDT" for i in range(16)]
        chunks = split_ws_symbols_for_connections(GateWsAdapter(), symbols)

        self.assertEqual(chunks, [symbols])

    def test_collect_reconnects_until_duration_instead_of_stopping_after_first_reset(self) -> None:
        clock = FakeClock()
        fake_websocket = FakeWebSocketModule(clock)
        original_time = ws_collector.time
        original_websocket = sys.modules.get("websocket")
        sys.modules["websocket"] = types.SimpleNamespace(
            create_connection=fake_websocket.create_connection,
            WebSocketTimeoutException=FakeWebSocketTimeout,
        )
        ws_collector.time = clock  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = ws_collector._collect_exchange_sync(  # noqa: SLF001
                    adapter=GateWsAdapter(),
                    symbols=["HYPE_USDT"],
                    out_dir=Path(tmp),
                    duration_sec=3,
                    update_interval="100ms",
                    depth_levels=20,
                )
                rows = [json.loads(line) for line in Path(result.output).read_text(encoding="utf-8").splitlines()]
        finally:
            ws_collector.time = original_time  # type: ignore[assignment]
            if original_websocket is None:
                sys.modules.pop("websocket", None)
            else:
                sys.modules["websocket"] = original_websocket

        self.assertTrue(result.duration_completed)
        self.assertTrue(result.liveness_clean)
        self.assertFalse(result.quality_eligible)
        self.assertFalse(result.completed)
        self.assertEqual(result.stop_reason, "duration_sec")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.errors), 1)
        self.assertGreaterEqual(result.duration_sec, 3)
        self.assertEqual(len(fake_websocket.connections), 2)
        stop_rows = [row for row in rows if row["event_type"] == "collector_stop"]
        self.assertEqual(len(stop_rows), 1)
        stop_payload = stop_rows[0]["payload"]["data"]
        self.assertFalse(stop_payload["completed"])
        self.assertTrue(stop_payload["duration_completed"])
        self.assertFalse(stop_payload["quality_eligible"])
        self.assertEqual(stop_payload["stop_reason"], "duration_sec")
        self.assertEqual(stop_payload["attempts"], 2)

    def test_collect_manifest_marks_final_only_after_duration_completion(self) -> None:
        clock = FakeClock()
        fake_websocket = FakeWebSocketModule(clock, fail_first_connection=False)
        original_time = ws_collector.time
        original_websocket = sys.modules.get("websocket")
        sys.modules["websocket"] = types.SimpleNamespace(
            create_connection=fake_websocket.create_connection,
            WebSocketTimeoutException=FakeWebSocketTimeout,
        )
        ws_collector.time = clock  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                manifest = ws_collector.collect_ws_markets(
                    {"gateio": ["HYPE_USDT"]},
                    out_dir=Path(tmp),
                    duration_sec=3,
                    update_interval="100ms",
                    depth_levels=20,
                )
        finally:
            ws_collector.time = original_time  # type: ignore[assignment]
            if original_websocket is None:
                sys.modules.pop("websocket", None)
            else:
                sys.modules["websocket"] = original_websocket

        self.assertTrue(manifest["completed"])
        self.assertTrue(manifest["duration_completed"])
        self.assertTrue(manifest["liveness_clean"])
        self.assertTrue(manifest["quality_eligible"])
        self.assertTrue(manifest["final"])
        self.assertEqual(manifest["stop_condition"], "duration_sec")
        self.assertEqual(manifest["requested_duration_sec"], 3)
        self.assertGreaterEqual(manifest["actual_duration_sec"], 3)
        self.assertEqual(manifest["results"][0]["attempts"], 1)
        self.assertEqual(manifest["results"][0]["stop_reason"], "duration_sec")

    def test_silent_socket_reconnects_and_marks_segment_dirty(self) -> None:
        result = self._collect_with_factory(None, duration_sec=5, silence_sec=2)

        self.assertTrue(result.duration_completed)
        self.assertFalse(result.liveness_clean)
        self.assertFalse(result.quality_eligible)
        self.assertGreaterEqual(result.market_silence_events, 1)
        self.assertGreaterEqual(result.reconnect_attempts, 1)

    def test_control_only_socket_does_not_refresh_market_liveness(self) -> None:
        def control_message() -> str:
            return json.dumps(
                {"time": 1, "channel": "spot.book_ticker", "event": "subscribe"}
            )

        result = self._collect_with_factory(
            control_message,
            duration_sec=5,
            silence_sec=2,
        )

        self.assertEqual(result.market_envelope_rows, 0)
        self.assertGreater(result.control_rows, 0)
        self.assertGreaterEqual(result.market_silence_events, 1)
        self.assertFalse(result.liveness_clean)

    def test_foreign_symbol_does_not_refresh_market_liveness(self) -> None:
        result = self._collect_with_factory(
            lambda: _gate_bbo("OTHER_USDT"),
            duration_sec=5,
            silence_sec=2,
        )

        self.assertEqual(result.market_envelope_rows, 0)
        self.assertGreater(result.unclassified_messages, 0)
        self.assertGreaterEqual(result.market_silence_events, 1)
        self.assertFalse(result.liveness_clean)

    def _collect_with_factory(
        self,
        message_factory: object,
        *,
        duration_sec: int,
        silence_sec: float,
    ) -> ws_collector.WsCollectResult:
        clock = FakeClock()
        fake_websocket = FakeWebSocketModule(
            clock,
            fail_first_connection=False,
            message_factory=message_factory,
        )
        original_time = ws_collector.time
        original_silence = ws_collector.MARKET_SILENCE_RECONNECT_SEC
        original_websocket = sys.modules.get("websocket")
        sys.modules["websocket"] = types.SimpleNamespace(
            create_connection=fake_websocket.create_connection,
            WebSocketTimeoutException=FakeWebSocketTimeout,
        )
        ws_collector.time = clock  # type: ignore[assignment]
        ws_collector.MARKET_SILENCE_RECONNECT_SEC = silence_sec
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return ws_collector._collect_exchange_sync(  # noqa: SLF001
                    adapter=GateWsAdapter(),
                    symbols=["HYPE_USDT"],
                    out_dir=Path(tmp),
                    duration_sec=duration_sec,
                    update_interval="100ms",
                    depth_levels=20,
                )
        finally:
            ws_collector.time = original_time  # type: ignore[assignment]
            ws_collector.MARKET_SILENCE_RECONNECT_SEC = original_silence
            if original_websocket is None:
                sys.modules.pop("websocket", None)
            else:
                sys.modules["websocket"] = original_websocket


if __name__ == "__main__":
    unittest.main()
