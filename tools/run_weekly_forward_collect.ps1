# Weekly forward collect: daily klines + funding + funding_pairs пересчёт.
# Research-only, публичные REST без ключей. Одобрено пользователем 2026-07-03 как scheduled task.
param(
    [int]$Top = 200,
    [int]$Days = 200,
    [int]$MaxSymbols = 0,
    [string]$PythonExe = "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe",
    [string]$UniverseCsv = "",
    [string]$IdentityEvidencePath = ""
)

$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($UniverseCsv)) {
    # Preserve the existing universe contract; changing the snapshot requires a separate review.
    $UniverseCsv = Join-Path $projectRoot "coins_not_on_binance_full_2026-05-29.csv"
}
if ([string]::IsNullOrWhiteSpace($IdentityEvidencePath)) {
    $IdentityEvidencePath = Join-Path $projectRoot "docs\analysis\funding-forward\funding_forward_identity_evidence_20260810_v1.json"
}
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
    "--universe-csv", $UniverseCsv,
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

$manifestPath = Join-Path $runDir "manifest.json"
$auditOut = Join-Path $projectRoot "exports\trading-mvp\analysis\funding_forward_audit_$stamp.json"
$auditStdout = @("SKIPPED: upstream collector, pairs, or execution gate failed")
$auditExit = 1
if ($collectExit -eq 0 -and $pairsExit -eq 0 -and $gateExit -eq 0) {
    $auditArgs = @(
        (Join-Path $projectRoot "trading_mvp\src\funding_forward_audit.py"),
        "--manifest", $manifestPath,
        "--pairs-json", $pairsOut,
        "--execution-json", $gateOut,
        "--universe-csv", $UniverseCsv,
        "--out", $auditOut
    )
    if (Test-Path -LiteralPath $IdentityEvidencePath -PathType Leaf) {
        $auditArgs += @("--identity-evidence", $IdentityEvidencePath)
    }
    $auditStdout = & $PythonExe @auditArgs 2>&1
    $auditExit = $LASTEXITCODE
    $auditStdout | Tee-Object -FilePath $logPath -Append
}

$historyOut = Join-Path $projectRoot "exports\trading-mvp\analysis\funding_forward_history_audit_$stamp.json"
$historyStdout = @("SKIPPED: current snapshot audit failed")
$historyExit = 1
if ($auditExit -eq 0) {
    $historyStdout = & $PythonExe (Join-Path $projectRoot "trading_mvp\src\funding_forward_history_audit.py") `
        --analysis-dir (Join-Path $projectRoot "exports\trading-mvp\analysis") `
        --daily-dir (Join-Path $projectRoot "exports\trading-mvp\daily") `
        --through-stamp $stamp `
        --symbol "AKE_USDT" `
        --current-audit $auditOut `
        --out $historyOut 2>&1
    $historyExit = $LASTEXITCODE
    $historyStdout | Tee-Object -FilePath $logPath -Append
}

$reportPath = Join-Path $reportDir "funding_forward_$stamp.md"
@(
    "# Funding forward snapshot $stamp",
    "",
    "Run: ``$runId`` (top=$Top, days=$Days), collector_exit=$collectExit, pairs_exit=$pairsExit, gate_exit=$gateExit, audit_exit=$auditExit, history_exit=$historyExit",
    "Artifacts: ``exports/trading-mvp/daily/$runId/manifest.json``, ``exports/trading-mvp/analysis/funding_pairs_forward_$stamp.json``, ``exports/trading-mvp/analysis/execution_gate_forward_$stamp.json``, ``exports/trading-mvp/analysis/funding_forward_audit_$stamp.json``, ``exports/trading-mvp/analysis/funding_forward_history_audit_$stamp.json``",
    "Universe: ``$UniverseCsv`` (explicitly pinned; this runner does not migrate the universe snapshot)",
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
) + $gateStdout + @(
    '```',
    "",
    "## Deterministic offline audit",
    "",
    '```text'
) + $auditStdout + @(
    '```',
    "",
    "## Longitudinal overlap audit",
    "",
    '```text'
) + $historyStdout + @(
    '```',
    "",
    "## Interpretation limits",
    "",
    "- Decision is watchlist-only, never edge acceptance.",
    "- The universe is selected by current 24h volume and then backfilled historically; it is not point-in-time.",
    "- Ticker equality is not asset identity. Only same-contract exchange evidence is marked verified.",
    "- Order-book capacity is one snapshot, not time-averaged executable capacity.",
    "- Annualized funding minus modeled costs is not realized return or PnL.",
    "- Chronological OOS, walk-forward and stress gates are not run by this task."
) | Set-Content -Path $reportPath -Encoding UTF8

"[$(Get-Date -Format o)] done collector_exit=$collectExit pairs_exit=$pairsExit gate_exit=$gateExit audit_exit=$auditExit history_exit=$historyExit report=$reportPath" | Tee-Object -FilePath $logPath -Append
if ($collectExit -ne 0 -or $pairsExit -ne 0 -or $gateExit -ne 0 -or $auditExit -ne 0 -or $historyExit -ne 0) { exit 1 }
exit 0
