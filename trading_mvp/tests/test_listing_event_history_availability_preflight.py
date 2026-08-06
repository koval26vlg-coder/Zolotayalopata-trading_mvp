from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import listing_event_history_availability_preflight as preflight  # noqa: E402
from listing_event_history_availability_preflight import build_availability_preflight  # noqa: E402
from listing_event_history_collector import Candle  # noqa: E402


def write_calendar(path: Path) -> None:
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
    rows: list[dict[str, str]] = []
    for index in range(8):
        exchange = "mexc" if index % 2 == 0 else "gateio"
        base = f"P{index:03d}"
        symbol = f"{base}USDT" if exchange == "mexc" else f"{base}_USDT"
        rows.append(
            {
                "event_id": f"{exchange}:{symbol}:listing",
                "exchange": exchange,
                "base": base,
                "quote": "USDT",
                "symbol": symbol,
                "listed_at_utc": "2023-11-14T22:13:20Z",
                "source_type": "fixture",
                "is_delisted": "false",
                "survivorship_status": "current_active_snapshot",
                "listed_ts": str(1_700_000_000 + index * 3600),
            }
        )
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_preview(path: Path, calendar: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "mode": "listing_event_history_collect_preview_planonly",
                "run_id": "fixture_preflight",
                "calendar_path": str(calendar),
                "selection": {
                    "target_events": 8,
                    "selected_events": 8,
                    "max_events_per_base": 2,
                    "max_exchange_fraction": 0.60,
                },
                "request_budget": {
                    "pre_window_sec": 60,
                    "post_window_sec": 60,
                    "granularities": ["5m"],
                },
            }
        ),
        encoding="utf-8",
    )


def write_quality(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "accepted": False,
                "decision": "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN",
                "reasons": ["min_ok_exchanges", "max_single_exchange_ok_event_fraction", "max_api_error_slot_rate"],
                "metrics": {"ok_exchanges": 1, "ok_events": 4, "api_error_slot_rate": 0.6},
                "counts": {"ok_rows_by_exchange": {"mexc": 1953}, "error_rows_by_exchange": {"gateio": 144}},
            }
        ),
        encoding="utf-8",
    )


class FakeOkClient:
    def __init__(self, **_: Any) -> None:
        pass

    def fetch_ohlcv(self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int) -> list[Candle]:
        return [
            Candle(
                ts=start_ts,
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.0,
                volume=10.0,
                quote_volume=10.0,
            )
        ]


class ListingEventHistoryAvailabilityPreflightTests(unittest.TestCase):
    def test_planonly_requires_confirmed_public_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            preview = root / "preview.json"
            quality = root / "quality.json"
            output = root / "preflight.json"
            write_calendar(calendar)
            write_preview(preview, calendar)
            write_quality(quality)

            result = build_availability_preflight(
                preview_path=preview,
                output_path=output,
                repo_root=root,
                previous_quality_report_path=quality,
                max_events_per_exchange=2,
                probe=False,
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_READY_FOR_PUBLIC_PROBE")
            self.assertFalse(result["would_start_collect"])
            self.assertFalse(result["would_run_public_probe"])
            self.assertTrue(result["public_probe_requires_explicit_user_approval"])
            self.assertEqual(result["probe_contract"]["planned_exchanges"], {"gateio": 2, "mexc": 2})
            self.assertEqual(result["probe_contract"]["probe_window_sec"], 3600)
            for row in result["planned_probe_rows"]:
                self.assertLessEqual(row["window_end_ts"] - row["window_start_ts"], 3600)
            self.assertTrue(output.exists())

    def test_confirmed_probe_accepts_two_venue_coverage_with_fake_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            preview = root / "preview.json"
            quality = root / "quality.json"
            output = root / "preflight.json"
            write_calendar(calendar)
            write_preview(preview, calendar)
            write_quality(quality)
            original_clients = preflight.CLIENTS
            preflight.CLIENTS = {"mexc": FakeOkClient, "gateio": FakeOkClient}
            try:
                result = build_availability_preflight(
                    preview_path=preview,
                    output_path=output,
                    repo_root=root,
                    previous_quality_report_path=quality,
                    max_events_per_exchange=2,
                    probe=True,
                    candles_per_request=2,
                )
            finally:
                preflight.CLIENTS = original_clients

            self.assertEqual(
                result["decision"],
                "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET",
            )
            self.assertFalse(result["would_start_collect"])
            self.assertTrue(result["would_run_public_probe"])
            self.assertEqual(result["summary"]["ok_exchanges"], 2)
            self.assertEqual(result["summary"]["api_error_slot_rate"], 0.0)
            self.assertLessEqual(result["summary"]["max_single_exchange_ok_event_fraction"], 0.70)

    def test_probe_selection_prefers_recent_active_events(self) -> None:
        old_active = {
            "event_id": "mexc:OLDUSDT:listing",
            "exchange": "mexc",
            "symbol": "OLDUSDT",
            "base": "OLD",
            "quote": "USDT",
            "event_ts": 1_600_000_000,
            "is_delisted": False,
            "survivorship_status": "current_active_snapshot",
        }
        recent_active = {
            "event_id": "mexc:NEWUSDT:listing",
            "exchange": "mexc",
            "symbol": "NEWUSDT",
            "base": "NEW",
            "quote": "USDT",
            "event_ts": 1_800_000_000,
            "is_delisted": False,
            "survivorship_status": "current_active_snapshot",
        }
        recent_delisted = {
            "event_id": "mexc:DEADUSDT:listing",
            "exchange": "mexc",
            "symbol": "DEADUSDT",
            "base": "DEAD",
            "quote": "USDT",
            "event_ts": 1_900_000_000,
            "is_delisted": True,
            "survivorship_status": "current_non_tradable_snapshot",
        }

        selected = preflight.select_probe_events(
            [old_active, recent_active, recent_delisted],
            max_events_per_exchange=1,
        )

        self.assertEqual([row["event_id"] for row in selected], ["mexc:NEWUSDT:listing"])


if __name__ == "__main__":
    unittest.main()
