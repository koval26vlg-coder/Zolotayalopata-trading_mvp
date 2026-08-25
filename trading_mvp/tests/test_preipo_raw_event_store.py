from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_raw_event_store import RawEventStore  # noqa: E402


class PreIPORawEventStoreTests(unittest.TestCase):
    def test_store_accepts_every_active_preipo_venue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            rows = [
                {
                    "venue": venue,
                    "contract_id": f"TEST-{venue.upper()}",
                    "event_kind": "lifecycle",
                    "exchange_ts": 1_780_000_000.0 + index,
                    "received_ts": 1_780_000_010.0 + index,
                }
                for index, venue in enumerate(("okx", "gate", "bitmex", "kraken"))
            ]

            result = store.append(rows)

            self.assertEqual(result["written"], 4)
            self.assertEqual(
                {row["venue"] for row in store.iter_events()},
                {"okx", "gate", "bitmex", "kraken"},
            )

    def test_store_is_append_only_deduplicated_and_manifests_raw_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            row = {
                "venue": "okx",
                "contract_id": "SPCX-USDT-SWAP",
                "event_kind": "bbo",
                "exchange_ts": 1_780_000_123.456,
                "received_ts": 1_780_000_130.0,
                "bid": 10.0,
                "ask": 10.1,
                "bid_qty": 4.0,
                "ask_qty": 3.0,
                "sequence": 12,
            }

            first = store.append([row, row])
            self.assertEqual(first["written"], 1)
            self.assertEqual(first["duplicates"], 1)
            self.assertEqual(len(list(store.iter_events())), 1)

            manifest = store.write_manifest()
            self.assertEqual(manifest["row_count"], 1)
            self.assertEqual(manifest["schema"], "trading_mvp_preipo_raw_event_store_v1")
            self.assertTrue(manifest["events_sha256"])

    def test_stale_out_of_order_update_is_preserved_but_marked_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            accepted = {
                "venue": "gate",
                "contract_id": "UNITREE_USDT",
                "event_kind": "ticker",
                "exchange_ts": 200.0,
                "received_ts": 201.0,
                "sequence": 20,
                "last": 11.0,
            }
            stale = {**accepted, "exchange_ts": 100.0, "received_ts": 202.0, "sequence": 19, "last": 10.0}

            store.append([accepted, stale])
            rows = list(store.iter_events())
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["causal_status"], "accepted")
            self.assertEqual(rows[1]["causal_status"], "stale")

    def test_numeric_sequences_are_compared_numerically_not_lexicographically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            base = {
                "venue": "bitmex",
                "contract_id": "SPCXUSDT",
                "event_kind": "bbo",
                "exchange_ts": 1_780_000_000.0,
                "received_ts": 1_780_000_001.0,
                "bid": 10.0,
                "ask": 10.1,
            }

            store.append(
                [
                    {**base, "sequence": "9"},
                    {**base, "sequence": "10", "received_ts": 1_780_000_002.0},
                    {**base, "sequence": "8", "received_ts": 1_780_000_003.0},
                ]
            )
            rows = list(store.iter_events())

            self.assertEqual(
                [row["causal_status"] for row in rows],
                ["accepted", "accepted", "stale"],
            )

    def test_same_timestamp_without_sequence_does_not_collapse_distinct_trades(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            base = {
                "venue": "bitmex",
                "contract_id": "SPCXUSDT",
                "event_kind": "trade",
                "exchange_ts": 1_780_000_000.0,
                "received_ts": 1_780_000_001.0,
                "side": "buy",
            }

            store.append(
                [
                    {**base, "last": 10.0, "qty": 1.0, "trade_id": "a"},
                    {**base, "last": 10.1, "qty": 2.0, "trade_id": "b"},
                ]
            )

            self.assertEqual(
                [row["causal_status"] for row in store.iter_events()],
                ["accepted", "accepted"],
            )

    def test_invalid_event_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            with self.assertRaises(ValueError):
                store.append([{"venue": "okx", "contract_id": "SPCX-USDT-SWAP"}])
            self.assertFalse((root / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
