param(
    [string]$WatchlistPath = "",
    [string]$RankPath = "",
    [string]$PostprocessPath = "",
    [string]$OutputJson = "",
    [string]$OutputCsv = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$invariantCulture = [System.Globalization.CultureInfo]::InvariantCulture
[System.Threading.Thread]::CurrentThread.CurrentCulture = $invariantCulture
[System.Threading.Thread]::CurrentThread.CurrentUICulture = $invariantCulture

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $WatchlistPath) {
    $WatchlistPath = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_candidate_watchlist_20260617.json"
}
if (-not $RankPath) {
    $RankPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_rank_24h_spotliq_relaxed15_20260615_202709.json"
}
if (-not $PostprocessPath) {
    $PostprocessPath = Join-Path $repoRoot "exports\trading-mvp\funding\funding_postprocess_24h_spotliq_relaxed15_20260615_202709.json"
}
if (-not $OutputJson) {
    $OutputJson = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_watchlist_review_20260617.json"
}
if (-not $OutputCsv) {
    $OutputCsv = Join-Path $repoRoot "exports\trading-mvp\analysis\funding_watchlist_review_20260617.csv"
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

function Get-MarketKey {
    param($Row)
    return ("{0}:{1}:{2}:{3}" -f ([string]$Row.exchange).ToLowerInvariant(), ([string]$Row.base).ToUpperInvariant(), ([string]$Row.spot_symbol).ToUpperInvariant(), ([string]$Row.perp_symbol).ToUpperInvariant())
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

foreach ($path in @($WatchlistPath, $RankPath, $PostprocessPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required artifact not found: $path"
    }
}

$watchlist = Get-Content -Raw -LiteralPath $WatchlistPath | ConvertFrom-Json
$rank = Get-Content -Raw -LiteralPath $RankPath | ConvertFrom-Json
$postprocess = Get-Content -Raw -LiteralPath $PostprocessPath | ConvertFrom-Json

$watchRows = @($watchlist.watchlist)
if ($watchRows.Count -eq 0) {
    $watchRows = @($watchlist.recommended)
}
$rankRows = @($rank.rows)

$rankByKey = @{}
foreach ($row in $rankRows) {
    $rankByKey[(Get-MarketKey $row)] = $row
}

$watchKeys = @{}
foreach ($row in $watchRows) {
    $watchKeys[(Get-MarketKey $row)] = $true
}

$reviewRows = @(
    foreach ($watch in $watchRows) {
        $key = Get-MarketKey $watch
        $final = if ($rankByKey.ContainsKey($key)) { $rankByKey[$key] } else { $null }
        $finalFound = $null -ne $final
        $initialRisk = To-Double $watch.risk_adjusted_edge_bps
        $finalRisk = if ($finalFound) { To-Double $final.risk_adjusted_edge_bps } else { $null }
        $initialExpected = To-Double $watch.expected_net_carry_bps
        $finalExpected = if ($finalFound) { To-Double $final.expected_net_carry_bps } else { $null }
        $finalEligible = if ($finalFound) { To-Bool $final.rank_eligible } else { $false }
        $priority = [string]$watch.priority
        $finalReasons = if ($finalFound) { (@($final.rank_reasons) -join ";") } else { "missing_from_rank" }
        $status = "missing_from_rank"
        if ($finalFound -and $finalEligible) {
            $status = "rank_eligible_current_cost"
        } elseif ($finalFound -and $finalRisk -gt $initialRisk -and $finalExpected -gt $initialExpected) {
            $status = "improved_but_not_eligible"
        } elseif ($finalFound) {
            $status = "not_eligible"
        }

        [pscustomobject][ordered]@{
            market_key = $key
            priority = $priority
            exchange = [string]$watch.exchange
            base = [string]$watch.base
            spot_symbol = [string]$watch.spot_symbol
            perp_symbol = [string]$watch.perp_symbol
            initial_rank = [int](To-Double $watch.rank)
            final_rank = if ($finalFound) { [int](To-Double $final.rank) } else { $null }
            final_found = $finalFound
            initial_watch_score = To-Double $watch.watch_score
            initial_funding_avg_bps = To-Double $watch.funding_avg_bps
            final_funding_avg_bps = if ($finalFound) { To-Double $final.funding_avg_bps } else { $null }
            initial_expected_net_carry_bps = $initialExpected
            final_expected_net_carry_bps = $finalExpected
            initial_risk_adjusted_edge_bps = $initialRisk
            final_risk_adjusted_edge_bps = $finalRisk
            risk_adjusted_edge_delta_bps = if ($finalFound) { $finalRisk - $initialRisk } else { $null }
            final_rank_eligible = $finalEligible
            final_rank_reasons = $finalReasons
            review_status = $status
        }
    }
)

$offWatchEligible = @(
    foreach ($row in $rankRows) {
        $key = Get-MarketKey $row
        if ((To-Bool $row.rank_eligible) -and -not $watchKeys.ContainsKey($key)) {
            [pscustomobject][ordered]@{
                market_key = $key
                exchange = [string]$row.exchange
                base = [string]$row.base
                spot_symbol = [string]$row.spot_symbol
                perp_symbol = [string]$row.perp_symbol
                rank = [int](To-Double $row.rank)
                expected_net_carry_bps = To-Double $row.expected_net_carry_bps
                risk_adjusted_edge_bps = To-Double $row.risk_adjusted_edge_bps
                rank_reasons = (@($row.rank_reasons) -join ";")
            }
        }
    }
)

$primaryRows = @($reviewRows | Where-Object { $_.priority -eq "primary_7d_watch" })
$secondaryRows = @($reviewRows | Where-Object { $_.priority -eq "secondary_7d_watch" })
$watchEligibleRows = @($reviewRows | Where-Object { $_.final_rank_eligible })
$primaryEligibleRows = @($primaryRows | Where-Object { $_.final_rank_eligible })
$secondaryEligibleRows = @($secondaryRows | Where-Object { $_.final_rank_eligible })
$improvedRows = @($reviewRows | Where-Object { $_.review_status -eq "improved_but_not_eligible" })
$rankEligibleCount = @($rankRows | Where-Object { To-Bool $_.rank_eligible }).Count
$researchAccepted = To-Bool $postprocess.research_acceptance.accepted

$decision = if ($researchAccepted -and $watchEligibleRows.Count -gt 0 -and $offWatchEligible.Count -eq 0) {
    "WATCHLIST_SUPPORTED_ACCEPTANCE_REVIEW_REQUIRED"
} elseif ($researchAccepted -and $watchEligibleRows.Count -eq 0) {
    "ACCEPTANCE_CONFLICT_NO_WATCHLIST_SUPPORT"
} elseif ($offWatchEligible.Count -gt 0 -and $watchEligibleRows.Count -eq 0) {
    "OFF_WATCHLIST_ONLY_REQUIRES_CHERRY_PICK_REVIEW"
} elseif ($watchEligibleRows.Count -gt 0) {
    "WATCHLIST_HAS_ELIGIBLE_MARKETS_BUT_RESEARCH_NOT_ACCEPTED"
} elseif ($rankEligibleCount -eq 0) {
    "NO_CURRENT_COST_EDGE_IN_WATCHLIST_OR_RANK"
} else {
    "INCONCLUSIVE_REVIEW_REQUIRED"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "funding_watchlist_review"
    decision = $decision
    warning = "Read-only anti-cherry-picking review. This is not a trade signal and cannot accept a strategy by itself."
    watchlist_path = $WatchlistPath
    rank_path = $RankPath
    postprocess_path = $PostprocessPath
    output_json = $OutputJson
    output_csv = $OutputCsv
    summary = [ordered]@{
        watchlist_rows = $watchRows.Count
        rank_rows = $rankRows.Count
        rank_eligible = $rankEligibleCount
        research_accepted = $researchAccepted
        primary_watch_rows = $primaryRows.Count
        secondary_watch_rows = $secondaryRows.Count
        watchlist_rank_eligible = $watchEligibleRows.Count
        primary_rank_eligible = $primaryEligibleRows.Count
        secondary_rank_eligible = $secondaryEligibleRows.Count
        off_watchlist_rank_eligible = $offWatchEligible.Count
        watchlist_improved_but_not_eligible = $improvedRows.Count
    }
    review_rows = @($reviewRows)
    off_watchlist_eligible = @($offWatchEligible)
    rules = @(
        "A future 7d result should be interpreted against the predeclared watchlist, not cherry-picked after the fact.",
        "Watchlist review cannot accept a strategy; it only validates whether rank/postprocess evidence aligns with the predeclared research focus.",
        "Research acceptance still requires current-cost rank/backtest/OOS/walk-forward/stress and paper-forward gates.",
        "If only off-watchlist markets pass, require explicit cherry-pick review before any promotion."
    )
    next_valid_moves = @(
        "After a final 7d manifest, run guarded funding-final-review and this watchlist review.",
        "If decision remains NO_CURRENT_COST_EDGE_IN_WATCHLIST_OR_RANK, do not paper-forward funding carry.",
        "If off-watchlist markets are the only eligible markets, treat them as new hypothesis requiring independent data, not as accepted edge.",
        "Live/API/leverage remain blocked."
    )
}

$outDir = Split-Path -Parent $OutputJson
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}
ConvertTo-InvariantCsvRows -Rows $reviewRows | Export-Csv -LiteralPath $OutputCsv -NoTypeInformation -Encoding UTF8
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputJson -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 10
    exit 0
}

Write-Host "Funding Watchlist Review" -ForegroundColor Cyan
Write-Host "Generated: $($result.generated_at)"
Write-Host "Decision: $decision"
Write-Host "Warning: $($result.warning)"
Write-Host ""
Write-Host "Summary" -ForegroundColor Yellow
Write-Host "  Watchlist rows: $($result.summary.watchlist_rows)"
Write-Host "  Rank rows: $($result.summary.rank_rows)"
Write-Host "  Rank eligible: $($result.summary.rank_eligible)"
Write-Host "  Research accepted: $($result.summary.research_accepted)"
Write-Host "  Watchlist rank eligible: $($result.summary.watchlist_rank_eligible)"
Write-Host "  Primary rank eligible: $($result.summary.primary_rank_eligible)"
Write-Host "  Secondary rank eligible: $($result.summary.secondary_rank_eligible)"
Write-Host "  Off-watchlist rank eligible: $($result.summary.off_watchlist_rank_eligible)"
Write-Host "  Watchlist improved but not eligible: $($result.summary.watchlist_improved_but_not_eligible)"
Write-Host ""
Write-Host "Top watchlist rows" -ForegroundColor Yellow
foreach ($row in @($reviewRows | Select-Object -First 10)) {
    Write-Host ("  - {0}:{1} {2} status={3} eligible={4} final_risk_edge={5} delta={6}" -f $row.exchange, $row.base, $row.priority, $row.review_status, $row.final_rank_eligible, $row.final_risk_adjusted_edge_bps, $row.risk_adjusted_edge_delta_bps)
}
Write-Host ""
Write-Host "Outputs" -ForegroundColor Yellow
Write-Host "  JSON: $OutputJson"
Write-Host "  CSV: $OutputCsv"
