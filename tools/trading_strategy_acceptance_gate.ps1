param(
    [string]$ScorecardPath = "",
    [string]$FundingPostprocessPath = "",
    [string]$FundingWatchlistReviewPath = "",
    [string]$PaperForwardSummaryPath = "",
    [string]$PaperDecisionPath = "",
    [int]$MinTrades = 20,
    [double]$MinWinRate = 0.60,
    [double]$MinExpectancyQuote = 0.0,
    [double]$MinNetPnlQuote = 0.0,
    [double]$MinProfitFactor = 1.20,
    [double]$MaxDrawdownQuote = 5.0,
    [switch]$RequireAccepted,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$preflightScript = Join-Path $repoRoot "tools\trading_edge_preflight.ps1"

if (-not $ScorecardPath) {
    $ScorecardPath = Join-Path $repoRoot "exports\trading-mvp\analysis\anufriev_strategy_scorecard_current_20260628.csv"
}
if (-not $FundingPostprocessPath) {
    $FundingPostprocessPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json"
}
if (-not $FundingWatchlistReviewPath) {
    $FundingWatchlistReviewPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_watchlist_review_20260617.json"
}

function Add-Reason {
    param(
        [System.Collections.Generic.List[string]]$Reasons,
        [string]$Reason
    )
    if (-not $Reasons.Contains($Reason)) {
        $Reasons.Add($Reason) | Out-Null
    }
}

function To-NullableDouble {
    param($Value)
    if ($null -eq $Value) {
        return $null
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text) -or $text -eq "not-applicable") {
        return $null
    }
    $parsed = 0.0
    if ([double]::TryParse($text, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function Test-BoolTrue {
    param($Value)
    if ($Value -is [bool]) {
        return $Value
    }
    return ([string]$Value).ToLowerInvariant() -eq "true"
}

$researchRejectVerdicts = @(
    "rejected",
    "failed",
    "inconclusive",
    "untested",
    "excluded_from_trading_bot",
    "tooling_only",
    "mandatory_gate"
)

$reasons = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

$preflight = $null
$fundingBlockedBySwarm = $false
try {
    $preflight = & pwsh -NoProfile -ExecutionPolicy Bypass -File $preflightScript -Json | ConvertFrom-Json
    if ($preflight.PSObject.Properties.Name -contains "funding_blocked_by_swarm") {
        $fundingBlockedBySwarm = Test-BoolTrue $preflight.funding_blocked_by_swarm
    }
    if (-not (Test-BoolTrue $preflight.ok)) {
        Add-Reason $reasons "edge_preflight_not_ok"
    }
} catch {
    Add-Reason $reasons "edge_preflight_failed"
    $warnings.Add("Failed to run edge preflight: $($_.Exception.Message)") | Out-Null
}

$scorecard = @()
if (Test-Path -LiteralPath $ScorecardPath) {
    $scorecard = @(Import-Csv -LiteralPath $ScorecardPath)
} else {
    Add-Reason $reasons "scorecard_missing"
}

$acceptedRows = @(
    $scorecard | Where-Object {
        $verdict = ([string]$_.verdict).ToLowerInvariant()
        -not ($researchRejectVerdicts -contains $verdict)
    }
)

if ($acceptedRows.Count -eq 0) {
    Add-Reason $reasons "no_accepted_scorecard_strategy"
}

$scorecardIssues = @()
foreach ($row in $acceptedRows) {
    $rowReasons = [System.Collections.Generic.List[string]]::new()
    $winRate = To-NullableDouble $row.win_rate
    $trades = To-NullableDouble $row.trades
    $netPnl = To-NullableDouble $row.net_pnl_quote
    $profitFactor = To-NullableDouble $row.profit_factor

    if ($null -eq $trades -or $trades -lt $MinTrades) { Add-Reason $rowReasons "min_trades" }
    if ($null -eq $winRate -or $winRate -lt $MinWinRate) { Add-Reason $rowReasons "min_win_rate" }
    if ($null -eq $netPnl -or $netPnl -le $MinNetPnlQuote) { Add-Reason $rowReasons "min_net_pnl_quote" }
    if ($null -eq $profitFactor -or $profitFactor -lt $MinProfitFactor) { Add-Reason $rowReasons "min_profit_factor" }

    if ($rowReasons.Count -gt 0) {
        $scorecardIssues += [ordered]@{
            strategy_family = $row.strategy_family
            project_setup_id = $row.project_setup_id
            verdict = $row.verdict
            reasons = @($rowReasons)
        }
    }
}
if ($scorecardIssues.Count -gt 0) {
    Add-Reason $reasons "accepted_scorecard_rows_fail_metric_floor"
}

$fundingPostprocess = $null
$fundingSummary = [ordered]@{
    path = $FundingPostprocessPath
    present = $false
    research_accepted = $null
    acceptance_accepted = $null
    oos_accepted = $null
    walk_forward_accepted = $null
    stress_accepted = $null
    data_quality_accepted = $null
    rank_eligible = $null
    total_trades = $null
    win_rate = $null
    expectancy_quote = $null
    net_pnl_quote = $null
    profit_factor = $null
    max_drawdown_quote = $null
}

$fundingWatchlistReview = $null
$fundingWatchlistSummary = [ordered]@{
    path = $FundingWatchlistReviewPath
    present = $false
    decision = $null
    watchlist_rank_eligible = $null
    primary_rank_eligible = $null
    secondary_rank_eligible = $null
    off_watchlist_rank_eligible = $null
    research_accepted = $null
    accepted_for_research_promotion = $false
}

if (Test-Path -LiteralPath $FundingPostprocessPath) {
    $fundingPostprocess = Get-Content -Raw -LiteralPath $FundingPostprocessPath | ConvertFrom-Json
    $fundingSummary.present = $true
    $fundingSummary.research_accepted = Test-BoolTrue $fundingPostprocess.research_acceptance.accepted
    $fundingSummary.acceptance_accepted = Test-BoolTrue $fundingPostprocess.acceptance.accepted
    $fundingSummary.oos_accepted = Test-BoolTrue $fundingPostprocess.oos.accepted
    $fundingSummary.walk_forward_accepted = Test-BoolTrue $fundingPostprocess.walk_forward.accepted
    $fundingSummary.stress_accepted = Test-BoolTrue $fundingPostprocess.research_acceptance.stress_accepted
    $fundingSummary.data_quality_accepted = Test-BoolTrue $fundingPostprocess.data_quality.accepted
    $fundingSummary.rank_eligible = [int]($fundingPostprocess.rank_summary.rank_eligible ?? 0)
    $fundingSummary.total_trades = [int]($fundingPostprocess.backtest_metrics.total_trades ?? 0)
    $fundingSummary.win_rate = [double]($fundingPostprocess.backtest_metrics.win_rate ?? 0)
    $fundingSummary.expectancy_quote = [double]($fundingPostprocess.backtest_metrics.expectancy_quote ?? 0)
    $fundingSummary.net_pnl_quote = [double]($fundingPostprocess.backtest_metrics.net_pnl_quote ?? 0)
    $fundingSummary.profit_factor = $fundingPostprocess.backtest_metrics.profit_factor
    $fundingSummary.max_drawdown_quote = [double]($fundingPostprocess.backtest_metrics.max_drawdown_quote ?? 0)

    if (-not $fundingSummary.data_quality_accepted) { Add-Reason $reasons "funding_data_quality_not_accepted" }
    if (-not $fundingSummary.research_accepted) { Add-Reason $reasons "funding_research_not_accepted" }
    if (-not $fundingSummary.acceptance_accepted) { Add-Reason $reasons "funding_backtest_not_accepted" }
    if (-not $fundingSummary.oos_accepted) { Add-Reason $reasons "funding_oos_not_accepted" }
    if (-not $fundingSummary.walk_forward_accepted) { Add-Reason $reasons "funding_walk_forward_not_accepted" }
    if (-not $fundingSummary.stress_accepted) { Add-Reason $reasons "funding_stress_not_accepted" }
    if ($fundingSummary.rank_eligible -le 0) { Add-Reason $reasons "funding_rank_eligible_zero" }
    if ($fundingSummary.total_trades -lt $MinTrades) { Add-Reason $reasons "funding_min_trades" }
    if ($fundingSummary.win_rate -lt $MinWinRate) { Add-Reason $reasons "funding_min_win_rate" }
    if ($fundingSummary.expectancy_quote -le $MinExpectancyQuote) { Add-Reason $reasons "funding_min_expectancy_quote" }
    if ($fundingSummary.net_pnl_quote -le $MinNetPnlQuote) { Add-Reason $reasons "funding_min_net_pnl_quote" }
    if ($null -eq $fundingSummary.profit_factor -or [double]$fundingSummary.profit_factor -lt $MinProfitFactor) { Add-Reason $reasons "funding_min_profit_factor" }
    if ($fundingSummary.max_drawdown_quote -gt $MaxDrawdownQuote) { Add-Reason $reasons "funding_max_drawdown_quote" }
} else {
    Add-Reason $reasons "funding_postprocess_missing"
}

if (Test-Path -LiteralPath $FundingWatchlistReviewPath) {
    $fundingWatchlistReview = Get-Content -Raw -LiteralPath $FundingWatchlistReviewPath | ConvertFrom-Json
    $fundingWatchlistSummary.present = $true
    $fundingWatchlistSummary.decision = [string]$fundingWatchlistReview.decision
    $fundingWatchlistSummary.watchlist_rank_eligible = [int]($fundingWatchlistReview.summary.watchlist_rank_eligible ?? 0)
    $fundingWatchlistSummary.primary_rank_eligible = [int]($fundingWatchlistReview.summary.primary_rank_eligible ?? 0)
    $fundingWatchlistSummary.secondary_rank_eligible = [int]($fundingWatchlistReview.summary.secondary_rank_eligible ?? 0)
    $fundingWatchlistSummary.off_watchlist_rank_eligible = [int]($fundingWatchlistReview.summary.off_watchlist_rank_eligible ?? 0)
    $fundingWatchlistSummary.research_accepted = Test-BoolTrue $fundingWatchlistReview.summary.research_accepted
    $fundingWatchlistSummary.accepted_for_research_promotion = (
        $fundingWatchlistSummary.decision -eq "WATCHLIST_SUPPORTED_ACCEPTANCE_REVIEW_REQUIRED" -and
        $fundingWatchlistSummary.watchlist_rank_eligible -gt 0 -and
        $fundingWatchlistSummary.off_watchlist_rank_eligible -eq 0
    )

    if (-not $fundingWatchlistSummary.accepted_for_research_promotion) {
        Add-Reason $reasons "funding_watchlist_review_not_acceptance_supporting"
    }
    if ($fundingWatchlistSummary.watchlist_rank_eligible -le 0) {
        Add-Reason $reasons "funding_watchlist_rank_eligible_zero"
    }
    if ($fundingWatchlistSummary.off_watchlist_rank_eligible -gt 0) {
        Add-Reason $reasons "funding_off_watchlist_eligible_requires_independent_review"
    }
    if ($fundingWatchlistSummary.decision -in @(
        "ACCEPTANCE_CONFLICT_NO_WATCHLIST_SUPPORT",
        "OFF_WATCHLIST_ONLY_REQUIRES_CHERRY_PICK_REVIEW",
        "INCONCLUSIVE_REVIEW_REQUIRED"
    )) {
        Add-Reason $reasons ("funding_watchlist_conflict_{0}" -f $fundingWatchlistSummary.decision.ToLowerInvariant())
    }
} else {
    Add-Reason $reasons "funding_watchlist_review_missing"
}

$paperSummary = $null
$paperDecision = $null
$paperAccepted = $false
if ($PaperForwardSummaryPath) {
    if (Test-Path -LiteralPath $PaperForwardSummaryPath) {
        $paperSummary = Get-Content -Raw -LiteralPath $PaperForwardSummaryPath | ConvertFrom-Json
        $paperAccepted = Test-BoolTrue $paperSummary.paper_acceptance.accepted
        if (-not $paperAccepted) {
            Add-Reason $reasons "paper_forward_not_accepted"
        }
        if (Test-BoolTrue $paperSummary.live_orders) {
            Add-Reason $reasons "paper_forward_live_orders_not_false"
        }
    } else {
        Add-Reason $reasons "paper_forward_summary_missing"
    }
} else {
    Add-Reason $reasons "paper_forward_not_run"
}

$paperDecisionAccepted = $false
if ($PaperDecisionPath) {
    if (Test-Path -LiteralPath $PaperDecisionPath) {
        $paperDecision = Get-Content -Raw -LiteralPath $PaperDecisionPath | ConvertFrom-Json
        $paperDecisionAccepted = Test-BoolTrue $paperDecision.summary.accepted
        if (-not $paperDecisionAccepted) {
            Add-Reason $reasons "paper_decision_not_accepted"
        }
        if (Test-BoolTrue $paperDecision.live_orders) {
            Add-Reason $reasons "paper_decision_live_orders_not_false"
        }
    } else {
        Add-Reason $reasons "paper_decision_missing"
    }
} else {
    Add-Reason $reasons "paper_decision_not_run"
}

$researchAccepted = (
    $acceptedRows.Count -gt 0 -and
    $fundingSummary.present -and
    $fundingSummary.research_accepted -and
    $fundingSummary.acceptance_accepted -and
    $fundingSummary.oos_accepted -and
    $fundingSummary.walk_forward_accepted -and
    $fundingSummary.stress_accepted -and
    $fundingSummary.data_quality_accepted -and
    $fundingSummary.rank_eligible -gt 0 -and
    $fundingSummary.total_trades -ge $MinTrades -and
    $fundingSummary.win_rate -ge $MinWinRate -and
    $fundingSummary.expectancy_quote -gt $MinExpectancyQuote -and
    $fundingSummary.net_pnl_quote -gt $MinNetPnlQuote -and
    $null -ne $fundingSummary.profit_factor -and
    [double]$fundingSummary.profit_factor -ge $MinProfitFactor -and
    $fundingSummary.max_drawdown_quote -le $MaxDrawdownQuote -and
    $fundingWatchlistSummary.accepted_for_research_promotion
)

$paperForwardAccepted = ($researchAccepted -and $paperAccepted -and $paperDecisionAccepted)
$liveAccepted = $false

$stage = if ($paperForwardAccepted) {
    "paper_forward_validated_live_still_blocked"
} elseif ($researchAccepted) {
    "research_accepted_paper_forward_required"
} else {
    "research_only_no_accepted_strategy"
}

$nextAction = if ($researchAccepted -and -not $paperForwardAccepted) {
    "Freeze config and run paper-forward only in visible/paper mode. Live remains blocked."
} elseif ($paperForwardAccepted) {
    "Run separate live-readiness review; live remains blocked until explicit approval and venue/API risk gates."
} elseif ($fundingBlockedBySwarm) {
    "Do not paper/live. Funding carry is blocked by Swarm L1/L2; validate real non-secret fee-tier evidence or select another edge family before any new long collect."
} else {
    "Do not paper/live. Continue proof pipeline: visible longer data collection after explicit approval, or improve gates/economics."
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_strategy_acceptance_gate"
    accepted = $researchAccepted
    live_orders = $false
    stage = $stage
    funding_blocked_by_swarm = $fundingBlockedBySwarm
    reasons = @($reasons)
    warnings = @($warnings)
    thresholds = [ordered]@{
        min_trades = $MinTrades
        min_win_rate = $MinWinRate
        min_expectancy_quote = $MinExpectancyQuote
        min_net_pnl_quote = $MinNetPnlQuote
        min_profit_factor = $MinProfitFactor
        max_drawdown_quote = $MaxDrawdownQuote
    }
    scorecard = [ordered]@{
        path = $ScorecardPath
        present = (Test-Path -LiteralPath $ScorecardPath)
        rows = $scorecard.Count
        accepted_rows = $acceptedRows.Count
        accepted_row_issues = @($scorecardIssues)
    }
    funding = $fundingSummary
    funding_watchlist_review = $fundingWatchlistSummary
    paper_forward = [ordered]@{
        summary_path = $PaperForwardSummaryPath
        decision_path = $PaperDecisionPath
        summary_provided = [bool]$PaperForwardSummaryPath
        decision_provided = [bool]$PaperDecisionPath
        accepted = $paperForwardAccepted
        summary_acceptance = $paperAccepted
        decision_acceptance = $paperDecisionAccepted
    }
    next_action = $nextAction
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "trading_mvp Strategy Acceptance Gate" -ForegroundColor Cyan
    Write-Host "Generated: $($result.generated_at)"
    Write-Host "Stage: $stage"
    Write-Host "Research accepted: $researchAccepted"
    Write-Host "Paper-forward accepted: $paperForwardAccepted"
    Write-Host "Live orders: false"
    Write-Host ""
    Write-Host "Scorecard" -ForegroundColor Yellow
    Write-Host "  Rows: $($result.scorecard.rows)"
    Write-Host "  Accepted rows: $($result.scorecard.accepted_rows)"
    Write-Host ""
    Write-Host "Funding current artifact" -ForegroundColor Yellow
    Write-Host "  Research accepted: $($fundingSummary.research_accepted)"
    Write-Host "  Rank eligible: $($fundingSummary.rank_eligible)"
    Write-Host "  Trades: $($fundingSummary.total_trades)"
    Write-Host "  Win rate: $($fundingSummary.win_rate)"
    Write-Host "  Net PnL quote: $($fundingSummary.net_pnl_quote)"
    Write-Host "  Expectancy quote: $($fundingSummary.expectancy_quote)"
    Write-Host "  Profit factor: $($fundingSummary.profit_factor)"
    Write-Host ""
    Write-Host "Funding watchlist review" -ForegroundColor Yellow
    Write-Host "  Present: $($fundingWatchlistSummary.present)"
    Write-Host "  Decision: $($fundingWatchlistSummary.decision)"
    Write-Host "  Watchlist rank eligible: $($fundingWatchlistSummary.watchlist_rank_eligible)"
    Write-Host "  Off-watchlist rank eligible: $($fundingWatchlistSummary.off_watchlist_rank_eligible)"
    Write-Host "  Acceptance supporting: $($fundingWatchlistSummary.accepted_for_research_promotion)"
    Write-Host ""
    Write-Host "Reasons" -ForegroundColor Yellow
    foreach ($reason in $reasons) {
        Write-Host "  - $reason"
    }
    Write-Host ""
    Write-Host "Next action" -ForegroundColor Yellow
    Write-Host "  $nextAction"
}

if ($RequireAccepted -and -not $researchAccepted) {
    exit 2
}
exit 0
