param(
    [string]$EventQualityPath = "exports\trading-mvp\backtests\event_quality_ws_confirmed_research_6h_20260628_103700.json",
    [string]$DataSufficiencyPath = "exports\trading-mvp\analysis\trading_data_sufficiency_plan_ws_confirmed_research_6h_20260628.json",
    [string]$UniversePath = "",
    [int[]]$MarketCounts = @(16, 24, 32, 48),
    [double]$TargetMaxHours = 72.0,
    [int]$RoundHoursTo = 6,
    [string]$Exchanges = "mexc,gateio",
    [string]$OutputPath = "",
    [string]$OutputUniversePath = "exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv",
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

function Read-JsonFileOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    $resolved = Resolve-RepoPath -Path $Path
    if (-not (Test-Path -LiteralPath $resolved)) {
        return $null
    }
    return Get-Content -Raw -LiteralPath $resolved | ConvertFrom-Json
}

function Find-LatestUniverseCsv {
    $universeDir = Join-Path $repoRoot "exports\trading-mvp\universe"
    $files = @(Get-ChildItem -LiteralPath $universeDir -Filter "no_binance_focus_*.csv" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($files.Count -eq 0) {
        throw "No no_binance_focus_*.csv universe file found in $universeDir"
    }
    return $files[0].FullName
}

function Get-BaseFromMarket {
    param([string]$Market)
    $symbol = ($Market -split ":", 2)[-1].ToUpperInvariant()
    if ($symbol.EndsWith("_USDT")) {
        return $symbol.Substring(0, $symbol.Length - 5)
    }
    if ($symbol.EndsWith("USDT")) {
        return $symbol.Substring(0, $symbol.Length - 4)
    }
    return $symbol
}

function Round-Nullable {
    param(
        [AllowNull()]$Value,
        [int]$Digits = 3
    )
    if ($null -eq $Value) {
        return $null
    }
    if ([double]::IsNaN([double]$Value) -or [double]::IsInfinity([double]$Value)) {
        return $null
    }
    return [math]::Round([double]$Value, $Digits)
}

function Round-UpToStep {
    param(
        [double]$Value,
        [int]$Step
    )
    if ($Value -le 0) {
        return 0
    }
    if ($Step -le 0) {
        return [int][math]::Ceiling($Value)
    }
    return [int]([math]::Ceiling($Value / $Step) * $Step)
}

$eventQuality = Read-JsonFileOrNull -Path $EventQualityPath
$dataSufficiency = Read-JsonFileOrNull -Path $DataSufficiencyPath
$resolvedUniverse = if ($UniversePath) { Resolve-RepoPath -Path $UniversePath } else { Find-LatestUniverseCsv }
if (-not (Test-Path -LiteralPath $resolvedUniverse)) {
    throw "Universe CSV is missing: $resolvedUniverse"
}

$exchangeIds = @($Exchanges -split "," | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
if ($exchangeIds.Count -eq 0) {
    throw "At least one exchange is required."
}

$observedByBase = @{}
$observedMarkets = @()
$byMarket = if ($eventQuality) { $eventQuality.by_market } else { $null }
if ($byMarket) {
    foreach ($prop in $byMarket.PSObject.Properties) {
        $market = [string]$prop.Name
        $stats = $prop.Value
        $base = Get-BaseFromMarket -Market $market
        $sweeps = if ($null -ne $stats.total_sweeps) { [int]$stats.total_sweeps } else { 0 }
        $targetRate = if ($null -ne $stats.target_before_stop_rate) { [double]$stats.target_before_stop_rate } else { 0.0 }
        $falseRate = if ($null -ne $stats.false_sweep_rate) { [double]$stats.false_sweep_rate } else { 0.0 }
        if (-not $observedByBase.ContainsKey($base)) {
            $observedByBase[$base] = [ordered]@{
                base = $base
                total_sweeps = 0
                markets_observed = 0
                target_before_stop_weighted = 0.0
                false_sweep_weighted = 0.0
            }
        }
        $observedByBase[$base].total_sweeps += $sweeps
        $observedByBase[$base].markets_observed += 1
        $observedByBase[$base].target_before_stop_weighted += ($targetRate * [math]::Max(1, $sweeps))
        $observedByBase[$base].false_sweep_weighted += ($falseRate * [math]::Max(1, $sweeps))
        $observedMarkets += [ordered]@{
            market = $market
            base = $base
            total_sweeps = $sweeps
            target_before_stop_rate = Round-Nullable -Value $targetRate -Digits 6
            false_sweep_rate = Round-Nullable -Value $falseRate -Digits 6
        }
    }
}

$baseScores = @{}
foreach ($key in $observedByBase.Keys) {
    $item = $observedByBase[$key]
    $weight = [math]::Max(1, [int]$item.total_sweeps)
    $baseScores[$key] = [ordered]@{
        base = $key
        total_sweeps = [int]$item.total_sweeps
        markets_observed = [int]$item.markets_observed
        target_before_stop_rate = Round-Nullable -Value ([double]$item.target_before_stop_weighted / $weight) -Digits 6
        false_sweep_rate = Round-Nullable -Value ([double]$item.false_sweep_weighted / $weight) -Digits 6
    }
}

$universeRows = @(Import-Csv -LiteralPath $resolvedUniverse)
$rankedRows = @()
$position = 0
$seenUniverseSymbols = @{}
foreach ($row in $universeRows) {
    $position += 1
    $symbol = ([string]$row.symbol).Trim().ToUpperInvariant()
    if (-not $symbol) {
        continue
    }
    if ($seenUniverseSymbols.ContainsKey($symbol)) {
        continue
    }
    $seenUniverseSymbols[$symbol] = $true
    $score = if ($baseScores.ContainsKey($symbol)) { $baseScores[$symbol] } else { $null }
    $rankValue = 1000000000
    if ($row.PSObject.Properties.Name -contains "rank") {
        [void][int]::TryParse([string]$row.rank, [ref]$rankValue)
    }
    $rankedRows += [pscustomobject]@{
        row = $row
        symbol = $symbol
        original_position = $position
        original_rank = $rankValue
        observed_sweeps = if ($score) { [int]$score.total_sweeps } else { 0 }
        observed_markets = if ($score) { [int]$score.markets_observed } else { 0 }
        target_before_stop_rate = if ($score) { [double]$score.target_before_stop_rate } else { 0.0 }
        false_sweep_rate = if ($score) { [double]$score.false_sweep_rate } else { 0.0 }
    }
}

$denseRows = @(
    $rankedRows |
        Sort-Object `
            @{ Expression = { $_.observed_sweeps }; Descending = $true },
            @{ Expression = { $_.target_before_stop_rate }; Descending = $true },
            @{ Expression = { $_.false_sweep_rate }; Descending = $false },
            @{ Expression = { $_.original_rank }; Descending = $false },
            @{ Expression = { $_.original_position }; Descending = $false }
)

$resolvedOutputUniverse = Resolve-RepoPath -Path $OutputUniversePath
$outputUniverseDir = Split-Path -Parent $resolvedOutputUniverse
if ($outputUniverseDir -and (-not (Test-Path -LiteralPath $outputUniverseDir))) {
    New-Item -ItemType Directory -Path $outputUniverseDir | Out-Null
}
$denseRows | ForEach-Object { $_.row } | Export-Csv -LiteralPath $resolvedOutputUniverse -NoTypeInformation -Encoding UTF8

$sweepRatePerMarketHour = if ($dataSufficiency -and $dataSufficiency.observed_rates -and $null -ne $dataSufficiency.observed_rates.sweep_rate_per_market_hour) { [double]$dataSufficiency.observed_rates.sweep_rate_per_market_hour } else { 0.5 }
$targetSweeps = if ($dataSufficiency -and $dataSufficiency.targets -and $null -ne $dataSufficiency.targets.target_sweeps) { [int]$dataSufficiency.targets.target_sweeps } else { 1000 }
$options = @()
foreach ($marketCount in $MarketCounts) {
    if ($marketCount -le 0) {
        continue
    }
    $estimatedHours = $null
    if ($sweepRatePerMarketHour -gt 0) {
        $estimatedHours = $targetSweeps / ($sweepRatePerMarketHour * $marketCount)
    }
    $runHours = if ($estimatedHours) { Round-UpToStep -Value $estimatedHours -Step $RoundHoursTo } else { 0 }
    $options += [ordered]@{
        total_markets = [int]$marketCount
        exchange_count = [int]$exchangeIds.Count
        max_pairs_per_exchange = [int][math]::Ceiling($marketCount / [double]$exchangeIds.Count)
        estimated_hours_for_target_sweeps = Round-Nullable -Value $estimatedHours -Digits 3
        estimated_days_for_target_sweeps = if ($estimatedHours) { Round-Nullable -Value ($estimatedHours / 24.0) -Digits 3 } else { $null }
        run_hours_rounded = $runHours
        meets_target_max_hours = if ($estimatedHours) { ([double]$estimatedHours -le $TargetMaxHours) } else { $false }
        assumes_same_sweep_rate_per_market_hour = $true
    }
}

$selected = @($options | Where-Object { $_.meets_target_max_hours } | Sort-Object total_markets | Select-Object -First 1)
if ($selected.Count -eq 0) {
    $selected = @($options | Sort-Object estimated_hours_for_target_sweeps | Select-Object -First 1)
}
$selectedOption = if ($selected.Count -gt 0) { $selected[0] } else { $null }

$prioritySymbols = @(
    $denseRows |
        Select-Object -First 50 |
        ForEach-Object {
            [ordered]@{
                symbol = $_.symbol
                observed_sweeps = $_.observed_sweeps
                observed_markets = $_.observed_markets
                original_rank = $_.original_rank
            }
        }
)

$recommendedHours = if ($selectedOption) { [int]$selectedOption.run_hours_rounded } else { 0 }
$recommendedMaxPairs = if ($selectedOption) { [int]$selectedOption.max_pairs_per_exchange } else { 0 }
$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "dense_ws_collect_plan"
    research_only = $true
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    paper_forward_allowed = $false
    inputs = [ordered]@{
        event_quality_path = Resolve-RepoPath -Path $EventQualityPath
        data_sufficiency_path = Resolve-RepoPath -Path $DataSufficiencyPath
        source_universe_path = $resolvedUniverse
    }
    dense_universe_output = $resolvedOutputUniverse
    target = [ordered]@{
        target_sweeps = $targetSweeps
        target_max_hours = $TargetMaxHours
        round_hours_to = $RoundHoursTo
        exchanges = @($exchangeIds)
    }
    observed_density = [ordered]@{
        observed_hours = $dataSufficiency.current.observed_hours
        observed_markets = $dataSufficiency.current.market_count
        total_sweeps = $dataSufficiency.current.total_sweeps
        sweep_rate_per_market_hour = Round-Nullable -Value $sweepRatePerMarketHour -Digits 8
        top_markets = @($observedMarkets | Sort-Object @{ Expression = { $_.total_sweeps }; Descending = $true } | Select-Object -First 20)
    }
    options = @($options)
    selected_option = $selectedOption
    priority_symbols = @($prioritySymbols)
    recommended_wrapper_args = [ordered]@{
        hours = $recommendedHours
        max_pairs_per_exchange = $recommendedMaxPairs
        max_symbols = 300
        universe_path = $resolvedOutputUniverse
    }
    recommended_planonly_command = if ($recommendedHours -gt 0 -and $recommendedMaxPairs -gt 0) {
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\tools\start_ws_collect_visible.ps1`" -Hours $recommendedHours -MaxPairsPerExchange $recommendedMaxPairs -UniversePath `"$resolvedOutputUniverse`" -PlanOnly"
    } else {
        $null
    }
    recommended_command_after_explicit_approval = if ($recommendedHours -gt 0 -and $recommendedMaxPairs -gt 0) {
        "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\tools\start_ws_collect_visible.ps1`" -Hours $recommendedHours -MaxPairsPerExchange $recommendedMaxPairs -UniversePath `"$resolvedOutputUniverse`" -ConfirmedLongRun"
    } else {
        $null
    }
    verdict = [ordered]@{
        another_blind_6h_collect_rejected = $true
        reason = "Current event density requires sizing by market-hours; use the dense universe and selected option before requesting a visible long run."
        requires_explicit_user_approval_for_actual_collect = $true
        no_live_orders = $true
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
    Write-Host "dense WS collect plan" -ForegroundColor Cyan
    Write-Host "Dense universe: $resolvedOutputUniverse"
    Write-Host "Selected markets: $($selectedOption.total_markets); max pairs/exchange: $recommendedMaxPairs; run hours: $recommendedHours"
    Write-Host "PlanOnly: $($result.recommended_planonly_command)"
    Write-Host "Actual after explicit approval: $($result.recommended_command_after_explicit_approval)"
}
