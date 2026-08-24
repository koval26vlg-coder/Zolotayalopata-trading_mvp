param(
    [string]$V2PlanPath = "",
    [string]$ExpansionPlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker,
    [switch]$ScheduledTick,
    [string]$WorkerHandoffToken = "",
    [string]$WorkerHandoffRunId = "",
    [string]$StatePathOverride = "",
    [string]$LedgerPathOverride = "",
    [string]$SchedulerClaimPathOverride = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultV2PlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-monitor-planonly-20260824-v5.json"
$defaultExpansionPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-expansion-planonly-20260824-v4.json"
if (-not $V2PlanPath) { $V2PlanPath = $defaultV2PlanPath }
if (-not $ExpansionPlanPath) { $ExpansionPlanPath = $defaultExpansionPlanPath }

$v2Launcher = Join-Path $repoRoot "tools\start_listing_momentum_forward_tick_visible.ps1"
$expansionLauncher = Join-Path $repoRoot "tools\start_listing_momentum_forward_expansion_tick_visible.ps1"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$statePath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_automation_state.json"
$ledgerPath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_automation_attempts.jsonl"
$schedulerClaimPath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_automation.claim.json"
$launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_automation.launch.json"
$workerErrorLog = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_automation.worker-error.log"
if ($StatePathOverride) { $statePath = [System.IO.Path]::GetFullPath($StatePathOverride) }
if ($LedgerPathOverride) { $ledgerPath = [System.IO.Path]::GetFullPath($LedgerPathOverride) }
if ($SchedulerClaimPathOverride) { $schedulerClaimPath = [System.IO.Path]::GetFullPath($SchedulerClaimPathOverride) }
$schedulerClaimArchiveDir = Join-Path (Split-Path -Parent $schedulerClaimPath) "scheduler-claim-archive"
$searchIntervalSec = 6 * 60 * 60
$soonIntervalSec = 3 * 60 * 60
$confirmedIntervalSec = 60 * 60
$scheduledIntervalSec = 5 * 60
$wakeIntervalSec = 5 * 60
$cadencePolicyVersion = "adaptive_event_proximity_v1"

function Resolve-PowerShellExecutable {
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($commandName in @("pwsh.exe", "pwsh", "powershell.exe", "powershell")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) { $candidates.Add($command.Source) }
    }
    $candidates.Add("C:\Program Files\PowerShell\7\pwsh.exe")
    $candidates.Add("C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "PowerShell executable not found"
}

function Read-JsonFile([string]$Path) {
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json -DateKind String
}

function Write-JsonFile([string]$Path, $Payload) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $tmpPath = "$Path.tmp.$PID"
    $Payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmpPath -Encoding UTF8
    Move-Item -LiteralPath $tmpPath -Destination $Path -Force
}

function Append-Ledger($Payload) {
    $dir = Split-Path -Parent $ledgerPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    ($Payload | ConvertTo-Json -Compress -Depth 20) | Add-Content -LiteralPath $ledgerPath -Encoding UTF8
}

function Get-TerminalLedgerAttempt([string]$AttemptId) {
    if (-not $AttemptId -or -not (Test-Path -LiteralPath $ledgerPath)) { return $null }
    $lines = @(Get-Content -LiteralPath $ledgerPath -Encoding UTF8)
    for ($index = $lines.Count - 1; $index -ge 0; $index--) {
        if (-not [string]$lines[$index]) { continue }
        try { $row = [string]$lines[$index] | ConvertFrom-Json -DateKind String } catch { continue }
        if ([string]$row.attempt_id -cne $AttemptId) { continue }
        if ([string]$row.status -notin @("RUNNING", "QUEUED_VISIBLE")) { return $row }
    }
    return $null
}

function Get-UtcIso {
    return (Get-Date).ToUniversalTime().ToString("o")
}

function Get-TextSha256([string]$Value) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToHexString($hasher.ComputeHash($bytes)).ToLowerInvariant() } finally { $hasher.Dispose() }
}

function Enter-VisibleLaunchMutex([int]$WaitMilliseconds = 0) {
    $mutexName = "Local\ZolotyayLopataListingLaunch_" + (Get-TextSha256 ([System.IO.Path]::GetFullPath($statePath))).Substring(0, 24)
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
        if ($candidate -in @($searchIntervalSec, $soonIntervalSec, $confirmedIntervalSec, $scheduledIntervalSec)) {
            return $candidate
        }
    }
    if ($State -and $State.cadence_stage) {
        switch ([string]$State.cadence_stage) {
            "SOON" { return $soonIntervalSec }
            "CONFIRMED" { return $confirmedIntervalSec }
            "SCHEDULED" { return $scheduledIntervalSec }
        }
    }
    return $searchIntervalSec
}

function Get-NextIntervalUtc([int]$IntervalSec = 0, $State = $null) {
    if ($IntervalSec -le 0) { $IntervalSec = Get-IntervalSeconds $State }
    return [DateTimeOffset]::UtcNow.AddSeconds($IntervalSec).ToString("o")
}

function Resolve-CadenceDecision($State) {
    $observation = $State.cadence_observation
    if ($null -eq $observation) {
        $observation = [ordered]@{
            event_eta_utc = $State.event_eta_utc
            official_confirmed = [bool]$State.official_confirmation
            exact_timestamp = [bool]$State.exact_timestamp
            candidate = ([string]$State.cadence_stage -ne "SEARCH")
            lifecycle_status = $State.lifecycle_status
            source_class = $State.source_class
            proxy_timestamp = [bool]$State.proxy_timestamp
        }
    }
    $lifecycle = [string]($observation.lifecycle_status)
    if ($lifecycle -in @("cancelled", "canceled", "expired", "delisted", "complete", "completed")) {
        return [ordered]@{ stage = "SEARCH"; interval_sec = $searchIntervalSec; reason = "terminal_lifecycle:$lifecycle"; event_eta_utc = $null }
    }
    $eta = $null
    if ($observation.event_eta_utc) {
        try { $eta = [DateTimeOffset]::Parse([string]$observation.event_eta_utc).ToUniversalTime() } catch { $eta = $null }
    }
    $official = [bool]$observation.official_confirmed -or ([string]$observation.source_class -eq "official")
    $exact = [bool]$observation.exact_timestamp -or [bool]$observation.exact_official_timestamp
    $proxy = [bool]$observation.proxy_timestamp -or ([string]$observation.source_class -eq "proxy") -or [bool]$observation.is_proxy_timestamp
    if ($exact -and $official -and -not $proxy -and $null -ne $eta) {
        $secondsUntil = ($eta - [DateTimeOffset]::UtcNow).TotalSeconds
        if (($secondsUntil -ge 0 -and $secondsUntil -le 24 * 60 * 60) -or ($secondsUntil -lt 0 -and [math]::Abs($secondsUntil) -le $scheduledIntervalSec)) {
            return [ordered]@{ stage = "SCHEDULED"; interval_sec = $scheduledIntervalSec; reason = "exact_official_event_within_24h"; event_eta_utc = $eta.ToString("o") }
        }
    }
    if ($official -and -not $proxy) {
        return [ordered]@{ stage = "CONFIRMED"; interval_sec = $confirmedIntervalSec; reason = "official_event_confirmed_without_near_exact_time"; event_eta_utc = if ($eta) { $eta.ToString("o") } else { $null } }
    }
    if ($null -ne $eta) {
        $secondsUntil = ($eta - [DateTimeOffset]::UtcNow).TotalSeconds
        if ($secondsUntil -ge 0 -and $secondsUntil -le 72 * 60 * 60) {
            return [ordered]@{ stage = "SOON"; interval_sec = $soonIntervalSec; reason = "candidate_event_within_72h"; event_eta_utc = $eta.ToString("o") }
        }
    }
    if ([bool]$observation.candidate -or [bool]$observation.contract_present -or [bool]$observation.pre_market_active) {
        return [ordered]@{ stage = "SOON"; interval_sec = $soonIntervalSec; reason = "candidate_or_active_contract_present"; event_eta_utc = if ($eta) { $eta.ToString("o") } else { $null } }
    }
    return [ordered]@{ stage = "SEARCH"; interval_sec = $searchIntervalSec; reason = "no_qualified_upcoming_event"; event_eta_utc = $null }
}

function Set-CadenceState($State, $Decision) {
    $State.cadence_policy_version = $cadencePolicyVersion
    $State.cadence_stage = [string]$Decision.stage
    $State.cadence_seconds = [int]$Decision.interval_sec
    $State.cadence_hours = [math]::Round(([int]$Decision.interval_sec / 3600), 4)
    $State.cadence_reason = [string]$Decision.reason
    $State.event_eta_utc = $Decision.event_eta_utc
    $State.next_interval_at_utc = Get-NextIntervalUtc -IntervalSec ([int]$Decision.interval_sec)
    return $State
}

function Get-TrackCadenceDecision([string]$PlanPath) {
    if (-not (Test-Path -LiteralPath $PlanPath)) { return $null }
    try {
        $plan = Read-JsonFile -Path $PlanPath
        $statePathFromPlan = [string]$plan.tick.state_path
        if (-not $statePathFromPlan -or -not (Test-Path -LiteralPath $statePathFromPlan)) { return $null }
        $trackState = Read-JsonFile -Path $statePathFromPlan
        $candidate = $trackState.adaptive_cadence
        if ($null -eq $candidate) { return $null }
        return [ordered]@{
            stage = [string]$candidate.stage
            interval_sec = [int]$candidate.interval_sec
            reason = [string]$candidate.reason
            event_eta_utc = $candidate.event_eta_utc
            source_plan = $PlanPath
        }
    } catch {
        return $null
    }
}

function Resolve-CombinedCadence($State) {
    $choices = [System.Collections.Generic.List[object]]::new()
    foreach ($path in @($V2PlanPath, $ExpansionPlanPath)) {
        $decision = Get-TrackCadenceDecision -PlanPath $path
        if ($null -ne $decision) { $choices.Add($decision) }
    }
    if ($choices.Count -eq 0) { return Resolve-CadenceDecision $State }
    return ($choices | Sort-Object -Property interval_sec | Select-Object -First 1)
}

function Get-ProcessStartedAtUtc([int]$ProcessId) {
    return (Get-Process -Id $ProcessId -ErrorAction Stop).StartTime.ToUniversalTime().ToString("o")
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
            # Legacy state has no process identity.  A live PID remains
            # fail-closed rather than being recovered speculatively.
            return $null -ne $process
        }
        try {
            $expected = [DateTimeOffset]::Parse($ExpectedProcessStartedAtUtc).ToUniversalTime().UtcDateTime
        } catch {
            return $true
        }
        $actual = $process.StartTime.ToUniversalTime()
        return [math]::Abs(($actual - $expected).TotalSeconds) -le 2
    } catch {
        return $false
    }
}

function Get-DefaultState {
    return [ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_state_v1"
        automation_id = "zolotyaylopata-listing-momentum-monitor"
        cadence_policy_version = $cadencePolicyVersion
        cadence_stage = "SEARCH"
        cadence_seconds = $searchIntervalSec
        cadence_hours = 6
        cadence_reason = "initial_search"
        event_eta_utc = $null
        official_confirmation = $false
        exact_timestamp = $false
        wake_interval_seconds = $wakeIntervalSec
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
        worker_handoff_issued_at_utc = $null
        outcomes = [ordered]@{}
        last_error = $null
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
    try {
        $state = Read-JsonFile -Path $statePath
        if ([string]$state.schema -ne "trading_mvp_listing_momentum_forward_automation_state_v1") {
            throw "automation state schema mismatch"
        }
        $legacyCadence = -not ($state.PSObject.Properties.Name -contains "cadence_policy_version")
        Ensure-StateProperty $state "cadence_policy_version" $cadencePolicyVersion
        Ensure-StateProperty $state "cadence_stage" "SEARCH"
        Ensure-StateProperty $state "cadence_seconds" $searchIntervalSec
        Ensure-StateProperty $state "cadence_hours" 6
        Ensure-StateProperty $state "cadence_reason" "migrated_existing_state"
        # Set-CadenceState assigns these three unconditionally, and assigning a property
        # that a PSCustomObject does not have throws under ErrorActionPreference Stop.
        # The terminal block sits outside the worker try/catch, so a state file written
        # before these fields existed killed the worker exactly at the commit point:
        # every run from 2026-08-19T12:26Z on left status RUNNING with worker_pid set and
        # no finish, and was swept up by a recovery entry. Get-DefaultState already
        # carries all three; only the migration list had missed them.
        Ensure-StateProperty $state "event_eta_utc" $null
        Ensure-StateProperty $state "official_confirmation" $false
        Ensure-StateProperty $state "exact_timestamp" $false
        Ensure-StateProperty $state "wake_interval_seconds" $wakeIntervalSec
        Ensure-StateProperty $state "worker_process_started_at_utc" $null
        Ensure-StateProperty $state "worker_handoff_token_sha256" $null
        Ensure-StateProperty $state "worker_handoff_run_id" $null
        Ensure-StateProperty $state "worker_handoff_issued_at_utc" $null
        if ($legacyCadence) {
            $state.cadence_policy_version = $cadencePolicyVersion
            $state.cadence_stage = "SEARCH"
            $state.cadence_seconds = $searchIntervalSec
            $state.cadence_hours = 6
            $state.cadence_reason = "migrated_legacy_fixed_cadence"
            $state.next_interval_at_utc = Get-NextIntervalUtc -IntervalSec $searchIntervalSec
        }
        return $state
    } catch {
        throw "automation state unreadable: $($_.Exception.Message)"
    }
}

function Set-State($State) {
    $State.updated_at_utc = Get-UtcIso
    Write-JsonFile -Path $statePath -Payload $State
}

function Recover-StaleWorker($State) {
    if ([string]$State.status -notin @("RUNNING", "QUEUED_VISIBLE")) { return $State }
    if ($State.worker_pid) {
        $expectedProcessStartedAtUtc = Get-StateWorkerProcessStartedAtUtc $State
        if (Test-ProcessAlive $State.worker_pid $expectedProcessStartedAtUtc) { return $State }
    } elseif ([string]$State.status -ne "QUEUED_VISIBLE") {
        return $State
    }

    $recoveryReason = "worker_not_alive_recovered"
    $attemptId = [string]$State.last_attempt_id
    $existingTerminal = Get-TerminalLedgerAttempt -AttemptId $attemptId
    if ($null -ne $existingTerminal) {
        $State.status = [string]$existingTerminal.status
        $State.pending_retry = if ($null -ne $existingTerminal.pending_retry) { [bool]$existingTerminal.pending_retry } else { [string]$existingTerminal.status -ne "COMPLETE" }
        $State.last_finished_at_utc = if ($existingTerminal.finished_at_utc) { $existingTerminal.finished_at_utc } else { Get-UtcIso }
        $State.worker_pid = $null
        $State.worker_process_started_at_utc = $null
        if ($existingTerminal.next_interval_at_utc) { $State.next_interval_at_utc = $existingTerminal.next_interval_at_utc }
        if ($null -ne $existingTerminal.outcomes) { $State.outcomes = $existingTerminal.outcomes }
        $terminalErrors = @($existingTerminal.errors | ForEach-Object { [string]$_ } | Where-Object { $_ })
        $State.last_error = if ($terminalErrors.Count -gt 0) { $terminalErrors -join "; " } else { $null }
        Set-State $State
        if (Test-Path -LiteralPath $launchRecordPath) {
            try {
                $launch = Read-JsonFile -Path $launchRecordPath
                if ([string]$launch.attempt_id -eq $attemptId -or -not $launch.attempt_id) {
                    $launch.status = [string]$existingTerminal.status
                    $launch | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue $State.last_finished_at_utc -Force
                    $launch | Add-Member -NotePropertyName pending_retry -NotePropertyValue ([bool]$State.pending_retry) -Force
                    $launch | Add-Member -NotePropertyName next_interval_at_utc -NotePropertyValue $State.next_interval_at_utc -Force
                    Write-JsonFile -Path $launchRecordPath -Payload $launch
                }
            } catch {
                # The terminal ledger and reconciled state remain authoritative.
            }
        }
        return $State
    }
    $State.status = "RETRY_NEXT_INTERVAL"
    $State.pending_retry = $true
    $State.retry_count = [int]$State.retry_count + 1
    $State.last_finished_at_utc = Get-UtcIso
    $State.worker_pid = $null
    $State.worker_process_started_at_utc = $null
    $State.next_interval_at_utc = Get-NextIntervalUtc -State $State
    $State.last_error = if ($State.last_error) { ([string]$State.last_error) + "; " + $recoveryReason } else { $recoveryReason }

    # The terminal attempt row is the recovery commit record. Persist it before
    # clearing the durable worker identity so a crash cannot orphan RUNNING.
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = if ($attemptId) { $attemptId } else { "recovery_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") }
        status = "RETRY_NEXT_INTERVAL"
        recovery_reason = $recoveryReason
        pending_retry = $true
        next_interval_at_utc = $State.next_interval_at_utc
    })
    Set-State $State

    if (Test-Path -LiteralPath $launchRecordPath) {
        try {
            $launch = Read-JsonFile -Path $launchRecordPath
            if ([string]$launch.status -eq "RUNNING" -and ([string]$launch.attempt_id -eq $attemptId -or -not $launch.attempt_id)) {
                $launch.status = "RETRY_NEXT_INTERVAL"
                $launch | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue (Get-UtcIso) -Force
                $launch | Add-Member -NotePropertyName pending_retry -NotePropertyValue $true -Force
                $launch | Add-Member -NotePropertyName recovery_reason -NotePropertyValue $recoveryReason -Force
                $launch | Add-Member -NotePropertyName next_interval_at_utc -NotePropertyValue $State.next_interval_at_utc -Force
                Write-JsonFile -Path $launchRecordPath -Payload $launch
            }
        } catch {
            $State.last_error = ([string]$State.last_error) + "; launch_record_recovery_failed: " + $_.Exception.Message
            Set-State $State
        }
    }

    return $State
}

function Invoke-TrackLauncher([string]$Launcher, [string]$PlanPath) {
    # Child launchers use `exit` for their own contract. Run them in a separate
    # PowerShell process so that one track cannot terminate this orchestrator
    # before its final state, launch record, and retry ledger are written.
    $pwshExe = Resolve-PowerShellExecutable
    & $pwshExe -NoProfile -ExecutionPolicy Bypass -File $Launcher -PlanPath $PlanPath -VisibleWorker -ScheduledTick 2>&1 |
        ForEach-Object { Write-Host $_ }
    $exitCode = [int]$LASTEXITCODE
    return $exitCode
}

function Enter-SchedulerClaimTransaction([int]$TimeoutMs = 5000) {
    $lockPath = $schedulerClaimPath + ".transaction.lock"
    $dir = Split-Path -Parent $lockPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $deadline = [DateTime]::UtcNow.AddMilliseconds([math]::Max(0, $TimeoutMs))
    while ($true) {
        try {
            return [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
        } catch [System.IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) { return $null }
            Start-Sleep -Milliseconds 20
        }
    }
}

function Get-SchedulerClaimSnapshot {
    if (-not (Test-Path -LiteralPath $schedulerClaimPath -PathType Leaf)) {
        return [pscustomobject]@{ State = "ABSENT"; Reason = "claim_absent"; Claim = $null; Sha256 = $null }
    }
    $bytes = $null
    $sha = $null
    try {
        $bytes = [System.IO.File]::ReadAllBytes($schedulerClaimPath)
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try { $sha = [Convert]::ToHexString($hasher.ComputeHash($bytes)).ToLowerInvariant() } finally { $hasher.Dispose() }
        $raw = [System.Text.UTF8Encoding]::new($false, $true).GetString($bytes)
        $claim = ConvertFrom-Json -InputObject $raw -DateKind String -ErrorAction Stop
        if ([string]$claim.schema -cne "trading_mvp_listing_momentum_forward_automation_claim_v1") { throw "schema mismatch" }
        if ([string]::IsNullOrWhiteSpace([string]$claim.run_id)) { throw "run_id missing" }
        if ([string]$claim.ownership_token -cnotmatch '^[0-9a-fA-F]{32}$') { throw "ownership_token invalid" }
        $ownerPid = 0
        if (-not [int]::TryParse([string]$claim.pid, [ref]$ownerPid) -or $ownerPid -le 0) { throw "pid invalid" }
        if ([string]::IsNullOrWhiteSpace([string]$claim.claimed_at_utc)) { throw "claimed_at_utc missing" }
        [void][DateTimeOffset]::Parse([string]$claim.claimed_at_utc)

        $expectedStartedAt = $null
        if (
            $claim.PSObject.Properties.Name -contains "owner_process_started_at_utc" -and
            -not [string]::IsNullOrWhiteSpace([string]$claim.owner_process_started_at_utc)
        ) {
            $expectedStartedAt = [DateTimeOffset]::Parse([string]$claim.owner_process_started_at_utc).ToUniversalTime().UtcDateTime
        }
        try {
            $process = Get-Process -Id $ownerPid -ErrorAction Stop
        } catch {
            return [pscustomobject]@{ State = "STALE_DEAD"; Reason = "owner_pid_dead"; Claim = $claim; Sha256 = $sha }
        }
        if ($null -eq $expectedStartedAt) {
            return [pscustomobject]@{ State = "LIVE_UNKNOWN_IDENTITY"; Reason = "live_pid_without_start_identity"; Claim = $claim; Sha256 = $sha }
        }
        $actualStartedAt = $process.StartTime.ToUniversalTime()
        if ([math]::Abs(($actualStartedAt - $expectedStartedAt).TotalSeconds) -le 2) {
            return [pscustomobject]@{ State = "LIVE"; Reason = "owner_pid_and_start_match"; Claim = $claim; Sha256 = $sha }
        }
        return [pscustomobject]@{ State = "STALE_REUSED"; Reason = "owner_pid_start_mismatch"; Claim = $claim; Sha256 = $sha }
    } catch {
        return [pscustomobject]@{ State = "CORRUPT"; Reason = ("claim_unreadable_or_invalid: " + $_.Exception.Message); Claim = $null; Sha256 = $sha }
    }
}

function Test-SameSchedulerClaimSnapshot($First, $Second) {
    if ($null -eq $First -or $null -eq $Second -or $null -eq $First.Claim -or $null -eq $Second.Claim) { return $false }
    if ([string]$First.Sha256 -cne [string]$Second.Sha256) { return $false }
    foreach ($field in @("schema", "run_id", "ownership_token", "pid", "owner_process_started_at_utc", "claimed_at_utc")) {
        if ([string]$First.Claim.$field -cne [string]$Second.Claim.$field) { return $false }
    }
    return $true
}

function Recover-StaleSchedulerClaim(
    [scriptblock]$BeforeStaleClaimDoubleCheck = $null,
    [scriptblock]$BeforeStaleClaimArchiveMove = $null
) {
    $first = Get-SchedulerClaimSnapshot
    if ([string]$first.State -notin @("STALE_DEAD", "STALE_REUSED")) {
        return [pscustomobject]@{ Recovered = $false; Snapshot = $first; ArchivePath = $null }
    }
    if ($null -ne $BeforeStaleClaimDoubleCheck) { & $BeforeStaleClaimDoubleCheck }
    $second = Get-SchedulerClaimSnapshot
    if (
        [string]$second.State -notin @("STALE_DEAD", "STALE_REUSED") -or
        -not (Test-SameSchedulerClaimSnapshot -First $first -Second $second)
    ) {
        return [pscustomobject]@{ Recovered = $false; Snapshot = $second; ArchivePath = $null }
    }

    if (-not (Test-Path -LiteralPath $schedulerClaimArchiveDir)) {
        New-Item -ItemType Directory -Force -Path $schedulerClaimArchiveDir | Out-Null
    }
    $safeRunId = ([string]$first.Claim.run_id) -replace '[^A-Za-z0-9_.-]', '_'
    $archivePath = Join-Path $schedulerClaimArchiveDir ("stale." + $safeRunId + "." + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ") + "." + [guid]::NewGuid().ToString("N") + ".json")
    if ($null -ne $BeforeStaleClaimArchiveMove) { & $BeforeStaleClaimArchiveMove }
    try {
        [System.IO.File]::Move($schedulerClaimPath, $archivePath)
    } catch {
        return [pscustomobject]@{ Recovered = $false; Snapshot = (Get-SchedulerClaimSnapshot); ArchivePath = $null }
    }
    $archivedHash = $null
    try {
        $archivedBytes = [System.IO.File]::ReadAllBytes($archivePath)
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try { $archivedHash = [Convert]::ToHexString($hasher.ComputeHash($archivedBytes)).ToLowerInvariant() } finally { $hasher.Dispose() }
    } catch {
        $archivedHash = $null
    }
    if ([string]$archivedHash -cne [string]$second.Sha256) {
        $restored = $false
        if (-not (Test-Path -LiteralPath $schedulerClaimPath)) {
            try {
                [System.IO.File]::Move($archivePath, $schedulerClaimPath)
                $restored = $true
            } catch {
                $restored = $false
            }
        }
        try {
            Append-Ledger ([ordered]@{
                schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
                attempt_id = "scheduler_claim_recovery_race_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ")
                status = "STALE_CLAIM_RECOVERY_RACE_BLOCKED"
                expected_stale_claim_sha256 = [string]$second.Sha256
                moved_claim_sha256 = [string]$archivedHash
                replacement_restored = $restored
                preserved_path = if ($restored) { $schedulerClaimPath } else { $archivePath }
                detected_at_utc = Get-UtcIso
            })
        } catch {
            Write-Warning ("scheduler claim recovery race was blocked but ledger evidence failed: " + $_.Exception.Message)
        }
        return [pscustomobject]@{
            Recovered = $false
            Snapshot = (Get-SchedulerClaimSnapshot)
            ArchivePath = if (Test-Path -LiteralPath $archivePath) { $archivePath } else { $null }
        }
    }
    try {
        Append-Ledger ([ordered]@{
            schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
            attempt_id = "scheduler_claim_recovery_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ")
            status = "STALE_CLAIM_RECOVERED"
            recovery_reason = [string]$first.Reason
            stale_run_id = [string]$first.Claim.run_id
            stale_owner_pid = [int]$first.Claim.pid
            stale_owner_process_started_at_utc = $first.Claim.owner_process_started_at_utc
            stale_claim_sha256 = [string]$first.Sha256
            archive_path = $archivePath
            recovered_at_utc = Get-UtcIso
        })
    } catch {
        Write-Warning ("scheduler stale-claim archive succeeded but ledger evidence failed: " + $_.Exception.Message)
    }
    return [pscustomobject]@{ Recovered = $true; Snapshot = $first; ArchivePath = $archivePath }
}

function Acquire-SchedulerClaim(
    [scriptblock]$BeforeStaleClaimDoubleCheck = $null,
    [scriptblock]$BeforeStaleClaimArchiveMove = $null
) {
    $transaction = Enter-SchedulerClaimTransaction
    if ($null -eq $transaction) { return $null }
    try {
    $dir = Split-Path -Parent $schedulerClaimPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    for ($attempt = 0; $attempt -lt 2; $attempt++) {
        $stream = $null
        try {
            $ownershipToken = [Guid]::NewGuid().ToString("N")
            $claimedAt = Get-UtcIso
            $ownerProcessStartedAt = (Get-Process -Id $PID -ErrorAction Stop).StartTime.ToUniversalTime().ToString("o")
            $runId = "listing_momentum_scheduler_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ") + "_" + $ownershipToken.Substring(0, 8)
            $stream = [System.IO.File]::Open(
                $schedulerClaimPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            $payload = [ordered]@{
                schema = "trading_mvp_listing_momentum_forward_automation_claim_v1"
                pid = $PID
                run_id = $runId
                ownership_token = $ownershipToken
                owner_process_started_at_utc = $ownerProcessStartedAt
                claimed_at_utc = $claimedAt
                automation_id = "zolotyaylopata-listing-momentum-monitor"
            }
            $bytes = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush()
            return [pscustomobject]@{
                Stream = $stream
                Identity = [pscustomobject]$payload
            }
        } catch {
            if ($null -ne $stream) { $stream.Dispose() }
            if ($attempt -eq 0) {
                $recovery = Recover-StaleSchedulerClaim -BeforeStaleClaimDoubleCheck $BeforeStaleClaimDoubleCheck -BeforeStaleClaimArchiveMove $BeforeStaleClaimArchiveMove
                if ([bool]$recovery.Recovered) { continue }
            }
            return $null
        }
    }
    return $null
    } finally {
        $transaction.Dispose()
    }
}

function Add-SchedulerClaimReleaseEvidence($Expected, $Observed, [string]$Reason, [string[]]$MismatchedFields) {
    try {
        Append-Ledger ([ordered]@{
            schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
            attempt_id = "claim_release_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ")
            status = "RETRY_NEXT_INTERVAL"
            reason = $Reason
            pending_retry = $true
            mismatched_fields = @($MismatchedFields)
            expected_claim_identity = $Expected
            observed_claim_identity = $Observed
            recorded_at_utc = Get-UtcIso
        })
    } catch {
        Write-Warning ("failed to persist scheduler claim release evidence: " + $_.Exception.Message)
    }
}

function Release-SchedulerClaim($Claim) {
    if ($null -eq $Claim) { return }
    $expected = $Claim.Identity
    try {
        if ($Claim.Stream) { $Claim.Stream.Dispose() }
    } catch {
        Add-SchedulerClaimReleaseEvidence -Expected $expected -Observed $null -Reason "scheduler_claim_release_stream_close_failed" -MismatchedFields @("stream")
        return
    }
    if ($null -eq $expected) {
        Add-SchedulerClaimReleaseEvidence -Expected $null -Observed $null -Reason "scheduler_claim_release_identity_missing" -MismatchedFields @("identity")
        return
    }
    $transaction = Enter-SchedulerClaimTransaction
    if ($null -eq $transaction) {
        Add-SchedulerClaimReleaseEvidence -Expected $expected -Observed $null -Reason "scheduler_claim_release_transaction_lock_busy" -MismatchedFields @("transaction_lock")
        return
    }
    try {
    if (-not (Test-Path -LiteralPath $schedulerClaimPath -PathType Leaf)) {
        Add-SchedulerClaimReleaseEvidence -Expected $expected -Observed $null -Reason "scheduler_claim_release_path_missing" -MismatchedFields @("path")
        return
    }

    $releaseStream = $null
    try {
        $releaseStream = [System.IO.File]::Open(
            $schedulerClaimPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Delete
        )
        $reader = [System.IO.StreamReader]::new(
            $releaseStream,
            [System.Text.UTF8Encoding]::new($false, $true),
            $true,
            1024,
            $true
        )
        try {
            $raw = $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
        $observed = ConvertFrom-Json -InputObject $raw -DateKind String -ErrorAction Stop
        $mismatched = [System.Collections.Generic.List[string]]::new()
        foreach ($field in @("ownership_token", "run_id", "pid", "owner_process_started_at_utc")) {
            if (
                -not ($observed.PSObject.Properties.Name -contains $field) -or
                ([string]$observed.$field -cne [string]$expected.$field)
            ) {
                $mismatched.Add($field)
            }
        }
        if ($mismatched.Count -gt 0) {
            Add-SchedulerClaimReleaseEvidence -Expected $expected -Observed $observed -Reason "scheduler_claim_release_identity_mismatch" -MismatchedFields @($mismatched)
            return
        }
        [System.IO.File]::Delete($schedulerClaimPath)
    } catch {
        Add-SchedulerClaimReleaseEvidence -Expected $expected -Observed $null -Reason "scheduler_claim_release_unreadable_or_locked" -MismatchedFields @("claim")
    } finally {
        if ($null -ne $releaseStream) { $releaseStream.Dispose() }
    }
    } finally {
        $transaction.Dispose()
    }
}

function Invoke-TrackPreflight([string]$Name, [string]$Launcher, [string]$PlanPath, [switch]$AllowClaimRecovery) {
    $result = [ordered]@{
        track = $Name
        ok = $false
        status = "PREFLIGHT_FAILED"
        reasons = @()
        plan_id = $null
        plan_hash = $null
        plan_file_sha256 = $null
        gate_status = $null
    }
    try {
        if ($AllowClaimRecovery) {
            $output = & $Launcher -PlanPath $PlanPath -PreflightOnly -ScheduledTick -Json 2>&1 | Out-String
        } else {
            $output = & $Launcher -PlanPath $PlanPath -PreflightOnly -Json 2>&1 | Out-String
        }
        if ($LASTEXITCODE -ne 0) { throw "launcher preflight exit $LASTEXITCODE" }
        $payload = $output | ConvertFrom-Json
        $result.ok = [bool]$payload.ok
        $result.status = if ($result.ok) { "READY" } else { "DEFERRED" }
        $result.reasons = @($payload.reasons)
        $result.plan_id = [string]$payload.plan_id
        $result.plan_hash = [string]$payload.plan_hash
        $result.plan_file_sha256 = [string]$payload.plan_file_sha256
        $result.gate_status = [string]$payload.gate_status
    } catch {
        $result.reasons = @("$($_.Exception.GetType().Name): $($_.Exception.Message)")
    }
    return $result
}

function Invoke-AutomationPreflight([switch]$AllowClaimRecovery) {
    $v2 = Invoke-TrackPreflight -Name "mexc_gate_v2" -Launcher $v2Launcher -PlanPath $V2PlanPath -AllowClaimRecovery:$AllowClaimRecovery
    $expansion = Invoke-TrackPreflight -Name "binance_bybit_okx_bitget_expansion" -Launcher $expansionLauncher -PlanPath $ExpansionPlanPath -AllowClaimRecovery:$AllowClaimRecovery
    return [ordered]@{
        ok = ([bool]$v2.ok -or [bool]$expansion.ok)
        tracks = @($v2, $expansion)
        checked_at_utc = Get-UtcIso
        cadence_policy_version = $cadencePolicyVersion
        wake_interval_seconds = $wakeIntervalSec
        cadence_stage = if (Test-Path -LiteralPath $statePath) { [string](Get-State).cadence_stage } else { "SEARCH" }
        next_interval_at_utc = if (Test-Path -LiteralPath $statePath) { (Get-State).next_interval_at_utc } else { Get-NextIntervalUtc -IntervalSec $searchIntervalSec }
    }
}

function Update-DeferredState($State, [string]$Reason, $Preflight, [string]$AttemptId = $null) {
    $State.status = "RETRY_NEXT_INTERVAL"
    $State.pending_retry = $true
    $State.retry_count = [int]$State.retry_count + 1
    $State.next_interval_at_utc = Get-NextIntervalUtc -State $State
    $State.last_error = $Reason
    $State.outcomes = [ordered]@{
        mexc_gate_v2 = "DEFERRED"
        binance_bybit_okx_bitget_expansion = "DEFERRED"
    }
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = if ($AttemptId) { $AttemptId } else { "deferred_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") }
        status = "RETRY_NEXT_INTERVAL"
        reason = $Reason
        pending_retry = $true
        next_interval_at_utc = $State.next_interval_at_utc
        preflight = $Preflight
    })
    Set-State $State
}

function Get-StatusPayload {
    $state = Get-State
    $initialDecision = Resolve-CadenceDecision $state
    $launch = $null
    if (Test-Path -LiteralPath $launchRecordPath) {
        try { $launch = Read-JsonFile -Path $launchRecordPath } catch { $launch = @{ status = "UNREADABLE" } }
    }
    $workerAlive = Test-ProcessAlive $state.worker_pid (Get-StateWorkerProcessStartedAtUtc $state)
    return [ordered]@{
        status = [string]$state.status
        automation_id = [string]$state.automation_id
        cadence_policy_version = [string]$state.cadence_policy_version
        cadence_stage = [string]$state.cadence_stage
        cadence_seconds = [int]$state.cadence_seconds
        cadence_hours = [double]$state.cadence_hours
        cadence_reason = [string]$state.cadence_reason
        wake_interval_seconds = $wakeIntervalSec
        event_eta_utc = $state.event_eta_utc
        pending_retry = [bool]$state.pending_retry
        retry_count = [int]$state.retry_count
        attempt_count = [int]$state.attempt_count
        next_interval_at_utc = $state.next_interval_at_utc
        worker_pid = $state.worker_pid
        worker_alive = $workerAlive
        outcomes = $state.outcomes
        last_error = $state.last_error
        launch_record = $launch
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
}

if ($Status) {
    $payload = Get-StatusPayload
    if ($Json) { $payload | ConvertTo-Json -Depth 20 } else {
        Write-Host "=== Listing Momentum automation status ===" -ForegroundColor Cyan
        $payload | ConvertTo-Json -Depth 20
    }
    exit 0
}

if ($PreflightOnly) {
    $preflight = Invoke-AutomationPreflight -AllowClaimRecovery:$ScheduledTick
    if ($Json) { $preflight | ConvertTo-Json -Depth 20 } else {
        Write-Host "=== Listing Momentum automation preflight ===" -ForegroundColor Cyan
        $preflight | ConvertTo-Json -Depth 20
    }
    exit 0
}

if (-not $ScheduledTick) {
    $payload = [ordered]@{
        ok = $false
        status = "BLOCKED"
        reasons = @("ScheduledTick_required_for_execution")
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 8 } else {
        Write-Host "automation execution requires ScheduledTick handoff" -ForegroundColor Red
    }
    exit 1
}

if ($VisibleWorker) {
    $handoffLaunchMutex = Enter-VisibleLaunchMutex -WaitMilliseconds 15000
    if ($null -eq $handoffLaunchMutex) {
        $payload = [ordered]@{ ok = $false; status = "BLOCKED"; reasons = @("worker_handoff_attach_timeout") }
        if ($Json) { $payload | ConvertTo-Json -Depth 8 } else { $payload | ConvertTo-Json -Depth 8 }
        exit 2
    }
    try { $handoffState = Get-State } finally { Exit-VisibleLaunchMutex $handoffLaunchMutex }
    $handoffValid = (
        -not [string]::IsNullOrWhiteSpace($WorkerHandoffToken) -and
        -not [string]::IsNullOrWhiteSpace($WorkerHandoffRunId) -and
        [string]$handoffState.status -in @("QUEUED_VISIBLE", "RUNNING") -and
        [string]$handoffState.worker_handoff_run_id -ceq $WorkerHandoffRunId -and
        [string]$handoffState.worker_handoff_token_sha256 -ceq (Get-TextSha256 $WorkerHandoffToken)
    )
    if (-not $handoffValid) {
        $payload = [ordered]@{ ok = $false; status = "BLOCKED"; reasons = @("worker_handoff_invalid_or_missing") }
        if ($Json) { $payload | ConvertTo-Json -Depth 8 } else { $payload | ConvertTo-Json -Depth 8 }
        exit 2
    }
    $workerPreflight = Invoke-AutomationPreflight -AllowClaimRecovery
    if (-not $workerPreflight.ok) {
        $state = Get-State
        $reason = "preflight_failed: " + ((@($workerPreflight.tracks | ForEach-Object { @($_.reasons) }) | ForEach-Object { [string]$_ }) -join "; ")
        Update-DeferredState -State $state -Reason $reason -Preflight $workerPreflight
        $payload = [ordered]@{
            status = "RETRY_NEXT_INTERVAL"
            pending_retry = $true
            next_interval_at_utc = $state.next_interval_at_utc
            preflight = $workerPreflight
        }
        if ($Json) { $payload | ConvertTo-Json -Depth 20 } else {
            Write-Host "visible automation worker preflight failed" -ForegroundColor Red
            $payload | ConvertTo-Json -Depth 20
        }
        exit 1
    }
    $state = $handoffState
    $attemptId = [string]$WorkerHandoffRunId
    $startedAt = Get-UtcIso
    $outcomes = [ordered]@{}
    $errors = [System.Collections.Generic.List[string]]::new()
    $launchRecord = [ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_launch_v1"
        status = "RUNNING"
        automation_id = [string]$state.automation_id
        attempt_id = $attemptId
        visible_terminal_pid = $PID
        started_at_utc = $startedAt
        cadence_policy_version = $cadencePolicyVersion
        cadence_stage = [string]$state.cadence_stage
        cadence_seconds = [int]$state.cadence_seconds
        cadence_hours = [double]$state.cadence_hours
        wake_interval_seconds = $wakeIntervalSec
        v2_plan_path = $V2PlanPath
        expansion_plan_path = $ExpansionPlanPath
        research_only = $true
        public_data_only = $true
        retry_policy = "failed_or_deferred_track_retries_on_next_scheduled_interval"
    }
    $state.status = "RUNNING"
    $state.pending_retry = [bool]$state.pending_retry
    $state.attempt_count = [int]$state.attempt_count + 1
    $state.last_attempt_id = $attemptId
    $state.last_started_at_utc = $startedAt
    $state.worker_pid = $PID
    $state.worker_process_started_at_utc = Get-ProcessStartedAtUtc -ProcessId $PID
    $state.worker_handoff_token_sha256 = $null
    $state.worker_handoff_run_id = $null
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = $attemptId
        status = "RUNNING"
        started_at_utc = $startedAt
        visible_terminal_pid = $PID
        pending_retry_before_attempt = [bool]$state.pending_retry
    })
    Set-State $state
    Write-JsonFile -Path $launchRecordPath -Payload $launchRecord

    try {
        Write-Host "=== Listing Momentum scheduled automation (visible) ===" -ForegroundColor Cyan
        Write-Host ("cadence stage: " + [string]$state.cadence_stage + "; actual interval: " + [int]$state.cadence_seconds + " sec; scheduler wake: " + $wakeIntervalSec + " sec")

        $v2Preflight = Invoke-TrackPreflight -Name "mexc_gate_v2" -Launcher $v2Launcher -PlanPath $V2PlanPath -AllowClaimRecovery
        if ($v2Preflight.ok) {
            Write-Host "--- MEXC + Gate v2 tick ---" -ForegroundColor Cyan
            $v2Exit = Invoke-TrackLauncher -Launcher $v2Launcher -PlanPath $V2PlanPath
            $outcomes.mexc_gate_v2 = if ($v2Exit -eq 0) { "COMPLETE" } else { "FAILED_RETRY_NEXT_INTERVAL" }
            if ($v2Exit -ne 0) { $errors.Add("mexc_gate_v2_exit_$v2Exit") }
        } else {
            $outcomes.mexc_gate_v2 = "DEFERRED_RETRY_NEXT_INTERVAL"
            $errors.Add("mexc_gate_v2_preflight: " + (@($v2Preflight.reasons) -join ","))
        }

        $expansionPreflight = Invoke-TrackPreflight -Name "binance_bybit_okx_bitget_expansion" -Launcher $expansionLauncher -PlanPath $ExpansionPlanPath -AllowClaimRecovery
        if ($expansionPreflight.ok) {
            Write-Host "--- Binance + Bybit + OKX + Bitget expansion tick ---" -ForegroundColor Cyan
            $expansionExit = Invoke-TrackLauncher -Launcher $expansionLauncher -PlanPath $ExpansionPlanPath
            $outcomes.binance_bybit_okx_bitget_expansion = if ($expansionExit -eq 0) { "COMPLETE" } else { "FAILED_RETRY_NEXT_INTERVAL" }
            if ($expansionExit -ne 0) { $errors.Add("expansion_exit_$expansionExit") }
        } else {
            $outcomes.binance_bybit_okx_bitget_expansion = "DEFERRED_RETRY_NEXT_INTERVAL"
            $errors.Add("expansion_preflight: " + (@($expansionPreflight.reasons) -join ","))
        }
    } catch {
        $errors.Add("automation_worker_exception: $($_.Exception.GetType().Name): $($_.Exception.Message)")
        ("worker failed at " + (Get-UtcIso) + "`n" + ($_ | Out-String)) | Set-Content -LiteralPath $workerErrorLog -Encoding UTF8
    }

    $finishedAt = Get-UtcIso
    $hasFailure = $errors.Count -gt 0
    $hasComplete = @($outcomes.Values | Where-Object { $_ -eq "COMPLETE" }).Count -gt 0
    $finalStatus = if (-not $hasFailure) { "COMPLETE" } elseif ($hasComplete) { "PARTIAL_RETRY_NEXT_INTERVAL" } else { "RETRY_NEXT_INTERVAL" }
    $state.status = $finalStatus
    $state.pending_retry = $hasFailure
    if ($hasFailure) { $state.retry_count = [int]$state.retry_count + 1 }
    $finalDecision = Resolve-CombinedCadence $state
    $state = Set-CadenceState -State $state -Decision $finalDecision
    $state.last_finished_at_utc = $finishedAt
    $state.worker_pid = $null
    $state.worker_process_started_at_utc = $null
    $state.outcomes = $outcomes
    $state.last_error = if ($hasFailure) { $errors -join "; " } else { $null }
    # Terminal evidence is the commit record. If this append fails, the durable
    # state and launch record remain RUNNING with worker identity for recovery.
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = $attemptId
        status = $finalStatus
        started_at_utc = $startedAt
        finished_at_utc = $finishedAt
        outcomes = $outcomes
        errors = @($errors)
        pending_retry = $hasFailure
        next_interval_at_utc = $state.next_interval_at_utc
        cadence_stage = [string]$state.cadence_stage
        cadence_seconds = [int]$state.cadence_seconds
    })
    Set-State $state
    $launchRecord.status = $finalStatus
    $launchRecord.finished_at_utc = $finishedAt
    $launchRecord.outcomes = $outcomes
    $launchRecord.errors = @($errors)
    $launchRecord.pending_retry = $hasFailure
    $launchRecord.next_interval_at_utc = $state.next_interval_at_utc
    $launchRecord.cadence_stage = [string]$state.cadence_stage
    $launchRecord.cadence_seconds = [int]$state.cadence_seconds
    $launchRecord.cadence_reason = [string]$state.cadence_reason
    $launchRecord | Add-Member -NotePropertyName exit_code -NotePropertyValue $(if ($hasFailure) { 1 } else { 0 }) -Force
    Write-JsonFile -Path $launchRecordPath -Payload $launchRecord
    Write-Host ("automation status: " + $finalStatus)
    Write-Host ("next interval: " + $state.next_interval_at_utc)
    if ($errors.Count -gt 0) { Write-Host ("deferred tracks: " + ($errors -join "; ")) -ForegroundColor Yellow }
    exit $(if ($hasFailure) { 1 } else { 0 })
}

$state = Get-State
$now = [DateTimeOffset]::UtcNow
if ($state.worker_pid -and (Test-ProcessAlive $state.worker_pid (Get-StateWorkerProcessStartedAtUtc $state))) {
    $payload = [ordered]@{
        status = "ALREADY_RUNNING"
        automation_id = [string]$state.automation_id
        worker_pid = $state.worker_pid
        next_interval_at_utc = $state.next_interval_at_utc
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 10 } else { $payload | ConvertTo-Json -Depth 10 }
    exit 0
}
if ($state.next_interval_at_utc) {
    try {
        $next = [DateTimeOffset]::Parse([string]$state.next_interval_at_utc)
        if ($now -lt $next) {
            $payload = [ordered]@{
                status = "NOT_DUE"
                automation_id = [string]$state.automation_id
                pending_retry = [bool]$state.pending_retry
                next_interval_at_utc = $state.next_interval_at_utc
                status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
            }
            if ($Json) { $payload | ConvertTo-Json -Depth 10 } else { $payload | ConvertTo-Json -Depth 10 }
            exit 0
        }
    } catch {
        $state.last_error = "invalid next_interval_at_utc; treating this fire as due"
    }
}

# Plan/gate preflight is read-only with respect to scheduler state and claims.
# Negative preflight must preserve stale evidence for a later valid fire.
$preflight = Invoke-AutomationPreflight -AllowClaimRecovery
$readyCount = @($preflight.tracks | Where-Object { $_.ok }).Count
if ($readyCount -eq 0) {
    $reason = "preflight_failed: " + ((@($preflight.tracks | ForEach-Object { @($_.reasons) }) | ForEach-Object { [string]$_ }) -join "; ")
    Update-DeferredState -State $state -Reason $reason -Preflight $preflight
    $payload = [ordered]@{
        status = "RETRY_NEXT_INTERVAL"
        automation_id = [string]$state.automation_id
        pending_retry = $true
        next_interval_at_utc = $state.next_interval_at_utc
        preflight = $preflight
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 20 } else { $payload | ConvertTo-Json -Depth 20 }
    exit 1
}

$claimStream = Acquire-SchedulerClaim
if ($null -eq $claimStream) {
    $payload = [ordered]@{
        status = "DEFERRED_NEXT_INTERVAL"
        automation_id = [string]$state.automation_id
        reason = "scheduler_claim_exists"
        pending_retry = [bool]$state.pending_retry
        next_interval_at_utc = $state.next_interval_at_utc
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 10 } else { $payload | ConvertTo-Json -Depth 10 }
    exit 0
}

$outerLaunchMutex = Enter-VisibleLaunchMutex -WaitMilliseconds 0
if ($null -eq $outerLaunchMutex) {
    Release-SchedulerClaim -Claim $claimStream
    $payload = [ordered]@{ status = "ALREADY_RUNNING"; automation_id = [string]$state.automation_id; reason = "visible_launch_in_progress"; pending_retry = [bool]$state.pending_retry; next_interval_at_utc = $state.next_interval_at_utc }
    if ($Json) { $payload | ConvertTo-Json -Depth 10 } else { $payload | ConvertTo-Json -Depth 10 }
    exit 0
}

# Scheduler claim + launch mutex serialize stale recovery with handoff attach.
$state = Recover-StaleWorker -State $state

try {
    $handoffToken = [string]$claimStream.Identity.ownership_token
    $handoffRunId = [string]$claimStream.Identity.run_id
    try {
        $queuedAt = Get-UtcIso
        $nextIntervalAtUtc = Get-NextIntervalUtc -State $state
        Append-Ledger ([ordered]@{
            schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
            attempt_id = $handoffRunId
            status = "QUEUED_VISIBLE"
            queued_at_utc = $queuedAt
            pending_retry_before_attempt = [bool]$state.pending_retry
            next_interval_at_utc = $nextIntervalAtUtc
        })
        $state.status = "QUEUED_VISIBLE"
        $state.last_attempt_id = $handoffRunId
        $state.worker_handoff_token_sha256 = Get-TextSha256 $handoffToken
        $state.worker_handoff_run_id = $handoffRunId
        $state.worker_handoff_issued_at_utc = $queuedAt
        $state.next_interval_at_utc = $nextIntervalAtUtc
        Set-State $state
        $pwshExe = Resolve-PowerShellExecutable
        $childArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -VisibleWorker -ScheduledTick -WorkerHandoffToken `"$handoffToken`" -WorkerHandoffRunId `"$handoffRunId`" -V2PlanPath `"$V2PlanPath`" -ExpansionPlanPath `"$ExpansionPlanPath`""
        $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
        $terminalProcessStartedAtUtc = Get-ProcessStartedAtUtc -ProcessId $terminal.Id
    } catch {
        Update-DeferredState -State $state -Reason ("visible_worker_start_failed: " + $_.Exception.Message) -Preflight $preflight -AttemptId $handoffRunId
        $payload = [ordered]@{
            status = "DEFERRED_NEXT_INTERVAL"
            automation_id = [string]$state.automation_id
            pending_retry = $true
            next_interval_at_utc = $state.next_interval_at_utc
            reason = $state.last_error
            preflight = $preflight
            status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
        }
        if ($Json) { $payload | ConvertTo-Json -Depth 20 } else { $payload | ConvertTo-Json -Depth 20 }
        exit 1
    }
    $state.worker_pid = $terminal.Id
    $state.worker_process_started_at_utc = $terminalProcessStartedAtUtc
    $state.status = "RUNNING"
    Set-State $state
    $payload = [ordered]@{
        status = "VISIBLE_TERMINAL_LAUNCHED"
        automation_id = [string]$state.automation_id
        visible_terminal_pid = $terminal.Id
        pending_retry_before_attempt = [bool]$state.pending_retry
        next_interval_at_utc = $state.next_interval_at_utc
        preflight = $preflight
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
        launch_record_path = $launchRecordPath
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 20 } else {
        Write-Host ("visible automation terminal launched (pid " + $terminal.Id + ")") -ForegroundColor Green
        Write-Host ("status: " + $payload.status_command)
    }
} finally {
    Release-SchedulerClaim -Claim $claimStream
    Exit-VisibleLaunchMutex $outerLaunchMutex
}
exit 0
