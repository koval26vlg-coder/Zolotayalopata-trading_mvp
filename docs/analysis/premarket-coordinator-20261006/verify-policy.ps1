$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Set-Location $root
$Host.UI.RawUI.WindowTitle = 'Premarket: offline policy checks, no collection'
$python = 'C:\Program Files\Python313\python.exe'
$pwsh = (Get-Command pwsh).Source
$launcher = Join-Path $root 'tools\start_premarket_depth_coordinator_visible.ps1'
$checks = [ordered]@{observed_utc=[DateTime]::UtcNow.ToString('o')}
Start-Transcript -LiteralPath (Join-Path $PSScriptRoot 'policy-verification-final.log') -NoClobber | Out-Null
try {
    & $python -m unittest -v trading_mvp.tests.test_autopilot_guard trading_mvp.tests.test_one_week_edge_sprint_readiness
    $checks.controller_regression_exit_code = $LASTEXITCODE
    $raw = & $pwsh -NoProfile -File $launcher -PreflightOnly
    $checks.preflight_exit_code = $LASTEXITCODE
    $checks.preflight = ($raw -join "`n") | ConvertFrom-Json
    if ($checks.preflight_exit_code -ne 2 -or $checks.preflight.reason -ne 'COLLECTION_DISABLED_OFFLINE_ONLY') { throw 'Unexpected preflight result' }
    foreach ($action in @('Status','Stop')) {
        $raw = & $pwsh -NoProfile -File $launcher "-$action" -RunId premarket_depth_offline_verification
        $key = $action.ToLowerInvariant() + '_check'
        $checks[$key] = ($raw -join "`n") | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $checks[$key].status -ne 'NOT_STARTED') { throw 'Unexpected unused-run status' }
    }
    $raw = & $pwsh -NoProfile -File tools/install_premarket_forward_depth_scan_task.ps1 -DryRun
    $checks.legacy_installer_exit_code = $LASTEXITCODE
    $checks.legacy_installer = ($raw -join "`n") | ConvertFrom-Json
    if ($checks.legacy_installer.status -ne 'LEGACY_HIDDEN_CAPTURE_RETIRED') { throw 'Legacy installer remains usable' }
    $checks.production_claim_exists = Test-Path docs/agent-log/active-market-data-writer-claim.json
    $checks.capture_namespace_exists = Test-Path docs/analysis/premarket-depth-coordinator-runs
    $checks.dispatch_files = @(Get-ChildItem docs/agent-log/run-gates -Filter 'premarket_depth_*.depth-owner*' | Select-Object -ExpandProperty Name)
    if ($checks.production_claim_exists -or $checks.capture_namespace_exists -or $checks.dispatch_files.Count) { throw 'Unexpected production output/claim/dispatch' }
    $checks.schedules = @(Get-ScheduledTask | Where-Object {$_.TaskName -match '(?i)premarket'} | ForEach-Object { @{name=$_.TaskName;state=$_.State.ToString()} })
    if (@($checks.schedules | Where-Object {$_.state -ne 'Disabled'}).Count) { throw 'Premarket schedule not disabled' }
    $m = Get-Content docs/plans/premarket-depth-coordinator-runtime-20261006-v1.json -Raw | ConvertFrom-Json
    $checks.runtime_manifest_hash = $m.manifest_hash
    $checks.runtime_manifest_file_sha256 = (Get-FileHash docs/plans/premarket-depth-coordinator-runtime-20261006-v1.json -Algorithm SHA256).Hash.ToLowerInvariant()
    $checks.status = 'OFFLINE_BOUNDARY_CHECKS_PASS'
    $checks | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'boundary-verification-final.json') -Encoding utf8NoBOM
    Write-Host 'OFFLINE_BOUNDARY_CHECKS_PASS. Inspect controller regression log separately.'
} finally { Stop-Transcript | Out-Null }
