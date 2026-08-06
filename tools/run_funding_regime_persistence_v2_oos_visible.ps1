[CmdletBinding()]
param(
    [string]$RunId = "",
    [string]$PlanPath = "E:\ZolotyayLopata-data\exports\trading-mvp\funding-regime-persistence-v2\plans\funding_regime_persistence_v2_planonly_20260717_001014.json",
    [string]$ExpectedPlanHash = "c51562b959001970f3c689f7e277e8d3131d17c7f5b0e4e206f29750b1b60465",
    [string]$FeasibilityPath = "E:\ZolotyayLopata-data\exports\trading-mvp\funding-regime-persistence-v2\feasibility\funding_regime_persistence_v2_train_20260717_002328.json",
    [string]$ExpectedFeasibilityResultHash = "bec9f9b368d3961d451c28ce730d86385af18b27cae5256566031e8875c113c0",
    [string]$ArtifactRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\funding-regime-persistence-v2\oos",
    [string]$FirstOutputPath = "",
    [string]$SecondOutputPath = "",
    [string]$ManifestPath = "",
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

if (-not $RunId) {
    $RunId = "funding_regime_persistence_v2_oos_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
if (-not $FirstOutputPath) { $FirstOutputPath = Join-Path $ArtifactRoot "$RunId.repeat-1.json" }
if (-not $SecondOutputPath) { $SecondOutputPath = Join-Path $ArtifactRoot "$RunId.repeat-2.json" }
if (-not $ManifestPath) { $ManifestPath = Join-Path $ArtifactRoot "$RunId.manifest.json" }
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\$RunId.launch.json"
}
if ($MaxRuntimeSec -lt 120) {
    throw "MaxRuntimeSec must reserve enough time for two deterministic repeats."
}
$PerRepeatRuntimeSec = [int][Math]::Floor(($MaxRuntimeSec - 60) / 2)

function Write-JsonAtomic {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temporary -Encoding utf8
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

function Get-FileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-GateStatus {
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
        throw "Active-run gate is RUNNING for $($gate.run_id); OOS cannot overlap it."
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "Active-run gate is STOPPED_INCOMPLETE for $($gate.run_id)."
    }
    if ($status -ne "READY_FOR_POSTPROCESS") {
        throw "Active-run gate is not open: $status"
    }
    return $gate
}

function Assert-InputsAndOutputs {
    foreach ($required in @($PlanPath, $FeasibilityPath, $RunMvp, $GateChecker)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required input is missing: $required" }
    }
    foreach ($hash in @($ExpectedPlanHash, $ExpectedFeasibilityResultHash)) {
        if ($hash -notmatch '^[0-9a-f]{64}$') { throw "Expected hashes must be lowercase SHA-256 values." }
    }
    $root = [System.IO.Path]::GetFullPath($ArtifactRoot).TrimEnd('\') + '\'
    foreach ($path in @($FirstOutputPath, $SecondOutputPath, $ManifestPath)) {
        $full = [System.IO.Path]::GetFullPath($path)
        if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "OOS artifacts must remain under $ArtifactRoot"
        }
        if (Test-Path -LiteralPath $path) { throw "Immutable OOS artifact already exists: $path" }
    }
}

function Get-RemainingRuntimeSec {
    param([Parameter(Mandatory)][datetime]$StartedAt)
    $remaining = $MaxRuntimeSec - [int]((Get-Date) - $StartedAt).TotalSeconds
    if ($remaining -lt 1) { throw "Visible OOS run exceeded MaxRuntimeSec." }
    return $remaining
}

function Invoke-OosRepeat {
    param([Parameter(Mandatory)][string]$Output, [Parameter(Mandatory)][datetime]$StartedAt)
    $remaining = Get-RemainingRuntimeSec -StartedAt $StartedAt
    if ($remaining -lt $PerRepeatRuntimeSec) {
        throw "Insufficient common runtime budget for the next deterministic repeat."
    }
    & pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File $RunMvp `
        -Action fast-edge-funding-persistence-v2-oos `
        -PlanPath $PlanPath `
        -ExpectedPlanHash $ExpectedPlanHash `
        -FeasibilityPath $FeasibilityPath `
        -ExpectedFeasibilityResultHash $ExpectedFeasibilityResultHash `
        -OutputPath $Output `
        -MaxRuntimeSec $PerRepeatRuntimeSec
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "run_mvp.ps1 failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $Output)) { throw "OOS repeat output is missing: $Output" }
    return (Get-Content -LiteralPath $Output -Raw | ConvertFrom-Json)
}

Assert-InputsAndOutputs

if ($Worker) {
    try {
        if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
            throw "Visible worker requires an ownership token and launch record."
        }
        $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
        if (
            [string]$record.run_id -ne $RunId -or
            [string]$record.plan_path -ne [System.IO.Path]::GetFullPath($PlanPath) -or
            [string]$record.feasibility_path -ne [System.IO.Path]::GetFullPath($FeasibilityPath) -or
            [string]$record.worker_token_sha256 -ne (Get-TextSha256 -Value $WorkerToken)
        ) {
            throw "Visible OOS worker ownership record mismatch."
        }
        $gate = Assert-GateOpen
        $startedAt = Get-Date
        $record.status = "RUNNING"
        $record.worker_pid = $PID
        $record.started_at = $startedAt.ToString("o")
        $record.deadline = $startedAt.AddSeconds($MaxRuntimeSec).ToString("o")
        Write-JsonAtomic -Path $LaunchRecordPath -Value $record

        Clear-Host
        Write-Host "trading_mvp funding-regime persistence v2" -ForegroundColor Cyan
        Write-Host "HASH-BOUND OOS / NO GRID / NO RETUNE" -ForegroundColor Yellow
        Write-Host "Run ID:          $RunId"
        Write-Host "Plan hash:       $ExpectedPlanHash"
        Write-Host "Feasibility:     $ExpectedFeasibilityResultHash"
        Write-Host "Total runtime:   <= $MaxRuntimeSec sec"
        Write-Host "Gate:            $($gate.gate_status)"
        Write-Host ""
        Write-Host "[1/3] OOS deterministic repeat 1..." -ForegroundColor Cyan
        $first = Invoke-OosRepeat -Output $FirstOutputPath -StartedAt $startedAt
        Write-Host "[2/3] OOS deterministic repeat 2..." -ForegroundColor Cyan
        $second = Invoke-OosRepeat -Output $SecondOutputPath -StartedAt $startedAt
        if (
            [string]$first.deterministic_result_hash -ne [string]$second.deterministic_result_hash -or
            [string]$first.verdict -ne [string]$second.verdict -or
            (Get-FileSha256 -Path $FirstOutputPath) -ne (Get-FileSha256 -Path $SecondOutputPath)
        ) {
            throw "deterministic repeat mismatch"
        }

        $manifest = [ordered]@{
            schema = "funding_regime_persistence_v2_oos_visible_manifest_v1"
            status = "COMPLETED"
            final = $true
            run_id = $RunId
            plan_path = [System.IO.Path]::GetFullPath($PlanPath)
            plan_hash = $ExpectedPlanHash
            feasibility_path = [System.IO.Path]::GetFullPath($FeasibilityPath)
            feasibility_result_hash = $ExpectedFeasibilityResultHash
            repeat_paths = @([System.IO.Path]::GetFullPath($FirstOutputPath), [System.IO.Path]::GetFullPath($SecondOutputPath))
            repeat_file_sha256 = @(
                (Get-FileSha256 -Path $FirstOutputPath)
                (Get-FileSha256 -Path $SecondOutputPath)
            )
            deterministic_result_hash = [string]$first.deterministic_result_hash
            verdict = [string]$first.verdict
            rejection_reasons = @($first.rejection_reasons)
            metrics = $first.metrics
            next_allowed_action = [string]$first.next_allowed_action
            network_used = $false
            grid_search = $false
            retune = $false
            live_orders = $false
            private_api_keys = $false
            leverage_or_margin = $false
            started_at = $startedAt.ToString("o")
            completed_at = (Get-Date).ToString("o")
            runtime_sec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
            max_runtime_sec = $MaxRuntimeSec
            per_repeat_runtime_sec = $PerRepeatRuntimeSec
        }
        Write-JsonAtomic -Path $ManifestPath -Value $manifest

        $record.status = "COMPLETED"
        $record.final = $true
        $record.completed_at = (Get-Date).ToString("o")
        $record.verdict = [string]$first.verdict
        $record.result_hash = [string]$first.deterministic_result_hash
        $record.failure = $null
        Write-JsonAtomic -Path $LaunchRecordPath -Value $record

        Write-Host "[3/3] Deterministic repeat verified." -ForegroundColor Green
        Write-Host "Verdict:       $($first.verdict)" -ForegroundColor Green
        Write-Host "Episodes:      $($first.metrics.independent_episode_count)"
        Write-Host "Signal dates:  $($first.metrics.unique_signal_dates)"
        Write-Host "Net PnL:       $($first.metrics.total_net_pnl_quote) quote"
        Write-Host "Expectancy:    $($first.metrics.total_net_expectancy_quote) quote/event"
        Write-Host "Stress PnL:    $($first.metrics.stress_total_net_pnl_quote) quote"
        Write-Host "Result hash:   $($first.deterministic_result_hash)"
        Write-Host "Next action:   $($first.next_allowed_action)"
        Write-Host ""
        Write-Host "Window closes in $HoldOpenSec seconds." -ForegroundColor DarkGray
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $failure = $_.Exception.Message
        $failurePath = Join-Path $ArtifactRoot "$RunId.failure.json"
        if (-not (Test-Path -LiteralPath $failurePath)) {
            Write-JsonAtomic -Path $failurePath -Value ([ordered]@{
                schema = "funding_regime_persistence_v2_oos_failure_v1"
                status = "STOPPED_INCOMPLETE"
                final = $false
                run_id = $RunId
                error = $failure
                partial_accept = $false
                completed_at = (Get-Date).ToString("o")
            })
        }
        if (Test-Path -LiteralPath $LaunchRecordPath) {
            $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
            $record.status = "STOPPED_INCOMPLETE"
            $record.final = $false
            $record.completed_at = (Get-Date).ToString("o")
            $record.failure = $failure
            Write-JsonAtomic -Path $LaunchRecordPath -Value $record
        }
        Write-Host ""
        Write-Host "OOS FAILED: $failure" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = Assert-GateOpen
$workerToken = [Guid]::NewGuid().ToString("N")
$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$scriptPath = $MyInvocation.MyCommand.Path
$workerArgs = @(
    "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath,
    "-Worker", "-WorkerToken", $workerToken,
    "-RunId", $RunId,
    "-PlanPath", $PlanPath,
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-FeasibilityPath", $FeasibilityPath,
    "-ExpectedFeasibilityResultHash", $ExpectedFeasibilityResultHash,
    "-ArtifactRoot", $ArtifactRoot,
    "-FirstOutputPath", $FirstOutputPath,
    "-SecondOutputPath", $SecondOutputPath,
    "-ManifestPath", $ManifestPath,
    "-LaunchRecordPath", $LaunchRecordPath,
    "-MaxRuntimeSec", $MaxRuntimeSec,
    "-HoldOpenSec", $HoldOpenSec
)
$launchRecord = [ordered]@{
    schema = "funding_regime_persistence_v2_oos_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    final = $false
    visible_terminal = $true
    launch_record_path = [System.IO.Path]::GetFullPath($LaunchRecordPath)
    plan_path = [System.IO.Path]::GetFullPath($PlanPath)
    expected_plan_hash = $ExpectedPlanHash
    feasibility_path = [System.IO.Path]::GetFullPath($FeasibilityPath)
    expected_feasibility_result_hash = $ExpectedFeasibilityResultHash
    first_output_path = [System.IO.Path]::GetFullPath($FirstOutputPath)
    second_output_path = [System.IO.Path]::GetFullPath($SecondOutputPath)
    manifest_path = [System.IO.Path]::GetFullPath($ManifestPath)
    max_runtime_sec = $MaxRuntimeSec
    per_repeat_runtime_sec = $PerRepeatRuntimeSec
    hold_open_sec = $HoldOpenSec
    gate_status_at_launch = [string]$gate.gate_status
    gate_run_id_at_launch = [string]$gate.run_id
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
    network_used = $false
    grid_search = $false
    retune = $false
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord
$process = Start-Process -FilePath $pwsh -ArgumentList $workerArgs -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
$launchRecord.status = "STARTED"
$launchRecord.worker_pid = $process.Id
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord

[pscustomobject]@{
    decision = "VISIBLE_HASH_BOUND_OOS_STARTED"
    run_id = $RunId
    worker_pid = $process.Id
    launch_record_path = [System.IO.Path]::GetFullPath($LaunchRecordPath)
    manifest_path = [System.IO.Path]::GetFullPath($ManifestPath)
    expected_finish_not_later_than = $launchRecord.expected_finish_not_later_than
    visible_terminal = $true
} | ConvertTo-Json -Depth 8
