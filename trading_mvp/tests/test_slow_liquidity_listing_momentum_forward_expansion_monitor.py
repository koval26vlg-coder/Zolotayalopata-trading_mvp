from __future__ import annotations

import hashlib
import json
import os
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

import slow_liquidity_listing_momentum_forward_expansion_monitor as monitor  # noqa: E402
import slow_liquidity_listing_momentum_forward_expansion_plan as plan_module  # noqa: E402
from listing_momentum_exchange_expansion import Candle  # noqa: E402
from global_market_writer_claim import (  # noqa: E402
    GlobalMarketWriterClaimError,
    claim_global_market_writer,
)


class FakeClient:
    max_candles_per_request = 1000

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, int, int]] = []

    def fetch_ohlcv(self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int):
        self.calls.append((symbol, granularity, start_ts, end_ts, limit))
        return [
            Candle(
                ts=start_ts,
                open=1.0,
                high=1.2,
                low=0.9,
                close=1.1,
                volume=10.0,
                quote_volume=11.0,
            )
        ]


class ExpansionMonitorTests(unittest.TestCase):
    def test_asset_provenance_survives_candidate_job_and_forward_row(self) -> None:
        candidates = monitor.diff_new_listings(
            set(),
            [
                {
                    "exchange": "okx",
                    "base": "XAPLD",
                    "symbol": "XAPLD-USDT",
                    "is_delisted": False,
                    "listed_ts": 1_710_000_000,
                    "asset_class": "tokenized_equity",
                    "asset_class_source": "declared_spot_asset_registry_v1",
                    "asset_class_acceptance_eligible": False,
                }
            ],
            baseline_as_of_ts=1_709_000_000,
            now_ts=1_710_000_100,
        )

        jobs = monitor.derive_forward_jobs(candidates)
        forward = monitor._forward_row(
            jobs[0],
            Candle(
                ts=jobs[0]["proxy_ts"],
                open=1.0,
                high=1.2,
                low=0.9,
                close=1.1,
                volume=10.0,
                quote_volume=11.0,
            ),
        )

        for row in (candidates[0], jobs[0], forward):
            self.assertEqual(row["asset_class"], "tokenized_equity")
            self.assertEqual(
                row["asset_class_source"], "declared_spot_asset_registry_v1"
            )
            self.assertFalse(row["asset_class_acceptance_eligible"])

    def test_rebuild_preserves_asset_provenance_and_quarantines_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            modern = root / "ticks" / "modern"
            legacy = root / "ticks" / "legacy"
            modern.mkdir(parents=True)
            legacy.mkdir(parents=True)
            modern_job = {
                "exchange": "okx",
                "base": "XAPLD",
                "symbol": "XAPLD-USDT",
                "category": "new_listing_window_complete",
                "timestamp_source": "listTime_ms",
                "flags": [],
                "asset_class": "tokenized_equity",
                "asset_class_source": "declared_spot_asset_registry_v1",
                "asset_class_acceptance_eligible": False,
            }
            legacy_job = {
                "exchange": "okx",
                "base": "HYPE",
                "symbol": "HYPE-USDT",
                "category": "new_listing_window_complete",
                "timestamp_source": "listTime_ms",
                "flags": [],
            }
            for tick_dir, tick_id, job in (
                (modern, "modern", modern_job),
                (legacy, "legacy", legacy_job),
            ):
                (tick_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "tick_id": tick_id,
                            "status": "COMPLETED",
                            "new_listing_count": 1,
                            "rows_written": 1,
                            "jobs": [job],
                        }
                    ),
                    encoding="utf-8",
                )
            (modern / "ohlcv.jsonl").write_text(
                json.dumps(
                    {
                        "exchange": "okx",
                        "base": "XAPLD",
                        "ts": 1_710_000_000,
                        "open": 1.0,
                        "high": 1.2,
                        "low": 0.9,
                        "close": 1.1,
                        "volume": 10.0,
                        "asset_class": "tokenized_equity",
                        "asset_class_source": "declared_spot_asset_registry_v1",
                        "asset_class_acceptance_eligible": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (legacy / "ohlcv.jsonl").write_text(
                json.dumps(
                    {
                        "exchange": "okx",
                        "base": "HYPE",
                        "ts": 1_710_000_000,
                        "open": 2.0,
                        "high": 2.2,
                        "low": 1.9,
                        "close": 2.1,
                        "volume": 20.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
                monitor, "STATE_PATH", root / "state.json"
            ):
                state = monitor.rebuild_forward_state()

        by_base = {window["base"]: window for window in state["windows"]}
        self.assertEqual(by_base["XAPLD"]["asset_class"], "tokenized_equity")
        self.assertFalse(by_base["XAPLD"]["asset_class_acceptance_eligible"])
        self.assertEqual(by_base["HYPE"]["asset_class"], "unclassified")
        self.assertEqual(
            by_base["HYPE"]["asset_class_source"],
            "legacy_missing_asset_provenance",
        )
        self.assertFalse(by_base["HYPE"]["asset_class_acceptance_eligible"])
        self.assertEqual(state["crypto_acceptance_window_count"], 0)
        self.assertEqual(state["descriptive_only_window_count"], 2)

    def test_direct_cli_tick_flag_cannot_bypass_launcher_handoff(self) -> None:
        with mock.patch.object(
            monitor, "load_plan", return_value={"plan_hash": "a" * 64}
        ), mock.patch.object(monitor, "run_tick") as run_tick_mock:
            with self.assertRaises(SystemExit):
                monitor.main(["--tick", "--confirmed-visible-tick"])
            run_tick_mock.assert_not_called()

    def _run_with_collector(
        self,
        tick_id: str,
        rows: list[dict],
        collector: object,
        now_ts: int,
    ) -> tuple[dict, Path]:
        root = Path(tempfile.mkdtemp())
        baseline_path = root / "preflight.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "schema": "fixture",
                    "venues": [
                        {
                            "exchange": "binance",
                            "snapshot_rows": [
                                {"exchange": "binance", "symbol": "BTCUSDT"}
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        plan = {
            "plan_hash": "fixture-plan",
            "source_bindings": {
                "preflight": {
                    "path": str(baseline_path),
                    "baseline_as_of_ts": now_ts - 3600,
                }
            },
        }
        with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
            monitor, "STATE_PATH", root / "state.json"
        ), mock.patch.object(
            monitor, "CLAIM_PATH", root / "active-market-data-writer-claim.json"
        ), mock.patch.object(
            monitor,
            "LEGACY_CLAIM_PATH",
            root / "active-market-data-writer-expansion-claim.json",
            create=True,
        ), mock.patch.object(monitor, "collect_window_bars", side_effect=collector):
            manifest = monitor.run_tick(
                plan,
                tick_id=tick_id,
                clients={venue: object() for venue in monitor.SUPPORTED_VENUES},
                fetcher=lambda: (rows, len(monitor.SUPPORTED_VENUES)),
                now_ts=now_ts,
            )
        return manifest, root

    def _assert_cli_nonzero(self, manifest: dict) -> None:
        tick_id = "fixture_cli_tick"
        with mock.patch.object(
            monitor, "load_plan", return_value={"plan_hash": "fixture"}
        ), mock.patch.object(monitor, "ExpansionSpotOhlcvClient", return_value=object()), mock.patch.object(
            monitor, "run_tick", return_value=manifest
        ), mock.patch.object(
            monitor, "tick_status", return_value={"status": "fixture"}
        ), mock.patch.object(
            monitor,
            "consume_worker_handoff_receipt",
            return_value={
                "claim_run_id": f"{monitor.PLAN_ID}__{tick_id}",
                "claim_output_namespace": str((monitor.TICKS_DIR / tick_id).resolve()),
                "claim_ownership_token_sha256": hashlib.sha256(b"1" * 32).hexdigest(),
            },
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

    def _write_baseline(self, root: Path, now_ts: int) -> tuple[Path, dict]:
        baseline_path = root / "preflight.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "schema": "fixture",
                    "venues": [
                        {
                            "exchange": "binance",
                            "snapshot_rows": [
                                {"exchange": "binance", "symbol": "BTCUSDT"}
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return baseline_path, {
            "plan_hash": "fixture-plan",
            "source_bindings": {
                "preflight": {
                    "path": str(baseline_path),
                    "baseline_as_of_ts": now_ts - 3600,
                }
            },
        }

    def _assert_failed_claim_archive(self, root: Path, reason: str) -> None:
        claim_path = root / "active-market-data-writer-claim.json"
        self.assertFalse(claim_path.exists())
        archives = list((root / "global-writer-claim-archive").glob("*.json"))
        self.assertEqual(len(archives), 1)
        archived = json.loads(archives[0].read_text(encoding="utf-8"))
        final_status = str(archived["final_status"])
        self.assertNotEqual(final_status.lower(), "completed")
        self.assertIn("STOPPED_INCOMPLETE", final_status)
        self.assertIn("RETRY_NEXT_INTERVAL", final_status)
        self.assertIn(reason, final_status)

    def test_fetcher_exception_releases_incomplete_claim_and_release_error_does_not_mask(self) -> None:
        root = Path(tempfile.mkdtemp())
        actual_release = monitor.release_global_market_writer

        def fail_fetcher():
            running_path = root / "ticks" / "expansion_fetcher_exception" / "manifest.json"
            self.assertTrue(running_path.is_file(), "RUNNING manifest is missing before fetcher")
            running = json.loads(running_path.read_text(encoding="utf-8"))
            self.assertEqual(running["status"], "RUNNING")
            self.assertEqual(running["evidence_stage"], "CLAIMED_PRE_FETCH")
            self.assertEqual(running["attempt_id"], "expansion_fetcher_exception")
            self.assertTrue(running["ownership_token"])
            raise ValueError("fixture fetcher failed")

        def release_then_raise(*args, **kwargs):
            actual_release(*args, **kwargs)
            raise RuntimeError("fixture release failed after archive")

        with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
            monitor, "STATE_PATH", root / "state.json"
        ), mock.patch.object(
            monitor,
            "CLAIM_PATH",
            root / "active-market-data-writer-claim.json",
        ), mock.patch.object(
            monitor,
            "LEGACY_CLAIM_PATH",
            root / "active-market-data-writer-expansion-claim.json",
            create=True,
        ), mock.patch.object(
            monitor, "release_global_market_writer", side_effect=release_then_raise
        ):
            with self.assertRaisesRegex(ValueError, "fixture fetcher failed"):
                monitor.run_tick(
                    {"plan_hash": "fixture-plan", "source_bindings": {"preflight": {}}},
                    tick_id="expansion_fetcher_exception",
                    clients={},
                    fetcher=fail_fetcher,
                )
        self._assert_failed_claim_archive(root, "fetch_or_prepare_exception")
        failure_manifest = json.loads(
            (root / "ticks" / "expansion_fetcher_exception" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failure_manifest["status"], "STOPPED_INCOMPLETE")
        self.assertTrue(failure_manifest["pending_retry"])
        self.assertEqual(failure_manifest["stop_reason"], "fetch_or_prepare_exception")

    def test_blocking_fetcher_has_durable_running_evidence_before_release(self) -> None:
        root = Path(tempfile.mkdtemp())
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
                    {"plan_hash": "fixture-plan", "source_bindings": {"preflight": {}}},
                    tick_id="expansion_blocking_fetcher",
                    clients={},
                    fetcher=blocking_fetcher,
                )
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
            monitor, "STATE_PATH", root / "state.json"
        ), mock.patch.object(
            monitor, "CLAIM_PATH", root / "active-market-data-writer-claim.json"
        ), mock.patch.object(
            monitor,
            "LEGACY_CLAIM_PATH",
            root / "active-market-data-writer-expansion-claim.json",
            create=True,
        ):
            worker = threading.Thread(target=invoke_tick, daemon=True)
            worker.start()
            try:
                self.assertTrue(fetch_entered.wait(2), "fetcher was not entered")
                manifest_path = root / "ticks" / "expansion_blocking_fetcher" / "manifest.json"
                self.assertTrue(manifest_path.is_file(), "blocked fetch has no durable RUNNING manifest")
                running = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(running["status"], "RUNNING")
                self.assertEqual(running["evidence_stage"], "CLAIMED_PRE_FETCH")
                self.assertTrue(
                    (root / "active-market-data-writer-claim.json").is_file(),
                    "claim disappeared while fetcher was blocked",
                )
            finally:
                release_fetcher.set()
                worker.join(5)

        self.assertFalse(worker.is_alive(), "blocking fetcher test leaked its worker thread")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TimeoutError)
        final_manifest = json.loads(
            (root / "ticks" / "expansion_blocking_fetcher" / "manifest.json").read_text(encoding="utf-8")
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
                root = Path(tempfile.mkdtemp())
                _, plan = self._write_baseline(root, 1_710_000_000)
                claim_path = root / "active-market-data-writer-claim.json"

                def mutate_claim_before_release():
                    claim = json.loads(claim_path.read_text(encoding="utf-8"))
                    claim[field] = mutated_value
                    claim_path.write_text(json.dumps(claim), encoding="utf-8")
                    return [], 0

                with mock.patch.object(
                    monitor, "TICKS_DIR", root / "ticks"
                ), mock.patch.object(
                    monitor, "STATE_PATH", root / "state.json"
                ), mock.patch.object(
                    monitor, "CLAIM_PATH", claim_path
                ), mock.patch.object(
                    monitor,
                    "LEGACY_CLAIM_PATH",
                    root / "active-market-data-writer-expansion-claim.json",
                    create=True,
                ):
                    with self.assertRaisesRegex(
                        GlobalMarketWriterClaimError, error_pattern
                    ):
                        monitor.run_tick(
                            plan,
                            tick_id=f"expansion_release_identity_{field}",
                            clients={},
                            fetcher=mutate_claim_before_release,
                            now_ts=1_710_000_000,
                        )
                preserved = json.loads(claim_path.read_text(encoding="utf-8"))
                self.assertEqual(preserved[field], mutated_value)
                self.assertEqual(preserved["status"], "CLAIMED")

    def test_terminal_manifest_persistence_exception_releases_incomplete_claim(self) -> None:
        import listing_event_history_collector as collector_module

        root = Path(tempfile.mkdtemp())
        _, plan = self._write_baseline(root, 1_710_000_000)
        actual_write_manifest = collector_module.write_manifest
        write_calls = 0

        def fail_terminal_manifest(path, payload):
            nonlocal write_calls
            write_calls += 1
            if write_calls == 1:
                raise OSError("fixture terminal manifest persistence failed")
            return actual_write_manifest(path, payload)

        with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
            monitor, "STATE_PATH", root / "state.json"
        ), mock.patch.object(
            monitor,
            "CLAIM_PATH",
            root / "active-market-data-writer-claim.json",
        ), mock.patch.object(
            monitor,
            "LEGACY_CLAIM_PATH",
            root / "active-market-data-writer-expansion-claim.json",
            create=True,
        ), mock.patch.object(
            collector_module, "write_manifest", side_effect=fail_terminal_manifest
        ):
            with self.assertRaisesRegex(
                OSError, "fixture terminal manifest persistence failed"
            ):
                monitor.run_tick(
                    plan,
                    tick_id="expansion_manifest_exception",
                    clients={},
                    fetcher=lambda: ([], len(monitor.SUPPORTED_VENUES)),
                    now_ts=1_710_000_000,
                )
        self.assertEqual(write_calls, 1)
        self._assert_failed_claim_archive(
            root, "terminal_manifest_persistence_exception"
        )
        failure_manifest = json.loads(
            (root / "ticks" / "expansion_manifest_exception" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failure_manifest["status"], "STOPPED_INCOMPLETE")
        self.assertTrue(failure_manifest["pending_retry"])
        self.assertEqual(
            failure_manifest["stop_reason"],
            "terminal_manifest_persistence_exception",
        )

    def test_startup_reconciles_orphan_running_manifest_to_retry(self) -> None:
        root = Path(tempfile.mkdtemp())
        tick_dir = root / "ticks" / "orphan_running"
        tick_dir.mkdir(parents=True)
        (tick_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": "trading_mvp_slow_liquidity_listing_momentum_forward_expansion_tick_manifest_v1",
                    "tick_id": "orphan_running",
                    "status": "RUNNING",
                    "started_at_utc": "2026-08-20T00:00:00Z",
                    "plan_hash": "fixture-plan",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"):
            result = monitor.reconcile_running_tick_manifests()
        self.assertEqual(result["reconciled"], 1)
        durable = json.loads((tick_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(durable["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(durable["stop_reason"], "interrupted_running_manifest")
        self.assertTrue(durable["pending_retry"])

    def test_state_rebuild_exception_releases_incomplete_claim(self) -> None:
        root = Path(tempfile.mkdtemp())
        _, plan = self._write_baseline(root, 1_710_000_000)

        def fail_rebuild_while_claim_is_held():
            self.assertTrue(
                (root / "active-market-data-writer-claim.json").is_file(),
                "canonical claim was released before state rebuild",
            )
            raise RuntimeError("fixture state rebuild failed")

        with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
            monitor, "STATE_PATH", root / "state.json"
        ), mock.patch.object(
            monitor,
            "CLAIM_PATH",
            root / "active-market-data-writer-claim.json",
        ), mock.patch.object(
            monitor,
            "LEGACY_CLAIM_PATH",
            root / "active-market-data-writer-expansion-claim.json",
            create=True,
        ), mock.patch.object(
            monitor,
            "rebuild_forward_state",
            side_effect=fail_rebuild_while_claim_is_held,
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture state rebuild failed"):
                monitor.run_tick(
                    plan,
                    tick_id="expansion_rebuild_exception",
                    clients={},
                    fetcher=lambda: ([], len(monitor.SUPPORTED_VENUES)),
                    now_ts=1_710_000_000,
                )
        self._assert_failed_claim_archive(root, "state_rebuild_exception")

    def test_live_canonical_claim_blocks_before_fetch_or_tick_writes(self) -> None:
        canonical = ROOT / "docs" / "agent-log" / "active-market-data-writer-claim.json"
        self.assertEqual(canonical.resolve(), monitor.CLAIM_PATH.resolve())

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            canonical_claim = root / "active-market-data-writer-claim.json"
            legacy_claim = root / "active-market-data-writer-expansion-claim.json"
            ticks = root / "ticks"
            fetch_calls = 0
            claim_global_market_writer(
                canonical_claim,
                run_id="existing_writer",
                owner_pid=os.getpid(),
                owner_kind="fixture",
                plan_hash="a" * 64,
                output_namespace=root / "existing-output",
            )

            def forbidden_fetcher():
                nonlocal fetch_calls
                fetch_calls += 1
                return [], 0

            with mock.patch.object(monitor, "TICKS_DIR", ticks), mock.patch.object(
                monitor, "STATE_PATH", root / "state.json"
            ), mock.patch.object(monitor, "CLAIM_PATH", canonical_claim), mock.patch.object(
                monitor, "LEGACY_CLAIM_PATH", legacy_claim, create=True
            ):
                with self.assertRaises(GlobalMarketWriterClaimError):
                    monitor.run_tick(
                        {"plan_hash": "fixture"},
                        tick_id="blocked_tick",
                        clients={},
                        fetcher=forbidden_fetcher,
                    )

            self.assertEqual(0, fetch_calls)
            self.assertFalse(ticks.exists())

    def test_live_or_corrupt_legacy_expansion_claim_fails_closed_before_fetch(self) -> None:
        fixtures = {
            "live": json.dumps(
                {
                    "schema": "legacy_expansion_claim_v1",
                    "pid": os.getpid(),
                    "claimed_at_utc": "2026-08-20T00:00:00Z",
                }
            ),
            "corrupt": "{not-json",
        }
        for label, contents in fixtures.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                legacy_claim = root / "active-market-data-writer-expansion-claim.json"
                legacy_claim.write_text(contents, encoding="utf-8")
                fetch_calls = 0

                def forbidden_fetcher():
                    nonlocal fetch_calls
                    fetch_calls += 1
                    return [], 0

                with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
                    monitor, "STATE_PATH", root / "state.json"
                ), mock.patch.object(
                    monitor, "CLAIM_PATH", root / "active-market-data-writer-claim.json"
                ), mock.patch.object(
                    monitor, "LEGACY_CLAIM_PATH", legacy_claim, create=True
                ):
                    with self.assertRaisesRegex(
                        monitor.ExpansionMonitorError,
                        "legacy expansion writer claim",
                    ):
                        monitor.run_tick(
                            {"plan_hash": "fixture"},
                            tick_id=f"legacy_{label}",
                            clients={},
                            fetcher=forbidden_fetcher,
                        )

                self.assertEqual(0, fetch_calls)
                self.assertFalse((root / "ticks").exists())

    def test_expansion_launcher_checks_canonical_and_legacy_claim_paths(self) -> None:
        source = (
            ROOT / "tools" / "start_listing_momentum_forward_expansion_tick_visible.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn('active-market-data-writer-claim.json"', source)
        self.assertIn("active-market-data-writer-expansion-claim.json", source)
        self.assertIn("legacy_expansion_writer_claim_exists", source)

    def test_all_request_errors_are_durable_retry_and_nonzero(self) -> None:
        now_ts = 1_710_000_000
        rows = [
            {
                "exchange": "binance",
                "base": "FAIL",
                "symbol": "FAILUSDT",
                "is_delisted": False,
                "listed_ts": None,
            }
        ]

        def fail_collection(*_args, **_kwargs):
            raise RuntimeError("fixture request failed")

        manifest, root = self._run_with_collector(
            "expansion_all_error", rows, fail_collection, now_ts
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
            (root / "ticks" / "expansion_all_error" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(durable["retry_queue"], manifest["retry_queue"])
        self.assertEqual(
            (root / "ticks" / "expansion_all_error" / "ohlcv.jsonl").read_text(),
            "",
        )
        self._assert_cli_nonzero(manifest)

    def test_mixed_request_error_preserves_rows_and_retains_failed_job(self) -> None:
        now_ts = 1_710_000_000
        rows = [
            {
                "exchange": "binance",
                "base": "GOOD",
                "symbol": "GOODUSDT",
                "is_delisted": False,
                "listed_ts": None,
            },
            {
                "exchange": "binance",
                "base": "FAIL",
                "symbol": "FAILUSDT",
                "is_delisted": False,
                "listed_ts": None,
            },
        ]

        def mixed_collection(_client, job, **_kwargs):
            if job["symbol"] == "FAILUSDT":
                raise RuntimeError("fixture request failed")
            return (
                [
                    Candle(
                        ts=job["proxy_ts"],
                        open=1.0,
                        high=1.2,
                        low=0.9,
                        close=1.1,
                        volume=10.0,
                        quote_volume=11.0,
                    )
                ],
                1,
            )

        manifest, root = self._run_with_collector(
            "expansion_mixed_error", rows, mixed_collection, now_ts
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
        self.assertEqual(manifest["rows_written"], 1)
        self.assertEqual([row["symbol"] for row in manifest["retry_queue"]], ["FAILUSDT"])
        durable_rows = (
            root / "ticks" / "expansion_mixed_error" / "ohlcv.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(durable_rows), 1)
        self.assertEqual(json.loads(durable_rows[0])["symbol"], "GOODUSDT")
        durable_manifest = json.loads(
            (root / "ticks" / "expansion_mixed_error" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(durable_manifest["retry_queue"], manifest["retry_queue"])
        self._assert_cli_nonzero(manifest)

    def test_detection_time_proxy_is_explicit(self) -> None:
        baseline = {
            "schema": "fixture",
            "venues": [
                {
                    "exchange": "binance",
                    "snapshot_rows": [
                        {"exchange": "binance", "symbol": "BTCUSDT"}
                    ],
                }
            ],
        }
        now_ts = 1_710_000_000
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline_path = root / "preflight.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            plan = {
                "plan_hash": "fixture-plan",
                "source_bindings": {
                    "preflight": {
                        "path": str(baseline_path),
                        "baseline_as_of_ts": now_ts - 3600,
                    }
                },
            }
            fake_client = FakeClient()
            with mock.patch.object(monitor, "TICKS_DIR", root / "ticks"), mock.patch.object(
                monitor, "STATE_PATH", root / "state.json"
            ), mock.patch.object(monitor, "CLAIM_PATH", root / "claim.json"), mock.patch.object(
                monitor, "SLEEP_SEC", 0
            ):
                manifest = monitor.run_tick(
                    plan,
                    tick_id="fixture_tick",
                    clients={
                        "binance": fake_client,
                        "bybit": fake_client,
                        "okx": fake_client,
                        "bitget": fake_client,
                    },
                    fetcher=lambda: (
                        [
                            {
                                "exchange": "binance",
                                "base": "NEW",
                                "symbol": "NEWUSDT",
                                "is_delisted": False,
                                "listed_ts": None,
                            }
                        ],
                        4,
                    ),
                    now_ts=now_ts,
                )
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(manifest["new_listing_count"], 1)
            self.assertEqual(manifest["jobs"][0]["timestamp_source"], "snapshot_diff_detection_time_proxy")
            self.assertEqual(manifest["jobs"][0]["asset_class"], "unclassified")
            self.assertEqual(
                manifest["jobs"][0]["asset_class_source"],
                "unclassified_no_positive_identity",
            )
            self.assertFalse(
                manifest["jobs"][0]["asset_class_acceptance_eligible"]
            )
            self.assertTrue(fake_client.calls)
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["venues"], ["binance", "bybit", "okx", "bitget"])


class ExpansionPlanTests(unittest.TestCase):
    def test_checked_in_plan_is_hash_bound_and_isolated_from_v2(self) -> None:
        plan = json.loads(plan_module.FORWARD_PLAN_PATH.read_text(encoding="utf-8"))
        plan_module.validate_plan(plan)
        self.assertEqual(plan["status"], "READY_FOR_VISIBLE_EXPANSION_TICKS")
        self.assertEqual(plan["venues"], ["binance", "bybit", "okx", "bitget"])
        self.assertTrue(plan["source_bindings"]["parent_v2"]["parallel_immutable"])
        self.assertEqual(
            plan["source_bindings"]["parent_v2"]["canonical_repository"],
            r"C:\Users\koval\Documents\ZolotyayLopata-listing-momentum-monitor",
        )
        self.assertNotIn(
            "automation_launcher",
            {row["role"] for row in plan["implementation"]["files"]},
        )
        self.assertTrue(plan["guard_contract"]["v2_namespace_must_remain_untouched"])
        self.assertFalse(plan["evaluator_or_oos_allowed"])
        self.assertFalse(plan["replay_allowed"])

    def test_plan_writer_is_idempotent_and_refuses_different_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "immutable.json"
            first = {"plan_id": "fixture_v1", "plan_hash": "a" * 64}
            second = {"plan_id": "fixture_v1", "plan_hash": "b" * 64}
            plan_module.write_immutable_plan(path, first)
            plan_module.write_immutable_plan(path, first)
            with self.assertRaisesRegex(Exception, "immutable artifact mismatch"):
                plan_module.write_immutable_plan(path, second)


if __name__ == "__main__":
    unittest.main()
