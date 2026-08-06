param(
    [string]$OutputPath = "",
    [ValidateRange(1, 300)]
    [int]$MaxRuntimeSec = 300
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "C:\Program Files\Python313\python.exe"
$runner = Join-Path $repoRoot "trading_mvp\src\fast_regression_lane.py"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python runtime is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Fast regression runner is unavailable: $runner"
}
if ($MaxRuntimeSec -gt 300) {
    throw "MaxRuntimeSec must be <= 300."
}

$arguments = @($runner, "--verbosity", "1")
if ($OutputPath) {
    $arguments += @("--output", $OutputPath)
}
$started = Get-Date
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Fast regression failed with exit code $LASTEXITCODE."
}
$elapsed = ((Get-Date) - $started).TotalSeconds
if ($elapsed -gt $MaxRuntimeSec) {
    throw "Fast regression exceeded MaxRuntimeSec: $([math]::Round($elapsed, 3))s."
}
