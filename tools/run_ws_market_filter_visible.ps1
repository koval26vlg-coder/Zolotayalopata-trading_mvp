param(
    [string]$PostprocessPath = "",
    [string]$InputPath = "",
    [string]$SourceManifestPath = "",
    [string]$RunLabel = "",
    [double]$FilterMaxGapSec = 300.0,
    [int]$FilterMinRowsPerMarket = 1000,
    [double]$FilterMinMarketSpanHours = 5.0,
    [double]$FilterMinMarketDurationRatio = 0.80,
    [string]$FilterRequiredEventKinds = "bbo,depth,trade",
    [int]$FilterMinAcceptedMarkets = 5,
    [int]$FilterMinAcceptedExchanges = 2,
    [int]$FilterMinTotalRows = 5000,
    [double]$FilterMaxMarketEventShare = 0.50,
    [int]$WsQualityMinRows = 5000,
    [int]$WsQualityMinExchanges = 2,
    [int]$WsQualityMinMarkets = 5,
    [double]$WsQualityMinSpanHours = 5.0,
    [double]$WsQualityMinDurationRatio = 0.80,
    [double]$WsQualityMaxParseErrorRate = 0.05,
    [string]$WsQualityRequiredEventKinds = "bbo,depth,trade",
    [int]$WsQualityMinMarketsWithRequiredKinds = 5,
    [double]$WsQualityMaxMarketEventShare = 0.50,
    [double]$WsQualityMaxGapSec = 300.0,
    [int]$WsQualityMaxManifestErrorCount = 50,
    [switch]$PlanOnly,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$script = Join-Path $repoRoot "trading_mvp\src\ws_market_filter.py"
$normalizedDir = Join-Path $repoRoot "exports\trading-mvp\normalized"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"

New-Item -ItemType Directory -Force -Path $normalizedDir, $backtestDir, $runDir | Out-Null
Set-Location $repoRoot

if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE") {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume or reject the incomplete run before WS market filter."
    }
}

if (-not $PostprocessPath) {
    $latest = Get-ChildItem -LiteralPath $backtestDir -Filter "ws_postprocess_ws_durable_72h_clean_window*.json" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        $PostprocessPath = $latest.FullName
    }
}
if (-not $PostprocessPath -and -not $InputPath) {
    throw "PostprocessPath or InputPath is required."
}

$sourcePostprocess = $null
if ($PostprocessPath) {
    $PostprocessPath = (Resolve-Path -LiteralPath $PostprocessPath).Path
    $sourcePostprocess = Get-Content -Raw -LiteralPath $PostprocessPath | ConvertFrom-Json
    if (-not $InputPath -and $sourcePostprocess.normalized_output) {
        $InputPath = [string]$sourcePostprocess.normalized_output
    }
    if (-not $SourceManifestPath -and $sourcePostprocess.manifest) {
        $SourceManifestPath = [string]$sourcePostprocess.manifest
    }
}
if (-not $InputPath) {
    throw "InputPath is required or must be present as normalized_output in PostprocessPath."
}
$InputPath = (Resolve-Path -LiteralPath $InputPath).Path
if ($SourceManifestPath) {
    $SourceManifestPath = (Resolve-Path -LiteralPath $SourceManifestPath).Path
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$label = if ($RunLabel) { $RunLabel } else { "ws_market_filter_$stamp" }
$normalizedOutput = Join-Path $normalizedDir ("ws_market_filtered_{0}.jsonl" -f $label)
$marketManifest = Join-Path $backtestDir ("ws_market_filter_manifest_{0}.json" -f $label)
$marketReport = Join-Path $backtestDir ("ws_market_filter_{0}.json" -f $label)
$qualityOutput = Join-Path $backtestDir ("ws_data_quality_{0}.json" -f $label)
$postprocessOutput = Join-Path $backtestDir ("ws_postprocess_{0}.json" -f $label)
$consoleLog = Join-Path $runDir ("ws_market_filter_{0}.console.log" -f $label)
$progressLog = Join-Path $runDir ("ws_market_filter_{0}.progress.jsonl" -f $label)
$stdoutLog = Join-Path $runDir ("ws_market_filter_{0}.stdout.log" -f $label)
$stderrLog = Join-Path $runDir ("ws_market_filter_{0}.stderr.log" -f $label)

$pythonCandidates = @(
    $env:TRADING_MVP_PYTHON,
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $repoRoot "trading_mvp\.venv\Scripts\python.exe"),
    "C:\Program Files\Python313\python.exe",
    "C:\Users\koval\Documents\ОК.ру\.venv\Scripts\python.exe"
) | Where-Object { $_ }
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = $pythonCmd.Source
    }
}
if (-not $python) {
    throw "Python not found. Set TRADING_MVP_PYTHON."
}

$freeC = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
$plan = [ordered]@{
    mode = "ws_market_filter_visible_plan"
    ok = $true
    would_run = (-not [bool]$PlanOnly)
    input = $InputPath
    source_postprocess = $PostprocessPath
    source_manifest = $SourceManifestPath
    normalized_output = $normalizedOutput
    market_manifest = $marketManifest
    market_report = $marketReport
    quality_output = $qualityOutput
    postprocess_output = $postprocessOutput
    console_log = $consoleLog
    progress_log = $progressLog
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    free_c_gb = $freeC
    filter_config = [ordered]@{
        required_event_kinds = $FilterRequiredEventKinds
        max_gap_sec = $FilterMaxGapSec
        min_rows_per_market = $FilterMinRowsPerMarket
        min_market_span_hours = $FilterMinMarketSpanHours
        min_market_duration_ratio = $FilterMinMarketDurationRatio
        min_accepted_markets = $FilterMinAcceptedMarkets
        min_accepted_exchanges = $FilterMinAcceptedExchanges
        min_total_rows = $FilterMinTotalRows
        max_market_event_share = $FilterMaxMarketEventShare
    }
    quality_config = [ordered]@{
        min_rows = $WsQualityMinRows
        min_exchanges = $WsQualityMinExchanges
        min_markets = $WsQualityMinMarkets
        min_span_hours = $WsQualityMinSpanHours
        min_duration_ratio = $WsQualityMinDurationRatio
        max_parse_error_rate = $WsQualityMaxParseErrorRate
        required_event_kinds = $WsQualityRequiredEventKinds
        min_markets_with_required_kinds = $WsQualityMinMarketsWithRequiredKinds
        max_market_event_share = $WsQualityMaxMarketEventShare
        max_gap_sec = $WsQualityMaxGapSec
        max_manifest_error_count = $WsQualityMaxManifestErrorCount
    }
    next_after_postprocess = "Run replay validation PlanOnly only if postprocess artifact has replay_allowed=true."
    blocked_actions = @("live_orders", "api_keys", "leverage_or_margin", "replay_grid_if_market_filter_or_data_quality_rejected")
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

$argsList = @(
    $script,
    "--input", $InputPath,
    "--normalized-output", $normalizedOutput,
    "--manifest-output", $marketManifest,
    "--report-output", $marketReport,
    "--quality-output", $qualityOutput,
    "--postprocess-output", $postprocessOutput,
    "--filter-required-event-kinds", $FilterRequiredEventKinds,
    "--filter-max-gap-sec", ([string]$FilterMaxGapSec),
    "--filter-min-rows-per-market", ([string]$FilterMinRowsPerMarket),
    "--filter-min-market-span-hours", ([string]$FilterMinMarketSpanHours),
    "--filter-min-market-duration-ratio", ([string]$FilterMinMarketDurationRatio),
    "--filter-min-accepted-markets", ([string]$FilterMinAcceptedMarkets),
    "--filter-min-accepted-exchanges", ([string]$FilterMinAcceptedExchanges),
    "--filter-min-total-rows", ([string]$FilterMinTotalRows),
    "--filter-max-market-event-share", ([string]$FilterMaxMarketEventShare),
    "--min-rows", ([string]$WsQualityMinRows),
    "--min-exchanges", ([string]$WsQualityMinExchanges),
    "--min-markets", ([string]$WsQualityMinMarkets),
    "--min-span-hours", ([string]$WsQualityMinSpanHours),
    "--min-duration-ratio", ([string]$WsQualityMinDurationRatio),
    "--max-parse-error-rate", ([string]$WsQualityMaxParseErrorRate),
    "--required-event-kinds", $WsQualityRequiredEventKinds,
    "--min-markets-with-required-kinds", ([string]$WsQualityMinMarketsWithRequiredKinds),
    "--max-market-event-share", ([string]$WsQualityMaxMarketEventShare),
    "--max-gap-sec", ([string]$WsQualityMaxGapSec),
    "--max-manifest-error-count", ([string]$WsQualityMaxManifestErrorCount),
    "--progress-every-lines", "1000000",
    "--progress-file", $progressLog,
    "--print-progress"
)
if ($PostprocessPath) {
    $argsList += @("--source-postprocess", $PostprocessPath)
}
if ($SourceManifestPath) {
    $argsList += @("--source-manifest", $SourceManifestPath)
}

Write-Host "Starting visible WS market filter"
Write-Host "Input: $InputPath"
Write-Host "Source postprocess: $PostprocessPath"
Write-Host "Market-filtered normalized: $normalizedOutput"
Write-Host "Postprocess: $postprocessOutput"
Write-Host "Progress: $progressLog"
Write-Host "Free C: $freeC GB"

$transcriptStarted = $false
try {
    Start-Transcript -Path $consoleLog -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

try {
    "stderr is merged into stdout for inline visible execution. See $stdoutLog" | Set-Content -LiteralPath $stderrLog -Encoding UTF8
    Write-Host "Worker mode: inline visible python"
    & $python @argsList 2>&1 | Tee-Object -FilePath $stdoutLog
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $stdoutTail = if (Test-Path -LiteralPath $stdoutLog) { Get-Content -LiteralPath $stdoutLog -Tail 20 } else { @() }
        throw "ws-market-filter failed with exit code $exitCode. output tail: $($stdoutTail -join ' | ')"
    }
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $postprocessOutput)) {
    throw "Expected market-filter postprocess artifact was not created: $postprocessOutput"
}

$result = Get-Content -Raw -LiteralPath $postprocessOutput | ConvertFrom-Json
Write-Host ("Replay allowed: {0}" -f ([bool]$result.replay_allowed))
Write-Host ("Accepted markets: {0}" -f $result.market_filter.metrics.accepted_markets)
Write-Host ("Rejected markets: {0}" -f $result.market_filter.metrics.rejected_markets)
Write-Host ("Output rows: {0}" -f $result.market_filter.metrics.output_rows)
Write-Host ("Filter reasons: {0}" -f (@($result.market_filter.reasons) -join ","))
Write-Host ("Data-quality reasons: {0}" -f (@($result.data_quality.reasons) -join ","))

if (-not $NoPause) {
    Read-Host "Press Enter to close this market-filter window"
}
