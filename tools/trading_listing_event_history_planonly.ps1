param(
    [string]$NormalizerOutputPath = "",
    [string]$DataQualityOutputPath = "",
    [string]$CalendarPath = "",
    [string]$OutputPath = "",
    [int]$TargetEvents = 100,
    [int]$TargetBases = 30,
    [int]$PreWindowSec = 3600,
    [int]$PostWindowSec = 259200,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"

if (-not $CalendarPath) {
    $CalendarPath = Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.csv"
}
if (-not $NormalizerOutputPath) {
    $candidate = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "listing_event_normalizer_planonly_*.json" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($candidate) {
        $NormalizerOutputPath = $candidate.FullName
    }
}
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_history_planonly_$timestamp.json"
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

function Count-CsvRows {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return 0
    }
    $count = 0
    Import-Csv -LiteralPath $Path | ForEach-Object { $count++ }
    return $count
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "listing_event_history_planonly"
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
        output_path = $OutputPath
        gate_updated = $false
    }
    $blockedOutDir = Split-Path -Parent $OutputPath
    if ($blockedOutDir -and -not (Test-Path -LiteralPath $blockedOutDir)) {
        New-Item -ItemType Directory -Force -Path $blockedOutDir | Out-Null
    }
    $blocked | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Json) {
        $blocked | ConvertTo-Json -Depth 8
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $CalendarPath)) {
    throw "Calendar path not found: $CalendarPath"
}
if (-not (Test-Path -LiteralPath $NormalizerOutputPath)) {
    throw "Normalizer output path not found: $NormalizerOutputPath"
}
if (-not $DataQualityOutputPath) {
    if ($gate.PSObject.Properties.Name -contains "last_listing_event_history_data_quality_output_path") {
        $gateQualityPath = [string]$gate.last_listing_event_history_data_quality_output_path
        if ($gateQualityPath -and (Test-Path -LiteralPath $gateQualityPath)) {
            $DataQualityOutputPath = $gateQualityPath
        }
    }
    if (-not $DataQualityOutputPath) {
        $candidateQuality = Get-ChildItem -Path (Join-Path $repoRoot "exports\trading-mvp\analysis") -Filter "listing_event_history_data_quality_*.json" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($candidateQuality) {
            $DataQualityOutputPath = $candidateQuality.FullName
        }
    }
}

$normalizer = Get-Content -Raw -LiteralPath $NormalizerOutputPath | ConvertFrom-Json
$quality = $null
if ($DataQualityOutputPath -and (Test-Path -LiteralPath $DataQualityOutputPath)) {
    $quality = Get-Content -Raw -LiteralPath $DataQualityOutputPath | ConvertFrom-Json
}
$calendarRows = Count-CsvRows -Path $CalendarPath
$matchedMarkets = if ($normalizer.overlap) { [int]$normalizer.overlap.matched_current_market_events } else { 0 }
$matchedOverlap = if ($normalizer.overlap) { [int]$normalizer.overlap.matched_time_overlap_events } else { 0 }

$qualityRejected = (
    ([string]$gate.next_goal_decision -eq "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN") -or
    ($quality -and -not [bool]$quality.accepted)
)
$decision = if ($qualityRejected) {
    "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_REVISE_COLLECT_PLAN"
} else {
    "LISTING_EVENT_HISTORY_PLANONLY_READY_FOR_VISIBLE_HISTORY_COLLECT_APPROVAL"
}
$qualityMetrics = if ($quality -and $quality.metrics) { $quality.metrics } else { $null }
$qualityCounts = if ($quality -and $quality.counts) { $quality.counts } else { $null }
$qualityReasons = if ($quality -and $quality.reasons) { @($quality.reasons) } else { @() }
$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "listing_event_history_planonly"
    decision = $decision
    selected_branch = "listing_event_drift_reversal"
    would_start = $false
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    gate_status = $gate.status
    evidence = [ordered]@{
        normalizer_output_path = $NormalizerOutputPath
        normalizer_decision = [string]$normalizer.decision
        data_quality_output_path = if ($quality) { $DataQualityOutputPath } else { $null }
        data_quality_decision = if ($quality) { [string]$quality.decision } else { $null }
        data_quality_rejected = [bool]$qualityRejected
        data_quality_reasons = $qualityReasons
        data_quality_metrics = if ($qualityMetrics) {
            [ordered]@{
                selected_events = $qualityMetrics.selected_events
                ok_events = $qualityMetrics.ok_events
                ok_bases = $qualityMetrics.ok_bases
                ok_exchanges = $qualityMetrics.ok_exchanges
                ok_event_granularity_slots = $qualityMetrics.ok_event_granularity_slots
                ok_event_fraction = $qualityMetrics.ok_event_fraction
                ok_slot_fraction = $qualityMetrics.ok_slot_fraction
                api_error_slot_rate = $qualityMetrics.api_error_slot_rate
                max_single_exchange_ok_event_fraction = $qualityMetrics.max_single_exchange_ok_event_fraction
            }
        } else {
            $null
        }
        data_quality_counts = if ($qualityCounts) {
            [ordered]@{
                rows_by_exchange = $qualityCounts.rows_by_exchange
                ok_rows_by_exchange = $qualityCounts.ok_rows_by_exchange
                error_rows_by_exchange = $qualityCounts.error_rows_by_exchange
                placeholder_rows_by_exchange = $qualityCounts.placeholder_rows_by_exchange
                ok_events_by_exchange = $qualityCounts.ok_events_by_exchange
            }
        } else {
            $null
        }
        current_ws_span_hours = if ($normalizer.market_data) { [Math]::Round([double]$normalizer.market_data.span_hours, 2) } else { $null }
        calendar_path = $CalendarPath
        calendar_rows = $calendarRows
        matched_current_market_events = $matchedMarkets
        matched_time_overlap_events = $matchedOverlap
        reason_current_slice_cannot_replay = "Current clean WS slice has no listing-event time overlap, so any replay would be false evidence."
    }
    required_dataset_contract = [ordered]@{
        event_source = "existing bias-controlled listing calendar plus explicit delisted/frozen/no-trade retention"
        target_events_min = $TargetEvents
        target_bases_min = $TargetBases
        exchanges_min = 2
        pre_window_sec = $PreWindowSec
        post_window_sec = $PostWindowSec
        required_granularities = @("1m", "5m", "1h")
        required_fields = @(
            "exchange",
            "symbol",
            "base",
            "quote",
            "event_ts",
            "candle_ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trade_count_if_available",
            "spread_proxy_or_snapshot_if_available",
            "data_status",
            "delisted_or_no_trade_flag"
        )
        quality_gates = @(
            "retain missing/no-trade/frozen/delisted outcomes as rows or explicit blocked events",
            "no single exchange contributes more than 60 percent of accepted event PnL",
            "no single base contributes more than 15 percent of accepted event PnL",
            "chronological train/test split by listing date",
            "walk-forward folds before acceptance",
            "base/VIP0/no-volume fees only",
            "stress with wider spread, missed entry, and delist/freeze haircut"
        )
    }
    source_plan = @(
        [ordered]@{
            exchange = "mexc"
            source_type = "public_spot_klines_history"
            api_keys_required = $false
            live_orders = $false
            note = "Use only public OHLCV endpoints when explicitly approved; missing historical candles must become no-data/no-trade outcomes, not silently dropped."
        },
        [ordered]@{
            exchange = "gateio"
            source_type = "public_spot_candlesticks_history"
            api_keys_required = $false
            live_orders = $false
            note = "Use only public OHLCV endpoints when explicitly approved; delisted symbols may be unavailable and must remain negative/blocked evidence."
        }
    )
    revised_collection_strategy = if ($qualityRejected) {
        [ordered]@{
            reason = "The first listing-event history artifact is MEXC-only in OK rows and fails the minimum two-venue evidence contract."
            do_not_repeat = @(
                "do_not_run_same_event_sample_with_same_gateio_endpoint_behavior",
                "do_not_treat_mexc_only_ok_rows_as_cross_venue_edge_evidence",
                "do_not_move_to_replay_grid_or_paper_forward"
            )
            required_plan_changes = @(
                "add_preflight_symbol_history_probe_per_exchange_before_full_ohlcv_collection",
                "separate_gateio_api_error_from_true_no_data_or_delisted_outcome",
                "build_exchange_event_coverage_matrix_before_collect_approval",
                "resample_or_expand_listing_events_until_two_venue_ok_coverage_target_is_plausible",
                "retain_failed_gateio_events_as negative evidence instead of dropping them",
                "only request actual visible collect after revised preview shows expected two_venue_coverage"
            )
            minimum_revised_preview_gates = [ordered]@{
                expected_events = $TargetEvents
                expected_bases = $TargetBases
                expected_exchanges = 2
                expected_two_venue_ok_events = 30
                max_expected_api_error_slot_rate = 0.5
                max_single_exchange_expected_ok_event_fraction = 0.7
            }
        }
    } else {
        $null
    }
    visible_run_policy = [ordered]@{
        actual_collect_requires_explicit_user_approval = $true
        visible_terminal_or_monitor_required = $true
        hidden_background_collect_allowed = $false
        metadata_required = @("run_id", "command", "cwd", "stdout", "stderr", "output_path", "manifest_path", "start_time", "expected_duration")
    }
    blocked_actions = @(
        "replay_on_current_ws_slice",
        "grid_search",
        "paper_forward",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "hidden_or_background_collect"
    )
    next_valid_moves = if ($qualityRejected) {
        @(
            "Revise the listing-event history collect preview so it performs symbol-history preflight and two-venue coverage estimation before any actual collect.",
            "Do not run another actual collect until the revised preview shows plausible two-venue OK coverage and preserves Gate failures as explicit evidence.",
            "After a revised approved collect, rerun data-quality before normalizer/replay/grid."
        )
    } else {
        @(
            "Implement visible PlanOnly preview for listing-event OHLCV history collect without starting it.",
            "Only after explicit user approval, run a visible public-history collector with metadata and progress monitor.",
            "After history collection, run data-quality and event normalizer again before any replay."
        )
    }
    commands = [ordered]@{
        rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
    }
    output_path = $OutputPath
}

$outDir = Split-Path -Parent $OutputPath
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}
$result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $nextStep = if ($qualityRejected) {
        "Revise listing-event history collect preview with symbol-history preflight and two-venue coverage estimation. Do not start actual collect/grid/replay/live/API/paper-forward."
    } else {
        "Implement visible PlanOnly preview for listing-event OHLCV history collect. Do not start actual collect/grid/replay/live/API/paper-forward without explicit approval."
    }
    $gateDecision = if ($qualityRejected) { "LISTING_EVENT_HISTORY_DATA_QUALITY_REJECTED_NEEDS_RECOLLECT_PLAN" } else { $decision }
    $gateVerdict = if ($qualityRejected) { "history_quality_rejected" } else { "history_planonly_ready_for_visible_collect_preview" }
    $nextRequired = if ($qualityRejected) { "revise_listing_event_history_collect_preview_planonly" } else { "implement_visible_listing_event_history_collect_preview_planonly" }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $gateDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value $(if ($qualityRejected) { "Listing-event history quality remains rejected; revise collect preview/venue coverage before any replay/grid." } else { "Current clean WS slice has matched_time_overlap_events=$matchedOverlap for listing events. Event replay is blocked until separate listing-event OHLCV history is sourced with survivorship controls." })
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = $gateVerdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "cross_venue_spot_dislocation_inventory_rebalance"
        previous_verdict = "rejected_no_net_edge_after_base_fees"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = $nextRequired
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_planonly_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_planonly_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_history_planonly_decision" -Value $decision
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 14
    exit 0
}

Write-Host "Listing event history PlanOnly" -ForegroundColor Cyan
Write-Host "Decision: $decision"
Write-Host "Calendar rows: $calendarRows"
Write-Host "Matched time-overlap events in current WS slice: $matchedOverlap"
Write-Host "Output: $OutputPath"
Write-Host ""
Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in @($result.next_valid_moves)) {
    Write-Host "  - $move"
}
