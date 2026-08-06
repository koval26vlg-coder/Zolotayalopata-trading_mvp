$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$wrapper = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"
$planPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_supplemental_3h_planonly_20260715_000830.json"
$planHash = "155d211ccf002cd607f0644e98f9a417de45e0644122b54b2dcbe6b4e1d81d92"
$runId = "pit_universe_v2_forward_20260715_n01"
$notBeforeText = "2026-07-15T00:15:00+03:00"
$hardDeadlineText = "2026-07-15T07:00:00+03:00"
$notBefore = [DateTimeOffset]::Parse($notBeforeText)
$hardDeadline = [DateTimeOffset]::Parse($hardDeadlineText)

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - waiting"
Write-Host "[pit-universe] approved visible segment: $runId" -ForegroundColor Cyan
Write-Host "[pit-universe] plan_hash=$planHash"
Write-Host "[pit-universe] duration=10800s interval=300s expected_cycles=36"
Write-Host "[pit-universe] hard_deadline=$hardDeadlineText; stop=Ctrl+C"
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

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - RUNNING"
Set-Location -LiteralPath $repoRoot
& $wrapper `
    -DurationSec 10800 `
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
    $Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - FAILED"
    throw "Visible segment wrapper failed with exit code $LASTEXITCODE"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - COMPLETE"
Write-Host "[pit-universe] visible segment wrapper completed. Keep this window for inspection." -ForegroundColor Green
