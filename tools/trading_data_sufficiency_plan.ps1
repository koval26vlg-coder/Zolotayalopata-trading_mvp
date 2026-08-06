param(
    [string]$EventQualityPath = "exports\trading-mvp\backtests\event_quality_ws_confirmed_research_6h_20260628_103700.json",
    [string]$AcceptancePath = "exports\trading-mvp\backtests\sweep_reversal_acceptance_ws_confirmed_research_6h_20260628_103700_gatefixed.json",
    [string]$ManifestPath = "exports\trading-mvp\raw\ws_collect_20260628_000346.json",
    [string]$GridPath = "exports\trading-mvp\backtests\ws_grid_search_ws_confirmed_research_6h_20260628_103700.json",
    [int]$TargetSweeps = 1000,
    [int]$TargetTrades = 20,
    [int[]]$AlternativeMarketCounts = @(16, 24, 32, 48),
    [string]$OutputPath = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Resolve-RepoPath {
    param([string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }
    return (Join-Path $repoRoot $Path)
}

function Read-JsonFile {
    param([string]$Path)
    $resolved = Resolve-RepoPath -Path $Path
    if (-not (Test-Path -LiteralPath $resolved)) {
        throw "Missing required JSON artifact: $resolved"
    }
    return Get-Content -Raw -LiteralPath $resolved | ConvertFrom-Json
}

function Round-Nullable {
    param(
        [AllowNull()]$Value,
        [int]$Digits = 6
    )
    if ($null -eq $Value) {
        return $null
    }
    if ([double]::IsNaN([double]$Value) -or [double]::IsInfinity([double]$Value)) {
        return $null
    }
    return [math]::Round([double]$Value, $Digits)
}

function Divide-Nullable {
    param(
        [double]$Numerator,
        [double]$Denominator
    )
    if ($Denominator -le 0) {
        return $null
    }
    return ($Numerator / $Denominator)
}

$eventQuality = Read-JsonFile -Path $EventQualityPath
$acceptance = Read-JsonFile -Path $AcceptancePath
$manifest = Read-JsonFile -Path $ManifestPath

$grid = $null
$gridResolved = Resolve-RepoPath -Path $GridPath
if (Test-Path -LiteralPath $gridResolved) {
    $grid = Get-Content -Raw -LiteralPath $gridResolved | ConvertFrom-Json
}

$accepted = $false
if ($null -ne $acceptance.accepted) {
    $accepted = [bool]$acceptance.accepted
}

$targetSweepsFromGate = $null
if ($acceptance.thresholds -and $acceptance.thresholds.min_event_count) {
    $targetSweepsFromGate = [int]$acceptance.thresholds.min_event_count
}
if ($targetSweepsFromGate -and $TargetSweeps -lt $targetSweepsFromGate) {
    $TargetSweeps = $targetSweepsFromGate
}

$targetTradesFromGate = $null
if ($acceptance.thresholds -and $acceptance.thresholds.min_trades) {
    $targetTradesFromGate = [int]$acceptance.thresholds.min_trades
}
if ($targetTradesFromGate -and $TargetTrades -lt $targetTradesFromGate) {
    $TargetTrades = $targetTradesFromGate
}

$durationSec = [double]$manifest.duration_sec
if ($manifest.results) {
    $durations = @($manifest.results | ForEach-Object { [double]$_.duration_sec } | Where-Object { $_ -gt 0 })
    if ($durations.Count -gt 0) {
        $durationSec = ($durations | Measure-Object -Maximum).Maximum
    }
}
$observedHours = Divide-Nullable -Numerator $durationSec -Denominator 3600.0

$marketCount = 0
if ($eventQuality.market_count) {
    $marketCount = [int]$eventQuality.market_count
} elseif ($manifest.discovery) {
    foreach ($exchangeName in $manifest.discovery.PSObject.Properties.Name) {
        $selected = $manifest.discovery.$exchangeName.selected_pairs
        if ($selected) {
            $marketCount += [int]$selected
        }
    }
}

$totalSweeps = 0
if ($eventQuality.summary -and $null -ne $eventQuality.summary.total_sweeps) {
    $totalSweeps = [int]$eventQuality.summary.total_sweeps
} elseif ($null -ne $eventQuality.total_sweeps) {
    $totalSweeps = [int]$eventQuality.total_sweeps
}

$totalRows = 0
if ($eventQuality.rows) {
    $totalRows = [int64]$eventQuality.rows
} elseif ($manifest.total_events) {
    $totalRows = [int64]$manifest.total_events
}

$sweepRatePerHour = $null
if ($observedHours -and $observedHours -gt 0) {
    $sweepRatePerHour = Divide-Nullable -Numerator $totalSweeps -Denominator $observedHours
}

$sweepRatePerMarketHour = $null
if ($observedHours -and $observedHours -gt 0 -and $marketCount -gt 0) {
    $sweepRatePerMarketHour = Divide-Nullable -Numerator $totalSweeps -Denominator ($observedHours * $marketCount)
}

$estimatedHoursForTargetSweepsCurrentMarkets = $null
if ($sweepRatePerHour -and $sweepRatePerHour -gt 0) {
    $estimatedHoursForTargetSweepsCurrentMarkets = Divide-Nullable -Numerator $TargetSweeps -Denominator $sweepRatePerHour
}

$estimatedMarketHoursForTargetSweeps = $null
if ($sweepRatePerMarketHour -and $sweepRatePerMarketHour -gt 0) {
    $estimatedMarketHoursForTargetSweeps = Divide-Nullable -Numerator $TargetSweeps -Denominator $sweepRatePerMarketHour
}

$alternativePlans = @()
foreach ($count in $AlternativeMarketCounts) {
    if ($count -le 0) {
        continue
    }
    $hours = $null
    if ($sweepRatePerMarketHour -and $sweepRatePerMarketHour -gt 0) {
        $hours = Divide-Nullable -Numerator $TargetSweeps -Denominator ($sweepRatePerMarketHour * $count)
    }
    $alternativePlans += [ordered]@{
        market_count = [int]$count
        estimated_hours_for_target_sweeps = Round-Nullable -Value $hours -Digits 3
        estimated_days_for_target_sweeps = Round-Nullable -Value (Divide-Nullable -Numerator ([double]($hours ?? 0)) -Denominator 24.0) -Digits 3
        assumes_same_sweep_rate_per_market_hour = $true
    }
}

$bestSignalType = $null
$bestMetrics = $null
$gridTrades = 0
if ($grid -and $grid.best_by_signal_type) {
    $bestProperties = @($grid.best_by_signal_type.PSObject.Properties)
    if ($bestProperties.Count -gt 0) {
        $best = $bestProperties | ForEach-Object {
            $metrics = $_.Value.metrics
            [pscustomobject]@{
                signal_type = $_.Name
                trades = if ($metrics -and $null -ne $metrics.total_trades) { [int]$metrics.total_trades } else { 0 }
                net_pnl = if ($metrics -and $null -ne $metrics.net_pnl_quote) { [double]$metrics.net_pnl_quote } else { [double]::NegativeInfinity }
                payload = $_.Value
            }
        } | Sort-Object -Property trades, net_pnl -Descending | Select-Object -First 1
        if ($best) {
            $bestSignalType = [string]$best.signal_type
            $bestMetrics = $best.payload.metrics
            $gridTrades = [int]$best.trades
        }
    }
}

$tradeRatePerHour = $null
if ($observedHours -and $observedHours -gt 0) {
    $tradeRatePerHour = Divide-Nullable -Numerator $gridTrades -Denominator $observedHours
}

$estimatedHoursForTargetTradesCurrentMarkets = $null
if ($tradeRatePerHour -and $tradeRatePerHour -gt 0) {
    $estimatedHoursForTargetTradesCurrentMarkets = Divide-Nullable -Numerator $TargetTrades -Denominator $tradeRatePerHour
}

$nextCollect6hIsLikelyInsufficient = $true
if ($estimatedHoursForTargetSweepsCurrentMarkets -and $estimatedHoursForTargetSweepsCurrentMarkets -le 24.0) {
    $nextCollect6hIsLikelyInsufficient = $false
}

$paperForwardAllowed = $false
if ($accepted -and $totalSweeps -ge $TargetSweeps) {
    $paperForwardAllowed = $true
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_data_sufficiency_plan"
    research_only = $true
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    paper_forward_allowed = $paperForwardAllowed
    inputs = [ordered]@{
        event_quality_path = Resolve-RepoPath -Path $EventQualityPath
        acceptance_path = Resolve-RepoPath -Path $AcceptancePath
        manifest_path = Resolve-RepoPath -Path $ManifestPath
        grid_path = $gridResolved
    }
    current = [ordered]@{
        observed_hours = Round-Nullable -Value $observedHours -Digits 6
        market_count = $marketCount
        rows = $totalRows
        total_sweeps = $totalSweeps
        acceptance_accepted = $accepted
        acceptance_reasons = @($acceptance.reasons)
        target_before_stop_rate = Round-Nullable -Value $eventQuality.summary.target_before_stop_rate -Digits 6
        false_sweep_rate = Round-Nullable -Value $eventQuality.summary.false_sweep_rate -Digits 6
        best_grid_signal_type = $bestSignalType
        best_grid_trades = $gridTrades
        best_grid_win_rate = if ($bestMetrics) { Round-Nullable -Value $bestMetrics.win_rate -Digits 6 } else { $null }
        best_grid_net_pnl_quote = if ($bestMetrics) { Round-Nullable -Value $bestMetrics.net_pnl_quote -Digits 8 } else { $null }
    }
    targets = [ordered]@{
        target_sweeps = $TargetSweeps
        target_trades = $TargetTrades
        source = "acceptance_gate_or_cli_minimum"
    }
    observed_rates = [ordered]@{
        sweep_rate_per_hour = Round-Nullable -Value $sweepRatePerHour -Digits 6
        sweep_rate_per_market_hour = Round-Nullable -Value $sweepRatePerMarketHour -Digits 8
        best_grid_trade_rate_per_hour = Round-Nullable -Value $tradeRatePerHour -Digits 6
    }
    estimates = [ordered]@{
        estimated_hours_for_target_sweeps_current_markets = Round-Nullable -Value $estimatedHoursForTargetSweepsCurrentMarkets -Digits 3
        estimated_days_for_target_sweeps_current_markets = Round-Nullable -Value (Divide-Nullable -Numerator ([double]($estimatedHoursForTargetSweepsCurrentMarkets ?? 0)) -Denominator 24.0) -Digits 3
        estimated_market_hours_for_target_sweeps = Round-Nullable -Value $estimatedMarketHoursForTargetSweeps -Digits 3
        estimated_hours_for_target_trades_current_markets = Round-Nullable -Value $estimatedHoursForTargetTradesCurrentMarkets -Digits 3
        alternative_market_counts = @($alternativePlans)
    }
    verdict = [ordered]@{
        next_collect_6h_is_likely_insufficient_for_event_gate = $nextCollect6hIsLikelyInsufficient
        reason = if ($nextCollect6hIsLikelyInsufficient) {
            "Current sweep density implies a 6h repeat is unlikely to reach the event gate; collect duration or market count must increase before another OOS claim."
        } else {
            "Current sweep density can plausibly reach the event gate within a 24h window, but OOS/walk-forward/stress gates still apply."
        }
        recommended_next_collect = if ($nextCollect6hIsLikelyInsufficient) {
            "Use a visible dense collect plan sized by market-hours, not another blind 6h run."
        } else {
            "A visible 6h-24h collect may be enough for event gate validation, subject to market density."
        }
        no_live_orders = $true
        no_investment_advice = $true
    }
}

if ($OutputPath) {
    $resolvedOutput = Resolve-RepoPath -Path $OutputPath
    $outputDir = Split-Path -Parent $resolvedOutput
    if ($outputDir -and (-not (Test-Path -LiteralPath $outputDir))) {
        New-Item -ItemType Directory -Path $outputDir | Out-Null
    }
    $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resolvedOutput -Encoding UTF8
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "trading_mvp data sufficiency plan" -ForegroundColor Cyan
    Write-Host "Observed hours: $($result.current.observed_hours); markets: $($result.current.market_count); sweeps: $($result.current.total_sweeps)/$($result.targets.target_sweeps)"
    Write-Host "Sweep rate/hour: $($result.observed_rates.sweep_rate_per_hour); per market-hour: $($result.observed_rates.sweep_rate_per_market_hour)"
    Write-Host "Estimated hours for target sweeps at current markets: $($result.estimates.estimated_hours_for_target_sweeps_current_markets)"
    Write-Host "6h likely insufficient: $($result.verdict.next_collect_6h_is_likely_insufficient_for_event_gate)"
    Write-Host "Paper-forward allowed: $($result.paper_forward_allowed)"
}
