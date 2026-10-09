param([switch]$Status)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent) -Parent
$completion = Join-Path $PSScriptRoot 'audit-completion.json'
if ($Status) {
    if (Test-Path -LiteralPath $completion) { Get-Content -LiteralPath $completion -Raw }
    else { @{status='NO_COMPLETION'; retry_authorized=$false} | ConvertTo-Json }
    exit 0
}
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'audit-owner.json')) { throw 'One-shot audit namespace already used; inspect before retry' }
$guard = ((& (Join-Path $root 'tools/check_trading_mvp_autopilot.ps1') -Json) -join "`n") | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $guard.usage.decision -ne 'CONTINUE' -or $guard.usage.remaining_percent -le 15 -or $guard.status -like 'PAUSED*') { throw 'Quota unavailable/paused' }
$reads = @((Join-Path $root 'trading_mvp/src/channel_validation'), (Split-Path $PSScriptRoot -Parent), (Join-Path $root 'docs/plans/channel-strategy-validation-20261006-v1.json'))
$gate = ((& (Join-Path $root 'tools/check_active_run_gate.ps1') -OfflineWork -ReadResourcePath $reads -WriteResourcePath @($PSScriptRoot) -Json) -join "`n") | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $gate.scope_decision.allowed -or $gate.gate_status -eq 'RUNNING') { throw 'Technical gate closed' }
$owner = @{owner_pid=$PID; started_utc=[DateTime]::UtcNow.ToString('o'); max_runtime_sec=120; network_allowed=$false; market_evaluation_allowed=$false}
$owner | ConvertTo-Json | Out-File -FilePath (Join-Path $PSScriptRoot 'audit-owner.json') -Encoding utf8NoBOM -NoClobber
$env:PYTHONDONTWRITEBYTECODE='1'
Write-Host 'Protocol audit: 20 frozen models; synthetic assertions only; no network or market replay; max 120 seconds.'
Write-Host "Status: & '$PSCommandPath' -Status"
Write-Host 'Stop: close this window or press Ctrl+C. Do not repeat an incomplete audit without inspection.'
$worker=$null
try {
    $worker=Start-Process -FilePath 'C:\Program Files\Python313\python.exe' -ArgumentList @('-u', ('"'+(Join-Path $PSScriptRoot 'audit_protocol.py')+'"'), '--write') -WorkingDirectory $root -NoNewWindow -PassThru
    if (-not $worker.WaitForExit(120000)) { $worker.Kill($true); throw 'Audit timeout' }
    if ($worker.ExitCode -ne 0) { throw "Audit failed: $($worker.ExitCode)" }
    @{status='COMPLETE'; exit_code=0; owner_pid=$PID; worker_pid=$worker.Id; finished_utc=[DateTime]::UtcNow.ToString('o'); max_runtime_sec=120; market_evaluation_run=$false} | ConvertTo-Json | Out-File -FilePath $completion -Encoding utf8NoBOM -NoClobber
    Write-Host 'COMPLETE: audit saved. No strategy was accepted or rejected.'
} finally {
    if ($worker -and -not $worker.HasExited) { $worker.Kill($true) }
}
