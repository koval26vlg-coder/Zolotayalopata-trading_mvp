param(
    [string]$PlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker,
    [switch]$ScheduledTick,
    [string]$WorkerHandoffToken = "",
    [string]$WorkerHandoffRunId = "",
    [string]$StatePathOverride = "",
    [string]$LedgerPathOverride = ""
)

$ErrorActionPreference = "Stop"

if ($args.Count -gt 0) {
    Write-Error ("Unsupported launcher arguments: " + ($args -join " "))
    exit 2
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot "docs\plans\preipo-perpetual-event-planonly-20260825-v5.json"
if (-not $PlanPath) { $PlanPath = $defaultPlanPath }
$planValidator = Join-Path $repoRoot "trading_mvp\src\preipo_plan.py"
$automationPy = Join-Path $repoRoot "trading_mvp\src\preipo_automation.py"
$claimManagerPy = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$runGateDir = Join-Path $repoRoot "docs\agent-log\run-gates"
$statePath = Join-Path $runGateDir "preipo_perpetual_event_automation_state.json"
$ledgerPath = Join-Path $runGateDir "preipo_perpetual_event_automation_attempts.jsonl"
$claimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$legacyExpansionClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-expansion-claim.json"
$claimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$launchRecordPath = Join-Path $runGateDir "preipo_perpetual_event_automation.launch.json"
$workerErrorPath = Join-Path $runGateDir "preipo_perpetual_event_automation.worker-error.log"
$pythonHandoffDir = Join-Path $runGateDir "python-worker-handoffs"
$eventsPath = Join-Path $repoRoot "exports\trading-mvp\preipo-perp\raw_events.jsonl"
$manifestPath = Join-Path $repoRoot "exports\trading-mvp\preipo-perp\manifest.json"
$scheduleIntervalSec = 3 * 60 * 60
$captureDurationSec = 5 * 60
$searchIntervalSec = 6 * 60 * 60
$soonIntervalSec = 3 * 60 * 60
$confirmedIntervalSec = 60 * 60
$scheduledIntervalSec = 5 * 60
$wakeIntervalSec = 5 * 60
$cadencePolicyVersion = "adaptive_event_proximity_v1"
$automationId = "zolotyaylopata-preipo-perpetual-event-monitor"

if ($StatePathOverride) { $statePath = [System.IO.Path]::GetFullPath($StatePathOverride) }
if ($LedgerPathOverride) { $ledgerPath = [System.IO.Path]::GetFullPath($LedgerPathOverride) }

function Resolve-PythonExecutable {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:PYTHON_EXE) { $candidates.Add($env:PYTHON_EXE) }
    foreach ($name in @("python.exe", "python", "py.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) { $candidates.Add($command.Source) }
    }
    $candidates.Add("C:\Program Files\Python313\python.exe")
    $candidates.Add("C:\Users\koval\AppData\Local\Programs\Python\Python313\python.exe")
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "Python executable not found; set PYTHON_EXE or install Python 3.13"
}

function Get-UtcIso { return [DateTimeOffset]::UtcNow.ToString("o") }
function Get-TextSha256([string]$Value) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToHexString($hasher.ComputeHash($bytes)).ToLowerInvariant() } finally { $hasher.Dispose() }
}
function Enter-VisibleLaunchMutex([int]$WaitMilliseconds = 0) {
    $mutexName = "Local\ZolotyayLopataPreIPOLaunch_" + (Get-TextSha256 ([System.IO.Path]::GetFullPath($statePath))).Substring(0, 24)
    $mutex = [System.Threading.Mutex]::new($false, $mutexName)
    $acquired = $false
    try { $acquired = $mutex.WaitOne([math]::Max(0, $WaitMilliseconds)) }
    catch [System.Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { $mutex.Dispose(); return $null }
    return $mutex
}
function Exit-VisibleLaunchMutex($Mutex) {
    if ($null -eq $Mutex) { return }
    try { $Mutex.ReleaseMutex() } catch { }
    try { $Mutex.Dispose() } catch { }
}
function Get-IntervalSeconds($State = $null) {
    if ($State -and $State.cadence_seconds) {
        $candidate = [int]$State.cadence_seconds
        if ($candidate -in @($searchIntervalSec, $soonIntervalSec, $confirmedIntervalSec, $scheduledIntervalSec)) { return $candidate }
    }
    switch ([string]$State.cadence_stage) {
        "SOON" { return $soonIntervalSec }
        "CONFIRMED" { return $confirmedIntervalSec }
        "SCHEDULED" { return $scheduledIntervalSec }
    }
    return $searchIntervalSec
}
function Get-NextIntervalUtc($State = $null) { return [DateTimeOffset]::UtcNow.AddSeconds((Get-IntervalSeconds $State)).ToString("o") }
function Get-FileSha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Read-JsonFile([string]$Path) { return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -DateKind String }

function Write-JsonAtomic([string]$Path, $Payload) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = "$Path.tmp.$PID"
    $Payload | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Append-Ledger($Payload) {
    $dir = Split-Path -Parent $ledgerPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    ($Payload | ConvertTo-Json -Compress -Depth 40) | Add-Content -LiteralPath $ledgerPath -Encoding UTF8
}

function Get-DefaultState {
    return [ordered]@{
        schema = "trading_mvp_preipo_perpetual_event_automation_state_v1"
        automation_id = $automationId
        cadence_policy_version = $cadencePolicyVersion
        cadence_stage = "SEARCH"
        cadence_seconds = $searchIntervalSec
        cadence_reason = "initial_search"
        event_eta_utc = $null
        official_confirmation = $false
        exact_timestamp = $false
        wake_interval_seconds = $wakeIntervalSec
        schedule_interval_seconds = $scheduleIntervalSec
        capture_duration_seconds = $captureDurationSec
        status = "IDLE"
        pending_retry = $false
        retry_count = 0
        attempt_count = 0
        next_interval_at_utc = $null
        last_attempt_id = $null
        last_started_at_utc = $null
        last_finished_at_utc = $null
        worker_pid = $null
        worker_process_started_at_utc = $null
        worker_handoff_token_sha256 = $null
        worker_handoff_run_id = $null
        worker_handoff_plan_hash = $null
        worker_handoff_issued_at_utc = $null
        outcomes = [ordered]@{}
        accrual = [ordered]@{ contracts_seen = 0; events_written = 0; complete_events = 0; official_events = 0; proxy_events = 0 }
        last_error = $null
        updated_at_utc = Get-UtcIso
    }
}

function Ensure-StateProperty($State, [string]$Name, $Value) {
    if (-not ($State.PSObject.Properties.Name -contains $Name)) {
        $State | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    } elseif ($null -eq $State.$Name) {
        $State.$Name = $Value
    }
}

function Get-State {
    if (-not (Test-Path -LiteralPath $statePath)) { return Get-DefaultState }
    $state = Read-JsonFile $statePath
    if ([string]$state.schema -ne "trading_mvp_preipo_perpetual_event_automation_state_v1") { throw "pre-IPO automation state schema mismatch" }
    $legacyCadence = -not ($state.PSObject.Properties.Name -contains "cadence_policy_version")
    Ensure-StateProperty $state "cadence_policy_version" $cadencePolicyVersion
    Ensure-StateProperty $state "cadence_stage" "SEARCH"
    Ensure-StateProperty $state "cadence_seconds" $searchIntervalSec
    Ensure-StateProperty $state "schedule_interval_seconds" $searchIntervalSec
    Ensure-StateProperty $state "cadence_reason" "migrated_existing_state"
    Ensure-StateProperty $state "wake_interval_seconds" $wakeIntervalSec
    Ensure-StateProperty $state "worker_process_started_at_utc" $null
    Ensure-StateProperty $state "worker_handoff_token_sha256" $null
    Ensure-StateProperty $state "worker_handoff_run_id" $null
    Ensure-StateProperty $state "worker_handoff_plan_hash" $null
    Ensure-StateProperty $state "worker_handoff_issued_at_utc" $null
    if ([int]$state.schedule_interval_seconds -ne $searchIntervalSec) {
        $state.schedule_interval_seconds = $searchIntervalSec
    }
    if ($legacyCadence) {
        $state.cadence_policy_version = $cadencePolicyVersion
        $state.cadence_stage = "SEARCH"
        $state.cadence_seconds = $searchIntervalSec
        $state.schedule_interval_seconds = $searchIntervalSec
        $state.cadence_reason = "migrated_legacy_fixed_cadence"
        $state.next_interval_at_utc = Get-NextIntervalUtc $state
    }
    return $state
}

function Set-State($State) {
    $State.updated_at_utc = Get-UtcIso
    Write-JsonAtomic $statePath $State
}

function Get-ProcessStartedAtUtc([int]$ProcessId) {
    return (Get-Process -Id $ProcessId -ErrorAction Stop).StartTime.ToUniversalTime().ToString("o")
}

function New-PythonWorkerHandoffReceipt($Claim, [string]$AttemptId, [string]$PlanHash) {
    $token = [guid]::NewGuid().ToString("N").ToLowerInvariant()
    $receiptPath = Join-Path $pythonHandoffDir ($AttemptId + ".json")
    $wrapperStartedAt = Get-ProcessStartedAtUtc -ProcessId $PID
    Write-JsonAtomic $receiptPath ([ordered]@{
        schema = "trading_mvp_market_data_worker_handoff_v1"
        status = "ISSUED"
        project = "trading_mvp"
        automation_id = $automationId
        attempt_id = $AttemptId
        plan_hash = $PlanHash
        wrapper_pid = $PID
        wrapper_process_started_at_utc = $wrapperStartedAt
        handoff_token_sha256 = Get-TextSha256 $token
        claim_run_id = [string]$Claim.run_id
        claim_owner_kind = [string]$Claim.owner_kind
        claim_owner_pid = [int]$Claim.owner_pid
        claim_owner_process_started_at_utc = [string]$Claim.owner_process_started_at_utc
        claim_ownership_token_sha256 = Get-TextSha256 ([string]$Claim.ownership_token)
        claim_output_namespace = [string]$Claim.output_namespace
        claim_must_exist = $true
        issued_at_utc = Get-UtcIso
    })
    return [ordered]@{ token = $token; receipt_path = $receiptPath; wrapper_process_started_at_utc = $wrapperStartedAt }
}

function Get-StateWorkerProcessStartedAtUtc($State) {
    if (
        $State.PSObject.Properties.Name -contains "worker_process_started_at_utc" -and
        -not [string]::IsNullOrWhiteSpace([string]$State.worker_process_started_at_utc)
    ) {
        return [string]$State.worker_process_started_at_utc
    }
    return $null
}

function Test-ProcessAlive([Nullable[int]]$ProcessId, [string]$ExpectedProcessStartedAtUtc = "") {
    if (-not $ProcessId) { return $false }
    try {
        $process = Get-Process -Id ([int]$ProcessId) -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($ExpectedProcessStartedAtUtc)) {
            # A legacy state cannot prove process identity. Keep a live PID
            # fail-closed instead of recovering a potentially active worker.
            return $true
        }
        try {
            $expected = [DateTimeOffset]::Parse($ExpectedProcessStartedAtUtc).ToUniversalTime().UtcDateTime
        } catch {
            # Corrupt identity is also fail-closed while the PID is live.
            return $true
        }
        $actual = $process.StartTime.ToUniversalTime()
        return [math]::Abs(($actual - $expected).TotalSeconds) -le 2
    } catch {
        return $false
    }
}

function Recover-StaleWorkerState($State, [switch]$PreserveQueuedHandoff) {
    if ([string]$State.status -notin @("RUNNING", "QUEUED_VISIBLE")) { return $State }
    if ($State.worker_pid) {
        $expectedProcessStartedAtUtc = Get-StateWorkerProcessStartedAtUtc $State
        if (Test-ProcessAlive $State.worker_pid $expectedProcessStartedAtUtc) { return $State }
    } elseif ([string]$State.status -ne "QUEUED_VISIBLE" -or $PreserveQueuedHandoff) {
        return $State
    }

    $attemptId = [string]$State.last_attempt_id
    $State.worker_pid = $null
    $State.worker_process_started_at_utc = $null
    $State.status = "RETRY_NEXT_INTERVAL"
    $State.pending_retry = $true
    $State.retry_count = [int]$State.retry_count + 1
    $State.last_finished_at_utc = Get-UtcIso
    $State.next_interval_at_utc = Get-NextIntervalUtc $State
    $State.last_error = if ($State.last_error) { ([string]$State.last_error) + "; worker_not_alive_recovered" } else { "worker_not_alive_recovered" }
    Append-Ledger ([ordered]@{ attempt_id = if ($attemptId) { $attemptId } else { "recovery_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") }; status = "RETRY_NEXT_INTERVAL"; reason = "worker_not_alive_recovered"; pending_retry = $true; next_interval_at_utc = $State.next_interval_at_utc })
    Set-State $State
    return $State
}

function Get-GlobalClaimInspection {
    if (-not (Test-Path -LiteralPath $claimPath)) {
        return [ordered]@{ state = "AVAILABLE"; reason = $null; claim = $null; owner_pids = @(); claimed_at_utc = $null }
    }
    try {
        $claim = Read-JsonFile $claimPath
        $claimedAtText = [string]$claim.claimed_at_utc
        if (-not $claimedAtText) { throw "claim is missing claimed_at_utc" }
        $claimedAt = [DateTimeOffset]::Parse($claimedAtText).ToUniversalTime()
        $ownerPids = [System.Collections.Generic.List[int]]::new()
        foreach ($name in @("owner_pid", "pid", "writer_pid", "terminal_pid")) {
            if ($claim.PSObject.Properties.Name -contains $name) {
                $candidate = 0
                if ([int]::TryParse([string]$claim.$name, [ref]$candidate) -and $candidate -gt 0 -and -not $ownerPids.Contains($candidate)) {
                    $ownerPids.Add($candidate)
                }
            }
        }
        if ($ownerPids.Count -eq 0) { throw "claim is missing a positive owner PID" }
        $identityPid = 0
        foreach ($name in @("owner_pid", "pid")) {
            if ($claim.PSObject.Properties.Name -contains $name) {
                $candidate = 0
                if ([int]::TryParse([string]$claim.$name, [ref]$candidate) -and $candidate -gt 0) {
                    $identityPid = $candidate
                    break
                }
            }
        }
        $identityStartedAt = $null
        if ($claim.PSObject.Properties.Name -contains "owner_process_started_at_utc" -and [string]$claim.owner_process_started_at_utc) {
            $identityStartedAt = [DateTimeOffset]::Parse([string]$claim.owner_process_started_at_utc).ToUniversalTime()
        }
        $livePids = [System.Collections.Generic.List[int]]::new()
        $identityMismatchPids = [System.Collections.Generic.List[int]]::new()
        foreach ($candidate in $ownerPids) {
            if (-not (Test-ProcessAlive $candidate)) { continue }
            if ($null -ne $identityStartedAt -and $candidate -eq $identityPid) {
                $actualStartedAt = [DateTimeOffset]((Get-Process -Id $candidate -ErrorAction Stop).StartTime.ToUniversalTime())
                if ([math]::Abs(($actualStartedAt - $identityStartedAt).TotalSeconds) -gt 2) {
                    $identityMismatchPids.Add($candidate)
                    continue
                }
            }
            $livePids.Add($candidate)
        }
        $claimState = if ($livePids.Count -gt 0) { "LIVE" } else { "STALE" }
        $claimReason = if ($livePids.Count -gt 0) { "global_writer_claim_live" } elseif ($identityMismatchPids.Count -gt 0) { "global_writer_claim_pid_identity_mismatch" } else { "global_writer_claim_owner_dead" }
        return [ordered]@{
            state = $claimState
            reason = $claimReason
            claim = $claim
            owner_pids = @($ownerPids)
            live_pids = @($livePids)
            identity_mismatch_pids = @($identityMismatchPids)
            claimed_at_utc = $claimedAt.ToString("o")
        }
    } catch {
        return [ordered]@{ state = "INVALID"; reason = "global_writer_claim_unreadable: $($_.Exception.Message)"; claim = $null; owner_pids = @(); claimed_at_utc = $null }
    }
}

function Recover-StaleGlobalClaim {
    try {
        $pythonExe = Resolve-PythonExecutable
        $output = & $pythonExe $claimManagerPy recover-stale --path $claimPath --archive-dir $claimArchiveDir 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw "recover-stale exited $exitCode`: $($output.Trim())" }
        $result = $output.Trim() | ConvertFrom-Json -DateKind String
        if ([string]$result.schema -cne "trading_mvp_global_market_writer_claim_recovery_v1") { throw "recovery schema mismatch" }
        if ([string]$result.status -notin @("ABSENT", "LIVE_PRESERVED", "STALE_RECOVERED", "BLOCKED")) { throw "unexpected recovery status" }
        if ([string]$result.status -eq "STALE_RECOVERED") {
            $identityMismatchPids = if ([string]$result.reason -eq "owner_process_identity_mismatch") { @([int]$result.owner_pid) } else { @() }
            Append-Ledger ([ordered]@{
                schema = "trading_mvp_global_market_writer_claim_recovery_v1"
                status = "STALE_CLAIM_RECOVERED"
                automation_id = $automationId
                recovered_at_utc = Get-UtcIso
                stale_owner_pid = [int]$result.owner_pid
                stale_owner_pids = @([int]$result.owner_pid)
                stale_identity_mismatch_pids = @($identityMismatchPids)
                stale_claimed_at_utc = $result.claimed_at_utc
                archive_path = [string]$result.archive_path
                original_sha256 = [string]$result.claim_sha256
            })
        }
        switch ([string]$result.status) {
            { $_ -in @("ABSENT", "STALE_RECOVERED") } { return [ordered]@{ state = "AVAILABLE"; reason = [string]$result.reason; claim = $null; owner_pids = @(); claimed_at_utc = $null; archive_path = $result.archive_path } }
            "LIVE_PRESERVED" { return [ordered]@{ state = "LIVE"; reason = [string]$result.reason; claim = $result; owner_pids = @([int]$result.owner_pid); claimed_at_utc = $result.claimed_at_utc } }
            default { return [ordered]@{ state = "INVALID"; reason = [string]$result.reason; claim = $result; owner_pids = @(); claimed_at_utc = $result.claimed_at_utc } }
        }
    } catch {
        return [ordered]@{ state = "INVALID"; reason = "global_writer_claim_recovery_failed: $($_.Exception.Message)"; claim = $null; owner_pids = @(); claimed_at_utc = $null }
    }
}

function Acquire-Claim([string]$RunId, [string]$PlanHash) {
    $inspection = Recover-StaleGlobalClaim
    if ([string]$inspection.state -ne "AVAILABLE") {
        return [ordered]@{ acquired = $false; status = $(if ([string]$inspection.state -eq "LIVE") { "ALREADY_RUNNING" } else { "CLAIM_BLOCKED" }); reason = $inspection.reason; inspection = $inspection; claim = $null }
    }
    try {
        $pythonExe = Resolve-PythonExecutable
        $ownerStartedAtUtc = (Get-Process -Id $PID -ErrorAction Stop).StartTime.ToUniversalTime().ToString("o")
        $claimArgs = @(
            $claimManagerPy, "claim", "--path", $claimPath,
            "--run-id", $RunId, "--owner-pid", [string]$PID,
            "--owner-kind", "preipo_perpetual_visible_worker",
            "--plan-hash", $PlanHash,
            "--output-namespace", (Split-Path -Parent $eventsPath),
            "--writer-pid", [string]$PID, "--terminal-pid", [string]$PID,
            "--owner-process-started-at-utc", $ownerStartedAtUtc
        )
        $claimText = & $pythonExe @claimArgs 2>&1 | Out-String
        $claimExitCode = $LASTEXITCODE
        if ($claimExitCode -ne 0) { throw "claim helper exited $claimExitCode`: $($claimText.Trim())" }
        $payload = $claimText.Trim() | ConvertFrom-Json -DateKind String -ErrorAction Stop
        if ([string]$payload.schema -cne "trading_mvp_global_market_writer_claim_v1" -or
            [string]$payload.run_id -cne $RunId -or [int]$payload.owner_pid -ne $PID -or
            [int]$payload.writer_pid -ne $PID -or [string]$payload.plan_hash -cne $PlanHash) {
            throw "claim helper returned inconsistent identity"
        }
        return [ordered]@{ acquired = $true; status = "CLAIMED"; reason = $null; claim = $payload }
    } catch {
        $existing = Get-GlobalClaimInspection
        return [ordered]@{ acquired = $false; status = $(if ([string]$existing.state -eq "LIVE") { "ALREADY_RUNNING" } else { "CLAIM_BLOCKED" }); reason = "global_writer_claim_race: $($_.Exception.Message)"; inspection = $existing; claim = $null }
    }
}

function Release-Claim($Claim, [string]$FinalStatus) {
    if ($null -eq $Claim) {
        Append-Ledger ([ordered]@{ status = "CLAIM_RELEASE_FAILED"; automation_id = $automationId; run_id = $null; reason = "global_writer_claim_identity_missing"; attempted_at_utc = Get-UtcIso })
        return $false
    }
    try {
        $pythonExe = Resolve-PythonExecutable
        $releaseArgs = @(
            $claimManagerPy, "release", "--path", $claimPath,
            "--run-id", [string]$Claim.run_id, "--owner-pid", [string]$Claim.owner_pid,
            "--ownership-token", [string]$Claim.ownership_token,
            "--final-status", $FinalStatus, "--archive-dir", $claimArchiveDir,
            "--plan-hash", [string]$Claim.plan_hash,
            "--owner-process-started-at-utc", [string]$Claim.owner_process_started_at_utc
        )
        $releaseText = & $pythonExe @releaseArgs 2>&1 | Out-String
        $releaseExitCode = $LASTEXITCODE
        if ($releaseExitCode -ne 0) { throw "release helper exited $releaseExitCode`: $($releaseText.Trim())" }
        $releaseResult = $releaseText.Trim() | ConvertFrom-Json -DateKind String -ErrorAction Stop
        $archivePath = [string]$releaseResult.archive_path
        if ([string]::IsNullOrWhiteSpace($archivePath) -or -not (Test-Path -LiteralPath $archivePath)) { throw "release helper archive evidence missing" }
        Append-Ledger ([ordered]@{ status = "CLAIM_RELEASED"; automation_id = $automationId; run_id = [string]$Claim.run_id; final_status = $FinalStatus; released_at_utc = Get-UtcIso; archive_path = $archivePath })
        return $true
    } catch {
        Append-Ledger ([ordered]@{ status = "CLAIM_RELEASE_FAILED"; automation_id = $automationId; run_id = [string]$Claim.run_id; reason = $_.Exception.Message; attempted_at_utc = Get-UtcIso })
        return $false
    }
}

function Invoke-ActiveRunGateCheck {
    try {
        $gateText = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json 2>&1 | Out-String
        $gateExitCode = $LASTEXITCODE
        if ($gateExitCode -ne 0) { throw "checker exited $gateExitCode" }
        if ([string]::IsNullOrWhiteSpace($gateText)) { throw "checker returned empty output" }
        $gate = $gateText.Trim() | ConvertFrom-Json -DateKind String
        if (-not ($gate.PSObject.Properties.Name -contains "status")) { throw "authoritative status is missing" }
        $authoritativeStatus = [string]$gate.status
        if ($authoritativeStatus -cne "READY_FOR_POSTPROCESS") {
            return [ordered]@{ ok = $false; reason = "active_run_gate_$authoritativeStatus"; payload = $gate }
        }
        return [ordered]@{ ok = $true; reason = $null; payload = $gate }
    } catch {
        return [ordered]@{ ok = $false; reason = "active_run_gate_invalid: $($_.Exception.Message)"; payload = $null }
    }
}

function Invoke-PlanPreflight {
    $pythonExe = Resolve-PythonExecutable
    if (-not (Test-Path -LiteralPath $PlanPath)) { throw "Plan file not found: $PlanPath" }
    $planText = & $pythonExe $planValidator --plan $PlanPath --json 2>&1 | Out-String
    $planExitCode = $LASTEXITCODE
    if ($planExitCode -ne 0) { throw "Plan validator exited $planExitCode`: $($planText.Trim())" }
    if ([string]::IsNullOrWhiteSpace($planText)) { throw "Plan validator returned empty output" }
    $plan = $planText.Trim() | ConvertFrom-Json -ErrorAction Stop
    foreach ($required in @("ok", "status", "reasons", "plan_id", "plan_hash")) {
        if (-not ($plan.PSObject.Properties.Name -contains $required)) { throw "Plan validator payload missing $required" }
    }
    if (([bool]$plan.ok -and [string]$plan.status -cne "PLAN_OK") -or
        (-not [bool]$plan.ok -and [string]$plan.status -cne "PLAN_INVALID")) {
        throw "Plan validator payload status is inconsistent"
    }
    if ([string]$plan.plan_hash -cnotmatch '^[0-9a-f]{64}$') { throw "Plan validator payload plan_hash is invalid" }
    $gateCheck = Invoke-ActiveRunGateCheck
    $gate = $gateCheck.payload
    $reasons = [System.Collections.Generic.List[string]]::new()
    if (-not [bool]$plan.ok) { $reasons.Add("plan_check_failed:" + (@($plan.reasons) -join ",")) }
    if (-not [bool]$gateCheck.ok) { $reasons.Add([string]$gateCheck.reason) }
    if (Test-Path -LiteralPath $legacyExpansionClaimPath) { $reasons.Add("legacy_expansion_writer_claim_exists") }
    return [ordered]@{
        ok = ($reasons.Count -eq 0)
        reasons = @($reasons)
        plan_id = [string]$plan.plan_id
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = Get-FileSha256 $PlanPath
        plan_check_status = [string]$plan.status
        gate_status = [string]$gate.gate_status
        gate_authoritative_status = [string]$gate.status
        cadence_policy_version = $cadencePolicyVersion
        cadence_stage = if (Test-Path -LiteralPath $statePath) { [string](Get-State).cadence_stage } else { "SEARCH" }
        cadence_seconds = if (Test-Path -LiteralPath $statePath) { [int](Get-State).cadence_seconds } else { $searchIntervalSec }
        schedule_interval_seconds = $scheduleIntervalSec
        capture_duration_seconds = $captureDurationSec
        wake_interval_seconds = $wakeIntervalSec
        events_path = $eventsPath
        manifest_path = $manifestPath
        next_interval_at_utc = if (Test-Path -LiteralPath $statePath) { (Get-State).next_interval_at_utc } else { Get-NextIntervalUtc }
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
}

function Set-RetryState([string]$Reason, $State, $Preflight = $null, [string]$AttemptId = $null) {
    $selfOwnedWorker = $false
    $workerProcessStartedAtUtc = Get-StateWorkerProcessStartedAtUtc $State
    if ($State.worker_pid -and [int]$State.worker_pid -eq $PID -and -not [string]::IsNullOrWhiteSpace($workerProcessStartedAtUtc)) {
        try {
            $expectedStart = [DateTimeOffset]::Parse($workerProcessStartedAtUtc).ToUniversalTime().UtcDateTime
            $actualStart = (Get-Process -Id $PID -ErrorAction Stop).StartTime.ToUniversalTime()
            $selfOwnedWorker = [math]::Abs(($actualStart - $expectedStart).TotalSeconds) -le 2
        } catch { }
    }
    $State.status = "RETRY_NEXT_INTERVAL"
    $State.pending_retry = $true
    $State.retry_count = [int]$State.retry_count + 1
    $State.next_interval_at_utc = Get-NextIntervalUtc $State
    $State.last_error = $Reason
    if ($selfOwnedWorker) {
        $State.worker_pid = $null
        $State.worker_process_started_at_utc = $null
    }
    $State.worker_handoff_token_sha256 = $null
    $State.worker_handoff_run_id = $null
    $State.worker_handoff_plan_hash = $null
    $State.worker_handoff_issued_at_utc = $null
    Append-Ledger ([ordered]@{ attempt_id = if ($AttemptId) { $AttemptId } else { "deferred_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") }; status = "RETRY_NEXT_INTERVAL"; reason = $Reason; pending_retry = $true; next_interval_at_utc = $State.next_interval_at_utc; preflight = $Preflight })
    Set-State $State
}

function Get-StatusPayload {
    $state = Get-State
    $launch = $null
    if (Test-Path -LiteralPath $launchRecordPath) { try { $launch = Read-JsonFile $launchRecordPath } catch { $launch = @{ status = "UNREADABLE" } } }
    return [ordered]@{
        status = [string]$state.status
        automation_id = [string]$state.automation_id
        cadence_policy_version = [string]$state.cadence_policy_version
        cadence_stage = [string]$state.cadence_stage
        cadence_seconds = [int]$state.cadence_seconds
        cadence_reason = [string]$state.cadence_reason
        event_eta_utc = $state.event_eta_utc
        wake_interval_seconds = $wakeIntervalSec
        schedule_interval_seconds = if ($null -ne $state.schedule_interval_seconds) { [int]$state.schedule_interval_seconds } else { $scheduleIntervalSec }
        capture_duration_seconds = if ($null -ne $state.capture_duration_seconds) { [int]$state.capture_duration_seconds } else { $captureDurationSec }
        pending_retry = [bool]$state.pending_retry
        retry_count = [int]$state.retry_count
        attempt_count = [int]$state.attempt_count
        next_interval_at_utc = $state.next_interval_at_utc
        worker_pid = $state.worker_pid
        worker_alive = Test-ProcessAlive $state.worker_pid (Get-StateWorkerProcessStartedAtUtc $state)
        outcomes = $state.outcomes
        accrual = $state.accrual
        last_error = $state.last_error
        launch_record = $launch
        state_path = $statePath
        ledger_path = $ledgerPath
        events_path = $eventsPath
        manifest_path = $manifestPath
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
}

if ($Status) {
    $payload = Get-StatusPayload
    if ($Json) { $payload | ConvertTo-Json -Depth 40 } else { Write-Host ($payload | ConvertTo-Json -Depth 40) }
    exit 0
}

if ($PreflightOnly) {
    $preflight = $null
    try { $preflight = Invoke-PlanPreflight } catch {
        $preflight = [ordered]@{ ok = $false; reasons = @("preflight_exception:" + $_.Exception.Message); status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    }
    if ($Json) { $preflight | ConvertTo-Json -Depth 40 } else { Write-Host ($preflight | ConvertTo-Json -Depth 40) }
    exit $(if ($preflight.ok) { 0 } else { 1 })
}

if (-not $ScheduledTick) {
    Write-Error "Execution requires -ScheduledTick; direct VisibleWorker bypass is disabled."
    exit 2
}

$state = Get-State
$invalidNextIntervalReason = $null
if ($state.next_interval_at_utc) {
    try {
        $nextInterval = [DateTimeOffset]::Parse([string]$state.next_interval_at_utc).ToUniversalTime()
    } catch {
        $invalidNextIntervalReason = "invalid_next_interval_at_utc: " + $_.Exception.Message
    }
    if ([DateTimeOffset]::UtcNow -lt $nextInterval) {
        $payload = [ordered]@{ status = "NOT_DUE"; automation_id = $automationId; pending_retry = [bool]$state.pending_retry; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
        $payload | ConvertTo-Json -Depth 30
        exit 0
    }
}

if ($state.worker_pid -and (Test-ProcessAlive $state.worker_pid (Get-StateWorkerProcessStartedAtUtc $state))) {
    $isOwnedVisibleHandoff = (
        $VisibleWorker -and
        [int]$state.worker_pid -eq $PID -and
        -not [string]::IsNullOrWhiteSpace($WorkerHandoffToken) -and
        -not [string]::IsNullOrWhiteSpace($WorkerHandoffRunId) -and
        [string]$state.status -eq "QUEUED_VISIBLE" -and
        [string]$state.worker_handoff_run_id -ceq $WorkerHandoffRunId -and
        [string]$state.worker_handoff_token_sha256 -ceq (Get-TextSha256 $WorkerHandoffToken)
    )
    if ($isOwnedVisibleHandoff) {
        # The outer launcher durably attached this exact visible process. It is
        # the owner, not a duplicate wake, so continue to the full handoff guard.
    } else {
    $payload = [ordered]@{ status = "ALREADY_RUNNING"; automation_id = $automationId; worker_pid = $state.worker_pid; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    $payload | ConvertTo-Json -Depth 30
    exit 0
    }
}

if ($VisibleWorker) {
    $handoffValid = (
        -not [string]::IsNullOrWhiteSpace($WorkerHandoffToken) -and
        -not [string]::IsNullOrWhiteSpace($WorkerHandoffRunId) -and
        [string]$state.status -eq "QUEUED_VISIBLE" -and
        [string]$state.worker_handoff_run_id -ceq $WorkerHandoffRunId -and
        [string]$state.worker_handoff_token_sha256 -ceq (Get-TextSha256 $WorkerHandoffToken)
    )
    if (-not $handoffValid) {
        [ordered]@{ status = "BLOCKED"; automation_id = $automationId; reason = "worker_handoff_invalid_or_missing" } | ConvertTo-Json -Depth 10
        exit 2
    }
}

$preflight = $null
try { $preflight = Invoke-PlanPreflight } catch {
    $preflight = [ordered]@{ ok = $false; reasons = @("preflight_exception:" + $_.Exception.Message); status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
}
if (-not $preflight.ok) {
    $reason = @($preflight.reasons) -join "; "
    Set-RetryState -Reason $reason -State $state -Preflight $preflight
    $payload = [ordered]@{ status = "RETRY_NEXT_INTERVAL"; automation_id = $automationId; pending_retry = $true; reason = $reason; next_interval_at_utc = $state.next_interval_at_utc; preflight = $preflight; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    $payload | ConvertTo-Json -Depth 40
    exit 1
}
if ($VisibleWorker -and [string]$state.worker_handoff_plan_hash -cne [string]$preflight.plan_hash) {
    $reason = "worker_handoff_plan_hash_mismatch"
    Set-RetryState -Reason $reason -State $state -Preflight $preflight
    [ordered]@{ status = "RETRY_NEXT_INTERVAL"; automation_id = $automationId; reason = $reason; next_interval_at_utc = $state.next_interval_at_utc } | ConvertTo-Json -Depth 20
    exit 1
}

if ($invalidNextIntervalReason) {
    Set-RetryState -Reason $invalidNextIntervalReason -State $state -Preflight $preflight
    $payload = [ordered]@{ status = "RETRY_NEXT_INTERVAL"; automation_id = $automationId; pending_retry = $true; reason = $invalidNextIntervalReason; next_interval_at_utc = $state.next_interval_at_utc; preflight = $preflight; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    $payload | ConvertTo-Json -Depth 40
    exit 1
}

# Persist stale-PID normalization only after positive Plan/gate preflight.
$visibleLaunchMutex = Enter-VisibleLaunchMutex -WaitMilliseconds $(if ($VisibleWorker) { 15000 } else { 0 })
if ($null -eq $visibleLaunchMutex) {
    [ordered]@{ status = "ALREADY_RUNNING"; automation_id = $automationId; reason = "visible_launch_in_progress"; next_interval_at_utc = $state.next_interval_at_utc } | ConvertTo-Json -Depth 20
    exit 0
}
if ($VisibleWorker) {
    $state = Get-State
    $handoffStillValid = (
        [string]$state.status -in @("QUEUED_VISIBLE", "RUNNING") -and
        [string]$state.worker_handoff_run_id -ceq $WorkerHandoffRunId -and
        [string]$state.worker_handoff_token_sha256 -ceq (Get-TextSha256 $WorkerHandoffToken) -and
        (-not $state.worker_pid -or [int]$state.worker_pid -eq $PID -or -not (Test-ProcessAlive $state.worker_pid (Get-StateWorkerProcessStartedAtUtc $state)))
    )
    Exit-VisibleLaunchMutex $visibleLaunchMutex
    $visibleLaunchMutex = $null
    if (-not $handoffStillValid) {
        [ordered]@{ status = "BLOCKED"; automation_id = $automationId; reason = "worker_handoff_attach_mismatch" } | ConvertTo-Json -Depth 20
        exit 2
    }
}
$state = Recover-StaleWorkerState -State $state -PreserveQueuedHandoff:$VisibleWorker

if ($VisibleWorker) {
    $attemptId = [string]$WorkerHandoffRunId
    $claimResult = Acquire-Claim -RunId $attemptId -PlanHash ([string]$preflight.plan_hash)
    if (-not [bool]$claimResult.acquired) {
        if ([string]$claimResult.status -eq "ALREADY_RUNNING") {
            $payload = [ordered]@{ status = "ALREADY_RUNNING"; automation_id = $automationId; pending_retry = [bool]$state.pending_retry; reason = [string]$claimResult.reason; claim = $claimResult.inspection.claim; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
            $payload | ConvertTo-Json -Depth 40
            exit 0
        }
        $reason = [string]$claimResult.reason
        Set-RetryState -Reason $reason -State $state -Preflight $preflight
        $payload = [ordered]@{ status = "RETRY_NEXT_INTERVAL"; automation_id = $automationId; pending_retry = $true; reason = $reason; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
        $payload | ConvertTo-Json -Depth 40
        exit 1
    }
    $workerClaim = $claimResult.claim
    $pythonHandoff = $null
    $started = Get-UtcIso
    $launchRecord = [ordered]@{
        schema = "trading_mvp_preipo_perpetual_event_automation_launch_v1"
        status = "RUNNING"
        automation_id = $automationId
        attempt_id = $attemptId
        visible_terminal_pid = $PID
        started_at_utc = $started
        cwd = $repoRoot
        command = "python trading_mvp/src/preipo_automation.py --repo-root `"$repoRoot`" --tick --attempt-id `"$attemptId`" --worker-handoff-token <redacted> --plan-hash `"$($preflight.plan_hash)`""
        plan_path = $PlanPath
        plan_hash = [string]$preflight.plan_hash
        plan_file_sha256 = [string]$preflight.plan_file_sha256
        expected_duration_sec = 420
        schedule_interval_seconds = $scheduleIntervalSec
        capture_duration_seconds = $captureDurationSec
        public_data_only = $true
        private_api = $false
        live_orders = $false
        retry_policy = "failed or deferred venue retries on next adaptive interval; scheduler wake is every 5 minutes"
        manifest_path = $manifestPath
    }
    try {
    $pythonHandoff = New-PythonWorkerHandoffReceipt -Claim $workerClaim -AttemptId $attemptId -PlanHash ([string]$preflight.plan_hash)
    $state.status = "RUNNING"
    $state.pending_retry = $false
    $state.attempt_count = [int]$state.attempt_count + 1
    $state.last_attempt_id = $attemptId
    $state.last_started_at_utc = $started
    $state.last_finished_at_utc = $null
    $state.worker_pid = $PID
    $state.worker_process_started_at_utc = Get-ProcessStartedAtUtc -ProcessId $PID
    $state.worker_handoff_token_sha256 = $null
    $state.worker_handoff_run_id = $null
    $state.worker_handoff_plan_hash = $null
    $state.worker_handoff_issued_at_utc = $null
    $state.outcomes = [ordered]@{}
    $state.last_error = $null
    Append-Ledger ([ordered]@{ attempt_id = $attemptId; status = "RUNNING"; started_at_utc = $started; visible_terminal_pid = $PID; worker_pid = $PID; runner_mode = "visible_terminal_worker"; plan_hash = [string]$preflight.plan_hash })
    Set-State $state
    Write-JsonAtomic $launchRecordPath $launchRecord
        Write-Host "=== Pre-IPO perpetual automation (visible) ===" -ForegroundColor Cyan
        Write-Host ("venues: OKX + Gate; cadence stage: " + [string]$state.cadence_stage + "; actual interval: " + [int]$state.cadence_seconds + " sec; scheduler wake: " + $wakeIntervalSec + " sec; public capture window: " + $captureDurationSec + " sec")
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        $pythonExe = Resolve-PythonExecutable
        $workerOutput = & $pythonExe $automationPy --repo-root $repoRoot --tick --attempt-id $attemptId --worker-handoff-token ([string]$pythonHandoff.token) --plan-hash ([string]$preflight.plan_hash) --max-contracts-per-venue 25 --timeout-sec 10 --websocket-duration-sec $captureDurationSec 2>&1 | Out-String
        $workerExit = $LASTEXITCODE
        if ($workerOutput.Trim()) { Write-Host $workerOutput.Trim() }
        $state = Get-State
        if ($workerExit -ne 0 -and [string]$state.status -notin @("RETRY_NEXT_INTERVAL", "PARTIAL_RETRY_NEXT_INTERVAL")) {
            Set-RetryState -Reason ("python_worker_exit_" + $workerExit) -State $state -Preflight $preflight
            $state = Get-State
        }
        $launchRecord.status = [string]$state.status
        $launchRecord.finished_at_utc = Get-UtcIso
        $launchRecord.worker_exit_code = $workerExit
        $launchRecord.pending_retry = [bool]$state.pending_retry
        $launchRecord.next_interval_at_utc = $state.next_interval_at_utc
        $launchRecord.outcomes = $state.outcomes
        Write-JsonAtomic $launchRecordPath $launchRecord
        Write-Host ("automation status: " + [string]$state.status)
        Write-Host ("next interval: " + [string]$state.next_interval_at_utc)
        exit $(if ($workerExit -eq 0) { 0 } else { 1 })
    } catch {
        $reason = "visible_worker_exception: " + $_.Exception.Message
        try { $state = Get-State; Set-RetryState -Reason $reason -State $state -Preflight $preflight } catch { }
        $reason | Set-Content -LiteralPath $workerErrorPath -Encoding UTF8
        $launchRecord.status = "RETRY_NEXT_INTERVAL"
        $launchRecord.finished_at_utc = Get-UtcIso
        $launchRecord.error = $reason
        Write-JsonAtomic $launchRecordPath $launchRecord
        exit 1
    } finally {
        $finalClaimStatus = if ($launchRecord.status) { [string]$launchRecord.status } else { "UNKNOWN" }
        $claimReleased = Release-Claim -Claim $workerClaim -FinalStatus $finalClaimStatus
        if (-not $claimReleased) {
            $releaseReason = "global_writer_claim_release_failed"
            try { $state = Get-State; Set-RetryState -Reason $releaseReason -State $state -Preflight $preflight } catch { }
            try {
                $launchRecord.status = "RETRY_NEXT_INTERVAL"
                $launchRecord.pending_retry = $true
                $launchRecord.finished_at_utc = Get-UtcIso
                $launchRecord.error = $releaseReason
                Write-JsonAtomic $launchRecordPath $launchRecord
            } catch { }
            exit 1
        }
    }
}

$claimInspection = Recover-StaleGlobalClaim
if ([string]$claimInspection.state -eq "LIVE") {
    $payload = [ordered]@{ status = "ALREADY_RUNNING"; automation_id = $automationId; reason = $claimInspection.reason; claim = $claimInspection.claim; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    $payload | ConvertTo-Json -Depth 40
    exit 0
}
if ([string]$claimInspection.state -ne "AVAILABLE") {
    Set-RetryState -Reason ([string]$claimInspection.reason) -State $state -Preflight $preflight
    $payload = [ordered]@{ status = "RETRY_NEXT_INTERVAL"; automation_id = $automationId; pending_retry = $true; reason = [string]$claimInspection.reason; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    $payload | ConvertTo-Json -Depth 40
    exit 1
}

try {
    $pwshExe = (Get-Process -Id $PID).Path
    $handoffToken = [guid]::NewGuid().ToString("N").ToLowerInvariant()
    $handoffRunId = "preipo_outer_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ") + "_" + $handoffToken.Substring(0, 8)
    $queuedAt = Get-UtcIso
    Append-Ledger ([ordered]@{ attempt_id = $handoffRunId; status = "QUEUED_VISIBLE"; queued_at_utc = $queuedAt; pending_retry_before_attempt = [bool]$state.pending_retry; next_interval_at_utc = $state.next_interval_at_utc; plan_hash = [string]$preflight.plan_hash })
    $state.status = "QUEUED_VISIBLE"
    $state.last_attempt_id = $handoffRunId
    $state.worker_handoff_token_sha256 = Get-TextSha256 $handoffToken
    $state.worker_handoff_run_id = $handoffRunId
    $state.worker_handoff_plan_hash = [string]$preflight.plan_hash
    $state.worker_handoff_issued_at_utc = $queuedAt
    Set-State $state
    $childArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -VisibleWorker -ScheduledTick -WorkerHandoffToken `"$handoffToken`" -WorkerHandoffRunId `"$handoffRunId`" -PlanPath `"$PlanPath`""
    $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
    $attachedState = Get-State
    $terminalProcessStartedAtUtc = Get-ProcessStartedAtUtc -ProcessId $terminal.Id
    if ([string]$attachedState.status -eq "QUEUED_VISIBLE" -and [string]$attachedState.worker_handoff_run_id -ceq $handoffRunId -and [string]$attachedState.worker_handoff_token_sha256 -ceq (Get-TextSha256 $handoffToken)) {
        $attachedState.worker_pid = $terminal.Id
        $attachedState.worker_process_started_at_utc = $terminalProcessStartedAtUtc
        Set-State $attachedState
        $state = $attachedState
    } elseif ([string]$attachedState.last_attempt_id -ceq $handoffRunId -and [int]$attachedState.worker_pid -eq $terminal.Id) {
        $state = $attachedState
    } else {
        throw "visible_worker_attach_state_conflict"
    }
    Exit-VisibleLaunchMutex $visibleLaunchMutex
    $visibleLaunchMutex = $null
    $payload = [ordered]@{ status = "VISIBLE_TERMINAL_LAUNCHED"; automation_id = $automationId; visible_terminal_pid = $terminal.Id; plan_hash = $preflight.plan_hash; expected_duration_sec = 420; schedule_interval_seconds = $scheduleIntervalSec; capture_duration_seconds = $captureDurationSec; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"; launch_record_path = $launchRecordPath }
    if ($Json) { $payload | ConvertTo-Json -Depth 40 } else { Write-Host ($payload | ConvertTo-Json -Depth 40) }
} catch {
    $startFailureReason = "visible_worker_start_failed: " + $_.Exception.Message
    try {
        Set-RetryState -Reason $startFailureReason -State $state -Preflight $preflight -AttemptId $handoffRunId
    } finally {
        Exit-VisibleLaunchMutex $visibleLaunchMutex
        $visibleLaunchMutex = $null
    }
    $payload = [ordered]@{ status = "RETRY_NEXT_INTERVAL"; automation_id = $automationId; pending_retry = $true; reason = $state.last_error; next_interval_at_utc = $state.next_interval_at_utc; status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json" }
    $payload | ConvertTo-Json -Depth 40
    exit 1
}
exit 0
