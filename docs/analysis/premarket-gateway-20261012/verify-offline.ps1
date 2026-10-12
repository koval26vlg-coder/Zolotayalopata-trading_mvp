$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$env:PYTHONDONTWRITEBYTECODE = '1'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Set-Location $root
$Host.UI.RawUI.WindowTitle = 'Premarket gateway: OFFLINE synthetic verification, no market collection'
$python = 'C:\Program Files\Python313\python.exe'
$log = Join-Path $PSScriptRoot 'visible-verification.log'
$record = Join-Path $PSScriptRoot 'verification.json'
if ((Test-Path -LiteralPath $log) -or (Test-Path -LiteralPath $record)) { throw 'Verification already exists; do not overwrite' }
$claim = Join-Path $root 'docs\agent-log\active-market-data-writer-claim.json'
$output = Join-Path $root 'docs\analysis\premarket-depth-gateway-runs'
$campaigns = Join-Path $root 'docs\analysis\premarket-depth-gateway-campaigns'
if ((Test-Path $claim) -or (Test-Path $output) -or (Test-Path $campaigns)) { throw 'Production namespace exists; stop offline verification' }
Write-Host 'OFFLINE ONLY. Ctrl+C stops verification. Synthetic test watchdog: 300 seconds.'
$suites = @('trading_mvp.tests.test_premarket_depth_gateway',
    'trading_mvp.tests.test_premarket_depth_dispatch','trading_mvp.tests.test_premarket_depth_coordinator',
    'trading_mvp.tests.test_global_market_writer_claim','trading_mvp.tests.test_premarket_depth_sampling_protocol',
    'trading_mvp.tests.test_premarket_forward_depth_quality','trading_mvp.tests.test_research_checkpoint')
# The watchdog exits the test process even if a fixture hangs.
& $python -c 'import faulthandler,unittest; faulthandler.dump_traceback_later(300,exit=True); unittest.main(module=None)' -v @suites 2>&1 | Tee-Object -FilePath $log
$testExit = $LASTEXITCODE
if ($testExit -ne 0) { throw 'Synthetic regressions failed' }
$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'tools\start_premarket_depth_gateway_visible.ps1'),[ref]$tokens,[ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
& $python trading_mvp/src/premarket_depth_gateway.py --freeze-only 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { throw 'Offline immutable freeze failed' }
$raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File tools/start_premarket_depth_gateway_visible.ps1 -PreflightOnly
$preflightExit = $LASTEXITCODE
$raw | Tee-Object -FilePath $log -Append
$preflight = ($raw -join "`n") | ConvertFrom-Json
if ($preflightExit -ne 2 -or $preflight.status -ne 'BLOCKED' -or $preflight.reason -ne 'COLLECTION_DISABLED_NO_CAMPAIGN') { throw 'Unexpected preflight result' }
if ((Test-Path $claim) -or (Test-Path $output) -or (Test-Path $campaigns)) { throw 'Unexpected production side effect' }
$runtimePath = Join-Path $root 'docs\plans\premarket-depth-gateway-runtime-20261012-v1.json'
$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$summary = Select-String -LiteralPath $log -Pattern '^Ran (\d+) tests in' | Select-Object -Last 1
if (-not $summary) { throw 'Test count absent' }
[ordered]@{status='OFFLINE_GATEWAY_VERIFIED_NOT_ACTIVATED';observed_utc=[DateTime]::UtcNow.ToString('o');
    visible_terminal_pid=$PID;test_watchdog_sec=300;test_exit_code=$testExit;tests_passed=[int]$summary.Matches[0].Groups[1].Value;
    launcher_parse_errors=0;preflight_exit_code=$preflightExit;preflight=$preflight;
    production_writer_claim_exists=$false;production_capture_namespace_exists=$false;production_campaign_namespace_exists=$false;
    market_network_requests=0;collection_enabled=$false;schedules_enabled=$false;
    runtime_file_sha256=(Get-FileHash -LiteralPath $runtimePath).Hash.ToLowerInvariant();runtime_manifest_hash=$runtime.manifest_hash
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $record -Encoding utf8NoBOM
'OFFLINE_GATEWAY_VERIFIED_NOT_ACTIVATED' | Tee-Object -FilePath $log -Append
