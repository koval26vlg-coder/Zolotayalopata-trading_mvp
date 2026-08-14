from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from listing_event_history_collector import Candle  # noqa: E402
from slow_liquidity_history_collector import (  # noqa: E402
    INTERVAL_SECONDS,
    HistoryJob,
    fetch_range,
)


class EpochAlignedCappedClient:
    def __init__(self, *, exchange: str, page_size: int) -> None:
        self.exchange = exchange
        self.max_candles_per_request = page_size
        self.calls: list[tuple[int, int, int]] = []

    def fetch_ohlcv(
        self,
        symbol: str,
        granularity: str,
        start_ts: int,
        end_ts: int,
        limit: int,
    ) -> list[Candle]:
        del symbol
        self.calls.append((start_ts, end_ts, limit))
        interval_sec = INTERVAL_SECONDS[granularity]
        timestamp = math.ceil(start_ts / interval_sec) * interval_sec
        candles: list[Candle] = []
        while timestamp <= end_ts and len(candles) < min(
            limit, self.max_candles_per_request
        ):
            candles.append(
                Candle(
                    ts=timestamp,
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    volume=1.0,
                    quote_volume=1.0,
                )
            )
            timestamp += interval_sec
        return candles


class SlowLiquidityAlignmentMatrixTests(unittest.TestCase):
    def test_56_day_ranges_are_exact_for_both_venues_and_timeframes(self) -> None:
        horizon_sec = 56 * 24 * 60 * 60
        venue_cases = (
            ("mexc", "EDGEUSDT", 500),
            ("gateio", "EDGE_USDT", 1000),
        )

        for exchange, symbol, page_size in venue_cases:
            for granularity in ("1h", "4h"):
                interval_sec = INTERVAL_SECONDS[granularity]
                offsets = (0, 1, 123, interval_sec // 2, interval_sec - 1)
                for offset in offsets:
                    with self.subTest(
                        exchange=exchange,
                        granularity=granularity,
                        offset=offset,
                    ):
                        start_ts = 10 * interval_sec + offset
                        end_ts = start_ts + horizon_sec
                        first_ts = (
                            (start_ts + interval_sec - 1) // interval_sec
                        ) * interval_sec
                        last_ts = (end_ts // interval_sec) * interval_sec
                        expected = list(
                            range(first_ts, last_ts + 1, interval_sec)
                        )
                        client = EpochAlignedCappedClient(
                            exchange=exchange,
                            page_size=page_size,
                        )

                        candles, requests_made = fetch_range(
                            client=client,
                            job=HistoryJob(
                                exchange=exchange,
                                symbol=symbol,
                                base="EDGE",
                                quote="USDT",
                                granularity=granularity,
                                start_ts=start_ts,
                                end_ts=end_ts,
                            ),
                            candles_per_request=1000,
                            sleep_sec=0,
                        )

                        actual = [candle.ts for candle in candles]
                        expected_requests = (
                            len(expected) + page_size - 1
                        ) // page_size
                        self.assertEqual(actual, expected)
                        self.assertEqual(len(actual), len(set(actual)))
                        self.assertEqual(requests_made, expected_requests)
                        self.assertEqual(len(client.calls), expected_requests)

                        for index, (page_start, page_end, limit) in enumerate(
                            client.calls
                        ):
                            self.assertEqual(page_start % interval_sec, 0)
                            self.assertEqual(page_end % interval_sec, 0)
                            self.assertEqual(limit, page_size)
                            self.assertLessEqual(
                                page_end - page_start,
                                (page_size - 1) * interval_sec,
                            )
                            if index:
                                previous_end = client.calls[index - 1][1]
                                self.assertEqual(
                                    page_start, previous_end + interval_sec
                                )

    def test_range_without_a_complete_candle_makes_no_request(self) -> None:
        interval_sec = INTERVAL_SECONDS["1h"]
        client = EpochAlignedCappedClient(exchange="mexc", page_size=500)

        candles, requests_made = fetch_range(
            client=client,
            job=HistoryJob(
                exchange="mexc",
                symbol="EDGEUSDT",
                base="EDGE",
                quote="USDT",
                granularity="1h",
                start_ts=10 * interval_sec + 1,
                end_ts=11 * interval_sec - 1,
            ),
            candles_per_request=1000,
            sleep_sec=0,
        )

        self.assertEqual(candles, [])
        self.assertEqual(requests_made, 0)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
