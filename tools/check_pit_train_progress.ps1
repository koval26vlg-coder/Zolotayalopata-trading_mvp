param(
    [string]$SchedulePath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260729_20260728_102711.json",
    [string]$ExpectedPlanHash = "31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7",
    [string]$GatePath = "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "C:\Program Files\Python313\python.exe"
$monitor = Join-Path $repoRoot "trading_mvp\src\pit_train_progress_monitor.py"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python runtime is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $monitor)) {
    throw "PIT train progress monitor is unavailable: $monitor"
}

$arguments = @(
    $monitor,
    "--schedule", $SchedulePath,
    "--expected-plan-hash", $ExpectedPlanHash,
    "--gate", $GatePath
)
if ($OutputPath) {
    $arguments += @("--output", $OutputPath)
}
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PIT train progress monitor failed with exit code $LASTEXITCODE."
}
