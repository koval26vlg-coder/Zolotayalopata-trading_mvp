param(
    [string]$ManifestPath = "",
    [string]$RunLabel = "",
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
$runner = Join-Path $repoRoot "trading_mvp\run_mvp.ps1"
$normalizedDir = Join-Path $repoRoot "exports\trading-mvp\normalized"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$runDir = Join-Path $repoRoot "exports\trading-mvp\run"

New-Item -ItemType Directory -Force -Path $normalizedDir, $backtestDir, $runDir | Out-Null
Set-Location $repoRoot

$gateStatus = $null
if (Test-Path -LiteralPath $gatePath) {
    $gateStatus = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
    if ($gateStatus.status -eq "RUNNING") {
        throw "Active run gate is RUNNING. Only status/ETA checks are allowed until the current run finishes."
    }
    if ($gateStatus.status -eq "STOPPED_INCOMPLETE") {
        throw "Active run gate is STOPPED_INCOMPLETE. Resume or reject the incomplete run before WS postprocess."
    }
}

if (-not $ManifestPath -and $null -ne $gateStatus) {
    $candidate = [string]$gateStatus.manifest_path
    if ($candidate -and ([System.IO.Path]::GetFileName($candidate) -like "ws_collect_*.json")) {
        $ManifestPath = $candidate
    }
}

if (-not $ManifestPath) {
    $result = [ordered]@{
        mode = "ws_postprocess_visible_plan"
        ok = $false
        would_run = $false
        reason = "ws_manifest_required"
        gate_status = if ($gateStatus) { $gateStatus.status } else { $null }
        gate_run_id = if ($gateStatus) { $gateStatus.run_id } else { $null }
        next_action = "Run this wrapper after a completed visible WS collect, or pass -ManifestPath <exports\\trading-mvp\\raw\\ws_collect_*.json> explicitly."
        blocked_actions = @("ws_replay_without_ws_postprocess", "ws_grid_without_data_quality", "live_orders", "api_keys", "leverage_or_margin")
    }
    $result | ConvertTo-Json -Depth 8
    if (-not $NoPause) {
        Read-Host "Press Enter to close this postprocess window"
    }
    exit 0
}

$ManifestPath = (Resolve-Path -LiteralPath $ManifestPath).Path
$manifestName = [System.IO.Path]::GetFileName($ManifestPath)
if ($manifestName -notlike "ws_collect_*.json") {
    throw "ManifestPath must point to a ws_collect_*.json manifest, got: $ManifestPath"
}

$baseName = [System.IO.Path]::GetFileNameWithoutExtension($ManifestPath)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$label = if ($RunLabel) { $RunLabel } else { "${baseName}_postprocess_$stamp" }

$normalizedOutput = Join-Path $normalizedDir ("ws_normalized_{0}.jsonl" -f $label)
$qualityOutput = Join-Path $backtestDir ("ws_data_quality_{0}.json" -f $label)
$postprocessOutput = Join-Path $backtestDir ("ws_postprocess_{0}.json" -f $label)
$consoleLog = Join-Path $runDir ("ws_postprocess_{0}.console.log" -f $label)

$plan = [ordered]@{
    mode = "ws_postprocess_visible_plan"
    ok = $true
    would_run = (-not [bool]$PlanOnly)
    manifest = $ManifestPath
    normalized_output = $normalizedOutput
    quality_output = $qualityOutput
    postprocess_output = $postprocessOutput
    console_log = $consoleLog
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
    next_after_postprocess = "Run replay/grid only if the postprocess artifact has replay_allowed=true. Otherwise reject/incomplete this WS dataset before changing strategy parameters."
    blocked_actions = @("live_orders", "api_keys", "leverage_or_margin", "paper_forward_without_accepted_research", "replay_grid_if_data_quality_rejected")
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Starting visible guarded WS postprocess"
Write-Host "Manifest: $ManifestPath"
Write-Host "Normalized: $normalizedOutput"
Write-Host "Quality: $qualityOutput"
Write-Host "Postprocess: $postprocessOutput"
Write-Host "Console log: $consoleLog"

$argsList = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner,
    "-Action", "ws-postprocess",
    "-InputPath", $ManifestPath,
    "-ManifestPath", $ManifestPath,
    "-OutputPath", $normalizedOutput,
    "-ReportOutputPath", $qualityOutput,
    "-PostprocessReportPath", $postprocessOutput,
    "-WsQualityMinRows", $WsQualityMinRows,
    "-WsQualityMinExchanges", $WsQualityMinExchanges,
    "-WsQualityMinMarkets", $WsQualityMinMarkets,
    "-WsQualityMinSpanHours", $WsQualityMinSpanHours,
    "-WsQualityMinDurationRatio", $WsQualityMinDurationRatio,
    "-WsQualityMaxParseErrorRate", $WsQualityMaxParseErrorRate,
    "-WsQualityRequiredEventKinds", $WsQualityRequiredEventKinds,
    "-WsQualityMinMarketsWithRequiredKinds", $WsQualityMinMarketsWithRequiredKinds,
    "-WsQualityMaxMarketEventShare", $WsQualityMaxMarketEventShare,
    "-WsQualityMaxGapSec", $WsQualityMaxGapSec,
    "-WsQualityMaxManifestErrorCount", $WsQualityMaxManifestErrorCount
)

$transcriptStarted = $false
try {
    Start-Transcript -Path $consoleLog -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host ("Transcript unavailable: {0}" -f $_.Exception.Message)
}

try {
    & pwsh @argsList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "ws-postprocess failed with exit code $exitCode"
    }
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $postprocessOutput)) {
    throw "Expected postprocess artifact was not created: $postprocessOutput"
}

$postprocess = Get-Content -Raw -LiteralPath $postprocessOutput | ConvertFrom-Json
$replayAllowed = [bool]$postprocess.replay_allowed
Write-Host ("Replay allowed: {0}" -f $replayAllowed)
if (-not $replayAllowed) {
    $reasons = @()
    if ($null -ne $postprocess.data_quality -and $null -ne $postprocess.data_quality.reasons) {
        $reasons = @($postprocess.data_quality.reasons)
    }
    Write-Host ("Data-quality rejected WS dataset. Reasons: {0}" -f ($reasons -join ", "))
    Write-Host "Do not run ws-replay/ws-grid-search on this dataset."
} else {
    Write-Host "Data-quality accepted. Replay/grid may be run only as research with OOS/walk-forward/stress gates."
}

if (-not $NoPause) {
    Read-Host "Press Enter to close this postprocess window"
}
