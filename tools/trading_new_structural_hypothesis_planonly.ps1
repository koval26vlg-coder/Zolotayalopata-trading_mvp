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
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\new_structural_hypothesis_planonly_$timestamp.json"
}

function Read-JsonFileOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
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
    $Payload | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Json) {
        $Payload | ConvertTo-Json -Depth 16
        return
    }
    Write-Host "New Structural Hypothesis PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Selected branch: $($Payload.selected_branch)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_new_structural_hypothesis_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = $null
        would_start = $false
        research_only = $true
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        reason = "Active run gate is $($gate.status); only gate-compliant status/resume work is allowed."
        output_path = $OutputPath
    }
    Save-Result -Payload $blocked
    exit 0
}

$rawGate = Read-JsonFileOrNull -Path $gatePath
$now = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
$selectedBranch = "forward_pit_universe_event_liquidity_anomaly"

$hypotheses = @(
    [ordered]@{
        branch = $selectedBranch
        rank = 1
        status = "selected_planonly"
        thesis = "Build a forward-only point-in-time universe and trade only large liquidity/event anomalies that are observable after the snapshot, avoiding current-top-volume survivorship and sub-fee microstructure noise."
        why_now = @(
            "The rejected branches failed mainly on base-cost economics, coverage, OOS/robustness, or survivorship controls.",
            "A forward PIT universe converts the project from retrospective cherry-picking to live-observable research evidence.",
            "Large liquidity/event anomalies can target moves measured in hundreds of bps, which is the correct scale for base/VIP0 fees."
        )
        first_implementation = "Design and then implement a short public preflight for daily venue snapshots: active contracts, status, quote volume, spread proxy, Binance-spot exclusion, first_seen/last_seen, inactive/delisted/no-data flags. No actual long collect until visible approval."
        data_requirements = @(
            "Daily public contract/ticker snapshots for MEXC, Gate and optional third venue.",
            "Point-in-time fields: asof_ts, first_seen_ts, last_seen_ts, status, listed_now, inactive_or_delisted, source_endpoint.",
            "Daily OHLCV/funding only for symbols already present in prior snapshots; no retroactive inclusion by future volume.",
            "Negative outcomes retained: no data, inactive, delisted, frozen, too wide spread, too low depth."
        )
        signal_family = @(
            "liquidity_shock_retest: enter only after volume/liquidity expands materially and spread compresses, then wait for retest rather than chase first spike.",
            "post_listing_maturation: ignore first chaotic window; evaluate 24h-7d post-listing drift/reversal only when liquidity gates pass.",
            "cross_venue_confirmation_filter: require independent venue confirmation when available; single-venue evidence stays weaker."
        )
        acceptance_gates = @(
            "point_in_time_universe_pass: every trade candidate must be known before the decision timestamp.",
            "negative_outcomes_pass: inactive/delisted/no-data symbols remain in denominator.",
            "sample_size: >= 100 independent events after cooldown.",
            "economics: net expectancy after base/VIP0 fees, spread, slippage, stale-data and partial-fill buffers > 0.",
            "OOS: holdout net PnL > 0 and profit factor >= 1.2.",
            "walk_forward: >= 60% positive folds with positive median net expectancy.",
            "stress: non-negative under 2x slippage, +50% fee buffer, missed entry and delist/freeze/no-exit haircut.",
            "risk: max drawdown <= 25%, no single base > 25% of positive contribution."
        )
        rejection_gates = @(
            "cannot_build_point_in_time_universe",
            "negative_outcomes_missing",
            "event_move_below_base_cost_hurdle",
            "too_few_independent_events",
            "holdout_or_walk_forward_failure",
            "stress_failure",
            "requires_live_api_keys_margin_or_fast_execution_to_prove"
        )
    },
    [ordered]@{
        branch = "daily_momentum_with_external_pit_universe"
        rank = 2
        status = "blocked_until_pit_source"
        thesis = "Revisit daily cross-sectional momentum only if a real point-in-time/delisted universe source is added."
        blocker = "Current local dataset is current-top-volume and rejected for acceptance."
    },
    [ordered]@{
        branch = "pure_market_making_or_hft_scalping"
        rank = 3
        status = "rejected_by_design_for_base_tier_public_api"
        thesis = "Avoid public-API HFT/micro targets under base/VIP0 fees."
        blocker = "Expected edge per trade is below fee/spread/latency hurdle."
    }
)

$result = [ordered]@{
    generated_at = $now
    mode = "trading_new_structural_hypothesis_planonly"
    decision = "NEW_STRUCTURAL_HYPOTHESIS_PLANONLY_SELECTED"
    selected_branch = $selectedBranch
    would_start = $false
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    reason = "All existing structural branches are rejected or blocked on current evidence. The next valid work is a new data-first PlanOnly branch that fixes survivorship before trying to prove edge."
    prior_gate = [ordered]@{
        status = $gate.status
        next_goal_decision = $gate.next_goal_decision
        replay_allowed = $gate.replay_allowed
        strategy_branch_status = if ($rawGate) { $rawGate.strategy_branch_status } else { $null }
    }
    hypotheses = $hypotheses
    selected_branch_plan = $hypotheses[0]
    next_valid_moves = @(
        "Implement a PlanOnly point-in-time universe snapshot preflight; do not start a long collect.",
        "If preflight confirms feasible public fields, prepare a visible snapshot collector approval packet.",
        "Only after PIT snapshots exist, define event labels and run OOS/walk-forward/stress/economics gates.",
        "Keep live orders, API keys, leverage, margin, grid search and paper-forward blocked."
    )
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "grid_search",
        "paper_forward",
        "hidden_background_collect",
        "reselect_rejected_branch_without_new_data"
    )
    commands = [ordered]@{
        rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
        next_goal_step = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\tools\trading_next_goal_step.ps1`" -Json"
    }
    output_path = $OutputPath
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value "NEW_STRUCTURAL_HYPOTHESIS_PLANONLY_SELECTED"
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Existing structural backlog is exhausted; selected forward PIT universe event/liquidity anomaly as the next research-only PlanOnly branch."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value "Implement point-in-time universe snapshot preflight PlanOnly. Do not start collect/grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value "Implement point-in-time universe snapshot preflight PlanOnly. Do not start collect/grid/live/API/paper-forward."
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = $selectedBranch
        verdict = "planonly_selected_not_tested"
        decision_source = $OutputPath
        selected_at = $now
        previous_branch = "structural_backlog"
        previous_verdict = "exhausted_or_blocked_on_current_evidence"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_step_required = "build_pit_universe_snapshot_preflight_planonly"
    })
    Set-JsonProperty -Object $gateDoc -Name "last_new_structural_hypothesis_planonly_at" -Value $now
    Set-JsonProperty -Object $gateDoc -Name "last_new_structural_hypothesis_planonly_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_new_structural_hypothesis_planonly_decision" -Value $result.decision
    Set-JsonProperty -Object $gateDoc -Name "last_new_structural_hypothesis_selected_branch" -Value $selectedBranch
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
