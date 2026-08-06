param(
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$fundingPlanPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_basis_planonly_20260708_163823.json"
$feeConstraintPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_fee_tier_operational_constraint_current.json"
$marketFilterPath = Join-Path $repoRoot "exports\trading-mvp\backtests\ws_market_filter_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.json"
$normalizedPath = Join-Path $repoRoot "exports\trading-mvp\normalized\ws_market_filtered_ws_durable_72h_2exchange_pregap_market_filter_20260708_1050.jsonl"
$crossVenueFullOutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\cross_venue_dislocation_full_ws_durable_72h_2exchange_pregap_20260708.json"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"
$pitUniverseVisibleCollectScript = Join-Path $repoRoot "tools\start_pit_universe_snapshot_collect_visible.ps1"
$pitCrossVenueScreenVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_screen_visible.ps1"
$pitCrossVenueForwardOosVisibleScript = Join-Path $repoRoot "tools\start_pit_cross_venue_forward_oos_visible.ps1"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\structural_branch_planonly_$timestamp.json"
}

function Invoke-JsonScript {
    param([string]$Path)

    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Script failed with exit code ${LASTEXITCODE}: $Path"
    }
    return ($raw | ConvertFrom-Json)
}

function Read-JsonFileOrNull {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
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
    $Payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 12
        return
    }

    Write-Host "Structural Branch PlanOnly" -ForegroundColor Cyan
    Write-Host "Generated: $($Payload.generated_at)"
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Selected branch: $($Payload.selected_branch)"
    Write-Host "Output: $OutputPath"
    Write-Host ""
    Write-Host "Why this branch" -ForegroundColor Yellow
    foreach ($reason in @($Payload.selected_branch_plan.selection_rationale)) {
        Write-Host "  - $reason"
    }
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
        mode = "trading_structural_branch_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = $null
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
            "If STOPPED_INCOMPLETE, visibly resume or explicitly reject the dataset before branch selection.",
            "Do not select a new branch, collect, replay, grid, paper-forward, live order, or API-key workflow while the gate is blocked."
        )
    }
    Save-Result -Payload $blocked
    exit 0
}

$rawGate = Read-JsonFileOrNull -Path $gatePath
$gateHistory = if ($rawGate) { $rawGate } else { $gate }
$forwardOosApprovalReady = [string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_APPROVAL_PACKET_READY_AWAITING_EXPLICIT_CONFIRMATION"
if ($forwardOosApprovalReady) {
    $startCommand = if ($gate.command_after_explicit_approval) {
        [string]$gate.command_after_explicit_approval
    } else {
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueForwardOosVisibleScript`" -PlanPath `"$($rawGate.forward_oos_plan_path)`" -ConfirmedForwardOosCollect"
    }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_structural_branch_planonly"
        decision = "PIT_LINEAR_PERP_FORWARD_OOS_COLLECT_AWAITING_EXPLICIT_VISIBLE_CONFIRMATION"
        selected_branch = "pit_linear_perp_cross_venue_forward_oos"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        research_only = $true
        reason = "Do not reselect or tune rejected branches. The current branch has a sealed forward-OOS packet and is waiting only for explicit visible-collect confirmation."
        selected_branch_plan = [ordered]@{
            branch = "pit_linear_perp_cross_venue_forward_oos"
            source_contract_type = "linear_perp"
            supports_spot_objective = $false
            plan_path = if ($rawGate) { $rawGate.forward_oos_plan_path } else { $null }
            plan_sha256 = if ($rawGate) { $rawGate.forward_oos_plan_sha256 } else { $null }
            selection_rationale = @(
                "The old spot full scan remains rejected after base costs.",
                "The corrected one-shot perp probe found at least one stress-cost-positive observation but does not prove persistence.",
                "A chronological forward dataset is required before replay, OOS claims or paper-forward."
            )
        }
        next_valid_moves = @(
            "Await explicit confirmation for the visible immutable-segment forward-OOS collect.",
            "After a quality-complete final manifest, run data-quality before any evaluation.",
            "Keep replay, grid, paper-forward and live blocked."
        )
        blocked_moves = @("automatic_collect_start", "branch_reselection", "replay", "grid_search", "paper_forward", "live_orders", "api_keys")
        commands = [ordered]@{
            command_after_explicit_approval = $startCommand
            active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        output_path = $OutputPath
    }
    Save-Result -Payload $result
    exit 0
}
$pitLinearPerpScreenReady = [string]$gate.next_goal_decision -eq "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"
if ($pitLinearPerpScreenReady) {
    $screenCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueScreenVisibleScript`" -ConfirmedResearchScreen -Json"
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_structural_branch_planonly"
        decision = "PIT_LINEAR_PERP_CROSS_VENUE_SCREEN_PLANONLY_READY"
        selected_branch = "pit_linear_perp_cross_venue_screening"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        screening_allowed_now = $true
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        research_only = $true
        reason = "Do not reselect the rejected spot branch. The current PIT source is linear_perp and permits only a visible streaming screening report over the immutable mask."
        selected_branch_plan = [ordered]@{
            branch = "pit_linear_perp_cross_venue_screening"
            source_contract_type = "linear_perp"
            supports_spot_objective = $false
            selection_rationale = @(
                "The prior spot full scan is rejected after the fixed base-cost hurdle.",
                "The PIT clean-slice source is derivatives-only and must be labelled separately.",
                "Streaming mask application avoids filtered JSONL materialization."
            )
        }
        next_valid_moves = @(
            "Run the visible streaming screen with fixed 69 bps cost hurdle.",
            "If candidates exist, require contract/depth/funding and OOS evidence before replay.",
            "If no candidates survive costs, reject this screening branch."
        )
        blocked_moves = @(
            "interpret_as_spot_scan",
            "materialize_filtered_jsonl",
            "new_collect",
            "replay",
            "backtest",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys"
        )
        commands = [ordered]@{
            visible_screen = $screenCommand
            visible_screen_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$pitCrossVenueScreenVisibleScript`" -PlanOnly -Json"
            active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        output_path = $OutputPath
    }
    Save-Result -Payload $result
    exit 0
}
$pitUniverseAlreadySelected = (
    ([string]$gate.next_goal_decision -eq "START_NEW_VISIBLE_PIT_UNIVERSE_SNAPSHOT_COLLECT_AFTER_FIX_APPROVAL") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "forward_pit_universe_event_liquidity_anomaly" -and
        [string]$gate.strategy_branch_status.verdict -eq "control_plane_fixed_ready_for_new_clean_collect_approval"
    )
)
if ($pitUniverseAlreadySelected) {
    $pitPlanCommand = "pwsh -NoProfile -ExecutionPolicy Bypass -File $pitUniverseVisibleCollectScript -Hours 24 -IntervalSec 300 -TimeoutSec 10 -MinContractsPerExchange 50 -OutputRoot E:\trading_mvp\pit-universe-snapshots -PlanOnly -Json"
    $selected = [ordered]@{
        branch = "forward_pit_universe_event_liquidity_anomaly"
        selection_rationale = @(
            "This branch is already selected by the authoritative current-run gate.",
            "The prior pre-v2 dataset is rejected; only a new clean PIT v2 collect can advance evidence."
        )
    }
    $result = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_structural_branch_planonly"
        decision = "PIT_UNIVERSE_BRANCH_ALREADY_SELECTED_AWAITING_NEW_CLEAN_COLLECT_APPROVAL"
        selected_branch = "forward_pit_universe_event_liquidity_anomaly"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        research_only = $true
        reason = "Do not select another structural branch while the current PIT data-only branch awaits a clean v2 collect decision."
        selected_branch_plan = $selected
        next_valid_moves = @(
            "Show the PIT v2 collect PlanOnly preview.",
            "Start only after explicit user approval in a visible terminal.",
            "Keep replay/grid/paper/live/API keys blocked until data-quality passes."
        )
        blocked_moves = @(
            "select_another_branch",
            "resume_old_pre_v2_pit_run",
            "actual_collect_without_explicit_confirmation",
            "replay",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys"
        )
        commands = [ordered]@{
            pit_universe_visible_collect_planonly = $pitPlanCommand
            active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`" -Json"
        }
        output_path = $OutputPath
    }
    Save-Result -Payload $result
    exit 0
}

$fundingPlan = Read-JsonFileOrNull -Path $fundingPlanPath
$feeConstraint = Read-JsonFileOrNull -Path $feeConstraintPath
$marketFilter = Read-JsonFileOrNull -Path $marketFilterPath
$crossVenueFullResult = Read-JsonFileOrNull -Path $crossVenueFullOutputPath
if (-not $crossVenueFullResult -and $gateHistory.PSObject.Properties.Name -contains "last_cross_venue_dislocation_full_output_path") {
    $crossVenueFullResult = Read-JsonFileOrNull -Path ([string]$gateHistory.last_cross_venue_dislocation_full_output_path)
}

$listingEventReplayResult = $null
if ($gateHistory.PSObject.Properties.Name -contains "last_listing_event_replay_output_path") {
    $listingEventReplayResult = Read-JsonFileOrNull -Path ([string]$gateHistory.last_listing_event_replay_output_path)
}
if (-not $listingEventReplayResult -and (Test-Path -LiteralPath $backtestDir)) {
    $latestListingReplay = Get-ChildItem -LiteralPath $backtestDir -Filter "listing_event_replay_planonly_*.json" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestListingReplay) {
        $listingEventReplayResult = Read-JsonFileOrNull -Path $latestListingReplay.FullName
    }
}
$listingEventReplayRejected = [bool](
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_REPLAY_PLANONLY_REJECTED*") -or
    ([string]$gateHistory.last_listing_event_replay_decision -like "LISTING_EVENT_REPLAY_PLANONLY_REJECTED*") -or
    (
        $listingEventReplayResult -and
        [string]$listingEventReplayResult.decision -like "LISTING_EVENT_REPLAY_PLANONLY_REJECTED*"
    ) -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "listing_event_drift_reversal" -and
        [string]$gate.strategy_branch_status.verdict -eq "replay_planonly_rejected"
    )
)

$baseFeeConstraintAccepted = [bool](
    $feeConstraint -and
    [string]$feeConstraint.mode -eq "funding_fee_tier_operational_constraint" -and
    [bool]$feeConstraint.accepted_as_operational_constraint -and
    -not [bool]$feeConstraint.lower_cost_scenarios_allowed_for_acceptance
)

$fundingRejectedBaseFees = [bool](
    ([string]$gate.next_goal_decision -eq "SELECT_NEXT_NON_HFT_STRUCTURAL_BRANCH_PLANONLY") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "funding_basis_carry_structural_planonly" -and
        [string]$gate.strategy_branch_status.verdict -eq "rejected_base_fees"
    ) -or
    (
        $fundingPlan -and
        [string]$fundingPlan.decision -eq "FUNDING_BASIS_PLANONLY_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH"
    )
)

$crossVenueBranch = "cross_venue_spot_dislocation_inventory_rebalance"
$listingEventBranch = "listing_event_drift_reversal"
$basisBranch = "spot_perp_basis_mean_reversion_no_funding"
$slowLiquidityBranch = "slow_liquidity_regime_breakout_retest"
$dailyMomentumBranch = "cross_sectional_momentum_daily"
$spotPerpRejectedVerdicts = @(
    "availability_preflight_rejected",
    "public_probe_rejected",
    "public_probe_rejected_rescope",
    "rejected_rescope"
)
$crossVenueRejected = [bool](
    ([string]$gate.next_goal_decision -eq "CROSS_VENUE_DISLOCATION_FULL_SCAN_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH") -or
    (
        $crossVenueFullResult -and
        [string]$crossVenueFullResult.decision -eq "REJECTED_NO_NET_EDGE_AFTER_BASE_FEES"
    ) -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY*") -or
    ([string]$gate.next_goal_decision -like "LISTING_EVENT_CALENDAR*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq $crossVenueBranch -and
        [string]$gate.strategy_branch_status.verdict -in @("rejected_base_fees", "rejected_full_scan_base_fees", "rejected_no_net_edge_after_base_fees")
    ) -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq $listingEventBranch -and
        [string]$gate.strategy_branch_status.verdict -in @("planonly_selected_not_tested", "planonly_needs_event_calendar", "planonly_ready_for_event_normalizer", "calendar_partial_needs_delisted_or_nontradable_coverage", "calendar_bias_control_pass_ready_for_normalizer")
    )
)
$spotPerpBasisRejected = [bool](
    ([string]$gate.next_goal_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") -or
    ([string]$gate.next_goal_decision -like "SPOT_PERP_BASIS_AVAILABILITY_PREFLIGHT_REJECTED*") -or
    ([string]$gateHistory.last_spot_perp_basis_public_probe_decision -eq "SPOT_PERP_BASIS_PUBLIC_PROBE_REJECTED_RESCOPE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq $basisBranch -and
        [string]$gate.strategy_branch_status.verdict -in $spotPerpRejectedVerdicts
    )
)
$slowLiquidityRejected = [bool](
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE") -or
    ([string]$gateHistory.last_slow_liquidity_replay_v1_decision -eq "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq $slowLiquidityBranch -and
        [string]$gate.strategy_branch_status.previous_branch -eq $basisBranch -and
        [string]$gateHistory.last_slow_liquidity_replay_v1_decision -eq "SLOW_LIQUIDITY_FIXED_V1_REPLAY_PLANONLY_REJECTED_NO_ROBUST_EDGE"
    )
)
$dailyMomentumRejected = [bool](
    ([string]$gate.next_goal_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_INCONCLUSIVE_REJECTED_FOR_ACCEPTANCE_CURRENT_DATASET") -or
    ([string]$gateHistory.last_daily_momentum_survivorship_resolution_decision -eq "DAILY_CROSS_SECTIONAL_MOMENTUM_INCONCLUSIVE_REJECTED_FOR_ACCEPTANCE_CURRENT_DATASET") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq $dailyMomentumBranch -and
        [string]$gate.strategy_branch_status.verdict -in @("survivorship_audit_revise_required", "inconclusive_rejected_for_acceptance_current_dataset")
    )
)
$candidates = @(
    [ordered]@{
        branch = $crossVenueBranch
        rank = 1
        score = 86
        verdict = "selected_for_next_planonly"
        thesis = "Detect persistent MEXC/Gate spot mid-price dislocations on non-Binance pairs, simulate inventory-neutral buy-low/sell-high execution with explicit base-fee, spread, slippage and rebalance buffers."
        why_now = @(
            "Uses the already collected two-exchange MEXC/Gate WS dataset instead of starting a new long run.",
            "Targets wider structural dislocations in thin non-Binance markets, not sub-10bps HFT noise.",
            "Can be hard-rejected quickly if the net spread after base fees and stress buffers is not large enough."
        )
        cost_hurdle_bps = "Primary screen: gross cross-venue edge must exceed two-sided base spot fees plus both venue spreads, slippage, stale-quote and rebalance buffers; default research hurdle >= 80-150 bps before any acceptance discussion."
        data_requirements = @(
            "Matched MEXC/Gate spot symbols by base/quote from the non-Binance universe.",
            "Synchronized best bid/ask or mid snapshots from the clean 72h market-filtered slice.",
            "Per-exchange spread, top-of-book depth, quote staleness and update density.",
            "Base-fee assumption file and explicit no-VIP/no-volume constraint.",
            "Inventory/rebalance accounting assumptions; no margin shorting or live transfer assumptions in acceptance."
        )
        acceptance_gates = @(
            "sample_size: >= 100 independent dislocation events after de-duplication and cooldown.",
            "market_diversity: >= 10 bases and no single base contributes > 25% of net PnL.",
            "economics: net expectancy after base fees/spread/slippage/rebalance buffer > 0.",
            "oos: train/test split profit factor >= 1.2 and net PnL > 0 in holdout.",
            "walk_forward: >= 60% positive folds with positive median net expectancy.",
            "stress: remains non-negative under 2x slippage, +50% fee buffer, stale quote rejection and partial-fill haircut.",
            "risk: max drawdown and inventory imbalance stay inside fixed paper limits."
        )
        rejection_gates = @(
            "gross_edge_below_cost_hurdle",
            "too_few_independent_events",
            "single_market_cherry_picking",
            "holdout_net_pnl_negative",
            "stress_slippage_or_stale_quote_failure",
            "requires_live_transfer_or_margin_to_work"
        )
        blocked_live_assumptions = @(
            "No live orders.",
            "No API keys.",
            "No leverage, margin, short-selling, or withdrawal automation.",
            "No claim of arbitrage profitability until inventory, withdrawal, freeze/delist and venue-risk costs are modeled."
        )
    },
    [ordered]@{
        branch = $listingEventBranch
        rank = 2
        score = 79
        verdict = "secondary_candidate"
        thesis = "Research new-listing and post-spike drift/reversal on non-Binance markets where moves can be large enough to survive base fees."
        why_now = @(
            "cross_venue_spot_dislocation_inventory_rebalance full scan found no eligible net-positive events after base fees and buffers.",
            "Listing/post-spike regimes can produce moves measured in tens to hundreds of bps, which is the right scale for base/VIP0 fees.",
            "The first step is PlanOnly: define event data, survivorship controls and validation gates before any new collection."
        )
        why_not_first = @(
            "Needs a reliable historical listing calendar and delisting/survivorship controls before testing.",
            "Higher risk of biased data if only surviving or memorable listings are sampled.",
            "May require new historical data before any proof."
        )
        cost_hurdle_bps = "Expected post-cost move should be measured in tens to hundreds of bps, not 3-10 bps."
        data_requirements = @(
            "Timestamped listing calendar by venue.",
            "1m/5m OHLCV and spread/liquidity snapshots around listing windows.",
            "Delisting and no-trade outcomes to prevent survivorship bias."
        )
        acceptance_gates = @(
            ">= 100 listing events across multiple months.",
            "Walk-forward by listing date.",
            "Stress for missed entry, wide spread and delist/freeze events."
        )
        rejection_gates = @(
            "event_calendar_missing_or_biased",
            "too_few_listing_events",
            "survivorship_bias_not_controlled",
            "holdout_net_pnl_negative_after_base_fees",
            "stress_missed_entry_wide_spread_or_freeze_failure"
        )
        blocked_live_assumptions = @(
            "No live orders.",
            "No API keys.",
            "No leverage, margin, short-selling, or withdrawal automation.",
            "No claim of listing-edge profitability until delist/freeze/survivorship and venue-risk costs are modeled."
        )
    },
    [ordered]@{
        branch = $basisBranch
        rank = 3
        score = 68
        verdict = "watch_candidate"
        thesis = "Mean-revert extreme spot/perp basis without relying on funding payout; use funding only as risk regime, not as PnL source."
        why_not_first = @(
            "Still fee- and execution-sensitive under base/VIP0 costs.",
            "Needs paired spot/perp liquidity and hedge feasibility.",
            "Can accidentally become funding carry again unless PnL attribution is strict."
        )
        cost_hurdle_bps = "Basis excursion must exceed round-trip spot+perp fees plus slippage and adverse-basis buffer."
        data_requirements = @(
            "Spot mid and perp mark/index by matched base.",
            "Spread/depth for both legs.",
            "Funding regime as a blocking filter only."
        )
        acceptance_gates = @(
            "sample_size: >= 100 independent basis excursions after cooldown and de-duplication.",
            "market_diversity: >= 10 bases and no single base contributes > 25% of net PnL.",
            "economics: net expectancy after base fees, spread, slippage and adverse-basis buffer > 0.",
            "oos: holdout net PnL > 0 and profit factor >= 1.2.",
            "walk_forward: >= 60% positive folds with positive median net expectancy.",
            "stress: remains non-negative under 2x slippage, +50% fee buffer and partial-fill haircut."
        )
        rejection_gates = @(
            "basis_excursion_below_cost_hurdle",
            "too_few_independent_events",
            "single_market_cherry_picking",
            "holdout_net_pnl_negative",
            "stress_slippage_or_partial_fill_failure",
            "requires_live_margin_or_shorting_to_work"
        )
        blocked_live_assumptions = @(
            "No live orders.",
            "No API keys.",
            "No leverage, margin, short-selling, or withdrawal automation.",
            "No claim of basis profitability until hedge feasibility, fills and venue-risk costs are modeled."
        )
    },
    [ordered]@{
        branch = $slowLiquidityBranch
        rank = 4
        score = 61
        verdict = "watch_candidate"
        thesis = "Avoid microstructure scalping; test slower 15m-4h liquidity regime shifts and retests with targets large enough for base fees."
        why_not_first = @(
            "Prior taker breakout and microstructure branches already failed cost/OOS gates.",
            "Likely lower win rate; must be judged by expectancy and drawdown, not hit-rate alone.",
            "Needs longer multi-week data for credible OOS."
        )
        cost_hurdle_bps = "Target/stop structure must clear base fees by a wide margin; no 3-6bps targets."
        data_requirements = @(
            "Multi-week OHLCV plus spread snapshots.",
            "Market regime labels and volume/liquidity filters.",
            "Train/OOS/walk-forward/stress gates."
        )
        acceptance_gates = @(
            "sample_size: >= 200 independent regime/retest events after cooldown and de-duplication.",
            "economics: target/stop distances clear base/VIP0 fees, spread, slippage and missed-fill buffers.",
            "market_diversity: >= 10 bases and no single base contributes > 25% of net PnL.",
            "oos: holdout net PnL > 0 and profit factor >= 1.2.",
            "walk_forward: >= 60% positive folds with positive median net expectancy.",
            "stress: remains non-negative under 2x slippage, +50% fee buffer, delayed entry and partial-fill haircut."
        )
        rejection_gates = @(
            "move_size_below_cost_hurdle",
            "too_few_independent_regime_events",
            "single_market_cherry_picking",
            "holdout_net_pnl_negative",
            "stress_slippage_or_delayed_entry_failure",
            "requires_unavailable_low_fee_or_hft_execution_to_work"
        )
        blocked_live_assumptions = @(
            "No live orders.",
            "No API keys.",
            "No leverage, margin, short-selling, or withdrawal automation.",
            "No claim of regime-edge profitability until OOS/walk-forward/stress and venue-risk costs are modeled."
        )
    },
    [ordered]@{
        branch = $dailyMomentumBranch
        rank = 5
        score = 57
        verdict = "fallback_candidate_after_structural_rejections"
        thesis = "Weekly cross-sectional perp momentum/reversal research on existing daily MEXC/Gate history; evaluate relative-strength continuation with funding drag and base/VIP0 costs."
        why_not_first = @(
            "Uses perpetual long/short research, so live use would require separate margin/leverage approval that remains blocked.",
            "Existing universe has survivorship bias from current top-volume contracts.",
            "Lower-frequency signal can be tested cheaply, but any positive result needs strict OOS/walk-forward/stress before paper-forward."
        )
        cost_hurdle_bps = "Weekly portfolio expectancy must remain positive after base/VIP0 perp fees, funding drag, slippage, liquidity filters and survivorship-bias disclosure."
        data_requirements = @(
            "Existing daily perp klines and funding history from MEXC/Gate.",
            "Non-Binance baseline tags and quote-volume liquidity filters.",
            "Train-only lookback selection, OOS split and walk-forward folds.",
            "Base/VIP0 fee assumptions plus stress slippage and adverse funding."
        )
        acceptance_gates = @(
            "sample_size: >= 20 independent weekly rebalances in OOS/walk-forward combined evidence.",
            "market_diversity: >= 30 eligible markets and no single base dominates portfolio contribution.",
            "economics: OOS weekly net expectancy after base fees, slippage and funding drag > 0.",
            "oos: holdout net return > 0 and profit factor >= 1.2 under base/VIP0 costs.",
            "walk_forward: >= 60% positive folds with positive median weekly net expectancy.",
            "stress: remains non-negative under 2x slippage, +50% fee buffer and adverse funding haircut.",
            "bias: survivorship and delisting limitations must be reported; positive result is candidate only, not accepted live edge."
        )
        rejection_gates = @(
            "too_few_rebalances",
            "oos_net_expectancy_non_positive",
            "walk_forward_or_stress_failure",
            "survivorship_bias_too_high_for_claim",
            "requires_live_margin_or_shorting_to_work"
        )
        blocked_live_assumptions = @(
            "No live orders.",
            "No API keys.",
            "No leverage, margin, short-selling, or withdrawal automation.",
            "No claim of daily momentum profitability until OOS/walk-forward/stress, funding drag and survivorship bias are accepted as research limits."
        )
    }
)

$basisRejectedAfterListingReplay = [bool]($listingEventReplayRejected -and $spotPerpBasisRejected)
$legacyStructuralBranchesExhausted = [bool]($crossVenueRejected -and $listingEventReplayRejected -and $spotPerpBasisRejected -and $slowLiquidityRejected)
$structuralBacklogExhausted = [bool]($legacyStructuralBranchesExhausted -and $dailyMomentumRejected)
$selectedBranch = if ($structuralBacklogExhausted) { $null } elseif ($legacyStructuralBranchesExhausted) { $dailyMomentumBranch } elseif ($basisRejectedAfterListingReplay) { $slowLiquidityBranch } elseif ($listingEventReplayRejected) { $basisBranch } elseif ($crossVenueRejected) { $listingEventBranch } else { $crossVenueBranch }
$selected = if ($selectedBranch) { $candidates | Where-Object { $_.branch -eq $selectedBranch } | Select-Object -First 1 } else { $null }
$decision = if ($structuralBacklogExhausted) {
    "STRUCTURAL_BRANCH_PLANONLY_BACKLOG_EXHAUSTED_REQUIRES_NEW_HYPOTHESIS_DESIGN"
} elseif ($legacyStructuralBranchesExhausted) {
    "DAILY_CROSS_SECTIONAL_MOMENTUM_PLANONLY_SELECTED"
} elseif ($basisRejectedAfterListingReplay) {
    "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_SELECTED"
} elseif ($listingEventReplayRejected) {
    "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_SELECTED"
} elseif ($crossVenueRejected) {
    "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_SELECTED"
} elseif ($fundingRejectedBaseFees) {
    "CROSS_VENUE_SPOT_DISLOCATION_PLANONLY_SELECTED"
} else {
    "STRUCTURAL_BRANCH_PLANONLY_SELECTED_WITH_INCOMPLETE_REJECTION_CONTEXT"
}
$previousBranch = if ($structuralBacklogExhausted) { $dailyMomentumBranch } elseif ($legacyStructuralBranchesExhausted) { $slowLiquidityBranch } elseif ($basisRejectedAfterListingReplay) { $basisBranch } elseif ($listingEventReplayRejected) { $listingEventBranch } elseif ($crossVenueRejected) { $crossVenueBranch } else { "funding_basis_carry_structural_planonly" }
$previousVerdict = if ($structuralBacklogExhausted) { "inconclusive_rejected_for_acceptance_current_dataset" } elseif ($legacyStructuralBranchesExhausted) { "replay_planonly_rejected_no_robust_edge" } elseif ($basisRejectedAfterListingReplay) { "public_probe_rejected" } elseif ($listingEventReplayRejected) { "replay_planonly_rejected" } elseif ($crossVenueRejected) { "rejected_no_net_edge_after_base_fees" } else { "rejected_base_fees" }
$selectionRationale = if ($structuralBacklogExhausted) {
    @(
        "cross_venue, listing_event, spot_perp_basis and slow_liquidity branches are already rejected or blocked on current evidence.",
        "cross_sectional_momentum_daily is also rejected for acceptance on the current dataset because local point-in-time/delisted universe coverage is missing.",
        "Do not reselect a rejected branch or tune a failed sample to manufacture win rate.",
        "The next work item is a new PlanOnly hypothesis design or a new bias-controlled data source proposal; no collect/grid/live/API/paper-forward."
    )
} elseif ($legacyStructuralBranchesExhausted) {
    @(
        "slow_liquidity fixed v1 replay is rejected on current evidence: negative net expectancy, OOS, walk-forward and stress gates failed.",
        "Do not reselect slow_liquidity or tune the rejected event family after replay.",
        "cross_sectional_momentum_daily is the next fallback branch that can use existing daily perp/funding history without a new long collector.",
        "The next step remains PlanOnly/research-only: define acceptance gates or run the existing daily backtest under base/VIP0 costs; no live/API/grid/paper-forward."
    )
} elseif ($basisRejectedAfterListingReplay) {
    @(
        "spot_perp_basis_mean_reversion_no_funding public probe is rejected on current evidence: 0 paired-ok bases reached the minimum coverage gate.",
        "Do not reselect spot/perp basis or start collect/replay/grid after a public-probe rejection.",
        "slow_liquidity_regime_breakout_retest is the remaining slower structural PlanOnly candidate; it must clear much larger base-fee hurdles than HFT-style signals.",
        "The next step remains PlanOnly: define regime labels, data requirements and rejection gates before any collect/backtest."
    )
} elseif ($listingEventReplayRejected) {
    @(
        "listing_event_drift_reversal fixed replay PlanOnly is rejected on current evidence: net expectancy, stress and walk-forward did not pass.",
        "Do not grid-tune or recollect the same listing-event sample to manufacture a win rate.",
        "spot_perp_basis_mean_reversion_no_funding is the next slower structural branch to test with strict base-fee and hedge-feasibility gates.",
        "The next step remains PlanOnly: define paired spot/perp data requirements and rejection gates before any collect/backtest."
    )
} elseif ($crossVenueRejected) {
    @(
        "The completed cross-venue full scan produced 0 eligible events and max net edge below zero after base fees and buffers.",
        "Do not grid-tune a rejected branch on the same dataset.",
        "listing_event_drift_reversal is the next non-HFT structural branch whose target moves can plausibly clear base/VIP0 costs.",
        "The next step remains PlanOnly: define data requirements, survivorship controls and validation gates before any collect/backtest."
    )
} else {
    @(
        "It reuses the current two-exchange MEXC/Gate data instead of spending another long run first.",
        "It targets structural venue fragmentation and wider bps dislocations that can survive base fees.",
        "It has a clean rejection path: if net dislocations do not clear fees, spread, slippage, stale-quote and inventory buffers, discard it.",
        "It does not require mixing funding into the signal and does not require HFT latency assumptions."
    )
}
$firstImplementation = if ($structuralBacklogExhausted) {
    "Create a new structural-hypothesis PlanOnly design packet: thesis, data source, survivorship controls, base-fee economics, OOS/walk-forward/stress gates, and explicit rejection criteria; no collect, grid, live orders or API keys."
} elseif ($legacyStructuralBranchesExhausted) {
    "Build a read-only cross_sectional_momentum_daily PlanOnly specification or run the existing research-only daily backtest on current daily history; no collector, grid, live orders or API keys."
} elseif ($basisRejectedAfterListingReplay) {
    "Build a read-only slow_liquidity_regime_breakout_retest PlanOnly specification: regime definitions, OHLCV/spread data requirements, cost hurdle, OOS/walk-forward/stress gates; no collector, grid, live orders or API keys."
} elseif ($listingEventReplayRejected) {
    "Build a read-only spot_perp_basis_mean_reversion_no_funding PlanOnly specification: paired spot/perp data requirements, hedge feasibility, cost hurdle, OOS/walk-forward/stress gates; no collector, grid, live orders or API keys."
} elseif ($crossVenueRejected) {
    "Build a read-only listing_event_drift_reversal PlanOnly specification and event-research scaffold: listing calendar requirements, survivorship controls, cost hurdle, OOS/walk-forward/stress gates; no collector, grid, live orders or API keys."
} else {
    "Build a read-only cross-venue dislocation detector/backtester PlanOnly against existing market-filtered 72h data; no collector, grid, live orders or API keys."
}
$expectedArtifacts = if ($structuralBacklogExhausted) {
    @(
        "exports/trading-mvp/analysis/new_structural_hypothesis_planonly_<timestamp>.json",
        "exports/trading-mvp/analysis/new_structural_hypothesis_data_requirements_<timestamp>.json",
        "docs/agent-log/<timestamp>-trading-mvp-new-hypothesis-design.md"
    )
} elseif ($legacyStructuralBranchesExhausted) {
    @(
        "exports/trading-mvp/analysis/cross_sectional_momentum_daily_planonly_<timestamp>.json",
        "exports/trading-mvp/backtests/momentum_daily_<timestamp>.json",
        "exports/trading-mvp/analysis/cross_sectional_momentum_daily_validation_<timestamp>.json"
    )
} elseif ($basisRejectedAfterListingReplay) {
    @(
        "exports/trading-mvp/analysis/slow_liquidity_regime_breakout_retest_planonly_<timestamp>.json",
        "exports/trading-mvp/analysis/slow_liquidity_regime_data_requirements_<timestamp>.json",
        "exports/trading-mvp/backtests/slow_liquidity_regime_validation_<timestamp>.json"
    )
} elseif ($listingEventReplayRejected) {
    @(
        "exports/trading-mvp/analysis/spot_perp_basis_mean_reversion_planonly_<timestamp>.json",
        "exports/trading-mvp/analysis/spot_perp_basis_availability_preflight_<timestamp>.json",
        "exports/trading-mvp/backtests/spot_perp_basis_mean_reversion_validation_<timestamp>.json"
    )
} elseif ($crossVenueRejected) {
    @(
        "exports/trading-mvp/analysis/listing_event_drift_reversal_planonly_<timestamp>.json",
        "exports/trading-mvp/analysis/listing_event_history_collect_preview_<timestamp>.json",
        "exports/trading-mvp/backtests/listing_event_replay_planonly_<timestamp>.json"
    )
} else {
    @(
        "exports/trading-mvp/analysis/cross_venue_dislocation_planonly_<timestamp>.json",
        "exports/trading-mvp/backtests/cross_venue_dislocation_events_<timestamp>.json",
        "exports/trading-mvp/backtests/cross_venue_dislocation_validation_<timestamp>.json"
    )
}
$resultReason = if ($structuralBacklogExhausted) { "The current structural backlog is exhausted on available evidence, including daily momentum rejected for acceptance due to missing point-in-time/delisted universe controls. Select no old branch; design a new PlanOnly hypothesis or source a bias-controlled universe before any collect/grid/live/API/paper-forward." } elseif ($legacyStructuralBranchesExhausted) { "slow_liquidity fixed v1 replay is rejected by robustness/economics gates after spot/perp, listing and cross-venue branches were already rejected or blocked. Select cross_sectional_momentum_daily as the next research-only fallback using existing daily perp/funding data; no collect/grid/live/API/paper-forward." } elseif ($basisRejectedAfterListingReplay) { "spot_perp_basis_mean_reversion_no_funding public probe is rejected under current public-data/coverage constraints. Select slow_liquidity_regime_breakout_retest as the next non-HFT structural PlanOnly branch; no collect/grid/replay/live/API/paper-forward." } elseif ($listingEventReplayRejected) { "listing_event_drift_reversal replay PlanOnly is rejected on current evidence. Select spot_perp_basis_mean_reversion_no_funding as the next non-HFT structural PlanOnly branch; no collect/grid/live/API/paper-forward." } elseif ($crossVenueRejected) { "Cross-venue spot dislocation is rejected by full scan under base fees/buffers. Select listing_event_drift_reversal as the next non-HFT structural PlanOnly branch; no collect/grid/live/API/paper-forward." } else { "Funding/basis carry is rejected under base/VIP0/no-volume fees. Select a non-HFT structural branch that can use existing dual-venue data and must clear base-fee economics before any new data collection." }
$nextValidMoves = @(
    $(if ($structuralBacklogExhausted) { "Design a new structural hypothesis PlanOnly packet instead of reselecting a rejected branch." } elseif ($legacyStructuralBranchesExhausted) { "Run cross_sectional_momentum_daily PlanOnly/backtest on existing daily history; do not start new data collection." } elseif ($basisRejectedAfterListingReplay) { "Build slow_liquidity_regime_breakout_retest PlanOnly research spec/scaffold; do not start data collection yet." } elseif ($listingEventReplayRejected) { "Build spot_perp_basis_mean_reversion_no_funding PlanOnly research spec/scaffold; do not start data collection yet." } elseif ($crossVenueRejected) { "Build listing_event_drift_reversal PlanOnly research spec/scaffold; do not start data collection yet." } else { "Implement the read-only cross-venue dislocation detector/backtester PlanOnly." }),
    $(if ($structuralBacklogExhausted) { "If daily momentum is revisited, source point-in-time/delisted universe data first; otherwise choose a new branch with an explicit anti-survivorship data plan." } elseif ($legacyStructuralBranchesExhausted) { "Use existing daily perp klines/funding files and enforce train-only lookback selection, OOS, walk-forward, stress and survivorship-bias caveats." } elseif ($basisRejectedAfterListingReplay) { "Define regime labels, minimum move size, OHLCV/spread/liquidity data requirements and base-fee cost hurdle." } elseif ($listingEventReplayRejected) { "Define paired spot/perp availability, spread/liquidity, hedge feasibility and base-fee data requirements." } elseif ($crossVenueRejected) { "Define listing-calendar, delisting/survivorship, spread/liquidity and base-fee data requirements." } else { "Use existing clean 72h MEXC/Gate market-filtered data first; do not start a new collector yet." }),
    "Apply base/VIP0/no-volume fee assumptions plus spread/slippage/stale-quote/rebalance buffers before any signal scoring.",
    "Run OOS, walk-forward, stress and economics gates before any paper-forward discussion.",
    $(if ($structuralBacklogExhausted) { "Keep paper-forward/live/API/grid blocked until a new branch passes data-quality, OOS, walk-forward, stress and economics gates." } elseif ($legacyStructuralBranchesExhausted) { "If daily momentum fails OOS/walk-forward/stress under base fees, mark the current structural backlog exhausted and require a new hypothesis rather than tuning rejected branches." } elseif ($basisRejectedAfterListingReplay) { "If slow_liquidity_regime_breakout_retest cannot pass PlanOnly cost/sample-size gates, reject it before any long run." } elseif ($listingEventReplayRejected) { "If spot_perp_basis_mean_reversion_no_funding cannot pass PlanOnly cost/hedge gates, reject it before any long run." } elseif ($crossVenueRejected) { "If listing_event_drift_reversal cannot pass PlanOnly data-bias/economics gates, reject it before any long run." } else { "If the branch fails cost/OOS/stress gates, reject it and move to listing_event_drift_reversal PlanOnly." })
)

$selectedBranchPlan = if ($structuralBacklogExhausted) {
    [ordered]@{
        branch = $null
        thesis = "No existing structural branch remains accepted for next-step execution on current evidence."
        selection_rationale = $selectionRationale
        first_implementation = $firstImplementation
        required_inputs = @(
            "New hypothesis thesis with expected edge measured well above base/VIP0 fees.",
            "Bias-controlled data source plan, including point-in-time universe or explicit negative/no-data outcomes.",
            "Cost model, liquidity/fill constraints and venue-risk assumptions before any backtest."
        )
        economics_policy = [ordered]@{
            optimize_for = "net_expectancy_after_costs"
            winrate_policy = "Win rate is supporting evidence only; reject high win-rate configs with negative expectancy or tail losses."
            base_fee_policy = "Use base/VIP0/no-volume fees and an explicit additional buffer; do not accept a lower-cost sensitivity row as proof."
            minimum_gross_hurdle = "Expected edge must be large enough to clear base fees, spread, slippage, stale data, partial fills and venue-risk buffers before testing."
        }
        validation_gates = @(
            "Data source has survivorship/delisting/no-data controls before acceptance.",
            "OOS holdout net PnL > 0 and profit factor >= 1.2 after base costs.",
            "Walk-forward >= 60% positive folds with positive median net expectancy.",
            "Stress remains non-negative under 2x slippage, +50% fee buffer and partial-fill/stale-data haircuts."
        )
        rejection_gates = @(
            "missing_bias_controlled_data_source",
            "move_size_below_cost_hurdle",
            "too_few_independent_events",
            "holdout_or_walk_forward_failure",
            "stress_failure",
            "requires_live_margin_or_api_keys_to_prove"
        )
        blocked_live_assumptions = @(
            "No live orders.",
            "No API keys.",
            "No leverage, margin, short-selling, or withdrawal automation.",
            "No paper-forward until a new branch passes the proof gates."
        )
        expected_artifacts = $expectedArtifacts
    }
} else {
    [ordered]@{
        branch = $selected.branch
        thesis = $selected.thesis
        selection_rationale = $selectionRationale
        first_implementation = $firstImplementation
        required_inputs = $selected.data_requirements
        economics_policy = [ordered]@{
            optimize_for = "net_expectancy_after_costs"
            winrate_policy = "Win rate is supporting evidence only; reject high win-rate configs with negative expectancy or tail losses."
            base_fee_policy = "Use base/VIP0/no-volume fees and an explicit additional buffer; do not accept a lower-cost sensitivity row as proof."
            minimum_gross_hurdle = $selected.cost_hurdle_bps
        }
        validation_gates = $selected.acceptance_gates
        rejection_gates = $selected.rejection_gates
        blocked_live_assumptions = $selected.blocked_live_assumptions
        expected_artifacts = $expectedArtifacts
    }
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_structural_branch_planonly"
    decision = $decision
    selected_branch = $selectedBranch
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    research_only = $true
    funding_rejected_base_fees = $fundingRejectedBaseFees
    base_fee_constraint_accepted = $baseFeeConstraintAccepted
    spot_perp_basis_rejected = $spotPerpBasisRejected
    slow_liquidity_rejected = $slowLiquidityRejected
    daily_momentum_rejected = $dailyMomentumRejected
    legacy_structural_branches_exhausted = $legacyStructuralBranchesExhausted
    structural_backlog_exhausted = $structuralBacklogExhausted
    reason = $resultReason
    branch_candidates = $candidates
    selected_branch_plan = $selectedBranchPlan
    current_artifacts = [ordered]@{
        gate = $gatePath
        funding_basis_planonly = $fundingPlanPath
        fee_constraint = $feeConstraintPath
        market_filter = $marketFilterPath
        normalized_market_filtered = $normalizedPath
        cross_venue_full_scan = $crossVenueFullOutputPath
    }
    existing_data_snapshot = [ordered]@{
        market_filter_exists = Test-Path -LiteralPath $marketFilterPath
        normalized_market_filtered_exists = Test-Path -LiteralPath $normalizedPath
        market_filter_replay_allowed = if ($marketFilter -and $marketFilter.PSObject.Properties.Name -contains "replay_allowed") { [bool]$marketFilter.replay_allowed } else { $null }
        market_filter_path = $marketFilterPath
        normalized_path = $normalizedPath
    }
    next_valid_moves = $nextValidMoves
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "grid_search",
        "paper_forward",
        "new_hidden_or_background_collect",
        "new_channel_or_p2p_content_analysis",
        "funding_fee_discount_rescue"
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
    $nextDecision = if ($structuralBacklogExhausted) { "STRUCTURAL_BRANCH_BACKLOG_EXHAUSTED_REQUIRES_NEW_HYPOTHESIS_PLANONLY" } elseif ($legacyStructuralBranchesExhausted) { "DAILY_CROSS_SECTIONAL_MOMENTUM_PLANONLY_RESEARCH" } elseif ($basisRejectedAfterListingReplay) { "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY_RESEARCH" } elseif ($listingEventReplayRejected) { "SPOT_PERP_BASIS_MEAN_REVERSION_PLANONLY_RESEARCH" } elseif ($crossVenueRejected) { "LISTING_EVENT_DRIFT_REVERSAL_PLANONLY_RESEARCH" } else { "IMPLEMENT_CROSS_VENUE_DISLOCATION_PLANONLY_RESEARCH" }
    $nextReason = if ($structuralBacklogExhausted) { "Current structural backlog is exhausted on available evidence, including daily momentum rejected for acceptance because point-in-time/delisted universe controls are missing. Next step is new hypothesis PlanOnly design; no collect/grid/live/API/paper-forward." } elseif ($legacyStructuralBranchesExhausted) { "slow_liquidity fixed v1 replay was rejected after spot/perp, listing and cross-venue branches were already rejected or blocked. Selected cross_sectional_momentum_daily as the next research-only fallback on existing daily perp/funding data; no collect/grid/live/API/paper-forward." } elseif ($basisRejectedAfterListingReplay) { "spot_perp_basis_mean_reversion_no_funding public probe was rejected under current coverage. Selected slow_liquidity_regime_breakout_retest as the next non-HFT structural PlanOnly branch; no collect/grid/replay/live/API/paper-forward." } elseif ($listingEventReplayRejected) { "listing_event_drift_reversal replay PlanOnly was rejected on current evidence. Selected spot_perp_basis_mean_reversion_no_funding as the next non-HFT structural PlanOnly branch; no collect/grid/live/API/paper-forward." } elseif ($crossVenueRejected) { "Cross-venue spot dislocation full scan was rejected under base fees/buffers. Selected listing_event_drift_reversal as the next non-HFT structural PlanOnly branch; no collect/grid/live/API/paper-forward." } else { "Selected cross-venue spot dislocation/inventory-rebalance as the next non-HFT structural branch after funding/basis rejection under base fees. Next step is a read-only PlanOnly detector/backtester on existing MEXC/Gate data; no collect/grid/live/API/paper-forward." }
    $nextStep = if ($structuralBacklogExhausted) { "Create a new structural-hypothesis PlanOnly design packet with thesis, bias-controlled data source, base-fee economics, OOS/walk-forward/stress gates and rejection criteria. Do not start collect/grid/live/API/paper-forward." } elseif ($legacyStructuralBranchesExhausted) { "Run or formalize cross_sectional_momentum_daily research-only validation on existing daily perp/funding history with train-only lookback selection, OOS, walk-forward, stress, base/VIP0 costs and survivorship-bias caveats. Do not start collect/grid/live/API/paper-forward." } elseif ($basisRejectedAfterListingReplay) { "Build slow_liquidity_regime_breakout_retest PlanOnly research spec/scaffold: regime labels, OHLCV/spread data requirements, cost hurdle and OOS/walk-forward/stress/economics gates. Do not start collect/grid/replay/live/API/paper-forward." } elseif ($listingEventReplayRejected) { "Build spot_perp_basis_mean_reversion_no_funding PlanOnly research spec/scaffold: paired spot/perp data requirements, hedge feasibility and OOS/walk-forward/stress/economics gates. Do not start collect/grid/live/API/paper-forward." } elseif ($crossVenueRejected) { "Build listing_event_drift_reversal PlanOnly research spec/scaffold: event calendar requirements, survivorship controls and OOS/walk-forward/stress/economics gates. Do not start collect/grid/live/API/paper-forward." } else { "Implement cross-venue spot dislocation PlanOnly detector/backtester using existing clean 72h MEXC/Gate data. Do not start new collect/grid/live/API/paper-forward." }
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $nextDecision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value $nextReason
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = $selectedBranch
        verdict = if ($structuralBacklogExhausted) { "backlog_exhausted_requires_new_hypothesis_design" } else { "planonly_selected_not_tested" }
        decision_source = $OutputPath
        selected_at = $result.generated_at
        previous_branch = $previousBranch
        previous_verdict = $previousVerdict
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_branch_required = $structuralBacklogExhausted
        next_step_required = if ($structuralBacklogExhausted) { "design_new_structural_hypothesis_planonly" } elseif ($legacyStructuralBranchesExhausted) { "run_cross_sectional_momentum_daily_research_only_validation" } elseif ($basisRejectedAfterListingReplay) { "build_slow_liquidity_regime_breakout_retest_planonly_research_scaffold" } elseif ($listingEventReplayRejected) { "build_spot_perp_basis_mean_reversion_planonly_research_scaffold" } elseif ($crossVenueRejected) { "build_listing_event_drift_reversal_planonly_research_scaffold" } else { "implement_read_only_cross_venue_dislocation_planonly_detector_backtester" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_structural_branch_planonly_at" -Value $result.generated_at
    Set-JsonProperty -Object $gateDoc -Name "last_structural_branch_planonly_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_structural_branch_planonly_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_structural_branch_planonly_selected_branch" -Value $selectedBranch
    $gateDoc | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
