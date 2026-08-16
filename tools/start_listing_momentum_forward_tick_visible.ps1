param(
    [string]$PlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-monitor-planonly-20260816.json"
if (-not $PlanPath) { $PlanPath = $defaultPlanPath }
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$claimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-claim.json"
$monitorPy = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_listing_momentum_forward_monitor.py"

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function Invoke-Preflight {
    $reasons = [System.Collections.Generic.List[string]]@()
    if (-not (Test-Path -LiteralPath $PlanPath)) {
        throw "Plan file not found: $PlanPath"
    }
    $plan = Read-JsonFile -Path $PlanPath
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ([string]$gate.gate_status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        $reasons.Add("active_run_gate_$($gate.gate_status)")
    }
    if (Test-Path -LiteralPath $claimPath) {
        $reasons.Add("global_writer_claim_exists")
    }
    return [ordered]@{
        ok = ($reasons.Count -eq 0)
        reasons = $reasons
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = Get-FileSha256 $PlanPath
        gate_status = [string]$gate.gate_status
        max_runtime_sec = [int]$plan.tick.max_runtime_sec
        tick_output_root = [string]$plan.tick.tick_output_root
    }
}

if ($Status) {
    $status = & python $monitorPy --status 2>&1 | Out-String
    if ($Json) { $status } else {
        Write-Host "=== forward monitor status ===" -ForegroundColor Cyan
        Write-Host $status
    }
    exit 0
}

if ($VisibleWorker) {
    $plan = Read-JsonFile -Path $PlanPath
    $launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_monitor.launch.json"
    $pointerPath = Join-Path $repoRoot "docs\agent-log\current-run.json"
    $workerErrorLog = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_monitor.worker-error.log"
    try {
        Write-JsonFile -Path $launchRecordPath -Payload ([ordered]@{
            schema = "trading_mvp_listing_momentum_forward_monitor_launch_v1"
            status = "RUNNING"
            run_id = "slow_liquidity_listing_momentum_forward_monitor_20260816"
            visible_terminal_pid = $PID
            started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            plan_path = $PlanPath
            plan_hash = [string]$plan.plan_hash
            plan_file_sha256 = Get-FileSha256 $PlanPath
            research_only = $true
            public_data_only = $true
        })
        Write-JsonFile -Path $pointerPath -Payload ([ordered]@{
            schema = "active_run_pointer_v1"
            project = "trading_mvp"
            run_id = "slow_liquidity_listing_momentum_forward_monitor_20260816"
            status = "RUNNING"
            updated_at = (Get-Date).ToString("o")
            manifest_path = [string]$plan.tick.state_path
            output = @{ path = [string]$plan.tick.tick_output_root; kind = "directory" }
            collector_pid = $null
            monitor_pid = $PID
            process_ids = @()
            launch_record_path = $launchRecordPath
        })
        Write-Host "=== forward monitor tick (visible) ===" -ForegroundColor Cyan
        Write-Host "plan_hash: $($plan.plan_hash)"
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        & python $monitorPy --plan $PlanPath --tick --confirmed-visible-tick
        $exitCode = $LASTEXITCODE
    } catch {
        ("worker failed at " + (Get-Date).ToUniversalTime().ToString("o") + "`n" +
            ($_ | Out-String)) | Set-Content -LiteralPath $workerErrorLog -Encoding UTF8
        Write-Host "worker failed; see $workerErrorLog" -ForegroundColor Red
        Start-Sleep -Seconds 10
        exit 1
    }
    $pointerStatus = if ($exitCode -eq 0) { "READY_FOR_POSTPROCESS" } else { "STOPPED_INCOMPLETE" }
    Write-JsonFile -Path $pointerPath -Payload ([ordered]@{
        schema = "active_run_pointer_v1"
        project = "trading_mvp"
        run_id = "slow_liquidity_listing_momentum_forward_monitor_20260816"
        status = $pointerStatus
        updated_at = (Get-Date).ToString("o")
        manifest_path = [string]$plan.tick.state_path
        output = @{ path = [string]$plan.tick.tick_output_root; kind = "directory" }
        collector_pid = $null
        monitor_pid = $null
        process_ids = @()
        launch_record_path = $launchRecordPath
    })
    $launch = Read-JsonFile -Path $launchRecordPath
    $launch.status = if ($exitCode -eq 0) { "COMPLETE" } else { "FAILED" }
    $launch | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue (Get-Date).ToUniversalTime().ToString("o") -Force
    $launch | Add-Member -NotePropertyName tick_exit_code -NotePropertyValue $exitCode -Force
    Write-JsonFile -Path $launchRecordPath -Payload $launch
    $state = & python $monitorPy --status 2>&1 | Out-String
    Write-Host $state
    Write-Host "tick exit code: $exitCode" -ForegroundColor Green
    Start-Sleep -Seconds 5
    exit $exitCode
}

$preflight = Invoke-Preflight
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
    "-VisibleWorker", "-PlanPath", $PlanPath
)
$terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
$payload = [ordered]@{
    status = "VISIBLE_TERMINAL_LAUNCHED"
    run_id = "slow_liquidity_listing_momentum_forward_monitor_20260816"
    visible_terminal_pid = $terminal.Id
    plan_hash = $preflight.plan_hash
    status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
}
if ($Json) { $payload | ConvertTo-Json -Depth 6 } else {
    Write-Host "visible tick terminal launched (pid $($terminal.Id))" -ForegroundColor Green
}
exit 0
