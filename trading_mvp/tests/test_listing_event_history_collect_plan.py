from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing_event_history_collect_plan import (  # noqa: E402
    build_history_collect_preview,
    estimate_requests,
    load_history_events,
    select_history_events,
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


def event_rows(count: int = 140) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(count):
        exchange = "mexc" if index % 2 == 0 else "gateio"
        base = f"T{index:03d}"
        symbol = f"{base}USDT" if exchange == "mexc" else f"{base}_USDT"
        is_delisted = index % 11 == 0
        rows.append(
            {
                "event_id": f"{exchange}:{symbol}:listing",
                "exchange": exchange,
                "base": base,
                "quote": "USDT",
                "symbol": symbol,
                "listed_ts": str(1_700_000_000 + index * 3600),
                "listed_at_utc": "2023-11-14T22:13:20Z",
                "is_delisted": "true" if is_delisted else "false",
                "survivorship_status": "current_non_tradable_snapshot" if is_delisted else "current_active_snapshot",
                "source_type": "fixture",
            }
        )
    return rows


def three_exchange_event_rows(count_per_exchange: int = 40) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for exchange in ("mexc", "gateio", "bitget"):
        for index in range(count_per_exchange):
            base = f"{exchange[:2].upper()}{index:03d}"
            symbol = f"{base}USDT" if exchange != "gateio" else f"{base}_USDT"
            event_index = len(rows)
            is_delisted = index % 17 == 0
            rows.append(
                {
                    "event_id": f"{exchange}:{symbol}:listing",
                    "exchange": exchange,
                    "base": base,
                    "quote": "USDT",
                    "symbol": symbol,
                    "listed_ts": str(1_700_000_000 + event_index * 3600),
                    "listed_at_utc": "2023-11-14T22:13:20Z",
                    "is_delisted": "true" if is_delisted else "false",
                    "survivorship_status": "current_non_tradable_snapshot" if is_delisted else "current_active_snapshot",
                    "source_type": "fixture",
                }
            )
    return rows


class ListingEventHistoryCollectPlanTests(unittest.TestCase):
    def test_select_history_events_preserves_nontradable_and_exchange_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calendar = Path(tmp) / "calendar.csv"
            write_calendar(calendar, event_rows(60))

            events = load_history_events(calendar)
            selected = select_history_events(events, target_events=20, max_exchange_fraction=0.60)

            exchange_counts: dict[str, int] = {}
            for event in selected:
                exchange_counts[event.exchange] = exchange_counts.get(event.exchange, 0) + 1

            self.assertEqual(len(selected), 20)
            self.assertGreater(sum(1 for event in selected if event.is_delisted), 0)
            self.assertLessEqual(max(exchange_counts.values()), 12)
            self.assertGreaterEqual(len({event.base for event in selected}), 20)

    def test_estimate_requests_uses_requested_granularities(self) -> None:
        estimate = estimate_requests(
            selected_count=2,
            pre_window_sec=3600,
            post_window_sec=259200,
            granularities=("1m", "5m", "1h"),
            candles_per_request=1000,
            request_rate_per_sec=2.0,
        )

        self.assertEqual(estimate["window_sec"], 262800)
        self.assertEqual(estimate["by_granularity"]["1m"]["candles_per_event"], 4381)
        self.assertEqual(estimate["by_granularity"]["1m"]["requests_per_event"], 5)
        self.assertEqual(estimate["estimated_total_requests"], 14)
        self.assertEqual(estimate["estimated_runtime_sec"], 7)

    def test_build_history_collect_preview_is_planonly_and_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            output = root / "preview.json"
            write_calendar(calendar, event_rows(140))

            result = build_history_collect_preview(
                calendar_path=calendar,
                output_path=output,
                run_id="fixture_history_collect",
                target_events=100,
                target_bases_min=30,
                request_rate_per_sec=4.0,
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL")
            self.assertFalse(result["would_start"])
            self.assertFalse(result["collect_allowed_now"])
            self.assertTrue(result["actual_collect_requires_explicit_user_approval"])
            self.assertFalse(result["api_keys"])
            self.assertFalse(result["live_orders"])
            self.assertFalse(result["replay_allowed_now"])
            self.assertGreaterEqual(result["selection"]["selected_nontradable_or_delisted_events"], 1)
            self.assertTrue(result["expected_outputs"]["manifest_path"].endswith("manifest.json"))
            self.assertTrue(output.exists())
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["run_id"], "fixture_history_collect")

    def test_build_history_collect_preview_can_require_three_exchanges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            output = root / "preview.json"
            write_calendar(calendar, three_exchange_event_rows(45))

            result = build_history_collect_preview(
                calendar_path=calendar,
                output_path=output,
                run_id="fixture_three_exchange_history_collect",
                target_events=90,
                target_bases_min=30,
                max_exchange_fraction=0.45,
                min_exchange_count=3,
                granularities=("1h",),
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL")
            self.assertEqual(result["selection"]["selected_exchange_count"], 3)
            self.assertEqual(set(result["selection"]["selected_exchange_counts"]), {"bitget", "gateio", "mexc"})
            self.assertEqual(result["selection"]["min_exchange_count"], 3)
            self.assertEqual(result["collector_contract"]["exchanges"], ["bitget", "gateio", "mexc"])

    def test_previous_quality_rejection_blocks_repeat_collect_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            output = root / "preview.json"
            quality = root / "quality.json"
            write_calendar(calendar, event_rows(140))
            quality.write_text(
                json.dumps(
                    {
                        "accepted": False,
                        "decision": "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN",
                        "reasons": [
                            "min_ok_exchanges",
                            "max_single_exchange_ok_event_fraction",
                            "max_api_error_slot_rate",
                        ],
                        "metrics": {
                            "selected_events": 120,
                            "ok_events": 4,
                            "ok_bases": 4,
                            "ok_exchanges": 1,
                            "api_error_slot_rate": 0.6,
                            "max_single_exchange_ok_event_fraction": 1.0,
                        },
                        "counts": {
                            "ok_rows_by_exchange": {"mexc": 1953},
                            "error_rows_by_exchange": {"gateio": 144, "mexc": 72},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = build_history_collect_preview(
                calendar_path=calendar,
                output_path=output,
                run_id="fixture_history_collect",
                target_events=100,
                target_bases_min=30,
                previous_quality_report_path=quality,
                require_two_venue_history_preflight=True,
            )

            self.assertEqual(
                result["decision"],
                "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_BLOCKED_NEEDS_REVISED_TWO_VENUE_PREFLIGHT",
            )
            self.assertFalse(result["would_start"])
            self.assertFalse(result["collect_allowed_now"])
            self.assertTrue(result["previous_quality_gate"]["available"])
            self.assertFalse(result["previous_quality_gate"]["accepted"])
            self.assertTrue(result["revised_two_venue_preflight_contract"]["required"])
            self.assertTrue(result["revised_two_venue_preflight_contract"]["quality_blocks_repeat"])
            self.assertIn(
                "probe_symbol_history_availability_for_mexc_and_gateio_per_event",
                result["revised_two_venue_preflight_contract"]["required_checks_before_actual_collect"],
            )

    def test_build_preview_from_accepted_availability_ok_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calendar = root / "calendar.csv"
            output = root / "preview.json"
            availability = root / "availability.json"
            write_calendar(calendar, event_rows(20))
            availability.write_text(
                json.dumps(
                    {
                        "decision": "LISTING_EVENT_HISTORY_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_COLLECT_APPROVAL_PACKET",
                        "summary": {
                            "ok_exchanges": 2,
                            "ok_events": 2,
                            "api_error_slot_rate": 0.0,
                            "max_single_exchange_ok_event_fraction": 0.5,
                        },
                        "probe_rows": [
                            {
                                "event_id": "mexc:RECENTUSDT:listing",
                                "exchange": "mexc",
                                "symbol": "RECENTUSDT",
                                "base": "RECENT",
                                "quote": "USDT",
                                "event_ts": 1_800_000_000,
                                "event_iso": "2027-01-15T08:00:00Z",
                                "granularity": "1h",
                                "full_window_start_ts": 1_799_996_400,
                                "full_window_end_ts": 1_800_259_200,
                                "probe_status": "ok",
                            },
                            {
                                "event_id": "gateio:NEW_USDT:listing",
                                "exchange": "gateio",
                                "symbol": "NEW_USDT",
                                "base": "NEW",
                                "quote": "USDT",
                                "event_ts": 1_800_100_000,
                                "event_iso": "2027-01-16T11:46:40Z",
                                "granularity": "1h",
                                "full_window_start_ts": 1_800_096_400,
                                "full_window_end_ts": 1_800_359_200,
                                "probe_status": "ok",
                            },
                            {
                                "event_id": "gateio:OLD_USDT:listing",
                                "exchange": "gateio",
                                "symbol": "OLD_USDT",
                                "base": "OLD",
                                "quote": "USDT",
                                "event_ts": 1_500_000_000,
                                "event_iso": "2017-07-14T02:40:00Z",
                                "granularity": "1h",
                                "probe_status": "api_error",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = build_history_collect_preview(
                calendar_path=calendar,
                output_path=output,
                run_id="fixture_availability_collect",
                granularities=("1h",),
                availability_preflight_path=availability,
                use_availability_ok_events=True,
            )

            self.assertEqual(result["decision"], "LISTING_EVENT_HISTORY_COLLECT_PREVIEW_READY_AWAITING_EXPLICIT_APPROVAL")
            self.assertEqual(result["selection"]["event_plan_source"], "explicit_sample_events")
            self.assertEqual(result["selection"]["selected_events"], 2)
            self.assertEqual(result["selection"]["selected_exchange_count"], 2)
            self.assertEqual(result["request_budget"]["granularities"], ["1h"])
            self.assertTrue(result["availability_preflight"]["accepted"])
            self.assertEqual(
                [row["event_id"] for row in result["selection"]["sample_events"]],
                ["mexc:RECENTUSDT:listing", "gateio:NEW_USDT:listing"],
            )
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
