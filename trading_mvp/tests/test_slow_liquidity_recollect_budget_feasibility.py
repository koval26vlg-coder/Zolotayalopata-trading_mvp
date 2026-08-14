from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

PLAN_PATH = (
    ROOT
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
)

from listing_event_history_collector import Candle  # noqa: E402
from slow_liquidity_history_collector import (  # noqa: E402
    INTERVAL_SECONDS,
    HistoryJob,
    output_row,
)


class SlowLiquidityRecollectBudgetFeasibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def _candle_count(self, granularity: str, *, aligned: bool) -> int:
        interval_sec = INTERVAL_SECONDS[granularity]
        horizon_sec = int(self.plan["execution"]["history_days"]) * 86400
        offset = 0 if aligned else 1
        start_ts = 10 * interval_sec + offset
        end_ts = start_ts + horizon_sec
        first_ts = ((start_ts + interval_sec - 1) // interval_sec) * interval_sec
        last_ts = (end_ts // interval_sec) * interval_sec
        return ((last_ts - first_ts) // interval_sec) + 1

    def test_request_and_attempt_budgets_hold_for_aligned_and_unaligned_runs(
        self,
    ) -> None:
        execution = self.plan["execution"]
        bases = int(execution["target_bases"])
        page_sizes = execution["effective_page_sizes"]

        for aligned in (False, True):
            by_exchange: dict[str, int] = {}
            for exchange in execution["exchanges"]:
                page_size = int(page_sizes[exchange])
                requests_per_base = sum(
                    math.ceil(
                        self._candle_count(granularity, aligned=aligned)
                        / page_size
                    )
                    for granularity in execution["timeframes"]
                )
                by_exchange[exchange] = bases * requests_per_base

            with self.subTest(aligned=aligned):
                self.assertEqual(
                    by_exchange,
                    execution["logical_requests_by_exchange"],
                )
                self.assertEqual(
                    sum(by_exchange.values()), execution["logical_requests"]
                )
                self.assertEqual(
                    execution["logical_requests"]
                    * (int(execution["max_retries"]) + 1),
                    execution["maximum_http_attempts"],
                )

    def test_quality_thresholds_match_at_least_eight_complete_bases(self) -> None:
        quality = self.plan["data_quality_after_success"]["thresholds"]
        execution = self.plan["execution"]
        rows_per_base = len(execution["exchanges"]) * sum(
            self._candle_count(granularity, aligned=False)
            for granularity in execution["timeframes"]
        )
        min_rows = int(quality["min_ok_rows"])
        required_bases = int(quality["min_two_exchange_full_coverage_1h4h_bases"])
        total_slots = (
            int(execution["target_bases"])
            * len(execution["exchanges"])
            * len(execution["timeframes"])
        )

        self.assertEqual(rows_per_base, 3360)
        self.assertLess((required_bases - 1) * rows_per_base, min_rows)
        self.assertGreaterEqual(required_bases * rows_per_base, min_rows)
        self.assertEqual(total_slots, 36)
        self.assertLessEqual(
            int(quality["min_ok_market_granularity_slots"]), total_slots
        )
        self.assertLessEqual(int(quality["min_ok_bases"]), required_bases)
        self.assertEqual(int(quality["min_ok_exchanges"]), 2)

    def test_output_cap_has_at_least_25_mb_success_path_headroom(self) -> None:
        execution = self.plan["execution"]
        max_rows = int(execution["target_bases"]) * len(
            execution["exchanges"]
        ) * sum(
            self._candle_count(granularity, aligned=True)
            for granularity in execution["timeframes"]
        )
        conservative_bytes_per_success_row = 2048
        conservative_output_bytes = max_rows * conservative_bytes_per_success_row
        output_cap = int(execution["hard_output_cap_bytes"])

        job = HistoryJob(
            exchange="gateio",
            symbol="STETH_USDT",
            base="STETH",
            quote="USDT",
            granularity="4h",
            start_ts=1_786_000_000,
            end_ts=1_790_838_400,
        )
        largest_finite = sys.float_info.max
        row = output_row(
            job,
            candle=Candle(
                ts=1_790_827_200,
                open=-largest_finite,
                high=largest_finite,
                low=-largest_finite,
                close=largest_finite,
                volume=largest_finite,
                quote_volume=largest_finite,
                trade_count=2**63 - 1,
            ),
            data_status="ok",
        )
        serialized_size = len(
            (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        )

        self.assertEqual(max_rows, 30276)
        self.assertLess(serialized_size, conservative_bytes_per_success_row)
        self.assertLessEqual(conservative_output_bytes, output_cap - 25_000_000)


if __name__ == "__main__":
    unittest.main()
