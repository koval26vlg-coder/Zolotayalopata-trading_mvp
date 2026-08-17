param(
    [string]$V2PlanPath = "",
    [string]$ExpansionPlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker,
    [switch]$ScheduledTick,
    [string]$StatePathOverride = "",
    [string]$LedgerPathOverride = "",
    [string]$SchedulerClaimPathOverride = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultV2PlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-monitor-planonly-20260817-v2.json"
$defaultExpansionPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-expansion-planonly-20260817.json"
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
$cadenceHours = 6

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
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
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

function Get-UtcIso {
    return (Get-Date).ToUniversalTime().ToString("o")
}

function Get-NextIntervalUtc {
    $localNow = Get-Date
    $block = [math]::Floor($localNow.Hour / $cadenceHours)
    $nextLocal = $localNow.Date.AddHours(($block + 1) * $cadenceHours)
    if ($nextLocal -le $localNow) { $nextLocal = $nextLocal.AddHours($cadenceHours) }
    return [TimeZoneInfo]::ConvertTimeToUtc($nextLocal).ToString("o")
}

function Test-ProcessAlive([Nullable[int]]$ProcessId) {
    if (-not $ProcessId) { return $false }
    try {
        $process = Get-Process -Id ([int]$ProcessId) -ErrorAction Stop
        return $null -ne $process
    } catch {
        return $false
    }
}

function Get-DefaultState {
    return [ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_state_v1"
        automation_id = "zolotyaylopata-listing-momentum-monitor"
        cadence_hours = $cadenceHours
        status = "IDLE"
        pending_retry = $false
        retry_count = 0
        attempt_count = 0
        next_interval_at_utc = $null
        last_attempt_id = $null
        last_started_at_utc = $null
        last_finished_at_utc = $null
        worker_pid = $null
        outcomes = [ordered]@{}
        last_error = $null
    }
}

function Get-State {
    if (-not (Test-Path -LiteralPath $statePath)) { return Get-DefaultState }
    try {
        $state = Read-JsonFile -Path $statePath
        if ([string]$state.schema -ne "trading_mvp_listing_momentum_forward_automation_state_v1") {
            throw "automation state schema mismatch"
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

function Acquire-SchedulerClaim {
    $dir = Split-Path -Parent $schedulerClaimPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $schedulerClaimPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $payload = [ordered]@{
            schema = "trading_mvp_listing_momentum_forward_automation_claim_v1"
            pid = $PID
            claimed_at_utc = Get-UtcIso
            automation_id = "zolotyaylopata-listing-momentum-monitor"
        }
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        return $stream
    } catch {
        if ($null -ne $stream) { $stream.Dispose() }
        Remove-Item -LiteralPath $schedulerClaimPath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Release-SchedulerClaim($Stream) {
    if ($null -ne $Stream) {
        $Stream.Dispose()
        Remove-Item -LiteralPath $schedulerClaimPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-TrackPreflight([string]$Name, [string]$Launcher, [string]$PlanPath) {
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
        $output = & $Launcher -PlanPath $PlanPath -PreflightOnly -Json 2>&1 | Out-String
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

function Invoke-AutomationPreflight {
    $v2 = Invoke-TrackPreflight -Name "mexc_gate_v2" -Launcher $v2Launcher -PlanPath $V2PlanPath
    $expansion = Invoke-TrackPreflight -Name "binance_bybit_okx_bitget_expansion" -Launcher $expansionLauncher -PlanPath $ExpansionPlanPath
    return [ordered]@{
        ok = ([bool]$v2.ok -or [bool]$expansion.ok)
        tracks = @($v2, $expansion)
        checked_at_utc = Get-UtcIso
        cadence_hours = $cadenceHours
        next_interval_at_utc = Get-NextIntervalUtc
    }
}

function Update-DeferredState($State, [string]$Reason, $Preflight) {
    $State.status = "RETRY_NEXT_INTERVAL"
    $State.pending_retry = $true
    $State.retry_count = [int]$State.retry_count + 1
    $State.next_interval_at_utc = Get-NextIntervalUtc
    $State.last_error = $Reason
    $State.outcomes = [ordered]@{
        mexc_gate_v2 = "DEFERRED"
        binance_bybit_okx_bitget_expansion = "DEFERRED"
    }
    Set-State $State
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = "deferred_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        status = "RETRY_NEXT_INTERVAL"
        reason = $Reason
        pending_retry = $true
        next_interval_at_utc = $State.next_interval_at_utc
        preflight = $Preflight
    })
}

function Get-StatusPayload {
    $state = Get-State
    $launch = $null
    if (Test-Path -LiteralPath $launchRecordPath) {
        try { $launch = Read-JsonFile -Path $launchRecordPath } catch { $launch = @{ status = "UNREADABLE" } }
    }
    $workerAlive = Test-ProcessAlive $state.worker_pid
    return [ordered]@{
        status = [string]$state.status
        automation_id = [string]$state.automation_id
        cadence_hours = [int]$state.cadence_hours
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
    $preflight = Invoke-AutomationPreflight
    if ($Json) { $preflight | ConvertTo-Json -Depth 20 } else {
        Write-Host "=== Listing Momentum automation preflight ===" -ForegroundColor Cyan
        $preflight | ConvertTo-Json -Depth 20
    }
    exit 0
}

if ($VisibleWorker) {
    $state = Get-State
    $attemptId = "listing_momentum_automation_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
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
        cadence_hours = $cadenceHours
        v2_plan_path = $V2PlanPath
        expansion_plan_path = $ExpansionPlanPath
        research_only = $true
        public_data_only = $true
        retry_policy = "failed_or_deferred_track_retries_on_next_scheduled_interval"
    }
    Write-JsonFile -Path $launchRecordPath -Payload $launchRecord
    $state.status = "RUNNING"
    $state.pending_retry = [bool]$state.pending_retry
    $state.attempt_count = [int]$state.attempt_count + 1
    $state.last_attempt_id = $attemptId
    $state.last_started_at_utc = $startedAt
    $state.worker_pid = $PID
    Set-State $state
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = $attemptId
        status = "RUNNING"
        started_at_utc = $startedAt
        visible_terminal_pid = $PID
        pending_retry_before_attempt = [bool]$state.pending_retry
    })

    try {
        Write-Host "=== Listing Momentum scheduled automation (visible) ===" -ForegroundColor Cyan
        Write-Host "cadence: every $cadenceHours hours; failed/deferred track is retried on next interval"

        $v2Preflight = Invoke-TrackPreflight -Name "mexc_gate_v2" -Launcher $v2Launcher -PlanPath $V2PlanPath
        if ($v2Preflight.ok) {
            Write-Host "--- MEXC + Gate v2 tick ---" -ForegroundColor Cyan
            & $v2Launcher -PlanPath $V2PlanPath -VisibleWorker
            $v2Exit = $LASTEXITCODE
            $outcomes.mexc_gate_v2 = if ($v2Exit -eq 0) { "COMPLETE" } else { "FAILED_RETRY_NEXT_INTERVAL" }
            if ($v2Exit -ne 0) { $errors.Add("mexc_gate_v2_exit_$v2Exit") }
        } else {
            $outcomes.mexc_gate_v2 = "DEFERRED_RETRY_NEXT_INTERVAL"
            $errors.Add("mexc_gate_v2_preflight: " + (@($v2Preflight.reasons) -join ","))
        }

        $expansionPreflight = Invoke-TrackPreflight -Name "binance_bybit_okx_bitget_expansion" -Launcher $expansionLauncher -PlanPath $ExpansionPlanPath
        if ($expansionPreflight.ok) {
            Write-Host "--- Binance + Bybit + OKX + Bitget expansion tick ---" -ForegroundColor Cyan
            & $expansionLauncher -PlanPath $ExpansionPlanPath -VisibleWorker
            $expansionExit = $LASTEXITCODE
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
    $state.next_interval_at_utc = Get-NextIntervalUtc
    $state.last_finished_at_utc = $finishedAt
    $state.worker_pid = $null
    $state.outcomes = $outcomes
    $state.last_error = if ($hasFailure) { $errors -join "; " } else { $null }
    Set-State $state
    $launchRecord.status = $finalStatus
    $launchRecord.finished_at_utc = $finishedAt
    $launchRecord.outcomes = $outcomes
    $launchRecord.errors = @($errors)
    $launchRecord.pending_retry = $hasFailure
    $launchRecord.next_interval_at_utc = $state.next_interval_at_utc
    $launchRecord | Add-Member -NotePropertyName exit_code -NotePropertyValue $(if ($hasFailure) { 1 } else { 0 }) -Force
    Write-JsonFile -Path $launchRecordPath -Payload $launchRecord
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
    })
    Write-Host ("automation status: " + $finalStatus)
    Write-Host ("next interval: " + $state.next_interval_at_utc)
    if ($errors.Count -gt 0) { Write-Host ("deferred tracks: " + ($errors -join "; ")) -ForegroundColor Yellow }
    exit $(if ($hasFailure) { 1 } else { 0 })
}

$state = Get-State
$now = [DateTimeOffset]::UtcNow
if ($state.worker_pid -and (Test-ProcessAlive $state.worker_pid)) {
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

$claimStream = Acquire-SchedulerClaim
if ($null -eq $claimStream) {
    $payload = [ordered]@{
        status = "DEFERRED_NEXT_INTERVAL"
        automation_id = [string]$state.automation_id
        reason = "scheduler_claim_exists"
        pending_retry = $true
        next_interval_at_utc = Get-NextIntervalUtc
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
    $state.status = "RETRY_NEXT_INTERVAL"
    $state.pending_retry = $true
    $state.retry_count = [int]$state.retry_count + 1
    $state.next_interval_at_utc = $payload.next_interval_at_utc
    $state.last_error = "scheduler_claim_exists"
    Set-State $state
    Append-Ledger ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_automation_attempt_v1"
        attempt_id = "claim_deferred_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        status = "RETRY_NEXT_INTERVAL"
        reason = "scheduler_claim_exists"
        next_interval_at_utc = $state.next_interval_at_utc
    })
    if ($Json) { $payload | ConvertTo-Json -Depth 10 } else { $payload | ConvertTo-Json -Depth 10 }
    exit 0
}

try {
    $preflight = Invoke-AutomationPreflight
    $readyCount = @($preflight.tracks | Where-Object { $_.ok }).Count
    if ($PreflightOnly) {
        if ($Json) { $preflight | ConvertTo-Json -Depth 20 } else { $preflight | ConvertTo-Json -Depth 20 }
        exit 0
    }
    if ($readyCount -eq 0) {
        Update-DeferredState -State $state -Reason "no_track_ready_for_this_interval" -Preflight $preflight
        $payload = [ordered]@{
            status = "DEFERRED_NEXT_INTERVAL"
            automation_id = [string]$state.automation_id
            pending_retry = $true
            next_interval_at_utc = $state.next_interval_at_utc
            preflight = $preflight
            status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
        }
        if ($Json) { $payload | ConvertTo-Json -Depth 20 } else { $payload | ConvertTo-Json -Depth 20 }
        exit 0
    }

    $state.status = "QUEUED_VISIBLE"
    $state.next_interval_at_utc = Get-NextIntervalUtc
    Set-State $state
    try {
        $pwshExe = Resolve-PowerShellExecutable
        $childArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -VisibleWorker -ScheduledTick -V2PlanPath `"$V2PlanPath`" -ExpansionPlanPath `"$ExpansionPlanPath`""
        $terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
    } catch {
        Update-DeferredState -State $state -Reason ("visible_worker_start_failed: " + $_.Exception.Message) -Preflight $preflight
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
        exit 0
    }
    $state.worker_pid = $terminal.Id
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
    Release-SchedulerClaim -Stream $claimStream
}
exit 0
