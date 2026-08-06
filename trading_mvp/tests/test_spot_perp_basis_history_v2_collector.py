from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from spot_perp_basis_history_v2_collector import (  # noqa: E402
    archive_months_for_window,
    build_collection_tasks,
    cached_task_result,
)


def fixture_plan(asset_count: int = 8) -> dict[str, object]:
    assets = [
        {
            "canonical_asset_id": f"coingecko:asset-{index}",
            "base": f"A{index}",
            "gate_spot_symbol": f"A{index}_USDT",
            "gate_perp_symbol": f"A{index}_USDT",
        }
        for index in range(asset_count)
    ]
    return {
        "schema": "trading_mvp_gate_spot_perp_history_plan_v2",
        "final": True,
        "plan_hash": "a" * 64,
        "universe": {"selected_assets": assets},
        "sample_plan": {
            "window_start_sec": 1_765_238_400,  # 2025-12-09T00:00:00Z
            "window_end_sec": 1_784_246_400,  # 2026-07-17T00:00:00Z
        },
    }


class GateSpotPerpHistoryCollectorTests(unittest.TestCase):
    def test_archive_months_exclude_current_partial_month(self) -> None:
        self.assertEqual(
            archive_months_for_window(1_765_238_400, 1_784_246_400),
            ["202512", "202601", "202602", "202603", "202604", "202605", "202606"],
        )

    def test_task_plan_has_four_archive_series_and_four_rest_tails_per_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = build_collection_tasks(fixture_plan(), Path(tmp))

        archive = [task for task in tasks if task["source"] == "gate_archive"]
        tails = [task for task in tasks if task["source"] == "gate_rest_tail"]
        self.assertEqual(len(archive), 8 * 7 * 4)
        self.assertEqual(len(tails), 8 * 4)
        self.assertEqual(len(tasks), 8 * 32)
        self.assertTrue(any(task["series"] == "spot_trade" and "/spot/candlesticks_1h/" in task["url"] for task in archive))
        self.assertTrue(any(task["series"] == "perp_mark" and task["params"]["contract"] == "mark_A0_USDT" for task in tails))

    def test_cache_requires_matching_task_identity_and_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = build_collection_tasks(fixture_plan(1), Path(tmp))[0]
            data_path = Path(task["cache_path"])
            meta_path = Path(task["meta_path"])
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_bytes(b"payload")
            import hashlib
            import json

            meta_path.write_text(
                json.dumps(
                    {
                        "task_id": task["task_id"],
                        "status": "downloaded",
                        "data_sha256": hashlib.sha256(b"payload").hexdigest(),
                        "bytes": 7,
                    }
                ),
                encoding="utf-8",
            )

            cached = cached_task_result(task)
            self.assertIsNotNone(cached)
            self.assertEqual(cached["status"], "cache_hit")

            data_path.write_bytes(b"tampered")
            self.assertIsNone(cached_task_result(task))


if __name__ == "__main__":
    unittest.main()
