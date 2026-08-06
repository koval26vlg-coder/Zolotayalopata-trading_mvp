param(
    [string]$RequestedStartLocal,
    [string]$HypothesisBankPath = "",
    [string]$ContinuousPolicyPath = "",
    [string]$PitSchedulePath = "",
    [string]$PriorManifestRoot = "",
    [string]$UniversePath = "",
    [string]$OutputPath = "",
    [int]$SegmentSec = 3600,
    [int]$DrainSec = 900,
    [int]$CertificationSec = 1200,
    [int]$TargetWriterSec = 0,
    [int]$MinPhaseHeadroomSec = 900,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $RequestedStartLocal) {
    throw "RequestedStartLocal is required."
}
if (-not $HypothesisBankPath) {
    $HypothesisBankPath = Join-Path $repoRoot "docs\research\trading_mvp_hypothesis_bank_v1.json"
}
if (-not $ContinuousPolicyPath) {
    $ContinuousPolicyPath = Join-Path $repoRoot "docs\plans\trading-mvp-continuous-production-policy-v1.json"
}
if (-not $PitSchedulePath) {
    $policy = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "docs\plans\trading-mvp-autopilot-policy-v1.json") | ConvertFrom-Json
    $PitSchedulePath = [string]$policy.current_pit_schedule.plan_path
}
if (-not $PriorManifestRoot) {
    $PriorManifestRoot = Join-Path $repoRoot "exports\trading-mvp\raw-durable\ws_durable_72h_20260704_000015"
}
if (-not $UniversePath) {
    $UniversePath = Join-Path $repoRoot "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv"
}
if (-not $OutputPath) {
    $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
    $OutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\campaigns\dense-ws-feasibility-$stamp.json"
}

function Resolve-Python {
    foreach ($candidate in @(
        $env:TRADING_MVP_PYTHON,
        "C:\Program Files\Python313\python.exe",
        (Join-Path $repoRoot ".venv\Scripts\python.exe")
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "Python runtime not found."
}

$python = Resolve-Python
$script = Join-Path $repoRoot "trading_mvp\src\dense_ws_campaign_feasibility.py"
$arguments = @(
    $script,
    "--hypothesis-bank", $HypothesisBankPath,
    "--continuous-policy", $ContinuousPolicyPath,
    "--pit-schedule", $PitSchedulePath,
    "--prior-manifest-root", $PriorManifestRoot,
    "--universe", $UniversePath,
    "--requested-start-local", $RequestedStartLocal,
    "--output", $OutputPath,
    "--segment-sec", [string]$SegmentSec,
    "--drain-sec", [string]$DrainSec,
    "--certification-sec", [string]$CertificationSec,
    "--min-phase-headroom-sec", [string]$MinPhaseHeadroomSec
)
if ($TargetWriterSec -gt 0) {
    $arguments += @("--target-writer-sec", [string]$TargetWriterSec)
}
$output = & $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Dense-WS feasibility estimator failed with exit code $LASTEXITCODE."
}
$result = ($output | Out-String).Trim() | ConvertFrom-Json
if ($Json) {
    $result | ConvertTo-Json -Depth 20
    exit 0
}

Write-Host "dense WS campaign feasibility PlanOnly" -ForegroundColor Cyan
Write-Host "Verdict: $($result.verdict)"
Write-Host "Window: $($result.window_feasibility.window_id)"
Write-Host "Writer: $($result.window_feasibility.planned_writer_sec) sec"
Write-Host "Complete segments: $($result.window_feasibility.complete_durable_segments)"
Write-Host "Collector started: $($result.would_start)"
Write-Host "Output: $OutputPath"
