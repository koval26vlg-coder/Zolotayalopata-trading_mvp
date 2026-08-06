param(
    [string]$OutputPath = "",
    [int]$MaxRowsPerJsonl = 200000,
    [int]$MaxRowsPerLargeJsonl = 5000,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$analysisDir = Join-Path $repoRoot "exports\trading-mvp\analysis"
$listingHistoryDir = Join-Path $repoRoot "exports\trading-mvp\listing-history"
$normalizedDir = Join-Path $repoRoot "exports\trading-mvp\normalized"
$backtestDir = Join-Path $repoRoot "exports\trading-mvp\backtests"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $analysisDir "slow_liquidity_data_availability_preflight_$timestamp.json"
}

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )

    if ($Object -is [System.Collections.IDictionary]) {
        $Object[$Name] = $Value
        return
    }

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
    $Payload | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }

    Write-Host "Slow Liquidity Data Availability Preflight" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $OutputPath"
    Write-Host "Gate updated: $($Payload.gate_updated)"
    Write-Host ""
    Write-Host "Failed checks" -ForegroundColor Yellow
    foreach ($check in @($Payload.data_sufficiency_checks)) {
        if ($check.status -ne "pass") {
            Write-Host "  - $($check.name): $($check.status) - $($check.observed)"
        }
    }
}

function Invoke-JsonScript {
    param([string]$Path)

    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path -Json
    if ($LASTEXITCODE -ne 0) {
        throw "Script failed with exit code ${LASTEXITCODE}: $Path"
    }
    return ($raw | ConvertFrom-Json)
}

function Add-ToSet {
    param(
        [Parameter(Mandatory = $true)]$Set,
        $Value
    )

    if ($null -ne $Value) {
        $text = [string]$Value
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            [void]$Set.Add($text)
        }
    }
}

function To-DoubleOrNull {
    param($Value)

    if ($null -eq $Value) { return $null }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    $parsed = 0.0
    if ([double]::TryParse($text, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function To-IsoOrNull {
    param($EpochSeconds)

    $ts = To-DoubleOrNull -Value $EpochSeconds
    if ($null -eq $ts) { return $null }
    if ($ts -gt 1000000000000) { $ts = $ts / 1000.0 }
    if ($ts -gt 10000000000) { $ts = $ts / 1000.0 }
    try {
        return [DateTimeOffset]::FromUnixTimeSeconds([int64][Math]::Floor($ts)).UtcDateTime.ToString("o")
    } catch {
        return $null
    }
}

function Get-RowTimestamp {
    param($Row)

    foreach ($field in @("candle_ts", "timestamp", "timestamp_ms", "recv_ts", "exchange_ts", "ts", "time", "open_time", "open_time_ms", "event_ts")) {
        if ($Row.PSObject.Properties.Name -contains $field) {
            $value = To-DoubleOrNull -Value $Row.$field
            if ($null -ne $value) {
                if ($value -gt 1000000000000) { $value = $value / 1000.0 }
                if ($value -gt 10000000000) { $value = $value / 1000.0 }
                return $value
            }
        }
    }
    return $null
}

function Test-AnyKey {
    param(
        [Parameter(Mandatory = $true)]$Keys,
        [Parameter(Mandatory = $true)][string[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        if ($Keys.Contains($candidate)) { return $true }
    }
    return $false
}

function Get-JsonlSummary {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Kind,
        [int]$MaxRows
    )

    $file = Get-Item -LiteralPath $Path
    $schema = New-Object 'System.Collections.Generic.HashSet[string]'
    $exchanges = New-Object 'System.Collections.Generic.HashSet[string]'
    $symbols = New-Object 'System.Collections.Generic.HashSet[string]'
    $bases = New-Object 'System.Collections.Generic.HashSet[string]'
    $quotes = New-Object 'System.Collections.Generic.HashSet[string]'
    $granularities = New-Object 'System.Collections.Generic.HashSet[string]'
    $eventIds = New-Object 'System.Collections.Generic.HashSet[string]'
    $eventKinds = New-Object 'System.Collections.Generic.HashSet[string]'
    $eventMinTs = @{}
    $eventMaxTs = @{}
    $statusCounts = @{}
    $parsedRows = 0
    $malformedRows = 0
    $positiveQuoteVolumeRows = 0
    $positiveVolumeRows = 0
    $minTs = $null
    $maxTs = $null
    $firstRow = $null

    foreach ($line in [System.IO.File]::ReadLines($Path)) {
        if ($parsedRows -ge $MaxRows) { break }
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $row = $line | ConvertFrom-Json
        } catch {
            $malformedRows += 1
            continue
        }
        $parsedRows += 1
        if ($null -eq $firstRow) { $firstRow = $row }

        foreach ($prop in $row.PSObject.Properties) {
            [void]$schema.Add($prop.Name)
        }
        Add-ToSet -Set $exchanges -Value $row.exchange
        Add-ToSet -Set $symbols -Value $row.symbol
        Add-ToSet -Set $bases -Value $row.base
        Add-ToSet -Set $quotes -Value $row.quote
        Add-ToSet -Set $granularities -Value $row.granularity
        Add-ToSet -Set $granularities -Value $row.timeframe
        Add-ToSet -Set $eventIds -Value $row.event_id
        Add-ToSet -Set $eventKinds -Value $row.event_kind

        if ($row.PSObject.Properties.Name -contains "data_status") {
            $status = [string]$row.data_status
            if (-not $statusCounts.ContainsKey($status)) { $statusCounts[$status] = 0 }
            $statusCounts[$status] += 1
        }

        $quoteVolume = To-DoubleOrNull -Value $row.quote_volume
        if ($null -ne $quoteVolume -and $quoteVolume -gt 0) { $positiveQuoteVolumeRows += 1 }
        $volume = To-DoubleOrNull -Value $row.volume
        if ($null -ne $volume -and $volume -gt 0) { $positiveVolumeRows += 1 }

        $ts = Get-RowTimestamp -Row $row
        if ($null -ne $ts) {
            if ($null -eq $minTs -or $ts -lt $minTs) { $minTs = $ts }
            if ($null -eq $maxTs -or $ts -gt $maxTs) { $maxTs = $ts }

            $eventKey = $null
            if ($row.PSObject.Properties.Name -contains "event_id") {
                $eventKey = [string]$row.event_id
            }
            if ([string]::IsNullOrWhiteSpace($eventKey) -and $row.PSObject.Properties.Name -contains "symbol") {
                $eventKey = [string]$row.symbol
            }
            if (-not [string]::IsNullOrWhiteSpace($eventKey)) {
                if (-not $eventMinTs.ContainsKey($eventKey) -or $ts -lt [double]$eventMinTs[$eventKey]) {
                    $eventMinTs[$eventKey] = $ts
                }
                if (-not $eventMaxTs.ContainsKey($eventKey) -or $ts -gt [double]$eventMaxTs[$eventKey]) {
                    $eventMaxTs[$eventKey] = $ts
                }
            }
        }
    }

    $keys = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($key in $schema) { [void]$keys.Add($key) }
    $hasOhlcv = (
        (Test-AnyKey -Keys $keys -Candidates @("open", "o")) -and
        (Test-AnyKey -Keys $keys -Candidates @("high", "h")) -and
        (Test-AnyKey -Keys $keys -Candidates @("low", "l")) -and
        (Test-AnyKey -Keys $keys -Candidates @("close", "c")) -and
        (Test-AnyKey -Keys $keys -Candidates @("volume", "v"))
    )
    $hasSpread = Test-AnyKey -Keys $keys -Candidates @("spread_bps", "best_bid", "best_ask", "bid", "ask", "bids", "asks")
    $hasLiquidity = Test-AnyKey -Keys $keys -Candidates @("quote_volume", "trade_count", "trade_count_if_available", "notional", "volume", "bid_qty", "ask_qty", "bids", "asks")
    $hasTopOfBook = Test-AnyKey -Keys $keys -Candidates @("best_bid", "best_ask", "bid", "ask", "bids", "asks")

    $spanSec = if ($null -ne $minTs -and $null -ne $maxTs) { [Math]::Max(0.0, $maxTs - $minTs) } else { $null }
    $eventSpanHours = @()
    foreach ($eventKey in $eventMinTs.Keys) {
        if ($eventMaxTs.ContainsKey($eventKey)) {
            $eventSpanHours += ([Math]::Max(0.0, [double]$eventMaxTs[$eventKey] - [double]$eventMinTs[$eventKey]) / 3600.0)
        }
    }
    $maxEventSpanHours = if ($eventSpanHours.Count -gt 0) { ($eventSpanHours | Measure-Object -Maximum).Maximum } else { $null }
    $avgEventSpanHours = if ($eventSpanHours.Count -gt 0) { ($eventSpanHours | Measure-Object -Average).Average } else { $null }
    $largeFile = $file.Length -gt 200MB

    return [ordered]@{
        path = $Path
        kind = $Kind
        exists = $true
        bytes = $file.Length
        last_write = $file.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz")
        parsed_rows = $parsedRows
        line_count = $parsedRows
        line_count_mode = if ($largeFile) { "sampled_large_file" } else { "full_or_sample_cap" }
        truncated = $parsedRows -ge $MaxRows
        malformed_rows = $malformedRows
        schema_keys = @($schema | Sort-Object)
        exchange_count = $exchanges.Count
        exchanges = @($exchanges | Sort-Object)
        symbol_count = $symbols.Count
        symbols_sample = @($symbols | Sort-Object | Select-Object -First 20)
        base_count = $bases.Count
        bases_sample = @($bases | Sort-Object | Select-Object -First 20)
        quote_count = $quotes.Count
        quotes = @($quotes | Sort-Object)
        unique_event_count = $eventIds.Count
        event_kind_count = $eventKinds.Count
        event_kinds = @($eventKinds | Sort-Object)
        granularities = @($granularities | Sort-Object)
        min_ts = $minTs
        max_ts = $maxTs
        min_iso = To-IsoOrNull -EpochSeconds $minTs
        max_iso = To-IsoOrNull -EpochSeconds $maxTs
        span_sec = $spanSec
        span_hours = if ($null -ne $spanSec) { [Math]::Round($spanSec / 3600.0, 3) } else { $null }
        max_event_span_hours = if ($null -ne $maxEventSpanHours) { [Math]::Round([double]$maxEventSpanHours, 3) } else { $null }
        avg_event_span_hours = if ($null -ne $avgEventSpanHours) { [Math]::Round([double]$avgEventSpanHours, 3) } else { $null }
        has_ohlcv = $hasOhlcv
        has_spread_or_book = $hasSpread
        has_top_of_book = $hasTopOfBook
        has_liquidity_proxy = $hasLiquidity
        positive_quote_volume_rows = $positiveQuoteVolumeRows
        positive_volume_rows = $positiveVolumeRows
        positive_quote_volume_ratio = if ($parsedRows -gt 0) { [Math]::Round($positiveQuoteVolumeRows / [double]$parsedRows, 6) } else { $null }
        data_status_counts = $statusCounts
    }
}

function Get-MarketFilterSummary {
    param([Parameter(Mandatory = $true)][string]$Path)

    $file = Get-Item -LiteralPath $Path
    $doc = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    return [ordered]@{
        path = $Path
        kind = "market_filter_report"
        exists = $true
        bytes = $file.Length
        last_write = $file.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss zzz")
        accepted = [bool]$doc.accepted
        reasons = @($doc.reasons)
        source_duration_sec = $doc.source_duration_sec
        source_duration_hours = if ($doc.source_duration_sec) { [Math]::Round([double]$doc.source_duration_sec / 3600.0, 3) } else { $null }
        output_span_hours = if ($doc.metrics.output_span_hours) { [Math]::Round([double]$doc.metrics.output_span_hours, 3) } else { $null }
        input_exchanges = $doc.metrics.input_exchanges
        input_markets = $doc.metrics.input_markets
        accepted_markets = $doc.metrics.accepted_markets
        rejected_markets = $doc.metrics.rejected_markets
        output_rows = $doc.metrics.output_rows
        output_exchanges = $doc.metrics.output_exchanges
        output_event_kinds = $doc.metrics.output_event_kinds
        output_max_market_event_share = $doc.metrics.output_max_market_event_share
        required_event_kinds = @($doc.config.required_event_kinds)
        max_gap_sec = $doc.config.max_gap_sec
        markets_sample = @($doc.markets | Select-Object -First 12 market, exchange, symbol, rows, event_kinds, span_hours, max_gap_sec)
    }
}

function New-Check {
    param(
        [string]$Name,
        [bool]$Pass,
        [string]$Required,
        [string]$Observed,
        [string]$Risk
    )

    return [ordered]@{
        name = $Name
        status = if ($Pass) { "pass" } else { "fail" }
        required = $Required
        observed = $Observed
        risk = $Risk
    }
}

$gate = Invoke-JsonScript -Path $gateChecker
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_slow_liquidity_data_availability_preflight_planonly"
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
        gate_status = $gate.status
        reason = "Active run gate is $($gate.status); only status/resume handling is allowed."
        output_path = $OutputPath
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$selectedGate = [bool](
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_REGIME_BREAKOUT_RETEST_PLANONLY*") -or
    ([string]$gate.next_goal_decision -like "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT*") -or
    (
        $gate.strategy_branch_status -and
        [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest"
    )
)
if (-not $selectedGate) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "trading_slow_liquidity_data_availability_preflight_planonly"
        decision = "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_NOT_SELECTED"
        selected_branch = "slow_liquidity_regime_breakout_retest"
        would_start = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        gate_status = $gate.status
        gate_next_goal_decision = $gate.next_goal_decision
        reason = "Gate has not selected slow_liquidity_regime_breakout_retest data availability preflight."
        output_path = $OutputPath
        gate_updated = $false
    }
    Save-Result -Payload $blocked
    exit 0
}

$listingFiles = @()
if (Test-Path -LiteralPath $listingHistoryDir) {
    $listingFiles = @(Get-ChildItem -LiteralPath $listingHistoryDir -Recurse -File -Filter "ohlcv.jsonl" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 8)
}
$wsFiles = @()
if (Test-Path -LiteralPath $normalizedDir) {
    $wsFiles = @(Get-ChildItem -LiteralPath $normalizedDir -File -Filter "*.jsonl" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^(ws_|ws_market_|ws_normalized_)" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 8)
}
$marketFilterFiles = @()
if (Test-Path -LiteralPath $backtestDir) {
    $marketFilterFiles = @(Get-ChildItem -LiteralPath $backtestDir -File -Filter "ws_market_filter*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "manifest" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 6)
}

$listingSummaries = @()
foreach ($file in $listingFiles) {
    $listingSummaries += (Get-JsonlSummary -Path $file.FullName -Kind "listing_history_ohlcv" -MaxRows $MaxRowsPerJsonl)
}
$wsSummaries = @()
foreach ($file in $wsFiles) {
    $rowCap = if ($file.Length -gt 200MB) { $MaxRowsPerLargeJsonl } else { $MaxRowsPerJsonl }
    $wsSummaries += (Get-JsonlSummary -Path $file.FullName -Kind "normalized_ws_sample" -MaxRows $rowCap)
}
$marketFilterSummaries = @()
foreach ($file in $marketFilterFiles) {
    $marketFilterSummaries += (Get-MarketFilterSummary -Path $file.FullName)
}

$latestOhlcv = @($listingSummaries | Sort-Object last_write -Descending | Select-Object -First 1)
$latestMarketFilter = @($marketFilterSummaries | Sort-Object last_write -Descending | Select-Object -First 1)

$ohlcvGranularities = @()
$ohlcvExchangeCount = 0
$ohlcvBaseCount = 0
$ohlcvEventCount = 0
$ohlcvRows = 0
$ohlcvSpanHours = 0.0
$ohlcvMaxEventSpanHours = 0.0
$positiveQuoteVolumeRatio = $null
if ($latestOhlcv.Count -gt 0) {
    $ohlcvGranularities = @($latestOhlcv[0].granularities)
    $ohlcvExchangeCount = [int]$latestOhlcv[0].exchange_count
    $ohlcvBaseCount = [int]$latestOhlcv[0].base_count
    $ohlcvEventCount = [int]$latestOhlcv[0].unique_event_count
    $ohlcvRows = [int]$latestOhlcv[0].parsed_rows
    $ohlcvSpanHours = if ($latestOhlcv[0].span_hours) { [double]$latestOhlcv[0].span_hours } else { 0.0 }
    $ohlcvMaxEventSpanHours = if ($latestOhlcv[0].max_event_span_hours) { [double]$latestOhlcv[0].max_event_span_hours } else { 0.0 }
    $positiveQuoteVolumeRatio = $latestOhlcv[0].positive_quote_volume_ratio
}

$wsHasAcceptedMarketFilter = [bool]($latestMarketFilter.Count -gt 0 -and [bool]$latestMarketFilter[0].accepted)
$wsSpanHours = if ($latestMarketFilter.Count -gt 0 -and $latestMarketFilter[0].output_span_hours) { [double]$latestMarketFilter[0].output_span_hours } else { 0.0 }
$wsMarkets = if ($latestMarketFilter.Count -gt 0 -and $latestMarketFilter[0].accepted_markets) { [int]$latestMarketFilter[0].accepted_markets } else { 0 }
$wsExchanges = if ($latestMarketFilter.Count -gt 0 -and $latestMarketFilter[0].output_exchanges) { [int]$latestMarketFilter[0].output_exchanges } else { 0 }
$has15m = $ohlcvGranularities -contains "15m"
$has1h = $ohlcvGranularities -contains "1h"
$has4h = $ohlcvGranularities -contains "4h"
$hasRequiredTimeframes = $has15m -and $has1h -and $has4h
$hasMultiWeekOhlcv = $ohlcvMaxEventSpanHours -ge (24.0 * 14.0)
$hasEnoughEvents = $ohlcvEventCount -ge 200
$hasEnoughBases = $ohlcvBaseCount -ge 10
$hasEnoughExchanges = $ohlcvExchangeCount -ge 2
$hasLiquidityProxy = ($positiveQuoteVolumeRatio -ne $null -and [double]$positiveQuoteVolumeRatio -ge 0.50)
$hasSpreadLayer = $wsHasAcceptedMarketFilter -and $wsExchanges -ge 2 -and $wsMarkets -ge 10 -and $wsSpanHours -ge 24.0

$checks = @(
    (New-Check -Name "multi_week_ohlcv" -Pass $hasMultiWeekOhlcv -Required ">= 14 days OHLCV history per market/event before replay" -Observed "max_event_span_hours=$([Math]::Round($ohlcvMaxEventSpanHours, 2)); aggregate_disjoint_span_hours=$([Math]::Round($ohlcvSpanHours, 2))" -Risk "Disjoint listing/event windows create overfit and no reliable walk-forward."),
    (New-Check -Name "required_timeframes" -Pass $hasRequiredTimeframes -Required "15m, 1h and 4h OHLCV present" -Observed ("granularities=" + (($ohlcvGranularities -join ",") -replace "^$", "none")) -Risk "Slow-regime signal cannot be validated across intended horizons."),
    (New-Check -Name "independent_events" -Pass $hasEnoughEvents -Required ">= 200 independent regime/retest events" -Observed "$ohlcvEventCount event_id values in latest OHLCV artifact" -Risk "Small sample cannot support OOS/walk-forward/stress claims."),
    (New-Check -Name "market_diversity" -Pass $hasEnoughBases -Required ">= 10 bases" -Observed "$ohlcvBaseCount bases in latest OHLCV artifact" -Risk "Single-market cherry-picking risk."),
    (New-Check -Name "venue_diversity" -Pass $hasEnoughExchanges -Required ">= 2 venues where possible" -Observed "$ohlcvExchangeCount exchanges in latest OHLCV artifact" -Risk "Venue-specific data quirks can masquerade as edge."),
    (New-Check -Name "liquidity_proxy" -Pass $hasLiquidityProxy -Required "quote_volume/volume usable on majority of OHLCV rows" -Observed "positive_quote_volume_ratio=$positiveQuoteVolumeRatio; rows=$ohlcvRows" -Risk "If volume is zero/missing, liquidity filter and cost model are unreliable."),
    (New-Check -Name "spread_or_book_layer" -Pass $hasSpreadLayer -Required "accepted top-of-book/spread proxy across >=2 venues and >=10 markets" -Observed "accepted=$wsHasAcceptedMarketFilter; exchanges=$wsExchanges; markets=$wsMarkets; span_hours=$([Math]::Round($wsSpanHours, 2))" -Risk "Execution buffer must be grounded in spread/top-of-book data, not guessed."),
    (New-Check -Name "base_fee_cost_hurdle" -Pass $true -Required "base/VIP0/no-volume cost hurdle retained" -Observed "minimum gross hurdle remains 249 bps from scaffold" -Risk "Winrate without net expectancy after base fees is not useful.")
)

$failedChecks = @($checks | Where-Object { $_.status -ne "pass" })
$decision = if ($failedChecks.Count -eq 0) {
    "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY"
} else {
    "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_HISTORY_PLAN"
}
$strategyAccepted = $false
$replayAllowed = $false

$nextStep = if ($decision -eq "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY") {
    "Define fixed v0 slow-liquidity signal PlanOnly before any replay. Keep replay/grid/live/API/paper-forward blocked until the fixed signal contract is written and explicitly gate-approved."
} else {
    "Build slow-liquidity history data plan/approval packet: public OHLCV 15m/1h/4h multi-week coverage plus spread/liquidity proxy. Do not start collect/replay/grid/live/API/paper-forward without explicit approval."
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_slow_liquidity_data_availability_preflight_planonly"
    decision = $decision
    selected_branch = "slow_liquidity_regime_breakout_retest"
    would_start = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    collect_allowed_now = $false
    replay_allowed_now = $replayAllowed
    grid_allowed_now = $false
    paper_forward_allowed = $false
    strategy_accepted = $strategyAccepted
    research_only = $true
    public_data_only = $true
    gate_status = $gate.status
    gate_next_goal_decision_before = $gate.next_goal_decision
    data_sufficiency_checks = $checks
    failed_check_count = $failedChecks.Count
    readiness_summary = [ordered]@{
        latest_ohlcv_rows = $ohlcvRows
        latest_ohlcv_exchanges = $ohlcvExchangeCount
        latest_ohlcv_bases = $ohlcvBaseCount
        latest_ohlcv_event_ids = $ohlcvEventCount
        latest_ohlcv_granularities = $ohlcvGranularities
        latest_ohlcv_span_hours = [Math]::Round($ohlcvSpanHours, 3)
        latest_ohlcv_max_event_span_hours = [Math]::Round($ohlcvMaxEventSpanHours, 3)
        latest_ohlcv_positive_quote_volume_ratio = $positiveQuoteVolumeRatio
        latest_market_filter_accepted = $wsHasAcceptedMarketFilter
        latest_market_filter_exchanges = $wsExchanges
        latest_market_filter_markets = $wsMarkets
        latest_market_filter_span_hours = [Math]::Round($wsSpanHours, 3)
    }
    artifacts = [ordered]@{
        listing_history_ohlcv = $listingSummaries
        normalized_ws_samples = $wsSummaries
        market_filter_reports = $marketFilterSummaries
    }
    requirements = [ordered]@{
        ohlcv_timeframes = @("15m", "1h", "4h")
        min_ohlcv_span_days = 14
        preferred_ohlcv_span_days = 56
        min_independent_events = 200
        min_bases = 10
        min_spread_proxy_venues = 2
        cost_policy = "base/VIP0/no-volume; minimum gross move hurdle 249 bps before signal acceptance"
        validation_gates = @("chronological OOS", "walk_forward", "stress", "economics", "market_diversity", "drawdown")
    }
    history_plan_if_rejected = [ordered]@{
        objective = "collect_or_prepare_public_history_only_after_explicit_approval"
        minimum = "15m/1h/4h OHLCV for >=14 days and >=200 independent regime/retest events"
        preferred = "8+ weeks OHLCV, 30+ bases, spread/top-of-book sampling or conservative spread model"
        must_remain_visible = $true
        requires_explicit_user_approval_for_actual_collect = $true
        blocked_until_then = @("replay", "grid_search", "paper_forward", "live_orders", "api_keys", "leverage_or_margin")
    }
    next_valid_moves = @(
        $nextStep,
        "If history is approved later, run only a visible collector/monitor and write PID/manifest/status metadata.",
        "Do not optimize for win rate before net expectancy, OOS, walk-forward, stress and economics gates pass."
    )
    commands = [ordered]@{
        rerun_this_preflight = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
    }
    output_path = $OutputPath
    gate_updated = $false
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $verdict = if ($decision -eq "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_ACCEPTED_READY_FOR_FIXED_SIGNAL_PLANONLY") {
        "data_availability_preflight_accepted_ready_for_fixed_signal_planonly"
    } else {
        "data_availability_preflight_rejected_needs_history_plan"
    }
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "slow_liquidity data availability preflight completed. failed_checks=$($failedChecks.Count); latest_ohlcv_rows=$ohlcvRows; granularities=$($ohlcvGranularities -join ','); ws_market_filter_accepted=$wsHasAcceptedMarketFilter."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        failed_check_count = $failedChecks.Count
        next_step_required = if ($failedChecks.Count -eq 0) { "define_fixed_v0_signal_planonly" } else { "build_history_data_plan_approval_packet_planonly" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_data_availability_preflight_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_data_availability_preflight_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_data_availability_preflight_decision" -Value $decision
    $gateDoc | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    Set-JsonProperty -Object $result -Name "gate_updated" -Value $true
}

Save-Result -Payload $result
