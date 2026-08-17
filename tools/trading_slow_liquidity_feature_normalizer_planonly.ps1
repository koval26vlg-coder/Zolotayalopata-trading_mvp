param(
    [string]$HistoryJsonlPath = "",
    [string]$HistoryManifestPath = "",
    [string]$FixedSignalPath = "",
    [string]$QualityPath = "",
    [string]$OutputPath = "",
    [int]$MinIndependentEvents = 100,
    [int]$MinEventBases = 8,
    [int]$MinEventExchanges = 2,
    [double]$MaxSingleBaseEventFraction = 0.25,
    [int]$ClusterWindowSec = 43200,
    [double]$TrainFraction = 0.70,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\slow_liquidity_feature_normalizer.py"
$readyDecision = "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_READY_FOR_FIXED_REPLAY_VALIDATION"
$rejectedDecision = "SLOW_LIQUIDITY_FEATURE_NORMALIZER_PLANONLY_REJECTED_INSUFFICIENT_EVENTS"

if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\analysis\slow_liquidity_feature_normalizer_planonly_$timestamp.json"
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

    Write-Host "Slow-liquidity feature normalizer PlanOnly" -ForegroundColor Cyan
    Write-Host "Decision: $($Payload.decision)"
    Write-Host "Replay allowed now: $($Payload.replay_allowed_now)"
    Write-Host "Output: $OutputPath"
}

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "slow_liquidity_feature_normalizer_planonly"
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
if (-not $FixedSignalPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_fixed_compression_v1_plan_output_path) {
    $FixedSignalPath = [string]$gateDoc.last_slow_liquidity_fixed_compression_v1_plan_output_path
}
if (-not $FixedSignalPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_fixed_signal_plan_output_path) {
    $FixedSignalPath = [string]$gateDoc.last_slow_liquidity_fixed_signal_plan_output_path
}
if (-not $QualityPath -and $gateDoc -and [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path) {
    $QualityPath = [string]$gateDoc.last_slow_liquidity_history_data_quality_output_path
}

$HistoryJsonlPath = Resolve-RepoPath $HistoryJsonlPath
$HistoryManifestPath = Resolve-RepoPath $HistoryManifestPath
$FixedSignalPath = Resolve-RepoPath $FixedSignalPath
$QualityPath = Resolve-RepoPath $QualityPath
$OutputPath = Resolve-RepoPath $OutputPath

foreach ($requiredPath in @($HistoryJsonlPath, $HistoryManifestPath, $FixedSignalPath, $QualityPath, $modulePath)) {
    if (-not $requiredPath -or -not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path not found: $requiredPath"
    }
}

$gateAllowsNormalizer = [bool](
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_SIGNAL_PLANONLY_READY_FOR_FEATURE_NORMALIZER") -or
    ([string]$gate.next_goal_decision -eq "SLOW_LIQUIDITY_FIXED_V1_COMPRESSION_PLANONLY_READY_FOR_FEATURE_NORMALIZER") -or
    ([string]$gate.next_goal_decision -eq $rejectedDecision) -or
    (
        $gateDoc -and
        $gateDoc.strategy_branch_status -and
        [string]$gateDoc.strategy_branch_status.branch -eq "slow_liquidity_regime_breakout_retest" -and
        [string]$gateDoc.strategy_branch_status.verdict -in @("fixed_signal_planonly_ready_for_feature_normalizer", "fixed_compression_v1_planonly_ready_for_feature_normalizer", "feature_normalizer_rejected_insufficient_events")
    )
)
if (-not $gateAllowsNormalizer) {
    throw "slow-liquidity feature normalizer is not the active gate step. Current next_goal_decision=$($gate.next_goal_decision)"
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
    "--fixed-signal", $FixedSignalPath,
    "--quality", $QualityPath,
    "--output", $OutputPath,
    "--min-independent-events", [string]$MinIndependentEvents,
    "--min-event-bases", [string]$MinEventBases,
    "--min-event-exchanges", [string]$MinEventExchanges,
    "--max-single-base-event-fraction", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.########}", $MaxSingleBaseEventFraction)),
    "--cluster-window-sec", [string]$ClusterWindowSec,
    "--train-fraction", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.########}", $TrainFraction))
)

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "slow_liquidity_feature_normalizer.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $ready = [bool]$result.replay_allowed_now
    $isScaledCompressionV1 = [string]$result.fixed_contract.signal.compression_metric -eq "range_width_over_atr_sqrt_lookback"
    $nextStep = if ($ready) {
        "Run one fixed slow-liquidity replay-validation PlanOnly from the feature normalizer artifact. No grid/live/API/paper-forward; keep parameters frozen."
    } else {
        if ($isScaledCompressionV1) {
            "Do not replay/grid. Reject the scaled-compression v1 contract or define a materially new hypothesis; do not tune its threshold from this sample."
        } else {
            "Do not replay/grid. Reject or rescope slow-liquidity fixed v0, or collect a larger independent 1h/4h history sample before retesting."
        }
    }
    $verdict = if ($ready) {
        "feature_normalizer_ready_for_fixed_replay_validation"
    } else {
        if ($isScaledCompressionV1) { "feature_normalizer_v1_rejected_insufficient_events" } else { "feature_normalizer_rejected_insufficient_events" }
    }
    $events = [int]$result.event_set.independent_events
    $eventBases = [int]$result.event_set.event_bases
    $eventExchanges = [int]$result.event_set.event_exchanges

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Slow-liquidity feature normalizer PlanOnly completed. independent_events=$events, event_bases=$eventBases, event_exchanges=$eventExchanges, replay_allowed=$ready."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $ready
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_feature_normalizer_at" -Value ([string]$result.generated_at)
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_feature_normalizer_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_feature_normalizer_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_feature_normalizer_events" -Value $events
    Set-JsonProperty -Object $gateDoc -Name "last_slow_liquidity_feature_normalizer_event_bases" -Value $eventBases
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "slow_liquidity_regime_breakout_retest"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        replay_allowed_now = $ready
        grid_allowed = $false
        paper_forward_allowed = $false
        strategy_accepted = $false
        signal_version = if ($isScaledCompressionV1) { "scaled_compression_v1" } else { "fixed_v0" }
        independent_events = $events
        event_bases = $eventBases
        event_exchanges = $eventExchanges
        next_step_required = [string]$result.required_next_step
    })
    $gateDoc | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 18
    exit 0
}

Write-Host "Slow-liquidity feature normalizer PlanOnly" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Independent events: $($result.event_set.independent_events)"
Write-Host "Event bases: $($result.event_set.event_bases)"
Write-Host "Event exchanges: $($result.event_set.event_exchanges)"
Write-Host "Replay allowed now: $($result.replay_allowed_now)"
Write-Host "Output: $OutputPath"
Write-Host ""
Write-Host "Next valid moves" -ForegroundColor Yellow
foreach ($move in @($result.next_valid_moves)) {
    Write-Host "  - $move"
}
