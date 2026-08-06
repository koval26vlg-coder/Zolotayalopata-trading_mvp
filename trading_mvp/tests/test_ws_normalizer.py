from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ws_normalizer import (  # noqa: E402
    classify_ws_row,
    decode_mexc_wrapper,
    expected_market_channels,
    normalize_ws_files,
    normalize_ws_row,
)


MEXC_BOOK_TICKER_B64 = (
    "CjVzcG90QHB1YmxpYy5hZ2dyZS5ib29rVGlja2VyLnYzLmFwaS5wYkAxMDBtc0BIWVBFVVNEVBoISFlQRVVTRFQw"
    "+t6t8+gz2hMtCgU3Mi4yORIENy4wMRoFNzIuMzQiBDgyLjEqCjEzMjAwNDMzNTYwyt6t8+gz"
)

MEXC_DEPTH_B64 = (
    "Ci1zcG90QHB1YmxpYy5saW1pdC5kZXB0aC52My5hcGkucGJASFlQRVVTRFRAMjAaCEhZUEVVU0RUMIzirfPoM/oSqQUKDgoFNzIuMzQSBTgyLjEwCg4KBTcyLjM2EgU4OS42MQoOCgU3Mi4zOBIFODMuODMKDgoFNzIuMzkSBTgwLjI4Cg4KBTcyLjQxEgU4Mi4xMAoOCgU3Mi40MhIFODIuMjEKDgoFNzIuNDYSBTgyLjEwCg4KBTcyLjQ3EgU4MC40OQoPCgU3Mi40OBIGMTQ2LjA4Cg0KBTcyLjUxEgQwLjA2Cg8KBTcyLjUzEgYxNDUuODQKDQoFNzIuNTUSBDAuNjQKDQoFNzIuNTYSBDAuMzMKDQoFNzIuNTkSBDAuMDIKDQoFNzIuNjASBDAuMDIKDQoFNzIuNjESBDAuMDIKDgoFNzIuNjISBTMyLjE1Cg0KBTcyLjYzEgQwLjUzCg4KBTcyLjY0EgUyNC4zMQoOCgU3Mi42NRIFMjQuNDASDQoFNzIuMjkSBDcuMDESDgoFNzIuMjgSBTEyLjYzEg4KBTcyLjI3EgUxNi4xMxINCgU3Mi4yNhIEOC44NBIOCgU3Mi4yNRIFODkuMTESDgoFNzIuMjQSBTgyLjMyEg8KBTcyLjIyEgYxNDcuODISDQoFNzIuMjASBDAuNjkSDwoFNzIuMTkSBjE3Ni4wNRINCgU3Mi4xOBIEMS4wNBIOCgU3Mi4xNxIFMjAuMDASDQoFNzIuMTYSBDIuMDASDgoFNzIuMTUSBTM2LjU1Eg0KBTcyLjE0EgQyLjAyEg4KBTcyLjEzEgUzMC41NhINCgU3Mi4xMhIEMS41MBIOCgU3Mi4xMRIFNTkuNjMSDQoFNzIuMTASBDIuMDISDQoFNzIuMDkSBDAuMDISDQoFNzIuMDgSBDIuMDIaIXNwb3RAcHVibGljLmxpbWl0LmRlcHRoLnYzLmFwaS5wYiIKMTMyMDA0MzM3Myjv4a3z6DM="
)


class WsNormalizerTests(unittest.TestCase):
    @staticmethod
    def _gate_bbo(symbol: str = "HYPE_USDT") -> dict:
        return {
            "recv_ts": 1.0,
            "exchange": "gateio",
            "channel": "spot.book_ticker",
            "symbol": symbol,
            "payload": {
                "encoding": "json",
                "data": {
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
                },
            },
        }

    def test_decode_mexc_aggre_book_ticker(self) -> None:
        decoded = decode_mexc_wrapper(base64.b64decode(MEXC_BOOK_TICKER_B64))
        self.assertEqual(decoded["symbol"], "HYPEUSDT")
        self.assertEqual(decoded["body_type"], "aggre_book_ticker")
        self.assertEqual(decoded["body"]["bid_price"], 72.29)
        self.assertEqual(decoded["body"]["ask_qty"], 82.1)

    def test_decode_mexc_limit_depth(self) -> None:
        decoded = decode_mexc_wrapper(base64.b64decode(MEXC_DEPTH_B64))
        self.assertEqual(decoded["symbol"], "HYPEUSDT")
        self.assertEqual(decoded["body_type"], "limit_depth")
        self.assertGreater(len(decoded["body"]["asks"]), 10)
        self.assertGreater(len(decoded["body"]["bids"]), 10)

    def test_normalize_gate_trade(self) -> None:
        row = {
            "recv_ts": 1.0,
            "exchange": "gateio",
            "channel": "spot.trades",
            "symbol": "HYPE_USDT",
            "payload": {
                "encoding": "json",
                "data": {
                    "time_ms": 1780506001864,
                    "channel": "spot.trades",
                    "event": "update",
                    "result": {
                        "id": 24708043,
                        "create_time_ms": "1780506001864.098000",
                        "side": "buy",
                        "currency_pair": "HYPE_USDT",
                        "amount": "0.95",
                        "price": "72.794",
                    },
                },
            },
        }
        events = normalize_ws_row(row)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_kind"], "trade")
        self.assertEqual(events[0]["price"], 72.794)
        self.assertEqual(events[0]["qty"], 0.95)
        self.assertEqual(events[0]["side"], "buy")

    def test_normalize_file_writes_common_rows(self) -> None:
        mexc_row = {
            "recv_ts": 1.0,
            "exchange": "mexc",
            "event_type": "protobuf",
            "channel": None,
            "symbol": None,
            "payload": {"encoding": "base64", "data": MEXC_BOOK_TICKER_B64},
        }
        gate_row = {
            "recv_ts": 2.0,
            "exchange": "gateio",
            "channel": "spot.book_ticker",
            "symbol": "HYPE_USDT",
            "payload": {
                "encoding": "json",
                "data": {
                    "time_ms": 1780506001383,
                    "channel": "spot.book_ticker",
                    "event": "update",
                    "result": {"s": "HYPE_USDT", "b": "72.788", "B": "4.06", "a": "72.794", "A": "0.95", "u": 1},
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "raw.jsonl"
            out = Path(tmp) / "normalized.jsonl"
            src.write_text(json.dumps(mexc_row) + "\n" + json.dumps(gate_row) + "\n", encoding="utf-8")
            result = normalize_ws_files(src, out)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(result["normalized_rows"], 2)
            self.assertEqual(result["by_kind"], {"bbo": 2})
            self.assertEqual(rows[0]["exchange"], "mexc")
            self.assertEqual(rows[1]["exchange"], "gateio")

    def test_classifier_accepts_only_exact_healthy_gate_market(self) -> None:
        channels = {
            "HYPE_USDT": set(
                expected_market_channels("gateio", "HYPE_USDT").values()
            )
        }
        healthy = classify_ws_row(
            self._gate_bbo(),
            expected_exchange="gateio",
            expected_symbols=["HYPE_USDT"],
            expected_channels_by_symbol=channels,
        )
        foreign = classify_ws_row(
            self._gate_bbo("OTHER_USDT"),
            expected_exchange="gateio",
            expected_symbols=["HYPE_USDT"],
            expected_channels_by_symbol=channels,
        )

        self.assertEqual(healthy["classification"], "market")
        self.assertTrue(healthy["qualifies_market_liveness"])
        self.assertEqual(foreign["classification"], "unclassified")
        self.assertFalse(foreign["qualifies_market_liveness"])

    def test_classifier_rejects_malformed_gate_update(self) -> None:
        row = self._gate_bbo()
        row["payload"]["data"]["result"]["b"] = "0"
        result = classify_ws_row(
            row,
            expected_exchange="gateio",
            expected_symbols=["HYPE_USDT"],
        )

        self.assertEqual(result["classification"], "unclassified")
        self.assertIn("market_structure", result["reason"])

    def test_classifier_recognizes_control_without_market_liveness(self) -> None:
        row = {
            "recv_ts": 1.0,
            "exchange": "gateio",
            "event_type": "subscribe",
            "channel": "spot.book_ticker",
            "symbol": None,
            "payload": {
                "encoding": "json",
                "data": {
                    "channel": "spot.book_ticker",
                    "event": "subscribe",
                    "result": {"status": "success"},
                },
            },
        }
        result = classify_ws_row(row, expected_exchange="gateio")

        self.assertEqual(result["classification"], "control")
        self.assertFalse(result["qualifies_market_liveness"])

    def test_classifier_rejects_mexc_wrapper_without_matching_body(self) -> None:
        def varint(value: int) -> bytes:
            out = bytearray()
            while True:
                byte = value & 0x7F
                value >>= 7
                out.append(byte | (0x80 if value else 0))
                if not value:
                    return bytes(out)

        def text_field(number: int, value: str) -> bytes:
            body = value.encode("utf-8")
            return varint((number << 3) | 2) + varint(len(body)) + body

        channel = "spot@public.aggre.bookTicker.v3.api.pb@100ms@HYPEUSDT"
        raw = text_field(1, channel) + text_field(3, "HYPEUSDT")
        row = {
            "recv_ts": 1.0,
            "exchange": "mexc",
            "event_type": "protobuf",
            "channel": None,
            "symbol": None,
            "payload": {
                "encoding": "base64",
                "byte_length": len(raw),
                "data": base64.b64encode(raw).decode("ascii"),
            },
        }
        result = classify_ws_row(
            row,
            expected_exchange="mexc",
            expected_symbols=["HYPEUSDT"],
            expected_channels_by_symbol={"HYPEUSDT": {channel}},
        )

        self.assertEqual(result["classification"], "unclassified")
        self.assertFalse(result["qualifies_market_liveness"])


if __name__ == "__main__":
    unittest.main()
