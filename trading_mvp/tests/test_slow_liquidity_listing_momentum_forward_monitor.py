from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from listing_event_history_collector import Candle  # noqa: E402
from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
import slow_liquidity_listing_momentum_forward_monitor as monitor  # noqa: E402
import slow_liquidity_listing_momentum_forward_monitor_plan as plan_module  # noqa: E402


HOUR = 3600
DAY = 86400
AS_OF = monitor.BASELINE_AS_OF_TS


def make_bars(start_ts: int, end_ts: int) -> list[Candle]:
    return [
        Candle(ts=ts, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0, quote_volume=15.0)
        for ts in range(start_ts, end_ts + 1, HOUR)
    ]


class FakeClient:
    def __init__(self, bars_by_symbol: dict[str, list[Candle]]) -> None:
        self.bars_by_symbol = bars_by_symbol
        self.max_candles_per_request = 500

    def fetch_ohlcv(
        self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int
    ) -> list[Candle]:
        bars = [
            bar
            for bar in self.bars_by_symbol.get(symbol, [])
            if start_ts <= bar.ts <= end_ts
        ]
        return bars[:limit]


class DiffNewListingsTests(unittest.TestCase):
    def test_categories(self) -> None:
        baseline = {("mexc", "OLDUSDT")}
        now = AS_OF + 10 * DAY
        rows = [
            {"exchange": "mexc", "base": "OLD", "symbol": "OLDUSDT",
             "listed_ts": AS_OF - 300 * DAY, "is_delisted": "false"},
            {"exchange": "mexc", "base": "NEW1", "symbol": "NEW1USDT",
             "listed_ts": AS_OF + 1 * DAY, "is_delisted": "false"},
            {"exchange": "gateio", "base": "NEW2", "symbol": "NEW2_USDT",
             "listed_ts": AS_OF + 9 * DAY, "is_delisted": "false"},
            {"exchange": "gateio", "base": "BACK", "symbol": "BACK_USDT",
             "listed_ts": AS_OF - 2 * DAY, "is_delisted": "false"},
            {"exchange": "mexc", "base": "GONE", "symbol": "GONEUSDT",
             "listed_ts": AS_OF + 1 * DAY, "is_delisted": "true"},
            {"exchange": "mexc", "base": "NOTS", "symbol": "NOTSUSDT",
             "listed_ts": "", "is_delisted": "false"},
        ]
        result = monitor.diff_new_listings(
            baseline, rows, baseline_as_of_ts=AS_OF, now_ts=now
        )
        by_symbol = {entry["symbol"]: entry for entry in result}
        self.assertNotIn("OLDUSDT", by_symbol)
        self.assertNotIn("GONEUSDT", by_symbol)
        self.assertNotIn("NOTSUSDT", by_symbol)
        self.assertEqual(
            by_symbol["NEW1USDT"]["category"], "new_listing_window_complete"
        )
        self.assertTrue(by_symbol["NEW1USDT"]["collect"])
        self.assertEqual(
            by_symbol["NEW2_USDT"]["category"], "new_listing_in_progress"
        )
        self.assertTrue(by_symbol["NEW2_USDT"]["collect"])
        self.assertEqual(
            by_symbol["BACK_USDT"]["category"], "backfill_or_relist_skip"
        )
        self.assertFalse(by_symbol["BACK_USDT"]["collect"])

    def test_derive_forward_jobs_skips_non_collect(self) -> None:
        entries = [
            {"exchange": "mexc", "base": "NEW1", "symbol": "NEW1USDT",
             "listed_ts": AS_OF + DAY, "category": "new_listing_window_complete",
             "collect": True},
            {"exchange": "gateio", "base": "BACK", "symbol": "BACK_USDT",
             "listed_ts": AS_OF - DAY, "category": "backfill_or_relist_skip",
             "collect": False},
        ]
        jobs = monitor.derive_forward_jobs(entries)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["probe_start_ts"] % HOUR, 0)
        self.assertEqual(
            job["window_end_ts"],
            ((AS_OF + DAY + monitor.WINDOW_SEC) // HOUR) * HOUR,
        )


class RunTickTests(unittest.TestCase):
    def _run(self, tick_id: str, rows: list[dict], bars: dict[str, list[Candle]], now_ts: int):
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim.json"), mock.patch.object(
            monitor, "CALENDAR_PATH", self._baseline_csv(tmp)
        ):
            plan = {"plan_hash": "forward-plan-hash"}
            fetcher = lambda: (rows, 2)  # noqa: E731
            clients = {
                "mexc": FakeClient(bars),
                "gateio": FakeClient(bars),
            }
            manifest = monitor.run_tick(
                plan, tick_id=tick_id, clients=clients, fetcher=fetcher, now_ts=now_ts
            )
        return manifest, tmp

    def _baseline_csv(self, tmp: Path) -> Path:
        baseline = tmp / "baseline.csv"
        baseline.write_text(
            "exchange,base,quote,symbol,is_delisted,listed_ts\n"
            "mexc,OLD,USDT,OLDUSDT,false,1514736000\n",
            encoding="utf-8",
        )
        return baseline

    def test_tick_collects_new_listing_and_writes_state(self) -> None:
        now = AS_OF + 10 * DAY
        proxy_ts = ((AS_OF + DAY) // HOUR) * HOUR
        rows = [
            {"exchange": "mexc", "base": "NEW1", "symbol": "NEW1USDT",
             "listed_ts": proxy_ts, "is_delisted": "false"},
        ]
        bars = {"NEW1USDT": make_bars(proxy_ts, proxy_ts + 71 * HOUR)}
        manifest, tmp = self._run("tick_a", rows, bars, now)
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertEqual(manifest["new_listing_count"], 1)
        self.assertEqual(manifest["rows_written"], 72)
        tick_dir = tmp / "ticks" / "tick_a"
        rows_on_disk = (tick_dir / "ohlcv.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows_on_disk), 72)
        self.assertIn("first_days_forward", rows_on_disk[0])
        state = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tick_count"], 1)
        self.assertEqual(state["window_count"], 1)
        self.assertTrue(state["windows"][0]["window_complete"])
        self.assertEqual(state["windows"][0]["stats"]["n_bars"], 72)
        self.assertFalse((tmp / "claim.json").exists())

    def test_tick_flags_in_progress_window(self) -> None:
        now = AS_OF + 2 * DAY  # window of NEW1 (listed at AS_OF+1d) still open
        proxy_ts = ((AS_OF + DAY) // HOUR) * HOUR
        rows = [
            {"exchange": "mexc", "base": "NEW1", "symbol": "NEW1USDT",
             "listed_ts": proxy_ts, "is_delisted": "false"},
        ]
        bars = {"NEW1USDT": make_bars(proxy_ts, proxy_ts + 20 * HOUR)}
        manifest, tmp = self._run("tick_b", rows, bars, now)
        self.assertEqual(manifest["status"], "COMPLETED")
        job = manifest["jobs"][0]
        self.assertIn("window_in_progress", job["flags"])
        state = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["windows"][0]["window_complete"])

    def test_tick_refuses_duplicate_id(self) -> None:
        now = AS_OF + 10 * DAY
        proxy_ts = ((AS_OF + DAY) // HOUR) * HOUR
        rows = [
            {"exchange": "mexc", "base": "NEW1", "symbol": "NEW1USDT",
             "listed_ts": proxy_ts, "is_delisted": "false"},
        ]
        manifest, tmp = self._run("tick_c", rows, {}, now)
        self.assertEqual(manifest["status"], "COMPLETED")
        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim2.json"), mock.patch.object(
            monitor, "CALENDAR_PATH", self._baseline_csv(tmp)
        ):
            with self.assertRaisesRegex(monitor.ForwardMonitorError, "already exists"):
                monitor.run_tick(
                    {"plan_hash": "h"},
                    tick_id="tick_c",
                    clients={"mexc": FakeClient({}), "gateio": FakeClient({})},
                    fetcher=lambda: ([], 2),
                    now_ts=now,
                )

    def test_tick_cap_enforced(self) -> None:
        now = AS_OF + 60 * DAY
        rows = [
            {"exchange": "mexc", "base": f"N{i}", "symbol": f"N{i}USDT",
             "listed_ts": AS_OF + (i + 1) * DAY, "is_delisted": "false"}
            for i in range(monitor.MAX_NEW_LISTINGS_PER_TICK + 1)
        ]
        with self.assertRaisesRegex(monitor.ForwardMonitorError, "exceed"):
            self._run("tick_d", rows, {}, now)


class PlanModuleTests(unittest.TestCase):
    def test_plan_is_bounded_accrual_only(self) -> None:
        plan = plan_module.build_forward_monitor_plan("2026-08-16T22:00:00Z")
        plan_module.validate_forward_monitor_plan(plan)
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["status"], "AWAIT_GUARD_GREEN_VISIBLE_TICKS")
        self.assertEqual(plan["tick"]["max_runtime_sec"], 600)
        self.assertEqual(plan["tick"]["max_new_listings_per_tick"], 50)
        self.assertTrue(plan["guard_contract"]["no_background_daemon"])
        self.assertTrue(plan["guard_contract"]["visible_terminal_launch_required"])
        self.assertEqual(
            plan["acceptance_policy"]["acceptance_decision"], "NONE_ACCRUAL_ONLY"
        )
        self.assertFalse(plan["evaluator_or_oos_allowed"])
        self.assertEqual(
            plan["source_bindings"]["baseline_calendar"]["baseline_as_of_ts"],
            monitor.BASELINE_AS_OF_TS,
        )

    def test_plan_with_evaluator_enabled_is_rejected(self) -> None:
        plan = plan_module.build_forward_monitor_plan("2026-08-16T22:00:00Z")
        plan["evaluator_or_oos_allowed"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            plan_module.ForwardMonitorPlanError, "evaluator"
        ):
            plan_module.validate_forward_monitor_plan(plan)

    def test_checked_in_plan_matches_generator(self) -> None:
        if not plan_module.FORWARD_PLAN_PATH.is_file():
            raise FileNotFoundError(plan_module.FORWARD_PLAN_PATH)
        checked_in = json.loads(
            plan_module.FORWARD_PLAN_PATH.read_text(encoding="utf-8")
        )
        rebuilt = plan_module.build_forward_monitor_plan(
            checked_in["generated_at_utc"]
        )
        self.assertEqual(checked_in, rebuilt)

    def test_monitor_accepts_frozen_plan(self) -> None:
        if not plan_module.FORWARD_PLAN_PATH.is_file():
            raise FileNotFoundError(plan_module.FORWARD_PLAN_PATH)
        plan = monitor.load_and_validate_forward_plan(plan_module.FORWARD_PLAN_PATH)
        self.assertEqual(plan["plan_id"], monitor.PLAN_ID)


if __name__ == "__main__":
    unittest.main()
