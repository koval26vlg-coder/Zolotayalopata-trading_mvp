param(
    [string]$CalendarPath = "",
    [string]$CalendarSummaryPath = "",
    [string]$MarketManifestPath = "",
    [string]$HistoryJsonlPath = "",
    [string]$HistoryManifestPath = "",
    [string]$OutputPath = "",
    [string]$Quote = "USDT",
    [int]$PreWindowSec = 3600,
    [int]$PostWindowSec = 259200,
    [int]$MinOverlapEvents = 100,
    [int]$MinOverlapBases = 30,
    [int]$MinOverlapExchanges = 2,
    [int]$MinHistoryEvents = 30,
    [int]$MinHistoryBases = 30,
    [int]$MinHistoryExchanges = 2,
    [double]$MaxSingleExchangeEventFraction = 0.60,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\listing_event_normalizer.py"

if (-not $CalendarPath) {
    $CalendarPath = Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.csv"
}
if (-not $CalendarSummaryPath) {
    $CalendarSummaryPath = [System.IO.Path]::ChangeExtension($CalendarPath, ".summary.json")
}
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_normalizer_planonly_$timestamp.json"
}

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )

    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
$rawGate = $null
if (Test-Path -LiteralPath $gatePath) {
    $rawGate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
}
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "listing_event_normalizer_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        would_start = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
    }
    if ($Json) {
        $blocked | ConvertTo-Json -Depth 8
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
}

if (-not $HistoryJsonlPath -and $rawGate -and ($rawGate.PSObject.Properties.Name -contains "last_listing_event_history_collect_output_path")) {
    $candidateHistoryJsonl = [string]$rawGate.last_listing_event_history_collect_output_path
    if ($candidateHistoryJsonl -and (Test-Path -LiteralPath $candidateHistoryJsonl)) {
        $HistoryJsonlPath = $candidateHistoryJsonl
    }
}
if (-not $HistoryManifestPath -and $rawGate -and ($rawGate.PSObject.Properties.Name -contains "last_listing_event_history_collect_manifest_path")) {
    $candidateHistoryManifest = [string]$rawGate.last_listing_event_history_collect_manifest_path
    if ($candidateHistoryManifest -and (Test-Path -LiteralPath $candidateHistoryManifest)) {
        $HistoryManifestPath = $candidateHistoryManifest
    }
}
if (-not $MarketManifestPath -and (-not $HistoryJsonlPath -or -not $HistoryManifestPath)) {
    $candidate = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\backtests") -Filter "ws_market_filter_manifest_*.json" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($candidate) {
        $MarketManifestPath = $candidate.FullName
    }
}

if (-not (Test-Path -LiteralPath $CalendarPath)) {
    throw "Calendar path not found: $CalendarPath"
}
if ($HistoryJsonlPath -and (-not (Test-Path -LiteralPath $HistoryJsonlPath))) {
    throw "History JSONL path not found: $HistoryJsonlPath"
}
if ($HistoryManifestPath -and (-not (Test-Path -LiteralPath $HistoryManifestPath))) {
    throw "History manifest path not found: $HistoryManifestPath"
}
if ((-not $HistoryJsonlPath -or -not $HistoryManifestPath) -and (-not (Test-Path -LiteralPath $MarketManifestPath))) {
    throw "Market manifest path not found: $MarketManifestPath"
}

$pythonCandidates = @(
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = $pythonCmd.Source
    }
}
if (-not $python) {
    throw "Python runtime not found."
}

$argsList = @(
    $modulePath,
    "--calendar", $CalendarPath,
    "--calendar-summary", $CalendarSummaryPath,
    "--output", $OutputPath,
    "--quote", $Quote,
    "--pre-window-sec", $PreWindowSec,
    "--post-window-sec", $PostWindowSec,
    "--min-overlap-events", $MinOverlapEvents,
    "--min-overlap-bases", $MinOverlapBases,
    "--min-overlap-exchanges", $MinOverlapExchanges,
    "--min-history-events", $MinHistoryEvents,
    "--min-history-bases", $MinHistoryBases,
    "--min-history-exchanges", $MinHistoryExchanges,
    "--max-single-exchange-event-fraction", $MaxSingleExchangeEventFraction
)
if ($HistoryJsonlPath -and $HistoryManifestPath) {
    $argsList += @("--history-jsonl", $HistoryJsonlPath, "--history-manifest", $HistoryManifestPath)
} else {
    $argsList += @("--market-manifest", $MarketManifestPath)
}

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "listing_event_normalizer.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $source = [string]$result.source
    $nextStep = if ($decision -eq "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY") {
        "Implement read-only listing_event_drift_reversal event replay PlanOnly on normalized events. No grid/live/API/paper-forward."
    } else {
        "Source or plan visible listing-event OHLCV history with delisted/frozen/no-trade outcomes before any replay/grid/live/API/paper-forward."
    }
    $verdict = if ($decision -eq "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY") {
        "normalizer_ready_for_event_replay_planonly"
    } elseif ($decision -eq "LISTING_EVENT_NORMALIZER_PLANONLY_INSUFFICIENT_OVERLAP_NEEDS_EVENT_OHLCV_HISTORY") {
        "normalizer_insufficient_overlap_needs_event_ohlcv_history"
    } else {
        "normalizer_blocked"
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    $reason = if ($source -eq "listing_event_history") {
        "Listing-event history normalizer PlanOnly completed. history_ok_events=$($result.history_coverage.ok_events), history_ok_bases=$($result.history_coverage.ok_unique_bases), history_ok_exchanges=$($result.history_coverage.ok_exchange_count), max_single_exchange_fraction=$($result.history_coverage.max_single_exchange_ok_event_fraction)."
    } else {
        "Listing-event normalizer PlanOnly completed. Current clean WS slice overlap: matched_time_overlap_events=$($result.overlap.matched_time_overlap_events), overlap_unique_bases=$($result.overlap.overlap_unique_bases), overlap_exchange_count=$($result.overlap.overlap_exchange_count)."
    }
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value $reason
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value ([bool]$result.replay_allowed_now)
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "cross_venue_spot_dislocation_inventory_rebalance"
        previous_verdict = "rejected_no_net_edge_after_base_fees"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = [bool]$result.replay_allowed_now
        grid_allowed = $false
        paper_forward_allowed = $false
        next_branch_required = $false
        next_step_required = [string]$result.required_next_step
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_decision" -Value $decision
    if ($source -eq "listing_event_history") {
        Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_source" -Value "listing_event_history"
        Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_history_events" -Value ([int]$result.history_coverage.ok_events)
        Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_history_bases" -Value ([int]$result.history_coverage.ok_unique_bases)
    } else {
        Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_source" -Value "ws_market_filter"
        Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_overlap_events" -Value ([int]$result.overlap.matched_time_overlap_events)
        Set-JsonProperty -Object $gateDoc -Name "last_listing_event_normalizer_overlap_bases" -Value ([int]$result.overlap.overlap_unique_bases)
    }
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 14
    exit 0
}

Write-Host "Listing event normalizer PlanOnly" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
if ([string]$result.source -eq "listing_event_history") {
    Write-Host "Source: listing_event_history"
    Write-Host "History OK events: $($result.history_coverage.ok_events)"
    Write-Host "History OK bases: $($result.history_coverage.ok_unique_bases)"
    Write-Host "History OK exchanges: $($result.history_coverage.ok_exchange_count)"
} else {
    Write-Host "Source: ws_market_filter"
    Write-Host "Calendar rows: $($result.calendar.rows)"
    Write-Host "Accepted markets: $($result.market_data.accepted_markets)"
    Write-Host "WS span hours: $([Math]::Round([double]$result.market_data.span_hours, 2))"
    Write-Host "Matched time-overlap events: $($result.overlap.matched_time_overlap_events)"
    Write-Host "Overlap bases: $($result.overlap.overlap_unique_bases)"
}
Write-Host "Output: $OutputPath"
Write-Host ""
Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in @($result.next_valid_moves)) {
    Write-Host "  - $move"
}
