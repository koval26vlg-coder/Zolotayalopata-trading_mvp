param(
    [string]$EventCensusPath = "",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$acceptedDecision = "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_READY_FOR_FIXED_V1_PLANONLY"
$decision = "SLOW_LIQUIDITY_FIXED_V1_PLANONLY_READY_FOR_REPLAY_VALIDATION"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_fixed_v1_planonly_$timestamp.json"
}

function Resolve-RepoPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
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
    $Payload | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }

    Write-Host "Slow-liquidity fixed v1 PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Family: $($Payload.fixed_signal_v1.family)"
    Write-Host "Replay allowed now: $($Payload.replay_allowed_now)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "slow_liquidity_fixed_v1_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "slow_liquidity_regime_breakout_retest"
        would_start = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
        output_path = $OutputPath
    }
    Save-Result -Payload $blocked
    exit 0
}

$gateDoc = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { $null }
if (-not $EventCensusPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_event_census_output_path) {
    $EventCensusPath = [string]$gateDoc.last_slow_liquidity_event_census_output_path
}

$EventCensusPath = Resolve-RepoPath $EventCensusPath
$OutputPath = Resolve-RepoPath $OutputPath
if (-not $EventCensusPath -or -not (Test-Path -LiteralPath $EventCensusPath)) {
    throw "EventCensusPath is required and must point to an existing event-census artifact."
}

$census = Get-Content -Raw -LiteralPath $EventCensusPath | ConvertFrom-Json
if ([string]$census.decision -ne $acceptedDecision) {
    throw "Event census must be accepted before fixed v1 PlanOnly. decision=$($census.decision)"
}

$topFamily = [string]$census.event_census.top_family
if ([string]::IsNullOrWhiteSpace($topFamily)) {
    throw "Event census accepted but top_family is empty."
}
$familySummary = $census.event_census.family_summaries.$topFamily
if (-not $familySummary -or -not [bool]$familySummary.accepted_for_fixed_v1_plan) {
    throw "Top family is not accepted for fixed v1 plan: $topFamily"
}

$cleanBases = @($census.data_scope.clean_bases | ForEach-Object { [string]$_ } | Where-Object { $_ } | Sort-Object -Unique)
$acceptedFamilies = @($census.event_census.accepted_families | ForEach-Object { [string]$_ } | Where-Object { $_ })

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "slow_liquidity_fixed_v1_planonly"
    decision = $decision
    selected_branch = "slow_liquidity_regime_breakout_retest"
    would_start = $false
    research_only = $true
    strategy_accepted = $false
    replay_allowed_now = $true
    grid_allowed_now = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    event_census_path = $EventCensusPath
    fixed_signal_v1 = [ordered]@{
        name = "slow_liquidity_volatility_expansion_continuation_v1"
        family = $topFamily
        direction = "long_only_spot"
        primary_timeframe = "1h"
        context_timeframe = "4h"
        clean_bases = $cleanBases
        entry_rule = "enter next 1h open after accepted volatility expansion candle"
        event_filters = [ordered]@{
            context_4h_pass = "4h close above SMA(24) or 4h range midpoint"
            min_body_bps = 120.0
            min_true_range_atr = 2.0
            min_volume_percentile = 0.75
            min_target_geometry_bps = 300.0
            disabled_timeframes = @("15m")
        }
        stop_rule = "min(expansion candle low, expansion close - 1.5 * prior 1h ATR)"
        target_rule = "max(2R, 300 bps) from entry"
        max_hold_bars = 72
        cluster_window_sec = 43200
        no_grid = $true
    }
    event_base_rate = [ordered]@{
        accepted_families = $acceptedFamilies
        top_family = $topFamily
        top_family_independent_events = [int]$familySummary.independent_events
        top_family_event_bases = [int]$familySummary.event_bases
        top_family_event_exchanges = [int]$familySummary.event_exchanges
        top_family_max_single_base_event_fraction = [double]$familySummary.max_single_base_event_fraction
        total_independent_events = [int]$census.event_census.independent_events
    }
    cost_model = [ordered]@{
        account_assumption = "base/VIP0/no-volume"
        normal_round_trip_fee_bps = 40.0
        normal_spread_slippage_buffer_bps = 80.0
        normal_total_cost_bps = 120.0
        stress_total_cost_bps = 245.0
        minimum_target_geometry_bps = 300.0
        rule = "Reject replay if net expectancy after normal and stress costs is not robust."
    }
    validation_contract = [ordered]@{
        no_grid = $true
        chronological_split = "70/30 train/OOS by event time"
        walk_forward = "4 chronological folds; no random shuffle"
        min_trades = 100
        min_oos_trades = 20
        min_event_bases = 8
        min_event_exchanges = 2
        max_single_base_net_pnl_share = 0.25
        min_profit_factor = 1.2
        min_walk_forward_positive_ratio = 0.60
        pass_conditions = @(
            "all-events net expectancy after normal costs > 0",
            "OOS net expectancy after normal costs > 0",
            "OOS profit factor >= 1.2",
            "walk-forward positive folds >= 60%",
            "stress net expectancy remains >= 0",
            "no single base contributes >25% of net PnL",
            "winrate is reported but cannot override negative expectancy"
        )
    }
    blocked_actions = @(
        "grid_search",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward",
        "parameter_tuning_after_replay",
        "claiming_edge_from_event_census_only"
    )
    next_step_after_ready = "Run one fixed-parameter slow-liquidity v1 replay-validation PlanOnly from this contract. No grid/live/API/paper-forward."
    next_valid_moves = @(
        "Run fixed slow-liquidity v1 replay-validation PlanOnly.",
        "If OOS/walk-forward/stress/economics fail, reject this branch instead of tuning parameters.",
        "If replay passes, request independent review before paper-forward."
    )
    output_path = $OutputPath
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "slow-liquidity fixed v1 PlanOnly is ready for one NoGrid replay-validation. family=$topFamily, independent_events=$($result.event_base_rate.top_family_independent_events), bases=$($result.event_base_rate.top_family_event_bases), exchanges=$($result.event_base_rate.top_family_event_exchanges)."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $result.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $result.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_v1_plan_at" -Value $result.generated_at
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_v1_plan_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_v1_plan_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = "fixed_v1_planonly_ready_for_replay_validation"
        decision_source = $OutputPath
        selected_at = $result.generated_at
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $true
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        family = $topFamily
        independent_events = [int]$familySummary.independent_events
        event_bases = [int]$familySummary.event_bases
        event_exchanges = [int]$familySummary.event_exchanges
        next_step_required = "run_fixed_slow_liquidity_v1_replay_validation_planonly"
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
