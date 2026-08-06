# Weekly forward collect: daily klines + funding + funding_pairs пересчёт.
# Research-only, публичные REST без ключей. Одобрено пользователем 2026-07-03 как scheduled task.
param(
    [int]$Top = 200,
    [int]$Days = 200,
    [int]$MaxSymbols = 0,
    [string]$PythonExe = "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd"
$runId = "daily_forward_$stamp"
$logDir = Join-Path $projectRoot "logs\weekly-forward"
New-Item -ItemType Directory -Force $logDir | Out-Null
$logPath = Join-Path $logDir "$stamp.log"
$reportDir = Join-Path $projectRoot "docs\analysis\funding-forward"
New-Item -ItemType Directory -Force $reportDir | Out-Null

"[$(Get-Date -Format o)] weekly forward collect start run_id=$runId top=$Top days=$Days" | Tee-Object -FilePath $logPath -Append

$collectorArgs = @(
    (Join-Path $projectRoot "trading_mvp\src\daily_collector.py"),
    "--exchanges", "mexc,gateio",
    "--top", $Top,
    "--days", $Days,
    "--run-id", $runId
)
if ($MaxSymbols -gt 0) { $collectorArgs += @("--max-symbols", $MaxSymbols) }
& $PythonExe @collectorArgs 2>&1 | Tee-Object -FilePath $logPath -Append
$collectExit = $LASTEXITCODE

$runDir = Join-Path $projectRoot "exports\trading-mvp\daily\$runId"
$pairsOut = Join-Path $projectRoot "exports\trading-mvp\analysis\funding_pairs_forward_$stamp.json"
$pairsStdout = & $PythonExe (Join-Path $projectRoot "trading_mvp\src\funding_pairs.py") `
    --run-dir $runDir `
    --fee-evidence-dir (Join-Path $projectRoot "exports\trading-mvp\analysis\fee_evidence_20260702") `
    --out $pairsOut 2>&1
$pairsExit = $LASTEXITCODE
$pairsStdout | Tee-Object -FilePath $logPath -Append

$gateOut = Join-Path $projectRoot "exports\trading-mvp\analysis\execution_gate_forward_$stamp.json"
$gateStdout = & $PythonExe (Join-Path $projectRoot "trading_mvp\src\execution_gate.py") `
    --pairs-json $pairsOut `
    --fee-evidence-dir (Join-Path $projectRoot "exports\trading-mvp\analysis\fee_evidence_20260702") `
    --auto-candidates `
    --out $gateOut 2>&1
$gateExit = $LASTEXITCODE
$gateStdout | Tee-Object -FilePath $logPath -Append

$reportPath = Join-Path $reportDir "funding_forward_$stamp.md"
@(
    "# Funding forward snapshot $stamp",
    "",
    "Run: ``$runId`` (top=$Top, days=$Days), collector_exit=$collectExit, pairs_exit=$pairsExit, gate_exit=$gateExit",
    "Artifacts: ``exports/trading-mvp/daily/$runId/manifest.json``, ``exports/trading-mvp/analysis/funding_pairs_forward_$stamp.json``, ``exports/trading-mvp/analysis/execution_gate_forward_$stamp.json``",
    "",
    "## Funding pairs",
    "",
    '```text'
) + $pairsStdout + @(
    '```',
    "",
    "## Execution gate (стаканы watchlist)",
    "",
    '```text'
) + $gateStdout + @('```') | Set-Content -Path $reportPath -Encoding UTF8

"[$(Get-Date -Format o)] done collector_exit=$collectExit pairs_exit=$pairsExit gate_exit=$gateExit report=$reportPath" | Tee-Object -FilePath $logPath -Append
if ($collectExit -ne 0 -or $pairsExit -ne 0 -or $gateExit -ne 0) { exit 1 }
exit 0
