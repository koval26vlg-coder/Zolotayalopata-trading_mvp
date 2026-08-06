param(
    [string]$QualityPath = "",
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
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_fixed_signal_planonly_$timestamp.json"
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

    Write-Host "Slow-liquidity fixed signal PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Clean bases: $($Payload.clean_slice.clean_bases.Count)"
    Write-Host "Replay allowed: $($Payload.replay_allowed_now)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_slow_liquidity_fixed_signal_planonly"
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
if (-not $QualityPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path) {
    $QualityPath = [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path
}

$QualityPath = Resolve-RepoPath $QualityPath
$OutputPath = Resolve-RepoPath $OutputPath

if (-not $QualityPath -or -not (Test-Path -LiteralPath $QualityPath)) {
    throw "QualityPath is required and must point to an existing slow-liquidity data-quality artifact."
}

$quality = Get-Content -Raw -LiteralPath $QualityPath | ConvertFrom-Json
$qualityAccepted = [bool]$quality.accepted
$gateAllowsFixedSignal = [bool](
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY") -or
    ([string]$quality.decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_QUALITY_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY") -or
    (
        $gateDoc -and
        $gateDoc.strategy_branch_status -and
        [string]$gateDoc.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gateDoc.strategy_branch_status.verdict -eq "history_quality_accepted_ready_for_fixed_signal_planonly"
    )
)

if (-not ($qualityAccepted -and $gateAllowsFixedSignal)) {
    $blockedByQuality = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_slow_liquidity_fixed_signal_planonly"
        decision = "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_BLOCKED_BY_DATA_QUALITY"
        selected_branch = "slow_liquidity_regime_breakout_retest"
        would_start = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        quality_path = $QualityPath
        quality_decision = [string]$quality.decision
        quality_accepted = $qualityAccepted
        gate_next_goal_decision = [string]$gate.next_goal_decision
        reason = "Slow-liquidity data-quality is not accepted for fixed-signal PlanOnly."
        output_path = $OutputPath
    }
    Save-Result -Payload $blockedByQuality
    exit 0
}

$cleanBases = @($quality.clean_markets.two_exchange_full_coverage_1h4h_bases | ForEach-Object { [string]$_ } | Where-Object { $_ } | Sort-Object -Unique)
$twoVenueBases = @($quality.clean_markets.two_exchange_bases | ForEach-Object { [string]$_ } | Where-Object { $_ } | Sort-Object -Unique)
$disabled15m = [bool]($quality.warnings -contains "15m_two_exchange_full_coverage_absent_use_1h4h_only")

$decision = "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER"
$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_slow_liquidity_fixed_signal_planonly"
    decision = $decision
    selected_branch = "slow_liquidity_regime_breakout_retest"
    would_start = $false
    research_only = $true
    strategy_accepted = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    quality_path = $QualityPath
    quality_decision = [string]$quality.decision
    clean_slice = [ordered]@{
        source = "slow_liquidity_history_data_quality"
        clean_bases = $cleanBases
        two_venue_bases = $twoVenueBases
        required_timeframes = @("1h", "4h")
        disabled_timeframes = if ($disabled15m) { @("15m") } else { @() }
        min_clean_bases_required = 8
        clean_bases_count = $cleanBases.Count
        note = "Use only bases with two-venue full coverage on 1h/4h. Do not use 15m until a separate clean 15m gate passes."
    }
    base_fee_cost_model = [ordered]@{
        account_assumption = "base/VIP0/no-volume"
        taker_round_trip_fee_bps = 40.0
        conservative_spread_slippage_buffer_bps = 80.0
        missed_fill_buffer_bps = 35.0
        adverse_selection_buffer_bps = 55.0
        false_break_buffer_bps = 35.0
        minimum_gross_move_hurdle_bps = 245.0
        minimum_target_after_cost_bps = 300.0
        rule = "Reject any event whose measured target/stop geometry cannot clear this hurdle before OOS."
    }
    fixed_signal_v0 = [ordered]@{
        name = "slow_liquidity_regime_breakout_retest_v0"
        direction = "long_only_spot"
        primary_timeframe = "1h"
        context_timeframe = "4h"
        disabled_timeframe = if ($disabled15m) { "15m" } else { "" }
        lookback_1h_bars = 96
        context_4h_bars = 42
        compression_range_width_max_atr = 1.20
        compression_min_bars = 24
        breakout_close_buffer_bps = 60.0
        volume_percentile_min = 0.70
        retest_window_bars = 12
        retest_tolerance_atr = 0.35
        entry_delay_bars = 1
        stop_atr_multiple = 1.20
        min_stop_bps = 120.0
        target_r_multiple = 2.20
        min_target_bps = 300.0
        max_hold_bars = 72
        cooldown_bars_after_exit = 24
        max_events_per_base_per_week = 3
    }
    entry_contract = [ordered]@{
        setup = "4h non-crash context + 1h compression + 1h breakout + delayed retest hold"
        enter_long = @(
            "base in clean_slice.clean_bases",
            "4h close above 4h SMA(42) or 4h range midpoint",
            "1h range_width_bps over lookback_1h_bars <= compression threshold",
            "1h close breaks range high by breakout_close_buffer_bps",
            "1h quote_volume percentile >= volume_percentile_min",
            "within retest_window_bars, low retests breakout zone and close remains above it",
            "target_bps >= minimum_target_after_cost_bps",
            "spread/liquidity proxy not stale and not above conservative guard"
        )
        block_entry = @(
            "15m-only confirmation required",
            "base not in clean 1h/4h two-venue slice",
            "target_bps below base fee cost hurdle",
            "same-base cooldown active",
            "volume spike without retest hold",
            "large gap candle where delayed entry invalidates R multiple"
        )
    }
    exit_contract = [ordered]@{
        stop = "below retest low minus stop_atr_multiple or min_stop_bps, whichever is wider"
        take_profit = "target_r_multiple * risk, but not below min_target_bps"
        time_stop = "max_hold_bars"
        kill_conditions = @(
            "spread/liquidity proxy deteriorates beyond guard",
            "4h context flips below range midpoint",
            "data gap or stale candle detected",
            "base delisted/unavailable on either required venue"
        )
    }
    validation_contract = [ordered]@{
        no_grid = $true
        parameter_changes_require_new_plan = $true
        chronological_split = "70/30 train/OOS by time"
        walk_forward = "rolling folds, no random shuffle"
        min_independent_events = 100
        min_bases = 8
        max_single_base_net_pnl_share = 0.25
        pass_conditions = @(
            "train and OOS net expectancy after costs > 0",
            "OOS profit_factor >= 1.2",
            "walk-forward positive folds >= 60%",
            "stress 2x slippage and delayed entry remains non-negative",
            "no single base dominates net PnL",
            "winrate is reported but cannot override negative expectancy"
        )
    }
    blocked_moves = @(
        "grid_search",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward",
        "15m_signal_until_clean_15m_gate_passes",
        "parameter_tuning_after_seeing_oos",
        "claiming_edge_from_in_sample_only"
    )
    next_valid_moves = @(
        "Build feature normalizer PlanOnly for this fixed contract on clean 1h/4h two-venue slice.",
        "Then run a single fixed-signal replay-validation PlanOnly, no grid.",
        "If event count or OOS/stress fails, reject or rescope before any new collect."
    )
    output_path = $OutputPath
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Fixed slow-liquidity v0 signal contract created on clean 1h/4h slice; clean_bases=$($cleanBases.Count); 15m_disabled=$disabled15m; no replay/grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Build slow-liquidity feature normalizer PlanOnly for fixed v0 signal on clean 1h/4h two-venue slice. Do not run grid/live/API/paper-forward; replay only after normalizer artifact exists and remains fixed-parameter."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value "Build slow-liquidity feature normalizer PlanOnly for fixed v0 signal on clean 1h/4h two-venue slice. Do not run grid/live/API/paper-forward; replay only after normalizer artifact exists and remains fixed-parameter."
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_signal_plan_at" -Value $result.generated_at
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_signal_plan_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_fixed_signal_plan_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = "fixed_signal_planonly_ready_for_feature_normalizer"
        decision_source = $OutputPath
        selected_at = $result.generated_at
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        clean_bases = $cleanBases.Count
        disabled_15m = $disabled15m
        next_step_required = "build_slow_liquidity_feature_normalizer_planonly"
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
