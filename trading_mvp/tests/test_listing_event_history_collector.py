from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import listing_event_history_collector as collector  # noqa: E402
from listing_event_history_collector import (  # noqa: E402
    APPROVAL_TEXT,
    BitgetSpotOhlcvClient,
    Candle,
    MexcSpotOhlcvClient,
    collect_history,
    parse_bitget_spot_candles,
    parse_gate_spot_candles,
    parse_mexc_spot_klines,
)


def write_calendar(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "event_id",
        "exchange",
        "base",
        "quote",
        "symbol",
        "listed_at_utc",
        "announcement_at_utc",
        "source_url",
        "source_type",
        "delisted_at_utc",
        "is_delisted",
        "first_trade_ts_utc",
        "survivorship_status",
        "listed_ts",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


class FakeMexcClient:
    def __init__(self, **_: Any) -> None:
        pass

    def fetch_ohlcv(self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int) -> list[Candle]:
        return [
            Candle(
                ts=start_ts,
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=10.0,
                quote_volume=15.0,
                trade_count=3,
            )
        ]


class FakeGateClient:
    def __init__(self, **_: Any) -> None:
        pass

    def fetch_ohlcv(self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int) -> list[Candle]:
        return []


class ListingEventHistoryCollectorTests(unittest.TestCase):
    def test_parse_mexc_spot_klines(self) -> None:
        rows = parse_mexc_spot_klines(
            [
                [1783535880000, "62094.19", "62096.93", "62067.43", "62068.1", "1.86975875", 1783535940000, "116068.11", 12],
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ts, 1783535880)
        self.assertEqual(rows[0].open, 62094.19)
        self.assertEqual(rows[0].quote_volume, 116068.11)
        self.assertEqual(rows[0].trade_count, 12)

    def test_parse_gate_spot_candles(self) -> None:
        rows = parse_gate_spot_candles(
            [
                ["1783535880", "294637.68565560", "62065.4", "62090.1", "62065.4", "62090", "4.74642400", "true"],
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ts, 1783535880)
        self.assertEqual(rows[0].open, 62090.0)
        self.assertEqual(rows[0].close, 62065.4)
        self.assertEqual(rows[0].volume, 4.746424)
        self.assertEqual(rows[0].quote_volume, 294637.68565560)

    def test_parse_bitget_spot_candles(self) -> None:
        rows = parse_bitget_spot_candles(
            {
                "code": "00000",
                "msg": "success",
                "data": [
                    [
                        "1783569600000",
                        "61979.5",
                        "62258.54",
                        "61958.05",
                        "62245",
                        "54.289935",
                        "3370410.27965134",
                        "3370410.27965134",
                    ]
                ],
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ts, 1783569600)
        self.assertEqual(rows[0].open, 61979.5)
        self.assertEqual(rows[0].close, 62245.0)
        self.assertEqual(rows[0].volume, 54.289935)
        self.assertEqual(rows[0].quote_volume, 3370410.27965134)

    def test_mexc_hourly_interval_maps_to_60m(self) -> None:
        captured: dict[str, Any] = {}

        class CapturingMexcClient(MexcSpotOhlcvClient):
            def _get(self, path: str, params: dict[str, Any]) -> Any:
                captured["path"] = path
                captured["params"] = params
                return []

        client = CapturingMexcClient()
        client.fetch_ohlcv("FLORKUSDT", "1h", 100, 200, 100)

        self.assertEqual(captured["path"], "/api/v3/klines")
        self.assertEqual(captured["params"]["interval"], "60m")

    def test_bitget_interval_maps_to_api_granularity(self) -> None:
        captured: dict[str, Any] = {}

        class CapturingBitgetClient(BitgetSpotOhlcvClient):
            def _get(self, path: str, params: dict[str, Any]) -> Any:
                captured["path"] = path
                captured["params"] = params
                return {"data": []}

        client = CapturingBitgetClient()
        client.fetch_ohlcv("HYPEUSDT", "5m", 100, 200, 100)

        self.assertEqual(captured["path"], "/api/v2/spot/market/candles")
        self.assertEqual(captured["params"]["granularity"], "5min")
        self.assertEqual(captured["params"]["symbol"], "HYPEUSDT")

    def test_collect_history_writes_ok_and_no_data_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            preview = root / "preview.json"
            output = root / "ohlcv.jsonl"
            manifest = root / "manifest.json"
            event_plan = root / "event_plan.json"
            write_calendar(
                calendar,
                [
                    {
                        "event_id": "mexc:AAAUSDT:listing",
                        "exchange": "mexc",
                        "base": "AAA",
                        "quote": "USDT",
                        "symbol": "AAAUSDT",
                        "listed_ts": "1700000000",
                        "listed_at_utc": "2023-11-14T22:13:20Z",
                        "is_delisted": "false",
                        "survivorship_status": "current_active_snapshot",
                        "source_type": "fixture",
                    },
                    {
                        "event_id": "gateio:OLD_USDT:listing",
                        "exchange": "gateio",
                        "base": "OLD",
                        "quote": "USDT",
                        "symbol": "OLD_USDT",
                        "listed_ts": "1700003600",
                        "listed_at_utc": "2023-11-14T23:13:20Z",
                        "is_delisted": "true",
                        "survivorship_status": "current_non_tradable_snapshot",
                        "source_type": "fixture",
                    },
                ],
            )
            preview.write_text(
                json.dumps(
                    {
                        "mode": "listing_event_history_collect_preview_planonly",
                        "run_id": "fixture_listing_history",
                        "calendar_path": str(calendar),
                        "selection": {
                            "target_events": 2,
                            "selected_events": 2,
                            "max_events_per_base": 2,
                            "max_exchange_fraction": 0.60,
                        },
                        "request_budget": {
                            "pre_window_sec": 60,
                            "post_window_sec": 60,
                            "granularities": ["1m"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            original_clients = collector.CLIENTS
            collector.CLIENTS = {"mexc": FakeMexcClient, "gateio": FakeGateClient}
            try:
                result = collect_history(
                    preview_path=preview,
                    output_jsonl=output,
                    manifest_path=manifest,
                    event_plan_path=event_plan,
                    confirmed_approval_text=APPROVAL_TEXT,
                    candles_per_request=1000,
                    sleep_sec=0,
                    max_retries=0,
                    max_events=2,
                    progress_every=0,
                    repo_root=root,
                )
            finally:
                collector.CLIENTS = original_clients

            self.assertTrue(result["final"])
            self.assertEqual(result["decision"], "LISTING_EVENT_HISTORY_COLLECT_COMPLETED_READY_FOR_DATA_QUALITY")
            self.assertEqual(result["ohlcv_rows"], 1)
            self.assertEqual(result["placeholder_rows"], 1)
            self.assertEqual(result["data_status_counts"]["ok"], 1)
            self.assertEqual(result["data_status_counts"]["no_data_or_delisted"], 1)

            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["data_status"] for row in rows}, {"ok", "no_data_or_delisted"})
            self.assertTrue(event_plan.exists())
            saved_manifest = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(saved_manifest["replay_allowed"])
            self.assertFalse(saved_manifest["grid_allowed"])

    def test_collect_history_uses_explicit_sample_event_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            preview = root / "preview.json"
            output = root / "ohlcv.jsonl"
            manifest = root / "manifest.json"
            event_plan = root / "event_plan.json"
            write_calendar(
                calendar,
                [
                    {
                        "event_id": "mexc:OLDUSDT:listing",
                        "exchange": "mexc",
                        "base": "OLD",
                        "quote": "USDT",
                        "symbol": "OLDUSDT",
                        "listed_ts": "1500000000",
                        "listed_at_utc": "2017-07-14T02:40:00Z",
                        "is_delisted": "true",
                        "survivorship_status": "current_non_tradable_snapshot",
                        "source_type": "fixture",
                    },
                    {
                        "event_id": "mexc:KEEPUSDT:listing",
                        "exchange": "mexc",
                        "base": "KEEP",
                        "quote": "USDT",
                        "symbol": "KEEPUSDT",
                        "listed_ts": "1800000000",
                        "listed_at_utc": "2027-01-15T08:00:00Z",
                        "is_delisted": "false",
                        "survivorship_status": "current_active_snapshot",
                        "source_type": "fixture",
                    },
                ],
            )
            preview.write_text(
                json.dumps(
                    {
                        "mode": "listing_event_history_collect_preview_planonly",
                        "run_id": "fixture_explicit_plan",
                        "calendar_path": str(calendar),
                        "selection": {
                            "event_plan_source": "explicit_sample_events",
                            "target_events": 1,
                            "selected_events": 1,
                            "max_events_per_base": 2,
                            "max_exchange_fraction": 0.60,
                            "sample_events": [
                                {
                                    "event_id": "mexc:KEEPUSDT:listing",
                                    "exchange": "mexc",
                                    "base": "KEEP",
                                    "quote": "USDT",
                                    "symbol": "KEEPUSDT",
                                    "event_ts": 1_800_000_000,
                                    "event_iso": "2027-01-15T08:00:00Z",
                                    "window_start_ts": 1_799_999_940,
                                    "window_end_ts": 1_800_000_060,
                                    "is_delisted": False,
                                    "survivorship_status": "availability_probe_verified",
                                    "source_type": "availability_preflight_probe_ok",
                                }
                            ],
                        },
                        "request_budget": {
                            "pre_window_sec": 60,
                            "post_window_sec": 60,
                            "granularities": ["1m"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            original_clients = collector.CLIENTS
            collector.CLIENTS = {"mexc": FakeMexcClient, "gateio": FakeGateClient}
            try:
                result = collect_history(
                    preview_path=preview,
                    output_jsonl=output,
                    manifest_path=manifest,
                    event_plan_path=event_plan,
                    confirmed_approval_text=APPROVAL_TEXT,
                    candles_per_request=1000,
                    sleep_sec=0,
                    max_retries=0,
                    progress_every=0,
                    repo_root=root,
                )
            finally:
                collector.CLIENTS = original_clients

            self.assertTrue(result["final"])
            saved_plan = json.loads(event_plan.read_text(encoding="utf-8"))
            self.assertEqual([row["event_id"] for row in saved_plan["events"]], ["mexc:KEEPUSDT:listing"])
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["event_id"] for row in rows}, {"mexc:KEEPUSDT:listing"})

    def test_collect_history_requires_exact_approval_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview = root / "preview.json"
            preview.write_text("{}", encoding="utf-8")

            with self.assertRaises(ValueError):
                collect_history(
                    preview_path=preview,
                    output_jsonl=root / "ohlcv.jsonl",
                    manifest_path=root / "manifest.json",
                    event_plan_path=root / "event_plan.json",
                    confirmed_approval_text="yes",
                    repo_root=root,
                )

    def test_write_manifest_retries_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            original_replace = Path.replace
            attempts = {"count": 0}

            def flaky_replace(path: Path, target: Path) -> Path:
                if path.name == "manifest.json.tmp" and attempts["count"] < 2:
                    attempts["count"] += 1
                    raise PermissionError("temporary manifest lock")
                return original_replace(path, target)

            with mock.patch.object(Path, "replace", flaky_replace):
                collector.write_manifest(manifest, {"ok": True})

            self.assertEqual(attempts["count"], 2)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), {"ok": True})


if __name__ == "__main__":
    unittest.main()
