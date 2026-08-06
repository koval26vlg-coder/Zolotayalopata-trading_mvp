[CmdletBinding()]
param(
    [string]$RunId = "",
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\funding-regime-persistence-v2\plans\funding_regime_persistence_v2_planonly_20260717_001014.json",
    [string]$ExpectedPlanHash = "c51562b959001970f3c689f7e277e8d3131d17c7f5b0e4e206f29750b1b60465",
    [string]$OutputPath = "",
    [string]$LaunchRecordPath = "",
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
$GateChecker = Join-Path $PSScriptRoot "check_active_run_gate.ps1"
$ArtifactRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\funding-regime-persistence-v2\feasibility"

if (-not $RunId) {
    $RunId = "funding_regime_persistence_v2_train_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $ArtifactRoot "$RunId.json"
}
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\$RunId.launch.json"
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temporary -Encoding utf8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Value)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-GateStatus {
    if (-not (Test-Path -LiteralPath $GateChecker)) {
        throw "Active-run gate checker is missing: $GateChecker"
    }
    $raw = & $GateChecker -Json
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Active-run gate checker failed with exit code $LASTEXITCODE"
    }
    return ($raw | Out-String | ConvertFrom-Json)
}

function Assert-GateOpen {
    $gate = Get-GateStatus
    $status = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
    if ($status -eq "RUNNING") {
        throw "Active-run gate is RUNNING for $($gate.run_id); train feasibility cannot overlap it."
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "Active-run gate is STOPPED_INCOMPLETE for $($gate.run_id); resolve it before evaluation."
    }
    if ($status -ne "READY_FOR_POSTPROCESS") {
        throw "Active-run gate is not open: $status"
    }
    return $gate
}

function Assert-Inputs {
    foreach ($required in @($PlanPath, $RunMvp, $GateChecker)) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required input is missing: $required"
        }
    }
    if ($ExpectedPlanHash -notmatch '^[0-9a-f]{64}$') {
        throw "ExpectedPlanHash must be a lowercase SHA-256 value."
    }
    $fullOutput = [System.IO.Path]::GetFullPath($OutputPath)
    $fullRoot = [System.IO.Path]::GetFullPath($ArtifactRoot).TrimEnd('\') + '\'
    if (-not $fullOutput.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "OutputPath must remain under $ArtifactRoot"
    }
    if (Test-Path -LiteralPath $OutputPath) {
        throw "Immutable train-feasibility output already exists: $OutputPath"
    }
}

Assert-Inputs

if ($Worker) {
    try {
        if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
            throw "Visible worker requires its ownership token and launch record."
        }
        $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
        if (
            [string]$record.run_id -ne $RunId -or
            [string]$record.plan_path -ne [System.IO.Path]::GetFullPath($PlanPath) -or
            [string]$record.output_path -ne [System.IO.Path]::GetFullPath($OutputPath) -or
            [string]$record.expected_plan_hash -ne $ExpectedPlanHash -or
            [string]$record.worker_token_sha256 -ne (Get-TextSha256 -Value $WorkerToken)
        ) {
            throw "Visible worker ownership record mismatch."
        }

        $gate = Assert-GateOpen
        $startedAt = Get-Date
        $deadline = $startedAt.AddSeconds($MaxRuntimeSec)
        $record.status = "RUNNING"
        $record.worker_pid = $PID
        $record.started_at = $startedAt.ToString("o")
        $record.deadline = $deadline.ToString("o")
        Write-JsonAtomic -Path $LaunchRecordPath -Value $record

        Clear-Host
        Write-Host "trading_mvp funding-regime persistence v2" -ForegroundColor Cyan
        Write-Host "TRAIN-ONLY FEASIBILITY / OOS EMBARGOED" -ForegroundColor Yellow
        Write-Host "Run ID:    $RunId"
        Write-Host "Plan hash: $ExpectedPlanHash"
        Write-Host "Output:    $OutputPath"
        Write-Host "Runtime:   <= $MaxRuntimeSec sec"
        Write-Host "Gate:      $($gate.gate_status)"
        Write-Host ""
        Write-Host "[1/2] Verifying frozen hashes and reading train-only funding/candles..." -ForegroundColor Cyan

        & pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvp `
            -Action fast-edge-funding-persistence-v2-train-feasibility `
            -PlanPath $PlanPath `
            -ExpectedPlanHash $ExpectedPlanHash `
            -OutputPath $OutputPath `
            -MaxRuntimeSec $MaxRuntimeSec
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            throw "run_mvp.ps1 failed with exit code $LASTEXITCODE"
        }
        if (-not (Test-Path -LiteralPath $OutputPath)) {
            throw "Evaluator returned without producing its immutable output."
        }

        $result = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
        $record.status = "COMPLETED"
        $record.final = $true
        $record.completed_at = (Get-Date).ToString("o")
        $record.verdict = [string]$result.verdict
        $record.result_hash = [string]$result.deterministic_result_hash
        $record.failure = $null
        Write-JsonAtomic -Path $LaunchRecordPath -Value $record

        Write-Host ""
        Write-Host "[2/2] Final train-only artifact verified." -ForegroundColor Green
        Write-Host "Verdict:       $($result.verdict)" -ForegroundColor Green
        Write-Host "Episodes:      $($result.metrics.independent_regime_episodes)"
        Write-Host "Signal dates:  $($result.metrics.unique_signal_dates)"
        Write-Host "Route sides:   $(@($result.metrics.route_directions).Count)"
        Write-Host "Result hash:   $($result.deterministic_result_hash)"
        Write-Host "Next action:   $($result.next_allowed_action)"
        Write-Host ""
        Write-Host "Window closes in $HoldOpenSec seconds." -ForegroundColor DarkGray
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $failure = $_.Exception.Message
        if (Test-Path -LiteralPath $LaunchRecordPath) {
            $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
            $record.status = "FAILED"
            $record.final = $true
            $record.completed_at = (Get-Date).ToString("o")
            $record.failure = $failure
            Write-JsonAtomic -Path $LaunchRecordPath -Value $record
        }
        Write-Host ""
        Write-Host "TRAIN FEASIBILITY FAILED: $failure" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Assert-GateOpen
$workerToken = [Guid]::NewGuid().ToString("N")
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$scriptPath = $MyInvocation.MyCommand.Path
$workerArgs = @(
    "-NoLogo",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $scriptPath,
    "-Worker",
    "-WorkerToken", $workerToken,
    "-RunId", $RunId,
    "-PlanPath", $PlanPath,
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-OutputPath", $OutputPath,
    "-LaunchRecordPath", $LaunchRecordPath,
    "-MaxRuntimeSec", $MaxRuntimeSec,
    "-HoldOpenSec", $HoldOpenSec
)

$launchRecord = [ordered]@{
    schema = "funding_regime_persistence_v2_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    final = $false
    visible_terminal = $true
    launch_record_path = [System.IO.Path]::GetFullPath($LaunchRecordPath)
    plan_path = [System.IO.Path]::GetFullPath($PlanPath)
    expected_plan_hash = $ExpectedPlanHash
    output_path = [System.IO.Path]::GetFullPath($OutputPath)
    max_runtime_sec = $MaxRuntimeSec
    hold_open_sec = $HoldOpenSec
    gate_status_at_launch = [string]$gate.gate_status
    gate_run_id_at_launch = [string]$gate.run_id
    network_access = $false
    train_only = $true
    oos_values_read = $false
    grid_search = $false
    retune = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    worker_token_sha256 = Get-TextSha256 -Value $workerToken
    launcher_pid = $PID
    worker_pid = $null
    launched_at = (Get-Date).ToString("o")
    started_at = $null
    deadline = $null
    completed_at = $null
    verdict = $null
    result_hash = $null
    failure = $null
    expected_finish_not_later_than = (Get-Date).AddSeconds($MaxRuntimeSec).ToString("o")
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord

$process = Start-Process -FilePath $pwsh -ArgumentList $workerArgs -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
$launchRecord.status = "STARTED"
$launchRecord.worker_pid = $process.Id
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord

[pscustomobject]@{
    decision = "VISIBLE_TRAIN_FEASIBILITY_STARTED"
    run_id = $RunId
    worker_pid = $process.Id
    launch_record_path = [System.IO.Path]::GetFullPath($LaunchRecordPath)
    output_path = [System.IO.Path]::GetFullPath($OutputPath)
    expected_finish_not_later_than = $launchRecord.expected_finish_not_later_than
    visible_terminal = $true
} | ConvertTo-Json -Depth 8
