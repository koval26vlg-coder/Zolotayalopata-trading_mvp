param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [string]$QualityPath = "",
    [string]$OutputPath = "",
    [string]$RequiredExchanges = "gateio,mexc",
    [string]$RuleRevision = "whole_cycle_two_venue_availability_v1",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$python = if ($env:TRADING_MVP_PYTHON) { $env:TRADING_MVP_PYTHON } else { "C:\Program Files\Python313\python.exe" }
$module = Join-Path $repoRoot "trading_mvp\src\pit_universe_clean_slice_spec.py"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Value))
}

$ManifestPath = Resolve-FullPath $ManifestPath
if (-not (Test-Path -LiteralPath $ManifestPath)) { throw "Manifest not found: $ManifestPath" }
if (-not (Test-Path -LiteralPath $python)) { throw "Python runtime not found: $python" }
if (-not (Test-Path -LiteralPath $module)) { throw "PlanOnly module not found: $module" }

$sourceDir = Split-Path -Parent $ManifestPath
if (-not $QualityPath) { $QualityPath = Join-Path $sourceDir "data_quality.json" }
$QualityPath = Resolve-FullPath $QualityPath
if (-not (Test-Path -LiteralPath $QualityPath)) { throw "Quality artifact not found: $QualityPath" }

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\pit_two_venue_clean_slice_spec_planonly_$timestamp.json"
}
$OutputPath = Resolve-FullPath $OutputPath

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -ne "READY_FOR_POSTPROCESS") {
    throw "Active run gate must be READY_FOR_POSTPROCESS; observed $($gate.status)"
}
if ([bool]$gate.replay_allowed) {
    throw "PlanOnly spec requires replay_allowed=false"
}

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ([string]$manifest.run_id -ne [string]$gate.run_id) {
    throw "Gate run_id does not match manifest run_id"
}
$quality = Get-Content -LiteralPath $QualityPath -Raw | ConvertFrom-Json
$qualityReasons = @($quality.reasons | ForEach-Object { [string]$_ })
if (
    [string]$quality.decision -ne "PIT_UNIVERSE_DATA_QUALITY_REJECTED" -or
    [bool]$quality.replay_allowed -or
    $qualityReasons.Count -ne 1 -or
    $qualityReasons[0] -ne "insufficient_exchange_coverage"
) {
    throw "Clean-slice spec is allowed only for a fail-closed quality reject solely due to insufficient_exchange_coverage"
}

Write-Host "PIT two-venue clean-slice specification PlanOnly" -ForegroundColor Cyan
Write-Host "Run ID: $($manifest.run_id)"
Write-Host "Hashing immutable source artifacts; no filtered dataset will be created."
$arguments = @(
    $module,
    "--manifest", $ManifestPath,
    "--out", $OutputPath,
    "--required-exchanges", $RequiredExchanges,
    "--rule-revision", $RuleRevision
)
& $python @arguments | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Clean-slice specification failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $OutputPath)) { throw "Specification output was not created: $OutputPath" }

$result = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
if ($Json) {
    $result | ConvertTo-Json -Depth 30
    exit 0
}
Write-Host "Decision: $($result.decision)"
Write-Host "Retained cycles/rows: $($result.mask.retained_cycle_count) / $($result.mask.retained_rows)"
Write-Host "Dropped cycles/rows: $($result.mask.dropped_cycle_count) / $($result.mask.dropped_rows)"
Write-Host "Replay allowed: $($result.replay_allowed)"
Write-Host "Output: $OutputPath"
