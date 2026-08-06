$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$planPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_schedule_planonly_20260714_220219.json"
$planHash = "34363aefacf4e2ad3c35053f267145841aa6faca69c154e70c3758e659dc6362"
$ledgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl"
$reportPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\pit_universe_v2_quality_report_20260714_n01.json"

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - QUALITY"
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
    $Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - QUALITY FAILED"
    throw "Quality certification failed with exit code $LASTEXITCODE"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT n01 - QUALITY COMPLETE"
Write-Host "[pit-universe] quality report: $reportPath" -ForegroundColor Green
