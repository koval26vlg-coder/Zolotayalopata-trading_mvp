$ErrorActionPreference = "Stop"

$repo = "C:\Users\koval\Documents\ZolotyayLopata"
$runner = Join-Path $repo "trading_mvp\run_mvp.ps1"
$output = "E:\ZolotyayLopata-data\exports\trading-mvp\historical-basis\universe\basis_universe_20260715_114700.json"
$pitState = "E:\ZolotyayLopata-data\exports\trading-mvp\pit-universe-v2\pit_universe_v2_forward_20260715_n01\universe_state.json"
$coinRegistry = Join-Path $repo "coins_not_on_binance_full_2026-05-29.csv"
$runId = "historical_basis_universe_20260715_114700"
$startedAt = Get-Date

Set-Location -LiteralPath $repo
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null

Write-Host "TRADING_MVP VISIBLE BASIS UNIVERSE PREFLIGHT" -ForegroundColor Cyan
Write-Host "run_id=$runId"
Write-Host "max_runtime_sec=600"
Write-Host "output=$output"
Write-Host "started_at=$($startedAt.ToString('yyyy-MM-dd HH:mm:ss zzz'))"

try {
    & $runner `
        -Action fast-edge-basis-universe-build `
        -InputPath $pitState `
        -CoinRegistryPath $coinRegistry `
        -OutputPath $output `
        -RunId $runId `
        -MaxRuntimeSec 600
    $exitCode = $LASTEXITCODE
    $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    if ($exitCode -ne 0) {
        Write-Host "FAILED exit_code=$exitCode elapsed_sec=$elapsed" -ForegroundColor Red
        exit $exitCode
    }
    Write-Host "COMPLETED exit_code=0 elapsed_sec=$elapsed output=$output" -ForegroundColor Green
} catch {
    $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    Write-Host "FAILED elapsed_sec=$elapsed error=$($_.Exception.Message)" -ForegroundColor Red
    throw
}

Write-Host "Window remains open for inspection. Close it when finished." -ForegroundColor Yellow
