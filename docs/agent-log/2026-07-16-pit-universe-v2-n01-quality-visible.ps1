$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$planPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_reseal_primary_immutable_sources_planonly_20260716_082454.json"
$planHash = "14f687e8e8491bb58c1e697d9a467d89ab360f6b683782caca43f8b33a0684a0"
$ledgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl"
$reportPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\pit_universe_v2_quality_report_20260716_n01.json"

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 20260716 n01 - QUALITY"
Write-Host "[pit-universe] hash-bound technical quality certification" -ForegroundColor Cyan
Write-Host "[pit-universe] no returns/PnL/OOS/grid/live/API keys"
Set-Location -LiteralPath $repoRoot

& ".\trading_mvp\run_mvp.ps1" `
    -Action fast-edge-night-schedule-quality `
    -PlanPath $planPath `
    -ExpectedPlanHash $planHash `
    -QualityLedgerPath $ledgerPath `
    -OutputPath $reportPath `
    -MaxRuntimeSec 1800

if ($LASTEXITCODE -ne 0) {
    $Host.UI.RawUI.WindowTitle = "trading_mvp PIT 20260716 n01 - QUALITY FAILED"
    throw "Quality certification failed with exit code $LASTEXITCODE"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 20260716 n01 - QUALITY COMPLETE"
Write-Host "[pit-universe] quality report: $reportPath" -ForegroundColor Green
Write-Host "[pit-universe] completed without returns/PnL/OOS/grid/probe/paper/live/API keys."
