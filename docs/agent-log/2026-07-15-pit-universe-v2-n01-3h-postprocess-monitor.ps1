$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$runId = "pit_universe_v2_forward_20260715_n01"
$manifestPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\$runId\manifest.json"
$planPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\schedules\pit_universe_v2_train_supplemental_3h_planonly_20260715_000830.json"
$planHash = "155d211ccf002cd607f0644e98f9a417de45e0644122b54b2dcbe6b4e1d81d92"
$ledgerPath = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\quality-certifications.jsonl"
$reportPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\pit_universe_v2_quality_report_20260715_n01.json"
$userDeadline = [DateTimeOffset]::Parse("2026-07-15T09:00:00+03:00")
$lastPrintedCycle = -1
$lastPrintedAt = [DateTimeOffset]::MinValue

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - MONITOR"
Write-Host "[monitor] run_id=$runId" -ForegroundColor Cyan
Write-Host "[monitor] waiting for final=true; then one hash-bound quality certification"
Write-Host "[monitor] no auto-resume, duplicate collector, OOS/grid/probe/paper/live/API keys"

while ($true) {
    $now = [DateTimeOffset]::Now
    if ($now -ge $userDeadline) {
        throw "User-approved operating window ended before postprocess: $($userDeadline.ToString('o'))"
    }

    if (-not (Test-Path -LiteralPath $manifestPath)) {
        Write-Host "[monitor] manifest not created yet; waiting 15s" -ForegroundColor Yellow
        Start-Sleep -Seconds 15
        continue
    }

    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    } catch {
        Write-Host "[monitor] manifest is being replaced atomically; retrying" -ForegroundColor Yellow
        Start-Sleep -Seconds 2
        continue
    }

    $cycle = [int]$manifest.cycle_count
    $elapsed = [double]$manifest.elapsed_active_sec
    $duration = [double]$manifest.duration_sec
    $remaining = [Math]::Max(0, $duration - $elapsed)
    $eta = $now.AddSeconds($remaining)
    if ($cycle -ne $lastPrintedCycle -or ($now - $lastPrintedAt).TotalSeconds -ge 60) {
        Write-Host ("[monitor] {0:HH:mm:ss} cycle={1} rows={2} errors={3} remaining={4:N0}s ETA={5:HH:mm:ss}" -f `
            $now, $cycle, [int]$manifest.rows_total, [int]$manifest.errors_total, $remaining, $eta)
        $lastPrintedCycle = $cycle
        $lastPrintedAt = $now
    }

    if ([bool]$manifest.final) {
        if ([string]$manifest.status -ne "COMPLETED") {
            throw "Collector finalized without COMPLETED status: status=$($manifest.status) stop_reason=$($manifest.stop_reason)"
        }
        break
    }

    $collectorAlive = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match [regex]::Escape($runId) }
    if (-not $collectorAlive) {
        Start-Sleep -Seconds 10
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if (-not [bool]$manifest.final) {
            throw "Collector process disappeared while manifest final=false; no auto-resume permitted."
        }
        continue
    }

    Start-Sleep -Seconds 30
}

Write-Host "[monitor] collector final=true; waiting for gate READY_FOR_POSTPROCESS" -ForegroundColor Green
$gateReady = $false
for ($attempt = 1; $attempt -le 12; $attempt++) {
    $gateJson = & (Join-Path $repoRoot "tools\check_active_run_gate.ps1") -Json
    $gate = ($gateJson -join [Environment]::NewLine) | ConvertFrom-Json
    if ([string]$gate.run_id -eq $runId -and [string]$gate.status -eq "READY_FOR_POSTPROCESS") {
        $gateReady = $true
        break
    }
    if ([string]$gate.status -eq "STOPPED_INCOMPLETE") {
        throw "Gate is STOPPED_INCOMPLETE; quality certification is forbidden."
    }
    Start-Sleep -Seconds 5
}
if (-not $gateReady) {
    throw "Gate did not reach READY_FOR_POSTPROCESS after collector final=true."
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - QUALITY"
Write-Host "[monitor] starting hash-bound technical quality certification" -ForegroundColor Cyan
Set-Location -LiteralPath $repoRoot
& ".\trading_mvp\run_mvp.ps1" `
    -Action fast-edge-night-schedule-quality `
    -PlanPath $planPath `
    -ExpectedPlanHash $planHash `
    -QualityLedgerPath $ledgerPath `
    -OutputPath $reportPath `
    -MaxRuntimeSec 1800

if ($LASTEXITCODE -ne 0) {
    $Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - QUALITY FAILED"
    throw "Quality certification failed with exit code $LASTEXITCODE"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp PIT 3h n01 - QUALITY COMPLETE"
Write-Host "[monitor] quality report: $reportPath" -ForegroundColor Green
Write-Host "[monitor] completed without OOS/grid/probe/paper/live/API keys."
