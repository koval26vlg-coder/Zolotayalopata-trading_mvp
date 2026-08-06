param(
    [string]$OutputPath = "",
    [int]$HistoryDays = 56,
    [string]$Timeframes = "15m,1h,4h",
    [int]$TargetBases = 50,
    [int]$MinIndependentEvents = 200,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$analysisDir = Join-Path $repoRoot "exports\trading-mvp\analysis"
$collectorModule = Join-Path $repoRoot "trading_mvp\src\listing_event_history_collector.py"
$universePath = Join-Path $repoRoot "coins_not_on_binance_full_2026-05-29.csv"
$approvalPhrase = "подтверждаю visible slow-liquidity OHLCV history collect"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $analysisDir "slow_liquidity_history_data_plan_$timestamp.json"
}

function Resolve-RepoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

$OutputPath = Resolve-RepoPath -Path $OutputPath

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

function Has-Property {
    param(
        [object]$Object,
        [string]$Name
    )
    return ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name)
}

function Invoke-JsonScript {
    param(
        [string]$Path,
        [string[]]$Arguments = @()
    )

    $raw = & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Script failed with exit code ${LASTEXITCODE}: $Path"
    }
    return ($raw | ConvertFrom-Json)
}

function Read-JsonFileOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
}

function Add-Check {
    param(
        [System.Collections.Generic.List[object]]$Checks,
        [string]$Name,
        [string]$Status,
        [string]$Evidence,
        [string]$Action = ""
    )

    $Checks.Add([ordered]@{
        name = $Name
        status = $Status
        evidence = $Evidence
        action = $Action
    }) | Out-Null
}

function Get-IntervalSeconds {
    param([string]$Timeframe)
    switch ($Timeframe) {
        "1m" { return 60 }
        "5m" { return 300 }
        "15m" { return 900 }
        "30m" { return 1800 }
        "1h" { return 3600 }
        "4h" { return 14400 }
        "1d" { return 86400 }
        default { return 0 }
    }
}

function Get-UniverseSummary {
    param([string]$Path)

    $summary = [ordered]@{
        path = $Path
        exists = $false
        row_count = 0
        symbol_count = 0
        symbols_sample = @()
        rank_min = $null
        rank_max = $null
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]$summary
    }

    $rows = @(Import-Csv -LiteralPath $Path)
    $symbols = @($rows | ForEach-Object { [string]$_.symbol } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
    $ranks = @($rows | ForEach-Object {
        $rankValue = 0
        if ([int]::TryParse([string]$_.rank, [ref]$rankValue)) {
            $rankValue
        }
    })

    $summary.exists = $true
    $summary.row_count = $rows.Count
    $summary.symbol_count = $symbols.Count
    $summary.symbols_sample = @($symbols | Select-Object -First 20)
    if ($ranks.Count -gt 0) {
        $summary.rank_min = ($ranks | Measure-Object -Minimum).Minimum
        $summary.rank_max = ($ranks | Measure-Object -Maximum).Maximum
    }

    return [pscustomobject]$summary
}

function Get-CollectorCapability {
    param([string]$Path)

    $capability = [ordered]@{
        path = $Path
        exists = $false
        exchange_adapters = [ordered]@{
            mexc = $false
            gateio = $false
            bitget = $false
        }
        timeframe_markers = [ordered]@{
            "15m" = $false
            "1h" = $false
            "4h" = $false
        }
        reusable_for_public_ohlcv = $false
        continuous_history_wrapper_exists = $false
        visible_slow_liquidity_wrapper_exists = $false
        collector_implementation_required = $true
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]$capability
    }

    $text = Get-Content -Raw -LiteralPath $Path
    $capability.exists = $true
    $capability["exchange_adapters"]["mexc"] = [bool]($text -match "MexcSpotOhlcvClient")
    $capability["exchange_adapters"]["gateio"] = [bool]($text -match "GateSpotOhlcvClient")
    $capability["exchange_adapters"]["bitget"] = [bool]($text -match "BitgetSpotOhlcvClient")
    $capability["timeframe_markers"]["15m"] = [bool]($text -match '"15m"|''15m''|15m')
    $capability["timeframe_markers"]["1h"] = [bool]($text -match '"1h"|''1h''|1h')
    $capability["timeframe_markers"]["4h"] = [bool]($text -match '"4h"|''4h''|4h')
    $capability.reusable_for_public_ohlcv = [bool](
        $capability["exchange_adapters"]["mexc"] -and
        $capability["exchange_adapters"]["gateio"] -and
        $capability["exchange_adapters"]["bitget"] -and
        $capability["timeframe_markers"]["15m"] -and
        $capability["timeframe_markers"]["1h"] -and
        $capability["timeframe_markers"]["4h"]
    )

    $continuousWrapper = Join-Path $repoRoot "tools\trading_slow_liquidity_history_collect_plan.ps1"
    $visibleWrapper = Join-Path $repoRoot "tools\start_slow_liquidity_history_collect_visible.ps1"
    $capability.continuous_history_wrapper_exists = Test-Path -LiteralPath $continuousWrapper
    $capability.visible_slow_liquidity_wrapper_exists = Test-Path -LiteralPath $visibleWrapper
    $capability.collector_implementation_required = -not ($capability.continuous_history_wrapper_exists -and $capability.visible_slow_liquidity_wrapper_exists)

    return [pscustomobject]$capability
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

    Write-Host "Slow Liquidity History Data Plan" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Output: $OutputPath"
    Write-Host "Gate updated: $($Payload.gate_updated)"
    Write-Host "Actual collect allowed now: $($Payload.collect_allowed_now)"
    Write-Host "Replay allowed now: $($Payload.replay_allowed_now)"
}

$checks = [System.Collections.Generic.List[object]]::new()
$gate = $null

try {
    $gate = Invoke-JsonScript -Path $gateChecker -Arguments @("-Json")
    if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
        $blocked = [ordered]@{
            generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
            mode = "trading_slow_liquidity_history_data_plan_planonly"
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
            research_only = $true
            public_data_only = $true
            requires_explicit_user_approval_for_actual_collect = $true
            actual_collect_command_emitted = $false
            explicit_approval_phrase = $approvalPhrase
            gate_status = $gate.status
            reason = "Active run gate is $($gate.status); only status/resume handling is allowed."
            output_path = $OutputPath
            gate_updated = $false
        }
        Save-Result -Payload $blocked
        exit 0
    }
    Add-Check $checks "active_run_gate" "pass" "Gate status=$($gate.status); next_goal_decision=$($gate.next_goal_decision)." ""
} catch {
    Add-Check $checks "active_run_gate" "fail" "Could not read active-run gate: $($_.Exception.Message)" "Fix check_active_run_gate.ps1 before planning history data."
}

$timeframeList = @($Timeframes.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$requiredTimeframes = @("15m", "1h", "4h")
$missingRequiredTimeframes = @($requiredTimeframes | Where-Object { $timeframeList -notcontains $_ })
$unsupportedTimeframes = @($timeframeList | Where-Object { (Get-IntervalSeconds -Timeframe $_) -le 0 })
$targetExchanges = @("mexc", "gateio", "bitget")
$preflightPath = ""
if ($gate -and (Has-Property $gate "last_slow_liquidity_data_availability_preflight_output_path")) {
    $preflightPath = [string]$gate.last_slow_liquidity_data_availability_preflight_output_path
}
if ([string]::IsNullOrWhiteSpace($preflightPath)) {
    $latestPreflight = Get-ChildItem -LiteralPath $analysisDir -Filter "slow_liquidity_data_availability_preflight_*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestPreflight) {
        $preflightPath = $latestPreflight.FullName
    }
}

$preflight = Read-JsonFileOrNull -Path $preflightPath
$universe = Get-UniverseSummary -Path $universePath
$collectorCapability = Get-CollectorCapability -Path $collectorModule

$gateAllowsPlan = $false
if ($gate) {
    $gateAllowsPlan = [bool](
        ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_DATA_AVAILABILITY_PREFLIGHT_REJECTED_NEEDS_HISTORY_PLAN") -or
        ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL") -or
        (
            $gate.strategy_branch_status -and
            [string]$gate.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
            [string]$gate.strategy_branch_status.verdict -in @(
                "data_availability_preflight_rejected_needs_history_plan",
                "history_data_plan_ready_awaiting_explicit_approval"
            )
        )
    )
}

if ($gateAllowsPlan) {
    Add-Check $checks "gate_slow_liquidity_history_plan_contract" "pass" "Gate selects slow_liquidity history planning; next_goal_decision=$($gate.next_goal_decision)." ""
} else {
    Add-Check $checks "gate_slow_liquidity_history_plan_contract" "fail" "Gate does not currently select slow-liquidity history planning." "Do not build/start history collect outside the selected branch."
}

if ($preflight) {
    $failedPreflight = @($preflight.data_sufficiency_checks | Where-Object { [string]$_.status -ne "pass" })
    Add-Check $checks "preflight_artifact_readback" "pass" "Read preflight=$preflightPath; decision=$($preflight.decision); failed_checks=$($failedPreflight.Count)." ""
} else {
    $failedPreflight = @()
    Add-Check $checks "preflight_artifact_readback" "fail" "Missing slow-liquidity data availability preflight artifact." "Run data availability preflight before history planning."
}

if ($missingRequiredTimeframes.Count -eq 0 -and $unsupportedTimeframes.Count -eq 0 -and $HistoryDays -ge 14 -and $TargetBases -ge 10 -and $MinIndependentEvents -ge 200) {
    Add-Check $checks "history_scope_contract" "pass" "HistoryDays=$HistoryDays; Timeframes=$($timeframeList -join ','); TargetBases=$TargetBases; MinIndependentEvents=$MinIndependentEvents." ""
} else {
    $scopeIssues = @()
    if ($missingRequiredTimeframes.Count -gt 0) { $scopeIssues += "missing_timeframes=$($missingRequiredTimeframes -join ',')" }
    if ($unsupportedTimeframes.Count -gt 0) { $scopeIssues += "unsupported_timeframes=$($unsupportedTimeframes -join ',')" }
    if ($HistoryDays -lt 14) { $scopeIssues += "HistoryDays=$HistoryDays" }
    if ($TargetBases -lt 10) { $scopeIssues += "TargetBases=$TargetBases" }
    if ($MinIndependentEvents -lt 200) { $scopeIssues += "MinIndependentEvents=$MinIndependentEvents" }
    Add-Check $checks "history_scope_contract" "fail" ($scopeIssues -join "; ") "Use at least 14 days, 15m/1h/4h, >=10 bases and >=200 event candidates."
}

if ($universe.exists -and $universe.symbol_count -ge $TargetBases) {
    Add-Check $checks "non_binance_universe_source" "pass" "Universe=$($universe.path); symbols=$($universe.symbol_count); target_bases=$TargetBases." ""
} else {
    Add-Check $checks "non_binance_universe_source" "fail" "Universe source missing or too small: $($universe.path); symbols=$($universe.symbol_count)." "Provide/refresh non-Binance spot universe before collect planning."
}

if ($collectorCapability.reusable_for_public_ohlcv) {
    Add-Check $checks "public_ohlcv_endpoint_adapters" "pass" "Existing Python collector has MEXC/Gate/Bitget public OHLCV adapters and 15m/1h/4h markers." ""
} elseif ($collectorCapability.exchange_adapters.mexc -and $collectorCapability.exchange_adapters.gateio -and $collectorCapability.exchange_adapters.bitget) {
    Add-Check $checks "public_ohlcv_endpoint_adapters" "warn" "Existing Python collector has MEXC/Gate/Bitget public OHLCV adapters, but slow-liquidity 15m/4h mappings/wrapper still need implementation." "Add 15m/4h interval mappings and a continuous visible history wrapper before actual collect."
} else {
    Add-Check $checks "public_ohlcv_endpoint_adapters" "fail" "Existing collector adapters/timeframes are insufficient." "Implement adapters before actual history collect."
}

if ($collectorCapability.collector_implementation_required) {
    Add-Check $checks "visible_history_wrapper" "warn" "Continuous slow-liquidity history wrapper is not implemented yet; approval must not directly start collect." "After explicit approval, implement PlanOnly/visible wrapper first."
} else {
    Add-Check $checks "visible_history_wrapper" "pass" "Continuous PlanOnly and visible history wrappers exist." ""
}

$externalStorageRoot = ""
try {
    $driveE = Get-PSDrive -Name "E" -ErrorAction SilentlyContinue
    if ($driveE) {
        $externalStorageRoot = "E:\trading_mvp\slow-liquidity-history"
        Add-Check $checks "external_storage_target" "pass" "E: is available; recommended_output_root=$externalStorageRoot." ""
    } else {
        Add-Check $checks "external_storage_target" "warn" "E: is not available in this process; default project exports would be used unless a later visible runner receives an external output root." "Prefer external storage for heavy history artifacts."
    }
} catch {
    Add-Check $checks "external_storage_target" "warn" "Could not inspect E: drive: $($_.Exception.Message)" "Prefer external storage for heavy history artifacts."
}

Add-Check $checks "no_actual_run_contract" "pass" "This script emits a PlanOnly approval packet only; would_start=false; collect/replay/grid/paper/live blocked." ""

$candlesPerBasePerExchange = 0
$timeframeBudget = @()
foreach ($timeframe in $timeframeList) {
    $intervalSec = Get-IntervalSeconds -Timeframe $timeframe
    if ($intervalSec -le 0) {
        continue
    }
    $candlesPerDay = [Math]::Ceiling(86400.0 / [double]$intervalSec)
    $candlesForHistory = [int64]($candlesPerDay * $HistoryDays)
    $candlesPerBasePerExchange += $candlesForHistory
    $timeframeBudget += [ordered]@{
        timeframe = $timeframe
        interval_sec = $intervalSec
        candles_per_day = $candlesPerDay
        candles_per_base_per_exchange = $candlesForHistory
    }
}

$estimatedTotalCandles = [int64]($TargetBases * $targetExchanges.Count * $candlesPerBasePerExchange)
$estimatedRequestsAt1000 = [int64][Math]::Ceiling($estimatedTotalCandles / 1000.0)
$failedChecks = @($checks | Where-Object { [string]$_.status -eq "fail" })
$warnChecks = @($checks | Where-Object { [string]$_.status -eq "warn" })
$decision = if ($failedChecks.Count -eq 0) {
    "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL"
} else {
    "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_BLOCKED"
}

$nextStep = if ($decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL") {
    "Await explicit approval phrase '$approvalPhrase'. After approval, implement or run only a visible slow-liquidity OHLCV history collector/wrapper; keep replay/grid/live/API/paper-forward blocked until data-quality and fixed-signal gates pass."
} else {
    "Fix failed PlanOnly history data plan checks before any approval or collect."
}

$preflightFailedChecks = if ($preflight) {
    @($preflight.data_sufficiency_checks | Where-Object { [string]$_.status -ne "pass" } | ForEach-Object {
        [ordered]@{
            name = $_.name
            status = $_.status
            required = $_.required
            observed = $_.observed
            risk = $_.risk
        }
    })
} else {
    @()
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "trading_slow_liquidity_history_data_plan_planonly"
    decision = $decision
    selected_branch = "slow_liquidity_regime_breakout_retest"
    would_start = $false
    collect_allowed_now = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    research_only = $true
    public_data_only = $true
    requires_explicit_user_approval_for_actual_collect = $true
    actual_collect_command_emitted = $false
    explicit_approval_phrase = $approvalPhrase
    gate_status = if ($gate) { [string]$gate.status } else { "UNKNOWN" }
    gate_next_goal_decision_before = if ($gate) { [string]$gate.next_goal_decision } else { "" }
    preflight_artifact = $preflightPath
    preflight_decision = if ($preflight) { [string]$preflight.decision } else { "" }
    preflight_failed_checks = $preflightFailedChecks
    plan_checks = $checks
    failed_check_count = $failedChecks.Count
    warn_check_count = $warnChecks.Count
    universe = $universe
    collector_capability = $collectorCapability
    data_plan = [ordered]@{
        objective = "slow_liquidity_regime_breakout_retest_multi_week_public_ohlcv_history"
        exchanges = $targetExchanges
        quote = "USDT"
        timeframes = $timeframeList
        history_days = $HistoryDays
        target_bases = $TargetBases
        min_independent_events = $MinIndependentEvents
        min_history_days = 14
        preferred_history_days = 56
        row_budget = [ordered]@{
            timeframe_budget = $timeframeBudget
            candles_per_base_per_exchange = $candlesPerBasePerExchange
            estimated_total_candles = $estimatedTotalCandles
            estimated_requests_at_1000_candles = $estimatedRequestsAt1000
        }
        symbol_mapping_policy = [ordered]@{
            mexc = "BASEUSDT"
            gateio = "BASE_USDT"
            bitget = "BASEUSDT"
            skip_unmatched_or_no_data = $true
            preserve_no_data_or_delisted_rows = $true
        }
        liquidity_and_spread_proxy = [ordered]@{
            ohlcv_quote_volume_required = $true
            use_existing_ws_market_filter_as_initial_spread_sanity_only = $true
            require_later_bbo_or_conservative_spread_model_before_replay = $true
            current_ws_market_filter_is_not_sufficient_as_final_execution_proof = $true
        }
        storage = [ordered]@{
            prefer_external_drive = $true
            recommended_output_root = if ($externalStorageRoot) { $externalStorageRoot } else { "exports\trading-mvp\slow-liquidity-history" }
            keep_manifest_event_plan_stdout_stderr = $true
        }
    }
    validation_gates_after_collect = @(
        "schema_and_data_quality_gate",
        "derive_regime_retest_events_without_lookahead",
        "fixed_signal_contract_planonly",
        "no_grid_replay_validation",
        "chronological_oos",
        "walk_forward",
        "stress_costs_spread_latency_gaps",
        "economics_base_fee_vip0_no_volume",
        "paper_forward_readiness_only_if_research_passes"
    )
    blocked_until_future_gates_pass = @(
        "replay",
        "grid_search",
        "paper_forward",
        "live_orders",
        "api_keys",
        "leverage_or_margin"
    )
    recommended_next_actions = @(
        $nextStep,
        "Do not start a collector from this packet; first build or verify a visible slow-liquidity history wrapper if approval is given.",
        "Keep optimizing net expectancy after base fees and stress costs, not raw winrate."
    )
    commands = [ordered]@{
        rerun_this_plan = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Json"
        rerun_and_update_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -UpdateGate -Json"
        active_run_gate = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$gateChecker`""
        command_after_explicit_approval = "not emitted: implement/verify visible slow-liquidity history wrapper first"
    }
    output_path = $OutputPath
    next_step_after_ready = $nextStep
    gate_updated = $false
}

if ($UpdateGate -and $gate -and $decision -eq "SLOW_LIQUIDITY_HISTORY_DATA_PLAN_READY_AWAITING_EXPLICIT_APPROVAL") {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "slow_liquidity history data plan ready; history_days=$HistoryDays; timeframes=$($timeframeList -join ','); target_bases=$TargetBases; estimated_candles=$estimatedTotalCandles; actual collect still requires explicit approval."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_actual_collect" -Value $true
    Set-JsonProperty -Object $gateDoc -Name "requires_explicit_user_approval_for_public_probe" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "command_after_explicit_approval" -Value ""
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = "history_data_plan_ready_awaiting_explicit_approval"
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        history_days = $HistoryDays
        timeframes = $timeframeList
        target_bases = $TargetBases
        estimated_total_candles = $estimatedTotalCandles
        explicit_approval_phrase = $approvalPhrase
        next_step_required = "await_explicit_approval_for_visible_history_collect_implementation"
    })
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_plan_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_plan_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_plan_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_history_data_plan_approval_phrase" -Value $approvalPhrase
    $gateDoc | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    Set-JsonProperty -Object $result -Name "gate_updated" -Value $true
}

Save-Result -Payload $result
