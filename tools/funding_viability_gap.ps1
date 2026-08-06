param(
    [string]$RankPath = "",
    [string]$PostprocessPath = "",
    [string]$ThresholdsPath = "",
    [int]$TopN = 10,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $RankPath) {
    $RankPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_rank_24h_spotliq_relaxed15_20260615_202709.json"
}
if (-not $PostprocessPath) {
    $PostprocessPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json"
}
if (-not $ThresholdsPath) {
    $ThresholdsPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_economic_thresholds_20260617.csv"
}

function To-Double {
    param($Value, [double]$Default = 0.0)
    if ($null -eq $Value) {
        return $Default
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $Default
    }
    $parsed = 0.0
    if ([double]::TryParse($text, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return $parsed
    }
    return $Default
}

function To-Bool {
    param($Value)
    if ($Value -is [bool]) {
        return $Value
    }
    return ([string]$Value).ToLowerInvariant() -eq "true"
}

if (-not (Test-Path -LiteralPath $RankPath)) {
    throw "Rank artifact not found: $RankPath"
}
if (-not (Test-Path -LiteralPath $PostprocessPath)) {
    throw "Postprocess artifact not found: $PostprocessPath"
}
if (-not (Test-Path -LiteralPath $ThresholdsPath)) {
    throw "Thresholds artifact not found: $ThresholdsPath"
}

$rank = Get-Content -Raw -LiteralPath $RankPath | ConvertFrom-Json
$postprocess = Get-Content -Raw -LiteralPath $PostprocessPath | ConvertFrom-Json
$thresholdRows = @(Import-Csv -LiteralPath $ThresholdsPath)
$rows = @($rank.rows)

$reasonCounts = @{}
foreach ($row in $rows) {
    foreach ($reason in @($row.rank_reasons)) {
        if (-not $reasonCounts.ContainsKey($reason)) {
            $reasonCounts[$reason] = 0
        }
        $reasonCounts[$reason] += 1
    }
}
$topBlockers = @(
    $reasonCounts.GetEnumerator() |
        Sort-Object @{ Expression = "Value"; Descending = $true }, @{ Expression = "Name"; Descending = $false } |
        ForEach-Object {
            [pscustomobject][ordered]@{ reason = $_.Name; count = $_.Value }
        }
)

$thresholdSummary = @(
    $thresholdRows | ForEach-Object {
        $required = To-Double $_.required_funding_bps_per_interval_for_zero_net
        $p95 = To-Double $_.observed_p95_funding_bps_per_interval
        $p99 = To-Double $_.observed_p99_funding_bps_per_interval
        $max = To-Double $_.observed_max_funding_bps_per_interval
        [pscustomobject][ordered]@{
            scenario = $_.scenario
            target_hold_intervals = To-Double $_.target_hold_intervals
            round_trip_cost_bps = To-Double $_.round_trip_cost_bps
            required_funding_bps_per_interval = $required
            observed_p95_funding_bps_per_interval = $p95
            observed_p99_funding_bps_per_interval = $p99
            observed_max_funding_bps_per_interval = $max
            p95_gap_bps = $p95 - $required
            p99_gap_bps = $p99 - $required
            max_gap_bps = $max - $required
            p95_clears_required = To-Bool $_.p95_clears_required
            p99_clears_required = To-Bool $_.p99_clears_required
            max_clears_required = To-Bool $_.max_clears_required
            break_even_hours_at_observed_p95 = To-Double $_.break_even_hours_at_observed_p95
            break_even_hours_at_observed_p99 = To-Double $_.break_even_hours_at_observed_p99
        }
    }
)

$candidateGaps = @(
    $rows | ForEach-Object {
        $fundingAvgBps = To-Double $_.funding_avg_bps
        $latestFundingBps = To-Double $_.funding_bps_per_interval
        $targetHoldIntervals = [Math]::Max(1.0, (To-Double $_.target_hold_intervals 1.0))
        $roundTripCostBps = To-Double $_.round_trip_cost_bps
        $basisRiskBps = To-Double $_.basis_risk_penalty_bps
        $spreadRiskBps = To-Double $_.spread_risk_penalty_bps
        $requiredFundingForZeroNet = $roundTripCostBps / $targetHoldIntervals
        $requiredFundingForRiskEdge = ($roundTripCostBps + $basisRiskBps + $spreadRiskBps) / $targetHoldIntervals
        $avgFundingGapForZeroNet = $fundingAvgBps - $requiredFundingForZeroNet
        $avgFundingGapForRiskEdge = $fundingAvgBps - $requiredFundingForRiskEdge
        $requiredHoldIntervalsForRiskEdge = $null
        $requiredHoldHoursForRiskEdge = $null
        if ($fundingAvgBps -gt 0) {
            $requiredHoldIntervalsForRiskEdge = ($roundTripCostBps + $basisRiskBps + $spreadRiskBps) / $fundingAvgBps
            $fundingIntervalHours = (To-Double $_.funding_interval_sec 14400.0) / 3600.0
            $requiredHoldHoursForRiskEdge = $requiredHoldIntervalsForRiskEdge * $fundingIntervalHours
        }
        [pscustomobject][ordered]@{
            rank = $_.rank
            exchange = $_.exchange
            base = $_.base
            spot_symbol = $_.spot_symbol
            perp_symbol = $_.perp_symbol
            rank_eligible = To-Bool $_.rank_eligible
            rank_reasons = @($_.rank_reasons)
            funding_avg_bps = $fundingAvgBps
            latest_funding_bps = $latestFundingBps
            funding_positive_ratio = To-Double $_.funding_positive_ratio
            round_trip_cost_bps = $roundTripCostBps
            basis_risk_penalty_bps = $basisRiskBps
            spread_risk_penalty_bps = $spreadRiskBps
            expected_net_carry_bps = To-Double $_.expected_net_carry_bps
            risk_adjusted_edge_bps = To-Double $_.risk_adjusted_edge_bps
            required_funding_bps_per_interval_for_zero_net = $requiredFundingForZeroNet
            required_funding_bps_per_interval_for_risk_edge = $requiredFundingForRiskEdge
            avg_funding_gap_bps_for_zero_net = $avgFundingGapForZeroNet
            avg_funding_gap_bps_for_risk_edge = $avgFundingGapForRiskEdge
            break_even_hours = $_.break_even_hours
            required_hold_hours_for_risk_edge = $requiredHoldHoursForRiskEdge
            regime_spot_top_min_notional_avg_quote = To-Double $_.regime_spot_top_min_notional_avg_quote
            regime_perp_volume_avg_quote = To-Double $_.regime_perp_volume_avg_quote
            regime_basis_std_bps = To-Double $_.regime_basis_std_bps
            regime_spread_avg_bps = To-Double $_.regime_spread_avg_bps
        }
    }
)

$topByRiskGap = @(
    $candidateGaps |
        Sort-Object @{ Expression = { [double]$_.avg_funding_gap_bps_for_risk_edge }; Descending = $true } |
        Select-Object -First $TopN
)
$topByRequiredHold = @(
    $candidateGaps |
        Where-Object { $null -ne $_.required_hold_hours_for_risk_edge } |
        Sort-Object @{ Expression = { [double]$_.required_hold_hours_for_risk_edge }; Descending = $false } |
        Select-Object -First $TopN
)
$topPositivePersistentByRiskGap = @(
    $candidateGaps |
        Where-Object { [double]$_.funding_avg_bps -gt 0 -and [double]$_.funding_positive_ratio -ge 0.55 } |
        Sort-Object @{ Expression = { [double]$_.avg_funding_gap_bps_for_risk_edge }; Descending = $true } |
        Select-Object -First $TopN
)

$rankEligible = [int]($postprocess.rank_summary.rank_eligible ?? 0)
$totalTrades = [int]($postprocess.backtest_metrics.total_trades ?? 0)
$researchAccepted = To-Bool $postprocess.research_acceptance.accepted
$dataQualityAccepted = To-Bool $postprocess.data_quality.accepted

$currentThresholds = @($thresholdSummary | Where-Object { $_.scenario -eq "current_taker_like" })
$currentOneInterval = $currentThresholds | Where-Object { [double]$_.target_hold_intervals -eq 1.0 } | Select-Object -First 1
$currentSixIntervals = $currentThresholds | Where-Object { [double]$_.target_hold_intervals -eq 6.0 } | Select-Object -First 1
$makerVipThree = $thresholdSummary | Where-Object { $_.scenario -eq "maker_vip_low_slip" -and [double]$_.target_hold_intervals -eq 3.0 } | Select-Object -First 1

$decision = if ($researchAccepted) {
    "RESEARCH_ACCEPTED_CHECK_PAPER_FORWARD"
} elseif ($rankEligible -eq 0 -and $totalTrades -eq 0) {
    "NOT_VIABLE_CURRENT_COST_MODEL"
} else {
    "INCONCLUSIVE_REVIEW_REQUIRED"
}

$primaryBlockers = @($topBlockers | Select-Object -First 5 | ForEach-Object { $_.reason })
$mustImprove = @()
if ($reasonCounts.ContainsKey("expected_edge_below_min")) {
    $mustImprove += "expected_net_carry_after_costs"
}
if ($reasonCounts.ContainsKey("risk_adjusted_edge_below_min")) {
    $mustImprove += "basis_and_spread_risk_adjusted_edge"
}
if ($reasonCounts.ContainsKey("break_even_horizon_too_long")) {
    $mustImprove += "hold_horizon_or_round_trip_cost"
}
if (($reasonCounts.ContainsKey("spot_top_liquidity_low")) -or ($reasonCounts.ContainsKey("spot_top_liquidity_regime_low"))) {
    $mustImprove += "spot_top_liquidity"
}
if (($reasonCounts.ContainsKey("perp_volume_low")) -or ($reasonCounts.ContainsKey("perp_volume_regime_low"))) {
    $mustImprove += "perp_volume"
}
if ($reasonCounts.ContainsKey("funding_below_min")) {
    $mustImprove += "funding_persistence_or_direction"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "funding_viability_gap"
    decision = $decision
    data_quality_accepted = $dataQualityAccepted
    research_accepted = $researchAccepted
    rank_eligible = $rankEligible
    total_trades = $totalTrades
    markets_analyzed = [int]($postprocess.rank_summary.markets_analyzed ?? $rows.Count)
    rows = [int]($postprocess.rank_summary.input_rows ?? 0)
    summary = [ordered]@{
        current_taker_like_one_interval_required_bps = $currentOneInterval.required_funding_bps_per_interval
        current_taker_like_observed_p95_bps = $currentOneInterval.observed_p95_funding_bps_per_interval
        current_taker_like_observed_p99_bps = $currentOneInterval.observed_p99_funding_bps_per_interval
        current_taker_like_one_interval_p99_gap_bps = $currentOneInterval.p99_gap_bps
        current_taker_like_six_interval_p99_gap_bps = $currentSixIntervals.p99_gap_bps
        maker_vip_three_interval_p95_gap_bps = $makerVipThree.p95_gap_bps
        top_blockers = @($topBlockers | Select-Object -First 10)
        must_improve = $mustImprove
    }
    threshold_scenarios = $thresholdSummary
    top_by_funding_gap_for_risk_edge = $topByRiskGap
    top_positive_persistent_by_funding_gap_for_risk_edge = $topPositivePersistentByRiskGap
    top_by_required_hold_hours_for_risk_edge = $topByRequiredHold
    next_valid_moves = @(
        "Visible 7d funding/basis collect only after explicit user approval.",
        "Do not relax acceptance gates to manufacture trades.",
        "If 7d still has rank_eligible=0, test lower-cost/maker/VIP assumptions only if operationally real, or expand exchange/universe coverage.",
        "Paper-forward remains blocked until strategy_acceptance_gate accepts research."
    )
    blocked_moves = @(
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "channel_intake",
        "paper_forward_without_accepted_research",
        "winrate_only_acceptance"
    )
    inputs = [ordered]@{
        rank = $RankPath
        postprocess = $PostprocessPath
        thresholds = $ThresholdsPath
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
    exit 0
}

Write-Host "Funding Viability Gap" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Decision: $decision"
Write-Host "Data quality accepted: $dataQualityAccepted"
Write-Host "Research accepted: $researchAccepted"
Write-Host "Rank eligible: $rankEligible"
Write-Host "Total trades: $totalTrades"
Write-Host ""
Write-Host "Current cost gap" -ForegroundColor Yellow
Write-Host ("  current/taker-like hold=1: required={0} bps, p95={1}, p99={2}, p99_gap={3}" -f $currentOneInterval.required_funding_bps_per_interval, $currentOneInterval.observed_p95_funding_bps_per_interval, $currentOneInterval.observed_p99_funding_bps_per_interval, $currentOneInterval.p99_gap_bps)
Write-Host ("  current/taker-like hold=6: p99_gap={0}" -f $currentSixIntervals.p99_gap_bps)
Write-Host ("  maker/VIP-like hold=3: p95_gap={0}" -f $makerVipThree.p95_gap_bps)
Write-Host ""
Write-Host "Top blockers" -ForegroundColor Yellow
foreach ($blocker in @($topBlockers | Select-Object -First 10)) {
    Write-Host ("  - {0}: {1}" -f $blocker.reason, $blocker.count)
}
Write-Host ""
Write-Host "Must improve" -ForegroundColor Yellow
foreach ($item in $mustImprove) {
    Write-Host "  - $item"
}
Write-Host ""
Write-Host "Best candidates by risk-edge gap" -ForegroundColor Yellow
foreach ($candidate in @($topByRiskGap | Select-Object -First ([Math]::Min(5, $TopN)))) {
    Write-Host ("  - {0}:{1} gap={2:n4} bps/interval required={3:n4} avg_funding={4:n4} reasons={5}" -f $candidate.exchange, $candidate.base, $candidate.avg_funding_gap_bps_for_risk_edge, $candidate.required_funding_bps_per_interval_for_risk_edge, $candidate.funding_avg_bps, (@($candidate.rank_reasons) -join ","))
}
Write-Host ""
Write-Host "Best positive/persistent funding candidates" -ForegroundColor Yellow
foreach ($candidate in @($topPositivePersistentByRiskGap | Select-Object -First ([Math]::Min(5, $TopN)))) {
    Write-Host ("  - {0}:{1} gap={2:n4} bps/interval required={3:n4} avg_funding={4:n4} positive_ratio={5:n3} reasons={6}" -f $candidate.exchange, $candidate.base, $candidate.avg_funding_gap_bps_for_risk_edge, $candidate.required_funding_bps_per_interval_for_risk_edge, $candidate.funding_avg_bps, $candidate.funding_positive_ratio, (@($candidate.rank_reasons) -join ","))
}
Write-Host ""
Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in $result.next_valid_moves) {
    Write-Host "  - $move"
}
