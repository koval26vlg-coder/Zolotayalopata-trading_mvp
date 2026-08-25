param(
    [string]$PlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker,
    [switch]$ScheduledTick,
    [switch]$CurrentRunPointerTestOnly,
    [string]$CurrentRunPointerPathOverride = "",
    [string]$CurrentRunPointerPayloadPath = "",
    [string]$CurrentRunPointerReadyPath = "",
    [string]$CurrentRunPointerDonePath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-monitor-planonly-20260825-v6.json"
if (-not $PlanPath) { $PlanPath = $defaultPlanPath }
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$claimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$claimArchiveDir = Join-Path $repoRoot "docs\agent-log\global-writer-claim-archive"
$legacyExpansionClaimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-expansion-claim.json"
$monitorPy = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_listing_momentum_forward_monitor.py"
$claimManagerPy = Join-Path $repoRoot "trading_mvp\src\global_market_writer_claim.py"
$pythonHandoffDir = Join-Path $repoRoot "docs\agent-log\run-gates\python-worker-handoffs"
$automationId = "zolotyaylopata-listing-momentum-forward-v2"

function Resolve-PythonExecutable {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:PYTHON_EXE) { $candidates.Add($env:PYTHON_EXE) }
    foreach ($commandName in @("python.exe", "python", "py.exe")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command -and $command.Source) { $candidates.Add($command.Source) }
    }
    $candidates.Add("C:\Program Files\Python313\python.exe")
    $candidates.Add("C:\Users\koval\AppData\Local\Programs\Python\Python313\python.exe")
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "Python executable not found; set PYTHON_EXE or install Python 3.13"
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256([string]$Value) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToHexString($hasher.ComputeHash($bytes)).ToLowerInvariant() } finally { $hasher.Dispose() }
}

function Read-JsonFile([string]$Path) {
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Write-JsonFile([string]$Path, $Payload) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-CurrentRunPointerTransactionMutexName([string]$Path) {
    $mutexKey = Get-TextSha256 (
        [System.IO.Path]::GetFullPath($Path).ToLowerInvariant()
    )
    return "Global\ZolotyayLopata.ListingStrategyCurrentRun.$mutexKey"
}

function Invoke-CurrentRunPointerTransaction {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [ValidateRange(1, 300)][int]$TimeoutSec = 30
    )
    $mutexName = Get-CurrentRunPointerTransactionMutexName -Path $Path
    $transactionMutex = [System.Threading.Mutex]::new($false, $mutexName)
    $mutexHeld = $false
    try {
        try {
            $mutexHeld = $transactionMutex.WaitOne(
                [TimeSpan]::FromSeconds($TimeoutSec)
            )
        } catch [System.Threading.AbandonedMutexException] {
            $mutexHeld = $true
        }
        if (-not $mutexHeld) {
            throw "Timed out waiting for listing-strategy current-run transaction mutex."
        }
        & $Action
    } finally {
        if ($mutexHeld) { $transactionMutex.ReleaseMutex() }
        $transactionMutex.Dispose()
    }
}

if ($CurrentRunPointerTestOnly) {
    $requiredTestPaths = @(
        $CurrentRunPointerPathOverride,
        $CurrentRunPointerPayloadPath,
        $CurrentRunPointerReadyPath,
        $CurrentRunPointerDonePath
    )
    if (@($requiredTestPaths | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
        throw "Current-run pointer test mode requires pointer, payload, ready, and done paths."
    }
    $canonicalPointerPath = [System.IO.Path]::GetFullPath(
        (Join-Path $repoRoot "docs\agent-log\current-run.json")
    )
    $testPointerPath = [System.IO.Path]::GetFullPath($CurrentRunPointerPathOverride)
    if ($testPointerPath.Equals(
        $canonicalPointerPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Current-run pointer test mode refuses the canonical current-run pointer."
    }
    $testPayload = Read-JsonFile -Path $CurrentRunPointerPayloadPath
    if (
        [string]$testPayload.schema -ne "active_run_pointer_v1" -or
        [string]$testPayload.project -ne "trading_mvp"
    ) {
        throw "Current-run pointer test payload identity mismatch."
    }
    foreach ($markerPath in @($CurrentRunPointerReadyPath, $CurrentRunPointerDonePath)) {
        $markerDir = Split-Path -Parent $markerPath
        if ($markerDir -and -not (Test-Path -LiteralPath $markerDir)) {
            New-Item -ItemType Directory -Force -Path $markerDir | Out-Null
        }
    }
    [System.IO.File]::WriteAllText(
        $CurrentRunPointerReadyPath,
        "READY",
        [System.Text.UTF8Encoding]::new($false)
    )
    Invoke-CurrentRunPointerTransaction -Path $CurrentRunPointerPathOverride -Action {
        Write-JsonFile -Path $CurrentRunPointerPathOverride -Payload $testPayload
    }
    [System.IO.File]::WriteAllText(
        $CurrentRunPointerDonePath,
        "DONE",
        [System.Text.UTF8Encoding]::new($false)
    )
    [ordered]@{
        status = "CURRENT_RUN_POINTER_TEST_WRITE_COMPLETE"
        pointer_path = [System.IO.Path]::GetFullPath($CurrentRunPointerPathOverride)
    } | ConvertTo-Json -Depth 4
    exit 0
}

function New-SpotPythonWorkerHandoffReceipt($Plan, [string]$TickId) {
    $handoffToken = [guid]::NewGuid().ToString("N").ToLowerInvariant()
    $claimToken = [guid]::NewGuid().ToString("N").ToLowerInvariant()
    $receiptPath = Join-Path $pythonHandoffDir ($TickId + ".json")
    $wrapperStartedAt = (Get-Process -Id $PID -ErrorAction Stop).StartTime.ToUniversalTime().ToString("o")
    $tickOutput = [System.IO.Path]::GetFullPath((Join-Path ([string]$Plan.tick.tick_output_root) $TickId))
    Write-JsonFile -Path $receiptPath -Payload ([ordered]@{
        schema = "trading_mvp_market_data_worker_handoff_v1"
        status = "ISSUED"
        project = "trading_mvp"
        automation_id = $automationId
        attempt_id = $TickId
        plan_hash = [string]$Plan.plan_hash
        wrapper_pid = $PID
        wrapper_process_started_at_utc = $wrapperStartedAt
        handoff_token_sha256 = Get-TextSha256 $handoffToken
        claim_run_id = ([string]$Plan.plan_id + "__" + $TickId)
        claim_owner_kind = "listing_momentum_forward_monitor_tick"
        claim_owner_pid = $null
        claim_owner_process_started_at_utc = $null
        claim_ownership_token_sha256 = Get-TextSha256 $claimToken
        claim_output_namespace = $tickOutput
        claim_must_exist = $false
        issued_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    })
    return [ordered]@{ handoff_token = $handoffToken; claim_token = $claimToken; receipt_path = $receiptPath }
}

function Resolve-CanonicalWriterClaim([switch]$AllowRecovery) {
    if (-not (Test-Path -LiteralPath $claimPath)) {
        return [ordered]@{ status = "ABSENT"; reason = "claim_absent" }
    }
    if (-not $AllowRecovery) {
        return [ordered]@{ status = "PRESERVED"; reason = "recovery_not_authorized_for_read_only_preflight" }
    }
    try {
        $pythonExe = Resolve-PythonExecutable
        $output = & $pythonExe $claimManagerPy recover-stale --path $claimPath --archive-dir $claimArchiveDir 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "recover-stale exited $LASTEXITCODE`: $($output.Trim())" }
        $result = $output.Trim() | ConvertFrom-Json -DateKind String
        if ([string]$result.schema -ne "trading_mvp_global_market_writer_claim_recovery_v1") { throw "recovery schema mismatch" }
        if ([string]$result.status -notin @("ABSENT", "LIVE_PRESERVED", "STALE_RECOVERED", "BLOCKED")) { throw "unexpected recovery status" }
        return $result
    } catch {
        return [ordered]@{ status = "BLOCKED"; reason = ("claim_recovery_failed: " + $_.Exception.Message) }
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

function Invoke-Preflight([switch]$AllowClaimRecovery) {
    $reasons = [System.Collections.Generic.List[string]]@()
    if (-not (Test-Path -LiteralPath $PlanPath)) {
        throw "Plan file not found: $PlanPath"
    }
    $plan = Read-JsonFile -Path $PlanPath
    $planCheckStatus = "FAILED"
    try {
        $pythonExe = Resolve-PythonExecutable
        $planCheckOutput = & $pythonExe $monitorPy --plan $PlanPath --plan-check 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            $reasons.Add("plan_check_failed")
        } else {
            $planCheck = $planCheckOutput | ConvertFrom-Json
            $planCheckStatus = [string]$planCheck.status
            if ($planCheckStatus -ne "PLAN_OK") {
                $reasons.Add("plan_check_not_ok")
            }
        }
    } catch {
        $reasons.Add("plan_check_failed")
    }
    $gateCheck = Invoke-ActiveRunGateCheck
    $gate = $gateCheck.payload
    if (-not [bool]$gateCheck.ok) { $reasons.Add([string]$gateCheck.reason) }
    $claimRecovery = Resolve-CanonicalWriterClaim -AllowRecovery:($AllowClaimRecovery -and $reasons.Count -eq 0)
    if ([string]$claimRecovery.status -notin @("ABSENT", "STALE_RECOVERED") -or (Test-Path -LiteralPath $claimPath)) {
        $reasons.Add("global_writer_claim_exists")
    }
    if (Test-Path -LiteralPath $legacyExpansionClaimPath) {
        $reasons.Add("legacy_expansion_writer_claim_exists")
    }
    return [ordered]@{
        ok = ($reasons.Count -eq 0)
        reasons = $reasons
        plan_id = [string]$plan.plan_id
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = Get-FileSha256 $PlanPath
        plan_check_status = $planCheckStatus
        gate_status = [string]$gate.gate_status
        gate_authoritative_status = [string]$gate.status
        max_runtime_sec = [int]$plan.tick.max_runtime_sec
        tick_output_root = [string]$plan.tick.tick_output_root
        global_writer_claim_recovery = $claimRecovery
    }
}

if ($VisibleWorker -and (-not $ScheduledTick -or $PreflightOnly -or $Status)) {
    $payload = [ordered]@{
        ok = $false
        status = "BLOCKED"
        reasons = @("VisibleWorker_requires_exclusive_ScheduledTick_execution")
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 6 } else {
        Write-Host "VisibleWorker requires exclusive ScheduledTick execution" -ForegroundColor Red
    }
    exit 1
}

if ($Status) {
    $pythonExe = Resolve-PythonExecutable
    $statusOutput = & $pythonExe $monitorPy --status 2>&1 | Out-String
    if ($Json) { $statusOutput } else {
        Write-Host "=== forward monitor status ===" -ForegroundColor Cyan
        Write-Host $statusOutput
    }
    exit 0
}

if (-not $ScheduledTick -and -not $PreflightOnly) {
    $payload = [ordered]@{
        ok = $false
        status = "BLOCKED"
        reasons = @("ScheduledTick_required_for_execution")
    }
    if ($Json) { $payload | ConvertTo-Json -Depth 6 } else {
        Write-Host "execution requires ScheduledTick handoff" -ForegroundColor Red
    }
    exit 1
}

if ($VisibleWorker) {
    $preflight = Invoke-Preflight -AllowClaimRecovery:$ScheduledTick
    if (-not $preflight.ok) {
        if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
            Write-Host "visible worker preflight failed:" -ForegroundColor Red
            Write-Host ($preflight.reasons -join ", ")
        }
        exit 1
    }
    $plan = Read-JsonFile -Path $PlanPath
    $runId = [string]$plan.plan_id
    $tickId = "forward_tick_" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffffffZ")
    $pythonHandoff = New-SpotPythonWorkerHandoffReceipt -Plan $plan -TickId $tickId
    $launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_monitor.launch.json"
    $pointerPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
    $workerErrorLog = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_monitor.worker-error.log"
    try {
        Write-JsonFile -Path $launchRecordPath -Payload ([ordered]@{
            schema = "trading_mvp_listing_momentum_forward_monitor_launch_v1"
            status = "RUNNING"
            run_id = $runId
            visible_terminal_pid = $PID
            started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            plan_path = $PlanPath
            plan_hash = [string]$plan.plan_hash
            plan_file_sha256 = Get-FileSha256 $PlanPath
            research_only = $true
            public_data_only = $true
        })
        Invoke-CurrentRunPointerTransaction -Path $pointerPath -Action {
            Write-JsonFile -Path $pointerPath -Payload ([ordered]@{
                schema = "active_run_pointer_v1"
                project = "trading_mvp"
                run_id = $runId
                status = "RUNNING"
                updated_at = (Get-Date).ToString("o")
                manifest_path = [string]$plan.tick.state_path
                output = @{ path = [string]$plan.tick.tick_output_root; kind = "directory" }
                collector_pid = $null
                monitor_pid = $PID
                process_ids = @()
                launch_record_path = $launchRecordPath
            })
        }
        Write-Host "=== forward monitor tick (visible) ===" -ForegroundColor Cyan
        Write-Host "plan_hash: $($plan.plan_hash)"
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        $pythonExe = Resolve-PythonExecutable
        & $pythonExe $monitorPy --plan $PlanPath --tick --confirmed-visible-tick --tick-id $tickId --worker-handoff-token ([string]$pythonHandoff.handoff_token) --claim-ownership-token ([string]$pythonHandoff.claim_token) --plan-hash ([string]$plan.plan_hash)
        $exitCode = $LASTEXITCODE
    } catch {
        ("worker failed at " + (Get-Date).ToUniversalTime().ToString("o") + "`n" +
            ($_ | Out-String)) | Set-Content -LiteralPath $workerErrorLog -Encoding UTF8
        try {
            Invoke-CurrentRunPointerTransaction -Path $pointerPath -Action {
                $pointer = Read-JsonFile -Path $pointerPath
                $pointer.status = "STOPPED_INCOMPLETE"
                $pointer.updated_at = (Get-Date).ToString("o")
                $pointer.monitor_pid = $null
                $pointer.process_ids = @()
                $pointer | Add-Member -NotePropertyName error_log -NotePropertyValue $workerErrorLog -Force
                Write-JsonFile -Path $pointerPath -Payload $pointer
            }
            $launch = Read-JsonFile -Path $launchRecordPath
            $launch.status = "FAILED"
            $launch | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue (Get-Date).ToUniversalTime().ToString("o") -Force
            $launch | Add-Member -NotePropertyName tick_exit_code -NotePropertyValue 1 -Force
            $launch | Add-Member -NotePropertyName error_log -NotePropertyValue $workerErrorLog -Force
            Write-JsonFile -Path $launchRecordPath -Payload $launch
        } catch {
            ("failed to persist worker failure state: " + ($_ | Out-String)) |
                Add-Content -LiteralPath $workerErrorLog -Encoding UTF8
        }
        Write-Host "worker failed; see $workerErrorLog" -ForegroundColor Red
        Start-Sleep -Seconds 10
        exit 1
    }
    $pointerStatus = if ($exitCode -eq 0) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
    Invoke-CurrentRunPointerTransaction -Path $pointerPath -Action {
        Write-JsonFile -Path $pointerPath -Payload ([ordered]@{
            schema = "active_run_pointer_v1"
            project = "trading_mvp"
            run_id = $runId
            status = $pointerStatus
            updated_at = (Get-Date).ToString("o")
            manifest_path = [string]$plan.tick.state_path
            output = @{ path = [string]$plan.tick.tick_output_root; kind = "directory" }
            collector_pid = $null
            monitor_pid = $null
            process_ids = @()
            launch_record_path = $launchRecordPath
        })
    }
    $launch = Read-JsonFile -Path $launchRecordPath
    $launch.status = if ($exitCode -eq 0) { "COMPLETE" } else { "FAILED" }
    $launch | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue (Get-Date).ToUniversalTime().ToString("o") -Force
    $launch | Add-Member -NotePropertyName tick_exit_code -NotePropertyValue $exitCode -Force
    Write-JsonFile -Path $launchRecordPath -Payload $launch
    $pythonExe = Resolve-PythonExecutable
    $statusOutput = & $pythonExe $monitorPy --status 2>&1 | Out-String
    Write-Host $statusOutput
    Write-Host "tick exit code: $exitCode" -ForegroundColor Green
    Start-Sleep -Seconds 5
    exit $exitCode
}

$preflight = Invoke-Preflight -AllowClaimRecovery:$ScheduledTick
if ($PreflightOnly) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
        Write-Host "=== forward tick preflight ===" -ForegroundColor Cyan
        Write-Host ("ok: " + $preflight.ok)
        if ($preflight.reasons.Count -gt 0) { Write-Host ("reasons: " + ($preflight.reasons -join ", ")) }
        Write-Host ("gate: " + $preflight.gate_status)
    }
    exit 0
}

if (-not $preflight.ok) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
        Write-Host "preflight failed:" -ForegroundColor Red
        Write-Host ($preflight.reasons -join ", ")
    }
    exit 1
}

$pwshExe = (Get-Process -Id $PID).Path
$childArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
    "-VisibleWorker", "-ScheduledTick", "-PlanPath", $PlanPath
)
$terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
$payload = [ordered]@{
    status = "VISIBLE_TERMINAL_LAUNCHED"
    run_id = $preflight.plan_id
    visible_terminal_pid = $terminal.Id
    plan_hash = $preflight.plan_hash
    status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
}
if ($Json) { $payload | ConvertTo-Json -Depth 6 } else {
    Write-Host "visible tick terminal launched (pid $($terminal.Id))" -ForegroundColor Green
}
exit 0
