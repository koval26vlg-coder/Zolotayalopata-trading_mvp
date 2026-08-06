[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$CollectorManifestPath,
    [Parameter(Mandatory = $true)][string]$PitStatePath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$GatePath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PlanModule = Join-Path $ProjectRoot "trading_mvp\src\spot_perp_basis_history_v2.py"
$QualityModule = Join-Path $ProjectRoot "trading_mvp\src\spot_perp_basis_history_v2_quality.py"
$CollectorModule = Join-Path $ProjectRoot "trading_mvp\src\spot_perp_basis_history_v2_collector.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Python runtime is required."
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-JsonAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not (Test-Path -LiteralPath $LaunchRecordPath)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($item in $Values.GetEnumerator()) {
        if ($record.PSObject.Properties.Name -contains $item.Key) { $record.($item.Key) = $item.Value }
        else { $record | Add-Member -NotePropertyName $item.Key -NotePropertyValue $item.Value }
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$CollectorManifestPath = [System.IO.Path]::GetFullPath($CollectorManifestPath)
$PitStatePath = [System.IO.Path]::GetFullPath($PitStatePath)
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$python = Resolve-Python
$env:TRADING_MVP_PYTHON = $python

foreach ($required in @($PlanPath, $CollectorManifestPath, $PitStatePath, $PlanModule, $QualityModule, $CollectorModule)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file is missing: $required" }
}

$validationRaw = & $python $PlanModule validate-plan --plan $PlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Plan validation failed." }
$validation = (@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json
$collector = Get-Content -LiteralPath $CollectorManifestPath -Raw | ConvertFrom-Json
if ($collector.final -ne $true -or [string]$collector.status -ne "READY_FOR_POSTPROCESS") {
    throw "Collector manifest is not READY_FOR_POSTPROCESS."
}
if ([string]$collector.plan_hash -ne $ExpectedPlanHash) { throw "Collector plan hash mismatch." }
$collectorRunId = [string]$collector.run_id
if (-not $collectorRunId) { throw "Collector run_id is missing." }
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$collectorRunId.quality.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$collectorRunId.quality.visible.log"
}
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$QualityReportPath = Join-Path $OutputPath "quality-report.json"

if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_spot_perp_quality_preview_v1"
        mode = "PlanOnly"
        decision = "READY_FOR_VISIBLE_QUALITY"
        collector_run_id = $collectorRunId
        plan_hash = $ExpectedPlanHash
        candidate_count = [int]$validation.candidate_count
        collector_completed_tasks = [int]$collector.completed_tasks
        collector_error_count = [int]$collector.error_count
        output_path = $OutputPath
        quality_report_path = $QualityReportPath
        max_runtime_sec = $MaxRuntimeSec
        network_access = $false
        returns_read = $false
        pnl_read = $false
        oos_read = $false
        grid_search = $false
        live_orders = $false
        visible_terminal_required = $true
    } | ConvertTo-Json -Depth 12
    exit 0
}

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Worker token and launch record are required."
    }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) {
        throw "Worker token mismatch."
    }
    if ([string]$launch.plan_hash -ne $ExpectedPlanHash -or [string]$launch.collector_run_id -ne $collectorRunId) {
        throw "Worker launch identity mismatch."
    }
    $env:PYTHONUNBUFFERED = "1"
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate spot-perp quality - $collectorRunId" } catch { }
    Update-LaunchRecord @{ status = "RUNNING"; worker_pid = $PID; worker_started_at = ([DateTimeOffset]::Now.ToString("o")) }
    Write-Host "trading_mvp visible Gate spot/perp history quality" -ForegroundColor Cyan
    Write-Host "collector_run_id=$collectorRunId"
    Write-Host "plan_hash=$ExpectedPlanHash"
    Write-Host "input_tasks=$($collector.completed_tasks)"
    Write-Host "quality_report=$QualityReportPath"
    try {
        & $python $QualityModule `
            --plan $PlanPath `
            --expected-plan-hash $ExpectedPlanHash `
            --collector-manifest $CollectorManifestPath `
            --pit-state $PitStatePath `
            --out $OutputPath `
            --max-runtime-sec $MaxRuntimeSec 2>&1 | Tee-Object -FilePath $LogPath
        $exitCode = [int]$LASTEXITCODE
        if ($exitCode -ne 0) { throw "Quality process exited with code $exitCode." }
        if (-not (Test-Path -LiteralPath $QualityReportPath)) { throw "Quality report is missing." }
        $result = Get-Content -LiteralPath $QualityReportPath -Raw | ConvertFrom-Json
        if ($result.final -ne $true) { throw "Quality report is not final." }
        Update-LaunchRecord @{
            status = "COMPLETED"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            worker_exit_code = 0
            quality_decision = [string]$result.decision
            accepted_asset_count = [int]$result.accepted_asset_count
            quality_artifact_hash = [string]$result.artifact_hash
            quality_report_path = $QualityReportPath
        }
        Write-Host "QUALITY_COMPLETE decision=$($result.decision) accepted=$($result.accepted_asset_count)" -ForegroundColor Green
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        Update-LaunchRecord @{
            status = "STOPPED_INCOMPLETE"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            worker_exit_code = 1
            failure = $message
        }
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json | ConvertFrom-Json
$gateStatus = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
if ($gateStatus -eq "RUNNING") { throw "Active run gate is RUNNING: $($gate.run_id)" }
if ($gateStatus -eq "STOPPED_INCOMPLETE") { throw "Resolve STOPPED_INCOMPLETE before quality." }
if (Test-Path -LiteralPath $OutputPath) { throw "Refusing to overwrite quality output: $OutputPath" }
if (Test-Path -LiteralPath $LaunchRecordPath) { throw "Refusing to overwrite launch record: $LaunchRecordPath" }

$collectorSourceInfo = Get-Item -LiteralPath $CollectorModule
$collectorLaunchPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$collectorRunId.visible-launch.json"
$collectorLaunch = if (Test-Path -LiteralPath $collectorLaunchPath) {
    Get-Content -LiteralPath $collectorLaunchPath -Raw | ConvertFrom-Json
} else { $null }
$collectorStartedAt = if ($collectorLaunch -and $collectorLaunch.started_at) {
    $startedValue = $collectorLaunch.started_at
    if ($startedValue -is [DateTimeOffset]) { $startedValue }
    elseif ($startedValue -is [DateTime]) { [DateTimeOffset]$startedValue }
    else {
        [DateTimeOffset]::Parse(
            [string]$startedValue,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind
        )
    }
} else { $null }
$sourcePredatesCollect = $false
if ($collectorStartedAt) {
    $sourcePredatesCollect = $collectorSourceInfo.LastWriteTimeUtc -le $collectorStartedAt.UtcDateTime
}

$token = [Guid]::NewGuid().ToString("N")
$record = [ordered]@{
    schema = "trading_mvp_gate_spot_perp_quality_visible_launch_v1"
    project = "trading_mvp"
    status = "LAUNCHING"
    created_at = [DateTimeOffset]::Now.ToString("o")
    collector_run_id = $collectorRunId
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = Get-FileSha256 -Path $PlanPath
    collector_manifest_path = $CollectorManifestPath
    collector_manifest_sha256 = Get-FileSha256 -Path $CollectorManifestPath
    pit_state_path = $PitStatePath
    pit_state_sha256 = Get-FileSha256 -Path $PitStatePath
    quality_module_sha256 = Get-FileSha256 -Path $QualityModule
    collector_module_sha256 = Get-FileSha256 -Path $CollectorModule
    collector_module_last_write_utc = $collectorSourceInfo.LastWriteTimeUtc.ToString("o")
    collector_source_predates_collect = $sourcePredatesCollect
    code_provenance_level = "posthoc_hash_and_mtime_attestation_not_immutable_snapshot"
    output_path = $OutputPath
    quality_report_path = $QualityReportPath
    log_path = $LogPath
    python_runtime = $python
    max_runtime_sec = $MaxRuntimeSec
    visible_terminal = $true
    worker_token_sha256 = Get-TextSha256 -Value $token
    network_access = $false
    returns_read = $false
    pnl_read = $false
    oos_read = $false
    grid_search = $false
    retune = $false
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $record
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$arguments = @(
    "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$PSCommandPath`"",
    "-Worker", "-WorkerToken", "`"$token`"",
    "-PlanPath", "`"$PlanPath`"",
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-CollectorManifestPath", "`"$CollectorManifestPath`"",
    "-PitStatePath", "`"$PitStatePath`"",
    "-OutputPath", "`"$OutputPath`"",
    "-GatePath", "`"$GatePath`"",
    "-LaunchRecordPath", "`"$LaunchRecordPath`"",
    "-LogPath", "`"$LogPath`"",
    "-MaxRuntimeSec", "$MaxRuntimeSec",
    "-HoldOpenSec", "$HoldOpenSec"
)
$process = Start-Process -FilePath $pwsh -ArgumentList $arguments -WindowStyle Normal -PassThru
Update-LaunchRecord @{ status = "RUNNING"; worker_pid = $process.Id; started_at = ([DateTimeOffset]::Now.ToString("o")) }
Write-Host "Visible Gate spot/perp quality opened. PID=$($process.Id)" -ForegroundColor Green
Write-Host "Result: $QualityReportPath"
Write-Host "Log: $LogPath"

$waitMs = ($MaxRuntimeSec + $HoldOpenSec + 30) * 1000
if (-not $process.WaitForExit($waitMs)) {
    try { $process.Kill($true) } catch { }
    try { $process.WaitForExit(5000) } catch { }
    Update-LaunchRecord @{
        status = "STOPPED_INCOMPLETE"
        completed_at = ([DateTimeOffset]::Now.ToString("o"))
        worker_exit_code = -1
        failure = "Visible quality exceeded MaxRuntimeSec."
    }
    throw "Visible quality exceeded MaxRuntimeSec."
}
if ($process.ExitCode -ne 0) { throw "Visible quality exited with code $($process.ExitCode)." }
Get-Content -LiteralPath $LaunchRecordPath -Raw
