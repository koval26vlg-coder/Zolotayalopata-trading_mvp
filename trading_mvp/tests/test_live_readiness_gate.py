from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from live_readiness_gate import (  # noqa: E402
    BLOCKED_LIVE,
    PAPER_ONLY,
    PREPARATION_ONLY,
    PolicyFormatError,
    policy_payload_sha256,
    validate_readiness,
)


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _runtime_snapshot(**overrides: object) -> dict:
    snapshot = {
        "strategy_plan_sha256": "a" * 64,
        "canonical_runtime_registry_raw_sha256": "b" * 64,
        "account_alias": "future-live-primary",
        "venue": "gateio",
        "requested_capabilities": {
            "authenticated_api": True,
            "live_orders": True,
            "real_capital": True,
            "leverage": True,
            "margin": True,
        },
        "requested_notional_usd": "1000.00",
        "current_daily_loss_usd": "50.00",
        "resulting_position_usd": "750.00",
        "kill_switch_ready": True,
        "reconciliation_ok": True,
        "reconciliation_age_seconds": 5,
        "market_data_age_seconds": 1,
        "clock_skew_seconds": 0,
    }
    snapshot.update(overrides)
    return snapshot


def _candidate_policy() -> dict:
    policy = {
        "schema": "future_live_policy_v1",
        "policy_id": "future-live-policy-2030-01",
        "strategy_plan_sha256": "a" * 64,
        "canonical_runtime_registry_raw_sha256": "b" * 64,
        "account_venue_allowlist": [
            {"account_alias": "future-live-primary", "venue": "gateio"},
        ],
        "allowed_capabilities": {
            "authenticated_api": True,
            "live_orders": True,
            "real_capital": True,
            "leverage": True,
            "margin": True,
        },
        "limits": {
            "max_notional_usd": "1500.00",
            "max_daily_loss_usd": "100.00",
            "max_position_usd": "1000.00",
        },
        "controls": {
            "kill_switch": {
                "required": True,
                "control_id": "offline-reviewed-kill-switch-v1",
            },
            "reconciliation": {
                "required": True,
                "control_id": "offline-reviewed-reconciliation-v1",
                "max_age_seconds": 30,
            },
            "max_market_data_age_seconds": 2,
            "max_clock_skew_seconds": 1,
        },
    }
    policy["approval"] = {
        "two_person_rule": True,
        "human_approved": True,
        "policy_payload_sha256": "0" * 64,
        "approved_at_utc": "2029-12-31T00:00:00Z",
        "expires_at_utc": "2030-01-02T00:00:00Z",
        "approvers": [
            {
                "identity": "strategy-owner",
                "role": "strategy_owner",
                "approved_at_utc": "2029-12-31T00:00:00Z",
                "signed_payload_sha256": "0" * 64,
                "signature": {
                    "algorithm": "EXTERNAL_DETACHED",
                    "key_id": "strategy-owner-key",
                    "detached_signature_sha256": "c" * 64,
                    "verified": True,
                },
            },
            {
                "identity": "risk-reviewer",
                "role": "risk_reviewer",
                "approved_at_utc": "2029-12-31T00:01:00Z",
                "signed_payload_sha256": "0" * 64,
                "signature": {
                    "algorithm": "EXTERNAL_DETACHED",
                    "key_id": "risk-reviewer-key",
                    "detached_signature_sha256": "d" * 64,
                    "verified": True,
                },
            },
        ],
    }
    digest = policy_payload_sha256(policy)
    policy["approval"]["policy_payload_sha256"] = digest
    for approver in policy["approval"]["approvers"]:
        approver["signed_payload_sha256"] = digest
    return policy


def _document(*, policy: dict | None = None, runtime: dict | None = None) -> dict:
    return {
        "schema": "live_readiness_validation_v1",
        "frozen_state": "PAPER_ONLY",
        "candidate_policy": _candidate_policy() if policy is None else policy,
        "runtime_snapshot": _runtime_snapshot() if runtime is None else runtime,
    }


def _rebind_approval(policy: dict) -> None:
    digest = policy_payload_sha256(policy)
    policy["approval"]["policy_payload_sha256"] = digest
    for approver in policy["approval"]["approvers"]:
        approver["signed_payload_sha256"] = digest


class LiveReadinessDefaultTests(unittest.TestCase):
    def test_missing_candidate_policy_is_blocked_and_frozen_paper_only(self) -> None:
        document = {
            "schema": "live_readiness_validation_v1",
            "frozen_state": "PAPER_ONLY",
            "candidate_policy": None,
            "runtime_snapshot": {
                "strategy_plan_sha256": "a" * 64,
                "canonical_runtime_registry_raw_sha256": "b" * 64,
                "account_alias": "future-live-primary",
                "venue": "gateio",
                "requested_capabilities": {
                    "authenticated_api": False,
                    "live_orders": False,
                    "real_capital": False,
                    "leverage": False,
                    "margin": False,
                },
                "requested_notional_usd": "0",
                "current_daily_loss_usd": "0",
                "resulting_position_usd": "0",
                "kill_switch_ready": False,
                "reconciliation_ok": False,
                "reconciliation_age_seconds": 0,
                "market_data_age_seconds": 0,
                "clock_skew_seconds": 0,
            },
        }

        result = validate_readiness(document, now=NOW)

        self.assertEqual(result["status"], BLOCKED_LIVE)
        self.assertEqual(result["frozen_state"], PAPER_ONLY)
        self.assertIn("missing_candidate_policy", result["blockers"])
        self.assertFalse(result["candidate_policy_complete"])
        self.assertFalse(result["live_execution_allowed"])
        self.assertEqual(
            result["effective_permissions"],
            {
                "authenticated_api": False,
                "live_orders": False,
                "real_capital": False,
                "leverage": False,
                "margin": False,
            },
        )

    def test_complete_candidate_is_preparation_only_never_live_authorization(self) -> None:
        result = validate_readiness(_document(), now=NOW)

        self.assertEqual(result["status"], PREPARATION_ONLY)
        self.assertEqual(result["frozen_state"], PAPER_ONLY)
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["candidate_policy_complete"])
        self.assertFalse(result["live_execution_allowed"])
        self.assertTrue(result["separate_execution_authorization_required"])
        self.assertFalse(any(result["effective_permissions"].values()))


class LiveReadinessBlockingTests(unittest.TestCase):
    def assert_blocked(self, document: dict, reason: str) -> dict:
        result = validate_readiness(document, now=NOW)
        self.assertEqual(result["status"], BLOCKED_LIVE)
        self.assertIn(reason, result["blockers"])
        self.assertFalse(result["candidate_policy_complete"])
        self.assertFalse(result["live_execution_allowed"])
        self.assertFalse(any(result["effective_permissions"].values()))
        return result

    def test_missing_approval_is_blocked(self) -> None:
        policy = _candidate_policy()
        del policy["approval"]

        self.assert_blocked(_document(policy=policy), "missing_approval")

    def test_expired_approval_is_blocked(self) -> None:
        policy = _candidate_policy()
        policy["approval"]["expires_at_utc"] = "2029-12-31T23:59:59Z"

        self.assert_blocked(_document(policy=policy), "approval_expired")

    def test_signed_payload_binds_expiry_and_approver_identity(self) -> None:
        cases = []

        extended = _candidate_policy()
        extended["approval"]["expires_at_utc"] = "2030-01-03T00:00:00Z"
        cases.append(extended)

        renamed = _candidate_policy()
        renamed["approval"]["approvers"][0]["identity"] = "replacement-owner"
        cases.append(renamed)

        for policy in cases:
            with self.subTest(policy_id=policy["policy_id"]):
                self.assert_blocked(
                    _document(policy=policy),
                    "approval_payload_hash_mismatch",
                )

    def test_two_distinct_human_approvals_are_required(self) -> None:
        policy = _candidate_policy()
        policy["approval"]["approvers"] = policy["approval"]["approvers"][:1]

        self.assert_blocked(_document(policy=policy), "two_person_approval_missing")

    def test_human_and_external_signature_receipts_are_required(self) -> None:
        cases = []

        human = _candidate_policy()
        human["approval"]["human_approved"] = False
        cases.append((human, "human_approval_missing"))

        payload = _candidate_policy()
        payload["approval"]["policy_payload_sha256"] = "e" * 64
        cases.append((payload, "approval_payload_hash_mismatch"))

        signed_payload = _candidate_policy()
        signed_payload["approval"]["approvers"][0]["signed_payload_sha256"] = "e" * 64
        cases.append((signed_payload, "approval_signature_payload_hash_mismatch"))

        verification = _candidate_policy()
        verification["approval"]["approvers"][0]["signature"]["verified"] = False
        cases.append((verification, "approval_signature_unverified"))

        for policy, blocker in cases:
            with self.subTest(blocker=blocker):
                self.assert_blocked(_document(policy=policy), blocker)

    def test_two_person_signatures_must_use_distinct_keys_and_receipts(self) -> None:
        same_key = _candidate_policy()
        same_key["approval"]["approvers"][1]["signature"]["key_id"] = same_key[
            "approval"
        ]["approvers"][0]["signature"]["key_id"]

        same_signature = _candidate_policy()
        same_signature["approval"]["approvers"][1]["signature"][
            "detached_signature_sha256"
        ] = same_signature["approval"]["approvers"][0]["signature"][
            "detached_signature_sha256"
        ]

        cases = (
            (same_key, "two_person_signature_keys_not_distinct"),
            (same_signature, "two_person_signatures_not_distinct"),
        )
        for policy, blocker in cases:
            with self.subTest(blocker=blocker):
                self.assert_blocked(_document(policy=policy), blocker)

    def test_strategy_and_registry_hash_mismatches_are_blocked(self) -> None:
        cases = (
            (
                "strategy_plan_sha256",
                "e" * 64,
                "strategy_plan_hash_mismatch",
            ),
            (
                "canonical_runtime_registry_raw_sha256",
                "f" * 64,
                "canonical_runtime_registry_hash_mismatch",
            ),
        )
        for field, value, blocker in cases:
            with self.subTest(field=field):
                runtime = _runtime_snapshot(**{field: value})
                self.assert_blocked(_document(runtime=runtime), blocker)

    def test_notional_daily_loss_and_position_limit_violations_are_blocked(self) -> None:
        cases = (
            ("requested_notional_usd", "1500.01", "max_notional_exceeded"),
            ("current_daily_loss_usd", "100.01", "max_daily_loss_exceeded"),
            ("resulting_position_usd", "1000.01", "max_position_exceeded"),
        )
        for field, value, blocker in cases:
            with self.subTest(field=field):
                runtime = _runtime_snapshot(**{field: value})
                self.assert_blocked(_document(runtime=runtime), blocker)

    def test_kill_switch_must_be_ready(self) -> None:
        runtime = _runtime_snapshot(kill_switch_ready=False)

        self.assert_blocked(_document(runtime=runtime), "kill_switch_not_ready")

    def test_reconciliation_must_be_ok_and_fresh(self) -> None:
        cases = (
            ({"reconciliation_ok": False}, "reconciliation_not_ok"),
            ({"reconciliation_age_seconds": 31}, "reconciliation_stale"),
        )
        for overrides, blocker in cases:
            with self.subTest(blocker=blocker):
                runtime = _runtime_snapshot(**overrides)
                self.assert_blocked(_document(runtime=runtime), blocker)

    def test_market_data_staleness_and_clock_skew_are_bounded(self) -> None:
        cases = (
            ({"market_data_age_seconds": 3}, "market_data_stale"),
            ({"clock_skew_seconds": 2}, "clock_skew_exceeded"),
        )
        for overrides, blocker in cases:
            with self.subTest(blocker=blocker):
                runtime = _runtime_snapshot(**overrides)
                self.assert_blocked(_document(runtime=runtime), blocker)

    def test_account_and_venue_must_be_allowlisted(self) -> None:
        runtime = _runtime_snapshot(venue="mexc")

        self.assert_blocked(_document(runtime=runtime), "account_venue_not_allowlisted")

    def test_each_requested_capability_must_be_explicitly_allowed(self) -> None:
        policy = _candidate_policy()
        policy["allowed_capabilities"]["margin"] = False
        _rebind_approval(policy)

        self.assert_blocked(_document(policy=policy), "capability_not_allowed:margin")


class LiveReadinessSchemaTests(unittest.TestCase):
    def test_unknown_fields_are_rejected_at_every_schema_level(self) -> None:
        mutations = {
            "envelope": lambda item: item.__setitem__("unexpected", True),
            "runtime": lambda item: item["runtime_snapshot"].__setitem__("unexpected", True),
            "requested_capabilities": lambda item: item["runtime_snapshot"][
                "requested_capabilities"
            ].__setitem__("withdrawal", True),
            "policy": lambda item: item["candidate_policy"].__setitem__("unexpected", True),
            "allowlist": lambda item: item["candidate_policy"]["account_venue_allowlist"][0].__setitem__(
                "unexpected", True
            ),
            "allowed_capabilities": lambda item: item["candidate_policy"][
                "allowed_capabilities"
            ].__setitem__("transfer", True),
            "limits": lambda item: item["candidate_policy"]["limits"].__setitem__(
                "unexpected", "1"
            ),
            "controls": lambda item: item["candidate_policy"]["controls"].__setitem__(
                "unexpected", True
            ),
            "kill_switch": lambda item: item["candidate_policy"]["controls"][
                "kill_switch"
            ].__setitem__("unexpected", True),
            "reconciliation": lambda item: item["candidate_policy"]["controls"][
                "reconciliation"
            ].__setitem__("unexpected", True),
            "approval": lambda item: item["candidate_policy"]["approval"].__setitem__(
                "unexpected", True
            ),
            "approver": lambda item: item["candidate_policy"]["approval"]["approvers"][0].__setitem__(
                "unexpected", True
            ),
            "signature": lambda item: item["candidate_policy"]["approval"]["approvers"][0][
                "signature"
            ].__setitem__("unexpected", True),
        }
        for level, mutate in mutations.items():
            with self.subTest(level=level):
                document = copy.deepcopy(_document())
                mutate(document)
                with self.assertRaisesRegex(PolicyFormatError, "unknown field"):
                    validate_readiness(document, now=NOW)

    def test_schema_types_hashes_and_frozen_state_are_strict(self) -> None:
        cases = []

        wrong_state = _document()
        wrong_state["frozen_state"] = "LIVE"
        cases.append((wrong_state, "frozen_state must remain PAPER_ONLY"))

        uppercase_hash = _document()
        uppercase_hash["runtime_snapshot"]["strategy_plan_sha256"] = "A" * 64
        cases.append((uppercase_hash, "lowercase SHA-256"))

        numeric_limit = _document()
        numeric_limit["candidate_policy"]["limits"]["max_notional_usd"] = 1500.0
        cases.append((numeric_limit, "canonical decimal string"))

        boolean_age = _document()
        boolean_age["runtime_snapshot"]["market_data_age_seconds"] = True
        cases.append((boolean_age, "non-negative integer"))

        for document, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PolicyFormatError, message):
                    validate_readiness(document, now=NOW)

    def test_validation_is_deterministic_and_blockers_are_sorted(self) -> None:
        runtime = _runtime_snapshot(
            kill_switch_ready=False,
            reconciliation_ok=False,
            market_data_age_seconds=3,
            clock_skew_seconds=2,
        )
        document = _document(runtime=runtime)

        first = validate_readiness(document, now=NOW)
        second = validate_readiness(copy.deepcopy(document), now=NOW)

        self.assertEqual(first, second)
        self.assertEqual(first["blockers"], sorted(first["blockers"]))
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_module_imports_no_network_process_or_scheduler_clients(self) -> None:
        source_path = SRC / "live_readiness_gate.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])

        self.assertTrue(
            imports.isdisjoint(
                {
                    "aiohttp",
                    "httpx",
                    "requests",
                    "schedule",
                    "socket",
                    "subprocess",
                    "urllib",
                }
            )
        )


class LiveReadinessCliTests(unittest.TestCase):
    def run_cli(self, document: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_path = Path(temp_dir) / "validation.json"
            policy_path.write_text(
                json.dumps(document, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            return subprocess.run(
                [
                    sys.executable,
                    str(SRC / "live_readiness_gate.py"),
                    "--validate",
                    str(policy_path),
                    "--json",
                    "--now",
                    "2030-01-01T00:00:00Z",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

    def test_cli_emits_preparation_only_json_for_complete_candidate(self) -> None:
        completed = self.run_cli(_document())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], PREPARATION_ONLY)
        self.assertFalse(result["live_execution_allowed"])
        self.assertEqual(completed.stderr, "")

    def test_cli_returns_nonzero_blocked_live_json(self) -> None:
        document = _document()
        document["candidate_policy"] = None

        completed = self.run_cli(document)

        self.assertEqual(completed.returncode, 2, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], BLOCKED_LIVE)
        self.assertIn("missing_candidate_policy", result["blockers"])

    def test_cli_maps_unknown_fields_to_blocked_live_json(self) -> None:
        document = _document()
        document["candidate_policy"]["limits"]["surprise"] = "1"

        completed = self.run_cli(document)

        self.assertEqual(completed.returncode, 2, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], BLOCKED_LIVE)
        self.assertEqual(result["blockers"], ["invalid_policy_document"])
        self.assertRegex(result["validation_errors"][0], "unknown field")


if __name__ == "__main__":
    unittest.main()
