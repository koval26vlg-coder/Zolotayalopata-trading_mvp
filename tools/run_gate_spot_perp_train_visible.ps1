[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ParentPlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedParentPlanHash,
    [Parameter(Mandatory = $true)][string]$QualityReportPath,
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
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
$SourceRoot = Join-Path $ProjectRoot "trading_mvp\src"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $LaunchRecordPath) {
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId.visible-launch.json"
}
if (-not $LogPath) {
    $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.visible.log"
}

function Resolve-Python {
    foreach ($candidate in @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }) {
        if (Test-Path -LiteralPath $candidate) { return [System.IO.Path]::GetFullPath($candidate) }
    }
    throw "Python runtime is required."
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace("-", "").ToLowerInvariant()
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
        $Value | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
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

function New-CodeSnapshot {
    param([Parameter(Mandatory = $true)][string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $entries = [System.Collections.Generic.List[object]]::new()
    foreach ($source in Get-ChildItem -LiteralPath $SourceRoot -File -Filter "*.py" | Sort-Object Name) {
        $target = Join-Path $Destination $source.Name
        Copy-Item -LiteralPath $source.FullName -Destination $target
        $entries.Add([ordered]@{
            file = $source.Name
            sha256 = Get-FileSha256 -Path $target
            bytes = (Get-Item -LiteralPath $target).Length
        }) | Out-Null
    }
    $canonical = (($entries | ForEach-Object { "$($_.file)|$($_.sha256)|$($_.bytes)" }) -join "`n") + "`n"
    $snapshotHash = Get-TextSha256 -Value $canonical
    $manifestPath = Join-Path $Destination "code-snapshot-manifest.json"
    $manifest = [ordered]@{
        schema = "trading_mvp_python_code_snapshot_v1"
        created_at = [DateTimeOffset]::Now.ToString("o")
        immutable = $true
        source_root = $SourceRoot
        file_count = $entries.Count
        files = $entries
        code_snapshot_hash = $snapshotHash
    }
    Write-JsonAtomic -Path $manifestPath -Value $manifest
    return [pscustomobject]@{
        directory = $Destination
        manifest_path = $manifestPath
        manifest_sha256 = Get-FileSha256 -Path $manifestPath
        code_snapshot_hash = $snapshotHash
        train_module = (Join-Path $Destination "spot_perp_basis_history_v2_train.py")
    }
}

$ParentPlanPath = [System.IO.Path]::GetFullPath($ParentPlanPath)
$QualityReportPath = [System.IO.Path]::GetFullPath($QualityReportPath)
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$python = Resolve-Python
$TrainInputRoot = Join-Path $OutputRoot "train-inputs"
$TrainPlanPath = Join-Path $OutputRoot "train-plan.json"
$TrainResultPath = Join-Path $OutputRoot "train-result.json"
$CodeSnapshotDir = Join-Path $OutputRoot "code-snapshot"

foreach ($required in @($ParentPlanPath, $QualityReportPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file is missing: $required" }
}

if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_spot_perp_train_visible_preview_v1"
        mode = "PlanOnly"
        decision = "READY_FOR_VISIBLE_TRAIN_FREEZE_AND_EVALUATE"
        run_id = $RunId
        parent_plan_hash = $ExpectedParentPlanHash
        output_root = $OutputRoot
        train_input_root = $TrainInputRoot
        train_plan_path = $TrainPlanPath
        train_result_path = $TrainResultPath
        max_runtime_sec = $MaxRuntimeSec
        immutable_code_snapshot = $true
        network_access = $false
        oos_read = $false
        grid_search = $false
        retune = $false
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
    if ((Get-TextSha256 -Value $WorkerToken) -ne [string]$launch.worker_token_sha256) { throw "Worker token mismatch." }
    if ([string]$launch.run_id -ne $RunId -or [string]$launch.parent_plan_hash -ne $ExpectedParentPlanHash) {
        throw "Worker launch identity mismatch."
    }
    $deadline = [DateTimeOffset]::Now.AddSeconds($MaxRuntimeSec)
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate spot-perp train - $RunId" } catch { }
    $env:PYTHONUNBUFFERED = "1"
    Update-LaunchRecord @{ status = "RUNNING"; worker_pid = $PID; worker_started_at = ([DateTimeOffset]::Now.ToString("o")) }
    Write-Host "trading_mvp visible Gate spot/perp train-only freeze + evaluate" -ForegroundColor Cyan
    Write-Host "run_id=$RunId"
    Write-Host "parent_plan_hash=$ExpectedParentPlanHash"
    Write-Host "hard_deadline=$($deadline.ToString('o'))"
    try {
        New-Item -ItemType Directory -Path $OutputRoot -ErrorAction Stop | Out-Null
        $snapshot = New-CodeSnapshot -Destination $CodeSnapshotDir
        $env:TRADING_MVP_CODE_SNAPSHOT_MANIFEST = $snapshot.manifest_path
        $env:TRADING_MVP_CODE_SNAPSHOT_MANIFEST_SHA256 = $snapshot.manifest_sha256
        $env:TRADING_MVP_CODE_SNAPSHOT_HASH = $snapshot.code_snapshot_hash
        Update-LaunchRecord @{
            code_snapshot_manifest = $snapshot.manifest_path
            code_snapshot_manifest_sha256 = $snapshot.manifest_sha256
            code_snapshot_hash = $snapshot.code_snapshot_hash
        }
        Write-Host "code_snapshot_hash=$($snapshot.code_snapshot_hash)"
        $remaining = [Math]::Max(1, [Math]::Min(600, [int]($deadline - [DateTimeOffset]::Now).TotalSeconds))
        & $python $snapshot.train_module freeze `
            --parent-plan $ParentPlanPath `
            --expected-parent-plan-hash $ExpectedParentPlanHash `
            --quality-report $QualityReportPath `
            --train-input-root $TrainInputRoot `
            --out-plan $TrainPlanPath `
            --max-runtime-sec $remaining 2>&1 | Tee-Object -FilePath $LogPath
        if ($LASTEXITCODE -ne 0) { throw "Train freeze exited with code $LASTEXITCODE." }
        $trainPlan = Get-Content -LiteralPath $TrainPlanPath -Raw | ConvertFrom-Json
        $trainPlanHash = [string]$trainPlan.plan_hash
        if (-not $trainPlanHash) { throw "Frozen train plan hash is missing." }
        Write-Host "train_plan_hash=$trainPlanHash" -ForegroundColor Yellow
        $remaining = [Math]::Max(1, [int]($deadline - [DateTimeOffset]::Now).TotalSeconds)
        & $python $snapshot.train_module evaluate `
            --train-plan $TrainPlanPath `
            --expected-train-plan-hash $trainPlanHash `
            --out $TrainResultPath `
            --max-runtime-sec $remaining 2>&1 | Tee-Object -FilePath $LogPath -Append
        if ($LASTEXITCODE -ne 0) { throw "Train evaluation exited with code $LASTEXITCODE." }
        $result = Get-Content -LiteralPath $TrainResultPath -Raw | ConvertFrom-Json
        if ($result.final -ne $true -or $result.oos_read -ne $false -or $result.deterministic_repeat_match -ne $true) {
            throw "Train result violates finality, embargo, or determinism contract."
        }
        Update-LaunchRecord @{
            status = "COMPLETED"
            completed_at = ([DateTimeOffset]::Now.ToString("o"))
            worker_exit_code = 0
            train_plan_path = $TrainPlanPath
            train_plan_hash = $trainPlanHash
            train_result_path = $TrainResultPath
            train_decision = [string]$result.decision
            episode_count = [int]$result.metrics.episode_count
            deterministic_result_hash = [string]$result.deterministic_result_hash
        }
        Write-Host "TRAIN_COMPLETE decision=$($result.decision) episodes=$($result.metrics.episode_count)" -ForegroundColor Green
        Write-Host "result=$TrainResultPath"
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
if ($gateStatus -eq "STOPPED_INCOMPLETE") { throw "Resolve STOPPED_INCOMPLETE before train evaluation." }
if (Test-Path -LiteralPath $OutputRoot) { throw "Refusing to overwrite train output: $OutputRoot" }
if (Test-Path -LiteralPath $LaunchRecordPath) { throw "Refusing to overwrite launch record: $LaunchRecordPath" }

$token = [Guid]::NewGuid().ToString("N")
$record = [ordered]@{
    schema = "trading_mvp_gate_spot_perp_train_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    created_at = [DateTimeOffset]::Now.ToString("o")
    parent_plan_path = $ParentPlanPath
    parent_plan_hash = $ExpectedParentPlanHash
    parent_plan_sha256 = Get-FileSha256 -Path $ParentPlanPath
    quality_report_path = $QualityReportPath
    quality_report_sha256 = Get-FileSha256 -Path $QualityReportPath
    output_root = $OutputRoot
    log_path = $LogPath
    python_runtime = $python
    max_runtime_sec = $MaxRuntimeSec
    visible_terminal = $true
    worker_token_sha256 = Get-TextSha256 -Value $token
    network_access = $false
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
    "-ParentPlanPath", "`"$ParentPlanPath`"",
    "-ExpectedParentPlanHash", $ExpectedParentPlanHash,
    "-QualityReportPath", "`"$QualityReportPath`"",
    "-RunId", $RunId,
    "-OutputRoot", "`"$OutputRoot`"",
    "-GatePath", "`"$GatePath`"",
    "-LaunchRecordPath", "`"$LaunchRecordPath`"",
    "-LogPath", "`"$LogPath`"",
    "-MaxRuntimeSec", "$MaxRuntimeSec",
    "-HoldOpenSec", "$HoldOpenSec"
)
$process = Start-Process -FilePath $pwsh -ArgumentList $arguments -WindowStyle Normal -PassThru
Update-LaunchRecord @{ status = "RUNNING"; worker_pid = $process.Id; started_at = ([DateTimeOffset]::Now.ToString("o")) }
Write-Host "Visible Gate spot/perp train opened. PID=$($process.Id)" -ForegroundColor Green
Write-Host "Output: $OutputRoot"
Write-Host "Log: $LogPath"
$waitMs = ($MaxRuntimeSec + $HoldOpenSec + 30) * 1000
if (-not $process.WaitForExit($waitMs)) {
    try { $process.Kill($true) } catch { }
    try { $process.WaitForExit(5000) } catch { }
    Update-LaunchRecord @{
        status = "STOPPED_INCOMPLETE"
        completed_at = ([DateTimeOffset]::Now.ToString("o"))
        worker_exit_code = -1
        failure = "Visible train exceeded MaxRuntimeSec."
    }
    throw "Visible train exceeded MaxRuntimeSec."
}
if ($process.ExitCode -ne 0) { throw "Visible train exited with code $($process.ExitCode)." }
Get-Content -LiteralPath $LaunchRecordPath -Raw
