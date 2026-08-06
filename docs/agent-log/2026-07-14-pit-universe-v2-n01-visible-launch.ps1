$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$wrapper = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"
$planPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_220219.json"
$planHash = "34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362"
$runId = "pit_universe_v2_forward_20260714_n01"
$notBeforeText = "2026-07-14T23:00:00+03:00"
$hardDeadlineText = "2026-07-15T07:00:00+03:00"
$notBefore = [DateTimeOffset]::Parse($notBeforeText)
$hardDeadline = [DateTimeOffset]::Parse($hardDeadlineText)

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - waiting for 23:00"
Write-Host "[pit-universe] approved visible segment: $runId" -ForegroundColor Cyan
Write-Host "[pit-universe] plan_hash=$planHash"
Write-Host "[pit-universe] starts=$notBeforeText duration=1200s interval=300s"
Write-Host "[pit-universe] data embargo: no returns/PnL/OOS/grid/live/API keys"

while ([DateTimeOffset]::Now -lt $notBefore) {
    $remaining = [Math]::Ceiling(($notBefore - [DateTimeOffset]::Now).TotalSeconds)
    Write-Host ("`r[pit-universe] waiting for approved window: {0}s remaining   " -f $remaining) -NoNewline
    Start-Sleep -Seconds ([Math]::Min(10, [Math]::Max(1, $remaining)))
}
Write-Host ""

if ([DateTimeOffset]::Now -ge $hardDeadline) {
    throw "Approved hard deadline already passed: $hardDeadlineText"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - RUNNING"
Set-Location -LiteralPath $repoRoot
& $wrapper `
    -DurationSec 1200 `
    -IntervalSec 300 `
    -TimeoutSec 10 `
    -MinContractsPerExchange 50 `
    -MinFreeDiskGiB 5 `
    -ApprovedNotBefore $notBeforeText `
    -ApprovedNotLaterThan $hardDeadlineText `
    -SchedulePlanPath $planPath `
    -ExpectedSchedulePlanHash $planHash `
    -OutputRoot "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2" `
    -RunId $runId `
    -ConfirmedPitUniverseSnapshotCollect

if ($LASTEXITCODE -ne 0) {
    $Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - FAILED"
    throw "Visible segment wrapper failed with exit code $LASTEXITCODE"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - COMPLETE"
Write-Host "[pit-universe] visible segment wrapper completed. Keep this window for inspection." -ForegroundColor Green
