from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PLAN = (
    ROOT
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-planonly-20260813-pagecap-provenance-slotintegrity-v6.json"
)
SOURCE_FREEZER = ROOT / "tools" / "freeze_exact_approved_slow_liquidity_history_recollect.ps1"
SOURCE_LAUNCHER = ROOT / "tools" / "start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
SOURCE_ACTIVE_RUN_GATE_CHECKER = ROOT / "tools" / "check_active_run_gate.ps1"
SOURCE_CONTROL_PLANE = (
    ROOT / "trading_mvp" / "src" / "slow_liquidity_recollect_control_plane.py"
)
SOURCE_WRITER_CLAIM = ROOT / "trading_mvp" / "src" / "global_market_writer_claim.py"
SOURCE_UNIVERSE = (
    ROOT
    / "docs"
    / "plans"
    / "slow-liquidity-history-recollect-universe-20260812-pagecapfix-v1.csv"
)
PWSH = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class SlowLiquidityRecollectFreezerIntegrationTests(unittest.TestCase):
    @staticmethod
    def _terminate_process_tree(pid: int) -> None:
        taskkill = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )

    def setUp(self) -> None:
        if not PWSH.is_file():
            self.skipTest("PowerShell 7 is not available")
        self.temp = tempfile.TemporaryDirectory()
        self.fixture_root = Path(self.temp.name) / "fixture repo"
        self.tools = self.fixture_root / "tools"
        self.plans = self.fixture_root / "docs" / "plans"
        self.agent_log = self.fixture_root / "docs" / "agent-log"
        self.source = self.fixture_root / "trading_mvp" / "src"
        self.output = self.fixture_root / "output"
        self.receipt = self.agent_log / "approvals" / "approval.json"
        self.launch_record = self.agent_log / "run-gates" / "launch.json"
        self.writer_claim = self.agent_log / "active-market-data-writer-claim.json"
        self.policy = self.plans / "trading-mvp-autopilot-policy-v1.json"
        self.gate = self.agent_log / "active-run-gate.json"
        self.plan_path = self.plans / "recollect-plan.json"
        self.freezer = self.tools / SOURCE_FREEZER.name
        self.active_run_gate_checker = self.tools / SOURCE_ACTIVE_RUN_GATE_CHECKER.name
        self.control_plane = self.source / SOURCE_CONTROL_PLANE.name
        self.launcher = self.tools / "start_exact_approved_slow_liquidity_history_recollect_visible.ps1"
        self.collector = self.source / "slow_liquidity_history_collector.py"
        self.writer_claim_cli = self.source / SOURCE_WRITER_CLAIM.name
        self.guard = self.tools / "check_trading_mvp_autopilot.ps1"
        self.failure_marker = self.fixture_root / "force-postapply-guard-failure"

        self.tools.mkdir(parents=True)
        self.plans.mkdir(parents=True)
        self.agent_log.mkdir(parents=True)
        self.source.mkdir(parents=True)
        shutil.copy2(SOURCE_FREEZER, self.freezer)
        shutil.copy2(SOURCE_ACTIVE_RUN_GATE_CHECKER, self.active_run_gate_checker)
        shutil.copy2(SOURCE_CONTROL_PLANE, self.control_plane)
        shutil.copy2(SOURCE_WRITER_CLAIM, self.writer_claim_cli)
        self.collector.write_text(
            "import time\ntime.sleep(120)\n",
            encoding="utf-8",
            newline="\n",
        )
        fixture_universe = self.plans / SOURCE_UNIVERSE.name
        shutil.copy2(SOURCE_UNIVERSE, fixture_universe)

        write_json(
            self.policy,
            {
                "schema": "fixture_policy_v1",
                "policy_id": "fixture_preapproval_policy",
                "status": "ACTIVE",
            },
        )
        write_json(
            self.gate,
            {
                "schema": "fixture_gate_v1",
                "status": "READY_FOR_POSTPROCESS",
                "next_goal_decision": (
                    "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_REJECTED_"
                    "NEEDS_RECOLLECT_OR_RESCOPE"
                ),
            },
        )
        self.original_policy = self.policy.read_bytes()
        self.original_gate = self.gate.read_bytes()
        self._write_fake_launcher()
        self._write_fake_guard()
        self.plan_hash, self.plan_file_sha256, self.approval_text = self._write_plan(
            fixture_universe
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fake_launcher(self) -> None:
        self.launcher.write_text(
            """param(
    [string]$PlanPath,
    [string]$ExpectedPlanHash,
    [string]$ExpectedPlanFileSha256,
    [switch]$PreflightOnly,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
[ordered]@{
    status = 'BLOCKED_AWAITING_EXACT_APPROVAL'
    reasons = @('exact_approval_receipt_missing')
    would_start = $false
} | ConvertTo-Json -Depth 5
""",
            encoding="utf-8",
            newline="\n",
        )

    def _write_fake_guard(self) -> None:
        self.guard.write_text(
            """param([switch]$Json)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$policyPath = Join-Path $root 'docs/plans/trading-mvp-autopilot-policy-v1.json'
$gatePath = Join-Path $root 'docs/agent-log/active-run-gate.json'
$failureMarker = Join-Path $root 'force-postapply-guard-failure'
$policy = Get-Content -LiteralPath $policyPath -Raw | ConvertFrom-Json -Depth 100
$gate = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json -Depth 100
$policyHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $policyPath).Hash.ToLowerInvariant()
$rebound = $policy.PSObject.Properties.Name -contains 'slow_liquidity_history_recollect'
if ($rebound -and (Test-Path -LiteralPath $failureMarker)) {
    $policyHash = '0' * 64
}
[ordered]@{
    schema = 'fixture_guard_v1'
    status = 'ACTIVE'
    stop_new_actions = $false
    policy_id = [string]$policy.policy_id
    policy_hash = $policyHash
    usage = [ordered]@{
        status = 'AVAILABLE'
        remaining_percent = 100.0
        event_age_sec = 0.0
        decision = 'CONTINUE'
    }
    gate = [ordered]@{
        status = [string]$gate.status
        next_goal_decision = [string]$gate.next_goal_decision
    }
} | ConvertTo-Json -Depth 10
""",
            encoding="utf-8",
            newline="\n",
        )

    def _write_plan(self, fixture_universe: Path) -> tuple[str, str, str]:
        plan = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
        plan["launcher"]["path"] = str(self.launcher)
        plan["launcher"]["sha256"] = sha256(self.launcher)
        plan["universe"]["path"] = str(fixture_universe)
        plan["universe"]["sha256"] = sha256(fixture_universe)
        for binding in plan["implementation"]["files"]:
            if binding["role"] == "collector":
                binding["path"] = str(self.collector)
                binding["sha256"] = sha256(self.collector)
            elif binding["role"] == "global_writer_claim":
                binding["path"] = str(self.writer_claim_cli)
                binding["sha256"] = sha256(self.writer_claim_cli)
            elif binding["role"] == "approval_control_plane":
                binding["path"] = str(self.control_plane)
                binding["sha256"] = sha256(self.control_plane)
            elif binding["role"] == "approval_rebind_tool":
                binding["path"] = str(self.freezer)
                binding["sha256"] = sha256(self.freezer)
            elif binding["role"] == "active_run_gate_checker":
                binding["path"] = str(self.active_run_gate_checker)
                binding["sha256"] = sha256(self.active_run_gate_checker)
        plan["execution"]["output_path"] = str(self.output)
        plan["execution"]["output_jsonl"] = str(self.output / "ohlcv.jsonl")
        plan["execution"]["manifest_path"] = str(self.output / "manifest.json")
        plan["execution"]["stdout_path"] = str(self.output / "stdout.log")
        plan["execution"]["stderr_path"] = str(self.output / "stderr.log")
        plan["execution"]["launch_record_path"] = str(self.launch_record)
        now = datetime.now().astimezone()
        plan["execution"]["not_before_local"] = (now - timedelta(hours=1)).isoformat(
            timespec="seconds"
        )
        plan["execution"]["latest_start_local"] = (now + timedelta(hours=1)).isoformat(
            timespec="seconds"
        )
        plan["execution"]["hard_deadline_local"] = (now + timedelta(hours=2)).isoformat(
            timespec="seconds"
        )
        plan["approval_receipt"]["path"] = str(self.receipt)
        plan["guard_contract"]["active_policy_path"] = str(self.policy)
        plan["guard_contract"]["preapproval_policy_id"] = (
            "fixture_preapproval_policy"
        )
        plan["guard_contract"]["preapproval_policy_file_sha256"] = sha256(
            self.policy
        )
        canonical = dict(plan)
        canonical.pop("plan_hash", None)
        plan_hash = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        plan["plan_hash"] = plan_hash
        write_json(self.plan_path, plan)
        plan_file_sha256 = sha256(self.plan_path)
        approval_text = (
            plan["approval_request"]["exact_user_text_template"]
            .replace("<PLAN_HASH>", plan_hash)
            .replace("<PLAN_FILE_SHA256>", plan_file_sha256)
        )
        return plan_hash, plan_file_sha256, approval_text

    def _apply_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = str(Path(os.sys.executable))
        env["PATH"] = os.pathsep.join(
            [str(PWSH.parent), os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"]
        )
        return env

    def _apply_command(
        self,
        *,
        expected_plan_hash: str | None = None,
        expected_plan_file_sha256: str | None = None,
        approval_text: str | None = None,
    ) -> list[str]:
        return [
            str(PWSH),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.freezer),
            "-PlanPath",
            str(self.plan_path),
            "-ExpectedPlanHash",
            expected_plan_hash or self.plan_hash,
            "-ExpectedPlanFileSha256",
            expected_plan_file_sha256 or self.plan_file_sha256,
            "-UserApprovalText",
            approval_text or self.approval_text,
            "-Apply",
            "-Json",
        ]

    def _run_apply(
        self,
        *,
        expected_plan_hash: str | None = None,
        expected_plan_file_sha256: str | None = None,
        approval_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._apply_command(
                expected_plan_hash=expected_plan_hash,
                expected_plan_file_sha256=expected_plan_file_sha256,
                approval_text=approval_text,
            ),
            cwd=str(self.fixture_root),
            env=self._apply_env(),
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )

    def test_apply_creates_exact_rebind_without_starting_collector(self) -> None:
        result = self._run_apply()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["status"], "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
        )
        self.assertTrue(self.receipt.is_file())
        policy = json.loads(self.policy.read_text(encoding="utf-8"))
        gate = json.loads(self.gate.read_text(encoding="utf-8"))
        rebind = policy["slow_liquidity_history_recollect"]
        self.assertEqual(rebind["plan_hash"], self.plan_hash)
        self.assertTrue(rebind["actual_collection_allowed"])
        self.assertEqual(
            gate["next_goal_decision"],
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_EXACT_APPROVED_PAGECAP_PROVENANCE_SLOTINTEGRITY_V6",
        )
        self.assertFalse(self.launch_record.exists())
        self.assertFalse(self.writer_claim.exists())
        self.assertFalse(self.output.exists())

    def test_concurrent_apply_commits_one_complete_control_plane_bundle(self) -> None:
        commit_line = (
            "        Write-FileCreateNew -Source $receiptCandidate "
            "-Destination $receiptPath"
        )
        barrier = r"""        $raceReadyDirectory = [Environment]::GetEnvironmentVariable(
            "SLOW_LIQUIDITY_FREEZE_RACE_READY_DIR"
        )
        $raceReleasePath = [Environment]::GetEnvironmentVariable(
            "SLOW_LIQUIDITY_FREEZE_RACE_RELEASE_PATH"
        )
        if (
            -not [string]::IsNullOrWhiteSpace($raceReadyDirectory) -and
            -not [string]::IsNullOrWhiteSpace($raceReleasePath)
        ) {
            New-Item -ItemType Directory -Force -Path $raceReadyDirectory | Out-Null
            [System.IO.File]::WriteAllText(
                (Join-Path $raceReadyDirectory ("{0}.ready" -f $PID)),
                "ready",
                [System.Text.UTF8Encoding]::new($false)
            )
            $raceDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
            while (-not (Test-Path -LiteralPath $raceReleasePath -PathType Leaf)) {
                if ([DateTimeOffset]::UtcNow -ge $raceDeadline) {
                    throw "fixture approval-freeze race release timed out"
                }
                Start-Sleep -Milliseconds 5
            }
        }
""" + commit_line
        freezer_source = self.freezer.read_text(encoding="utf-8-sig")
        self.assertEqual(freezer_source.count(commit_line), 1)
        self.freezer.write_text(
            freezer_source.replace(commit_line, barrier, 1),
            encoding="utf-8",
            newline="\n",
        )
        self.plan_hash, self.plan_file_sha256, self.approval_text = self._write_plan(
            self.plans / SOURCE_UNIVERSE.name
        )

        ready_dir = self.fixture_root / "freeze-race-ready"
        release_path = self.fixture_root / "freeze-race-release"
        env = self._apply_env()
        env["SLOW_LIQUIDITY_FREEZE_RACE_READY_DIR"] = str(ready_dir)
        env["SLOW_LIQUIDITY_FREEZE_RACE_RELEASE_PATH"] = str(release_path)
        processes = [
            subprocess.Popen(
                self._apply_command(),
                cwd=str(self.fixture_root),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        try:
            deadline = time.monotonic() + 45.0
            while len(list(ready_dir.glob("*.ready"))) != 2:
                if any(process.poll() is not None for process in processes):
                    early = [process.communicate(timeout=5) for process in processes]
                    self.fail(f"approval-freeze participant exited early: {early}")
                if time.monotonic() >= deadline:
                    self.fail("approval-freeze participants did not reach commit barrier")
                time.sleep(0.02)
            release_path.write_text("go", encoding="utf-8")
            results = [process.communicate(timeout=90) for process in processes]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        successes = [
            (process, stdout, stderr)
            for process, (stdout, stderr) in zip(processes, results, strict=True)
            if process.returncode == 0
        ]
        failures = [
            (process, stdout, stderr)
            for process, (stdout, stderr) in zip(processes, results, strict=True)
            if process.returncode != 0
        ]
        diagnostics = [
            {
                "returncode": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
            for process, stdout, stderr in successes + failures
        ]
        self.assertEqual(1, len(successes), diagnostics)
        self.assertEqual(1, len(failures), diagnostics)
        winner = json.loads(successes[0][1])
        self.assertEqual(
            winner["status"], "FROZEN_WITH_EXACT_RECOLLECT_EXECUTION_APPROVAL"
        )
        self.assertTrue(self.receipt.is_file())

        receipt_sha256 = sha256(self.receipt)
        validation = subprocess.run(
            [
                os.sys.executable,
                str(self.control_plane),
                "validate",
                "--plan",
                str(self.plan_path),
                "--expected-plan-file-sha256",
                self.plan_file_sha256,
                "--expected-plan-hash",
                self.plan_hash,
                "--receipt",
                str(self.receipt),
                "--expected-receipt-file-sha256",
                receipt_sha256,
                "--policy",
                str(self.policy),
                "--gate",
                str(self.gate),
            ],
            cwd=str(self.fixture_root),
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertEqual(json.loads(validation.stdout)["status"], "VALID")
        self.assertEqual(winner["approval_receipt_sha256"], receipt_sha256)
        self.assertFalse(self.launch_record.exists())
        self.assertFalse(self.writer_claim.exists())
        self.assertFalse(self.output.exists())

    def test_apply_rejects_superseded_expected_hashes_without_side_effects(self) -> None:
        stale_plan_hash = "1" * 64
        stale_plan_file_sha256 = "2" * 64
        stale_approval_text = (
            json.loads(self.plan_path.read_text(encoding="utf-8"))["approval_request"]
            ["exact_user_text_template"]
            .replace("<PLAN_HASH>", stale_plan_hash)
            .replace("<PLAN_FILE_SHA256>", stale_plan_file_sha256)
        )

        result = self._run_apply(
            expected_plan_hash=stale_plan_hash,
            expected_plan_file_sha256=stale_plan_file_sha256,
            approval_text=stale_approval_text,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.policy.read_bytes(), self.original_policy)
        self.assertEqual(self.gate.read_bytes(), self.original_gate)
        self.assertFalse(self.launch_record.exists())
        self.assertFalse(self.writer_claim.exists())
        self.assertFalse(self.output.exists())

    def test_apply_rejects_superseded_text_against_current_hashes(self) -> None:
        stale_approval_text = self.approval_text.replace(
            self.plan_hash,
            "1" * 64,
            1,
        )

        result = self._run_apply(approval_text=stale_approval_text)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.policy.read_bytes(), self.original_policy)
        self.assertEqual(self.gate.read_bytes(), self.original_gate)
        self.assertFalse(self.launch_record.exists())
        self.assertFalse(self.writer_claim.exists())
        self.assertFalse(self.output.exists())

    def test_owned_stop_is_terminal_releases_claim_and_forbids_retry(self) -> None:
        source = SOURCE_LAUNCHER.read_text(encoding="utf-8-sig")
        patched, replacements = re.subn(
            r"function Test-VisibleConsoleWindow \{.*?\n\}\n\nfunction ConvertTo-ProcessArgument",
            (
                "function Test-VisibleConsoleWindow { return $true }\n\n"
                "function ConvertTo-ProcessArgument"
            ),
            source,
            count=1,
            flags=re.DOTALL,
        )
        self.assertEqual(replacements, 1)
        self.launcher.write_text(patched, encoding="utf-8", newline="\n")
        self.plan_hash, self.plan_file_sha256, self.approval_text = self._write_plan(
            self.plans / SOURCE_UNIVERSE.name
        )
        freeze = self._run_apply()
        self.assertEqual(freeze.returncode, 0, msg=freeze.stderr)
        receipt_sha256 = sha256(self.receipt)

        env = os.environ.copy()
        env["TRADING_MVP_PYTHON"] = str(Path(os.sys.executable))
        env["PATH"] = os.pathsep.join(
            [
                str(PWSH.parent),
                os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
            ]
        )
        worker = subprocess.Popen(
            [
                str(PWSH),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.launcher),
                "-PlanPath",
                str(self.plan_path),
                "-ExpectedPlanHash",
                self.plan_hash,
                "-ExpectedPlanFileSha256",
                self.plan_file_sha256,
                "-ExpectedApprovalReceiptSha256",
                receipt_sha256,
                "-VisibleWorker",
            ],
            cwd=str(self.fixture_root),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        writer_pid: int | None = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if worker.poll() is not None:
                    stdout, stderr = worker.communicate(timeout=5)
                    self.fail(
                        f"fixture worker exited before RUNNING: {stdout}\n{stderr}"
                    )
                if self.launch_record.is_file() and self.writer_claim.is_file():
                    record = json.loads(
                        self.launch_record.read_text(encoding="utf-8-sig")
                    )
                    if record.get("status") == "RUNNING":
                        writer_pid = int(record["writer_pid"])
                        break
                time.sleep(0.1)
            else:
                self.fail("fixture worker did not reach RUNNING")

            stop = subprocess.run(
                [
                    str(PWSH),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.launcher),
                    "-PlanPath",
                    str(self.plan_path),
                    "-ExpectedPlanHash",
                    self.plan_hash,
                    "-ExpectedPlanFileSha256",
                    self.plan_file_sha256,
                    "-ExpectedApprovalReceiptSha256",
                    receipt_sha256,
                    "-Stop",
                    "-Json",
                ],
                cwd=str(self.fixture_root),
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(stop.returncode, 0, msg=stop.stderr)
            self.assertEqual(json.loads(stop.stdout)["status"], "STOP_REQUESTED")
            stdout, stderr = worker.communicate(timeout=30)
            self.assertNotEqual(worker.returncode, 0, msg=stdout + stderr)
        finally:
            if worker.poll() is None:
                if writer_pid is not None:
                    self._terminate_process_tree(writer_pid)
                try:
                    worker.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    self._terminate_process_tree(worker.pid)
                    worker.communicate(timeout=10)

        record = json.loads(self.launch_record.read_text(encoding="utf-8-sig"))
        gate = json.loads(self.gate.read_text(encoding="utf-8-sig"))
        self.assertEqual(record["status"], "STOPPED_INCOMPLETE")
        self.assertFalse(record["retry_authorized"])
        self.assertEqual(gate["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(
            gate["next_goal_decision"],
            "SLOW_LIQUIDITY_HISTORY_RECOLLECT_STOPPED_INCOMPLETE_NO_RETRY",
        )
        self.assertFalse(self.writer_claim.exists())
        archives = list(
            (self.agent_log / "global-writer-claim-archive").glob("*.json")
        )
        self.assertEqual(len(archives), 1)
        archived = json.loads(archives[0].read_text(encoding="utf-8-sig"))
        self.assertEqual(archived["final_status"], "STOPPED_INCOMPLETE")

    def test_postapply_guard_failure_restores_original_control_plane(self) -> None:
        self.failure_marker.touch()

        result = self._run_apply()

        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("Fresh guard did not confirm", combined)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.policy.read_bytes(), self.original_policy)
        self.assertEqual(self.gate.read_bytes(), self.original_gate)
        self.assertFalse(self.launch_record.exists())
        self.assertFalse(self.writer_claim.exists())
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
