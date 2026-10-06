param([ValidatePattern('^[a-z0-9-]+$')][string]$Attempt = 'final')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Set-Location $root
$python = 'C:\Program Files\Python313\python.exe'
$Host.UI.RawUI.WindowTitle = 'Premarket: offline coordinator verification, NO MARKET COLLECTION'
$log = Join-Path $PSScriptRoot "visible-verification-$Attempt.log"
Start-Transcript -LiteralPath $log -NoClobber | Out-Null
try {
    Write-Host 'OFFLINE ONLY. Stop: Ctrl+C. Expected <300 sec. Synthetic claims use temporary folders only.'
    & $python -m unittest -v trading_mvp.tests.test_premarket_depth_coordinator trading_mvp.tests.test_global_market_writer_claim trading_mvp.tests.test_premarket_depth_sampling_protocol trading_mvp.tests.test_premarket_forward_depth_quality trading_mvp.tests.test_research_checkpoint
    if ($LASTEXITCODE -ne 0) { throw 'Targeted synthetic regressions failed' }
    & (Join-Path $PSScriptRoot 'verify-native-owner.ps1')
    & $python trading_mvp/src/premarket_depth_coordinator.py --freeze-only
    if ($LASTEXITCODE -ne 0) { throw 'Immutable offline freeze failed' }
    'OFFLINE_VERIFICATION_COMPLETE_COLLECTION_DISABLED' | Write-Host
} catch {
    Write-Host ('OFFLINE_VERIFICATION_FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    throw
} finally {
    Stop-Transcript | Out-Null
}
