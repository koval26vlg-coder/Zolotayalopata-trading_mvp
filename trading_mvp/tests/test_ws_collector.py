from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ws_collector import GateWsAdapter, MexcWsAdapter, RawEventWriter  # noqa: E402


class WsCollectorTests(unittest.TestCase):
    def test_raw_event_writer_encodes_binary_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "events.jsonl"
            writer = RawEventWriter(out, flush_every=1)
            writer.write_message(MexcWsAdapter(), b"\x08\x01\x12\x03abc")
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


if __name__ == "__main__":
    unittest.main()
