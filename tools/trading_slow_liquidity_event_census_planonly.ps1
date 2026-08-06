param(
    [string]$HistoryJsonlPath = "",
    [string]$HistoryManifestPath = "",
    [string]$RescopePath = "",
    [string]$QualityPath = "",
    [string]$OutputPath = "",
    [int]$MinIndependentEvents = 100,
    [int]$MinEventBases = 8,
    [int]$MinEventExchanges = 2,
    [double]$MaxSingleBaseEventFraction = 0.25,
    [int]$ClusterWindowSec = 43200,
    [double]$MinTargetGeometryBps = 300.0,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_event_census.py"
$readyDecision = "SLOW_LIQUIDITY_FIXED_V0_REJECTED_NO_EVENT_BASE_RATE_READY_FOR_EVENT_CENSUS_V1_PLANONLY"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_event_census_v1_planonly_$timestamp.json"
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

    Write-Host "Slow-liquidity event-census v1 PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Independent events: $($Payload.event_census.independent_events)"
    Write-Host "Top family: $($Payload.event_census.top_family)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "slow_liquidity_event_census_v1_planonly"
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
if (-not $HistoryJsonlPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_history_collect_output_path) {
    $HistoryJsonlPath = [string]$gateDoc.last_slow_liquidity_history_collect_output_path
}
if (-not $HistoryManifestPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_history_collect_manifest_path) {
    $HistoryManifestPath = [string]$gateDoc.last_slow_liquidity_history_collect_manifest_path
}
if (-not $RescopePath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_rescope_plan_output_path) {
    $RescopePath = [string]$gateDoc.last_slow_liquidity_rescope_plan_output_path
}
if (-not $QualityPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path) {
    $QualityPath = [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path
}

$HistoryJsonlPath = Resolve-RepoPath $HistoryJsonlPath
$HistoryManifestPath = Resolve-RepoPath $HistoryManifestPath
$RescopePath = Resolve-RepoPath $RescopePath
$QualityPath = Resolve-RepoPath $QualityPath
$OutputPath = Resolve-RepoPath $OutputPath

foreach ($requiredPath in @($HistoryJsonlPath, $HistoryManifestPath, $RescopePath, $QualityPath, $modulePath)) {
    if (-not $requiredPath -or -not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath"
    }
}

$gateAllowsCensus = [bool](
    ([string]$gate.next_goal_decision -eq $readyDecision) -or
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_READY_FOR_FIXED_V1_PLANONLY") -or
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_EVENT_CENSUS_V1_REJECTED_INSUFFICIENT_EVENT_BASE_RATE") -or
    (
        $gateDoc -and
        $gateDoc.strategy_branch_status -and
        [string]$gateDoc.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gateDoc.strategy_branch_status.verdict -in @("fixed_v0_rejected_no_event_base_rate_ready_for_event_census_v1", "event_census_v1_accepted_ready_for_fixed_v1_planonly", "event_census_v1_rejected_insufficient_event_base_rate")
    )
)
if (-not $gateAllowsCensus) {
    throw "slow-liquidity event-census v1 is not the active gate step. Current next_goal_decision=$($gate.next_goal_decision)"
}

$pythonCandidates = @(
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $python = $pythonCmd.Source
    }
}
if (-not $python) {
    throw "Python runtime not found."
}

$argsList = @(
    $modulePath,
    "--history-jsonl", $HistoryJsonlPath,
    "--history-manifest", $HistoryManifestPath,
    "--rescope", $RescopePath,
    "--quality", $QualityPath,
    "--output", $OutputPath,
    "--min-independent-events", [string]$MinIndependentEvents,
    "--min-event-bases", [string]$MinEventBases,
    "--min-event-exchanges", [string]$MinEventExchanges,
    "--max-single-base-event-fraction", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.########}", $MaxSingleBaseEventFraction)),
    "--cluster-window-sec", [string]$ClusterWindowSec,
    "--min-target-geometry-bps", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.########}", $MinTargetGeometryBps))
)

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "slow_liquidity_event_census.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $accepted = [string]$decision -eq "SLOW_LIQUIDITY_EVENT_CENSUS_V1_ACCEPTED_READY_FOR_FIXED_V1_PLANONLY"
    $independentEvents = [int]$result.event_census.independent_events
    $topFamily = [string]$result.event_census.top_family
    $acceptedFamilies = @($result.event_census.accepted_families | ForEach-Object { [string]$_ })
    $nextStep = if ($accepted) {
        "Build fixed v1 PlanOnly for top slow-liquidity family '$topFamily'. Do not replay/grid/live/API/paper-forward until fixed v1 contract exists."
    } else {
        "Reject slow_liquidity_regime_breakout_retest on event-census evidence and select another structural PlanOnly branch. Do not collect larger history under v0."
    }
    $verdict = if ($accepted) {
        "event_census_v1_accepted_ready_for_fixed_v1_planonly"
    } else {
        "event_census_v1_rejected_insufficient_event_base_rate"
    }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "slow-liquidity event-census v1 completed. independent_events=$independentEvents, top_family=$topFamily, accepted_families=$($acceptedFamilies -join ',')."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_event_census_at" -Value ([string]$result.generated_at)
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_event_census_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_event_census_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_event_census_events" -Value $independentEvents
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_event_census_top_family" -Value $topFamily
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        independent_events = $independentEvents
        top_family = $topFamily
        accepted_families = $acceptedFamilies
        next_step_required = if ($accepted) { "build_fixed_v1_signal_planonly" } else { "select_next_structural_branch_planonly" }
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

Save-Result -Payload $result
