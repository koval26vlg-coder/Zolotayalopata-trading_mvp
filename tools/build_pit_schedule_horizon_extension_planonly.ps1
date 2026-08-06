param(
    [string]$SchedulePath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260729_20260728_102711.json",
    [string]$ExpectedPlanHash = "31b4b6c73487953755409ce32dafb818c4bc8c61b7db67ecd709a6457ece8af7",
    [string]$ObservedAt = "",
    [string]$AuditOutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research\pit-universe-v2-schedule-horizon-audit-31b4b6c7-v1.json",
    [string]$ExtensionOutputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_extension_planonly_20260812_from_31b4b6c7_v1.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "C:\Program Files\Python313\python.exe"
$auditTool = Join-Path $repoRoot "trading_mvp\src\pit_schedule_horizon.py"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python runtime is unavailable: $python"
}
if (-not (Test-Path -LiteralPath $auditTool -PathType Leaf)) {
    throw "PIT schedule horizon tool is unavailable: $auditTool"
}
if (-not $ObservedAt) {
    $ObservedAt = [DateTimeOffset]::Now.ToString("o")
}

& $python $auditTool `
    --plan $SchedulePath `
    --expected-plan-hash $ExpectedPlanHash `
    --observed-at $ObservedAt `
    --audit-output $AuditOutputPath `
    --extension-output $ExtensionOutputPath
if ($LASTEXITCODE -ne 0) {
    throw "PIT schedule horizon PlanOnly build failed with exit code $LASTEXITCODE."
}
