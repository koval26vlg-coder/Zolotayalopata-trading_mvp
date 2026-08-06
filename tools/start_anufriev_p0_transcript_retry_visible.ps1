param(
    [int]$MaxVideos = 2,
    [int]$SleepSec = 60,
    [int]$TimeoutSec = 20,
    [int]$MaxWindows = 8,
    [switch]$Reprocess,
    [switch]$OverrideChannelFreeze,
    [string]$RunLabel = ""
)

$ErrorActionPreference = "Stop"
if (-not $OverrideChannelFreeze) {
    throw "Channel transcript/RSS intake is frozen by current user scope. Focus is strategy edge/high-winrate proof in trading_mvp. Re-run with -OverrideChannelFreeze only if the user explicitly reopens channel transcript work."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$queue = Join-Path $repoRoot "exports\youtube-anufriev\anufriev_transcript_retry_queue_p0_alpha_current_20260617.csv"
$metadata = Join-Path $repoRoot "exports\youtube-anufriev\anufriev_trading_relevant_metadata_20260606.jsonl"
$outDir = Join-Path $repoRoot "exports\youtube-anufriev"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"
New-Item -ItemType Directory -Force -Path $outDir, $runDir | Out-Null

if (-not (Test-Path $queue)) { throw "Missing queue: $queue" }
if (-not (Test-Path $metadata)) { throw "Missing metadata: $metadata" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$label = if ($RunLabel) { $RunLabel } else { "anufriev_transcript_retry_p0_alpha_visible_$stamp" }
$output = Join-Path $outDir ("{0}.jsonl" -f $label)
$state = Join-Path $outDir ("{0}.state.json" -f $label)
$consoleLog = Join-Path $runDir ("{0}.console.log" -f $label)

$pythonCandidates = @(
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    "python"
)
$python = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python") {
        $python = $candidate
        break
    }
    if (Test-Path $candidate) {
        $python = $candidate
        break
    }
}
if (-not $python) { throw "Python executable not found" }

$argsList = @(
    (Join-Path $repoRoot "tools\anufriev_transcript_retry.py"),
    "--queue", $queue,
    "--metadata", $metadata,
    "--output", $output,
    "--state", $state,
    "--max-videos", $MaxVideos,
    "--sleep-sec", $SleepSec,
    "--timeout-sec", $TimeoutSec,
    "--max-windows", $MaxWindows,
    "--stop-on-rate-limit"
)
if ($Reprocess) { $argsList += "--reprocess" }

Write-Host "Starting visible Anufriev P0 alpha transcript retry"
Write-Host "  Queue: $queue"
Write-Host "  Metadata: $metadata"
Write-Host "  Output: $output"
Write-Host "  State: $state"
Write-Host "  Console log: $consoleLog"
Write-Host "  MaxVideos: $MaxVideos SleepSec: $SleepSec"
Write-Host "  Scope: trading alpha only. P2P/legal/off-ramp/custody/115-FZ videos are excluded."
Write-Host "  Rule: keep this run visible; do not hide or background it. Stop-on-rate-limit is enabled."
Write-Host ""

$commandLine = @($python) + $argsList
& $python @argsList 2>&1 | Tee-Object -FilePath $consoleLog
$exitCode = $LASTEXITCODE
Write-Host ""
Write-Host "Finished with exit code: $exitCode"
Write-Host "Output: $output"
Write-Host "State: $state"
Write-Host "Console log: $consoleLog"
exit $exitCode
