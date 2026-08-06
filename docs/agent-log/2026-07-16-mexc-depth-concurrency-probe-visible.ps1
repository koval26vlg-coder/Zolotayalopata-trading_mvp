$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\koval\Documents\ZolotyayLopata"
$python = "C:\Program Files\Python313\python.exe"
$driverPath = Join-Path $repoRoot "docs\agent-log\2026-07-16-mexc-depth-concurrency-probe.py"
$outputPath = "E:\ZolotyayLopata-data\exports\trading-mvp\fast-edge-track\quality\mexc_depth_concurrency_probe_20260716_v2.json"
$stdoutPath = Join-Path $repoRoot "docs\agent-log\mexc_depth_concurrency_probe_20260716_v2.stdout.log"
$stderrPath = Join-Path $repoRoot "docs\agent-log\mexc_depth_concurrency_probe_20260716_v2.stderr.log"
$maxRuntimeSec = 180

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python runtime is missing: $python"
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite existing probe output: $outputPath"
}

$Host.UI.RawUI.WindowTitle = "trading_mvp MEXC depth concurrency probe"
Write-Host "[depth-probe] public-only technical verification" -ForegroundColor Cyan
Write-Host "[depth-probe] max_runtime_sec=$maxRuntimeSec"
Write-Host "[depth-probe] output=$outputPath"
Write-Host "[depth-probe] no gate/ledger/PnL/OOS/grid/live/API keys"

$startedAt = Get-Date
$worker = Start-Process `
    -FilePath $python `
    -ArgumentList @(
        $driverPath,
        "--output", $outputPath,
        "--timeout-sec", "10"
    ) `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -NoNewWindow `
    -PassThru

while (-not $worker.HasExited) {
    $elapsedSec = [int]((Get-Date) - $startedAt).TotalSeconds
    if ($elapsedSec -ge $maxRuntimeSec) {
        Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
        throw "Public depth probe exceeded MaxRuntimeSec=$maxRuntimeSec"
    }
    $stdoutBytes = if (Test-Path -LiteralPath $stdoutPath) { (Get-Item -LiteralPath $stdoutPath).Length } else { 0 }
    Write-Host "[depth-probe] elapsed_sec=$elapsedSec worker_pid=$($worker.Id) stdout_bytes=$stdoutBytes"
    Start-Sleep -Seconds 5
    $worker.Refresh()
}

if ($worker.ExitCode -ne 0) {
    $stderrText = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { "" }
    throw "Public depth probe failed with exit code $($worker.ExitCode): $stderrText"
}
if (-not (Test-Path -LiteralPath $outputPath)) {
    throw "Public depth probe did not create its output artifact."
}

$report = Get-Content -Raw -LiteralPath $outputPath | ConvertFrom-Json
$depth = $report.summary.mexc_depth
$elapsedSec = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 3)
Write-Host "[depth-probe] decision=$($report.decision)" -ForegroundColor Green
Write-Host "[depth-probe] targets=$($depth.targets) complete=$($depth.complete) missing=$($depth.missing) coverage=$($depth.coverage)"
Write-Host "[depth-probe] elapsed_sec=$elapsedSec depth_errors=$(@($report.depth_errors.PSObject.Properties).Count)"
if ([double]$depth.coverage -lt [double]$depth.minimum_required_coverage) {
    $Host.UI.RawUI.WindowTitle = "trading_mvp MEXC depth probe FAILED"
    throw "MEXC depth coverage remains below frozen minimum."
}

$Host.UI.RawUI.WindowTitle = "trading_mvp MEXC depth probe COMPLETE"
Write-Host "[depth-probe] technical coverage accepted" -ForegroundColor Green
