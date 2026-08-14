from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "tools" / "slow_liquidity_exact_recollect_status.ps1"
QUICK_STATUS = REPO_ROOT / "tools" / "trading_quick_status.ps1"
NEXT_STEP = REPO_ROOT / "tools" / "trading_next_goal_step.ps1"
GOAL_STATUS = REPO_ROOT / "tools" / "trading_goal_status.ps1"
LAUNCHER = (
    REPO_ROOT
    / "tools"
    / "start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
)
FREEZER = (
    REPO_ROOT
    / "tools"
    / "freeze_exact_approved_slow_liquidity_history_recollect.ps1"
)
QUALITY_RUNNER = REPO_ROOT / "tools" / "run_exact_slow_liquidity_recollect_quality.ps1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class ExactLifecycleFixture:
    plan_hash = "a" * 64
    receipt_hash = "b" * 64
    run_id = "slow_liquidity_history_recollect_lifecycle_fixture"
    bases = ["STETH", "WEETH", "CC"]
    exchanges = ["mexc", "gateio"]
    timeframes = ["1h", "4h"]

    def __init__(self, root: Path) -> None:
        self.root = root
        self.plan_path = root / "plan.json"
        self.readiness_path = root / "readiness.json"
        self.gate_path = root / "active-run-gate.json"
        self.policy_path = root / "policy.json"
        self.receipt_path = root / "approval.json"
        self.launch_path = root / "launch.json"
        self.output_path = root / "output"
        self.output_jsonl = self.output_path / "ohlcv.jsonl"
        self.manifest_path = self.output_path / "manifest.json"
        self.quality_path = root / "quality.json"

        self.plan = {
            "schema": "trading_mvp_slow_liquidity_history_recollect_planonly_v1",
            "mode": "PlanOnly",
            "status": "AWAIT_EXACT_HASH_BOUND_APPROVAL",
            "actual_collection_allowed": False,
            "plan_hash": self.plan_hash,
            "universe": {"bases": self.bases},
            "execution": {
                "run_id": self.run_id,
                "output_path": str(self.output_path),
                "output_jsonl": str(self.output_jsonl),
                "manifest_path": str(self.manifest_path),
                "launch_record_path": str(self.launch_path),
                "exchanges": self.exchanges,
                "timeframes": self.timeframes,
                "history_days": 56,
                "max_runtime_sec": 900,
                "hard_output_cap_bytes": 100_000_000,
                "maximum_http_attempts": 126,
            },
            "guard_contract": {
                "active_policy_path": str(self.policy_path),
                "required_decision_after_approval": (
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6"
                ),
                "required_policy_rebind_status": (
                    "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
                ),
                "required_policy_rebind_schema": (
                    "trading_mvp_slow_liquidity_history_recollect_policy_rebind_v1"
                ),
            },
            "launcher": {
                "path": str(LAUNCHER),
                "sha256": sha256(LAUNCHER),
            },
            "approval_receipt": {"path": str(self.receipt_path)},
            "data_quality_after_success": {
                "output_path": str(self.quality_path),
                "exact_runner_path": str(QUALITY_RUNNER),
                "exact_runner_sha256": sha256(QUALITY_RUNNER),
            },
            "commands": {
                "preflight": self._launcher_command("-PreflightOnly -Json"),
                "approval_freeze_preflight": self._approval_packet_command(
                    "-PreflightOnly -Json"
                ),
                "start_after_receipt": self._launcher_command(
                    "-ExpectedApprovalReceiptSha256 <RECEIPT_SHA256> -Json"
                ),
                "status": self._launcher_command("-Status -Json"),
                "stop": self._launcher_command(
                    "-ExpectedApprovalReceiptSha256 <RECEIPT_SHA256> -Stop -Json"
                ),
                "data_quality_after_complete_preflight": self._quality_command(
                    "-PreflightOnly -Json"
                ),
                "data_quality_after_complete": self._quality_command("-Json"),
            },
        }
        write_json(self.plan_path, self.plan)
        self.plan_file_sha256 = sha256(self.plan_path)
        write_json(
            self.readiness_path,
            {
                "schema": (
                    "trading_mvp_one_week_historical_edge_sprint_readiness_v1"
                ),
                "status": "AWAIT_EXACT_SLOW_LIQUIDITY_RECOLLECT_APPROVAL",
                "slow_liquidity_candidate": {
                    "exact_plan_path": str(self.plan_path),
                    "exact_plan_file_sha256": self.plan_file_sha256,
                    "exact_plan_hash": self.plan_hash,
                },
            },
        )
        self.write_gate(
            status="READY_FOR_POSTPROCESS",
            decision=(
                "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_OR_RESCOPE"
            ),
            run_id="slow_liquidity_history_collect_rejected_fixture",
            postapproval=False,
        )

    def _launcher_command(self, suffix: str) -> str:
        return (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{LAUNCHER}" '
            f'-PlanPath "{self.plan_path}" -ExpectedPlanHash <PLAN_HASH> '
            f"-ExpectedPlanFileSha256 <PLAN_FILE_SHA256> {suffix}"
        )

    def _approval_packet_command(self, suffix: str) -> str:
        return (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{FREEZER}" '
            f'-PlanPath "{self.plan_path}" -ExpectedPlanHash <PLAN_HASH> '
            f"-ExpectedPlanFileSha256 <PLAN_FILE_SHA256> {suffix}"
        )

    def _quality_command(self, suffix: str) -> str:
        return (
            f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{QUALITY_RUNNER}" '
            f'-PlanPath "{self.plan_path}" -ExpectedPlanHash <PLAN_HASH> '
            f"-ExpectedPlanFileSha256 <PLAN_FILE_SHA256> "
            f"-ExpectedApprovalReceiptSha256 <RECEIPT_SHA256> {suffix}"
        )

    def freeze_approval(self) -> None:
        receipt = {
            "schema": "trading_mvp_slow_liquidity_history_recollect_approval_v1",
            "status": "APPROVED",
            "approval_type": "EXACT_HASH_BOUND_VISIBLE_PUBLIC_RECOLLECT",
            "plan_path": str(self.plan_path),
            "plan_file_sha256": self.plan_file_sha256,
            "plan_hash": self.plan_hash,
            "run_id": self.run_id,
            "bases": self.bases,
            "exchanges": self.exchanges,
            "timeframes": self.timeframes,
            "history_days": 56,
            "max_runtime_sec": 900,
            "hard_output_cap_bytes": 100_000_000,
            "maximum_http_attempts": 126,
            "policy_rebind_status": "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL",
            "required_guard_decision": (
                "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6"
            ),
            "single_use": True,
            "stop_incomplete_retry_authorized": False,
            "official_identity_verification_authorized": False,
            "evaluator_or_oos_authorized": False,
            "paper_or_live_authorized": False,
            "private_api_or_real_capital_authorized": False,
            "receipt_hash": self.receipt_hash,
        }
        write_json(self.receipt_path, receipt)
        self.receipt_file_sha256 = sha256(self.receipt_path)
        rebind = {
            "schema": "trading_mvp_slow_liquidity_history_recollect_policy_rebind_v1",
            "status": "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL",
            "run_id": self.run_id,
            "plan_path": str(self.plan_path),
            "plan_file_sha256": self.plan_file_sha256,
            "plan_hash": self.plan_hash,
            "approval_receipt_path": str(self.receipt_path),
            "approval_receipt_file_sha256": self.receipt_file_sha256,
            "approval_receipt_hash": self.receipt_hash,
            "actual_collection_allowed": True,
            "stop_incomplete_retry_authorized": False,
        }
        write_json(
            self.policy_path,
            {"slow_liquidity_history_recollect": rebind},
        )
        self.write_gate(
            status="READY_FOR_POSTPROCESS",
            decision=(
                "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6"
            ),
            run_id="slow_liquidity_history_collect_rejected_fixture",
        )

    def write_gate(
        self,
        *,
        status: str,
        decision: str,
        run_id: str | None = None,
        postapproval: bool = True,
        quality_committed: bool = False,
    ) -> None:
        gate: dict[str, object] = {
            "schema": "active_run_gate_v1",
            "project": "trading_mvp",
            "status": status,
            "run_id": run_id or self.run_id,
            "final": status == "READY_FOR_POSTPROCESS",
            "next_goal_decision": decision,
            "replay_allowed": False,
            "grid_allowed": False,
            "paper_forward_allowed": False,
            "live_orders": False,
            "api_keys": False,
            "leverage_or_margin": False,
            "stopped_incomplete_retry_authorized": False,
        }
        if postapproval:
            gate.update(
                {
                    "slow_liquidity_recollect_policy_rebind_status": (
                        "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
                    ),
                    "slow_liquidity_recollect_plan_path": str(self.plan_path),
                    "slow_liquidity_recollect_plan_file_sha256": (
                        self.plan_file_sha256
                    ),
                    "slow_liquidity_recollect_plan_hash": self.plan_hash,
                    "slow_liquidity_recollect_approval_receipt_path": str(
                        self.receipt_path
                    ),
                    "slow_liquidity_recollect_approval_receipt_sha256": (
                        self.receipt_file_sha256
                    ),
                    "slow_liquidity_recollect_approval_receipt_hash": (
                        self.receipt_hash
                    ),
                }
            )
        if quality_committed:
            gate.update(
                {
                    "last_slow_liquidity_history_data_quality_output_path": str(
                        self.quality_path
                    ),
                    "last_slow_liquidity_history_data_quality_output_sha256": sha256(
                        self.quality_path
                    ),
                }
            )
        write_json(self.gate_path, gate)

    def write_launch(self, status: str) -> None:
        write_json(
            self.launch_path,
            {
                "schema": "trading_mvp_slow_liquidity_recollect_launch_v1",
                "status": status,
                "run_id": self.run_id,
                "terminal_ownership_verified": True,
                "plan_path": str(self.plan_path),
                "plan_file_sha256": self.plan_file_sha256,
                "plan_hash": self.plan_hash,
                "approval_receipt_path": str(self.receipt_path),
                "approval_receipt_sha256": self.receipt_file_sha256,
                "output_path": str(self.output_path),
                "retry_authorized": False,
            },
        )

    def write_complete_output(self) -> None:
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.output_jsonl.write_text("{}\n", encoding="utf-8")
        write_json(
            self.manifest_path,
            {"run_id": self.run_id, "final": True},
        )

    def write_quality(self, decision: str) -> None:
        accepted = decision.startswith(
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
        )
        write_json(
            self.quality_path,
            {
                "decision": decision,
                "accepted": accepted,
                "terminal": not accepted,
                "retry_authorized": False,
                "rescope_authorized": False,
                "evaluator_or_oos_authorized": False,
                "identity_verification_required": accepted,
                "identity_verification_authorized": False,
                "exact_recollect_provenance": {
                    "run_id": self.run_id,
                    "plan_path": str(self.plan_path),
                    "plan_file_sha256": self.plan_file_sha256,
                    "plan_hash": self.plan_hash,
                    "approval_receipt_path": str(self.receipt_path),
                    "approval_receipt_file_sha256": self.receipt_file_sha256,
                    "launch_record_path": str(self.launch_path),
                    "launch_record_file_sha256": sha256(self.launch_path),
                    "manifest_path": str(self.manifest_path),
                    "manifest_file_sha256": sha256(self.manifest_path),
                    "output_jsonl_path": str(self.output_jsonl),
                    "output_jsonl_file_sha256": sha256(self.output_jsonl),
                    "technical_quality_only": True,
                    "official_identity_verification_authorized": False,
                    "evaluator_or_oos_authorized": False,
                    "stopped_incomplete_retry_authorized": False,
                },
            },
        )


class SlowLiquidityExactLifecycleStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pwsh = shutil.which("pwsh")
        if not cls.pwsh:
            raise unittest.SkipTest("pwsh is not available")

    def run_helper(self, fixture: ExactLifecycleFixture) -> dict[str, object]:
        command = (
            f". '{HELPER}'; "
            f"$gate = Get-Content -Raw -LiteralPath '{fixture.gate_path}' | "
            "ConvertFrom-Json -DateKind String; "
            "Get-SlowLiquidityExactRecollectStatus "
            f"-Gate $gate -PlanPath '{fixture.plan_path}' "
            f"-ReadinessPath '{fixture.readiness_path}' "
            f"-DefaultLauncherPath '{LAUNCHER}' "
            f"-RawGatePath '{fixture.gate_path}' | ConvertTo-Json -Depth 12"
        )
        result = subprocess.run(
            [
                self.pwsh,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        return json.loads(result.stdout)

    def run_router(
        self,
        script: Path,
        fixture: ExactLifecycleFixture,
        *,
        skip_swarm: bool = False,
    ) -> dict[str, object]:
        command = [
            self.pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-GatePath",
            str(fixture.gate_path),
            "-ExactSlowLiquidityRecollectPlanPath",
            str(fixture.plan_path),
            "-SprintReadinessPath",
            str(fixture.readiness_path),
        ]
        if skip_swarm:
            command.append("-SkipSwarm")
        command.append("-Json")
        result = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        return json.loads(result.stdout)

    def test_helper_routes_every_exact_lifecycle_phase_without_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ExactLifecycleFixture(Path(temporary))

            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "AWAITING_EXACT_APPROVAL")
            self.assertTrue(payload["awaiting_approval"])
            self.assertTrue(payload["approval_packet_command_valid"])
            self.assertEqual(
                payload["primary_command"], payload["approval_packet_command"]
            )
            self.assertIn(FREEZER.name, payload["primary_command"])
            self.assertIn("-PreflightOnly", payload["primary_command"])
            self.assertNotIn("-Apply", payload["primary_command"])
            self.assertNotIn("<", payload["primary_command"])
            self.assertIn(LAUNCHER.name, payload["preflight_command"])

            fixture.freeze_approval()
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "APPROVED_AWAITING_VISIBLE_LAUNCH")
            self.assertTrue(payload["approved_awaiting_launch"])
            self.assertIn(fixture.receipt_file_sha256, payload["launch_command"])
            self.assertNotIn("<", payload["launch_command"])

            fixture.write_launch("VISIBLE_WORKER_CLAIMED")
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "VISIBLE_LAUNCH_STARTING")
            self.assertTrue(payload["visible_launch_starting"])
            self.assertEqual(payload["primary_command"], payload["status_command"])

            fixture.output_path.mkdir()
            fixture.write_launch("RUNNING")
            fixture.write_gate(
                status="RUNNING",
                decision="SLOW_LIQUIDITY_HISTORY_RECOLLECT_RUNNING",
            )
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertTrue(payload["running"])
            self.assertIn("-Stop", payload["stop_command"])

            fixture.write_complete_output()
            fixture.write_launch("COMPLETE")
            fixture.write_gate(
                status="READY_FOR_POSTPROCESS",
                decision=(
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_COMPLETED_READY_FOR_DATA_QUALITY"
                ),
            )
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "READY_FOR_TECHNICAL_QUALITY")
            self.assertTrue(payload["ready_for_quality"])
            self.assertEqual(payload["primary_command"], payload["quality_command"])
            self.assertIn("-PreflightOnly", payload["quality_preflight_command"])

            fixture.write_quality("quality_commit_in_progress")
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "TECHNICAL_QUALITY_COMMITTING")
            self.assertTrue(payload["technical_quality_committing"])

            accepted = (
                "SLOW_LIQUIDITY_HISTORY_RECOLLECT_QUALITY_ACCEPTED_"
                "AWAIT_OFFICIAL_IDENTITY_APPROVAL"
            )
            fixture.write_quality(accepted)
            fixture.write_gate(
                status="READY_FOR_POSTPROCESS",
                decision=accepted,
                quality_committed=True,
            )
            payload = self.run_helper(fixture)
            self.assertEqual(
                payload["phase"],
                "QUALITY_ACCEPTED_AWAIT_OFFICIAL_IDENTITY_APPROVAL",
            )
            self.assertTrue(payload["requires_user_approval"])
            self.assertEqual(
                payload["required_user_input"],
                "exact_official_asset_identity_verification_approval",
            )

            tampered_quality = json.loads(
                fixture.quality_path.read_text(encoding="utf-8")
            )
            tampered_quality["exact_recollect_provenance"]["run_id"] = "foreign_run"
            write_json(fixture.quality_path, tampered_quality)
            fixture.write_gate(
                status="READY_FOR_POSTPROCESS",
                decision=accepted,
                quality_committed=True,
            )
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "INTEGRITY_BLOCKED")
            self.assertIn("exact quality run id mismatch", payload["errors"])

            rejected = (
                "TERMINAL_DATA_QUALITY_REJECT_NO_RETRY_WITHOUT_NEW_EXACT_APPROVAL"
            )
            fixture.write_quality(rejected)
            fixture.write_gate(
                status="READY_FOR_POSTPROCESS",
                decision=rejected,
                quality_committed=True,
            )
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "QUALITY_REJECTED_TERMINAL_NO_RETRY")
            self.assertTrue(payload["quality_rejected_terminal_no_retry"])

            fixture.write_launch("STOPPED_INCOMPLETE")
            fixture.write_gate(
                status="STOPPED_INCOMPLETE",
                decision=(
                    "SLOW_LIQUIDITY_HISTORY_RECOLLECT_STOPPED_INCOMPLETE_NO_RETRY"
                ),
            )
            payload = self.run_helper(fixture)
            self.assertEqual(payload["phase"], "STOPPED_INCOMPLETE_NO_RETRY")
            self.assertTrue(payload["stopped_incomplete_no_retry"])
            self.assertNotIn("resume", payload["primary_command"].lower())

    def test_helper_fails_closed_on_receipt_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ExactLifecycleFixture(Path(temporary))
            fixture.freeze_approval()
            receipt = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
            receipt["plan_hash"] = "0" * 64
            write_json(fixture.receipt_path, receipt)

            payload = self.run_helper(fixture)

            self.assertEqual(payload["phase"], "INTEGRITY_BLOCKED")
            self.assertTrue(payload["integrity_blocked"])
            self.assertFalse(payload["plan_valid"])
            self.assertIn("approval receipt plan hash mismatch", payload["errors"])

    def test_helper_fails_closed_on_unsafe_approval_packet_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ExactLifecycleFixture(Path(temporary))
            fixture.plan["commands"]["approval_freeze_preflight"] = (
                fixture._approval_packet_command("-Apply -Json")
            )
            write_json(fixture.plan_path, fixture.plan)
            fixture.plan_file_sha256 = sha256(fixture.plan_path)
            readiness = json.loads(
                fixture.readiness_path.read_text(encoding="utf-8")
            )
            readiness["slow_liquidity_candidate"]["exact_plan_file_sha256"] = (
                fixture.plan_file_sha256
            )
            write_json(fixture.readiness_path, readiness)

            payload = self.run_helper(fixture)

            self.assertEqual(payload["phase"], "INTEGRITY_BLOCKED")
            self.assertFalse(payload["approval_packet_command_valid"])
            self.assertIsNone(payload["approval_packet_command"])
            self.assertIn(
                "exact approval packet command is not PreflightOnly",
                payload["errors"],
            )
            self.assertIn(
                "exact approval packet command would apply approval",
                payload["errors"],
            )

    def test_quick_and_next_route_waiting_phase_to_current_approval_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ExactLifecycleFixture(Path(temporary))

            quick = self.run_router(QUICK_STATUS, fixture, skip_swarm=True)
            self.assertEqual(
                quick["status"],
                "AWAITING_EXACT_SLOW_LIQUIDITY_RECOLLECT_APPROVAL",
            )
            self.assertEqual(
                quick["primary_command"], quick["exact_approval_packet_command"]
            )
            self.assertIn(FREEZER.name, quick["primary_command"])
            self.assertIn(
                "read_current_exact_approval_packet", quick["allowed_actions"]
            )
            self.assertIsNone(quick["exact_visible_launch_command"])
            self.assertIn(
                LAUNCHER.name,
                quick["slow_liquidity_exact_recollect"]["preflight_command"],
            )

            next_step = self.run_router(NEXT_STEP, fixture)
            commands = next_step["commands"]
            self.assertEqual(
                next_step["primary_command"],
                commands["slow_liquidity_exact_recollect_approval_packet"],
            )
            self.assertIn(FREEZER.name, next_step["primary_command"])
            self.assertIn(
                LAUNCHER.name,
                commands["slow_liquidity_exact_recollect_preflight"],
            )
            self.assertEqual(
                commands["visible_collect_preview"],
                commands["slow_liquidity_exact_recollect_preflight"],
            )
            self.assertEqual(
                commands["visible_collect_after_approval"],
                commands["slow_liquidity_exact_recollect_preflight"],
            )

    def test_quick_and_next_route_approved_receipt_to_exact_visible_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ExactLifecycleFixture(Path(temporary))
            fixture.freeze_approval()

            quick = self.run_router(
                QUICK_STATUS,
                fixture,
                skip_swarm=True,
            )
            self.assertEqual(
                quick["status"],
                "EXACT_SLOW_LIQUIDITY_RECOLLECT_APPROVED_READY_FOR_VISIBLE_LAUNCH",
            )
            self.assertFalse(
                quick["requires_explicit_user_approval_for_actual_collect"]
            )
            self.assertIn(fixture.receipt_file_sha256, quick["primary_command"])
            self.assertFalse(quick["would_start"])

            next_step = self.run_router(NEXT_STEP, fixture)
            self.assertEqual(
                next_step["decision"],
                "SLOW_LIQUIDITY_EXACT_RECOLLECT_APPROVED_RUN_VISIBLE_ONCE",
            )
            self.assertFalse(next_step["requires_user_approval_for_actual_collect"])
            self.assertIn(fixture.receipt_file_sha256, next_step["primary_command"])
            self.assertEqual(
                next_step["fast_path"]["reason"],
                "exact_slow_liquidity_lifecycle_is_current",
            )

    def test_goal_status_source_routes_exact_checkpoint_before_generic_gate(self) -> None:
        text = GOAL_STATUS.read_text(encoding="utf-8")
        self.assertIn("slow_liquidity_exact_recollect_checkpoint_gate", text)
        self.assertIn("slow_liquidity_exact_recollect_approval_packet_command", text)
        self.assertIn("slow_liquidity_exact_recollect_launch_command", text)
        self.assertIn("slow_liquidity_exact_recollect_quality_command", text)
        self.assertIn("$slowLiquidityExactRecollectCheckpointGate", text)
        self.assertLess(
            text.index(
                "$nextAllowedAction = if ($slowLiquidityExactRecollectCheckpointGate)"
            ),
            text.index('} elseif ($gate.status -eq "RUNNING") {'),
        )


if __name__ == "__main__":
    unittest.main()
