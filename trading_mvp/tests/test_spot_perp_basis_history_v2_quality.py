from __future__ import annotations

import sys
import hashlib
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from spot_perp_basis_history_v2_quality import (  # noqa: E402
    assess_asset_quality,
    merge_rows_strict,
    parse_rest_candles,
    verify_task_cache,
)


class GateSpotPerpHistoryQualityTests(unittest.TestCase):
    def test_rest_candle_parser_supports_spot_arrays_and_futures_objects(self) -> None:
        spot = parse_rest_candles(
            [["3600", "1000", "101", "102", "99", "100", "10"]],
            market_type="spot",
        )
        futures = parse_rest_candles(
            [{"t": 3600, "v": 50, "c": "101", "h": "102", "l": "99", "o": "100", "sum": "5050"}],
            market_type="perp",
        )

        self.assertEqual(spot[0]["open"], 100.0)
        self.assertEqual(spot[0]["volume_quote"], 1000.0)
        self.assertEqual(spot[0]["volume_base"], 10.0)
        self.assertEqual(futures[0]["volume_raw"], 50.0)
        self.assertEqual(futures[0]["volume_quote"], 5050.0)

    def test_strict_merge_rejects_conflicting_duplicate_timestamp(self) -> None:
        row = {"ts": 0, "open": 1, "high": 1, "low": 1, "close": 1}
        self.assertEqual(merge_rows_strict([[row], [dict(row)]]), [row])
        conflict = {**row, "close": 2}
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            merge_rows_strict([[row], [conflict]])

    def test_task_cache_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.json"
            path.write_bytes(b"[]")
            task = {
                "task_id": "task-1",
                "cache_path": str(path),
                "data_sha256": hashlib.sha256(b"[]").hexdigest(),
            }
            self.assertEqual(verify_task_cache(task), path)
            task["data_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "cache hash mismatch"):
                verify_task_cache(task)

    def test_quality_uses_train_only_liquidity_and_accepts_complete_fixture(self) -> None:
        start = 0
        end = 48 * 3600
        timestamps = range(start, end, 3600)
        spot = [
            {
                "ts": ts,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume_base": 1_000.0,
                "volume_quote": 100_000.0,
            }
            for ts in timestamps
        ]
        perp = [
            {
                "ts": ts,
                "open": 101.0,
                "high": 102.0,
                "low": 100.0,
                "close": 101.0,
                "volume_raw": 1_000.0,
                "volume_quote": 101_000.0,
            }
            for ts in timestamps
        ]
        mark = [
            {"ts": ts, "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0}
            for ts in timestamps
        ]
        funding = [{"ts": ts, "funding_rate": 0.0001} for ts in range(start, end, 8 * 3600)]

        quality = assess_asset_quality(
            spot_rows=spot,
            perp_rows=perp,
            mark_rows=mark,
            funding_rows=funding,
            start_sec=start,
            end_sec=end,
            liquidity_start_sec=start,
            liquidity_end_sec=end,
            contract_multiplier=1.0,
            minimum_median_seven_day_quote_volume=1_000_000.0,
            liquidity_window_days=1,
        )

        self.assertTrue(quality["accepted"])
        self.assertEqual(quality["aligned_rows"], 48)
        self.assertGreater(quality["minimum_median_rolling_quote_volume"], 1_000_000.0)
        self.assertTrue(quality["funding"]["accepted"])


if __name__ == "__main__":
    unittest.main()
