from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import premarket_automation as premarket_automation_module  # noqa: E402
from premarket_automation import (  # noqa: E402
    AutomationPaths,
    append_attempt,
    capture_websocket_events,
    discover_and_snapshot,
    load_state,
    mark_retry_next_interval,
)
from premarket_plan import validate_plan  # noqa: E402
from global_market_writer_claim import claim_global_market_writer  # noqa: E402
from premarket_perp import (  # noqa: E402
    EXIT_OFFSETS_SEC,
    PreMarketPhase,
    SourceClass,
    build_entry_candidates,
    evaluate_evidence_gate,
    normalize_bybit_instrument,
    normalize_gate_instrument,
    normalize_okx_instrument,
    normalize_market_event,
    replay_listing_event,
)


class PreMarketPerpTests(unittest.TestCase):
    def test_cli_tick_requires_bound_worker_handoff_before_run_tick(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            sys,
            "argv",
            [
                "premarket_automation.py",
                "--repo-root",
                temp_dir,
                "--tick",
            ],
        ), patch.object(premarket_automation_module, "run_tick") as run_tick_mock:
            with self.assertRaises(SystemExit):
                premarket_automation_module._main()
            run_tick_mock.assert_not_called()
            self.assertEqual([], list(Path(temp_dir).rglob("*")))

    def test_cli_consumes_bound_handoff_and_reuses_wrapper_attempt_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            paths = premarket_automation_module._default_paths(repo)
            attempt_id = "premarket_perp_automation_fixture"
            plan_hash = "a" * 64
            handoff_token = "2" * 32
            claim_token = "3" * 32
            output_namespace = repo / "exports" / "trading-mvp" / "premarket-perp"
            claim = claim_global_market_writer(
                repo / "docs" / "agent-log" / "active-market-data-writer-claim.json",
                run_id=attempt_id,
                owner_pid=os.getpid(),
                owner_kind="premarket_perp_visible_worker",
                plan_hash=plan_hash,
                output_namespace=output_namespace,
                writer_pid=os.getpid(),
                terminal_pid=os.getpid(),
                ownership_token=claim_token,
            )
            state = premarket_automation_module.load_state(paths)
            state.update({
                "status": "RUNNING",
                "attempt_count": 1,
                "last_attempt_id": attempt_id,
                "last_started_at_utc": claim["claimed_at_utc"],
                "worker_pid": os.getpid(),
                "worker_process_started_at_utc": claim["owner_process_started_at_utc"],
            })
            premarket_automation_module.save_state(paths, state)
            receipt_path = paths.ledger_path.parent / "python-worker-handoffs" / f"{attempt_id}.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps({
                "schema": "trading_mvp_market_data_worker_handoff_v1",
                "status": "ISSUED",
                "project": "trading_mvp",
                "automation_id": premarket_automation_module.AUTOMATION_ID,
                "attempt_id": attempt_id,
                "plan_hash": plan_hash,
                "wrapper_pid": os.getpid(),
                "wrapper_process_started_at_utc": claim["owner_process_started_at_utc"],
                "handoff_token_sha256": hashlib.sha256(handoff_token.encode()).hexdigest(),
                "claim_run_id": attempt_id,
                "claim_owner_kind": "premarket_perp_visible_worker",
                "claim_owner_pid": os.getpid(),
                "claim_owner_process_started_at_utc": claim["owner_process_started_at_utc"],
                "claim_ownership_token_sha256": hashlib.sha256(claim_token.encode()).hexdigest(),
                "claim_output_namespace": str(output_namespace.resolve()),
                "claim_must_exist": True,
                "issued_at_utc": claim["claimed_at_utc"],
            }), encoding="utf-8")

            argv = [
                "premarket_automation.py", "--repo-root", str(repo), "--tick",
                "--attempt-id", attempt_id, "--worker-handoff-token", handoff_token,
                "--plan-hash", plan_hash,
            ]
            with patch.object(sys, "argv", argv), patch.object(
                premarket_automation_module, "run_tick", return_value={"ok": True}
            ) as run_tick_mock, patch("builtins.print"):
                self.assertEqual(0, premarket_automation_module._main())

            run_tick_mock.assert_called_once()
            kwargs = run_tick_mock.call_args.kwargs
            self.assertEqual(attempt_id, kwargs["attempt_id"])
            self.assertEqual(os.getpid(), kwargs["external_worker_pid"])
            self.assertEqual(claim["owner_process_started_at_utc"], kwargs["external_worker_process_started_at_utc"])
            self.assertTrue(kwargs["running_evidence_already_persisted"])
            self.assertFalse(receipt_path.exists())
            self.assertEqual(1, len(list((receipt_path.parent / "consumed").glob("*.json"))))

    def test_wrapper_attempt_has_one_running_and_one_terminal_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            attempt_id = "premarket_perp_automation_shared"
            worker_start = "2026-08-20T12:00:00Z"
            state = premarket_automation_module.load_state(paths)
            state.update({
                "status": "RUNNING",
                "attempt_count": 1,
                "last_attempt_id": attempt_id,
                "last_started_at_utc": worker_start,
                "worker_pid": os.getpid(),
                "worker_process_started_at_utc": worker_start,
            })
            premarket_automation_module.save_state(paths, state)
            premarket_automation_module.append_attempt(paths, {
                "attempt_id": attempt_id,
                "status": "RUNNING",
                "started_at_utc": worker_start,
                "worker_pid": os.getpid(),
            })
            result_payload = {
                "outcomes": {"bybit": {"status": "COMPLETE"}},
                "contracts_seen": 0,
                "events_written": 0,
                "cadence_observation": {},
            }
            with patch.object(
                premarket_automation_module, "build_public_adapters", return_value={}
            ), patch.object(
                premarket_automation_module,
                "discover_and_snapshot",
                return_value=result_payload,
            ):
                result = premarket_automation_module.run_tick(
                    paths,
                    attempt_id=attempt_id,
                    external_worker_pid=os.getpid(),
                    external_worker_process_started_at_utc=worker_start,
                    running_evidence_already_persisted=True,
                )
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            linked = [row for row in rows if row.get("attempt_id") == attempt_id]
            self.assertEqual(1, sum(row.get("status") == "RUNNING" for row in linked), linked)
            self.assertEqual(1, sum(row.get("status") != "RUNNING" for row in linked), linked)
            self.assertEqual(attempt_id, result["attempt_id"])
            terminal_state = premarket_automation_module.load_state(paths)
            self.assertIsNone(terminal_state["worker_pid"])
            self.assertIsNone(terminal_state["worker_process_started_at_utc"])

    def test_bybit_prelisting_normalizes_call_auction_and_official_contract_fields(self) -> None:
        item = {
            "symbol": "ABCUSDT",
            "baseCoin": "ABC",
            "quoteCoin": "USDT",
            "settleCoin": "USDT",
            "status": "PreLaunch",
            "launchTime": "1700000000000",
            "deliveryTime": "0",
            "isPreListing": True,
            "preListingInfo": {
                "curAuctionPhase": "CallAuction",
                "phases": [
                    {"phase": "CallAuction", "startTime": "1700000000000", "endTime": "1700000060000"},
                    {"phase": "Continuous", "startTime": "1700000060000", "endTime": "0"},
                ],
                "auctionFeeInfo": {
                    "auctionFeeRate": "0.0004",
                    "takerFeeRate": "0.001",
                    "makerFeeRate": "0.0004",
                },
            },
            "priceFilter": {"tickSize": "0.0001"},
            "lotSizeFilter": {"minOrderQty": "1", "qtyStep": "1"},
            "leverageFilter": {"maxLeverage": "5"},
        }

        contract = normalize_bybit_instrument(item)

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.phase, PreMarketPhase.CALL_AUCTION.value)
        self.assertEqual(contract.lifecycle_status, "call_auction")
        self.assertEqual(contract.spot_symbol, "ABCUSDT")
        self.assertEqual(contract.tradable_ts, 1_700_000_000.0)
        self.assertEqual(contract.taker_fee_bps, 10.0)
        self.assertEqual(contract.maker_fee_bps, 4.0)
        self.assertEqual(contract.source_class, SourceClass.OFFICIAL.value)

    def test_okx_pre_market_normalizes_transition_and_spot_identity(self) -> None:
        item = {
            "instType": "SWAP",
            "instId": "ABC-USDT-SWAP",
            "uly": "ABC-USDT",
            "baseCcy": "ABC",
            "quoteCcy": "USDT",
            "settleCcy": "USDT",
            "state": "live",
            "ruleType": "pre_market",
            "openType": "call_auction",
            "listTime": "1700000000000",
            "preMktSwTime": "1700003600000",
            "tickSz": "0.0001",
            "lotSz": "1",
            "minSz": "1",
            "lever": "5",
            "initPxLmtPct": "0.05",
            "maxPxLmtPct": "0.15",
        }

        contract = normalize_okx_instrument(item)

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.phase, PreMarketPhase.CALL_AUCTION.value)
        self.assertEqual(contract.spot_symbol, "ABC-USDT")
        self.assertEqual(contract.transition_ts, 1_700_003_600.0)
        self.assertEqual(contract.price_limit_up, 0.15)
        self.assertEqual(contract.source_class, SourceClass.OFFICIAL.value)

    def test_gate_prelaunch_normalizes_liquidation_parameters(self) -> None:
        item = {
            "name": "ABC_USDT",
            "status": "prelaunch",
            "base": "ABC",
            "quanto_multiplier": "1",
            "launch_time": 1_700_003_600,
            "create_time": 1_700_000_000,
            "maintenance_rate": "0.01",
            "mark_price": "1.0",
            "index_price": "1.0",
            "maker_fee_rate": "0.0004",
            "taker_fee_rate": "0.00075",
            "phase": "continuous",
            "premarket": True,
        }

        contract = normalize_gate_instrument(item)

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(contract.lifecycle_status, "scheduled")
        self.assertEqual(contract.phase, PreMarketPhase.CONTINUOUS.value)
        self.assertEqual(contract.maintenance_margin_rate, 0.01)
        self.assertEqual(contract.taker_fee_bps, 7.5)
        self.assertEqual(contract.spot_symbol, "ABC_USDT")

    def test_market_event_normalization_preserves_exchange_and_received_timestamps(self) -> None:
        event = normalize_market_event(
            "bybit",
            "ABCUSDT",
            {
                "topic": "orderbook.50.ABCUSDT",
                "ts": 1700000000123,
                "type": "snapshot",
                "data": {
                    "s": "ABCUSDT",
                    "b": [["1.00", "10"]],
                    "a": [["1.01", "8"]],
                    "u": 17,
                    "cts": 1700000000000,
                },
            },
            received_ts=1_700_000_001.0,
        )

        self.assertEqual(event["event_kind"], "depth")
        self.assertEqual(event["exchange_ts"], 1_700_000_000.0)
        self.assertEqual(event["recv_ts"], 1_700_000_001.0)
        self.assertEqual(event["bids"], [[1.0, 10.0]])
        self.assertEqual(event["asks"], [[1.01, 8.0]])
        self.assertEqual(event["source_seq"], 17)

    def test_entry_candidates_have_two_timing_cohorts_without_future_price_data(self) -> None:
        contract = {
            "contract_id": "ABCUSDT",
            "tradable_ts": 1_700_000_000.0,
            "official_spot_listing_ts": 1_700_020_000.0,
            "phase": "continuous",
            "source_class": "official",
        }
        candidates = build_entry_candidates(contract)

        self.assertEqual({item["entry_cohort"] for item in candidates}, {"first_tradable", "last_1_4h"})
        self.assertEqual(
            [item["entry_ts"] for item in candidates if item["entry_cohort"] == "first_tradable"],
            [1_700_000_000.0],
        )
        self.assertEqual(
            [item["entry_ts"] for item in candidates if item["entry_cohort"] == "last_1_4h"],
            [1_700_000_000.0 + 20_000.0 - 14_400.0],
        )
        self.assertNotIn("price", candidates[0])

        proxy_candidates = build_entry_candidates(contract, first_tradable_observation_ts=1_700_005_000.0)
        self.assertEqual(proxy_candidates[0]["entry_ts"], 1_700_005_000.0)
        self.assertEqual(proxy_candidates[0]["entry_ts_class"], "detection_proxy")

    def test_replay_uses_causal_event_relative_exits_and_keeps_unfilled_in_denominator(self) -> None:
        contract = {
            "venue": "bybit",
            "contract_id": "ABCUSDT",
            "spot_symbol": "ABCUSDT",
            "phase": "continuous",
            "official_spot_listing_ts": 100.0,
            "source_class": "official",
            "taker_fee_bps": 10.0,
            "maker_fee_bps": 4.0,
            "maintenance_margin_rate": 0.01,
        }
        events = [
            {"exchange_ts": 90.0, "recv_ts": 90.0, "event_kind": "bbo", "bid_price": 10.0, "ask_price": 10.1, "bid_qty": 5.0, "ask_qty": 0.0, "mark_price": 10.05, "index_price": 10.0},
            {"exchange_ts": 100.0, "recv_ts": 100.0, "event_kind": "bbo", "bid_price": 11.0, "ask_price": 11.1, "bid_qty": 0.0, "ask_qty": 0.0, "mark_price": 11.05, "index_price": 10.5},
            {"exchange_ts": 105.0, "recv_ts": 105.0, "event_kind": "bbo", "bid_price": 12.0, "ask_price": 12.1, "bid_qty": 10.0, "ask_qty": 10.0, "mark_price": 12.05, "index_price": 11.0},
            {"exchange_ts": 115.0, "recv_ts": 115.0, "event_kind": "bbo", "bid_price": 13.0, "ask_price": 13.1, "bid_qty": 10.0, "ask_qty": 10.0, "mark_price": 13.05, "index_price": 12.0},
            {"exchange_ts": 160.0, "recv_ts": 160.0, "event_kind": "bbo", "bid_price": 14.0, "ask_price": 14.1, "bid_qty": 10.0, "ask_qty": 10.0, "mark_price": 14.05, "index_price": 13.0},
        ]

        result = replay_listing_event(contract, events, notional_quote=25.0, entry_ts=90.0)

        self.assertEqual(result["exit_offsets_sec"], list(EXIT_OFFSETS_SEC))
        self.assertEqual(result["event_status"], "complete")
        self.assertEqual(result["entry_fill_status"], "unfilled")
        self.assertFalse(result["acceptance_eligible"])
        self.assertEqual(result["fill_denominator"], 1)
        self.assertIn("t0_plus_5s", result["exits"])
        self.assertNotIn("peak_price", result)

    def test_evidence_gate_reports_insufficient_data_and_concentration(self) -> None:
        events = [
            {"event_status": "complete", "source_class": "official", "venue": "bybit", "filled": True, "net_pnl_quote": 1.0}
            for _ in range(10)
        ]
        result = evaluate_evidence_gate(events)

        self.assertEqual(result["status"], "INSUFFICIENT_DATA_NOT_REJECTED")
        self.assertEqual(result["complete_events"], 10)
        self.assertFalse(result["acceptance_eligible"])

    def test_retry_state_is_persisted_and_attempt_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
            )

            state = load_state(paths)
            state, next_interval = mark_retry_next_interval(
                state,
                "network_error",
                now_ts=1_700_000_000.0,
                interval_sec=300,
                state_path=paths.state_path,
            )
            append_attempt(paths, {"attempt_id": "a1", "status": state["status"], "reason": "network_error"})
            state = load_state(paths)

            self.assertEqual(state["status"], "RETRY_NEXT_INTERVAL")
            self.assertTrue(state["pending_retry"])
            self.assertEqual(state["next_interval_at_utc"], next_interval)
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["attempt_id"], "a1")

    def test_attempt_append_flushes_and_fsyncs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
            )

            with patch.object(premarket_automation_module.os, "fsync") as fsync:
                append_attempt(paths, {"attempt_id": "a1", "status": "RUNNING"})

            fsync.assert_called_once()
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["attempt_id"], "a1")

    def test_run_tick_records_one_terminal_when_original_and_manifest_writes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(
                    premarket_automation_module,
                    "discover_and_snapshot",
                    side_effect=RuntimeError("raw store denied"),
                ),
                patch.object(
                    premarket_automation_module,
                    "_write_manifest",
                    side_effect=PermissionError("manifest denied"),
                ),
            ):
                result = premarket_automation_module.run_tick(paths)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]
            diagnostic_rows = [row for row in rows if row.get("record_type") == "DIAGNOSTIC"]

            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "RuntimeError: raw store denied")
            self.assertEqual(result["manifest_error"], "PermissionError: manifest denied")
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")
            self.assertNotIn("manifest_error", terminal_rows[0])
            self.assertEqual(len(diagnostic_rows), 1)
            self.assertEqual(diagnostic_rows[0]["manifest_error"], "PermissionError: manifest denied")

    def test_failed_terminal_is_appended_before_manifest_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            calls: list[tuple[str, str]] = []
            original_append = premarket_automation_module.append_attempt
            original_manifest = premarket_automation_module._write_manifest

            def recording_append(target_paths, payload):
                calls.append(("append", str(payload["status"])))
                original_append(target_paths, payload)

            def recording_manifest(*args, **kwargs):
                calls.append(("manifest", str(kwargs["status"])))
                return original_manifest(*args, **kwargs)

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(
                    premarket_automation_module,
                    "discover_and_snapshot",
                    side_effect=RuntimeError("raw store denied"),
                ),
                patch.object(premarket_automation_module, "append_attempt", side_effect=recording_append),
                patch.object(premarket_automation_module, "_write_manifest", side_effect=recording_manifest),
            ):
                premarket_automation_module.run_tick(paths)

            self.assertEqual(
                calls,
                [
                    ("append", "RUNNING"),
                    ("append", "RETRY_NEXT_INTERVAL"),
                    ("manifest", "RETRY_NEXT_INTERVAL"),
                ],
            )

    def test_manifest_diagnostic_append_failure_keeps_one_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            diagnostic_attempts = 0
            original_append = premarket_automation_module.append_attempt

            def fail_diagnostic_append(target_paths, payload):
                nonlocal diagnostic_attempts
                if payload.get("record_type") == "DIAGNOSTIC":
                    diagnostic_attempts += 1
                    raise PermissionError("diagnostic denied")
                original_append(target_paths, payload)

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(
                    premarket_automation_module,
                    "discover_and_snapshot",
                    side_effect=RuntimeError("raw store denied"),
                ),
                patch.object(premarket_automation_module, "append_attempt", side_effect=fail_diagnostic_append),
                patch.object(
                    premarket_automation_module,
                    "_write_manifest",
                    side_effect=PermissionError("manifest denied"),
                ),
            ):
                result = premarket_automation_module.run_tick(paths)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(result["manifest_error"], "PermissionError: manifest denied")
            self.assertEqual(diagnostic_attempts, 1)
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")

    def test_success_receipt_precedes_manifest_and_terminal_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            calls: list[tuple[str, str]] = []
            original_append = premarket_automation_module.append_attempt
            result_payload = {
                "outcomes": {"bybit": {"status": "COMPLETE"}},
                "contracts_seen": 1,
                "events_written": 2,
                "cadence_observation": {},
            }
            original_manifest = premarket_automation_module._write_manifest

            def recording_append(target_paths, payload):
                calls.append(("append", str(payload["status"])))
                original_append(target_paths, payload)

            def recording_receipt(*args, **kwargs):
                calls.append(("receipt", str(kwargs["status"])))
                return {
                    "schema": "test_terminal_receipt_v1",
                    "attempt_id": kwargs["attempt_id"],
                    "status": "PREPARED",
                    "intended_status": kwargs["status"],
                    "outcomes": kwargs["outcomes"],
                    "reason": kwargs["reason"],
                    "pending_retry": kwargs["pending_retry"],
                    "next_interval_at_utc": kwargs["next_interval_at_utc"],
                    "expected_manifest_path": kwargs["expected_manifest_path"],
                    "expected_manifest_sha256": kwargs["expected_manifest_sha256"],
                    "receipt_sha256": "a" * 64,
                }

            def recording_manifest(*args, **kwargs):
                calls.append(("manifest", str(kwargs["status"])))
                return original_manifest(*args, **kwargs)

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(premarket_automation_module, "discover_and_snapshot", return_value=result_payload),
                patch.object(premarket_automation_module, "append_attempt", side_effect=recording_append),
                patch.object(
                    premarket_automation_module,
                    "_write_terminal_receipt",
                    create=True,
                    side_effect=recording_receipt,
                ),
                patch.object(premarket_automation_module, "_write_manifest", side_effect=recording_manifest),
            ):
                result = premarket_automation_module.run_tick(paths)

            self.assertTrue(result["ok"], result)
            self.assertEqual(
                calls,
                [
                    ("append", "RUNNING"),
                    ("receipt", "COMPLETE"),
                    ("manifest", "COMPLETE"),
                    ("append", "COMPLETE"),
                ],
            )

    def test_terminal_receipt_is_idempotent_and_conflicts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            kwargs = {
                "attempt_id": "premarket-attempt-a",
                "status": "COMPLETE",
                "outcomes": {"bybit": {"status": "COMPLETE"}},
                "reason": None,
                "pending_retry": False,
                "next_interval_at_utc": "2026-08-21T00:00:00Z",
                "expected_manifest_path": str(paths.manifest_path),
                "expected_manifest_sha256": "b" * 64,
            }

            first = premarket_automation_module._write_terminal_receipt(paths, **kwargs)
            receipt_path = root / "terminal-receipts" / "premarket-attempt-a.json"
            original_bytes = receipt_path.read_bytes()
            second = premarket_automation_module._write_terminal_receipt(paths, **kwargs)

            self.assertEqual(first, second)
            self.assertEqual(receipt_path.read_bytes(), original_bytes)
            self.assertEqual(len(first["receipt_sha256"]), 64)
            self.assertEqual(first["status"], "PREPARED")
            self.assertEqual(first["intended_status"], "COMPLETE")
            self.assertNotIn("final_status", first)
            with self.assertRaisesRegex(RuntimeError, "terminal receipt conflict"):
                premarket_automation_module._write_terminal_receipt(
                    paths,
                    **{**kwargs, "outcomes": {"bybit": {"status": "RETRY_NEXT_INTERVAL"}}},
                )
            self.assertEqual(receipt_path.read_bytes(), original_bytes)

    def test_interruption_after_success_receipt_leaves_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            result_payload = {
                "outcomes": {"bybit": {"status": "COMPLETE"}},
                "contracts_seen": 1,
                "events_written": 2,
                "cadence_observation": {},
            }

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(premarket_automation_module, "discover_and_snapshot", return_value=result_payload),
                patch.object(premarket_automation_module, "_write_manifest", side_effect=KeyboardInterrupt),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    premarket_automation_module.run_tick(paths)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            receipts = list((root / "terminal-receipts").glob("*.json"))

            self.assertEqual([row["status"] for row in rows], ["RUNNING"])
            self.assertEqual(load_state(paths)["status"], "RUNNING")
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "PREPARED")
            self.assertEqual(receipt["intended_status"], "COMPLETE")
            self.assertNotIn("final_status", receipt)
            self.assertEqual(receipt["outcomes"], result_payload["outcomes"])

    def test_interruption_after_failure_receipt_reconciles_retry_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            original_save_state = premarket_automation_module.save_state
            save_calls = 0

            def interrupt_retry_state(target_paths, state):
                nonlocal save_calls
                save_calls += 1
                if save_calls == 2:
                    raise KeyboardInterrupt("fixture interrupted after failure receipt")
                return original_save_state(target_paths, state)

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(
                    premarket_automation_module,
                    "discover_and_snapshot",
                    side_effect=RuntimeError("raw store denied"),
                ),
                patch.object(premarket_automation_module, "save_state", side_effect=interrupt_retry_state),
            ):
                with self.assertRaisesRegex(KeyboardInterrupt, "interrupted after failure receipt"):
                    premarket_automation_module.run_tick(paths)

            receipts = list((root / "terminal-receipts").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "PREPARED")
            self.assertEqual(receipt["intended_status"], "RETRY_NEXT_INTERVAL")
            self.assertTrue(receipt["pending_retry"])
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["status"] for row in rows], ["RUNNING"])
            self.assertEqual(premarket_automation_module.load_state(paths)["status"], "RUNNING")

            premarket_automation_module.reconcile_prepared_receipts(paths)
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["status"], "RETRY_NEXT_INTERVAL")
            self.assertEqual(
                terminal_rows[0]["terminal_receipt"]["receipt_sha256"],
                receipt["receipt_sha256"],
            )
            self.assertEqual(
                premarket_automation_module.load_state(paths)["status"],
                "RETRY_NEXT_INTERVAL",
            )

    def test_initial_running_state_failure_has_ledger_receipt_and_retry_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            original_save_state = premarket_automation_module.save_state
            save_calls = 0

            def fail_first_state_save(target_paths, state):
                nonlocal save_calls
                save_calls += 1
                if save_calls == 1:
                    raise OSError("fixture initial RUNNING state denied")
                return original_save_state(target_paths, state)

            result = None
            escaped = None
            with (
                patch.object(
                    premarket_automation_module,
                    "save_state",
                    side_effect=fail_first_state_save,
                ),
                patch.object(
                    premarket_automation_module,
                    "build_public_adapters",
                    return_value={},
                ),
            ):
                try:
                    result = premarket_automation_module.run_tick(paths)
                except OSError as exc:
                    escaped = exc

            self.assertIsNone(escaped, f"startup failure escaped recovery: {escaped}")
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "RETRY_NEXT_INTERVAL")
            rows = [
                json.loads(line)
                for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[0]["status"], "RUNNING")
            self.assertEqual(rows[-1]["status"], "RETRY_NEXT_INTERVAL")
            self.assertEqual(load_state(paths)["status"], "RETRY_NEXT_INTERVAL")
            receipts = list((root / "terminal-receipts").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertEqual(
                json.loads(receipts[0].read_text(encoding="utf-8"))["intended_status"],
                "RETRY_NEXT_INTERVAL",
            )

    def test_initial_running_ledger_failure_never_leaves_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            original_append_attempt = premarket_automation_module.append_attempt
            append_calls = 0

            def fail_first_ledger_append(target_paths, payload):
                nonlocal append_calls
                append_calls += 1
                if append_calls == 1:
                    raise OSError("fixture initial RUNNING ledger denied")
                return original_append_attempt(target_paths, payload)

            result = None
            escaped = None
            with (
                patch.object(
                    premarket_automation_module,
                    "append_attempt",
                    side_effect=fail_first_ledger_append,
                ),
                patch.object(
                    premarket_automation_module,
                    "build_public_adapters",
                    return_value={},
                ),
            ):
                try:
                    result = premarket_automation_module.run_tick(paths)
                except OSError as exc:
                    escaped = exc

            self.assertIsNone(escaped, f"startup failure escaped recovery: {escaped}")
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "RETRY_NEXT_INTERVAL")
            rows = [
                json.loads(line)
                for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertNotIn("RUNNING", [row["status"] for row in rows])
            self.assertEqual(rows[-1]["status"], "RETRY_NEXT_INTERVAL")
            self.assertEqual(load_state(paths)["status"], "RETRY_NEXT_INTERVAL")
            receipts = list((root / "terminal-receipts").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertEqual(
                json.loads(receipts[0].read_text(encoding="utf-8"))["intended_status"],
                "RETRY_NEXT_INTERVAL",
            )

    def test_manifest_failure_keeps_prepared_receipt_and_only_retry_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            result_payload = {
                "outcomes": {"bybit": {"status": "COMPLETE"}},
                "contracts_seen": 1,
                "events_written": 2,
                "cadence_observation": {},
            }

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(premarket_automation_module, "discover_and_snapshot", return_value=result_payload),
                patch.object(
                    premarket_automation_module,
                    "_write_manifest",
                    side_effect=OSError("manifest denied"),
                ),
            ):
                result = premarket_automation_module.run_tick(paths)

            receipt_path = next((root / "terminal-receipts").glob("*.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(receipt["status"], "PREPARED")
            self.assertEqual(receipt["intended_status"], "COMPLETE")
            self.assertNotIn("final_status", receipt)
            self.assertEqual(result["status"], "RETRY_NEXT_INTERVAL")
            self.assertEqual(load_state(paths)["status"], "RETRY_NEXT_INTERVAL")
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["status"], "RETRY_NEXT_INTERVAL")
            self.assertFalse(terminal_rows[0]["manifest_committed"])
            self.assertEqual(
                terminal_rows[0]["terminal_receipt"]["receipt_sha256"],
                receipt["receipt_sha256"],
            )

    def test_prepared_receipt_reconciliation_commits_only_matching_manifest(self) -> None:
        manifest_bytes = b'{"status":"COMPLETE"}\n'
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        for manifest_case in ("matching", "missing", "mismatch"):
            with self.subTest(manifest_case=manifest_case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                paths = AutomationPaths(
                    state_path=root / "state.json",
                    ledger_path=root / "attempts.jsonl",
                    claim_path=root / "claim.json",
                    launch_path=root / "launch.json",
                    worker_error_path=root / "worker-error.log",
                    events_path=root / "events.jsonl",
                    manifest_path=root / "manifest.json",
                )
                attempt_id = f"premarket-{manifest_case}"
                state = load_state(paths)
                state.update({"status": "RUNNING", "last_attempt_id": attempt_id, "worker_pid": 123})
                premarket_automation_module.save_state(paths, state)
                receipt = premarket_automation_module._write_terminal_receipt(
                    paths,
                    attempt_id=attempt_id,
                    status="COMPLETE",
                    outcomes={"bybit": {"status": "COMPLETE"}},
                    reason=None,
                    pending_retry=False,
                    next_interval_at_utc="2026-08-21T00:00:00Z",
                    expected_manifest_path=str(paths.manifest_path),
                    expected_manifest_sha256=manifest_sha256,
                )
                if manifest_case == "matching":
                    paths.manifest_path.write_bytes(manifest_bytes)
                elif manifest_case == "mismatch":
                    paths.manifest_path.write_bytes(b'{"status":"ALTERED"}\n')

                premarket_automation_module.reconcile_prepared_receipts(paths)
                premarket_automation_module.reconcile_prepared_receipts(paths)

                rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
                terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]
                self.assertEqual(len(terminal_rows), 1)
                self.assertEqual(
                    terminal_rows[0]["status"],
                    "COMPLETE" if manifest_case == "matching" else "RETRY_NEXT_INTERVAL",
                )
                self.assertEqual(
                    terminal_rows[0]["manifest_committed"],
                    manifest_case == "matching",
                )
                self.assertEqual(
                    terminal_rows[0]["terminal_receipt"]["receipt_sha256"],
                    receipt["receipt_sha256"],
                )
                self.assertEqual(
                    load_state(paths)["status"],
                    "COMPLETE" if manifest_case == "matching" else "RETRY_NEXT_INTERVAL",
                )

                if manifest_case == "matching":
                    # The shared latest-manifest path may be replaced by a later
                    # attempt; the already-linked terminal is the durable commit.
                    paths.manifest_path.write_bytes(b'{"status":"LATER_ATTEMPT"}\n')
                    premarket_automation_module.reconcile_prepared_receipts(paths)
                    rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(
                        len([row for row in rows if row.get("record_type") == "TERMINAL"]),
                        1,
                    )
                    self.assertEqual(load_state(paths)["status"], "COMPLETE")
                else:
                    paths.manifest_path.write_bytes(manifest_bytes)
                    premarket_automation_module.reconcile_prepared_receipts(paths)
                    rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(
                        len([row for row in rows if row.get("record_type") == "TERMINAL"]),
                        1,
                    )
                    self.assertEqual(load_state(paths)["status"], "RETRY_NEXT_INTERVAL")

    def test_reconciliation_rejects_conflicting_main_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            manifest_bytes = b'{"status":"COMPLETE"}\n'
            paths.manifest_path.write_bytes(manifest_bytes)
            premarket_automation_module._write_terminal_receipt(
                paths,
                attempt_id="premarket-conflict",
                status="COMPLETE",
                outcomes={"bybit": {"status": "COMPLETE"}},
                reason=None,
                pending_retry=False,
                next_interval_at_utc="2026-08-21T00:00:00Z",
                expected_manifest_path=str(paths.manifest_path),
                expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            )
            append_attempt(
                paths,
                {
                    "record_type": "TERMINAL",
                    "terminal": True,
                    "attempt_id": "premarket-conflict",
                    "status": "COMPLETE",
                    "terminal_receipt": {"receipt_sha256": "0" * 64},
                },
            )

            with self.assertRaisesRegex(RuntimeError, "terminal receipt conflict"):
                premarket_automation_module.reconcile_prepared_receipts(paths)
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len([row for row in rows if row.get("record_type") == "TERMINAL"]), 1)

    def test_run_tick_records_terminal_when_retry_state_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(
                    premarket_automation_module,
                    "discover_and_snapshot",
                    side_effect=RuntimeError("raw store denied"),
                ),
                patch.object(
                    premarket_automation_module,
                    "save_state",
                    side_effect=[None, PermissionError("state denied")],
                ),
            ):
                result = premarket_automation_module.run_tick(paths)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(result["reason"], "RuntimeError: raw store denied")
            self.assertEqual(result["state_error"], "PermissionError: state denied")
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")
            self.assertEqual(terminal_rows[0]["state_error"], "PermissionError: state denied")

    def test_run_tick_records_terminal_when_worker_error_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AutomationPaths(
                state_path=root / "state.json",
                ledger_path=root / "attempts.jsonl",
                claim_path=root / "claim.json",
                launch_path=root / "launch.json",
                worker_error_path=root / "worker-error.log",
                events_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            original_write_text = Path.write_text

            def fail_worker_error_write(path: Path, *args, **kwargs):
                if path == paths.worker_error_path:
                    raise PermissionError("worker error denied")
                return original_write_text(path, *args, **kwargs)

            with (
                patch.object(premarket_automation_module, "build_public_adapters", return_value={}),
                patch.object(
                    premarket_automation_module,
                    "discover_and_snapshot",
                    side_effect=RuntimeError("raw store denied"),
                ),
                patch.object(Path, "write_text", new=fail_worker_error_write),
            ):
                result = premarket_automation_module.run_tick(paths)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(result["reason"], "RuntimeError: raw store denied")
            self.assertEqual(result["worker_error"], "PermissionError: worker error denied")
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")
            self.assertEqual(terminal_rows[0]["worker_error"], "PermissionError: worker error denied")

    def test_planonly_is_hash_bound_to_public_paper_contract(self) -> None:
        plan_path = Path(__file__).resolve().parents[2] / "docs" / "plans" / "premarket-perp-listing-impulse-planonly-20260825-v5.json"
        result = validate_plan(plan_path)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PLAN_OK")
        self.assertEqual(set(result["venues"]), {"bybit", "okx", "gate"})

    def test_websocket_capture_is_bounded_and_skips_zero_duration(self) -> None:
        class Adapter:
            venue = "bybit"
            ws_url = "wss://invalid.example"

            def websocket_subscriptions(self, contract):
                return []

        with tempfile.TemporaryDirectory() as temp_dir:
            result = capture_websocket_events(
                Adapter(),
                object(),
                events_path=Path(temp_dir) / "events.jsonl",
                duration_sec=0,
            )

        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["events_written"], 0)

    def test_failed_active_websocket_keeps_venue_queued_for_next_interval(self) -> None:
        contract = normalize_bybit_instrument(
            {
                "symbol": "QUEUEUSDT",
                "baseCoin": "QUEUE",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "status": "PreLaunch",
                "isPreListing": True,
                "preListingInfo": {"curAuctionPhase": "Continuous"},
            }
        )

        class Adapter:
            venue = "bybit"

            def discover_contracts(self):
                return [contract]

            def snapshot_payloads(self, _contract):
                return [{"topic": "tickers.QUEUEUSDT", "data": {"bid1Price": "1", "ask1Price": "1.1"}}]

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            premarket_automation_module,
            "capture_websocket_events",
            return_value={"status": "RETRY_NEXT_INTERVAL", "events_written": 0, "reason": "timeout"},
        ):
            result = discover_and_snapshot(
                adapters={"bybit": Adapter()},
                events_path=Path(temp_dir) / "events.jsonl",
                websocket_duration_sec=1,
                now_ts=1_700_000_000.0,
            )
            event = json.loads((Path(temp_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(result["outcomes"]["bybit"]["status"], "RETRY_NEXT_INTERVAL")
        self.assertEqual(result["outcomes"]["bybit"]["retry_reason"], "websocket_capture_failed")
        self.assertEqual(event["premarket_contract_id"], "QUEUEUSDT")
        self.assertEqual(event["spot_symbol"], "QUEUEUSDT")
        self.assertEqual(event["phase"], "continuous")
        self.assertIn("announcement_ts", event)
        self.assertIn("official_spot_listing_ts", event)

    def test_visible_orchestrator_contains_normal_terminal_and_retry_contract(self) -> None:
        script_path = Path(__file__).resolve().parents[2] / "tools" / "start_premarket_perp_listing_automation_visible.ps1"
        source = script_path.read_text(encoding="utf-8-sig")

        self.assertIn("-WindowStyle Normal", source)
        self.assertIn("RETRY_NEXT_INTERVAL", source)
        self.assertIn("PARTIAL_RETRY_NEXT_INTERVAL", source)
        self.assertIn("pending_retry", source)
        self.assertIn("next_interval_at_utc", source)
        self.assertIn("--websocket-duration-sec 10", source)
        self.assertIn("active-market-data-writer-claim.json", source)
        self.assertIn("STALE_CLAIM_RECOVERED", source)
        self.assertIn("ALREADY_RUNNING", source)
        self.assertNotIn("InlineWorker", source)


if __name__ == "__main__":
    unittest.main()
