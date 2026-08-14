from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLAN_PATH = (
    ROOT.parents[1]
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
)

from listing_event_history_collector import (  # noqa: E402
    BitgetSpotOhlcvClient,
    Candle,
    GateSpotOhlcvClient,
    MexcSpotOhlcvClient,
    fetch_window,
)
from slow_liquidity_history_collector import (  # noqa: E402
    INTERVAL_SECONDS,
    HistoryJob,
    UniverseAsset,
    build_initial_manifest,
    build_jobs,
    fetch_range,
)


class CappedMexcClient:
    exchange = "mexc"
    max_candles_per_request = 500

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    def fetch_ohlcv(
        self,
        symbol: str,
        granularity: str,
        start_ts: int,
        end_ts: int,
        limit: int,
    ) -> list[Candle]:
        self.calls.append((start_ts, end_ts, limit))
        interval_sec = {"1h": 3600, "4h": 4 * 3600}[granularity]
        count = min(limit, self.max_candles_per_request)
        candles: list[Candle] = []
        timestamp = start_ts
        while timestamp <= end_ts and len(candles) < count:
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


class CappedGateClient(CappedMexcClient):
    exchange = "gateio"
    max_candles_per_request = 1000


class EpochAlignedCappedClient(CappedMexcClient):
    def fetch_ohlcv(
        self,
        symbol: str,
        granularity: str,
        start_ts: int,
        end_ts: int,
        limit: int,
    ) -> list[Candle]:
        self.calls.append((start_ts, end_ts, limit))
        interval_sec = INTERVAL_SECONDS[granularity]
        timestamp = ((start_ts + interval_sec - 1) // interval_sec) * interval_sec
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


class NoisyEpochAlignedCappedClient(EpochAlignedCappedClient):
    def fetch_ohlcv(
        self,
        symbol: str,
        granularity: str,
        start_ts: int,
        end_ts: int,
        limit: int,
    ) -> list[Candle]:
        candles = super().fetch_ohlcv(
            symbol, granularity, start_ts, end_ts, limit
        )
        interval_sec = INTERVAL_SECONDS[granularity]
        return candles + [
            Candle(
                ts=start_ts + 1,
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1.0,
                quote_volume=1.0,
            ),
            Candle(
                ts=end_ts + interval_sec,
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1.0,
                quote_volume=1.0,
            ),
        ]


class EmptyCappedClient:
    def __init__(self, max_candles_per_request: int) -> None:
        self.max_candles_per_request = max_candles_per_request
        self.calls = 0

    def fetch_ohlcv(
        self,
        symbol: str,
        granularity: str,
        start_ts: int,
        end_ts: int,
        limit: int,
    ) -> list[Candle]:
        self.calls += 1
        return []


class AlwaysTimeoutSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise requests.Timeout("synthetic timeout")


class SlowLiquidityHistoryCollectorTests(unittest.TestCase):
    def test_manifest_binds_exact_history_anchor(self) -> None:
        asset = UniverseAsset(rank=1, name="Edge", base="EDGE", coin_id="edge")
        jobs = build_jobs(
            [asset],
            exchanges=["mexc"],
            granularities=["1h"],
            quote="USDT",
            start_ts=1_800_123,
            end_ts=1_900_123,
        )

        manifest = build_initial_manifest(
            run_id="synthetic",
            universe_path=Path("universe.csv"),
            output_jsonl=Path("ohlcv.jsonl"),
            manifest_path=Path("manifest.json"),
            assets=[asset],
            jobs=jobs,
            exchanges=["mexc"],
            granularities=["1h"],
            history_days=56,
            history_anchor_ts=1_900_123,
            candles_per_request=500,
            approval_text="synthetic",
            resumed_existing_stats={},
        )

        self.assertEqual(
            manifest["quality_contract_version"],
            "slow_liquidity_history_exact_v2",
        )
        self.assertEqual(manifest["history_anchor_ts"], 1_900_123)
        self.assertEqual(manifest["history_anchor_iso"], "1970-01-22T23:48:43Z")

    def test_build_jobs_aligns_wall_clock_history_bounds_for_quality(self) -> None:
        history_days = 56
        raw_start = 1_800_123
        raw_end = raw_start + history_days * 86_400
        jobs = build_jobs(
            [UniverseAsset(rank=1, name="Edge", base="EDGE", coin_id="edge")],
            exchanges=["mexc", "gateio"],
            granularities=["1h", "4h"],
            quote="USDT",
            start_ts=raw_start,
            end_ts=raw_end,
        )

        self.assertEqual(len(jobs), 4)
        for job in jobs:
            interval = INTERVAL_SECONDS[job.granularity]
            expected_candles = ((job.end_ts - job.start_ts) // interval) + 1
            minimum_candles = (history_days * 86_400) // interval
            self.assertEqual(job.start_ts % interval, 0)
            self.assertEqual(job.end_ts % interval, 0)
            self.assertGreaterEqual(job.start_ts, raw_start)
            self.assertLessEqual(job.end_ts, raw_end)
            self.assertIn(expected_candles, (minimum_candles, minimum_candles + 1))

    def test_frozen_scope_has_exact_request_and_attempt_caps(self) -> None:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        execution = plan["execution"]
        end_ts = int(execution["history_days"]) * 24 * 60 * 60
        clients = {
            "mexc": EmptyCappedClient(
                int(execution["effective_page_sizes"]["mexc"])
            ),
            "gateio": EmptyCappedClient(
                int(execution["effective_page_sizes"]["gateio"])
            ),
        }
        logical_requests_by_exchange = {"mexc": 0, "gateio": 0}

        for base in plan["universe"]["bases"]:
            for exchange in execution["exchanges"]:
                for granularity in execution["timeframes"]:
                    _, requests_made = fetch_range(
                        client=clients[exchange],
                        job=HistoryJob(
                            exchange=exchange,
                            symbol=(
                                f"{base}_USDT"
                                if exchange == "gateio"
                                else f"{base}USDT"
                            ),
                            base=base,
                            quote="USDT",
                            granularity=granularity,
                            start_ts=0,
                            end_ts=end_ts,
                        ),
                        candles_per_request=int(execution["candles_per_request"]),
                        sleep_sec=0,
                    )
                    logical_requests_by_exchange[exchange] += requests_made

        logical_requests = sum(logical_requests_by_exchange.values())
        maximum_http_attempts = logical_requests * (
            int(execution["max_retries"]) + 1
        )
        self.assertEqual(
            logical_requests_by_exchange,
            execution["logical_requests_by_exchange"],
        )
        self.assertEqual(logical_requests, execution["logical_requests"])
        self.assertEqual(
            maximum_http_attempts,
            execution["maximum_http_attempts"],
        )

    def test_public_client_retry_bound_is_max_retries_plus_one(self) -> None:
        client = MexcSpotOhlcvClient(timeout_sec=1, max_retries=1)
        session = AlwaysTimeoutSession()
        client.session = session

        with patch("listing_event_history_collector.time.sleep", return_value=None):
            with self.assertRaises(requests.RequestException):
                client._get("/synthetic", {})

        self.assertEqual(session.calls, 2)

    def test_exchange_clients_publish_their_actual_page_caps(self) -> None:
        self.assertEqual(getattr(MexcSpotOhlcvClient, "max_candles_per_request", None), 500)
        self.assertEqual(getattr(BitgetSpotOhlcvClient, "max_candles_per_request", None), 500)
        self.assertEqual(getattr(GateSpotOhlcvClient, "max_candles_per_request", None), 1000)

    def test_fetch_range_honors_exchange_page_cap_without_gaps(self) -> None:
        interval_sec = 3600
        candle_count = 1200
        job = HistoryJob(
            exchange="mexc",
            symbol="EDGEUSDT",
            base="EDGE",
            quote="USDT",
            granularity="1h",
            start_ts=0,
            end_ts=(candle_count - 1) * interval_sec,
        )
        client = CappedMexcClient()

        candles, requests_made = fetch_range(
            client=client,
            job=job,
            candles_per_request=1000,
            sleep_sec=0,
        )

        self.assertEqual(len(candles), candle_count)
        self.assertEqual(requests_made, 3)
        self.assertEqual([call[2] for call in client.calls], [500, 500, 500])
        self.assertEqual(
            [candle.ts for candle in candles],
            [index * interval_sec for index in range(candle_count)],
        )

    def test_fetch_range_is_contiguous_around_mexc_page_cap_boundaries(self) -> None:
        interval_sec = 3600
        for candle_count in (499, 500, 501, 999, 1000, 1001):
            with self.subTest(candle_count=candle_count):
                job = HistoryJob(
                    exchange="mexc",
                    symbol="EDGEUSDT",
                    base="EDGE",
                    quote="USDT",
                    granularity="1h",
                    start_ts=0,
                    end_ts=(candle_count - 1) * interval_sec,
                )
                client = CappedMexcClient()

                candles, requests_made = fetch_range(
                    client=client,
                    job=job,
                    candles_per_request=1000,
                    sleep_sec=0,
                )

                expected_requests = (candle_count + 499) // 500
                expected_timestamps = [
                    index * interval_sec for index in range(candle_count)
                ]
                expected_calls = [
                    (
                        page_start * interval_sec,
                        (min(page_start + 500, candle_count) - 1) * interval_sec,
                        500,
                    )
                    for page_start in range(0, candle_count, 500)
                ]
                actual_timestamps = [candle.ts for candle in candles]
                self.assertEqual(requests_made, expected_requests)
                self.assertEqual(client.calls, expected_calls)
                self.assertEqual(actual_timestamps, expected_timestamps)
                self.assertEqual(len(actual_timestamps), len(set(actual_timestamps)))

    def test_unaligned_range_keeps_epoch_aligned_candles_across_pages(self) -> None:
        interval_sec = 3600
        start_ts = 123
        end_ts = start_ts + 1200 * interval_sec
        job = HistoryJob(
            exchange="mexc",
            symbol="EDGEUSDT",
            base="EDGE",
            quote="USDT",
            granularity="1h",
            start_ts=start_ts,
            end_ts=end_ts,
        )
        client = EpochAlignedCappedClient()

        candles, requests_made = fetch_range(
            client=client,
            job=job,
            candles_per_request=1000,
            sleep_sec=0,
        )

        expected_timestamps = list(
            range(interval_sec, end_ts + 1, interval_sec)
        )
        actual_timestamps = [candle.ts for candle in candles]
        self.assertEqual(requests_made, 3)
        self.assertEqual(actual_timestamps, expected_timestamps)
        self.assertEqual(len(actual_timestamps), len(set(actual_timestamps)))

    def test_fetch_range_drops_off_grid_and_out_of_page_candles(self) -> None:
        interval_sec = INTERVAL_SECONDS["1h"]
        client = NoisyEpochAlignedCappedClient()

        candles, requests_made = fetch_range(
            client=client,
            job=HistoryJob(
                exchange="mexc",
                symbol="EDGEUSDT",
                base="EDGE",
                quote="USDT",
                granularity="1h",
                start_ts=123,
                end_ts=1200 * interval_sec + 123,
            ),
            candles_per_request=1000,
            sleep_sec=0,
        )

        expected = list(range(interval_sec, 1200 * interval_sec + 1, interval_sec))
        self.assertEqual(requests_made, 3)
        self.assertEqual([candle.ts for candle in candles], expected)
        self.assertTrue(all(candle.ts % interval_sec == 0 for candle in candles))

    def test_frozen_56_day_mexc_ranges_are_contiguous_for_1h_and_4h(self) -> None:
        end_ts = 56 * 24 * 60 * 60
        cases = (
            ("1h", 3600, 1345, 3),
            ("4h", 4 * 3600, 337, 1),
        )
        for granularity, interval_sec, candle_count, expected_requests in cases:
            with self.subTest(granularity=granularity):
                job = HistoryJob(
                    exchange="mexc",
                    symbol="EDGEUSDT",
                    base="EDGE",
                    quote="USDT",
                    granularity=granularity,
                    start_ts=0,
                    end_ts=end_ts,
                )
                client = CappedMexcClient()

                candles, requests_made = fetch_range(
                    client=client,
                    job=job,
                    candles_per_request=1000,
                    sleep_sec=0,
                )

                expected_timestamps = list(range(0, end_ts + 1, interval_sec))
                actual_timestamps = [candle.ts for candle in candles]
                self.assertEqual(candle_count, len(expected_timestamps))
                self.assertEqual(requests_made, expected_requests)
                self.assertEqual(actual_timestamps, expected_timestamps)
                self.assertEqual(len(actual_timestamps), len(set(actual_timestamps)))
                self.assertTrue(all(call[2] == 500 for call in client.calls))

    def test_fetch_range_is_contiguous_around_gate_page_cap_boundaries(self) -> None:
        interval_sec = 3600
        for candle_count in (999, 1000, 1001, 1999, 2000, 2001):
            with self.subTest(candle_count=candle_count):
                job = HistoryJob(
                    exchange="gateio",
                    symbol="EDGE_USDT",
                    base="EDGE",
                    quote="USDT",
                    granularity="1h",
                    start_ts=0,
                    end_ts=(candle_count - 1) * interval_sec,
                )
                client = CappedGateClient()

                candles, requests_made = fetch_range(
                    client=client,
                    job=job,
                    candles_per_request=1000,
                    sleep_sec=0,
                )

                expected_requests = (candle_count + 999) // 1000
                expected_timestamps = [
                    index * interval_sec for index in range(candle_count)
                ]
                expected_calls = [
                    (
                        page_start * interval_sec,
                        (min(page_start + 1000, candle_count) - 1) * interval_sec,
                        1000,
                    )
                    for page_start in range(0, candle_count, 1000)
                ]
                actual_timestamps = [candle.ts for candle in candles]
                self.assertEqual(requests_made, expected_requests)
                self.assertEqual(client.calls, expected_calls)
                self.assertEqual(actual_timestamps, expected_timestamps)
                self.assertEqual(len(actual_timestamps), len(set(actual_timestamps)))

    def test_frozen_two_exchange_matrix_is_contiguous_and_matches_budget(self) -> None:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        execution = plan["execution"]
        end_ts = int(execution["history_days"]) * 24 * 60 * 60
        client_types = {
            "mexc": CappedMexcClient,
            "gateio": CappedGateClient,
        }
        logical_requests_by_exchange = {"mexc": 0, "gateio": 0}
        total_candles = 0

        for base in plan["universe"]["bases"]:
            for exchange in execution["exchanges"]:
                for granularity in execution["timeframes"]:
                    interval_sec = INTERVAL_SECONDS[granularity]
                    expected_timestamps = list(range(0, end_ts + 1, interval_sec))
                    client = client_types[exchange]()
                    candles, requests_made = fetch_range(
                        client=client,
                        job=HistoryJob(
                            exchange=exchange,
                            symbol=(
                                f"{base}_USDT"
                                if exchange == "gateio"
                                else f"{base}USDT"
                            ),
                            base=base,
                            quote="USDT",
                            granularity=granularity,
                            start_ts=0,
                            end_ts=end_ts,
                        ),
                        candles_per_request=int(execution["candles_per_request"]),
                        sleep_sec=0,
                    )
                    actual_timestamps = [candle.ts for candle in candles]
                    self.assertEqual(actual_timestamps, expected_timestamps)
                    self.assertEqual(
                        len(actual_timestamps),
                        len(set(actual_timestamps)),
                    )
                    logical_requests_by_exchange[exchange] += requests_made
                    total_candles += len(candles)

        expected_candles_per_exchange = len(plan["universe"]["bases"]) * sum(
            len(range(0, end_ts + 1, INTERVAL_SECONDS[granularity]))
            for granularity in execution["timeframes"]
        )
        self.assertEqual(
            logical_requests_by_exchange,
            execution["logical_requests_by_exchange"],
        )
        self.assertEqual(
            sum(logical_requests_by_exchange.values()),
            execution["logical_requests"],
        )
        self.assertEqual(total_candles, expected_candles_per_exchange * 2)

    def test_shared_listing_fetch_honors_exchange_page_cap_without_gaps(self) -> None:
        interval_sec = 3600
        candle_count = 1200
        client = CappedMexcClient()

        candles, requests_made = fetch_window(
            client=client,
            event={
                "symbol": "EDGEUSDT",
                "window_start_ts": 0,
                "window_end_ts": (candle_count - 1) * interval_sec,
            },
            granularity="1h",
            candles_per_request=1000,
            sleep_sec=0,
        )

        self.assertEqual(len(candles), candle_count)
        self.assertEqual(requests_made, 3)
        self.assertEqual([call[2] for call in client.calls], [500, 500, 500])


if __name__ == "__main__":
    unittest.main()
