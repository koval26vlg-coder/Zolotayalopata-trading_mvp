param(
    [string]$PlanPath = "",
    [switch]$PreflightOnly,
    [switch]$Status,
    [switch]$Json,
    [switch]$VisibleWorker
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$defaultPlanPath = Join-Path $repoRoot "docs\plans\slow-liquidity-listing-momentum-forward-expansion-planonly-20260817.json"
if (-not $PlanPath) { $PlanPath = $defaultPlanPath }
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$monitorPy = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_listing_momentum_forward_expansion_monitor.py"
$claimPath = Join-Path $repoRoot "docs\agent-log\active-market-data-writer-expansion-claim.json"
$launchRecordPath = Join-Path $repoRoot "docs\agent-log\run-gates\listing_momentum_forward_expansion.launch.json"

function Resolve-PythonExecutable {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:PYTHON_EXE) { $candidates.Add($env:PYTHON_EXE) }
    foreach ($commandName in @("python.exe", "python", "py.exe")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) { $candidates.Add($command.Source) }
    }
    $candidates.Add("C:\Program Files\Python313\python.exe")
    $candidates.Add("C:\Users\koval\AppData\Local\Programs\Python\Python313\python.exe")
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "Python executable not found; set PYTHON_EXE or install Python 3.13"
}

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
    $Payload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Invoke-Preflight {
    if (-not (Test-Path -LiteralPath $PlanPath)) { throw "Plan file not found: $PlanPath" }
    $plan = Read-JsonFile -Path $PlanPath
    $pythonExe = Resolve-PythonExecutable
    $planCheckOutput = & $pythonExe $monitorPy --plan $PlanPath --plan-check 2>&1 | Out-String
    $planCheck = $planCheckOutput | ConvertFrom-Json
    $gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    $reasons = [System.Collections.Generic.List[string]]::new()
    if ([string]$planCheck.status -ne "PLAN_OK") { $reasons.Add("plan_check_not_ok") }
    if ([string]$gate.gate_status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        $reasons.Add("active_run_gate_$($gate.gate_status)")
    }
    if (Test-Path -LiteralPath $claimPath) { $reasons.Add("expansion_writer_claim_exists") }
    return [ordered]@{
        ok = ($reasons.Count -eq 0)
        reasons = $reasons
        plan_id = [string]$plan.plan_id
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = Get-FileSha256 $PlanPath
        plan_check_status = [string]$planCheck.status
        gate_status = [string]$gate.gate_status
        max_runtime_sec = [int]$plan.tick.max_runtime_sec
        tick_output_root = [string]$plan.tick.tick_output_root
        status_command = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status -Json"
    }
}

if ($Status) {
    $pythonExe = Resolve-PythonExecutable
    $statusOutput = & $pythonExe $monitorPy --status 2>&1 | Out-String
    if ($Json) { $statusOutput.Trim() } else {
        Write-Host "=== Listing Momentum expansion monitor status ===" -ForegroundColor Cyan
        Write-Host $statusOutput.Trim()
    }
    exit 0
}

if ($VisibleWorker) {
    $plan = Read-JsonFile -Path $PlanPath
    $started = (Get-Date).ToUniversalTime().ToString("o")
    Write-JsonFile -Path $launchRecordPath -Payload ([ordered]@{
        schema = "trading_mvp_listing_momentum_forward_expansion_launch_v1"
        status = "RUNNING"
        run_id = [string]$plan.plan_id
        visible_terminal_pid = $PID
        started_at_utc = $started
        command = "python trading_mvp/src/slow_liquidity_listing_momentum_forward_expansion_monitor.py --plan `"$PlanPath`" --tick --confirmed-visible-tick"
        cwd = $repoRoot
        plan_path = $PlanPath
        plan_hash = [string]$plan.plan_hash
        plan_file_sha256 = Get-FileSha256 $PlanPath
        output_root = [string]$plan.tick.tick_output_root
        state_path = [string]$plan.tick.state_path
        expected_duration_sec = [int]$plan.tick.max_runtime_sec
        research_only = $true
        public_data_only = $true
    })
    Write-Host "=== Listing Momentum expansion tick (visible) ===" -ForegroundColor Cyan
    Write-Host ("plan_hash: " + [string]$plan.plan_hash)
    Write-Host ("expected max runtime: " + [int]$plan.tick.max_runtime_sec + " sec")
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $pythonExe = Resolve-PythonExecutable
    & $pythonExe $monitorPy --plan $PlanPath --tick --confirmed-visible-tick
    $exitCode = $LASTEXITCODE
    $launch = Read-JsonFile -Path $launchRecordPath
    $launch.status = if ($exitCode -eq 0) { "COMPLETE" } else { "FAILED" }
    $launch | Add-Member -NotePropertyName finished_at_utc -NotePropertyValue (Get-Date).ToUniversalTime().ToString("o") -Force
    $launch | Add-Member -NotePropertyName tick_exit_code -NotePropertyValue $exitCode -Force
    Write-JsonFile -Path $launchRecordPath -Payload $launch
    Write-Host ("tick exit code: " + $exitCode)
    exit $exitCode
}

$preflight = Invoke-Preflight
if ($PreflightOnly) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
        Write-Host "=== Listing Momentum expansion tick preflight ===" -ForegroundColor Cyan
        Write-Host ("ok: " + $preflight.ok)
        Write-Host ("gate: " + $preflight.gate_status)
        if ($preflight.reasons.Count -gt 0) { Write-Host ("reasons: " + ($preflight.reasons -join ", ")) }
    }
    exit 0
}

if (-not $preflight.ok) {
    if ($Json) { $preflight | ConvertTo-Json -Depth 8 } else {
        Write-Host "expansion tick preflight failed:" -ForegroundColor Red
        Write-Host ($preflight.reasons -join ", ")
    }
    exit 1
}

$pwshExe = (Get-Process -Id $PID).Path
$childArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -VisibleWorker -PlanPath `"$PlanPath`""
$terminal = Start-Process -FilePath $pwshExe -ArgumentList $childArgs -WorkingDirectory $repoRoot -WindowStyle Normal -PassThru
$payload = [ordered]@{
    status = "VISIBLE_TERMINAL_LAUNCHED"
    run_id = $preflight.plan_id
    visible_terminal_pid = $terminal.Id
    plan_hash = $preflight.plan_hash
    expected_duration_sec = $preflight.max_runtime_sec
    output_root = $preflight.tick_output_root
    status_command = $preflight.status_command
    launch_record_path = $launchRecordPath
}
if ($Json) { $payload | ConvertTo-Json -Depth 8 } else {
    Write-Host ("visible expansion tick terminal launched (pid " + $terminal.Id + ")") -ForegroundColor Green
    Write-Host ("status: " + $preflight.status_command)
}
exit 0
