param(
    [string]$FeatureNormalizerPath = "",
    [string]$QualityPath = "",
    [string]$OutputPath = "",
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$rejectedDecision = "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS"
$decision = "SLOW_LIQUIDITY_FIXED_V0_REJECTED_NO_EVENT_BASE_RATE_READY_FOR_EVENT_CENSUS_V1_PLANONLY"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_rescope_planonly_$timestamp.json"
}

function Resolve-RepoPath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
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
    $Payload | ConvertTo-Json -Depth 18 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if ($Json) {
        $Payload | ConvertTo-Json -Depth 18
        return
    }

    Write-Host "Slow-liquidity rescope PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "v0 verdict: $($Payload.v0_verdict)"
    Write-Host "Next: $($Payload.next_step_after_ready)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "slow_liquidity_rescope_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        selected_branch = "slow_liquidity_regime_breakout_retest"
        would_start = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
        output_path = $OutputPath
    }
    Save-Result -Payload $blocked
    exit 0
}

$gateDoc = if (Test-Path -LiteralPath $gatePath) { Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json } else { $null }
if (-not $FeatureNormalizerPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_feature_normalizer_output_path) {
    $FeatureNormalizerPath = [string]$gateDoc.last_slow_liquidity_feature_normalizer_output_path
}
if (-not $QualityPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path) {
    $QualityPath = [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path
}

$FeatureNormalizerPath = Resolve-RepoPath $FeatureNormalizerPath
$QualityPath = Resolve-RepoPath $QualityPath
$OutputPath = Resolve-RepoPath $OutputPath

foreach ($requiredPath in @($FeatureNormalizerPath, $QualityPath)) {
    if (-not $requiredPath -or -not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath"
    }
}

$normalizer = Get-Content -Raw -LiteralPath $FeatureNormalizerPath | ConvertFrom-Json
$quality = Get-Content -Raw -LiteralPath $QualityPath | ConvertFrom-Json

if ([string]$normalizer.decision -ne $rejectedDecision) {
    throw "Feature normalizer must be rejected before rescope. decision=$($normalizer.decision)"
}

$rawEvents = [int]$normalizer.event_set.raw_candidate_events
$independentEvents = [int]$normalizer.event_set.independent_events
$eventBases = [int]$normalizer.event_set.event_bases
$eventExchanges = [int]$normalizer.event_set.event_exchanges
$cleanBases = @($normalizer.fixed_contract.clean_bases | ForEach-Object { [string]$_ } | Where-Object { $_ } | Sort-Object -Unique)
if ($cleanBases.Count -eq 0 -and $quality.clean_markets) {
    $cleanBases = @($quality.clean_markets.two_exchange_full_coverage_1h4h_bases | ForEach-Object { [string]$_ } | Where-Object { $_ } | Sort-Object -Unique)
}

$v0Verdict = if ($rawEvents -eq 0 -and $independentEvents -eq 0) {
    "REJECTED_NO_EVENT_BASE_RATE"
} else {
    "REJECTED_INSUFFICIENT_INDEPENDENT_EVENT_BASE_RATE"
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    mode = "slow_liquidity_rescope_planonly"
    decision = $decision
    selected_branch = "slow_liquidity_regime_breakout_retest"
    v0_verdict = $v0Verdict
    would_start = $false
    research_only = $true
    strategy_accepted = $false
    replay_allowed_now = $false
    grid_allowed_now = $false
    paper_forward_allowed = $false
    live_orders = $false
    api_keys = $false
    leverage_or_margin = $false
    rescope_rationale = @(
        "fixed v0 produced raw_candidate_events=$rawEvents and independent_events=$independentEvents on accepted 56d 1h/4h data",
        "larger history under the same v0 is not justified until an event family shows base-rate on current history",
        "base/VIP0 cost hurdle remains unchanged; do not lower target geometry to manufacture trades",
        "next work is event-census only, not PnL replay or grid"
    )
    inputs = [ordered]@{
        feature_normalizer_path = $FeatureNormalizerPath
        quality_path = $QualityPath
        history_jsonl_path = [string]$normalizer.inputs.history_jsonl_path
        history_manifest_path = [string]$normalizer.inputs.history_manifest_path
        history_run_id = [string]$normalizer.inputs.history_run_id
    }
    v0_event_set = [ordered]@{
        raw_candidate_events = $rawEvents
        independent_events = $independentEvents
        event_bases = $eventBases
        event_exchanges = $eventExchanges
        reasons = @($normalizer.reasons | ForEach-Object { [string]$_ })
        warnings = @($normalizer.warnings | ForEach-Object { [string]$_ })
    }
    v1_event_census_plan = [ordered]@{
        purpose = "count event base-rate before any replay or new data collection"
        clean_bases = $cleanBases
        required_timeframes = @("1h", "4h")
        disabled_timeframes = @("15m")
        candidate_families = @(
            "range_breakout_without_retest_v1",
            "volatility_expansion_continuation_v1",
            "liquidity_shock_reclaim_long_v1",
            "four_hour_compression_breakout_v1"
        )
        acceptance_before_replay = [ordered]@{
            min_independent_events = 100
            min_event_bases = 8
            min_event_exchanges = 2
            max_single_base_event_fraction = 0.25
            min_target_geometry_bps = 300.0
        }
        blocked_until_census_passes = @(
            "larger_history_collect",
            "replay_validation",
            "grid_search",
            "paper_forward",
            "live_orders",
            "api_keys"
        )
    }
    next_step_after_ready = "Run slow-liquidity event-census v1 PlanOnly on existing 56d 1h/4h history. If no family reaches event base-rate, reject the slow-liquidity branch; do not collect larger history under v0."
    next_valid_moves = @(
        "Run slow-liquidity event-census v1 PlanOnly on existing history.",
        "If a family passes event base-rate, build a fixed v1 signal PlanOnly before replay.",
        "If no family passes event base-rate, reject slow_liquidity_regime_breakout_retest and select a different structural branch."
    )
    blocked_actions = @(
        "grid_search",
        "replay_validation",
        "paper_forward",
        "live_orders",
        "api_keys",
        "leverage_or_margin",
        "larger_history_collect_for_v0"
    )
    output_path = $OutputPath
}

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "slow_liquidity fixed v0 rejected as $v0Verdict; raw_candidate_events=$rawEvents, independent_events=$independentEvents. Next is event-census v1 PlanOnly on existing data; no replay/grid/collect/live/API."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $result.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $result.next_step_after_ready
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_rescope_plan_at" -Value $result.generated_at
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_rescope_plan_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_rescope_plan_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = "fixed_v0_rejected_no_event_base_rate_ready_for_event_census_v1"
        decision_source = $OutputPath
        selected_at = $result.generated_at
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        raw_candidate_events = $rawEvents
        independent_events = $independentEvents
        next_step_required = "run_slow_liquidity_event_census_v1_planonly"
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result["gate_updated"] = $true
} else {
    $result["gate_updated"] = $false
}

Save-Result -Payload $result
