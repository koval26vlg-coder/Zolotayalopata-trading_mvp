from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh") or shutil.which("pwsh.exe")


LAUNCHERS = {
    "premarket": {
        "script": "start_premarket_perp_listing_automation_visible.ps1",
        "validator": "premarket_plan.py",
        "automation": "premarket_automation.py",
        "plan": "premarket-perp-listing-impulse-planonly-20260821-v2.json",
        "state": "premarket_perp_listing_automation_state.json",
        "ledger": "premarket_perp_listing_automation_attempts.jsonl",
        "state_schema": "trading_mvp_premarket_perp_listing_automation_state_v1",
        "automation_id": "zolotyaylopata-premarket-perp-listing-monitor",
    },
    "preipo": {
        "script": "start_preipo_perpetual_event_automation_visible.ps1",
        "validator": "preipo_plan.py",
        "automation": "preipo_automation.py",
        "plan": "preipo-perpetual-event-planonly-20260821-v2.json",
        "state": "preipo_perpetual_event_automation_state.json",
        "ledger": "preipo_perpetual_event_automation_attempts.jsonl",
        "state_schema": "trading_mvp_preipo_perpetual_event_automation_state_v1",
        "automation_id": "zolotyaylopata-preipo-perpetual-event-monitor",
    },
}

_MISSING = object()


class LauncherFixture:
    HANDOFF_TOKEN = "2" * 32
    def __init__(self, root: Path, kind: str) -> None:
        self.root = root
        self.kind = kind
        self.config = LAUNCHERS[kind]
        self.tools = root / "tools"
        self.src = root / "trading_mvp" / "src"
        self.plans = root / "docs" / "plans"
        self.run_gates = root / "docs" / "agent-log" / "run-gates"
        self.claim = root / "docs" / "agent-log" / "active-market-data-writer-claim.json"
        self.legacy_expansion_claim = (
            root / "docs" / "agent-log" / "active-market-data-writer-expansion-claim.json"
        )
        self.archive = root / "docs" / "agent-log" / "global-writer-claim-archive"
        self.marker = root / "python-worker-ran.txt"
        self.script = self.tools / self.config["script"]
        self.plan = self.plans / self.config["plan"]
        self.state = self.run_gates / self.config["state"]
        self.ledger = self.run_gates / self.config["ledger"]

        self.tools.mkdir(parents=True)
        self.src.mkdir(parents=True)
        self.plans.mkdir(parents=True)
        self.run_gates.mkdir(parents=True)
        shutil.copy2(ROOT / "tools" / self.config["script"], self.script)
        self.plan.write_text("{}\n", encoding="utf-8")
        (self.src / self.config["validator"]).write_text(
            """
import json
import os
import sys

ok = os.environ.get("FAKE_PLAN_OK", "true").lower() == "true"
print(json.dumps({
    "ok": ok,
    "status": "PLAN_OK" if ok else "PLAN_INVALID",
    "reasons": [] if ok else ["fixture_plan_rejected"],
    "plan_id": "fixture-plan",
    "plan_hash": "a" * 64,
}))
raise SystemExit(int(os.environ.get("FAKE_PLAN_EXIT_CODE", "0")))
""".lstrip(),
            encoding="utf-8",
        )
        (self.src / self.config["automation"]).write_text(
            """
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psutil

parent = psutil.Process(os.getppid())
state = json.loads(Path(os.environ["FAKE_STATE_PATH"]).read_text(encoding="utf-8-sig"))
Path(os.environ["FAKE_AUTOMATION_MARKER"]).write_text(
    json.dumps({
        "parent_pid": parent.pid,
        "parent_started_at_utc": datetime.fromtimestamp(
            parent.create_time(), timezone.utc
        ).isoformat(),
        "state": state,
    }),
    encoding="utf-8",
)
if os.environ.get("FAKE_SUBSTITUTE_CLAIM_BEFORE_EXIT", "false").lower() == "true":
    claim_path = Path(os.environ["FAKE_CLAIM_PATH"])
    claim = json.loads(claim_path.read_text(encoding="utf-8-sig"))
    claim["plan_hash"] = "f" * 64
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
print("fixture worker complete")
""".lstrip(),
            encoding="utf-8",
        )
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
        shutil.copy2(
            ROOT / "trading_mvp" / "src" / "global_market_writer_claim.py",
            self.src / "global_market_writer_claim.py",
        )

    def inject_ledger_failure_for_status(self, status: str) -> None:
        source = self.script.read_text(encoding="utf-8")
        marker = "function Append-Ledger($Payload) {\n"
        replacement = (
            marker
            + f"    if ([string]$Payload.status -eq '{status}') {{ throw 'fixture_{status.lower()}_ledger_failure' }}\n"
        )
        if marker not in source:
            raise AssertionError("Append-Ledger marker missing")
        self.script.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_outer_start_process_failure(self) -> None:
        source = self.script.read_text(encoding="utf-8")
        marker = "    $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru\n"
        replacement = "    throw 'fixture_outer_start_process_failure'\n"
        if marker not in source:
            raise AssertionError("outer Start-Process marker missing")
        self.script.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_outer_start_process_result(self, process_id: int) -> None:
        source = self.script.read_text(encoding="utf-8")
        marker = "    $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru\n"
        replacement = f"    $terminal = [pscustomobject]@{{ Id = {process_id} }}\n"
        if marker not in source:
            raise AssertionError("outer Start-Process marker missing")
        self.script.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_self_owned_worker_state_before_preflight_result(self) -> None:
        source = self.script.read_text(encoding="utf-8")
        marker = "if (-not $preflight.ok) {\n"
        replacement = (
            "# Fixture: reproduce an outer launcher that already attached this visible worker.\n"
            "$state.worker_pid = $PID\n"
            "$state.worker_process_started_at_utc = Get-ProcessStartedAtUtc -ProcessId $PID\n"
            "Set-State $state\n"
            + marker
        )
        if marker not in source:
            raise AssertionError("negative preflight marker missing")
        self.script.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def inject_outer_start_barrier(
        self,
        *,
        process_id: int,
        barrier_path: Path,
        release_path: Path,
    ) -> None:
        source = self.script.read_text(encoding="utf-8")
        marker = "    $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru\n"
        barrier_literal = "'" + str(barrier_path).replace("'", "''") + "'"
        release_literal = "'" + str(release_path).replace("'", "''") + "'"
        replacement = (
            f"    Add-Content -LiteralPath {barrier_literal} -Value 'entered' -Encoding UTF8\n"
            f"    while (-not (Test-Path -LiteralPath {release_literal})) {{ Start-Sleep -Milliseconds 20 }}\n"
            f"    $terminal = [pscustomobject]@{{ Id = {process_id} }}\n"
        )
        if marker not in source:
            raise AssertionError("outer Start-Process marker missing")
        self.script.write_text(source.replace(marker, replacement, 1), encoding="utf-8")

    def write_state(
        self,
        *,
        next_interval_at_utc: str | None,
        worker_pid: int | None = None,
        worker_process_started_at_utc: str | None | object = _MISSING,
        last_started_at_utc: str | None = None,
        status: str = "IDLE",
    ) -> None:
        state = {
            "schema": self.config["state_schema"],
            "automation_id": self.config["automation_id"],
            "cadence_policy_version": "adaptive_event_proximity_v1",
            "cadence_stage": "SEARCH",
            "cadence_seconds": 21600,
            "cadence_reason": "fixture",
            "event_eta_utc": None,
            "official_confirmation": False,
            "exact_timestamp": False,
            "wake_interval_seconds": 300,
            "schedule_interval_seconds": 21600,
            "capture_duration_seconds": 300,
            "status": status,
            "pending_retry": False,
            "retry_count": 0,
            "attempt_count": 0,
            "next_interval_at_utc": next_interval_at_utc,
            "last_attempt_id": None,
            "last_started_at_utc": last_started_at_utc,
            "last_finished_at_utc": None,
            "worker_pid": worker_pid,
            "outcomes": {},
            "accrual": {
                "contracts_seen": 0,
                "events_written": 0,
                "complete_events": 0,
                "official_events": 0,
                "proxy_events": 0,
            },
            "last_error": None,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        if worker_process_started_at_utc is not _MISSING:
            state["worker_process_started_at_utc"] = worker_process_started_at_utc
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def write_claim(
        self,
        *,
        owner_pid: int,
        claimed_at_utc: str | None = None,
        owner_process_started_at_utc: str | None = None,
        overrides: dict[str, object] | None = None,
        remove_fields: tuple[str, ...] = (),
    ) -> bytes:
        payload = {
            "schema": "trading_mvp_global_market_writer_claim_v1",
            "project": "trading_mvp",
            "status": "CLAIMED",
            "run_id": "fixture-existing-writer",
            "owner_pid": owner_pid,
            "writer_pid": None,
            "terminal_pid": None,
            "owner_kind": "fixture",
            "ownership_token": "1" * 32,
            "plan_hash": "b" * 64,
            "output_namespace": str(self.root / "existing-output"),
            "claimed_at_utc": claimed_at_utc
            or (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "research_only": True,
            "live_orders": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
        }
        if owner_process_started_at_utc is not None:
            payload["owner_process_started_at_utc"] = owner_process_started_at_utc
        if overrides:
            payload.update(overrides)
        for field in remove_fields:
            payload.pop(field, None)
        encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        self.claim.parent.mkdir(parents=True, exist_ok=True)
        self.claim.write_bytes(encoded)
        return encoded

    def run(
        self,
        *extra: str,
        plan_ok: bool = True,
        gate_status: str = "READY_FOR_POSTPROCESS",
        gate_authoritative_status: str | None = None,
        gate_mode: str = "valid",
        plan_exit_code: int = 0,
        substitute_claim_before_exit: bool = False,
        worker_handoff: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        extra_args = list(extra)
        if (
            "-VisibleWorker" in extra_args
            and "-ScheduledTick" in extra_args
            and worker_handoff
        ):
            if not self.state.exists():
                self.write_state(next_interval_at_utc=None)
            handoff_state = json.loads(self.state.read_text(encoding="utf-8-sig"))
            handoff_state["status"] = "QUEUED_VISIBLE"
            handoff_state["worker_handoff_token_sha256"] = hashlib.sha256(
                self.HANDOFF_TOKEN.encode("utf-8")
            ).hexdigest()
            handoff_state["worker_handoff_run_id"] = f"fixture-{self.kind}-handoff"
            handoff_state["worker_handoff_plan_hash"] = "a" * 64
            handoff_state["worker_handoff_issued_at_utc"] = datetime.now(
                timezone.utc
            ).isoformat()
            self.state.write_text(json.dumps(handoff_state), encoding="utf-8")
            extra_args.extend(
                [
                    "-WorkerHandoffToken",
                    self.HANDOFF_TOKEN,
                    "-WorkerHandoffRunId",
                    f"fixture-{self.kind}-handoff",
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
                "FAKE_AUTOMATION_MARKER": str(self.marker),
                "FAKE_STATE_PATH": str(self.state),
                "FAKE_CLAIM_PATH": str(self.claim),
                "FAKE_SUBSTITUTE_CLAIM_BEFORE_EXIT": (
                    "true" if substitute_claim_before_exit else "false"
                ),
            }
        )
        return subprocess.run(
            [
                str(PWSH),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
                "-PlanPath",
                str(self.plan),
                *extra_args,
            ],
            cwd=self.root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

    def run_release_claim_harness(
        self,
        *,
        fail_archive_rewrite: bool = False,
        substitute_plan_hash: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        source = self.script.read_text(encoding="utf-8")
        release_function = source[
            source.index("function Release-Claim") : source.index(
                "function Invoke-PlanPreflight"
            )
        ]
        harness = self.root / f"{self.kind}-release-claim-harness.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = "Stop"
$claimPath = {json.dumps(str(self.claim))}
$claimArchiveDir = {json.dumps(str(self.archive))}
$claimManagerPy = {json.dumps(str(self.src / "global_market_writer_claim.py"))}
$ledgerPath = {json.dumps(str(self.ledger))}
$automationId = {json.dumps(self.config["automation_id"])}
$failArchiveRewrite = ${str(fail_archive_rewrite).lower()}
function Resolve-PythonExecutable {{ return {json.dumps(sys.executable)} }}
function Get-UtcIso {{ return (Get-Date).ToUniversalTime().ToString("o") }}
function Append-Ledger($Payload) {{
    ($Payload | ConvertTo-Json -Compress -Depth 30) |
        Add-Content -LiteralPath $ledgerPath -Encoding UTF8
}}
function Read-JsonFile([string]$Path) {{
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -DateKind String
}}
function Write-FixtureJson([string]$Path, $Payload) {{
    if ($failArchiveRewrite -and [System.IO.Path]::GetFullPath($Path).StartsWith([System.IO.Path]::GetFullPath($claimArchiveDir))) {{
        throw "fixture_post_move_archive_write_failure"
    }}
    $Payload | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding UTF8
}}
function Write-JsonFile([string]$Path, $Payload) {{ Write-FixtureJson -Path $Path -Payload $Payload }}
function Write-JsonAtomic([string]$Path, $Payload) {{ Write-FixtureJson -Path $Path -Payload $Payload }}
{release_function}
$owned = [ordered]@{{
    schema = "trading_mvp_global_market_writer_claim_v1"
    project = "trading_mvp"
    status = "CLAIMED"
    run_id = "fixture-owned-release"
    owner_pid = $PID
    writer_pid = $PID
    terminal_pid = $PID
    owner_kind = "fixture"
    ownership_token = ("a" * 32)
    plan_hash = ("b" * 64)
    claimed_at_utc = Get-UtcIso
    owner_process_started_at_utc = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToString("o")
}}
$claimObject = [pscustomobject]$owned
$owned | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $claimPath -Encoding UTF8
if (${str(substitute_plan_hash).lower()}) {{
    $substitute = Get-Content -Raw -LiteralPath $claimPath | ConvertFrom-Json -DateKind String
    $substitute.plan_hash = ("f" * 64)
    $substitute | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $claimPath -Encoding UTF8
}}
$releaseSucceeded = Release-Claim -Claim $claimObject -FinalStatus "COMPLETE"
$reacquired = $false
if (-not (Test-Path -LiteralPath $claimPath)) {{
    $stream = [System.IO.File]::Open($claimPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $stream.Dispose()
    $reacquired = $true
}}
[ordered]@{{
    active_exists = Test-Path -LiteralPath $claimPath
    reacquired = $reacquired
    archive_count = @((Get-ChildItem -LiteralPath $claimArchiveDir -File -ErrorAction SilentlyContinue)).Count
    release_succeeded = [bool]$releaseSucceeded
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )


@unittest.skipIf(PWSH is None, "PowerShell 7 is required")
class DerivativeVisibleLauncherGuardTests(unittest.TestCase):
    def fixture(self, temp_dir: str, kind: str) -> LauncherFixture:
        return LauncherFixture(Path(temp_dir) / kind, kind)

    def test_valid_looking_plan_json_with_nonzero_validator_exit_fails_closed(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    plan_exit_code=17,
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                self.assertTrue(state["pending_retry"])

    def test_direct_derivative_worker_without_parent_handoff_is_read_only_blocked(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    worker_handoff=False,
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("handoff", (result.stdout + result.stderr).lower())
                self.assertFalse(fixture.marker.exists())
                self.assertFalse(fixture.state.exists())
                self.assertFalse(fixture.claim.exists())
                self.assertFalse(fixture.ledger.exists())

    def test_claim_release_failure_overrides_worker_success_with_durable_retry(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    substitute_claim_before_exit=True,
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                self.assertTrue(state["pending_retry"])
                self.assertIn("claim_release", state["last_error"])
                active = json.loads(fixture.claim.read_text(encoding="utf-8-sig"))
                self.assertEqual("f" * 64, active["plan_hash"])
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                self.assertTrue(
                    any(row.get("status") == "CLAIM_RELEASE_FAILED" for row in rows),
                    rows,
                )
                self.assertEqual("RETRY_NEXT_INTERVAL", rows[-1]["status"])

    def test_retry_state_is_not_committed_before_retry_ledger(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.inject_ledger_failure_for_status("RETRY_NEXT_INTERVAL")

                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    plan_ok=False,
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertEqual("QUEUED_VISIBLE", state["status"])
                self.assertIsNone(state["worker_pid"])
                self.assertFalse(fixture.ledger.exists())
                self.assertFalse(fixture.claim.exists())

    def test_running_ledger_failure_is_retried_and_releases_owned_claim(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.inject_ledger_failure_for_status("RUNNING")

                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                self.assertTrue(state["pending_retry"])
                self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                self.assertEqual(["RETRY_NEXT_INTERVAL", "CLAIM_RELEASED"], [row["status"] for row in rows])

    def test_outer_queue_is_durable_before_start_and_launch_failure_is_nonzero(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.inject_outer_start_process_failure()

                result = fixture.run("-ScheduledTick", "-Json")

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                self.assertEqual("QUEUED_VISIBLE", rows[0]["status"], rows)
                self.assertEqual("RETRY_NEXT_INTERVAL", rows[-1]["status"], rows)

    def test_outer_persists_live_visible_child_identity_and_duplicate_tick_is_read_only(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                helper = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    fixture = self.fixture(temp_dir, kind)
                    fixture.inject_outer_start_process_result(helper.pid)

                    first = fixture.run("-ScheduledTick", "-Json")

                    self.assertEqual(0, first.returncode, first.stdout + first.stderr)
                    state_before = fixture.state.read_bytes()
                    ledger_before = fixture.ledger.read_bytes()
                    state = json.loads(state_before.decode("utf-8-sig"))
                    self.assertEqual("QUEUED_VISIBLE", state["status"])
                    self.assertEqual(helper.pid, state["worker_pid"])
                    self.assertTrue(state["worker_process_started_at_utc"])

                    second = fixture.run("-ScheduledTick", "-Json")

                    self.assertEqual(0, second.returncode, second.stdout + second.stderr)
                    self.assertIn("ALREADY_RUNNING", second.stdout + second.stderr)
                    self.assertEqual(state_before, fixture.state.read_bytes())
                    self.assertEqual(ledger_before, fixture.ledger.read_bytes())
                finally:
                    helper.terminate()
                    helper.wait(timeout=10)

    def test_outer_launched_visible_child_consumes_its_owned_handoff(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run("-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and not fixture.marker.exists():
                    time.sleep(0.05)
                self.assertTrue(fixture.marker.exists(), result.stdout + result.stderr)
                marker = json.loads(fixture.marker.read_text(encoding="utf-8-sig"))
                visible_terminal_pid = json.loads(result.stdout)["visible_terminal_pid"]
                self.assertEqual(visible_terminal_pid, marker["parent_pid"])
                try:
                    psutil.Process(visible_terminal_pid).wait(timeout=10)
                except psutil.NoSuchProcess:
                    pass

    def test_concurrent_outer_tick_is_blocked_during_queue_to_child_attach(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                barrier = fixture.root / "outer-start-barrier.txt"
                release = fixture.root / "outer-start-release.txt"
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
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        first_future = pool.submit(fixture.run, "-ScheduledTick", "-Json")
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline and not barrier.exists():
                            time.sleep(0.02)
                        self.assertTrue(barrier.exists())
                        state_before = fixture.state.read_bytes()
                        ledger_before = fixture.ledger.read_bytes()

                        second_future = pool.submit(fixture.run, "-ScheduledTick", "-Json")
                        contender_deadline = time.monotonic() + 3
                        while time.monotonic() < contender_deadline and not second_future.done():
                            entered = barrier.read_text(encoding="utf-8-sig").splitlines()
                            if len(entered) >= 2:
                                break
                            time.sleep(0.02)
                        state_during = fixture.state.read_bytes()
                        ledger_during = fixture.ledger.read_bytes()
                        release.write_text("release", encoding="utf-8")
                        second = second_future.result(timeout=15)
                        first = first_future.result(timeout=15)
                        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
                        self.assertIn("ALREADY_RUNNING", second.stdout + second.stderr)
                        self.assertEqual(state_before, state_during)
                        self.assertEqual(ledger_before, ledger_during)
                    self.assertEqual(0, first.returncode, first.stdout + first.stderr)
                    self.assertEqual(
                        1,
                        len(barrier.read_text(encoding="utf-8-sig").splitlines()),
                    )
                finally:
                    if not release.exists():
                        release.write_text("release", encoding="utf-8")
                    helper.terminate()
                    helper.wait(timeout=10)

    def test_stale_worker_recovery_terminalizes_original_attempt_ledger_first(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_state(
                    next_interval_at_utc=None,
                    worker_pid=999_999,
                    worker_process_started_at_utc=(
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                    status="RUNNING",
                )
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                state["last_attempt_id"] = f"{kind}-orphan-running"
                fixture.state.write_text(json.dumps(state), encoding="utf-8")
                fixture.write_claim(
                    owner_pid=os.getpid(),
                    owner_process_started_at_utc=self.current_process_started_at_utc(),
                )

                result = fixture.run("-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                self.assertEqual(
                    [f"{kind}-orphan-running"],
                    [row["attempt_id"] for row in rows],
                    rows,
                )
                self.assertEqual("RETRY_NEXT_INTERVAL", rows[0]["status"])
                updated = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertIsNone(updated["worker_pid"])

    def test_stale_worker_state_is_unchanged_when_recovery_ledger_fails(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_state(
                    next_interval_at_utc=None,
                    worker_pid=999_999,
                    worker_process_started_at_utc=(
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                    status="RUNNING",
                )
                original_state = fixture.state.read_bytes()
                fixture.inject_ledger_failure_for_status("RETRY_NEXT_INTERVAL")

                result = fixture.run("-ScheduledTick", "-Json")

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(original_state, fixture.state.read_bytes())
                self.assertFalse(fixture.ledger.exists())

    def test_null_pid_queued_handoff_is_recovered_as_original_attempt(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_state(next_interval_at_utc=None, status="QUEUED_VISIBLE")
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                state["last_attempt_id"] = f"{kind}-orphan-queued"
                state["worker_handoff_issued_at_utc"] = (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat()
                fixture.state.write_text(json.dumps(state), encoding="utf-8")
                fixture.write_claim(
                    owner_pid=os.getpid(),
                    owner_process_started_at_utc=self.current_process_started_at_utc(),
                )

                result = fixture.run("-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                rows = [
                    json.loads(line.lstrip("\ufeff"))
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                self.assertEqual(
                    [f"{kind}-orphan-queued"],
                    [row["attempt_id"] for row in rows],
                    rows,
                )
                self.assertEqual("RETRY_NEXT_INTERVAL", rows[0]["status"])

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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=True,
        )
        return result.stdout.strip()

    def test_visible_workers_reject_negative_plan_before_running_python(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json", plan_ok=False)

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                self.assertIn("fixture_plan_rejected", result.stdout + result.stderr)

    def test_self_owned_visible_worker_retry_clears_terminal_process_identity(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.inject_self_owned_worker_state_before_preflight_result()

                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    plan_ok=False,
                )

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertEqual("RETRY_NEXT_INTERVAL", state["status"], state)
                self.assertTrue(state["pending_retry"], state)
                self.assertIsNone(state["worker_pid"], state)
                self.assertIsNone(state["worker_process_started_at_utc"], state)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)

    def test_visible_workers_reject_negative_global_gate_before_running_python(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                result = fixture.run(
                    "-VisibleWorker",
                    "-ScheduledTick",
                    "-Json",
                    gate_status="RUNNING",
                )

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                self.assertIn("active_run_gate_RUNNING", result.stdout + result.stderr)

    def test_negative_preflight_preserves_stale_worker_and_claim_evidence(self) -> None:
        scenarios = (
            {"plan_ok": False, "gate_status": "READY_FOR_POSTPROCESS"},
            {"plan_ok": True, "gate_status": "RUNNING"},
        )
        mismatched_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        exact_start = self.current_process_started_at_utc()
        for kind in LAUNCHERS:
            for scenario in scenarios:
                with self.subTest(kind=kind, **scenario), tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.fixture(temp_dir, kind)
                    fixture.write_state(
                        next_interval_at_utc="invalid-next-interval",
                        worker_pid=os.getpid(),
                        worker_process_started_at_utc=mismatched_start,
                        last_started_at_utc=exact_start,
                        status="RUNNING",
                    )
                    original_state = fixture.state.read_bytes()
                    original_claim = fixture.write_claim(owner_pid=999_999)
                    fixture.ledger.write_bytes(b"fixture-seed\n")
                    original_ledger = fixture.ledger.read_bytes()

                    result = fixture.run(
                        "-ScheduledTick",
                        "-Json",
                        **scenario,
                    )

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    updated_state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                    self.assertEqual(os.getpid(), updated_state["worker_pid"])
                    self.assertEqual(mismatched_start, updated_state["worker_process_started_at_utc"])
                    self.assertEqual("RETRY_NEXT_INTERVAL", updated_state["status"])
                    self.assertTrue(updated_state["pending_retry"])
                    self.assertNotEqual("invalid-next-interval", updated_state["next_interval_at_utc"])
                    self.assertEqual(original_claim, fixture.claim.read_bytes())
                    self.assertTrue(fixture.ledger.read_bytes().startswith(original_ledger))
                    ledger_row = json.loads(
                        fixture.ledger.read_text(encoding="utf-8-sig").splitlines()[-1]
                    )
                    self.assertEqual("RETRY_NEXT_INTERVAL", ledger_row["status"])
                    self.assertFalse(ledger_row["preflight"]["ok"])
                    self.assertFalse(fixture.archive.exists())
                    self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                    self.assertFalse(
                        list(fixture.run_gates.glob("*.launch.json")),
                        result.stdout + result.stderr,
                    )

    def test_authoritative_gate_must_be_ready_before_any_worker_or_write(self) -> None:
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
        for kind in LAUNCHERS:
            for scenario in scenarios:
                with self.subTest(kind=kind, **scenario), tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.fixture(temp_dir, kind)

                    result = fixture.run(
                        "-VisibleWorker",
                        "-ScheduledTick",
                        "-Json",
                        **scenario,
                    )

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                    self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                    state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                    self.assertEqual("RETRY_NEXT_INTERVAL", state["status"])
                    self.assertTrue(state["pending_retry"])
                    ledger = json.loads(
                        fixture.ledger.read_text(encoding="utf-8-sig").splitlines()[-1]
                    )
                    self.assertEqual("RETRY_NEXT_INTERVAL", ledger["status"])
                    self.assertFalse(ledger["preflight"]["ok"])
                    self.assertFalse(fixture.archive.exists(), result.stdout + result.stderr)

    def test_corrupt_canonical_claim_is_preserved_and_never_recovered(self) -> None:
        cases = (
            ("schema", {"schema": "wrong"}, ()),
            ("project", {"project": "wrong"}, ()),
            ("status", {"status": "RELEASED"}, ()),
            ("missing_token", {}, ("ownership_token",)),
            ("bad_token", {"ownership_token": "A" * 32}, ()),
            ("unsafe_run", {"run_id": "unsafe run/id"}, ()),
            ("missing_plan_hash", {}, ("plan_hash",)),
            ("bad_plan_hash", {"plan_hash": "not-a-sha256"}, ()),
            ("naive_claimed_at", {"claimed_at_utc": "2026-08-20T00:00:00"}, ()),
        )
        for kind in LAUNCHERS:
            for label, overrides, remove_fields in cases:
                with self.subTest(kind=kind, label=label), tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.fixture(temp_dir, kind)
                    original = fixture.write_claim(
                        owner_pid=999_999,
                        overrides=overrides,
                        remove_fields=remove_fields,
                    )

                    result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(original, fixture.claim.read_bytes())
                    self.assertFalse(fixture.archive.exists(), result.stdout + result.stderr)
                    self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)

    def test_direct_visible_workers_honor_not_due_before_writer_claim(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_state(next_interval_at_utc=future)
                original_claim = fixture.write_claim(owner_pid=os.getpid())

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("NOT_DUE", result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertEqual(original_claim, fixture.claim.read_bytes())

    def test_live_global_claim_is_preserved_and_blocks_every_visible_worker(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                original_claim = fixture.write_claim(owner_pid=os.getpid())

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("ALREADY_RUNNING", result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertEqual(original_claim, fixture.claim.read_bytes())

    def test_exact_process_start_identity_preserves_live_global_claim(self) -> None:
        process_started_at_utc = self.current_process_started_at_utc()
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                original_claim = fixture.write_claim(
                    owner_pid=os.getpid(),
                    owner_process_started_at_utc=process_started_at_utc,
                )

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("ALREADY_RUNNING", result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertEqual(original_claim, fixture.claim.read_bytes())

    def test_reused_pid_with_mismatched_process_start_is_recovered_after_double_check(self) -> None:
        mismatched_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_claim(
                    owner_pid=os.getpid(),
                    owner_process_started_at_utc=mismatched_start,
                )

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                ledger_rows = [
                    json.loads(line)
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                recovered = [row for row in ledger_rows if row.get("status") == "STALE_CLAIM_RECOVERED"]
                self.assertEqual(1, len(recovered), ledger_rows)
                self.assertEqual([os.getpid()], recovered[0]["stale_identity_mismatch_pids"])
                self.assertTrue(Path(recovered[0]["archive_path"]).is_file())

    def test_live_or_corrupt_legacy_expansion_claim_blocks_derivative_workers(self) -> None:
        legacy_payloads = {
            "live": json.dumps(
                {
                    "schema": "legacy_expansion_claim_v1",
                    "pid": os.getpid(),
                    "claimed_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            ),
            "corrupt": "{not-json",
        }
        for kind in LAUNCHERS:
            for label, contents in legacy_payloads.items():
                with self.subTest(kind=kind, label=label), tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.fixture(temp_dir, kind)
                    fixture.legacy_expansion_claim.parent.mkdir(parents=True, exist_ok=True)
                    fixture.legacy_expansion_claim.write_text(contents, encoding="utf-8")

                    result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("legacy_expansion_writer_claim_exists", result.stdout + result.stderr)
                    self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                    self.assertEqual(contents, fixture.legacy_expansion_claim.read_text(encoding="utf-8"))

    def test_dead_global_claim_is_archived_with_recovery_evidence_then_worker_runs(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_claim(owner_pid=999_999)

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertFalse(fixture.claim.exists(), result.stdout + result.stderr)
                archive_records = list(fixture.archive.glob("*.json"))
                self.assertGreaterEqual(len(archive_records), 2, result.stdout + result.stderr)
                ledger_rows = [
                    json.loads(line)
                    for line in fixture.ledger.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
                recovered = [row for row in ledger_rows if row.get("status") == "STALE_CLAIM_RECOVERED"]
                self.assertEqual(1, len(recovered), ledger_rows)
                self.assertEqual(999_999, recovered[0]["stale_owner_pid"])
                self.assertTrue(recovered[0]["stale_claimed_at_utc"])
                self.assertTrue(Path(recovered[0]["archive_path"]).is_file())

    def test_visible_worker_without_scheduled_tick_is_rejected(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run("-VisibleWorker", "-Json")

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)
                self.assertIn("ScheduledTick", result.stdout + result.stderr)

    def test_premarket_inline_worker_entry_point_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.fixture(temp_dir, "premarket")

            result = fixture.run("-InlineWorker", "-ScheduledTick", "-Json")

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)

    def test_status_and_not_due_do_not_persist_in_memory_state_normalization(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for kind in LAUNCHERS:
            for mode in ("status", "not_due"):
                with self.subTest(kind=kind, mode=mode), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                    fixture = self.fixture(temp_dir, kind)
                    fixture.write_state(next_interval_at_utc=future)
                    state = json.loads(fixture.state.read_text(encoding="utf-8"))
                    for field in (
                        "cadence_policy_version",
                        "cadence_stage",
                        "cadence_seconds",
                        "cadence_reason",
                        "wake_interval_seconds",
                        "worker_process_started_at_utc",
                    ):
                        state.pop(field, None)
                    fixture.state.write_text(json.dumps(state), encoding="utf-8")
                    before_bytes = fixture.state.read_bytes()
                    before_mtime = fixture.state.stat().st_mtime_ns

                    args = ("-Status", "-Json") if mode == "status" else ("-ScheduledTick", "-Json")
                    result = fixture.run(*args)

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    if mode == "not_due":
                        self.assertIn("NOT_DUE", result.stdout + result.stderr)
                    self.assertEqual(before_bytes, fixture.state.read_bytes())
                    self.assertEqual(before_mtime, fixture.state.stat().st_mtime_ns)

    def test_status_uses_worker_process_start_identity_without_writing_state(self) -> None:
        exact_start = self.current_process_started_at_utc()
        mismatch_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cases = (
            ("exact", exact_start, None, True),
            ("mismatch", mismatch_start, exact_start, False),
            ("fallback", _MISSING, exact_start, True),
            ("legacy_last_started_drift", _MISSING, mismatch_start, True),
            ("legacy_missing", _MISSING, None, True),
        )
        for kind in LAUNCHERS:
            for label, worker_start, last_start, expected_alive in cases:
                with self.subTest(kind=kind, label=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                    fixture = self.fixture(temp_dir, kind)
                    fixture.write_state(
                        next_interval_at_utc=None,
                        worker_pid=os.getpid(),
                        worker_process_started_at_utc=worker_start,
                        last_started_at_utc=last_start,
                        status="RUNNING",
                    )
                    before_bytes = fixture.state.read_bytes()
                    before_mtime = fixture.state.stat().st_mtime_ns

                    result = fixture.run("-Status", "-Json")

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(expected_alive, payload["worker_alive"], payload)
                    self.assertEqual(before_bytes, fixture.state.read_bytes())
                    self.assertEqual(before_mtime, fixture.state.stat().st_mtime_ns)

    def test_due_tick_recovers_reused_worker_pid_but_exact_or_legacy_live_pid_blocks(self) -> None:
        exact_start = self.current_process_started_at_utc()
        mismatch_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for kind in LAUNCHERS:
            with self.subTest(kind=kind, case="mismatch"), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir, kind)
                fixture.write_state(
                    next_interval_at_utc=None,
                    worker_pid=os.getpid(),
                    worker_process_started_at_utc=mismatch_start,
                    last_started_at_utc=exact_start,
                    status="RUNNING",
                )

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                state = json.loads(fixture.state.read_text(encoding="utf-8-sig"))
                self.assertNotEqual(os.getpid(), state["worker_pid"], state)
                self.assertNotEqual(mismatch_start, state["worker_process_started_at_utc"], state)
                self.assertEqual(1, state["retry_count"], state)

            for label, worker_start, last_start in (
                ("exact", exact_start, None),
                ("fallback", _MISSING, exact_start),
                ("legacy_last_started_drift", _MISSING, mismatch_start),
                ("legacy_missing", _MISSING, None),
            ):
                with self.subTest(kind=kind, case=label), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                    fixture = self.fixture(temp_dir, kind)
                    fixture.write_state(
                        next_interval_at_utc=None,
                        worker_pid=os.getpid(),
                        worker_process_started_at_utc=worker_start,
                        last_started_at_utc=last_start,
                        status="RUNNING",
                    )
                    before = fixture.state.read_bytes()

                    result = fixture.run("-ScheduledTick", "-Json")

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertIn("ALREADY_RUNNING", result.stdout + result.stderr)
                    self.assertEqual(before, fixture.state.read_bytes())
                    self.assertFalse(fixture.marker.exists(), result.stdout + result.stderr)

    def test_visible_worker_persists_exact_process_start_identity_before_python(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run("-VisibleWorker", "-ScheduledTick", "-Json")

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                marker = json.loads(fixture.marker.read_text(encoding="utf-8"))
                state = marker["state"]
                self.assertEqual(marker["parent_pid"], state["worker_pid"])
                stored = datetime.fromisoformat(state["worker_process_started_at_utc"].replace("Z", "+00:00"))
                observed = datetime.fromisoformat(marker["parent_started_at_utc"].replace("Z", "+00:00"))
                self.assertLessEqual(abs((stored - observed).total_seconds()), 0.01)

    def test_release_delegates_atomic_archive_to_canonical_claim_helper(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run_release_claim_harness()

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertTrue(payload["reacquired"], payload)
                archives = list(fixture.archive.glob("*.json"))
                self.assertEqual(1, len(archives), archives)
                archived = json.loads(archives[0].read_text(encoding="utf-8-sig"))
                self.assertEqual("RELEASED", archived["status"], archived)
                self.assertEqual("fixture-owned-release", archived["run_id"])
                self.assertEqual("b" * 64, archived["plan_hash"])
                self.assertTrue(
                    fixture.claim.with_name(
                        fixture.claim.name + ".transaction.lock"
                    ).exists()
                )

    def test_release_preserves_substituted_plan_hash_claim(self) -> None:
        for kind in LAUNCHERS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
                fixture = self.fixture(temp_dir, kind)

                result = fixture.run_release_claim_harness(
                    substitute_plan_hash=True
                )

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertFalse(payload["reacquired"], payload)
                self.assertTrue(fixture.claim.exists(), payload)
                active = json.loads(fixture.claim.read_text(encoding="utf-8-sig"))
                self.assertEqual("f" * 64, active["plan_hash"])
                self.assertFalse(fixture.archive.exists())


if __name__ == "__main__":
    unittest.main()
