from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_raw_event_store import RawEventStore  # noqa: E402


class PreIPORawEventStoreTests(unittest.TestCase):
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

    def test_invalid_event_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RawEventStore(root / "events.jsonl", root / "manifest.json")
            with self.assertRaises(ValueError):
                store.append([{"venue": "okx", "contract_id": "SPCX-USDT-SWAP"}])
            self.assertFalse((root / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
