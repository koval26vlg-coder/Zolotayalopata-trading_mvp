param(
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_drift_reversal_planonly_$timestamp.json"
}

function Invoke-JsonScript {
    param([string]$Path)

    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Script failed with exit code ${LASTEXITCODE}: $Path"
    }
    return ($raw | ConvertFrom-Json)
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

function Save-Result {
    param($Payload)

    $outDir = Split-Path -Parent $OutputPath
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 14
        return
    }

    Write-Host "Listing Event Drift/Reversal PlanOnly" -ForegroundColor Cyan
    Write-Host "Generated: $($Payload.generated_at)"
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $OutputPath"
    Write-Host ""
    Write-Host "Next valid moves" -ForegroundColor Yellow
    foreach ($move in @($Payload.next_valid_moves)) {
        Write-Host "  - $move"
    }
}

$gate = Invoke-JsonScript -Path $gateChecker
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_listing_event_drift_reversal_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "listing_event_drift_reversal"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        reason = "Active run gate is $($gate.status); only gate-compliant status/resume work is allowed."
        gate_status = $gate.status
        output_path = $OutputPath
        next_valid_moves = @(
            "If RUNNING, wait and only do status/ETA checks.",
            "If STOPPED_INCOMPLETE, visibly resume or explicitly reject the dataset before branch work.",
            "Do not select, collect, replay, grid, paper-forward, live order, or API-key workflow while the gate is blocked."
        )
    }
    Save-Result -Payload $blocked
    exit 0
}

$calendarCandidates = @(
    (Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.csv"),
    (Join-Path $repoRoot "exports\trading-mvp\listings\non_binance_listing_events.jsonl"),
    (Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_calendar.json"),
    (Join-Path $repoRoot "exports\trading-mvp\analysis\listing_event_calendar.jsonl")
)
$existingCalendars = @($calendarCandidates | Where-Object { Test-Path -LiteralPath $_ })
$hasEventCalendar = $existingCalendars.Count -gt 0

$roundTripFeeBps = 39.0
$entryExitSlippageBps = 30.0
$spreadBufferBps = 30.0
$missedEntryBufferBps = 25.0
$eventRiskBufferBps = 50.0
$minimumGrossMoveHurdleBps = $roundTripFeeBps + $entryExitSlippageBps + $spreadBufferBps + $missedEntryBufferBps + $eventRiskBufferBps

$decision = if ($hasEventCalendar) {
    "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_READY_FOR_EVENT_NORMALIZER"
} else {
    "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_NEEDS_BIAS_CONTROLLED_EVENT_CALENDAR"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_listing_event_drift_reversal_planonly"
    decision = $decision
    selected_branch = "listing_event_drift_reversal"
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    research_only = $true
    gate_status = $gate.status
    cross_venue_rejection_evidence = [ordered]@{
        output_path = [string]$gate.last_cross_venue_dislocation_full_output_path
        candidate_events = $gate.last_cross_venue_dislocation_full_candidate_events
        eligible_events = $gate.last_cross_venue_dislocation_full_eligible_events
        max_gross_edge_bps = $gate.last_cross_venue_dislocation_full_max_gross_edge_bps
        max_net_edge_bps = $gate.last_cross_venue_dislocation_full_max_net_edge_bps
        decision = "rejected_no_net_edge_after_base_fees"
    }
    cost_hurdle = [ordered]@{
        policy = "base/VIP0/no-volume only; do not accept lower-cost sensitivity as proof"
        round_trip_fee_bps = $roundTripFeeBps
        entry_exit_slippage_bps = $entryExitSlippageBps
        spread_buffer_bps = $spreadBufferBps
        missed_entry_buffer_bps = $missedEntryBufferBps
        event_risk_buffer_bps = $eventRiskBufferBps
        minimum_gross_move_hurdle_bps = $minimumGrossMoveHurdleBps
        note = "Listing/post-spike branch must target moves far larger than microstructure scalps; otherwise base fees dominate."
    }
    local_event_calendar = [ordered]@{
        required = $true
        present = $hasEventCalendar
        existing_paths = @($existingCalendars)
        candidate_paths = @($calendarCandidates)
        required_schema = @(
            "event_id",
            "exchange",
            "base",
            "quote",
            "symbol",
            "listed_at_utc",
            "announcement_at_utc",
            "source_url",
            "source_type",
            "delisted_at_utc",
            "is_delisted",
            "first_trade_ts_utc",
            "survivorship_status"
        )
    }
    research_hypotheses = @(
        [ordered]@{
            name = "post_listing_drift"
            thesis = "After initial listing, thin non-Binance markets can keep drifting if liquidity/attention expands after first prints."
            entry_windows = @("5m_after_first_trade", "15m_after_first_trade", "60m_after_first_trade")
            exit_windows = @("1h", "4h", "24h")
            blocked_if = @("spread_too_wide", "missing_first_trade_ts", "no_holdout_by_listing_date")
        },
        [ordered]@{
            name = "post_spike_reversal"
            thesis = "Large listing spikes can mean-revert after liquidity thins and early buyers exhaust."
            entry_windows = @("after_1h_spike", "after_4h_spike")
            exit_windows = @("4h", "24h", "72h")
            blocked_if = @("requires_short_without_borrow", "spread_too_wide", "delist_freeze_risk_unmodeled")
        }
    )
    data_requirements = @(
        "Bias-controlled listing/delisting calendar across MEXC/Gate and any later allowed non-Binance venues.",
        "OHLCV around each event at 1m/5m/1h granularity from pre-listing or first trade through at least 72h.",
        "Spread/depth snapshots or conservative spread model for every entry/exit window.",
        "Delisted, frozen, no-trade and missing-data events retained as negative/blocked outcomes.",
        "Exchange fee schedule pinned to base/VIP0/no-volume assumptions.",
        "Venue-risk flags: withdrawal freeze, maintenance, delisting notice, abnormal spread, stale quotes."
    )
    validation_gates = @(
        "sample_size: >= 100 bias-controlled listing events before any acceptance discussion.",
        "venue_diversity: >= 2 venues and no single venue contributes > 60% of net PnL.",
        "market_diversity: >= 30 bases and no single base contributes > 15% of net PnL.",
        "economics: median and aggregate net expectancy after base fees/slippage/spread/event buffers > 0.",
        "oos: chronological train/test split by listing date, holdout net PnL > 0 and profit factor >= 1.2.",
        "walk_forward: >= 60% positive folds with positive median net expectancy.",
        "stress: non-negative after 2x slippage, +50% fee buffer, missed-entry delay and delist/freeze haircut.",
        "risk: max drawdown and tail loss remain inside fixed research limits."
    )
    rejection_gates = @(
        "event_calendar_missing_or_survivorship_biased",
        "too_few_events_after_quality_filters",
        "net_expectancy_negative_after_base_fees",
        "holdout_or_walk_forward_failure",
        "stress_missed_entry_wide_spread_or_delist_failure",
        "requires_shorting_margin_or_live_withdrawal_timing_to_work"
    )
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "grid_search",
        "paper_forward",
        "new_hidden_or_background_collect",
        "channel_p2p_offramp_custody_analysis",
        "claiming_high_winrate_without_positive_net_expectancy_oos_walk_forward_stress"
    )
    next_valid_moves = if ($hasEventCalendar) {
        @(
            "Implement a read-only listing event normalizer/backtester PlanOnly against the existing calendar.",
            "Keep base/VIP0/no-volume cost hurdle in the backtester.",
            "Do not collect, grid, live trade, use API keys, leverage, margin or paper-forward before validation gates exist."
        )
    } else {
        @(
            "Create or source a bias-controlled local listing/delisting calendar artifact with the required schema.",
            "Include delisted/frozen/no-trade events; do not use only surviving winners.",
            "After the calendar exists, implement a read-only event normalizer/backtester PlanOnly.",
            "Do not start a long collect/grid/live/API/paper-forward from this PlanOnly step."
        )
    }
    commands = [ordered]@{
        rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
    }
    output_path = $OutputPath
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "listing_event_drift_reversal PlanOnly scaffold generated. The branch is research-only and currently requires a bias-controlled listing/delisting event calendar before any backtest/collect/grid/live step."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Build or source the local bias-controlled listing/delisting event calendar artifact with required schema; include delisted/frozen/no-trade outcomes. Do not start collect/grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value "Build or source the local bias-controlled listing/delisting event calendar artifact with required schema; include delisted/frozen/no-trade outcomes. Do not start collect/grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = if ($hasEventCalendar) { "planonly_ready_for_event_normalizer" } else { "planonly_needs_event_calendar" }
        decision_source = $OutputPath
        selected_at = $result.generated_at
        previous_branch = "cross_venue_spot_dislocation_inventory_rebalance"
        previous_verdict = "rejected_no_net_edge_after_base_fees"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_branch_required = $false
        next_step_required = if ($hasEventCalendar) { "implement_read_only_listing_event_normalizer_backtester_planonly" } else { "create_bias_controlled_listing_delisting_event_calendar" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_planonly_at" -Value $result.generated_at
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_planonly_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_planonly_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_planonly_has_event_calendar" -Value $hasEventCalendar
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
