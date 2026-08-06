param(
    [string]$OutputPath = "",
    [string]$FeeTierConstraintPath = "",
    [int]$TopN = 10,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$fundingCostAssumptionGateScript = Join-Path $repoRoot "tools\funding_cost_assumption_gate.ps1"
$fundingViabilityGapScript = Join-Path $repoRoot "tools\funding_viability_gap.ps1"
$fundingCandidateWatchlistScript = Join-Path $repoRoot "tools\funding_candidate_watchlist.ps1"
$fundingWatchlistReviewScript = Join-Path $repoRoot "tools\funding_watchlist_review.ps1"
if (-not $FeeTierConstraintPath) {
    $FeeTierConstraintPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_fee_tier_operational_constraint_current.json"
}

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_basis_planonly_$timestamp.json"
}

function Invoke-JsonScript {
    param(
        [string]$Path,
        [string[]]$ExtraArgs = @()
    )

    $argsList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Path) + $ExtraArgs + @("-Json")
    $raw = & pwsh @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Script failed with exit code ${LASTEXITCODE}: $Path"
    }
    return ($raw | ConvertFrom-Json)
}

function Select-TopObjects {
    param(
        $Rows,
        [int]$Limit
    )
    return @($Rows | Select-Object -First $Limit)
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

    Write-Host "Funding/Basis Carry PlanOnly" -ForegroundColor Cyan
    Write-Host "Generated: $($Payload.generated_at)"
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Selected branch: $($Payload.selected_branch)"
    Write-Host "Output: $OutputPath"
    Write-Host ""
    Write-Host "Summary" -ForegroundColor Yellow
    Write-Host "  Cost gate: $($Payload.summary.cost_gate_decision)"
    Write-Host "  Fee evidence present: $($Payload.summary.fee_tier_evidence_present)"
    Write-Host "  Viability: $($Payload.summary.viability_decision)"
    Write-Host "  Rank eligible: $($Payload.summary.rank_eligible)"
    Write-Host "  Total trades: $($Payload.summary.total_trades)"
    Write-Host "  Watchlist: $($Payload.summary.watchlist_decision)"
    Write-Host ""
    Write-Host "Acceptance blockers" -ForegroundColor Yellow
    foreach ($blocker in @($Payload.acceptance_blockers)) {
        Write-Host "  - $blocker"
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
        mode = "trading_funding_basis_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = $null
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        paper_forward_allowed = $false
        reason = "Active run gate is $($gate.status); only gate-compliant status/resume work is allowed."
        gate_status = $gate.status
        output_path = $OutputPath
        next_valid_moves = @(
            "If RUNNING, wait and only do status/ETA checks.",
            "If STOPPED_INCOMPLETE, visibly resume or explicitly reject the dataset before branch selection.",
            "Do not run funding diagnostics, replay, grid, collectors, live orders or API-key work."
        )
    }
    Save-Result -Payload $blocked
    exit 0
}

$costGate = Invoke-JsonScript -Path $fundingCostAssumptionGateScript
$viability = Invoke-JsonScript -Path $fundingViabilityGapScript
$watchlist = Invoke-JsonScript -Path $fundingCandidateWatchlistScript
$watchlistReview = Invoke-JsonScript -Path $fundingWatchlistReviewScript
$feeTierConstraint = $null
$feeTierConstraintPresent = Test-Path -LiteralPath $FeeTierConstraintPath
if ($feeTierConstraintPresent) {
    $feeTierConstraint = Get-Content -Raw -LiteralPath $FeeTierConstraintPath | ConvertFrom-Json
}
$baseFeeConstraintAccepted = [bool](
    $feeTierConstraint -and
    [string]$feeTierConstraint.mode -eq "funding_fee_tier_operational_constraint" -and
    [bool]$feeTierConstraint.accepted_as_operational_constraint -and
    -not [bool]$feeTierConstraint.lower_cost_scenarios_allowed_for_acceptance
)

$topBlockers = @($viability.summary.top_blockers | Select-Object -First 10)
$acceptanceBlockers = [System.Collections.Generic.List[string]]::new()
foreach ($reason in @($costGate.fee_tier_evidence_reasons)) {
    $acceptanceBlockers.Add([string]$reason) | Out-Null
}
foreach ($blocker in $topBlockers) {
    $acceptanceBlockers.Add([string]$blocker.reason) | Out-Null
}
if ([int]($viability.rank_eligible ?? 0) -eq 0) {
    $acceptanceBlockers.Add("rank_eligible_zero") | Out-Null
}
if ([int]($viability.total_trades ?? 0) -eq 0) {
    $acceptanceBlockers.Add("backtest_total_trades_zero") | Out-Null
}
if ([string]$watchlistReview.decision -eq "NO_CURRENT_COST_EDGE_IN_WATCHLIST_OR_RANK") {
    $acceptanceBlockers.Add("watchlist_review_no_current_cost_edge") | Out-Null
}

$decision = if (
    $baseFeeConstraintAccepted -and
    [string]$viability.decision -eq "NOT_VIABLE_CURRENT_COST_MODEL"
) {
    "FUNDING_BASIS_PLANONLY_REJECTED_BASE_FEES_SELECT_NEXT_BRANCH"
} elseif (
    [string]$costGate.decision -eq "USE_CURRENT_COST_ONLY_FOR_ACCEPTANCE" -and
    [string]$viability.decision -eq "NOT_VIABLE_CURRENT_COST_MODEL"
) {
    "FUNDING_BASIS_PLANONLY_CURRENT_COST_NOT_ACCEPTED"
} elseif ([bool]$costGate.fee_tier_evidence_accepted) {
    "FUNDING_BASIS_PLANONLY_FEE_EVIDENCE_REVIEW_REQUIRED"
} else {
    "FUNDING_BASIS_PLANONLY_INCONCLUSIVE"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_funding_basis_planonly"
    decision = $decision
    selected_branch = "funding_basis_carry_structural_planonly"
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    paper_forward_allowed = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    reason = "PlanOnly branch packet after liquidity_sweep_reversal rejection. Uses existing funding/basis diagnostics only; no collector, grid, live orders, API keys, leverage or margin."
    summary = [ordered]@{
        gate_status = $gate.status
        gate_next_goal_decision = $gate.next_goal_decision
        cost_gate_decision = $costGate.decision
        fee_tier_evidence_present = [bool]$costGate.fee_tier_evidence_present
        fee_tier_evidence_accepted = [bool]$costGate.fee_tier_evidence_accepted
        fee_tier_constraint_present = $feeTierConstraintPresent
        base_fee_constraint_accepted = $baseFeeConstraintAccepted
        account_tier_constraint = if ($feeTierConstraint) { [string]$feeTierConstraint.account_tier } else { "not-specified" }
        exact_fee_bps_specified = if ($feeTierConstraint) { [bool]$feeTierConstraint.exact_fee_bps_specified } else { $false }
        acceptance_scenarios = @($costGate.acceptance_scenarios)
        sensitivity_only_scenarios = @($costGate.sensitivity_only_scenarios)
        viability_decision = $viability.decision
        data_quality_accepted = [bool]$viability.data_quality_accepted
        research_accepted = [bool]$viability.research_accepted
        rank_eligible = [int]($viability.rank_eligible ?? 0)
        total_trades = [int]($viability.total_trades ?? 0)
        markets_analyzed = [int]($viability.markets_analyzed ?? 0)
        rows = [int]($viability.rows ?? 0)
        watchlist_decision = $watchlist.decision
        primary_7d_watch = [int]($watchlist.summary.primary_7d_watch ?? 0)
        secondary_7d_watch = [int]($watchlist.summary.secondary_7d_watch ?? 0)
        diagnostic_coverage = [int]($watchlist.summary.diagnostic_coverage ?? 0)
        watchlist_review_decision = $watchlistReview.decision
        watchlist_rank_eligible = [int]($watchlistReview.summary.watchlist_rank_eligible ?? 0)
        off_watchlist_rank_eligible = [int]($watchlistReview.summary.off_watchlist_rank_eligible ?? 0)
    }
    economics_snapshot = [ordered]@{
        current_taker_like_one_interval_required_bps = $viability.summary.current_taker_like_one_interval_required_bps
        current_taker_like_observed_p95_bps = $viability.summary.current_taker_like_observed_p95_bps
        current_taker_like_observed_p99_bps = $viability.summary.current_taker_like_observed_p99_bps
        current_taker_like_one_interval_p99_gap_bps = $viability.summary.current_taker_like_one_interval_p99_gap_bps
        current_taker_like_six_interval_p99_gap_bps = $viability.summary.current_taker_like_six_interval_p99_gap_bps
        maker_vip_three_interval_p95_gap_bps = $viability.summary.maker_vip_three_interval_p95_gap_bps
        top_blockers = $topBlockers
        must_improve = @($viability.summary.must_improve)
    }
    watchlist_snapshot = [ordered]@{
        recommended_bases = @($watchlist.summary.unique_recommended_bases)
        recommended = Select-TopObjects -Rows $watchlist.recommended -Limit $TopN
        review_rows = Select-TopObjects -Rows $watchlistReview.review_rows -Limit $TopN
    }
    fee_tier_constraint = if ($feeTierConstraint) { $feeTierConstraint } else { $null }
    acceptance_blockers = @($acceptanceBlockers | Select-Object -Unique)
    next_valid_moves = if ($baseFeeConstraintAccepted) {
        @(
            "Treat funding/basis carry as rejected under base/no-volume fees for the current project state.",
            "Do not spend more cycles trying to rescue funding/basis via maker/VIP/reduced-fee sensitivity rows.",
            "Exact fee bps may be collected later only for reporting precision, not as a reason to reopen lower-cost acceptance scenarios.",
            "Design a new non-HFT structural research branch through PlanOnly.",
            "Do not tune liquidity_sweep_reversal further on the current dataset."
        )
    } else {
        @(
            "If the user can provide non-secret actual maker/taker fee tiers for spot and perp on MEXC/Gate, store them as fee evidence and rerun this PlanOnly packet.",
            "If accepted fee evidence materially lowers real round-trip costs, plan a new visible multi-week funding/basis collect; still no live/API/paper-forward.",
            "If current-cost economics remain negative and no fee evidence exists, deprioritize funding carry and design a new non-HFT structural branch.",
            "Do not tune liquidity_sweep_reversal further on the current dataset.",
            "Do not use watchlist rows as trade signals; they are only research focus candidates."
        )
    }
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "paper_forward",
        "grid_search",
        "new_hidden_or_background_collect",
        "retune_liquidity_sweep_reversal_on_current_dataset"
    )
    commands = [ordered]@{
        rerun_this_planonly = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
        funding_cost_assumption_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$fundingCostAssumptionGateScript`" -Json"
        funding_viability_gap = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$fundingViabilityGapScript`" -Json"
        funding_candidate_watchlist = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$fundingCandidateWatchlistScript`" -Json"
        funding_watchlist_review = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$fundingWatchlistReviewScript`" -Json"
    }
    inputs = [ordered]@{
        gate_checker = $gateChecker
        cost_gate = $fundingCostAssumptionGateScript
        viability_gap = $fundingViabilityGapScript
        candidate_watchlist = $fundingCandidateWatchlistScript
        watchlist_review = $fundingWatchlistReviewScript
        fee_tier_constraint = $FeeTierConstraintPath
    }
    output_path = $OutputPath
}

Save-Result -Payload $result
