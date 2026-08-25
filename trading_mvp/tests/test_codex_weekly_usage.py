from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from codex_weekly_usage import (  # noqa: E402
    collect_weekly_usage,
    evaluate_usage_guard,
    extract_latest_weekly_event,
)


def _token_event(
    timestamp: str,
    *,
    used_percent: float,
    window_minutes: int = 10_080,
    resets_at: int = 2_000_000_000,
) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "primary": {
                        "used_percent": used_percent,
                        "window_minutes": window_minutes,
                        "resets_at": resets_at,
                    },
                    "plan_type": "plus",
                    "rate_limit_reached_type": None,
                },
            },
        },
        separators=(",", ":"),
    )


class CodexWeeklyUsageTests(unittest.TestCase):
    def test_extracts_latest_weekly_event_and_ignores_other_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rollout-test.jsonl"
            path.write_text(
                "\n".join(
                    [
                        _token_event(
                            "2026-07-28T07:00:00Z",
                            used_percent=70,
                        ),
                        _token_event(
                            "2026-07-28T07:05:00Z",
                            used_percent=99,
                            window_minutes=300,
                        ),
                        _token_event(
                            "2026-07-28T07:10:00Z",
                            used_percent=85,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            event = extract_latest_weekly_event(path)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event.used_percent, 85)
            self.assertEqual(event.remaining_percent, 15)
            self.assertEqual(event.window_minutes, 10_080)

    def test_threshold_is_inclusive_at_fifteen_percent_remaining(self) -> None:
        usage = {
            "status": "AVAILABLE",
            "remaining_percent": 15.0,
        }
        result = evaluate_usage_guard(usage, min_remaining_percent=15.0)
        self.assertEqual(result["decision"], "PAUSE_WEEKLY_LIMIT")

    def test_available_status_rejects_invalid_remaining_percent(self) -> None:
        invalid_values = (
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.1,
            100.1,
            True,
            "87.0",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "remaining_percent"):
                    evaluate_usage_guard(
                        {
                            "status": "AVAILABLE",
                            "remaining_percent": value,
                        },
                        min_remaining_percent=15.0,
                    )

    def test_collects_freshest_account_wide_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "2026" / "07" / "27" / "rollout-first.jsonl"
            second = root / "2026" / "07" / "28" / "rollout-second.jsonl"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text(
                _token_event("2026-07-28T07:00:00Z", used_percent=20) + "\n",
                encoding="utf-8",
            )
            second.write_text(
                _token_event("2026-07-28T07:30:00Z", used_percent=40) + "\n",
                encoding="utf-8",
            )
            usage = collect_weekly_usage(
                root,
                now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
            )
            self.assertEqual(usage["status"], "AVAILABLE")
            self.assertEqual(usage["used_percent"], 40)
            self.assertEqual(usage["remaining_percent"], 60)
            self.assertEqual(Path(usage["source_path"]), second.resolve())

    def test_old_event_from_before_reset_infers_fresh_weekly_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "rollout-old.jsonl"
            reset = int(datetime(2026, 7, 28, 7, 30, tzinfo=timezone.utc).timestamp())
            path.write_text(
                _token_event(
                    "2026-07-28T07:00:00Z",
                    used_percent=95,
                    resets_at=reset,
                )
                + "\n",
                encoding="utf-8",
            )
            usage = collect_weekly_usage(
                root,
                now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
            )
            self.assertEqual(usage["status"], "RESET_INFERRED")
            self.assertEqual(usage["remaining_percent"], 100)
            self.assertTrue(usage["inferred_from_completed_reset"])
            guarded = evaluate_usage_guard(usage, min_remaining_percent=15)
            self.assertEqual(guarded["decision"], "CONTINUE")

    def test_event_older_than_daily_watchdog_grace_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "rollout-stale.jsonl"
            path.write_text(
                _token_event("2026-07-26T00:00:00Z", used_percent=10) + "\n",
                encoding="utf-8",
            )
            usage = collect_weekly_usage(
                root,
                now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
                stale_after_sec=108_000,
            )
            self.assertEqual(usage["status"], "STALE")
            guarded = evaluate_usage_guard(usage, min_remaining_percent=15)
            self.assertEqual(guarded["decision"], "PAUSE_USAGE_TELEMETRY_STALE")


if __name__ == "__main__":
    unittest.main()
