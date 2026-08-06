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
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_regime_breakout_retest_planonly_$timestamp.json"
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

    Write-Host "Slow Liquidity Regime Breakout/Retest PlanOnly" -ForegroundColor Cyan
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
        mode = "trading_slow_liquidity_regime_breakout_retest_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "slow_liquidity_regime_breakout_retest"
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

$selectedGate = [bool](
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest"
    )
)
$spotPerpRejectedGate = [bool](
    ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") -or
    ([string]$gate.last_spot_perp_basis_public_probe_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "spot_perp_basis_mean_reversion_no_funding" -and
        [string]$gate.strategy_branch_status.verdict -in @("availability_preflight_rejected", "public_probe_rejected", "public_probe_rejected_rescope", "rejected_rescope")
    )
)

$roundTripFeeBps = 39.0
$entryExitSlippageBps = 40.0
$spreadBufferBps = 45.0
$missedFillBufferBps = 35.0
$adverseSelectionBufferBps = 55.0
$regimeFalseBreakBufferBps = 35.0
$minimumGrossMoveHurdleBps = $roundTripFeeBps + $entryExitSlippageBps + $spreadBufferBps + $missedFillBufferBps + $adverseSelectionBufferBps + $regimeFalseBreakBufferBps

$decision = "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_READY_FOR_DATA_AVAILABILITY_PREFLIGHT"

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_slow_liquidity_regime_breakout_retest_planonly"
    decision = $decision
    selected_branch = "slow_liquidity_regime_breakout_retest"
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    research_only = $true
    strategy_accepted = $false
    gate_status = $gate.status
    selected_gate = $selectedGate
    prior_rejection_context = [ordered]@{
        spot_perp_basis_rejected = $spotPerpRejectedGate
        last_spot_perp_basis_public_probe_output_path = [string]$gate.last_spot_perp_basis_public_probe_output_path
        last_spot_perp_basis_public_probe_decision = [string]$gate.last_spot_perp_basis_public_probe_decision
        reason = "spot/perp basis public probe did not meet paired coverage. Do not reselect it unless the branch is explicitly rescoped with new evidence."
    }
    thesis = "Research slower 15m-4h liquidity-regime breakouts and retests on non-Binance markets, targeting moves large enough to clear base/VIP0/no-volume fees and execution buffers. This is not HFT scalping."
    cost_hurdle = [ordered]@{
        policy = "base/VIP0/no-volume only; do not accept lower-cost sensitivity as proof"
        round_trip_fee_bps = $roundTripFeeBps
        entry_exit_slippage_bps = $entryExitSlippageBps
        spread_buffer_bps = $spreadBufferBps
        missed_fill_buffer_bps = $missedFillBufferBps
        adverse_selection_buffer_bps = $adverseSelectionBufferBps
        regime_false_break_buffer_bps = $regimeFalseBreakBufferBps
        minimum_gross_move_hurdle_bps = $minimumGrossMoveHurdleBps
        note = "Reject any setup whose target/stop geometry depends on 3-10 bps microstructure edge. The move must be materially larger than all base-fee and execution buffers."
    }
    signal_families = @(
        [ordered]@{
            name = "range_compression_breakout_retest"
            timeframe = @("15m", "1h", "4h")
            thesis = "After low-volatility compression, a liquidity expansion plus successful retest can create a slower continuation move."
            long_condition = "compression regime, volume expansion, close above range, retest holds above breakout level, spread/liquidity pass filters"
            short_condition = "disabled by default unless borrow/perp hedge rules are separately proven; spot-only v1 is long-only"
            invalidation = "failed retest, close back inside range, spread spike, liquidity collapse, stale market, adverse gap"
        },
        [ordered]@{
            name = "liquidity_expansion_retest"
            timeframe = @("15m", "1h")
            thesis = "A volume/liquidity expansion after thin-market accumulation can be tradable only if the retest confirms and cost hurdle is large enough."
            long_condition = "volume expansion percentile gate, top-liquidity improvement or conservative proxy, retest holds, ATR target clears cost hurdle"
            invalidation = "expansion fades, quote stales, spread widens, volume collapses"
        },
        [ordered]@{
            name = "false_break_reclaim"
            timeframe = @("15m", "1h")
            thesis = "A failed breakdown followed by reclaim can capture slower stop-run exhaustion, but must be OOS-proven and stress-tested."
            long_condition = "break below local range, fast reclaim, retest holds, volume confirms, spread/liquidity pass filters"
            invalidation = "reclaim failure, second breakdown, stop distance below cost hurdle"
        }
    )
    data_requirements = @(
        "Multi-week OHLCV at 15m, 1h and 4h for non-Binance universe symbols.",
        "Per-market spread snapshots or a conservative spread model derived from public top-of-book data.",
        "Volume/liquidity filters: minimum quote volume, quote update density if available, stale-market exclusion.",
        "Base/VIP0/no-volume fee model pinned to the current account assumption.",
        "Delist/freeze/no-trade flags retained as blocked outcomes.",
        "Chronological train/OOS split and walk-forward folds by time, not random rows.",
        "No Binance trading dependency; Binance only remains exclusion/universe context if already present."
    )
    feature_contract = [ordered]@{
        regime_labels = @("compression", "expansion", "trend_continuation", "failed_break_reclaim", "chop")
        required_features = @(
            "atr_bps",
            "range_width_bps",
            "range_duration_bars",
            "volume_percentile",
            "breakout_distance_bps",
            "retest_distance_bps",
            "spread_bps",
            "quote_volume",
            "cooldown_bars",
            "max_hold_bars"
        )
        execution_model = "spot-only paper/research model, no leverage, no margin, no API keys, conservative entry delay and slippage"
        default_direction = "long_only_until_short_or_perp_hedge_feasibility_is_proven"
    }
    validation_gates = @(
        "sample_size: >= 200 independent regime/retest events after cooldown and de-duplication.",
        "market_diversity: >= 10 bases and no single base contributes > 25% of net PnL.",
        "economics: aggregate and median net expectancy after base fees, spread, slippage, missed-fill and adverse-selection buffers > 0.",
        "oos: chronological holdout net PnL > 0 and profit factor >= 1.2.",
        "walk_forward: >= 60% positive folds with positive median net expectancy.",
        "stress: non-negative after 2x slippage, +50% fee buffer, delayed entry and partial-fill haircut.",
        "risk: max drawdown and tail loss remain inside fixed research limits.",
        "winrate_policy: high win rate is not sufficient; reject if expectancy, profit factor, OOS or stress fail."
    )
    rejection_gates = @(
        "move_size_below_cost_hurdle",
        "too_few_independent_regime_events",
        "single_market_cherry_picking",
        "holdout_net_pnl_negative",
        "walk_forward_positive_folds_below_threshold",
        "stress_slippage_or_delayed_entry_failure",
        "requires_unavailable_low_fee_or_hft_execution_to_work",
        "requires_leverage_margin_shorting_or_live_api_keys_to_show_edge"
    )
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "grid_search",
        "paper_forward",
        "new_hidden_or_background_collect",
        "replay_before_data_availability_preflight",
        "claiming_high_winrate_without_positive_net_expectancy_oos_walk_forward_stress",
        "resurrecting_rejected_spot_perp_basis_without_new_evidence"
    )
    next_valid_moves = @(
        "Build read-only slow-liquidity data availability preflight PlanOnly: inventory existing OHLCV/spread/liquidity coverage by market and timeframe.",
        "Define fixed v0 signal parameters before any replay; do not grid-search the branch before basic data sufficiency is proven.",
        "Keep base/VIP0/no-volume cost hurdle in every scoring artifact.",
        "If data availability is weak, reject or rescope before any long collect.",
        "If data availability is sufficient, prepare a visible collect/replay approval packet; actual collect still requires explicit user confirmation."
    )
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
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "slow_liquidity_regime_breakout_retest PlanOnly scaffold generated after spot/perp basis public-probe rejection. Research-only; no collect/grid/replay/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Build read-only slow-liquidity data availability preflight PlanOnly: existing OHLCV/spread/liquidity coverage by market/timeframe, cost hurdle, and fixed validation gates. Do not start collect/grid/replay/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value "Build read-only slow-liquidity data availability preflight PlanOnly: existing OHLCV/spread/liquidity coverage by market/timeframe, cost hurdle, and fixed validation gates. Do not start collect/grid/replay/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = "planonly_scaffold_ready_for_data_availability_preflight"
        decision_source = $OutputPath
        selected_at = $result.generated_at
        previous_branch = "spot_perp_basis_mean_reversion_no_funding"
        previous_verdict = "public_probe_rejected_rescope"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        next_branch_required = $false
        next_step_required = "build_slow_liquidity_data_availability_preflight_planonly"
    })
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_regime_planonly_at" -Value $result.generated_at
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_regime_planonly_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_regime_planonly_decision" -Value $decision
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
