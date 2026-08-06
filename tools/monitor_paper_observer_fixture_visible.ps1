param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedPlanHash,
    [ValidateRange(1, 1800)]
    [int]$MaxRuntimeSec = 1800,
    [ValidateRange(1, 60)]
    [int]$PollIntervalSec = 2
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "C:\Program Files\Python313\python.exe"
$monitor = Join-Path $repoRoot "trading_mvp\src\paper_observer_monitor.py"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python runtime is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $monitor)) {
    throw "Paper observer monitor is unavailable: $monitor"
}

& $python $monitor `
    --plan $PlanPath `
    --expected-plan-hash $ExpectedPlanHash `
    --watch `
    --poll-interval-sec $PollIntervalSec `
    --max-runtime-sec $MaxRuntimeSec
if ($LASTEXITCODE -ne 0) {
    throw "Paper observer monitor failed with exit code $LASTEXITCODE."
}
