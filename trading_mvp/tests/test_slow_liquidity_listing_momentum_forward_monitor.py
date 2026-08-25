from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from listing_event_history_collector import Candle  # noqa: E402
from global_market_writer_claim import GlobalMarketWriterClaimError  # noqa: E402
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
    def test_direct_cli_tick_flag_cannot_bypass_launcher_handoff(self) -> None:
        with mock.patch.object(
            monitor, "load_and_validate_forward_plan", return_value={"plan_hash": "a" * 64}
        ), mock.patch.object(monitor, "run_tick") as run_tick_mock:
            with self.assertRaises(SystemExit):
                monitor.main(["--tick", "--confirmed-visible-tick"])
            run_tick_mock.assert_not_called()

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

    def _run_with_collector(
        self,
        tick_id: str,
        rows: list[dict],
        collector: object,
        now_ts: int,
    ) -> tuple[dict, Path]:
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim.json"), mock.patch.object(
            monitor, "CALENDAR_PATH", self._baseline_csv(tmp)
        ), mock.patch.object(monitor, "collect_window_bars", side_effect=collector):
            manifest = monitor.run_tick(
                {"plan_hash": "forward-plan-hash"},
                tick_id=tick_id,
                clients={"mexc": object(), "gateio": object()},
                fetcher=lambda: (rows, 2),
                now_ts=now_ts,
            )
        return manifest, tmp

    def _assert_cli_nonzero(self, manifest: dict) -> None:
        factory = lambda **_kwargs: object()  # noqa: E731
        tick_id = "fixture_cli_tick"
        with mock.patch.object(
            monitor, "load_and_validate_forward_plan", return_value={"plan_hash": "fixture"}
        ), mock.patch.object(monitor, "run_tick", return_value=manifest), mock.patch.object(
            monitor, "tick_status", return_value={"status": "fixture"}
        ), mock.patch.object(
            monitor,
            "consume_worker_handoff_receipt",
            return_value={
                "claim_run_id": f"{monitor.PLAN_ID}__{tick_id}",
                "claim_output_namespace": str((monitor.TICKS_DIR / tick_id).resolve()),
                "claim_ownership_token_sha256": hashlib.sha256(b"1" * 32).hexdigest(),
            },
        ), mock.patch.dict(
            "listing_event_history_collector.CLIENTS",
            {"mexc": factory, "gateio": factory},
            clear=True,
        ), mock.patch("builtins.print"):
            self.assertEqual(
                monitor.main([
                    "--tick",
                    "--confirmed-visible-tick",
                    "--tick-id",
                    tick_id,
                    "--worker-handoff-token",
                    "2" * 32,
                    "--claim-ownership-token",
                    "1" * 32,
                    "--plan-hash",
                    "fixture",
                ]),
                1,
            )

    def _assert_failed_claim_archive(self, root: Path, reason: str) -> None:
        self.assertFalse((root / "claim.json").exists())
        archives = list((root / "global-writer-claim-archive").glob("*.json"))
        self.assertEqual(len(archives), 1)
        archived = json.loads(archives[0].read_text(encoding="utf-8"))
        final_status = str(archived["final_status"])
        self.assertNotEqual(final_status.lower(), "completed")
        self.assertIn("STOPPED_INCOMPLETE", final_status)
        self.assertIn("RETRY_NEXT_INTERVAL", final_status)
        self.assertIn(reason, final_status)

    def test_fetcher_exception_releases_incomplete_claim_and_release_error_does_not_mask(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        actual_release = monitor.release_global_market_writer

        def fail_fetcher():
            running_path = tmp / "ticks" / "tick_fetcher_exception" / "manifest.json"
            self.assertTrue(running_path.is_file(), "RUNNING manifest is missing before fetcher")
            running = json.loads(running_path.read_text(encoding="utf-8"))
            self.assertEqual(running["status"], "RUNNING")
            self.assertEqual(running["evidence_stage"], "CLAIMED_PRE_FETCH")
            self.assertEqual(running["attempt_id"], "tick_fetcher_exception")
            self.assertTrue(running["ownership_token"])
            raise ValueError("fixture fetcher failed")

        def release_then_raise(*args, **kwargs):
            actual_release(*args, **kwargs)
            raise RuntimeError("fixture release failed after archive")

        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim.json"), mock.patch.object(
            monitor, "release_global_market_writer", side_effect=release_then_raise
        ):
            with self.assertRaisesRegex(ValueError, "fixture fetcher failed"):
                monitor.run_tick(
                    {"plan_hash": "forward-plan-hash"},
                    tick_id="tick_fetcher_exception",
                    clients={},
                    fetcher=fail_fetcher,
                )
        self._assert_failed_claim_archive(tmp, "fetch_or_prepare_exception")
        failure_manifest = json.loads(
            (tmp / "ticks" / "tick_fetcher_exception" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failure_manifest["status"], "STOPPED_INCOMPLETE")
        self.assertTrue(failure_manifest["pending_retry"])
        self.assertEqual(failure_manifest["stop_reason"], "fetch_or_prepare_exception")

    def test_blocking_fetcher_has_durable_running_evidence_before_release(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        fetch_entered = threading.Event()
        release_fetcher = threading.Event()
        errors: list[BaseException] = []

        def blocking_fetcher():
            fetch_entered.set()
            if not release_fetcher.wait(5):
                raise TimeoutError("fixture blocking fetcher release timed out")
            raise TimeoutError("fixture simulated fetch hang")

        def invoke_tick() -> None:
            try:
                monitor.run_tick(
                    {"plan_hash": "forward-plan-hash"},
                    tick_id="tick_blocking_fetcher",
                    clients={},
                    fetcher=blocking_fetcher,
                )
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim.json"):
            worker = threading.Thread(target=invoke_tick, daemon=True)
            worker.start()
            try:
                self.assertTrue(fetch_entered.wait(2), "fetcher was not entered")
                manifest_path = tmp / "ticks" / "tick_blocking_fetcher" / "manifest.json"
                self.assertTrue(manifest_path.is_file(), "blocked fetch has no durable RUNNING manifest")
                running = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(running["status"], "RUNNING")
                self.assertEqual(running["evidence_stage"], "CLAIMED_PRE_FETCH")
                self.assertTrue((tmp / "claim.json").is_file(), "claim disappeared while fetcher was blocked")
            finally:
                release_fetcher.set()
                worker.join(5)

        self.assertFalse(worker.is_alive(), "blocking fetcher test leaked its worker thread")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TimeoutError)
        final_manifest = json.loads(
            (tmp / "ticks" / "tick_blocking_fetcher" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(final_manifest["status"], "STOPPED_INCOMPLETE")
        self.assertTrue(final_manifest["pending_retry"])

    def test_release_rejects_mutated_plan_hash_or_owner_process_start(self) -> None:
        cases = (
            ("plan_hash", "mutated-plan-hash", "plan_hash mismatch"),
            (
                "owner_process_started_at_utc",
                "2000-01-01T00:00:00+00:00",
                "owner process start mismatch",
            ),
        )
        for field, mutated_value, error_pattern in cases:
            with self.subTest(field=field):
                tmp = Path(tempfile.mkdtemp())
                claim_path = tmp / "claim.json"

                def mutate_claim_before_release():
                    claim = json.loads(claim_path.read_text(encoding="utf-8"))
                    claim[field] = mutated_value
                    claim_path.write_text(json.dumps(claim), encoding="utf-8")
                    return [], 0

                with mock.patch.object(
                    monitor, "TICKS_DIR", tmp / "ticks"
                ), mock.patch.object(
                    monitor, "FORWARD_STATE_PATH", tmp / "state.json"
                ), mock.patch.object(
                    monitor, "CLAIM_PATH", claim_path
                ), mock.patch.object(
                    monitor, "CALENDAR_PATH", self._baseline_csv(tmp)
                ):
                    with self.assertRaisesRegex(
                        GlobalMarketWriterClaimError, error_pattern
                    ):
                        monitor.run_tick(
                            {"plan_hash": "forward-plan-hash"},
                            tick_id=f"tick_release_identity_{field}",
                            clients={},
                            fetcher=mutate_claim_before_release,
                            now_ts=AS_OF + DAY,
                        )
                preserved = json.loads(claim_path.read_text(encoding="utf-8"))
                self.assertEqual(preserved[field], mutated_value)
                self.assertEqual(preserved["status"], "CLAIMED")

    def test_terminal_manifest_persistence_exception_releases_incomplete_claim(self) -> None:
        import listing_event_history_collector as collector_module

        tmp = Path(tempfile.mkdtemp())
        actual_write_manifest = collector_module.write_manifest
        write_calls = 0

        def fail_terminal_manifest(path, payload):
            nonlocal write_calls
            write_calls += 1
            if write_calls == 1:
                raise OSError("fixture terminal manifest persistence failed")
            return actual_write_manifest(path, payload)

        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim.json"), mock.patch.object(
            monitor, "CALENDAR_PATH", self._baseline_csv(tmp)
        ), mock.patch.object(
            collector_module, "write_manifest", side_effect=fail_terminal_manifest
        ):
            with self.assertRaisesRegex(
                OSError, "fixture terminal manifest persistence failed"
            ):
                monitor.run_tick(
                    {"plan_hash": "forward-plan-hash"},
                    tick_id="tick_manifest_exception",
                    clients={},
                    fetcher=lambda: ([], 2),
                    now_ts=AS_OF + DAY,
                )
        self.assertEqual(write_calls, 1)
        self._assert_failed_claim_archive(tmp, "terminal_manifest_persistence_exception")
        failure_manifest = json.loads(
            (tmp / "ticks" / "tick_manifest_exception" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failure_manifest["status"], "STOPPED_INCOMPLETE")
        self.assertTrue(failure_manifest["pending_retry"])
        self.assertEqual(
            failure_manifest["stop_reason"],
            "terminal_manifest_persistence_exception",
        )

    def test_startup_reconciles_orphan_running_manifest_to_retry(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        tick_dir = tmp / "ticks" / "orphan_running"
        tick_dir.mkdir(parents=True)
        (tick_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_tick_manifest_v1",
                    "tick_id": "orphan_running",
                    "status": "RUNNING",
                    "started_at_utc": "2026-08-20T00:00:00Z",
                    "plan_hash": "forward-plan-hash",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"):
            result = monitor.reconcile_running_tick_manifests()
        self.assertEqual(result["reconciled"], 1)
        durable = json.loads((tick_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(durable["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(durable["stop_reason"], "interrupted_running_manifest")
        self.assertTrue(durable["pending_retry"])

    def test_state_rebuild_exception_releases_incomplete_claim(self) -> None:
        tmp = Path(tempfile.mkdtemp())

        def fail_rebuild_while_claim_is_held():
            self.assertTrue(
                (tmp / "claim.json").is_file(),
                "canonical claim was released before state rebuild",
            )
            raise RuntimeError("fixture state rebuild failed")

        with mock.patch.object(monitor, "TICKS_DIR", tmp / "ticks"), mock.patch.object(
            monitor, "FORWARD_STATE_PATH", tmp / "state.json"
        ), mock.patch.object(monitor, "CLAIM_PATH", tmp / "claim.json"), mock.patch.object(
            monitor, "CALENDAR_PATH", self._baseline_csv(tmp)
        ), mock.patch.object(
            monitor,
            "rebuild_forward_state",
            side_effect=fail_rebuild_while_claim_is_held,
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture state rebuild failed"):
                monitor.run_tick(
                    {"plan_hash": "forward-plan-hash"},
                    tick_id="tick_rebuild_exception",
                    clients={},
                    fetcher=lambda: ([], 2),
                    now_ts=AS_OF + DAY,
                )
        self._assert_failed_claim_archive(tmp, "state_rebuild_exception")

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

    def test_all_request_errors_are_durable_retry_and_nonzero(self) -> None:
        now = AS_OF + 10 * DAY
        proxy_ts = ((AS_OF + DAY) // HOUR) * HOUR
        rows = [
            {
                "exchange": "mexc",
                "base": "FAIL",
                "symbol": "FAILUSDT",
                "listed_ts": proxy_ts,
                "is_delisted": "false",
            }
        ]

        def fail_collection(*_args, **_kwargs):
            raise RuntimeError("fixture request failed")

        manifest, tmp = self._run_with_collector(
            "tick_all_error", rows, fail_collection, now
        )
        self.assertEqual(manifest["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(manifest["stop_reason"], "all_jobs_request_error")
        self.assertEqual(manifest["retry_disposition"], "RETRY_NEXT_INTERVAL")
        self.assertTrue(manifest["pending_retry"])
        self.assertEqual(manifest["jobs_total"], 1)
        self.assertEqual(manifest["jobs_attempted"], 1)
        self.assertEqual(manifest["jobs_succeeded"], 0)
        self.assertEqual(manifest["jobs_failed"], 1)
        self.assertEqual(manifest["jobs_pending_retry"], 1)
        self.assertEqual(manifest["jobs"][0]["job_status"], "FAILED_RETRY_NEXT_INTERVAL")
        self.assertEqual(manifest["retry_queue"][0]["symbol"], "FAILUSDT")
        self.assertEqual(
            manifest["retry_queue"][0]["retry_disposition"],
            "RETRY_NEXT_INTERVAL",
        )
        durable = json.loads(
            (tmp / "ticks" / "tick_all_error" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(durable["retry_queue"], manifest["retry_queue"])
        self.assertEqual((tmp / "ticks" / "tick_all_error" / "ohlcv.jsonl").read_text(), "")
        self.assertFalse((tmp / "claim.json").exists())
        self._assert_cli_nonzero(manifest)

    def test_mixed_request_error_preserves_rows_and_retains_failed_job(self) -> None:
        now = AS_OF + 10 * DAY
        proxy_ts = ((AS_OF + DAY) // HOUR) * HOUR
        rows = [
            {
                "exchange": "mexc",
                "base": "GOOD",
                "symbol": "GOODUSDT",
                "listed_ts": proxy_ts,
                "is_delisted": "false",
            },
            {
                "exchange": "mexc",
                "base": "FAIL",
                "symbol": "FAILUSDT",
                "listed_ts": proxy_ts,
                "is_delisted": "false",
            },
        ]

        def mixed_collection(_client, job, **_kwargs):
            if job["symbol"] == "FAILUSDT":
                raise RuntimeError("fixture request failed")
            return make_bars(proxy_ts, proxy_ts + 71 * HOUR), 1

        manifest, tmp = self._run_with_collector(
            "tick_mixed_error", rows, mixed_collection, now
        )
        self.assertEqual(manifest["status"], "PARTIAL_RETRY_NEXT_INTERVAL")
        self.assertEqual(manifest["stop_reason"], "partial_job_request_error")
        self.assertEqual(manifest["retry_disposition"], "RETRY_NEXT_INTERVAL")
        self.assertTrue(manifest["pending_retry"])
        self.assertEqual(manifest["jobs_total"], 2)
        self.assertEqual(manifest["jobs_attempted"], 2)
        self.assertEqual(manifest["jobs_succeeded"], 1)
        self.assertEqual(manifest["jobs_failed"], 1)
        self.assertEqual(manifest["jobs_pending_retry"], 1)
        self.assertEqual(manifest["rows_written"], 72)
        self.assertEqual([row["symbol"] for row in manifest["retry_queue"]], ["FAILUSDT"])
        durable_rows = (
            tmp / "ticks" / "tick_mixed_error" / "ohlcv.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(durable_rows), 72)
        self.assertTrue(all(json.loads(row)["symbol"] == "GOODUSDT" for row in durable_rows))
        durable_manifest = json.loads(
            (tmp / "ticks" / "tick_mixed_error" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(durable_manifest["retry_queue"], manifest["retry_queue"])
        self._assert_cli_nonzero(manifest)

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

    def test_technical_rebind_preserves_previous_immutable_plan(self) -> None:
        previous_path = (
            ROOT
            / "docs/plans"
            / "slow-liquidity-listing-momentum-forward-monitor-planonly-20260821-v3.json"
        )
        self.assertEqual(
            hashlib.sha256(previous_path.read_bytes()).hexdigest(),
            "b4e6b085c40e10c91cc235f186e46f52e56fc6f6d913b79f0b707172d4bc99f4",
        )
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        plan = plan_module.build_forward_monitor_plan("2026-08-17T12:45:00Z")
        rebind = plan["source_bindings"]["technical_rebind"]
        self.assertEqual(
            rebind["supersedes_plan_hash"],
            previous["plan_hash"],
        )
        self.assertEqual(
            rebind["supersedes_plan_file_sha256"],
            hashlib.sha256(previous_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(rebind["supersedes_plan_path"], str(previous_path))
        # A scope change may be declared, never merely asserted. False keeps the plan a
        # pure technical rebind; True is admitted only with a declaration that enumerates
        # what moved, says why, and records that autopilot authority is withdrawn -
        # autopilot_guard admits only same-scope rebinds, and is deliberately unrelaxed.
        if rebind["research_scope_changed"] is False:
            self.assertNotIn("research_scope_change", rebind)
        else:
            self.assertIs(rebind["research_scope_changed"], True)
            declaration = rebind["research_scope_change"]
            self.assertTrue(declaration["changed_fields"])
            self.assertTrue(all(f.strip() for f in declaration["changed_fields"]))
            self.assertTrue(declaration["reason"].strip())
            self.assertEqual(
                declaration["autopilot_authority"], "WITHDRAWN_UNTIL_REVIEWED"
            )

    def test_a_scope_change_without_its_declaration_is_refused(self) -> None:
        plan = plan_module.build_forward_monitor_plan("2026-08-17T12:45:00Z")
        rebind = plan["source_bindings"]["technical_rebind"]
        rebind["research_scope_changed"] = True
        rebind.pop("research_scope_change", None)
        with self.assertRaisesRegex(Exception, "must carry its declaration"):
            plan_module.validate_forward_monitor_plan(plan)

    def test_a_first_appearance_role_may_not_claim_to_supersede(self) -> None:
        # The rule that lets the role set grow at all: a role the superseded plan did not
        # carry has nothing to replace, so a borrowed hash must be refused outright.
        plan = plan_module.build_forward_monitor_plan("2026-08-17T12:45:00Z")
        row = next(
            item
            for item in plan["implementation"]["files"]
            if item["role"] == "cadence_policy"
        )
        self.assertIsNone(row["provenance"]["superseded_sha256"])
        row["provenance"]["superseded_sha256"] = "0" * 64
        row["provenance"]["kind"] = "technical_rebind_from_superseded_plan_row"
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(Exception, "must not claim to supersede"):
            plan_module.validate_forward_monitor_plan(plan)

    def test_monitor_rejects_stale_implementation_binding(self) -> None:
        plan = plan_module.build_forward_monitor_plan("2026-08-17T12:45:00Z")
        launcher = next(
            item
            for item in plan["implementation"]["files"]
            if item["role"] == "visible_launcher"
        )
        launcher["sha256"] = "0" * 64
        plan["plan_hash"] = canonical_hash(plan)
        with tempfile.TemporaryDirectory() as temp_dir:
            plan_path = Path(temp_dir) / "stale-plan.json"
            plan_path.write_text(
                json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                monitor.ForwardMonitorError,
                "implementation sha256 mismatch",
            ):
                monitor.load_and_validate_forward_plan(plan_path)

    def test_launcher_preflight_runs_hash_bound_plan_check(self) -> None:
        launcher_path = (
            ROOT / "tools" / "start_listing_momentum_forward_tick_visible.ps1"
        )
        launcher = launcher_path.read_text(encoding="utf-8-sig")
        self.assertIn("--plan-check", launcher)
        self.assertIn("plan_check_status", launcher)

    def test_monitor_accepts_frozen_plan(self) -> None:
        if not plan_module.FORWARD_PLAN_PATH.is_file():
            raise FileNotFoundError(plan_module.FORWARD_PLAN_PATH)
        plan = monitor.load_and_validate_forward_plan(plan_module.FORWARD_PLAN_PATH)
        self.assertEqual(plan["plan_id"], monitor.PLAN_ID)


if __name__ == "__main__":
    unittest.main()
