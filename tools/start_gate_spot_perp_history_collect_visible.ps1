[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$OutputRoot = "E:\ZolotyayLopata-data\exports\trading-mvp\gate-spot-perp-v2",
    [string]$GatePath = "",
    [string]$LaunchRecordPath = "",
    [string]$LogPath = "",
    [ValidateRange(1, 7200)][int]$MaxRuntimeSec = 1200,
    [ValidateRange(1, 12)][int]$Workers = 6,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60,
    [ValidateRange(1, 100000)][double]$MinimumFreeGb = 10,
    [string]$ApprovedNotBefore = "",
    [string]$ApprovedNotLaterThan = "",
    [switch]$ConfirmedPublicHistoryCollect,
    [switch]$Resume,
    [switch]$PlanOnly,
    [switch]$Worker,
    [string]$WorkerToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PlanModule = Join-Path $ProjectRoot "trading_mvp\src\spot_perp_basis_history_v2.py"
$Collector = Join-Path $ProjectRoot "trading_mvp\src\spot_perp_basis_history_v2_collector.py"
$GateChecker = Join-Path $ProjectRoot "tools\check_active_run_gate.ps1"
if (-not $GatePath) { $GatePath = Join-Path $ProjectRoot "docs\agent-log\active-run-gate.json" }
if (-not $LaunchRecordPath) {
    $suffix = if ($Resume) { ".resume.$(Get-Date -Format 'yyyyMMdd_HHmmss')" } else { "" }
    $LaunchRecordPath = Join-Path $ProjectRoot "docs\agent-log\run-gates\$RunId$suffix.visible-launch.json"
}
if (-not $LogPath) { $LogPath = Join-Path $ProjectRoot "exports\trading-mvp\run\$RunId.visible.log" }
$ManifestPath = Join-Path (Join-Path (Join-Path $OutputRoot "runs") $RunId) "manifest.json"

function Resolve-Python {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "trading_mvp\.venv\Scripts\python.exe"),
        "C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        & $candidate -c "import requests" 2>$null
        if ($LASTEXITCODE -eq 0) { return [System.IO.Path]::GetFullPath($candidate) }
    }
    throw "Python runtime with requests is required."
}

function Write-JsonAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temp = "$Path.tmp.$PID.$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    try {
        $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Parse-Time {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [DateTimeOffset]::Parse(
        $Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
}

function Get-Window {
    param([switch]$AllowDefaults)
    $now = [DateTimeOffset]::Now
    if ($ApprovedNotBefore) { $start = Parse-Time $ApprovedNotBefore }
    elseif ($AllowDefaults) { $start = $now }
    else { throw "ApprovedNotBefore is required for an actual collect." }
    if ($ApprovedNotLaterThan) { $end = Parse-Time $ApprovedNotLaterThan }
    elseif ($AllowDefaults) { $end = $start.AddSeconds($MaxRuntimeSec + 120) }
    else { throw "ApprovedNotLaterThan is required for an actual collect." }
    if ($end -le $start) { throw "ApprovedNotLaterThan must be after ApprovedNotBefore." }
    return [pscustomobject]@{ start = $start; end = $end }
}

function Get-FreeGb {
    param([Parameter(Mandatory = $true)][string]$Path)
    $root = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($Path))
    $drive = Get-PSDrive -Name $root.TrimEnd('\').TrimEnd(':') -ErrorAction Stop
    return [Math]::Round($drive.Free / 1GB, 3)
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
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$GatePath = [System.IO.Path]::GetFullPath($GatePath)
$LaunchRecordPath = [System.IO.Path]::GetFullPath($LaunchRecordPath)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$python = Resolve-Python
$env:TRADING_MVP_PYTHON = $python
$validationRaw = & $python $PlanModule validate-plan --plan $PlanPath --expected-plan-hash $ExpectedPlanHash
if ($LASTEXITCODE -ne 0) { throw "Gate spot/perp plan validation failed." }
$validation = (@($validationRaw) -join [Environment]::NewLine) | ConvertFrom-Json
$window = Get-Window -AllowDefaults
$freeGb = Get-FreeGb -Path $OutputRoot

if ($Worker) {
    if (-not $WorkerToken -or -not (Test-Path -LiteralPath $LaunchRecordPath)) {
        throw "Worker token and launch record are required."
    }
    $launch = Get-Content -LiteralPath $LaunchRecordPath -Raw | ConvertFrom-Json
    if ((Get-TextSha256 $WorkerToken) -ne [string]$launch.worker_token_sha256) { throw "Worker token mismatch." }
    if ([string]$launch.plan_hash -ne $ExpectedPlanHash -or [string]$launch.run_id -ne $RunId) {
        throw "Worker launch identity mismatch."
    }
    $window = Get-Window
    $now = [DateTimeOffset]::Now
    if ($now -lt $window.start -or $now -ge $window.end) { throw "Worker started outside the approved window." }
    try { $Host.UI.RawUI.WindowTitle = "trading_mvp Gate spot-perp history - $RunId" } catch { }
    $env:PYTHONUNBUFFERED = "1"
    Update-LaunchRecord @{ status = "RUNNING"; worker_pid = $PID; worker_started_at = $now.ToString("o") }
    Write-Host "trading_mvp visible Gate spot/perp public history collect" -ForegroundColor Cyan
    Write-Host "run_id=$RunId"
    Write-Host "plan_hash=$ExpectedPlanHash"
    Write-Host "hard_deadline=$($window.end.ToString('o'))"
    Write-Host "manifest=$ManifestPath"
    $arguments = @(
        $Collector,
        "--plan", $PlanPath,
        "--expected-plan-hash", $ExpectedPlanHash,
        "--output-root", $OutputRoot,
        "--run-id", $RunId,
        "--max-runtime-sec", "$MaxRuntimeSec",
        "--gate-path", $GatePath,
        "--workers", "$Workers"
    )
    if ($Resume) { $arguments += "--resume" }
    & $python @arguments 2>&1 | Tee-Object -FilePath $LogPath
    $exitCode = [int]$LASTEXITCODE
    $status = if ($exitCode -eq 0) { "COMPLETED" } else { "STOPPED_INCOMPLETE" }
    Update-LaunchRecord @{
        status = $status
        completed_at = ([DateTimeOffset]::Now.ToString("o"))
        worker_exit_code = $exitCode
        manifest_path = $ManifestPath
    }
    if ($exitCode -eq 0) { Write-Host "READY_FOR_POSTPROCESS" -ForegroundColor Green }
    else { Write-Host "STOPPED_INCOMPLETE: use visible resume with the same run_id" -ForegroundColor Red }
    if ($HoldOpenSec -gt 0) { Start-Sleep -Seconds $HoldOpenSec }
    exit $exitCode
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GateChecker -GatePath $GatePath -Json | ConvertFrom-Json
$gateStatus = if ($gate.gate_status) { [string]$gate.gate_status } else { [string]$gate.status }
if ($gateStatus -eq "RUNNING") { throw "Active run gate is RUNNING: $($gate.run_id)" }
if ($gateStatus -eq "STOPPED_INCOMPLETE" -and -not $Resume) { throw "Resolve or resume STOPPED_INCOMPLETE before a new collect." }
$approvalPhrase = "Подтверждаю visible Gate spot/perp history collect plan_hash=$ExpectedPlanHash, run_id=$RunId, MaxRuntimeSec=$MaxRuntimeSec, hard deadline=$($window.end.ToString('o')), public API only, без grid/OOS/live/private API keys."

if ($PlanOnly) {
    [ordered]@{
        schema = "trading_mvp_gate_spot_perp_visible_collect_preview_v1"
        mode = "PlanOnly"
        decision = "AWAIT_EXPLICIT_GATE_SPOT_PERP_HISTORY_COLLECT_APPROVAL"
        plan_path = $PlanPath
        plan_hash = $ExpectedPlanHash
        candidate_count = [int]$validation.candidate_count
        run_id = $RunId
        output_root = $OutputRoot
        manifest_path = $ManifestPath
        max_runtime_sec = $MaxRuntimeSec
        expected_tasks = [int]$validation.candidate_count * 32
        approved_not_before = $window.start.ToString("o")
        approved_not_later_than = $window.end.ToString("o")
        free_gb = $freeGb
        minimum_free_gb = $MinimumFreeGb
        visible_terminal_required = $true
        collector_started = $false
        auto_resume = $false
        grid_search = $false
        oos_read = $false
        live_orders = $false
        private_api_keys = $false
        approval_phrase = $approvalPhrase
    } | ConvertTo-Json -Depth 12
    exit 0
}

if (-not $ConfirmedPublicHistoryCollect) { throw "ConfirmedPublicHistoryCollect is required. Run -PlanOnly first." }
$window = Get-Window
$now = [DateTimeOffset]::Now
if ($now -lt $window.start -or $now -ge $window.end) { throw "Current time is outside the approved window." }
if ($freeGb -lt $MinimumFreeGb) { throw "Disk guard failed: free_gb=$freeGb minimum_free_gb=$MinimumFreeGb" }
if (Test-Path -LiteralPath (Join-Path $OutputRoot ".gate-spot-perp-history-writer.lock")) {
    throw "Gate spot/perp writer lease already exists."
}
if (-not $Resume -and (Test-Path -LiteralPath (Split-Path -Parent $ManifestPath))) {
    throw "Refusing to overwrite existing run directory: $(Split-Path -Parent $ManifestPath)"
}
if ($Resume -and -not (Test-Path -LiteralPath $ManifestPath)) { throw "Resume manifest is missing: $ManifestPath" }
if (Test-Path -LiteralPath $LaunchRecordPath) { throw "Refusing to overwrite launch record: $LaunchRecordPath" }

$token = [Guid]::NewGuid().ToString("N")
$record = [ordered]@{
    schema = "trading_mvp_gate_spot_perp_visible_launch_v1"
    project = "trading_mvp"
    run_id = $RunId
    status = "LAUNCHING"
    created_at = $now.ToString("o")
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    output_root = $OutputRoot
    manifest_path = $ManifestPath
    log_path = $LogPath
    max_runtime_sec = $MaxRuntimeSec
    workers = $Workers
    approved_not_before = $window.start.ToString("o")
    approved_not_later_than = $window.end.ToString("o")
    minimum_free_gb = $MinimumFreeGb
    free_gb_at_launch = $freeGb
    expected_tasks = [int]$validation.candidate_count * 32
    visible_terminal = $true
    resume = [bool]$Resume
    auto_resume = $false
    worker_token_sha256 = Get-TextSha256 $token
    research_only = $true
    live_orders = $false
    private_api_keys = $false
    leverage_or_margin = $false
}
Write-JsonAtomic -Path $LaunchRecordPath -Value $record
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

$pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$workerArgs = @(
    "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$PSCommandPath`"",
    "-Worker", "-WorkerToken", "`"$token`"",
    "-PlanPath", "`"$PlanPath`"",
    "-ExpectedPlanHash", $ExpectedPlanHash,
    "-RunId", $RunId,
    "-OutputRoot", "`"$OutputRoot`"",
    "-GatePath", "`"$GatePath`"",
    "-LaunchRecordPath", "`"$LaunchRecordPath`"",
    "-LogPath", "`"$LogPath`"",
    "-MaxRuntimeSec", "$MaxRuntimeSec",
    "-Workers", "$Workers",
    "-HoldOpenSec", "$HoldOpenSec",
    "-MinimumFreeGb", "$MinimumFreeGb",
    "-ApprovedNotBefore", "`"$($window.start.ToString('o'))`"",
    "-ApprovedNotLaterThan", "`"$($window.end.ToString('o'))`""
)
if ($Resume) { $workerArgs += "-Resume" }
$process = Start-Process -FilePath $pwsh -ArgumentList $workerArgs -WindowStyle Normal -PassThru
Update-LaunchRecord @{ status = "RUNNING"; worker_pid = $process.Id; started_at = ([DateTimeOffset]::Now.ToString("o")) }
[ordered]@{
    schema = "trading_mvp_gate_spot_perp_visible_launch_result_v1"
    decision = "VISIBLE_COLLECT_LAUNCHED"
    run_id = $RunId
    worker_pid = $process.Id
    plan_hash = $ExpectedPlanHash
    manifest_path = $ManifestPath
    log_path = $LogPath
    launch_record_path = $LaunchRecordPath
    hard_deadline = $window.end.ToString("o")
    visible_terminal = $true
    auto_resume = $false
} | ConvertTo-Json -Depth 10
