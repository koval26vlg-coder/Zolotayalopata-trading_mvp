param(
    [string]$NormalizerPath = "",
    [string]$OutputPath = "",
    [double]$NotionalQuote = 100.0,
    [double]$EntryDelayHours = 6.0,
    [double]$HoldHours = 24.0,
    [double]$TriggerBps = 200.0,
    [double]$FeeBpsPerSide = 10.0,
    [double]$SlippageBpsPerSide = 5.0,
    [double]$StressFeeMultiplier = 1.5,
    [double]$StressSlippageMultiplier = 2.0,
    [double]$StressHaircutBps = 50.0,
    [int]$MinTrades = 10,
    [int]$MinOosTrades = 3,
    [double]$MinProfitFactor = 1.2,
    [double]$MinWalkForwardPassRatio = 0.60,
    [int]$WalkForwardWindows = 4,
    [double]$TrainFraction = 0.70,
    [switch]$UpdateGate,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gateChecker = Join-Path $repoRoot "tools\check_active_run_gate.ps1"
$gatePath = Join-Path $repoRoot "docs\agent-log\active-run-gate.json"
$modulePath = Join-Path $repoRoot "trading_mvp\src\listing_event_replay.py"

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

$gate = & pwsh -NoProfile -ExecutionPolicy Bypass -File $gateChecker -Json | ConvertFrom-Json
if ([string]$gate.status -in @("RUNNING", "STOPPED_INCOMPLETE")) {
    $blocked = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        mode = "listing_event_replay_planonly"
        decision = "BLOCKED_BY_ACTIVE_RUN_GATE"
        would_start = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed_now = $false
        paper_forward_allowed = $false
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        reason = "Active run gate is $($gate.status); only status/resume work is allowed."
        gate_status = $gate.status
    }
    if ($Json) {
        $blocked | ConvertTo-Json -Depth 8
    } else {
        Write-Host "Blocked by active run gate: $($gate.status)" -ForegroundColor Yellow
    }
    exit 0
}

$rawGate = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
if (-not $NormalizerPath -and ($rawGate.PSObject.Properties.Name -contains "last_listing_event_normalizer_output_path")) {
    $candidate = [string]$rawGate.last_listing_event_normalizer_output_path
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        $NormalizerPath = $candidate
    }
}
if (-not $NormalizerPath -or (-not (Test-Path -LiteralPath $NormalizerPath))) {
    throw "Normalizer path not found: $NormalizerPath"
}
if (-not [bool]$rawGate.replay_allowed) {
    throw "Gate replay_allowed=false; do not run listing-event replay PlanOnly."
}
if ([string]$rawGate.next_goal_decision -ne "LISTING_EVENT_NORMALIZER_PLANONLY_READY_FOR_EVENT_REPLAY_PLANONLY") {
    throw "Unexpected gate next_goal_decision=$($rawGate.next_goal_decision)"
}
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $repoRoot "exports\trading-mvp\backtests\listing_event_replay_planonly_$timestamp.json"
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
    "--normalizer", $NormalizerPath,
    "--output", $OutputPath,
    "--notional-quote", $NotionalQuote,
    "--entry-delay-hours", $EntryDelayHours,
    "--hold-hours", $HoldHours,
    "--trigger-bps", $TriggerBps,
    "--fee-bps-per-side", $FeeBpsPerSide,
    "--slippage-bps-per-side", $SlippageBpsPerSide,
    "--stress-fee-multiplier", $StressFeeMultiplier,
    "--stress-slippage-multiplier", $StressSlippageMultiplier,
    "--stress-haircut-bps", $StressHaircutBps,
    "--min-trades", $MinTrades,
    "--min-oos-trades", $MinOosTrades,
    "--min-profit-factor", $MinProfitFactor,
    "--min-walk-forward-pass-ratio", $MinWalkForwardPassRatio,
    "--walk-forward-windows", $WalkForwardWindows,
    "--train-fraction", $TrainFraction
)

$raw = & $python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "listing_event_replay.py failed with exit code $LASTEXITCODE"
}
$result = $raw | ConvertFrom-Json

if ($UpdateGate) {
    $gateDoc = Get-Content -Raw -LiteralPath $gatePath | ConvertFrom-Json
    $decision = [string]$result.decision
    $candidate = [bool]$result.research_acceptance.robust_candidate
    $nextStep = if ($candidate) {
        "Build independent listing-event validation packet and paper-forward readiness gates. No grid/live/API/paper-forward."
    } else {
        "Reject this fixed listing_event_drift_reversal setup on current sample; select a new non-HFT branch or collect larger independent listing-event sample before retesting. No grid/live/API/paper-forward."
    }
    $verdict = if ($candidate) { "replay_planonly_candidate_requires_validation" } else { "replay_planonly_rejected" }

    Set-JsonProperty -Object $gateDoc -Name "updated_at" -Value ((Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz"))
    Set-JsonProperty -Object $gateDoc -Name "next_goal_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "next_goal_reason" -Value "Listing-event replay PlanOnly completed. trades=$($result.summary.trades), expectancy=$($result.summary.expectancy_quote), oos_expectancy=$($result.oos.summary.expectancy_quote), stress_expectancy=$($result.stress.summary.expectancy_quote), robust_candidate=$candidate."
    Set-JsonProperty -Object $gateDoc -Name "next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "raw_gate_next_step_after_ready" -Value $nextStep
    Set-JsonProperty -Object $gateDoc -Name "replay_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "collect_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "grid_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "paper_forward_allowed" -Value $false
    Set-JsonProperty -Object $gateDoc -Name "strategy_branch_status" -Value ([ordered]@{
        branch = "listing_event_drift_reversal"
        verdict = $verdict
        decision_source = $OutputPath
        selected_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        previous_branch = "cross_venue_spot_dislocation_inventory_rebalance"
        previous_verdict = "rejected_no_net_edge_after_base_fees"
        live_orders = $false
        api_keys = $false
        leverage_or_margin = $false
        collect_allowed_now = $false
        replay_allowed_now = $false
        grid_allowed = $false
        paper_forward_allowed = $false
        next_branch_required = (-not $candidate)
        next_step_required = if ($candidate) { "independent_listing_event_validation_packet" } else { "select_next_non_hft_branch_or_larger_independent_listing_sample" }
    })
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_replay_at" -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_replay_output_path" -Value $OutputPath
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_replay_decision" -Value $decision
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_replay_trades" -Value ([int]$result.summary.trades)
    Set-JsonProperty -Object $gateDoc -Name "last_listing_event_replay_expectancy_quote" -Value ([double]$result.summary.expectancy_quote)
    $gateDoc | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $gatePath -Encoding UTF8
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $true
} else {
    $result | Add-Member -NotePropertyName "gate_updated" -NotePropertyValue $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 14
    exit 0
}

Write-Host "Listing event replay PlanOnly" -ForegroundColor Cyan
Write-Host "Decision: $($result.decision)"
Write-Host "Trades: $($result.summary.trades)"
Write-Host "Expectancy quote: $($result.summary.expectancy_quote)"
Write-Host "OOS expectancy quote: $($result.oos.summary.expectancy_quote)"
Write-Host "Stress expectancy quote: $($result.stress.summary.expectancy_quote)"
Write-Host "Output: $OutputPath"
