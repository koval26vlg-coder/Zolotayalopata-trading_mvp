from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh") or shutil.which("pwsh.exe")

MAIN_SCRIPT = "start_listing_momentum_forward_automation_visible.ps1"
V2_SCRIPT = "start_listing_momentum_forward_tick_visible.ps1"
EXPANSION_SCRIPT = "start_listing_momentum_forward_expansion_tick_visible.ps1"

_MISSING = object()


class ListingMomentumLauncherFixture:
    MAIN_HANDOFF_TOKEN = "1" * 32
    MAIN_HANDOFF_RUN_ID = "fixture-scheduler-handoff"
    def __init__(self, root: Path) -> None:
        self.root = root
        self.tools = root / "tools"
        self.src = root / "trading_mvp" / "src"
        self.plans = root / "docs" / "plans"
        self.agent_log = root / "docs" / "agent-log"
        self.run_gates = self.agent_log / "run-gates"
        self.python_marker = root / "python-invocations.jsonl"
        self.child_marker = root / "child-invocations.jsonl"
        self.v2_plan = self.plans / "v2-plan.json"
        self.expansion_plan = self.plans / "expansion-plan.json"
        self.main_state = self.run_gates / "main-state.json"
        self.main_ledger = self.run_gates / "main-attempts.jsonl"
        self.main_claim = self.run_gates / "main-scheduler-claim.json"
        self.scheduler_claim_archive = self.run_gates / "scheduler-claim-archive"
        self.global_claim = self.agent_log / "active-market-data-writer-claim.json"
        self.global_claim_archive = self.agent_log / "global-writer-claim-archive"
        self.legacy_expansion_claim = (
            self.agent_log / "active-market-data-writer-expansion-claim.json"
        )

        self.tools.mkdir(parents=True)
        self.src.mkdir(parents=True)
        self.plans.mkdir(parents=True)
        for script in (MAIN_SCRIPT, V2_SCRIPT, EXPANSION_SCRIPT):
            shutil.copy2(ROOT / "tools" / script, self.tools / script)

        (self.tools / "check_active_run_gate.ps1").write_text(
            """
param([switch]$Json)
switch ($env:FAKE_GATE_MODE) {
    "invalid_json" { Write-Output "{not-json"; exit 0 }
    "nonzero" {
        [ordered]@{
            gate_status = $env:FAKE_GATE_STATUS
            status = $env:FAKE_GATE_AUTHORITATIVE_STATUS
        } | ConvertTo-Json
        exit 9
    }
    "missing_status" {
        [ordered]@{ gate_status = $env:FAKE_GATE_STATUS } | ConvertTo-Json
        exit 0
    }
    default {
        [ordered]@{
            gate_status = $env:FAKE_GATE_STATUS
            status = $env:FAKE_GATE_AUTHORITATIVE_STATUS
        } | ConvertTo-Json
        exit 0
    }
}
""".lstrip(),
            encoding="utf-8",
        )
        monitor = """
import json
import os
import sys
from pathlib import Path

marker = Path(os.environ["FAKE_PYTHON_MARKER"])
marker.parent.mkdir(parents=True, exist_ok=True)
with marker.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")

if "--plan-check" in sys.argv:
    ok = os.environ.get("FAKE_PLAN_OK", "true").lower() == "true"
    print(json.dumps({
        "status": "PLAN_OK" if ok else "PLAN_INVALID",
        "plan_hash": "a" * 64,
        "max_runtime_sec": 30,
        "tick_output_root": "fixture-ticks",
    }))
    raise SystemExit(int(os.environ.get("FAKE_PLAN_EXIT_CODE", "0")))
elif "--status" in sys.argv:
    print(json.dumps({"status": "IDLE"}))
else:
    print("fixture tick complete")
""".lstrip()
        (self.src / "slow_liquidity_listing_momentum_forward_monitor.py").write_text(
            monitor,
            encoding="utf-8",
        )
        (
            self.src
            / "slow_liquidity_listing_momentum_forward_expansion_monitor.py"
        ).write_text(monitor, encoding="utf-8")
        shutil.copy2(
            ROOT / "trading_mvp" / "src" / "global_market_writer_claim.py",
            self.src / "global_market_writer_claim.py",
        )

        self._write_plan(self.v2_plan, "fixture-v2")
        self._write_plan(self.expansion_plan, "fixture-expansion")

    def _write_plan(self, path: Path, plan_id: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "plan_id": plan_id,
                    "plan_hash": "a" * 64,
                    "tick": {
                        "max_runtime_sec": 30,
                        "tick_output_root": str(self.root / "ticks" / plan_id),
                        "state_path": str(self.root / "states" / f"{plan_id}.json"),
                    },
                }
            ),
            encoding="utf-8",
        )

    def script(self, name: str) -> Path:
        return self.tools / name

    def production_artifacts(self) -> tuple[Path, ...]:
        return (
            self.main_state,
            self.main_ledger,
            self.main_claim,
            self.run_gates / "listing_momentum_forward_automation.launch.json",
            self.run_gates / "listing_momentum_forward_monitor.launch.json",
            self.run_gates / "listing_momentum_forward_expansion.launch.json",
            self.agent_log / "current-run.json",
        )

    def python_invocations(self) -> list[list[str]]:
        if not self.python_marker.exists():
            return []
        return [
            json.loads(line)
            for line in self.python_marker.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def write_main_state(
        self,
        *,
        next_interval_at_utc: str | None,
        worker_pid: int | None = None,
        worker_process_started_at_utc: str | None | object = _MISSING,
        last_started_at_utc: str | None = None,
        status: str = "IDLE",
    ) -> None:
        state = {
            "schema": "trading_mvp_listing_momentum_forward_automation_state_v1",
            "automation_id": "zolotyaylopata-listing-momentum-monitor",
            "cadence_policy_version": "adaptive_event_proximity_v1",
            "cadence_stage": "SEARCH",
            "cadence_seconds": 21600,
            "cadence_hours": 6,
            "cadence_reason": "fixture",
            "event_eta_utc": None,
            "official_confirmation": False,
            "exact_timestamp": False,
            "wake_interval_seconds": 300,
            "status": status,
            "pending_retry": False,
            "retry_count": 0,
            "attempt_count": 0,
            "next_interval_at_utc": next_interval_at_utc,
            "last_attempt_id": "fixture-attempt" if worker_pid else None,
            "last_started_at_utc": last_started_at_utc,
            "last_finished_at_utc": None,
            "worker_pid": worker_pid,
            "outcomes": {},
            "last_error": None,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        if worker_process_started_at_utc is not _MISSING:
            state["worker_process_started_at_utc"] = worker_process_started_at_utc
        self.main_state.parent.mkdir(parents=True, exist_ok=True)
        self.main_state.write_text(json.dumps(state), encoding="utf-8")

    def run(
        self,
        script: str,
        *extra: str,
        plan_ok: bool = True,
        gate_status: str = "READY_FOR_POSTPROCESS",
        gate_authoritative_status: str | None = None,
        gate_mode: str = "valid",
        plan_exit_code: int = 0,
        v2_child_exit: int = 0,
        expansion_child_exit: int = 0,
        main_handoff: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        extra_args = list(extra)
        if (
            script == MAIN_SCRIPT
            and "-VisibleWorker" in extra_args
            and "-ScheduledTick" in extra_args
            and main_handoff
        ):
            if not self.main_state.exists():
                self.write_main_state(next_interval_at_utc=None)
            handoff_state = json.loads(
                self.main_state.read_text(encoding="utf-8-sig")
            )
            handoff_state["status"] = "QUEUED_VISIBLE"
            handoff_state["worker_handoff_token_sha256"] = hashlib.sha256(
                self.MAIN_HANDOFF_TOKEN.encode("utf-8")
            ).hexdigest()
            handoff_state["worker_handoff_run_id"] = self.MAIN_HANDOFF_RUN_ID
            self.main_state.write_text(json.dumps(handoff_state), encoding="utf-8")
            extra_args.extend(
                [
                    "-WorkerHandoffToken",
                    self.MAIN_HANDOFF_TOKEN,
                    "-WorkerHandoffRunId",
                    self.MAIN_HANDOFF_RUN_ID,
                ]
            )
        env = os.environ.copy()
        env.update(
            {
                "PYTHON_EXE": sys.executable,
                "FAKE_PLAN_OK": "true" if plan_ok else "false",
                "FAKE_PLAN_EXIT_CODE": str(plan_exit_code),
                "FAKE_GATE_STATUS": gate_status,
                "FAKE_GATE_AUTHORITATIVE_STATUS": gate_authoritative_status or gate_status,
                "FAKE_GATE_MODE": gate_mode,
                "FAKE_PYTHON_MARKER": str(self.python_marker),
                "FAKE_CHILD_MARKER": str(self.child_marker),
                "FAKE_MAIN_STATE": str(self.main_state),
                "FAKE_MAIN_LAUNCH": str(
                    self.run_gates / "listing_momentum_forward_automation.launch.json"
                ),
                "FAKE_V2_CHILD_EXIT": str(v2_child_exit),
                "FAKE_EXPANSION_CHILD_EXIT": str(expansion_child_exit),
            }
        )
        command = [
            str(PWSH),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script(script)),
        ]
        if script == MAIN_SCRIPT:
            command.extend(
                [
                    "-V2PlanPath",
                    str(self.v2_plan),
                    "-ExpansionPlanPath",
                    str(self.expansion_plan),
                    "-StatePathOverride",
                    str(self.main_state),
                    "-LedgerPathOverride",
                    str(self.main_ledger),
                    "-SchedulerClaimPathOverride",
                    str(self.main_claim),
                ]
            )
        else:
            command.extend(
                [
                    "-PlanPath",
                    str(self.v2_plan if script == V2_SCRIPT else self.expansion_plan),
                ]
            )
        command.extend(extra_args)
        return subprocess.run(
            command,
            cwd=self.root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

    def install_recording_child_launchers(self) -> None:
        stub = """
param(
    [string]$PlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Json,
    [switch]$VisibleWorker,
    [switch]$ScheduledTick
)
if ($PreflightOnly) {
    [ordered]@{
        ok = $true
        reasons = @()
        plan_id = "fixture-child"
        plan_hash = ("b" * 64)
        plan_file_sha256 = ("c" * 64)
        gate_status = "READY_FOR_POSTPROCESS"
    } | ConvertTo-Json
    exit 0
}
if ($VisibleWorker) {
    $track = if ($PlanPath -like "*v2-plan.json") { "v2" } else { "expansion" }
    $mainState = Get-Content -Raw -LiteralPath $env:FAKE_MAIN_STATE | ConvertFrom-Json -DateKind String
    $mainLaunch = Get-Content -Raw -LiteralPath $env:FAKE_MAIN_LAUNCH | ConvertFrom-Json -DateKind String
    $mainProcessStarted = (Get-Process -Id ([int]$mainLaunch.visible_terminal_pid) -ErrorAction Stop).StartTime.ToUniversalTime()
    $identityMatches = $false
    if ($mainState.worker_process_started_at_utc) {
        try {
            $storedStart = [DateTimeOffset]::Parse([string]$mainState.worker_process_started_at_utc).ToUniversalTime()
            $identityMatches = [math]::Abs(($mainProcessStarted - $storedStart.UtcDateTime).TotalMilliseconds) -le 10
        } catch { $identityMatches = $false }
    }
    $row = [ordered]@{
        plan_path = $PlanPath
        visible_worker = [bool]$VisibleWorker
        scheduled_tick = [bool]$ScheduledTick
        worker_identity_matches = $identityMatches
    } | ConvertTo-Json -Compress
    Add-Content -LiteralPath $env:FAKE_CHILD_MARKER -Value $row -Encoding UTF8
    Write-Output ("fixture child progress: " + $track)
    [ordered]@{ track = $track; status = "fixture worker finished" } | ConvertTo-Json
    $exitCode = if ($track -eq "v2") { [int]$env:FAKE_V2_CHILD_EXIT } else { [int]$env:FAKE_EXPANSION_CHILD_EXIT }
    exit $exitCode
}
exit 1
""".lstrip()
        self.script(V2_SCRIPT).write_text(stub, encoding="utf-8")
        self.script(EXPANSION_SCRIPT).write_text(stub, encoding="utf-8")

    def inject_terminal_ledger_failure(self) -> None:
        path = self.script(MAIN_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = "function Append-Ledger($Payload) {\n"
        replacement = (
            marker
            + "    if ([string]$Payload.status -ne 'RUNNING') { throw 'fixture_terminal_ledger_failure' }\n"
        )
        if marker not in source:
            raise AssertionError("Append-Ledger marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_running_ledger_failure(self) -> None:
        path = self.script(MAIN_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = "function Append-Ledger($Payload) {\n"
        replacement = (
            marker
            + "    if ([string]$Payload.status -eq 'RUNNING') { throw 'fixture_running_ledger_failure' }\n"
        )
        if marker not in source:
            raise AssertionError("Append-Ledger marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_running_state_failure(self) -> None:
        path = self.script(MAIN_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = "function Set-State($State) {\n"
        replacement = (
            marker
            + "    if ([string]$State.status -eq 'RUNNING') { throw 'fixture_running_state_failure' }\n"
        )
        if marker not in source:
            raise AssertionError("Set-State marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_terminal_state_failure_once(self) -> None:
        path = self.script(MAIN_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = "function Set-State($State) {\n"
        failure_marker = self.root / "terminal-state-failure-fired.txt"
        failure_literal = "'" + str(failure_marker).replace("'", "''") + "'"
        replacement = (
            marker
            + f"    if ([string]$State.status -notin @('RUNNING','QUEUED_VISIBLE') -and -not (Test-Path -LiteralPath {failure_literal})) {{ Set-Content -LiteralPath {failure_literal} -Value 'fired' -Encoding UTF8; throw 'fixture_terminal_state_failure_once' }}\n"
        )
        if marker not in source:
            raise AssertionError("Set-State marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_outer_start_process_failure(self) -> None:
        path = self.script(MAIN_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = "        $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru\n"
        replacement = "        throw 'fixture_outer_start_process_failure'\n"
        if marker not in source:
            raise AssertionError("outer Start-Process marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_outer_start_barrier(
        self,
        *,
        process_id: int,
        barrier_path: Path,
        release_path: Path,
    ) -> None:
        path = self.script(MAIN_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = "        $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru\n"
        barrier_literal = "'" + str(barrier_path).replace("'", "''") + "'"
        release_literal = "'" + str(release_path).replace("'", "''") + "'"
        replacement = (
            f"        Add-Content -LiteralPath {barrier_literal} -Value 'entered' -Encoding UTF8\n"
            f"        while (-not (Test-Path -LiteralPath {release_literal})) {{ Start-Sleep -Milliseconds 20 }}\n"
            f"        $terminal = [pscustomobject]@{{ Id = {process_id} }}\n"
        )
        if marker not in source:
            raise AssertionError("outer Start-Process marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_expansion_worker_invocation_failure(self) -> None:
        path = self.script(EXPANSION_SCRIPT)
        source = path.read_text(encoding="utf-8")
        marker = next(
            (
                line + "\n"
                for line in source.splitlines()
                if line.lstrip().startswith("& $pythonExe $monitorPy --plan $PlanPath --tick")
            ),
            None,
        )
        replacement = "    throw 'fixture_expansion_worker_invocation_failure'\n"
        if marker is None or marker not in source:
            raise AssertionError("expansion worker invocation marker missing")
        path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def write_scheduler_claim(
        self,
        *,
        pid: int,
        owner_process_started_at_utc: str | None,
        run_id: str = "fixture-existing-scheduler",
    ) -> bytes:
        payload = {
            "schema": "trading_mvp_listing_momentum_forward_automation_claim_v1",
            "pid": pid,
            "run_id": run_id,
            "ownership_token": "e" * 32,
            "claimed_at_utc": datetime.now(timezone.utc).isoformat(),
            "automation_id": "zolotyaylopata-listing-momentum-monitor",
        }
        if owner_process_started_at_utc is not None:
            payload["owner_process_started_at_utc"] = owner_process_started_at_utc
        encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        self.main_claim.parent.mkdir(parents=True, exist_ok=True)
        self.main_claim.write_bytes(encoded)
        return encoded

    def write_global_claim(
        self,
        *,
        owner_pid: int,
        owner_process_started_at_utc: str | None,
    ) -> bytes:
        payload = {
            "schema": "trading_mvp_global_market_writer_claim_v1",
            "project": "trading_mvp",
            "status": "CLAIMED",
            "run_id": "fixture-orphan-writer",
            "owner_pid": owner_pid,
            "writer_pid": None,
            "terminal_pid": None,
            "owner_kind": "fixture",
            "ownership_token": "1" * 32,
            "plan_hash": "b" * 64,
            "output_namespace": str(self.root / "existing-output"),
            "claimed_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
        }
        if owner_process_started_at_utc is not None:
            payload["owner_process_started_at_utc"] = owner_process_started_at_utc
        encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        self.global_claim.parent.mkdir(parents=True, exist_ok=True)
        self.global_claim.write_bytes(encoded)
        return encoded

    def run_scheduler_claim_acquire_harness(
        self,
        *,
        mutate_during_recovery: bool = False,
        mutate_before_archive_move: bool = False,
        contend_with_transaction_lock: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        source = self.script(MAIN_SCRIPT).read_text(encoding="utf-8")
        start_marker = (
            "function Enter-SchedulerClaimTransaction"
            if "function Enter-SchedulerClaimTransaction" in source
            else (
                "function Get-SchedulerClaimSnapshot"
                if "function Get-SchedulerClaimSnapshot" in source
                else "function Acquire-SchedulerClaim"
            )
        )
        functions = source[
            source.index(start_marker) : source.index("function Invoke-TrackPreflight")
        ]
        harness = self.root / "scheduler-claim-acquire-harness.ps1"
        mutation = """
$beforeDoubleCheck = {
    $changed = Get-Content -Raw -LiteralPath $schedulerClaimPath | ConvertFrom-Json -DateKind String
    $changed.run_id = "changed-during-recovery"
    $changed.ownership_token = ("f" * 32)
    $changed | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $schedulerClaimPath -Encoding UTF8
}
""" if mutate_during_recovery else "$beforeDoubleCheck = $null\n"
        archive_move_mutation = """
$beforeArchiveMove = {
    [System.IO.File]::Delete($schedulerClaimPath)
    [ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_claim_v1"
        pid = $PID
        run_id = "replacement-live-claim"
        ownership_token = ("a" * 32)
        owner_process_started_at_utc = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString("o")
        claimed_at_utc = Get-UtcIso
        automation_id = "zolotyaylopata-listing-momentum-monitor"
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $schedulerClaimPath -Encoding UTF8
}
""" if mutate_before_archive_move else (
            """
$beforeArchiveMove = {
    $contender = $null
    try {
        $contender = [System.IO.File]::Open(
            ($schedulerClaimPath + ".transaction.lock"),
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        [System.IO.File]::Delete($schedulerClaimPath)
        [ordered]@{
            schema = "trading_mvp_listing_momentum_forward_automation_claim_v1"
            pid = $PID
            run_id = "transaction-contender-replacement"
            ownership_token = ("e" * 32)
            owner_process_started_at_utc = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString("o")
            claimed_at_utc = Get-UtcIso
            automation_id = "zolotyaylopata-listing-momentum-monitor"
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $schedulerClaimPath -Encoding UTF8
    } catch [System.IO.IOException] {
        $script:contenderBlocked = $true
    } finally {
        if ($null -ne $contender) { $contender.Dispose() }
    }
}
""" if contend_with_transaction_lock else "$beforeArchiveMove = $null\n"
        )
        harness.write_text(
            f"""
$ErrorActionPreference = "Stop"
$schedulerClaimPath = {json.dumps(str(self.main_claim))}
$schedulerClaimArchiveDir = {json.dumps(str(self.scheduler_claim_archive))}
$ledgerPath = {json.dumps(str(self.main_ledger))}
$script:contenderBlocked = $false
function Get-UtcIso {{ return (Get-Date).ToUniversalTime().ToString("o") }}
function Append-Ledger($Payload) {{
    ($Payload | ConvertTo-Json -Compress -Depth 30) |
        Add-Content -LiteralPath $ledgerPath -Encoding UTF8
}}
{functions}
{mutation}
{archive_move_mutation}
$claim = Acquire-SchedulerClaim -BeforeStaleClaimDoubleCheck $beforeDoubleCheck -BeforeStaleClaimArchiveMove $beforeArchiveMove
if ($null -ne $claim -and $claim.Stream) {{ $claim.Stream.Dispose() }}
[ordered]@{{
    acquired = $null -ne $claim
    claim_exists = Test-Path -LiteralPath $schedulerClaimPath
    archive_count = @((Get-ChildItem -LiteralPath $schedulerClaimArchiveDir -File -ErrorAction SilentlyContinue)).Count
    ledger_exists = Test-Path -LiteralPath $ledgerPath
    contender_blocked = $script:contenderBlocked
}} | ConvertTo-Json -Compress
""".lstrip(),
            encoding="utf-8",
        )
        return subprocess.run(
            [
                str(PWSH),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )

    def run_scheduler_claim_release_harness(
        self, mutation: str | None
    ) -> subprocess.CompletedProcess[str]:
        source = self.script(MAIN_SCRIPT).read_text(encoding="utf-8")
        start_marker = (
            "function Enter-SchedulerClaimTransaction"
            if "function Enter-SchedulerClaimTransaction" in source
            else (
                "function Get-SchedulerClaimSnapshot"
                if "function Get-SchedulerClaimSnapshot" in source
                else "function Acquire-SchedulerClaim"
            )
        )
        functions = source[
            source.index(start_marker) : source.index(
                "function Invoke-TrackPreflight"
            )
        ]
        harness = self.root / "scheduler-claim-release-harness.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = "Stop"
$schedulerClaimPath = {json.dumps(str(self.main_claim))}
$ledgerPath = {json.dumps(str(self.main_ledger))}
function Get-UtcIso {{ return (Get-Date).ToUniversalTime().ToString("o") }}
function Append-Ledger($Payload) {{
    ($Payload | ConvertTo-Json -Compress -Depth 20) |
        Add-Content -LiteralPath $ledgerPath -Encoding UTF8
}}
{functions}
$claim = Acquire-SchedulerClaim
if ($null -eq $claim) {{ throw "fixture failed to acquire claim" }}
$stream = if ($claim.PSObject.Properties.Name -contains "Stream") {{ $claim.Stream }} else {{ $claim }}
$stream.Dispose()
$payload = Get-Content -Raw -LiteralPath $schedulerClaimPath | ConvertFrom-Json -DateKind String
$defaults = [ordered]@{{
    ownership_token = ("a" * 32)
    run_id = "fixture-owned-run"
    pid = $PID
    owner_process_started_at_utc = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString("o")
}}
foreach ($field in $defaults.Keys) {{
    if (-not ($payload.PSObject.Properties.Name -contains $field)) {{
        $payload | Add-Member -NotePropertyName $field -NotePropertyValue $defaults[$field]
    }}
}}
$mutation = {json.dumps(mutation or "none")}
switch ($mutation) {{
    "ownership_token" {{ $payload.ownership_token = ("f" * 32) }}
    "run_id" {{ $payload.run_id = "substituted-run" }}
    "pid" {{ $payload.pid = 999999 }}
    "owner_process_started_at_utc" {{ $payload.owner_process_started_at_utc = "2000-01-01T00:00:00.0000000Z" }}
}}
$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $schedulerClaimPath -Encoding UTF8
Release-SchedulerClaim $claim
[ordered]@{{
    claim_exists = Test-Path -LiteralPath $schedulerClaimPath
    ledger_exists = Test-Path -LiteralPath $ledgerPath
}} | ConvertTo-Json -Compress
""".lstrip(),
            encoding="utf-8",
        )
        return subprocess.run(
            [
                str(PWSH),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )


@unittest.skipIf(PWSH is None, "PowerShell 7 is required")
class ListingMomentumVisibleLauncherGuardTests(unittest.TestCase):
    def fixture(self, temp_dir: str) -> ListingMomentumLauncherFixture:
        return ListingMomentumLauncherFixture(Path(temp_dir))

    def current_process_started_at_utc(self) -> str:
        result = subprocess.run(
            [
                str(PWSH),
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {os.getpid()}).StartTime.ToUniversalTime().ToString('o')",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=True,
        )
        return result.stdout.strip()

    def assert_no_production_artifacts(self, fixture: ListingMomentumLauncherFixture) -> None:
        created = [str(path) for path in fixture.production_artifacts() if path.exists()]
        self.assertEqual([], created)

    def test_v2_current_run_pointer_test_hook_writes_exact_payload_without_market_work(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            pointer_path = fixture.root / "transaction-fixture" / "current-run.json"
            payload_path = fixture.root / "transaction-fixture" / "payload.json"
            ready_path = fixture.root / "transaction-fixture" / "ready.marker"
            done_path = fixture.root / "transaction-fixture" / "done.marker"
            payload = {
                "schema": "active_run_pointer_v1",
                "project": "trading_mvp",
                "run_id": "transaction_writer_fixture",
                "status": "RUNNING",
                "process_ids": [os.getpid()],
            }
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(json.dumps(payload), encoding="utf-8")

            result = fixture.run(
                V2_SCRIPT,
                "-CurrentRunPointerTestOnly",
                "-CurrentRunPointerPathOverride",
                str(pointer_path),
                "-CurrentRunPointerPayloadPath",
                str(payload_path),
                "-CurrentRunPointerReadyPath",
                str(ready_path),
                "-CurrentRunPointerDonePath",
                str(done_path),
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(pointer_path.read_text(encoding="utf-8-sig")), payload
            )
            self.assertTrue(ready_path.is_file())
            self.assertTrue(done_path.is_file())
            self.assertEqual([], fixture.python_invocations())

    def test_v2_current_run_pointer_test_hook_refuses_canonical_pointer(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            pointer_path = fixture.agent_log / "current-run.json"
            payload_path = fixture.root / "transaction-fixture" / "payload.json"
            ready_path = fixture.root / "transaction-fixture" / "ready.marker"
            done_path = fixture.root / "transaction-fixture" / "done.marker"
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(
                json.dumps(
                    {
                        "schema": "active_run_pointer_v1",
                        "project": "trading_mvp",
                        "run_id": "must_not_write",
                        "status": "RUNNING",
                    }
                ),
                encoding="utf-8",
            )

            result = fixture.run(
                V2_SCRIPT,
                "-CurrentRunPointerTestOnly",
                "-CurrentRunPointerPathOverride",
                str(pointer_path),
                "-CurrentRunPointerPayloadPath",
                str(payload_path),
                "-CurrentRunPointerReadyPath",
                str(ready_path),
                "-CurrentRunPointerDonePath",
                str(done_path),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical current-run pointer", result.stderr)
            self.assertFalse(pointer_path.exists())
            self.assertFalse(ready_path.exists())
            self.assertFalse(done_path.exists())

    def test_direct_visible_workers_require_scheduled_tick_before_python_or_writes(self) -> None:
        for script in (MAIN_SCRIPT, V2_SCRIPT, EXPANSION_SCRIPT):
            with self.subTest(script=script), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)

                result = fixture.run(script, "-VisibleWorker", "-Json")

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("ScheduledTick", result.stdout + result.stderr)
                self.assertEqual([], fixture.python_invocations(), result.stdout + result.stderr)
                self.assert_no_production_artifacts(fixture)

    def test_main_direct_scheduled_worker_without_handoff_is_read_only_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
                main_handoff=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("handoff", (result.stdout + result.stderr).lower())
            self.assertEqual([], fixture.python_invocations())
            self.assertFalse(fixture.child_marker.exists())
            self.assert_no_production_artifacts(fixture)

    def test_every_direct_execution_path_requires_scheduled_tick_before_preflight_or_writes(self) -> None:
        for script in (MAIN_SCRIPT, V2_SCRIPT, EXPANSION_SCRIPT):
            with self.subTest(script=script), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)

                result = fixture.run(script, "-Json", plan_ok=False)

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("ScheduledTick", result.stdout + result.stderr)
                self.assertEqual([], fixture.python_invocations(), result.stdout + result.stderr)
                self.assertFalse(fixture.child_marker.exists(), result.stdout + result.stderr)
                self.assert_no_production_artifacts(fixture)

    def test_expansion_valid_plan_payload_with_nonzero_validator_exit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)

            result = fixture.run(
                EXPANSION_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
                plan_exit_code=23,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            invocations = fixture.python_invocations()
            self.assertTrue(invocations, result.stdout + result.stderr)
            self.assertTrue(all("--plan-check" in row for row in invocations), invocations)
            self.assertFalse(
                (fixture.agent_log / "current-run.json").exists(),
                result.stdout + result.stderr,
            )
            self.assertFalse(
                (fixture.run_gates / "listing_momentum_forward_expansion.launch.json").exists(),
                result.stdout + result.stderr,
            )
            self.assertFalse(fixture.global_claim.exists(), result.stdout + result.stderr)

    def test_expansion_worker_exception_terminalizes_running_launch_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.inject_expansion_worker_invocation_failure()

            result = fixture.run(
                EXPANSION_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            launch_path = (
                fixture.run_gates / "listing_momentum_forward_expansion.launch.json"
            )
            launch = json.loads(launch_path.read_text(encoding="utf-8-sig"))
            self.assertEqual("FAILED", launch["status"], launch)
            self.assertIsNotNone(launch["finished_at_utc"], launch)
            self.assertNotEqual(0, launch["tick_exit_code"], launch)
            self.assertIn("fixture_expansion_worker_invocation_failure", launch["error"])

    def test_spot_worker_mode_rejects_mixed_read_only_flags_before_python_or_writes(self) -> None:
        for script in (V2_SCRIPT, EXPANSION_SCRIPT):
            for read_only_flag in ("-PreflightOnly", "-Status"):
                with self.subTest(script=script, flag=read_only_flag), tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.fixture(temp_dir)

                    result = fixture.run(
                        script,
                        "-VisibleWorker",
                        read_only_flag,
                        "-Json",
                    )

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertIn("ScheduledTick", result.stdout + result.stderr)
                    self.assertEqual([], fixture.python_invocations(), result.stdout + result.stderr)
                    self.assert_no_production_artifacts(fixture)

    def test_main_scheduled_worker_fails_preflight_before_running_metadata_or_ticks(self) -> None:
        scenarios = (
            {"plan_ok": False, "gate_status": "READY_FOR_POSTPROCESS"},
            {"plan_ok": True, "gate_status": "RUNNING"},
        )
        for scenario in scenarios:
            with self.subTest(**scenario), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)

                result = fixture.run(
                    MAIN_SCRIPT,
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    **scenario,
                )

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
                self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                self.assertTrue(state["pending_retry"])
                ledger = json.loads(
                    fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()[-1]
                )
                self.assertEqual("RETRY_NEXT_INTERVAL", ledger["status"])
                self.assertFalse(ledger["preflight"]["ok"])
                self.assertFalse(fixture.main_claim.exists())
                self.assertFalse(
                    (fixture.run_gates / "listing_momentum_forward_automation.launch.json").exists()
                )
                self.assertFalse(
                    any("--tick" in args for args in fixture.python_invocations()),
                    result.stdout + result.stderr,
                )

    def test_authoritative_gate_must_be_ready_for_all_spot_execution_paths(self) -> None:
        scenarios = (
            {
                "gate_status": "REJECTED_INCOMPLETE",
                "gate_authoritative_status": "STOPPED_INCOMPLETE",
                "gate_mode": "valid",
            },
            {
                "gate_status": "READY_FOR_POSTPROCESS",
                "gate_authoritative_status": "READY_FOR_POSTPROCESS",
                "gate_mode": "missing_status",
            },
            {
                "gate_status": "READY_FOR_POSTPROCESS",
                "gate_authoritative_status": "READY_FOR_POSTPROCESS",
                "gate_mode": "invalid_json",
            },
            {
                "gate_status": "READY_FOR_POSTPROCESS",
                "gate_authoritative_status": "READY_FOR_POSTPROCESS",
                "gate_mode": "nonzero",
            },
        )
        for script in (MAIN_SCRIPT, V2_SCRIPT, EXPANSION_SCRIPT):
            for scenario in scenarios:
                with self.subTest(script=script, **scenario), tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.fixture(temp_dir)

                    result = fixture.run(
                        script,
                        "-VisibleWorker",
                        "-ScheduledTick",
                        "-Json",
                        **scenario,
                    )

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertFalse(fixture.child_marker.exists(), result.stdout + result.stderr)
                    self.assertFalse(
                        any("--tick" in args for args in fixture.python_invocations()),
                        result.stdout + result.stderr,
                    )
                    if script == MAIN_SCRIPT:
                        state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
                        self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                        self.assertTrue(state["pending_retry"])
                        ledger = json.loads(
                            fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()[-1]
                        )
                        self.assertEqual("RETRY_NEXT_INTERVAL", ledger["status"])
                        self.assertFalse(ledger["preflight"]["ok"])
                        self.assertFalse(fixture.main_claim.exists())
                    else:
                        self.assert_no_production_artifacts(fixture)

    def test_negative_main_preflight_preserves_stale_worker_and_scheduler_claim_evidence(self) -> None:
        scenarios = (
            {"plan_ok": False, "gate_status": "READY_FOR_POSTPROCESS"},
            {"plan_ok": True, "gate_status": "RUNNING"},
        )
        mismatched_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for scenario in scenarios:
            with self.subTest(**scenario), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.write_main_state(
                    next_interval_at_utc="invalid-next-interval",
                    worker_pid=os.getpid(),
                    worker_process_started_at_utc=mismatched_start,
                    last_started_at_utc=self.current_process_started_at_utc(),
                    status="RUNNING",
                )
                original_claim = fixture.write_scheduler_claim(
                    pid=999_999,
                    owner_process_started_at_utc=None,
                )
                fixture.main_ledger.write_bytes(b"fixture-seed\n")
                original_ledger = fixture.main_ledger.read_bytes()

                result = fixture.run(
                    MAIN_SCRIPT,
                    "-ScheduledTick",
                    "-Json",
                    **scenario,
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                updated_state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
                self.assertEqual(os.getpid(), updated_state["worker_pid"])
                self.assertEqual(mismatched_start, updated_state["worker_process_started_at_utc"])
                self.assertEqual("RETRY_NEXT_INTERVAL", updated_state["status"])
                self.assertTrue(updated_state["pending_retry"])
                self.assertNotEqual("invalid-next-interval", updated_state["next_interval_at_utc"])
                self.assertEqual(original_claim, fixture.main_claim.read_bytes())
                self.assertTrue(fixture.main_ledger.read_bytes().startswith(original_ledger))
                ledger_row = json.loads(
                    fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()[-1]
                )
                self.assertEqual("RETRY_NEXT_INTERVAL", ledger_row["status"])
                self.assertFalse(ledger_row["preflight"]["ok"])
                self.assertFalse(fixture.scheduler_claim_archive.exists())
                self.assertFalse(fixture.child_marker.exists(), result.stdout + result.stderr)
                self.assertFalse(
                    any("--tick" in args for args in fixture.python_invocations()),
                    result.stdout + result.stderr,
                )
                self.assertFalse(
                    (fixture.run_gates / "listing_momentum_forward_automation.launch.json").exists()
                )

    def test_v2_scheduled_worker_rechecks_plan_gate_and_claim_before_metadata_or_tick(self) -> None:
        scenarios = ("plan", "gate", "claim")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                if scenario == "claim":
                    claim = fixture.agent_log / "active-market-data-writer-claim.json"
                    claim.parent.mkdir(parents=True, exist_ok=True)
                    claim.write_text("{}", encoding="utf-8")

                result = fixture.run(
                    V2_SCRIPT,
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    plan_ok=scenario != "plan",
                    gate_status="RUNNING" if scenario == "gate" else "READY_FOR_POSTPROCESS",
                )

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(
                    (fixture.run_gates / "listing_momentum_forward_monitor.launch.json").exists()
                )
                self.assertFalse((fixture.agent_log / "current-run.json").exists())
                self.assertFalse(
                    any("--tick" in args for args in fixture.python_invocations()),
                    result.stdout + result.stderr,
                )

    def test_main_internal_track_handoff_passes_scheduled_tick(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()

            result = fixture.run(MAIN_SCRIPT, "-VisibleWorker", "-ScheduledTick", "-Json")

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.child_marker.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(2, len(rows), rows)
            self.assertTrue(all(row["visible_worker"] for row in rows), rows)
            self.assertTrue(all(row["scheduled_tick"] for row in rows), rows)
            self.assertTrue(all(row["worker_identity_matches"] for row in rows), rows)

    def test_main_visible_worker_displays_nonempty_handoff_cadence(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.write_main_state(next_interval_at_utc=None)
            state = json.loads(fixture.main_state.read_text(encoding="utf-8"))
            state.update(
                {
                    "cadence_stage": "CONFIRMED",
                    "cadence_seconds": 3600,
                    "cadence_hours": 1,
                    "cadence_reason": "official_event_confirmed_without_near_exact_time",
                    "official_confirmation": True,
                }
            )
            fixture.main_state.write_text(json.dumps(state), encoding="utf-8")

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            combined_output = result.stdout + result.stderr
            self.assertEqual(0, result.returncode, combined_output)
            self.assertIn(
                "cadence stage: CONFIRMED; actual interval: 3600 sec; scheduler wake: 300 sec",
                combined_output,
            )

    def test_main_combined_cadence_selects_smallest_ordered_track_interval(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.write_main_state(next_interval_at_utc=None)
            states = fixture.root / "states"
            states.mkdir(parents=True, exist_ok=True)
            (states / "fixture-v2.json").write_text(
                json.dumps(
                    {
                        "adaptive_cadence": {
                            "stage": "CANDIDATE",
                            "interval_sec": 10800,
                            "reason": "fixture_v2_candidate",
                            "event_eta_utc": None,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (states / "fixture-expansion.json").write_text(
                json.dumps(
                    {
                        "adaptive_cadence": {
                            "stage": "CONFIRMED",
                            "interval_sec": 3600,
                            "reason": "fixture_expansion_confirmed",
                            "event_eta_utc": None,
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            final_state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertEqual(final_state["cadence_stage"], "CONFIRMED")
            self.assertEqual(final_state["cadence_seconds"], 3600)
            self.assertEqual(
                final_state["cadence_reason"], "fixture_expansion_confirmed"
            )

    def test_main_track_outcomes_use_only_integer_exit_code_while_child_output_stays_visible(self) -> None:
        scenarios = (
            {
                "v2_child_exit": 0,
                "expansion_child_exit": 0,
                "expected_returncode": 0,
                "expected_status": "COMPLETE",
                "expected_v2": "COMPLETE",
                "expected_expansion": "COMPLETE",
                "expected_error": None,
            },
            {
                "v2_child_exit": 1,
                "expansion_child_exit": 0,
                "expected_returncode": 1,
                "expected_status": "PARTIAL_RETRY_NEXT_INTERVAL",
                "expected_v2": "FAILED_RETRY_NEXT_INTERVAL",
                "expected_expansion": "COMPLETE",
                "expected_error": "mexc_gate_v2_exit_1",
            },
        )
        for scenario in scenarios:
            with self.subTest(**scenario), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.install_recording_child_launchers()

                result = fixture.run(
                    MAIN_SCRIPT,
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    v2_child_exit=scenario["v2_child_exit"],
                    expansion_child_exit=scenario["expansion_child_exit"],
                )

                combined_output = result.stdout + result.stderr
                self.assertEqual(
                    scenario["expected_returncode"],
                    result.returncode,
                    combined_output,
                )
                self.assertIn("fixture child progress: v2", combined_output)
                self.assertIn("fixture child progress: expansion", combined_output)
                self.assertIn('"status": "fixture worker finished"', combined_output)
                state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
                self.assertEqual(scenario["expected_status"], state["status"])
                self.assertEqual(scenario["expected_v2"], state["outcomes"]["mexc_gate_v2"])
                self.assertEqual(
                    scenario["expected_expansion"],
                    state["outcomes"]["binance_bybit_okx_bitget_expansion"],
                )
                self.assertEqual(scenario["expected_error"], state["last_error"])

    def test_main_terminal_state_is_not_committed_before_terminal_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.inject_terminal_ledger_failure()

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertEqual("RUNNING", state["status"])
            self.assertIsNotNone(state["worker_pid"])
            launch = json.loads(
                (fixture.run_gates / "listing_momentum_forward_automation.launch.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            self.assertEqual("RUNNING", launch["status"])
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            self.assertEqual(["RUNNING"], [row["status"] for row in rows])

    def test_main_visible_worker_reuses_outer_handoff_attempt_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            self.assertEqual(
                [fixture.MAIN_HANDOFF_RUN_ID, fixture.MAIN_HANDOFF_RUN_ID],
                [row["attempt_id"] for row in rows],
                rows,
            )
            self.assertEqual(["RUNNING", "COMPLETE"], [row["status"] for row in rows])

    def test_main_startup_reconciles_existing_terminal_without_conflicting_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.inject_terminal_state_failure_once()

            first = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertNotEqual(0, first.returncode, first.stdout + first.stderr)
            first_rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            self.assertEqual(["RUNNING", "COMPLETE"], [row["status"] for row in first_rows])
            attempt_id = first_rows[0]["attempt_id"]
            fixture.inject_outer_start_process_failure()

            second = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

            self.assertNotEqual(0, second.returncode, second.stdout + second.stderr)
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            linked = [row for row in rows if row.get("attempt_id") == attempt_id]
            self.assertEqual(["RUNNING", "COMPLETE"], [row["status"] for row in linked], rows)

    def test_main_running_metadata_requires_durable_running_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.inject_running_ledger_failure()

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertEqual("QUEUED_VISIBLE", state["status"])
            self.assertIsNone(state["worker_pid"])
            self.assertFalse(
                (fixture.run_gates / "listing_momentum_forward_automation.launch.json").exists()
            )
            self.assertFalse(fixture.main_ledger.exists())
            self.assertFalse(fixture.child_marker.exists())

    def test_main_running_state_failure_leaves_running_ledger_without_false_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.inject_running_state_failure()

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            self.assertEqual(["RUNNING"], [row["status"] for row in rows])
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertEqual("QUEUED_VISIBLE", state["status"])
            self.assertIsNone(state["worker_pid"])
            self.assertFalse(
                (fixture.run_gates / "listing_momentum_forward_automation.launch.json").exists()
            )
            self.assertFalse(fixture.child_marker.exists())

    def test_each_outer_launcher_handoff_includes_scheduled_tick(self) -> None:
        v2_source = (ROOT / "tools" / V2_SCRIPT).read_text(encoding="utf-8")
        expansion_source = (ROOT / "tools" / EXPANSION_SCRIPT).read_text(encoding="utf-8")
        self.assertIn('"-VisibleWorker", "-ScheduledTick", "-PlanPath"', v2_source)
        self.assertIn("-VisibleWorker -ScheduledTick -PlanPath", expansion_source)

    def test_scheduler_claim_collision_preserves_existing_claim_and_launches_nothing(self) -> None:
        exact_start = self.current_process_started_at_utc()
        claims = {
            "live": json.dumps(
                {
                    "schema": "trading_mvp_listing_momentum_forward_automation_claim_v1",
                    "pid": os.getpid(),
                    "run_id": "existing-scheduler",
                    "ownership_token": "e" * 32,
                    "owner_process_started_at_utc": exact_start,
                    "claimed_at_utc": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            "corrupt": "{not-json",
        }
        for label, contents in claims.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.main_claim.parent.mkdir(parents=True, exist_ok=True)
                fixture.main_claim.write_text(contents, encoding="utf-8")
                original = fixture.main_claim.read_bytes()

                result = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(original, fixture.main_claim.read_bytes())
                self.assertFalse(
                    any("--tick" in args for args in fixture.python_invocations()),
                    result.stdout + result.stderr,
                )
                self.assertFalse(fixture.child_marker.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.main_state.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.main_ledger.exists(), result.stdout + result.stderr)

    def test_main_deferred_state_is_not_written_when_terminal_ledger_append_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.inject_terminal_ledger_failure()

            result = fixture.run(
                MAIN_SCRIPT,
                "-ScheduledTick",
                "-Json",
                plan_ok=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(fixture.main_state.exists(), result.stdout + result.stderr)
            self.assertFalse(fixture.main_ledger.exists(), result.stdout + result.stderr)

    def test_main_stale_worker_recovery_terminalizes_original_attempt_ledger_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.write_main_state(
                next_interval_at_utc=None,
                worker_pid=999_999,
                worker_process_started_at_utc=(
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                status="RUNNING",
            )
            fixture.write_scheduler_claim(pid=999_999, owner_process_started_at_utc=None)
            fixture.inject_outer_start_process_failure()

            result = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
            self.assertIsNone(state["worker_pid"])
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            recovered = [row for row in rows if row.get("attempt_id") == "fixture-attempt"]
            self.assertEqual(1, len(recovered), rows)
            self.assertEqual("RETRY_NEXT_INTERVAL", recovered[0]["status"])

    def test_main_stale_worker_state_is_unchanged_when_recovery_ledger_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.write_main_state(
                next_interval_at_utc=None,
                worker_pid=999_999,
                worker_process_started_at_utc=(
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                status="RUNNING",
            )
            original_state = fixture.main_state.read_bytes()
            fixture.inject_terminal_ledger_failure()

            result = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(original_state, fixture.main_state.read_bytes())
            self.assertFalse(fixture.main_ledger.exists())

    def test_main_outer_queue_is_durable_before_start_and_failure_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.inject_outer_start_process_failure()

            result = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            self.assertEqual("QUEUED_VISIBLE", rows[0]["status"], rows)
            self.assertEqual("RETRY_NEXT_INTERVAL", rows[-1]["status"], rows)

    def test_main_null_pid_queued_handoff_is_recovered_as_original_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.write_main_state(next_interval_at_utc=None, status="QUEUED_VISIBLE")
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            state["last_attempt_id"] = "orphan-queued-attempt"
            state["worker_handoff_issued_at_utc"] = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
            fixture.main_state.write_text(json.dumps(state), encoding="utf-8")
            fixture.write_scheduler_claim(pid=999_999, owner_process_started_at_utc=None)
            fixture.inject_outer_start_process_failure()

            result = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            recovered = [row for row in rows if row.get("attempt_id") == "orphan-queued-attempt"]
            self.assertEqual(1, len(recovered), rows)
            self.assertEqual("RETRY_NEXT_INTERVAL", recovered[0]["status"])

    def test_main_second_tick_cannot_recover_first_tick_queued_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            barrier = fixture.root / "main-start-barrier.txt"
            release = fixture.root / "main-start-release.txt"
            helper = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                fixture.inject_outer_start_barrier(
                    process_id=helper.pid,
                    barrier_path=barrier,
                    release_path=release,
                )
                with ThreadPoolExecutor(max_workers=1) as pool:
                    first_future = pool.submit(
                        fixture.run, MAIN_SCRIPT, "-ScheduledTick", "-Json"
                    )
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline and not barrier.exists():
                        time.sleep(0.02)
                    self.assertTrue(barrier.exists())
                    state_before = fixture.main_state.read_bytes()
                    ledger_before = fixture.main_ledger.read_bytes()

                    second = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

                    self.assertEqual(0, second.returncode, second.stdout + second.stderr)
                    self.assertEqual(state_before, fixture.main_state.read_bytes())
                    self.assertEqual(ledger_before, fixture.main_ledger.read_bytes())
                    release.write_text("release", encoding="utf-8")
                    first = first_future.result(timeout=15)
                self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            finally:
                if not release.exists():
                    release.write_text("release", encoding="utf-8")
                helper.terminate()
                helper.wait(timeout=10)

    def test_scheduler_claim_acquire_recovers_dead_or_reused_owner_then_retries_once(self) -> None:
        stale_cases = (
            ("dead", 999_999, None),
            (
                "reused",
                os.getpid(),
                (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            ),
        )
        for label, pid, process_start in stale_cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                original = fixture.write_scheduler_claim(
                    pid=pid,
                    owner_process_started_at_utc=process_start,
                )

                result = fixture.run_scheduler_claim_acquire_harness()

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertTrue(payload["acquired"], payload)
                self.assertTrue(fixture.main_claim.exists(), payload)
                self.assertNotEqual(original, fixture.main_claim.read_bytes())
                archives = list(fixture.scheduler_claim_archive.glob("*.json"))
                self.assertEqual(1, len(archives), archives)
                self.assertEqual(original, archives[0].read_bytes())
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                recovered = [row for row in rows if row.get("status") == "STALE_CLAIM_RECOVERED"]
                self.assertEqual(1, len(recovered), rows)
                self.assertEqual(
                    archives[0].resolve(),
                    Path(recovered[0]["archive_path"]).resolve(),
                )

    def test_scheduler_claim_recovery_race_restores_replacement_and_never_acquires(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.write_scheduler_claim(
                pid=999_999,
                owner_process_started_at_utc=None,
            )

            result = fixture.run_scheduler_claim_acquire_harness(
                mutate_before_archive_move=True
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["acquired"], payload)
            replacement = json.loads(
                fixture.main_claim.read_text(encoding="utf-8-sig")
            )
            self.assertEqual("replacement-live-claim", replacement["run_id"])
            self.assertEqual(0, payload["archive_count"], payload)
            ledger_rows = [
                json.loads(line.lstrip("\ufeff"))
                for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            self.assertEqual(
                "STALE_CLAIM_RECOVERY_RACE_BLOCKED",
                ledger_rows[-1]["status"],
            )

    def test_scheduler_claim_transaction_lock_blocks_recovery_aba_contender(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.write_scheduler_claim(
                pid=999_999,
                owner_process_started_at_utc=(
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
            )

            result = fixture.run_scheduler_claim_acquire_harness(
                contend_with_transaction_lock=True,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["contender_blocked"], payload)
            self.assertTrue(payload["acquired"], payload)
            self.assertTrue(payload["claim_exists"], payload)
            self.assertEqual(1, payload["archive_count"], payload)

    def test_scheduler_claim_acquire_preserves_live_corrupt_and_changed_claims(self) -> None:
        exact_start = self.current_process_started_at_utc()
        preserved_cases = (
            ("live", exact_start),
            ("legacy_live", None),
        )
        for label, process_start in preserved_cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                original = fixture.write_scheduler_claim(
                    pid=os.getpid(),
                    owner_process_started_at_utc=process_start,
                )

                result = fixture.run_scheduler_claim_acquire_harness()

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(json.loads(result.stdout)["acquired"])
                self.assertEqual(original, fixture.main_claim.read_bytes())
                self.assertFalse(fixture.scheduler_claim_archive.exists())

        with self.subTest(label="corrupt"), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            original = b"{not-json"
            fixture.main_claim.parent.mkdir(parents=True, exist_ok=True)
            fixture.main_claim.write_bytes(original)

            result = fixture.run_scheduler_claim_acquire_harness()

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["acquired"])
            self.assertEqual(original, fixture.main_claim.read_bytes())
            self.assertFalse(fixture.scheduler_claim_archive.exists())

        with self.subTest(label="changed"), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.write_scheduler_claim(
                pid=999_999,
                owner_process_started_at_utc=None,
            )

            result = fixture.run_scheduler_claim_acquire_harness(
                mutate_during_recovery=True
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["acquired"])
            changed = json.loads(fixture.main_claim.read_text(encoding="utf-8-sig"))
            self.assertEqual("changed-during-recovery", changed["run_id"])
            self.assertEqual("f" * 32, changed["ownership_token"])
            self.assertFalse(fixture.scheduler_claim_archive.exists())

    def test_scheduler_claim_release_removes_only_exact_owned_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()

            result = fixture.run_scheduler_claim_release_harness(None)

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(fixture.main_claim.exists(), result.stdout + result.stderr)
            self.assertFalse(fixture.main_ledger.exists(), result.stdout + result.stderr)

    def test_scheduler_claim_release_preserves_each_substituted_identity_with_retry_evidence(self) -> None:
        for mutation in (
            "ownership_token",
            "run_id",
            "pid",
            "owner_process_started_at_utc",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)

                result = fixture.run_scheduler_claim_release_harness(mutation)

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertTrue(fixture.main_claim.exists(), result.stdout + result.stderr)
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.main_ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                self.assertEqual(1, len(rows), rows)
                self.assertEqual("RETRY_NEXT_INTERVAL", rows[0]["status"])
                self.assertEqual("scheduler_claim_release_identity_mismatch", rows[0]["reason"])
                self.assertEqual(mutation, rows[0]["mismatched_fields"][0])

    def test_v2_legacy_expansion_claim_is_preserved_and_blocks_before_metadata_or_tick(self) -> None:
        claims = {
            "live": json.dumps(
                {
                    "schema": "legacy_expansion_claim_v1",
                    "pid": os.getpid(),
                    "claimed_at_utc": "2026-08-20T00:00:00Z",
                }
            ),
            "corrupt": "{not-json",
        }
        for label, contents in claims.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.legacy_expansion_claim.parent.mkdir(parents=True, exist_ok=True)
                fixture.legacy_expansion_claim.write_text(contents, encoding="utf-8")

                result = fixture.run(
                    V2_SCRIPT,
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                )

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("legacy_expansion_writer_claim_exists", result.stdout + result.stderr)
                self.assertEqual(
                    contents,
                    fixture.legacy_expansion_claim.read_text(encoding="utf-8"),
                )
                self.assertFalse(
                    (fixture.run_gates / "listing_momentum_forward_monitor.launch.json").exists()
                )
                self.assertFalse((fixture.agent_log / "current-run.json").exists())
                self.assertFalse(
                    any("--tick" in args for args in fixture.python_invocations()),
                    result.stdout + result.stderr,
                )

    def test_spot_preflight_recovers_stale_canonical_claim_before_worker_metadata(self) -> None:
        for script in (V2_SCRIPT, EXPANSION_SCRIPT):
            with self.subTest(script=script), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                original = fixture.write_global_claim(
                    owner_pid=999_999,
                    owner_process_started_at_utc=None,
                )

                result = fixture.run(
                    script,
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                )

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(fixture.global_claim.exists(), result.stdout + result.stderr)
                archives = list(fixture.global_claim_archive.glob("*.json"))
                self.assertEqual(1, len(archives), archives)
                self.assertEqual(original, archives[0].read_bytes())
                self.assertTrue(
                    any("--tick" in args for args in fixture.python_invocations()),
                    result.stdout + result.stderr,
                )

    def test_negative_plan_or_gate_preserves_stale_claim_before_recovery(self) -> None:
        scenarios = (
            {"plan_ok": False, "gate_status": "READY_FOR_POSTPROCESS"},
            {"plan_ok": True, "gate_status": "RUNNING"},
        )
        for script in (V2_SCRIPT, EXPANSION_SCRIPT):
            for scenario in scenarios:
                with self.subTest(script=script, **scenario), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                    fixture = self.fixture(temp_dir)
                    original = fixture.write_global_claim(
                        owner_pid=999_999,
                        owner_process_started_at_utc=None,
                    )

                    result = fixture.run(
                        script,
                        "-VisibleWorker",
                        "-ScheduledTick",
                        "-Json",
                        **scenario,
                    )

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(original, fixture.global_claim.read_bytes())
                    self.assertFalse(fixture.global_claim_archive.exists())
                    self.assertFalse(
                        any("--tick" in args for args in fixture.python_invocations()),
                        result.stdout + result.stderr,
                    )

    def test_spot_preflight_preserves_live_corrupt_or_changed_canonical_claim(self) -> None:
        exact_start = self.current_process_started_at_utc()
        cases = (
            ("live", None),
            ("corrupt", b"{not-json"),
            ("changed", None),
        )
        for script in (V2_SCRIPT, EXPANSION_SCRIPT):
            for label, raw in cases:
                with self.subTest(script=script, label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                    fixture = self.fixture(temp_dir)
                    if raw is None:
                        original = fixture.write_global_claim(
                            owner_pid=os.getpid(),
                            owner_process_started_at_utc=exact_start,
                        )
                    else:
                        fixture.global_claim.parent.mkdir(parents=True, exist_ok=True)
                        fixture.global_claim.write_bytes(raw)
                        original = raw
                    if label == "changed":
                        (fixture.src / "global_market_writer_claim.py").write_text(
                            """
import json
print(json.dumps({
    "schema": "trading_mvp_global_market_writer_claim_recovery_v1",
    "status": "BLOCKED",
    "reason": "claim_changed_during_recovery",
}))
""".lstrip(),
                            encoding="utf-8",
                        )

                    result = fixture.run(
                        script,
                        "-VisibleWorker",
                        "-ScheduledTick",
                        "-Json",
                    )

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(original, fixture.global_claim.read_bytes())
                    self.assertFalse(fixture.global_claim_archive.exists())
                    self.assertFalse(
                        any("--tick" in args for args in fixture.python_invocations()),
                        result.stdout + result.stderr,
                    )

    def test_spot_preflight_only_does_not_recover_stale_claim_without_scheduled_tick(self) -> None:
        for script in (MAIN_SCRIPT, V2_SCRIPT, EXPANSION_SCRIPT):
            with self.subTest(script=script), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                original = fixture.write_global_claim(
                    owner_pid=999_999,
                    owner_process_started_at_utc=None,
                )

                result = fixture.run(script, "-PreflightOnly", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(original, fixture.global_claim.read_bytes())
                self.assertFalse(fixture.global_claim_archive.exists())

    def test_main_status_and_not_due_preserve_legacy_state_bytes_and_mtime(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for mode in ("status", "not_due"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.write_main_state(next_interval_at_utc=future)
                state = json.loads(fixture.main_state.read_text(encoding="utf-8"))
                for field in (
                    "cadence_policy_version",
                    "cadence_stage",
                    "cadence_seconds",
                    "cadence_hours",
                    "cadence_reason",
                    "wake_interval_seconds",
                    "worker_process_started_at_utc",
                ):
                    state.pop(field, None)
                fixture.main_state.write_text(json.dumps(state), encoding="utf-8")
                before_bytes = fixture.main_state.read_bytes()
                before_mtime = fixture.main_state.stat().st_mtime_ns

                args = ("-Status", "-Json") if mode == "status" else ("-ScheduledTick", "-Json")
                result = fixture.run(MAIN_SCRIPT, *args)

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                if mode == "not_due":
                    self.assertIn("NOT_DUE", result.stdout + result.stderr)
                self.assertEqual(before_bytes, fixture.main_state.read_bytes())
                self.assertEqual(before_mtime, fixture.main_state.stat().st_mtime_ns)

    def test_main_status_compares_worker_pid_start_identity_without_writing(self) -> None:
        exact_start = self.current_process_started_at_utc()
        mismatch_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cases = (
            ("exact", exact_start, None, True),
            ("mismatch", mismatch_start, exact_start, False),
            ("fallback", _MISSING, exact_start, True),
            ("legacy_last_started_drift", _MISSING, mismatch_start, True),
            ("legacy_missing", _MISSING, None, True),
        )
        for label, worker_start, last_start, expected_alive in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.write_main_state(
                    next_interval_at_utc=None,
                    worker_pid=os.getpid(),
                    worker_process_started_at_utc=worker_start,
                    last_started_at_utc=last_start,
                    status="RUNNING",
                )
                before_bytes = fixture.main_state.read_bytes()
                before_mtime = fixture.main_state.stat().st_mtime_ns

                result = fixture.run(MAIN_SCRIPT, "-Status", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(expected_alive, payload["worker_alive"], payload)
                self.assertEqual(before_bytes, fixture.main_state.read_bytes())
                self.assertEqual(before_mtime, fixture.main_state.stat().st_mtime_ns)

    def test_main_due_path_recovers_reused_pid_but_exact_and_legacy_live_pid_block(self) -> None:
        exact_start = self.current_process_started_at_utc()
        mismatch_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            fixture = self.fixture(temp_dir)
            fixture.install_recording_child_launchers()
            fixture.write_main_state(
                next_interval_at_utc=None,
                worker_pid=os.getpid(),
                worker_process_started_at_utc=mismatch_start,
                last_started_at_utc=exact_start,
                status="RUNNING",
            )

            result = fixture.run(
                MAIN_SCRIPT,
                "-VisibleWorker",
                "-ScheduledTick",
                "-Json",
            )

            self.assertNotIn("ALREADY_RUNNING", result.stdout + result.stderr)
            state = json.loads(fixture.main_state.read_text(encoding="utf-8-sig"))
            self.assertIsNone(state["worker_pid"], state)
            self.assertIsNone(state["worker_process_started_at_utc"], state)

        for label, worker_start, last_start in (
            ("exact", exact_start, None),
            ("fallback", _MISSING, exact_start),
            ("legacy_last_started_drift", _MISSING, mismatch_start),
            ("legacy_missing", _MISSING, None),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir)
                fixture.write_main_state(
                    next_interval_at_utc=None,
                    worker_pid=os.getpid(),
                    worker_process_started_at_utc=worker_start,
                    last_started_at_utc=last_start,
                    status="RUNNING",
                )
                before = fixture.main_state.read_bytes()

                result = fixture.run(MAIN_SCRIPT, "-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("ALREADY_RUNNING", result.stdout + result.stderr)
                self.assertEqual(before, fixture.main_state.read_bytes())


if __name__ == "__main__":
    unittest.main()
