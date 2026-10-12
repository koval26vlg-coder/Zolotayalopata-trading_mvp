$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Set-Location $root
$Host.UI.RawUI.WindowTitle = 'Premarket dispatch: synthetic tests ONLY, no market collection'
$python = 'C:\Program Files\Python313\python.exe'
$log = Join-Path $PSScriptRoot 'visible-verification.log'
if (Test-Path -LiteralPath $log) { throw 'Do not replace a verification log' }
Write-Host 'OFFLINE ONLY. Stop: Ctrl+C. Tests use temporary claims/databases, not production resources.'
$suites = @('trading_mvp.tests.test_premarket_depth_dispatch','trading_mvp.tests.test_premarket_depth_coordinator',
    'trading_mvp.tests.test_global_market_writer_claim','trading_mvp.tests.test_premarket_depth_sampling_protocol',
    'trading_mvp.tests.test_premarket_forward_depth_quality','trading_mvp.tests.test_research_checkpoint')
& $python -m unittest -v @suites 2>&1 | Tee-Object -FilePath $log
$testExit = $LASTEXITCODE
if ($testExit -ne 0) { throw 'Synthetic regressions failed' }
& $python trading_mvp/src/premarket_depth_dispatch.py --freeze-only 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { throw 'Offline freeze failed' }
$raw = & $python trading_mvp/src/premarket_depth_dispatch.py --preflight
$preflightExit = $LASTEXITCODE
$preflight = ($raw -join "`n") | ConvertFrom-Json
if ($preflightExit -ne 2 -or $preflight.status -ne 'BLOCKED') { throw 'Unexpected preflight result' }
[ordered]@{status='OFFLINE_INTEGRATION_VERIFIED_PILOT_NOT_READY';observed_utc=[DateTime]::UtcNow.ToString('o');
    test_exit_code=$testExit;preflight_exit_code=$preflightExit;preflight=$preflight;
    production_writer_claim_exists=(Test-Path docs/agent-log/active-market-data-writer-claim.json);
    production_capture_namespace_exists=(Test-Path docs/analysis/premarket-depth-coordinator-runs);
    runtime_file_sha256=(Get-FileHash docs/plans/premarket-depth-dispatch-runtime-20261006-v1.json).Hash.ToLowerInvariant()
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'verification.json') -Encoding utf8NoBOM
'OFFLINE_INTEGRATION_VERIFIED_PILOT_NOT_READY' | Tee-Object -FilePath $log -Append
