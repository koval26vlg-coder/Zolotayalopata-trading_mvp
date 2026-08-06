param(
    [string]$RankPath = "",
    [string]$OutputCsv = "",
    [string]$OutputJson = "",
    [int]$TopN = 15,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$invariantCulture = [System.Globalization.CultureInfo]::InvariantCulture
[System.Threading.Thread]::CurrentThread.CurrentCulture = $invariantCulture
[System.Threading.Thread]::CurrentThread.CurrentUICulture = $invariantCulture

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $RankPath) {
    $RankPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_rank_24h_spotliq_relaxed15_20260615_202709.json"
}
if (-not $OutputCsv) {
    $OutputCsv = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.csv"
}
if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json"
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

function Log10-Safe {
    param([double]$Value)
    if ($Value -le 0) {
        return 0.0
    }
    return [Math]::Log10($Value)
}

function ConvertTo-InvariantCsvRows {
    param($Rows)
    foreach ($row in @($Rows)) {
        $ordered = [ordered]@{}
        foreach ($property in $row.PSObject.Properties) {
            $value = $property.Value
            if ($value -is [double] -or $value -is [float] -or $value -is [decimal]) {
                $ordered[$property.Name] = ([double]$value).ToString("0.######", $invariantCulture)
            } elseif ($value -is [int] -or $value -is [long]) {
                $ordered[$property.Name] = [string]$value
            } elseif ($value -is [bool]) {
                $ordered[$property.Name] = ([string]$value).ToLowerInvariant()
            } else {
                $ordered[$property.Name] = $value
            }
        }
        [pscustomobject]$ordered
    }
}

if (-not (Test-Path -LiteralPath $RankPath)) {
    throw "Rank artifact not found: $RankPath"
}

$rank = Get-Content -Raw -LiteralPath $RankPath | ConvertFrom-Json
$rows = @($rank.rows)

$watchlist = @(
    foreach ($row in $rows) {
        $fundingAvgBps = To-Double $row.funding_avg_bps
        $positiveRatio = To-Double $row.funding_positive_ratio
        $persistenceScore = To-Double $row.funding_persistence_score
        $perpVolume = To-Double $row.regime_perp_volume_avg_quote
        $spotTop = To-Double $row.regime_spot_top_min_notional_avg_quote
        $spreadAvgBps = To-Double $row.regime_spread_avg_bps
        $basisStdBps = To-Double $row.regime_basis_std_bps
        $basisAbsMaxBps = To-Double $row.regime_basis_abs_max_bps
        $expectedNetBps = To-Double $row.expected_net_carry_bps
        $riskAdjustedBps = To-Double $row.risk_adjusted_edge_bps
        $fundingObservations = [int](To-Double $row.funding_observations)

        $fundingOk = $fundingAvgBps -gt 0 -and $positiveRatio -ge 0.55 -and $fundingObservations -ge 12
        $strongPersistence = $fundingAvgBps -gt 0 -and $positiveRatio -ge 0.85 -and $persistenceScore -ge 0
        $liquidityOk = $perpVolume -ge 1000000 -and $spotTop -ge 25
        $liquidityWeakButUsable = $perpVolume -ge 250000 -and $spotTop -ge 10
        $executionOk = $spreadAvgBps -le 8
        $executionWeakButUsable = $spreadAvgBps -le 15
        $basisOk = $basisStdBps -le 25 -and $basisAbsMaxBps -le 100
        $basisWeakButUsable = $basisStdBps -le 75 -and $basisAbsMaxBps -le 250

        $reasons = [System.Collections.Generic.List[string]]::new()
        if ($expectedNetBps -lt 0) { $reasons.Add("current_cost_expected_net_negative") | Out-Null }
        if ($riskAdjustedBps -lt 0) { $reasons.Add("current_cost_risk_adjusted_edge_negative") | Out-Null }
        if (-not $fundingOk) { $reasons.Add("funding_not_persistent_positive") | Out-Null }
        if (-not $liquidityOk) { $reasons.Add("liquidity_below_primary_threshold") | Out-Null }
        if (-not $executionOk) { $reasons.Add("execution_spread_above_primary_threshold") | Out-Null }
        if (-not $basisOk) { $reasons.Add("basis_regime_unstable") | Out-Null }
        foreach ($rankReason in @($row.rank_reasons)) {
            $reasons.Add("rank_reason:$rankReason") | Out-Null
        }
        $reasons.Add("watchlist_not_trade_signal") | Out-Null

        $priority = "drop_from_primary_watchlist"
        if ($fundingOk -and $strongPersistence -and $liquidityOk -and $executionOk -and $basisOk) {
            $priority = "primary_7d_watch"
        } elseif ($fundingOk -and $liquidityWeakButUsable -and $executionWeakButUsable -and $basisWeakButUsable) {
            $priority = "secondary_7d_watch"
        } elseif ($fundingOk -or $liquidityWeakButUsable) {
            $priority = "diagnostic_coverage"
        }

        $fundingScore = ($fundingAvgBps * 2.0) + [Math]::Max(0.0, $persistenceScore) + ($positiveRatio * 3.0)
        $liquidityScore = (Log10-Safe $perpVolume) + (Log10-Safe $spotTop)
        $executionPenalty = ($spreadAvgBps * 0.5) + ($basisStdBps * 0.1)
        $currentCostPenalty = [Math]::Min(20.0, [Math]::Abs([Math]::Min(0.0, $riskAdjustedBps)) / 10.0)
        $priorityBonus = switch ($priority) {
            "primary_7d_watch" { 10.0 }
            "secondary_7d_watch" { 5.0 }
            "diagnostic_coverage" { 1.0 }
            default { 0.0 }
        }
        $watchScore = $priorityBonus + $fundingScore + $liquidityScore - $executionPenalty - $currentCostPenalty

        [pscustomobject][ordered]@{
            priority = $priority
            watch_score = [Math]::Round($watchScore, 6)
            rank = [int](To-Double $row.rank)
            exchange = [string]$row.exchange
            base = [string]$row.base
            quote = [string]$row.quote
            spot_symbol = [string]$row.spot_symbol
            perp_symbol = [string]$row.perp_symbol
            funding_observations = $fundingObservations
            funding_avg_bps = [Math]::Round($fundingAvgBps, 6)
            latest_funding_bps = [Math]::Round((To-Double $row.funding_bps_per_interval), 6)
            funding_positive_ratio = [Math]::Round($positiveRatio, 6)
            funding_persistence_score = [Math]::Round($persistenceScore, 6)
            regime_perp_volume_avg_quote = [Math]::Round($perpVolume, 6)
            regime_spot_top_min_notional_avg_quote = [Math]::Round($spotTop, 6)
            regime_spread_avg_bps = [Math]::Round($spreadAvgBps, 6)
            regime_basis_std_bps = [Math]::Round($basisStdBps, 6)
            regime_basis_abs_max_bps = [Math]::Round($basisAbsMaxBps, 6)
            expected_net_carry_bps = [Math]::Round($expectedNetBps, 6)
            risk_adjusted_edge_bps = [Math]::Round($riskAdjustedBps, 6)
            break_even_hours = [Math]::Round((To-Double $row.break_even_hours), 6)
            rank_eligible = To-Bool $row.rank_eligible
            rank_reasons = (@($row.rank_reasons) -join ";")
            watch_reasons = (@($reasons) -join ";")
        }
    }
) | Sort-Object `
    @{ Expression = { $_.priority -eq "primary_7d_watch" }; Descending = $true },
    @{ Expression = { $_.priority -eq "secondary_7d_watch" }; Descending = $true },
    @{ Expression = { [double]$_.watch_score }; Descending = $true }

$priorityCounts = @(
    $watchlist |
        Group-Object priority |
        Sort-Object Name |
        ForEach-Object {
            [pscustomobject][ordered]@{
                priority = $_.Name
                count = $_.Count
            }
        }
)

$primary = @($watchlist | Where-Object { $_.priority -eq "primary_7d_watch" })
$secondary = @($watchlist | Where-Object { $_.priority -eq "secondary_7d_watch" })
$recommended = @($primary + $secondary | Sort-Object @{ Expression = { [double]$_.watch_score }; Descending = $true } | Select-Object -First $TopN)

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "funding_candidate_watchlist"
    decision = "WATCHLIST_READY_NOT_TRADEABLE"
    warning = "This is a 7d research focus list, not a trade signal. Current 24h cost model still has zero accepted strategies."
    input = $RankPath
    output_csv = $OutputCsv
    output_json = $OutputJson
    summary = [ordered]@{
        input_rows = $rows.Count
        primary_7d_watch = $primary.Count
        secondary_7d_watch = $secondary.Count
        diagnostic_coverage = @($watchlist | Where-Object { $_.priority -eq "diagnostic_coverage" }).Count
        drop_from_primary_watchlist = @($watchlist | Where-Object { $_.priority -eq "drop_from_primary_watchlist" }).Count
        rank_eligible = @($watchlist | Where-Object { $_.rank_eligible }).Count
        unique_recommended_bases = @($recommended | Select-Object -ExpandProperty base -Unique)
    }
    thresholds = [ordered]@{
        primary_min_funding_positive_ratio = 0.85
        primary_min_perp_volume_avg_quote = 1000000
        primary_min_spot_top_min_notional_avg_quote = 25
        primary_max_regime_spread_avg_bps = 8
        primary_max_regime_basis_std_bps = 25
        secondary_min_funding_positive_ratio = 0.55
        secondary_min_perp_volume_avg_quote = 250000
        secondary_min_spot_top_min_notional_avg_quote = 10
        secondary_max_regime_spread_avg_bps = 15
        secondary_max_regime_basis_std_bps = 75
    }
    priority_counts = $priorityCounts
    recommended = @($recommended)
    watchlist = @($watchlist)
    next_valid_moves = @(
        "Use this list to interpret the next visible 7d funding/basis collect.",
        "Do not use this list to open trades; current cost model remains unaccepted.",
        "After 7d final manifest, require rank/backtest/OOS/walk-forward/stress to pass before any paper-forward discussion.",
        "If all primary/secondary candidates still fail current-cost economics, shift away from funding carry or require real fee-tier evidence before lower-cost scenarios."
    )
}

$outDir = Split-Path -Parent $OutputCsv
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}
ConvertTo-InvariantCsvRows -Rows $watchlist | Export-Csv -LiteralPath $OutputCsv -NoTypeInformation -Encoding UTF8
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputJson -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 10
    exit 0
}

Write-Host "Funding Candidate Watchlist" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Decision: $($result.decision)"
Write-Host "Warning: $($result.warning)"
Write-Host ""
Write-Host "Summary" -ForegroundColor Yellow
Write-Host "  Input rows: $($result.summary.input_rows)"
Write-Host "  Primary 7d watch: $($result.summary.primary_7d_watch)"
Write-Host "  Secondary 7d watch: $($result.summary.secondary_7d_watch)"
Write-Host "  Diagnostic coverage: $($result.summary.diagnostic_coverage)"
Write-Host "  Drop from primary watchlist: $($result.summary.drop_from_primary_watchlist)"
Write-Host "  Rank eligible: $($result.summary.rank_eligible)"
Write-Host "  Recommended bases: $(@($result.summary.unique_recommended_bases) -join ', ')"
Write-Host ""
Write-Host "Top recommended" -ForegroundColor Yellow
foreach ($row in @($recommended | Select-Object -First $TopN)) {
    Write-Host ("  - {0}:{1} {2} score={3} avg_funding={4}bps pos={5} spread={6}bps spot_top={7} risk_edge={8}bps" -f $row.exchange, $row.base, $row.priority, $row.watch_score, $row.funding_avg_bps, $row.funding_positive_ratio, $row.regime_spread_avg_bps, $row.regime_spot_top_min_notional_avg_quote, $row.risk_adjusted_edge_bps)
}
Write-Host ""
Write-Host "Outputs" -ForegroundColor Yellow
Write-Host "  CSV: $OutputCsv"
Write-Host "  JSON: $OutputJson"
