from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from preipo_adapters import PreIPOContract  # noqa: E402
from preipo_raw_event_store import RawEventStore  # noqa: E402
from global_market_writer_claim import claim_global_market_writer  # noqa: E402
import preipo_automation as preipo_automation_module  # noqa: E402
from preipo_automation import (  # noqa: E402
    AutomationPaths,
    CAPTURE_DURATION_SEC,
    SCHEDULE_INTERVAL_SEC,
    acquire_writer_claim,
    append_attempt,
    discover_and_snapshot,
    load_state,
    mark_retry_next_interval,
    release_writer_claim,
    run_tick,
)


class _FakeAdapter:
    venue = "okx"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def discover_contracts(self):
        if self.fail:
            raise RuntimeError("simulated network error")
        return [
            PreIPOContract(
                venue="okx",
                contract_id="SPCX-USDT-SWAP",
                underlying_symbol="SPCX",
                quote="USDT",
                lifecycle_status="preipo_continuous",
                phase="preipo_continuous",
                source_class="official",
            )
        ]

    def snapshot_payloads(self, contract):
        return [
            {
                "arg": {"channel": "books", "instId": contract.contract_id},
                "data": [
                    {
                        "ts": "1780000123456",
                        "bids": [["10", "4"]],
                        "asks": [["10.1", "3"]],
                        "seqId": 12,
                    }
                ],
            }
        ]

    def websocket_subscriptions(self, contract):
        return []


class PreIPOAutomationTests(unittest.TestCase):
    def test_cli_tick_requires_bound_worker_handoff_before_run_tick(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            sys,
            "argv",
            [
                "preipo_automation.py",
                "--repo-root",
                temp_dir,
                "--tick",
            ],
        ), patch.object(preipo_automation_module, "run_tick") as run_tick_mock:
            with self.assertRaises(SystemExit):
                preipo_automation_module._main()
            run_tick_mock.assert_not_called()
            self.assertEqual([], list(Path(temp_dir).rglob("*")))

    def test_cli_consumes_bound_handoff_and_reuses_wrapper_attempt_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            paths = preipo_automation_module._default_paths(repo)
            attempt_id = "preipo_automation_fixture"
            plan_hash = "b" * 64
            handoff_token = "4" * 32
            claim_token = "5" * 32
            output_namespace = repo / "exports" / "trading-mvp" / "preipo-perp"
            claim = claim_global_market_writer(
                repo / "docs" / "agent-log" / "active-market-data-writer-claim.json",
                run_id=attempt_id,
                owner_pid=os.getpid(),
                owner_kind="preipo_perpetual_visible_worker",
                plan_hash=plan_hash,
                output_namespace=output_namespace,
                writer_pid=os.getpid(),
                terminal_pid=os.getpid(),
                ownership_token=claim_token,
            )
            state = preipo_automation_module.load_state(paths)
            state.update({
                "status": "RUNNING",
                "attempt_count": 1,
                "last_attempt_id": attempt_id,
                "last_started_at_utc": claim["claimed_at_utc"],
                "worker_pid": os.getpid(),
                "worker_process_started_at_utc": claim["owner_process_started_at_utc"],
            })
            preipo_automation_module.save_state(paths, state)
            receipt_path = paths.ledger_path.parent / "python-worker-handoffs" / f"{attempt_id}.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps({
                "schema": "trading_mvp_market_data_worker_handoff_v1",
                "status": "ISSUED",
                "project": "trading_mvp",
                "automation_id": preipo_automation_module.AUTOMATION_ID,
                "attempt_id": attempt_id,
                "plan_hash": plan_hash,
                "wrapper_pid": os.getpid(),
                "wrapper_process_started_at_utc": claim["owner_process_started_at_utc"],
                "handoff_token_sha256": hashlib.sha256(handoff_token.encode()).hexdigest(),
                "claim_run_id": attempt_id,
                "claim_owner_kind": "preipo_perpetual_visible_worker",
                "claim_owner_pid": os.getpid(),
                "claim_owner_process_started_at_utc": claim["owner_process_started_at_utc"],
                "claim_ownership_token_sha256": hashlib.sha256(claim_token.encode()).hexdigest(),
                "claim_output_namespace": str(output_namespace.resolve()),
                "claim_must_exist": True,
                "issued_at_utc": claim["claimed_at_utc"],
            }), encoding="utf-8")

            argv = [
                "preipo_automation.py", "--repo-root", str(repo), "--tick",
                "--attempt-id", attempt_id, "--worker-handoff-token", handoff_token,
                "--plan-hash", plan_hash,
            ]
            with patch.object(sys, "argv", argv), patch.object(
                preipo_automation_module, "run_tick", return_value={"ok": True}
            ) as run_tick_mock, patch("builtins.print"):
                self.assertEqual(0, preipo_automation_module._main())

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
            paths = self._paths(root)
            attempt_id = "preipo_automation_shared"
            worker_start = "2026-08-20T12:00:00Z"
            state = preipo_automation_module.load_state(paths)
            state.update({
                "status": "RUNNING",
                "attempt_count": 1,
                "last_attempt_id": attempt_id,
                "last_started_at_utc": worker_start,
                "worker_pid": os.getpid(),
                "worker_process_started_at_utc": worker_start,
            })
            preipo_automation_module.save_state(paths, state)
            preipo_automation_module.append_attempt(paths, {
                "attempt_id": attempt_id,
                "status": "RUNNING",
                "started_at_utc": worker_start,
                "worker_pid": os.getpid(),
            })
            result = preipo_automation_module.run_tick(
                paths,
                adapters={"okx": _FakeAdapter()},
                now_ts=1_780_000_000.0,
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
            terminal_state = preipo_automation_module.load_state(paths)
            self.assertIsNone(terminal_state["worker_pid"])
            self.assertIsNone(terminal_state["worker_process_started_at_utc"])

    def _paths(self, root: Path) -> AutomationPaths:
        return AutomationPaths(
            state_path=root / "state.json",
            ledger_path=root / "attempts.jsonl",
            claim_path=root / "claim.json",
            launch_path=root / "launch.json",
            worker_error_path=root / "worker-error.log",
            events_path=root / "events.jsonl",
            manifest_path=root / "manifest.json",
        )

    def test_retry_state_is_persisted_and_attempt_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            state = load_state(paths)
            updated, next_at = mark_retry_next_interval(state, "network_error", now_ts=1000.0, state_path=paths.state_path)
            append_attempt(paths, {"attempt_id": "a1", "status": updated["status"], "next_interval_at_utc": next_at})

            reloaded = load_state(paths)
            self.assertEqual(reloaded["status"], "RETRY_NEXT_INTERVAL")
            self.assertTrue(reloaded["pending_retry"])
            self.assertEqual(len(paths.ledger_path.read_text(encoding="utf-8").splitlines()), 1)

    def test_run_tick_records_one_terminal_when_original_and_manifest_writes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)

            with (
                patch("preipo_automation.discover_and_snapshot", side_effect=RuntimeError("raw store denied")),
                patch("preipo_automation._write_manifest", side_effect=PermissionError("manifest denied")),
            ):
                result = run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

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
            paths = self._paths(Path(temp_dir))
            calls: list[tuple[str, str]] = []

            def recording_append(target_paths, payload):
                calls.append(("append", str(payload["status"])))
                append_attempt(target_paths, payload)

            def recording_manifest(*args, **kwargs):
                calls.append(("manifest", str(kwargs["status"])))
                return {}

            with (
                patch("preipo_automation.discover_and_snapshot", side_effect=RuntimeError("raw store denied")),
                patch("preipo_automation.append_attempt", side_effect=recording_append),
                patch("preipo_automation._write_manifest", side_effect=recording_manifest),
            ):
                run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

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
            paths = self._paths(Path(temp_dir))
            diagnostic_attempts = 0

            def fail_diagnostic_append(target_paths, payload):
                nonlocal diagnostic_attempts
                if payload.get("record_type") == "DIAGNOSTIC":
                    diagnostic_attempts += 1
                    raise PermissionError("diagnostic denied")
                append_attempt(target_paths, payload)

            with (
                patch("preipo_automation.discover_and_snapshot", side_effect=RuntimeError("raw store denied")),
                patch("preipo_automation.append_attempt", side_effect=fail_diagnostic_append),
                patch("preipo_automation._write_manifest", side_effect=PermissionError("manifest denied")),
            ):
                result = run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(result["manifest_error"], "PermissionError: manifest denied")
            self.assertEqual(diagnostic_attempts, 1)
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")

    def test_success_receipt_precedes_manifest_and_terminal_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._paths(Path(temp_dir))
            calls: list[tuple[str, str]] = []
            result_payload = {
                "outcomes": {"okx": {"status": "COMPLETE"}},
                "contracts_seen": 1,
                "events_written": 2,
                "official_contracts": 1,
                "proxy_contracts": 0,
                "cadence_observation": {},
            }
            original_manifest = preipo_automation_module._write_manifest

            def recording_append(target_paths, payload):
                calls.append(("append", str(payload["status"])))
                append_attempt(target_paths, payload)

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
                patch("preipo_automation.discover_and_snapshot", return_value=result_payload),
                patch("preipo_automation.append_attempt", side_effect=recording_append),
                patch(
                    "preipo_automation._write_terminal_receipt",
                    create=True,
                    side_effect=recording_receipt,
                ),
                patch("preipo_automation._write_manifest", side_effect=recording_manifest),
            ):
                result = run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

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
            paths = self._paths(root)
            kwargs = {
                "attempt_id": "preipo-attempt-a",
                "status": "COMPLETE",
                "outcomes": {"okx": {"status": "COMPLETE"}},
                "reason": None,
                "pending_retry": False,
                "next_interval_at_utc": "2026-08-21T00:00:00Z",
                "expected_manifest_path": str(paths.manifest_path),
                "expected_manifest_sha256": "b" * 64,
            }

            first = preipo_automation_module._write_terminal_receipt(paths, **kwargs)
            receipt_path = root / "terminal-receipts" / "preipo-attempt-a.json"
            original_bytes = receipt_path.read_bytes()
            second = preipo_automation_module._write_terminal_receipt(paths, **kwargs)

            self.assertEqual(first, second)
            self.assertEqual(receipt_path.read_bytes(), original_bytes)
            self.assertEqual(len(first["receipt_sha256"]), 64)
            self.assertEqual(first["status"], "PREPARED")
            self.assertEqual(first["intended_status"], "COMPLETE")
            self.assertNotIn("final_status", first)
            with self.assertRaisesRegex(RuntimeError, "terminal receipt conflict"):
                preipo_automation_module._write_terminal_receipt(
                    paths,
                    **{**kwargs, "outcomes": {"okx": {"status": "RETRY_NEXT_INTERVAL"}}},
                )
            self.assertEqual(receipt_path.read_bytes(), original_bytes)

    def test_interruption_after_success_receipt_leaves_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            result_payload = {
                "outcomes": {"okx": {"status": "COMPLETE"}},
                "contracts_seen": 1,
                "events_written": 2,
                "official_contracts": 1,
                "proxy_contracts": 0,
                "cadence_observation": {},
            }

            with (
                patch("preipo_automation.discover_and_snapshot", return_value=result_payload),
                patch("preipo_automation._write_manifest", side_effect=KeyboardInterrupt),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

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
            paths = self._paths(root)
            original_save_state = preipo_automation_module.save_state
            save_calls = 0

            def interrupt_retry_state(target_paths, state):
                nonlocal save_calls
                save_calls += 1
                if save_calls == 2:
                    raise KeyboardInterrupt("fixture interrupted after failure receipt")
                return original_save_state(target_paths, state)

            with (
                patch("preipo_automation.discover_and_snapshot", side_effect=RuntimeError("raw store denied")),
                patch("preipo_automation.save_state", side_effect=interrupt_retry_state),
            ):
                with self.assertRaisesRegex(KeyboardInterrupt, "interrupted after failure receipt"):
                    run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

            receipts = list((root / "terminal-receipts").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "PREPARED")
            self.assertEqual(receipt["intended_status"], "RETRY_NEXT_INTERVAL")
            self.assertTrue(receipt["pending_retry"])
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["status"] for row in rows], ["RUNNING"])
            self.assertEqual(load_state(paths)["status"], "RUNNING")

            preipo_automation_module.reconcile_prepared_receipts(paths)
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["status"], "RETRY_NEXT_INTERVAL")
            self.assertEqual(
                terminal_rows[0]["terminal_receipt"]["receipt_sha256"],
                receipt["receipt_sha256"],
            )
            self.assertEqual(load_state(paths)["status"], "RETRY_NEXT_INTERVAL")

    def test_initial_running_state_failure_has_ledger_receipt_and_retry_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            original_save_state = preipo_automation_module.save_state
            save_calls = 0

            def fail_first_state_save(target_paths, state):
                nonlocal save_calls
                save_calls += 1
                if save_calls == 1:
                    raise OSError("fixture initial RUNNING state denied")
                return original_save_state(target_paths, state)

            result = None
            escaped = None
            with patch(
                "preipo_automation.save_state",
                side_effect=fail_first_state_save,
            ):
                try:
                    result = run_tick(
                        paths,
                        adapters={"okx": _FakeAdapter()},
                        now_ts=1_780_000_000.0,
                    )
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
            paths = self._paths(root)
            original_append_attempt = preipo_automation_module.append_attempt
            append_calls = 0

            def fail_first_ledger_append(target_paths, payload):
                nonlocal append_calls
                append_calls += 1
                if append_calls == 1:
                    raise OSError("fixture initial RUNNING ledger denied")
                return original_append_attempt(target_paths, payload)

            result = None
            escaped = None
            with patch(
                "preipo_automation.append_attempt",
                side_effect=fail_first_ledger_append,
            ):
                try:
                    result = run_tick(
                        paths,
                        adapters={"okx": _FakeAdapter()},
                        now_ts=1_780_000_000.0,
                    )
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
            paths = self._paths(root)
            result_payload = {
                "outcomes": {"okx": {"status": "COMPLETE"}},
                "contracts_seen": 1,
                "events_written": 2,
                "official_contracts": 1,
                "proxy_contracts": 0,
                "cadence_observation": {},
            }

            with (
                patch("preipo_automation.discover_and_snapshot", return_value=result_payload),
                patch("preipo_automation._write_manifest", side_effect=OSError("manifest denied")),
            ):
                result = run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

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
                paths = self._paths(root)
                attempt_id = f"preipo-{manifest_case}"
                state = load_state(paths)
                state.update({"status": "RUNNING", "last_attempt_id": attempt_id, "worker_pid": 123})
                preipo_automation_module.save_state(paths, state)
                receipt = preipo_automation_module._write_terminal_receipt(
                    paths,
                    attempt_id=attempt_id,
                    status="COMPLETE",
                    outcomes={"okx": {"status": "COMPLETE"}},
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

                preipo_automation_module.reconcile_prepared_receipts(paths)
                preipo_automation_module.reconcile_prepared_receipts(paths)

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
                    preipo_automation_module.reconcile_prepared_receipts(paths)
                    rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(
                        len([row for row in rows if row.get("record_type") == "TERMINAL"]),
                        1,
                    )
                    self.assertEqual(load_state(paths)["status"], "COMPLETE")
                else:
                    paths.manifest_path.write_bytes(manifest_bytes)
                    preipo_automation_module.reconcile_prepared_receipts(paths)
                    rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(
                        len([row for row in rows if row.get("record_type") == "TERMINAL"]),
                        1,
                    )
                    self.assertEqual(load_state(paths)["status"], "RETRY_NEXT_INTERVAL")

    def test_reconciliation_rejects_conflicting_main_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            manifest_bytes = b'{"status":"COMPLETE"}\n'
            paths.manifest_path.write_bytes(manifest_bytes)
            preipo_automation_module._write_terminal_receipt(
                paths,
                attempt_id="preipo-conflict",
                status="COMPLETE",
                outcomes={"okx": {"status": "COMPLETE"}},
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
                    "attempt_id": "preipo-conflict",
                    "status": "COMPLETE",
                    "terminal_receipt": {"receipt_sha256": "0" * 64},
                },
            )

            with self.assertRaisesRegex(RuntimeError, "terminal receipt conflict"):
                preipo_automation_module.reconcile_prepared_receipts(paths)
            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len([row for row in rows if row.get("record_type") == "TERMINAL"]), 1)

    def test_run_tick_records_terminal_when_retry_state_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._paths(Path(temp_dir))

            with (
                patch("preipo_automation.discover_and_snapshot", side_effect=RuntimeError("raw store denied")),
                patch(
                    "preipo_automation.save_state",
                    side_effect=[None, PermissionError("state denied")],
                ),
            ):
                result = run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(result["reason"], "RuntimeError: raw store denied")
            self.assertEqual(result["state_error"], "PermissionError: state denied")
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")
            self.assertEqual(terminal_rows[0]["state_error"], "PermissionError: state denied")

    def test_run_tick_records_terminal_when_worker_error_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._paths(Path(temp_dir))
            original_write_text = Path.write_text

            def fail_worker_error_write(path: Path, *args, **kwargs):
                if path == paths.worker_error_path:
                    raise PermissionError("worker error denied")
                return original_write_text(path, *args, **kwargs)

            with (
                patch("preipo_automation.discover_and_snapshot", side_effect=RuntimeError("raw store denied")),
                patch.object(Path, "write_text", new=fail_worker_error_write),
            ):
                result = run_tick(paths, adapters={"okx": _FakeAdapter()}, now_ts=1_780_000_000.0)

            rows = [json.loads(line) for line in paths.ledger_path.read_text(encoding="utf-8").splitlines()]
            terminal_rows = [row for row in rows if row.get("record_type") == "TERMINAL"]

            self.assertEqual(result["reason"], "RuntimeError: raw store denied")
            self.assertEqual(result["worker_error"], "PermissionError: worker error denied")
            self.assertEqual(len(terminal_rows), 1)
            self.assertEqual(terminal_rows[0]["reason"], "RuntimeError: raw store denied")
            self.assertEqual(terminal_rows[0]["worker_error"], "PermissionError: worker error denied")

    def test_schedule_and_capture_defaults_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._paths(Path(temp_dir))
            state = load_state(paths)
            self.assertEqual(SCHEDULE_INTERVAL_SEC, 6 * 60 * 60)
            self.assertEqual(CAPTURE_DURATION_SEC, 5 * 60)
            self.assertEqual(state["schedule_interval_seconds"], SCHEDULE_INTERVAL_SEC)
            self.assertEqual(state["capture_duration_seconds"], CAPTURE_DURATION_SEC)
            _, next_at = mark_retry_next_interval(state, "network_error", now_ts=1000.0)
            parsed = datetime.fromisoformat(next_at.replace("Z", "+00:00"))
            self.assertEqual(parsed.timestamp(), 1000.0 + SCHEDULE_INTERVAL_SEC)

    def test_writer_claim_skips_duplicate_and_releases_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            first = acquire_writer_claim(paths)
            self.assertIsNotNone(first)
            second = acquire_writer_claim(paths)
            self.assertIsNone(second)
            assert first is not None
            release_writer_claim(paths, first)
            third = acquire_writer_claim(paths)
            self.assertIsNotNone(third)
            assert third is not None
            release_writer_claim(paths, third)

    def test_partial_venue_failure_is_queued_for_next_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            result = run_tick(
                paths,
                adapters={"okx": _FakeAdapter(), "gate": _FakeAdapter(fail=True)},
                now_ts=1_780_000_000.0,
            )

            self.assertEqual(result["status"], "PARTIAL_RETRY_NEXT_INTERVAL")
            self.assertTrue(result["pending_retry"])
            self.assertEqual(result["outcomes"]["okx"]["status"], "COMPLETE")
            self.assertEqual(result["outcomes"]["gate"]["status"], "RETRY_NEXT_INTERVAL")
            self.assertTrue(paths.events_path.exists())
            self.assertTrue(paths.manifest_path.exists())

    def test_websocket_capture_budget_is_global_per_tick(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root)
            durations: list[float] = []

            def fake_capture(*args, duration_sec: float, **kwargs):
                durations.append(float(duration_sec))
                return {"status": "COMPLETE", "events_written": 0, "duration_sec": 0.0}

            with patch("preipo_automation.capture_websocket_events", side_effect=fake_capture):
                result = discover_and_snapshot(
                    adapters={"okx": _FakeAdapter(), "gate": _FakeAdapter()},
                    store=RawEventStore(paths.events_path, paths.manifest_path),
                    max_contracts_per_venue=25,
                    websocket_duration_sec=300,
                    now_ts=1_780_000_000.0,
                )

            self.assertEqual(result["contracts_seen"], 2)
            self.assertEqual(len(durations), 2)
            self.assertLessEqual(sum(durations), 300.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
