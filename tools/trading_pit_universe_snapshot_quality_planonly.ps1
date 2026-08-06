param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [string]$OutputPath = "",
    [int]$MinCycles = 12,
    [int]$MinExchangesPerCycle = 2,
    [double]$MaxErrorCycleRatio = 0.05,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = if ($env:TRADING_MVP_PYTHON) { $env:TRADING_MVP_PYTHON } else { "C:\Program Files\Python313\python.exe" }
$module = Join-Path $repoRoot "trading_mvp\src\pit_universe_snapshot_quality.py"
if (-not (Test-Path -LiteralPath $ManifestPath)) { throw "Manifest not found: $ManifestPath" }
if (-not (Test-Path -LiteralPath $python)) { throw "Python runtime not found: $python" }
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path (Split-Path -Parent $ManifestPath) "data_quality.json"
}

$arguments = @(
    $module,
    "--manifest", $ManifestPath,
    "--out", $OutputPath,
    "--min-cycles", [string]$MinCycles,
    "--min-exchanges-per-cycle", [string]$MinExchangesPerCycle,
    "--max-error-cycle-ratio", [string]$MaxErrorCycleRatio
)
& $python @arguments
$exitCode = $LASTEXITCODE
if ($Json -and (Test-Path -LiteralPath $OutputPath)) {
    Get-Content -Raw -LiteralPath $OutputPath
}
if ($exitCode -ne 0) {
    throw "PIT data-quality rejected or failed with exit code $exitCode. Report: $OutputPath"
}
