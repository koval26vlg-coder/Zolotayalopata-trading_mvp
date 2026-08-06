from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pit_universe_snapshot_quality import PitQualityConfig, evaluate_pit_snapshot_quality  # noqa: E402


def _row(cycle: int, exchange: str, symbol: str, ts: str) -> dict[str, object]:
    return {
        "run_id": "pit_fixture",
        "cycle": cycle,
        "snapshot_ts": ts,
        "exchange": exchange,
        "symbol": symbol,
        "base": symbol.replace("_USDT", "").replace("USDT", ""),
        "quote": "USDT",
        "contract_type": "linear_perp",
        "status": "trading",
        "listed_now": True,
        "inactive_or_delisted": False,
        "volume_24h_quote": 1000.0,
        "bid_price": 9.99,
        "ask_price": 10.01,
        "mid_price": 10.0,
        "spread_bps": 20.0,
        "bid_size_contracts": 1000.0,
        "ask_size_contracts": 1000.0,
        "liquidity_proxy_source": "ticker_bbo_and_24h_quote_volume",
        "mark_price": 10.0,
        "index_price": 10.0,
        "funding_rate": 0.0001,
        "funding_interval_sec": 28_800,
        "funding_next_apply_ts": None,
        "contract_multiplier": 1.0,
        "minimum_order_size": 0.001,
        "maximum_order_size": 1_000_000.0,
        "price_tick": 0.001,
        "quantity_step": 0.001,
        "binance_spot_listed": False,
        "excluded_by_binance_spot": False,
        "eligible_non_binance_spot": True,
        "binance_reference_ts": ts,
        "source_endpoint": "fixture",
        "raw_status": "trading",
        "first_seen_ts": "2026-07-09T00:01:00+00:00",
        "last_seen_ts": ts,
        "missing_since_ts": None,
        "observed_now": True,
        "tombstone": False,
        "presence_state": "observed",
    }


class PitUniverseSnapshotQualityTests(unittest.TestCase):
    def _write_fixture(self, root: Path, *, final: bool = True, duplicate: bool = False) -> Path:
        snapshots = root / "snapshots.jsonl"
        cycles = root / "cycles.jsonl"
        rows = []
        cycle_rows = []
        for cycle in (1, 2):
            ts = f"2026-07-09T00:0{cycle}:00+00:00"
            rows.extend([_row(cycle, "mexc", "AAA_USDT", ts), _row(cycle, "gateio", "BBB_USDT", ts)])
            cycle_rows.append(
                {
                    "run_id": "pit_fixture",
                    "cycle": cycle,
                    "cycle_started_at_utc": ts,
                    "decision": "accepted",
                    "source_rows": 2,
                    "output_rows": 2,
                    "errors": {},
                    "successful_exchanges": ["gateio", "mexc"],
                }
            )
        if duplicate:
            rows.append(dict(rows[-1]))
        snapshots.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        cycles.write_text("\n".join(json.dumps(row) for row in cycle_rows) + "\n", encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "mode": "pit_universe_snapshot_collect",
                    "run_id": "pit_fixture",
                    "final": final,
                    "cycle_count": 2,
                    "rows_total": len(rows),
                    "errors_total": 0,
                    "snapshots_path": str(snapshots),
                    "cycles_path": str(cycles),
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_complete_two_exchange_fixture_allows_replay_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._write_fixture(Path(tmp))
            report = evaluate_pit_snapshot_quality(
                manifest,
                PitQualityConfig(min_cycles=2, min_exchanges_per_cycle=2, max_error_cycle_ratio=0.0),
            )

        self.assertTrue(report["ok"])
        self.assertTrue(report["replay_allowed"])
        self.assertEqual(report["metrics"]["rows"], 4)
        self.assertEqual(report["reasons"], [])

    def test_incomplete_manifest_blocks_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._write_fixture(Path(tmp), final=False)
            report = evaluate_pit_snapshot_quality(manifest, PitQualityConfig(min_cycles=2))

        self.assertFalse(report["replay_allowed"])
        self.assertIn("manifest_not_final", report["reasons"])

    def test_duplicate_cycle_exchange_symbol_blocks_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._write_fixture(Path(tmp), duplicate=True)
            report = evaluate_pit_snapshot_quality(manifest, PitQualityConfig(min_cycles=2))

        self.assertFalse(report["replay_allowed"])
        self.assertIn("duplicate_snapshot_keys", report["reasons"])

    def test_missing_dual_venue_bbo_quantity_blocks_quality_certification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._write_fixture(root)
            snapshots_path = root / "snapshots.jsonl"
            rows = [json.loads(line) for line in snapshots_path.read_text(encoding="utf-8").splitlines()]
            for row in rows:
                row["symbol"] = "AAA_USDT"
                row["base"] = "AAA"
                if row["exchange"] == "mexc":
                    row["ask_size_contracts"] = None
            snapshots_path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            report = evaluate_pit_snapshot_quality(
                manifest,
                PitQualityConfig(
                    min_cycles=2,
                    min_exchanges_per_cycle=2,
                    min_dual_venue_bbo_size_coverage=0.95,
                ),
            )

        self.assertFalse(report["ok"])
        self.assertIn("dual_venue_bbo_size_coverage_below_minimum", report["reasons"])
        self.assertEqual(report["metrics"]["dual_venue_bbo_size_coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
