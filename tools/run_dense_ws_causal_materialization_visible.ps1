[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)][string]$QualityReportPath,
    [Parameter(Mandatory = $true)][string]$LabelsOutputPath,
    [Parameter(Mandatory = $true)][string]$SnapshotsOutputPath,
    [Parameter(Mandatory = $true)][string]$ManifestOutputPath,
    [string]$LogPath = "",
    [ValidateRange(1, 1800)][int]$MaxRuntimeSec = 1800,
    [ValidateRange(0, 120)][int]$HoldOpenSec = 60
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Materializer = Join-Path $ProjectRoot 'trading_mvp\src\dense_ws_causal_materializer.py'
$GuardChecker = Join-Path $ProjectRoot 'tools\check_trading_mvp_autopilot.ps1'

function Resolve-TradingMvpPython {
    $candidates = @(
        $env:TRADING_MVP_PYTHON,
        'C:\Program Files\Python313\python.exe',
        (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
        (Join-Path $ProjectRoot 'trading_mvp\.venv\Scripts\python.exe'),
        'C:\Users\koval\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw 'Python runtime is unavailable. Set TRADING_MVP_PYTHON.'
}

function Resolve-RequiredFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$PlanPath = Resolve-RequiredFile -Path $PlanPath
$QualityReportPath = Resolve-RequiredFile -Path $QualityReportPath
$Materializer = Resolve-RequiredFile -Path $Materializer
$GuardChecker = Resolve-RequiredFile -Path $GuardChecker
$LabelsOutputPath = [System.IO.Path]::GetFullPath($LabelsOutputPath)
$SnapshotsOutputPath = [System.IO.Path]::GetFullPath($SnapshotsOutputPath)
$ManifestOutputPath = [System.IO.Path]::GetFullPath($ManifestOutputPath)
$outputPaths = @($LabelsOutputPath, $SnapshotsOutputPath, $ManifestOutputPath)
if (($outputPaths | Select-Object -Unique).Count -ne 3) {
    throw 'Materialization output paths must be distinct.'
}
foreach ($path in $outputPaths) {
    if (Test-Path -LiteralPath $path) {
        throw "Refusing to overwrite immutable output: $path"
    }
}
if (-not $LogPath) {
    $LogPath = "$ManifestOutputPath.visible.log"
}
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
if (Test-Path -LiteralPath $LogPath) {
    throw "Refusing to overwrite visible log: $LogPath"
}
$logParent = Split-Path -Parent $LogPath
if ($logParent) {
    New-Item -ItemType Directory -Force -Path $logParent | Out-Null
}

$guardRaw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $GuardChecker -Json
if ($LASTEXITCODE -ne 0) {
    throw 'Authoritative trading MVP guard failed.'
}
$guard = (@($guardRaw) -join [Environment]::NewLine) | ConvertFrom-Json
if ([string]$guard.usage.status -ne 'AVAILABLE' -or [string]$guard.usage.decision -ne 'CONTINUE') {
    throw 'Weekly usage telemetry is unavailable, stale, or paused.'
}
$remainingPercent = [double]$guard.usage.remaining_percent
if ($remainingPercent -le 15.0) {
    throw "Weekly remaining_percent=$remainingPercent blocks new materialization."
}
if ([bool]$guard.stop_new_actions) {
    throw "Authoritative guard blocks new actions: $($guard.decision)"
}
$gateStatus = [string]$guard.gate.status
if ($gateStatus -ne 'READY_FOR_POSTPROCESS') {
    throw "Active run gate must be READY_FOR_POSTPROCESS, observed=$gateStatus."
}
if ([bool]$guard.action_due) {
    throw 'A higher-priority approved action is due; materialization is deferred.'
}
$pitEtaSec = $null
if ($guard.schedule_window -and $null -ne $guard.schedule_window.eta_sec) {
    $pitEtaSec = [int]$guard.schedule_window.eta_sec
}
if ($null -ne $pitEtaSec -and $pitEtaSec -ge 0 -and $pitEtaSec -le ($MaxRuntimeSec + 60)) {
    throw "PIT segment is due too soon for this bounded run: eta_sec=$pitEtaSec."
}

$Python = Resolve-TradingMvpPython
$arguments = @(
    '-u', $Materializer,
    '--plan', $PlanPath,
    '--expected-plan-hash', $ExpectedPlanHash.ToLowerInvariant(),
    '--quality-report', $QualityReportPath,
    '--labels-output', $LabelsOutputPath,
    '--snapshots-output', $SnapshotsOutputPath,
    '--manifest-output', $ManifestOutputPath,
    '--max-runtime-sec', [string]$MaxRuntimeSec
)

$startedAt = [DateTimeOffset]::Now
@(
    "[$($startedAt.ToString('o'))] VISIBLE_BOUNDED_CAUSAL_MATERIALIZATION",
    "plan_hash=$($ExpectedPlanHash.ToLowerInvariant())",
    "max_runtime_sec=$MaxRuntimeSec",
    "labels_output=$LabelsOutputPath",
    "snapshots_output=$SnapshotsOutputPath",
    "manifest_output=$ManifestOutputPath",
    "weekly_remaining_percent=$remainingPercent"
) | Tee-Object -FilePath $LogPath

& $Python @arguments 2>&1 | Tee-Object -FilePath $LogPath -Append
$exitCode = [int]$LASTEXITCODE
$elapsedSec = [math]::Round(([DateTimeOffset]::Now - $startedAt).TotalSeconds, 3)
"[$([DateTimeOffset]::Now.ToString('o'))] exit_code=$exitCode elapsed_sec=$elapsedSec" |
    Tee-Object -FilePath $LogPath -Append
if ($exitCode -ne 0) {
    throw "Causal materialization exited with code $exitCode. See $LogPath"
}
if (-not (Test-Path -LiteralPath $ManifestOutputPath -PathType Leaf)) {
    throw "Materialization manifest is missing: $ManifestOutputPath"
}
$manifest = Get-Content -LiteralPath $ManifestOutputPath -Raw | ConvertFrom-Json
if ([string]$manifest.plan_hash -ne $ExpectedPlanHash.ToLowerInvariant()) {
    throw 'Persisted materialization plan hash mismatch.'
}
Write-Host (
    'MATERIALIZATION_COMPLETE decision={0} snapshots={1} manifest={2}' -f
    $manifest.decision,
    $manifest.execution_snapshots.rows,
    $ManifestOutputPath
) -ForegroundColor Green
if ($HoldOpenSec -gt 0) {
    Write-Host "Terminal closes in $HoldOpenSec seconds."
    Start-Sleep -Seconds $HoldOpenSec
}
exit 0
