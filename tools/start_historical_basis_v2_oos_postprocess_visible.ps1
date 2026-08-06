[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$TrainPostprocessManifestPath,
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis-1h-v2\oos-postprocess",
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
$RunMvp = Join-Path $ProjectRoot "trading_mvp\run_mvp.ps1"
$OosPostprocessCli = Join-Path $ProjectRoot "trading_mvp\src\historical_basis_v2_oos_postprocess.py"
if (-not $GatePath) {
    $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json"
}

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        "C:\Program Files\Python313\python.exe",
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    $resolved = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($resolved) { return [System.IO.Path]::GetFullPath($resolved) }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python runtime not found. Set TRADING_MVP_PYTHON."
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
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

function Assert-GateAllowsOfflinePostprocess {
    if (-not (Test-Path -LiteralPath $GatePath)) {
        throw "Active run gate is missing: $GatePath"
    }
    $gate = Get-Content -LiteralPath $GatePath -Raw | ConvertFrom-Json
    $status = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
    if ($status -eq "RUNNING") {
        throw "OOS postprocess waits until the active market-data writer finishes."
    }
    if ($status -eq "STOPPED_INCOMPLETE") {
        throw "Resolve STOPPED_INCOMPLETE before OOS postprocess."
    }
    return $status
}

function Get-Preview {
    $python = Resolve-Python
    $raw = & $python $OosPostprocessCli `
        --plan $PlanPath `
        --expected-plan-hash $ExpectedPlanHash `
        --train-postprocess-manifest $TrainPostprocessManifestPath `
        --output-root $OutputRoot `
        --max-runtime-sec $MaxRuntimeSec `
        --plan-only
    if ($LASTEXITCODE -ne 0) {
        throw "OOS postprocess preview failed with exit code $LASTEXITCODE."
    }
    return ((@($raw) -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Update-LaunchRecord {
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    if (-not (Test-Path -LiteralPath $LaunchRecordPath)) { return }
    $record = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    foreach ($entry in $Values.GetEnumerator()) {
        Set-ObjectProperty -Object $record -Name ([string]$entry.Key) -Value $entry.Value
    }
    Write-JsonAtomic -Path $LaunchRecordPath -Value $record
}

$PlanPath = [System.IO.Path]::GetFullPath($PlanPath)
$TrainPostprocessManifestPath = [System.IO.Path]::GetFullPath($TrainPostprocessManifestPath)
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$gateStatus = Assert-GateAllowsOfflinePostprocess
$preview = Get-Preview
$collectorRunId = [string]$preview.collector_run_id
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$collectorRunId.oos-postprocess.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$collectorRunId.oos-postprocess.visible.log"
}
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)

if ($PlanOnly) {
    $preview | Add-Member -NotePropertyName "gate_status" -NotePropertyValue $gateStatus
    $preview | Add-Member -NotePropertyName "visible_terminal_required" -NotePropertyValue $true
    $preview | Add-Member -NotePropertyName "oos_postprocess_started" -NotePropertyValue $false
    $preview | Add-Member -NotePropertyName "launch_record_path" -NotePropertyValue $LaunchRecordPath
    $preview | Add-Member -NotePropertyName "log_path" -NotePropertyValue $LogPath
    $preview | ConvertTo-Json -Depth 20
    exit 0
}

if ([string]$preview.decision -ne "READY_FOR_VISIBLE_OOS_POSTPROCESS") {
    throw "OOS postprocess preview rejected launch: $($preview.decision)"
}

if ($Worker) {
    if (-not $WorkerToken) { throw "WorkerToken is required in worker mode." }
    if (-not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Worker launch record is missing: $LaunchRecordPath"
    }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) {
        throw "Worker token mismatch."
    }
    if (
        [string]$launch.collector_run_id -ne $collectorRunId -or
        [string]$launch.plan_hash -ne $ExpectedPlanHash
    ) {
        throw "Worker launch record does not match the frozen postprocess run."
    }
    $env:PYTHONUNBUFFERED = "1"
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp basis-v2 OOS postprocess - $collectorRunId" } catch { }
    Update-LaunchRecord -Values @{
        status = "RUNNING"
        worker_pid = $PID
        worker_started_at = ([DateTimeOffset]::Now.ToString("o"))
    }
    Write-Host "trading_mvp basis-v2 visible OOS full-evaluation postprocess" -ForegroundColor Cyan
    Write-Host "collector_run_id=$collectorRunId"
    Write-Host "plan_hash=$ExpectedPlanHash"
    Write-Host "output_root=$OutputRoot"
    try {
        & $RunMvp `
            -Action fast-edge-basis-v2-oos-postprocess `
            -PlanPath $PlanPath `
            -ExpectedPlanHash $ExpectedPlanHash `
            -ManifestPath $TrainPostprocessManifestPath `
            -OutputPath $OutputRoot `
            -ActiveRunGatePath $GatePath `
            -MaxRuntimeSec $MaxRuntimeSec 2>&1 | Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) {
            throw "run_mvp exited with code $LASTEXITCODE"
        }
        $resultPath = [string]$preview.paths.manifest
        if (-not (Test-Path -LiteralPath $resultPath)) {
            throw "OOS postprocess exited without final manifest: $resultPath"
        }
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ($result.final -ne $true -or $result.oos_read -ne $true -or $result.full_evaluation -ne $true) {
            throw "OOS postprocess result violates the full-evaluation contract."
        }
        Update-LaunchRecord -Values @{
            status = "COMPLETED"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            result_manifest_path = $resultPath
            result_status = [string]$result.status
            result_verdict = [string]$result.verdict
            deterministic_result_hash = [string]$result.deterministic_result_hash
            oos_read = $true
            full_evaluation = $true
            worker_exit_code = 0
        }
        Write-Host "OOS_POSTPROCESS_COMPLETE status=$($result.status) verdict=$($result.verdict)" -ForegroundColor Green
        Write-Host "result_manifest=$resultPath"
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 0
    } catch {
        $message = "{0}: {1}" -f $_.Exception.GetType().Name, $_.Exception.Message
        Update-LaunchRecord -Values @{
            status = "STOPPED_INCOMPLETE"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            failure = $message
            worker_exit_code = 1
        }
        Write-Host "STOPPED_INCOMPLETE: $message" -ForegroundColor Red
        if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
        exit 1
    }
}

if (Test-Path -LiteralPath $LaunchRecordPath) {
    throw "Refusing to overwrite immutable launch record: $LaunchRecordPath"
}

$token = [Guid]::NewGuid().ToString("N")
$launchRecord = [ordered]@{
    schema = "trading_mvp_basis_v2_visible_oos_postprocess_launch_v1"
    project = "trading_mvp"
    status = "LAUNCHING"
    created_at = [DateTimeOffset]::Now.ToString("o")
    collector_run_id = $collectorRunId
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    train_postprocess_manifest_path = $TrainPostprocessManifestPath
    train_postprocess_manifest_sha256 = [string]$preview.train_postprocess_manifest_sha256
    output_root = $OutputRoot
    result_manifest_path = [string]$preview.paths.manifest
    log_path = $LogPath
    cwd = $ProjectRoot
    max_runtime_sec = $MaxRuntimeSec
    visible_terminal = $true
    worker_token_sha256 = Get-TextSha256 -Value $token
    network_access = $false
    oos_read = $false
    oos_read_planned = $true
    full_evaluation = $true
    grid_search = $false
    retune = $false
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $launchRecord
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$arguments = @(
    "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$PSCommandPath`"",
    "-Worker", "-WorkerToken", "`"$token`"",
    "-PlanPath", "`"$PlanPath`"",
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-TrainPostprocessManifestPath", "`"$TrainPostprocessManifestPath`"",
    "-OutputRoot", "`"$OutputRoot`"",
    "-GatePath", "`"$GatePath`"",
    "-LaunchRecordPath", "`"$LaunchRecordPath`"",
    "-LogPath", "`"$LogPath`"",
    "-MaxRuntimeSec", "$MaxRuntimeSec",
    "-HoldOpenSec", "$HoldOpenSec"
)
$process = Start-Process -FilePath $pwsh -ArgumentList $arguments -WindowStyle Normal -PassThru
Update-LaunchRecord -Values @{
    status = "RUNNING"
    worker_pid = $process.Id
    started_at = ([DateTimeOffset]::Now.ToString("o"))
}
Write-Host "Visible basis-v2 OOS postprocess opened. PID=$($process.Id)" -ForegroundColor Green
Write-Host "Hard runtime limit: $MaxRuntimeSec sec"
Write-Host "Result: $($preview.paths.manifest)"
Write-Host "Log: $LogPath"

$waitMs = ($MaxRuntimeSec + $HoldOpenSec + 30) * 1000
if (-not $process.WaitForExit($waitMs)) {
    try { $process.Kill($true) } catch { }
    try { $process.WaitForExit(5000) } catch { }
    Update-LaunchRecord -Values @{
        status = "STOPPED_INCOMPLETE"
        completed_at = ([DateTimeOffset]::Now.ToString("o"))
        failure = "Visible OOS postprocess exceeded MaxRuntimeSec."
        worker_exit_code = -1
    }
    throw "Visible OOS postprocess exceeded MaxRuntimeSec."
}
if ($process.ExitCode -ne 0) {
    throw "Visible OOS postprocess exited with code $($process.ExitCode)."
}

Get-Content -LiteralPath $LaunchRecordPath -Raw

